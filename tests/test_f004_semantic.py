"""F-004 semantic-memory tests (vector half: Qdrant + embeddings).

Uses a deterministic FakeEmbedder (token bag-of-words → vector, so cosine similarity tracks token
overlap) + an in-memory Qdrant, so these run fast without downloading a model. True semantic
(synonym) behaviour is proven separately by a live check against the real embedding model.

Maps to TC ids: FR-004-04 (embedding_ref/1:1), FR-004-08/33 (index on store, remove on supersede),
FR-004-10 (semantic recall), FR-004-36 / NFR-004-16 (user-filtered search, isolation),
FR-004-40 / NFR-004-07 (degrade to keyword when the vector store is down).
"""
from __future__ import annotations

import hashlib

import pytest

from services.bot.domain import memory as mem
from services.bot.domain.fact_extraction import MemoryOps, NewFact
from services.bot.domain.users import get_or_create_user
from services.bot.domain.vector_store import MemoryIndex, VectorStoreUnavailable
from services.bot.models import FactStatus, UserFact

_DIM = 512


class FakeEmbedder:
    """Deterministic bag-of-words embedder: shared content tokens → high cosine similarity.

    Large dim to avoid hash collisions; short/common tokens dropped so stopwords don't add noise
    (a stand-in for real semantic embeddings, used only to test the plumbing deterministically).
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * _DIM
            for tok in t.lower().split():
                if len(tok) <= 2:
                    continue
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16) % _DIM
                vec[h] += 1.0
            out.append(vec)
        return out


def _index() -> MemoryIndex:
    from qdrant_client import QdrantClient

    return MemoryIndex(QdrantClient(":memory:"), FakeEmbedder(), collection="test_facts")


async def _user(db, tg_id=5001):
    user, _ = await get_or_create_user(db, telegram_id=tg_id, locale="ru")
    return user


async def _fact(db, user_id, category, content):
    f = UserFact(user_id=user_id, category=category, content=content, status=FactStatus.active)
    db.add(f)
    await db.flush()
    return f


# ── FR-004-08/10 — index on store, semantic recall ─────────────────────────────────────────────


async def test_fr_004_10_01_semantic_recall_returns_relevant_fact(db):
    """TC-FR-004-10-01 — recall_relevant returns the fact whose content overlaps the query."""
    user = await _user(db)
    idx = _index()
    f_wed = await _fact(db, user.id, "family", "his sister wedding june")
    f_job = await _fact(db, user.id, "work", "he works design studio berlin")
    idx.index_fact(user.id, f_wed.id, f_wed.content)
    idx.index_fact(user.id, f_job.id, f_job.content)

    hits = await mem.recall_relevant(db, user.id, "tell me about the wedding", idx, limit=1)
    assert len(hits) == 1 and hits[0].id == f_wed.id


async def test_fr_004_36_01_search_filtered_by_user(db):
    """TC-NFR-004-16 / FR-004-36 — search is user-filtered: A never gets B's point, same content."""
    a = await _user(db, tg_id=6001)
    b = await _user(db, tg_id=6002)
    idx = _index()
    fa = await _fact(db, a.id, "work", "he works at a bakery")
    fb = await _fact(db, b.id, "work", "he works at a bakery")
    idx.index_fact(a.id, fa.id, fa.content)
    idx.index_fact(b.id, fb.id, fb.content)

    a_ids = idx.search(a.id, "works bakery", k=10)
    assert a_ids == [fa.id]  # only A's point, never B's despite identical content


async def test_fr_004_33_01_remove_on_supersede(db):
    """TC-FR-004-33 — a superseded fact's point is removed, so it's not semantically recalled."""
    user = await _user(db, tg_id=6100)
    idx = _index()
    old = await _fact(db, user.id, "work", "he works company alpha")
    idx.index_fact(user.id, old.id, old.content)
    # supersede via apply_memory_ops with the index → point removed, new one added
    await mem.apply_memory_ops(
        db, user.id,
        MemoryOps(add=[NewFact("work", "he works company beta")], supersede=[old.id]),
        index=idx,
    )
    ids = idx.search(user.id, "he works company", k=10)
    assert old.id not in ids  # the superseded point is gone


# ── FR-004-04/08 — apply_memory_ops indexes + sets embedding_ref ────────────────────────────────


async def test_fr_004_04_01_apply_ops_indexes_and_sets_ref(db):
    """TC-FR-004-04-01 — a fact stored with an index is embedded and carries an embedding_ref."""
    user = await _user(db, tg_id=6200)
    idx = _index()
    inserted = await mem.apply_memory_ops(
        db, user.id, MemoryOps(add=[NewFact("preferences", "he loves jazz music")]), index=idx)
    assert inserted[0].embedding_ref == str(inserted[0].id)  # SQL row ↔ vector point 1:1
    assert idx.search(user.id, "jazz music", k=5) == [inserted[0].id]


# ── FR-004-40 / NFR-004-07 — degrade to keyword when the vector store is down ───────────────────


async def test_fr_004_40_01_recall_degrades_to_keyword(db):
    """TC-FR-004-40-01 — if the vector index raises, recall falls back to keyword recall."""
    user = await _user(db, tg_id=6300)
    await _fact(db, user.id, "work", "he works at a design studio")

    class DownIndex:
        def search(self, *a, **k):
            raise VectorStoreUnavailable("qdrant down")

    hits = await mem.recall_relevant(db, user.id, "как там работа в студии?", DownIndex(), limit=5)
    # keyword fallback still finds the studio fact (buzzword "студи" overlaps)
    assert any("design studio" in f.content for f in hits)


async def test_fr_004_40_02_indexing_failure_keeps_sql(db):
    """TC-FR-004-40 — if indexing fails, the SQL fact still persists (degrade, no data loss)."""
    user = await _user(db, tg_id=6400)

    class DownIndex:
        def index_fact(self, *a, **k):
            raise VectorStoreUnavailable("qdrant down")
        def remove_facts(self, *a, **k):
            raise VectorStoreUnavailable("qdrant down")

    inserted = await mem.apply_memory_ops(
        db, user.id, MemoryOps(add=[NewFact("work", "he is a teacher")]), index=DownIndex())
    assert len(inserted) == 1  # SQL write stood despite the index failure
    active = await mem.active_facts(db, user.id)
    assert any("teacher" in f.content for f in active)
