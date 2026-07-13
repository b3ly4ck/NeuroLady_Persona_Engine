"""User-fact memory store + recall (F-004, Postgres-only slice).

Owns the relational side of the memory system: storing categorized `USER_FACT` rows with
supersession/dedup (FR-004-06/07/11/12/15), and recalling a user's active facts ranked by
relevance to the current message (FR-004-09/13/24/25/26). All reads/writes are scoped to the acting
user (FR-004-36 / NFR-004-03). The semantic (Qdrant) half is deferred: ranking here is a
keyword-overlap + recency + confidence heuristic rather than embedding similarity.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain.fact_extraction import MemoryOps
from services.bot.domain.vector_store import MemoryIndex, VectorStoreUnavailable
from services.bot.models import FactStatus, UserFact

log = logging.getLogger(__name__)

# How many recalled facts are fused into the reply context (FR-004-26 — bounded, don't dominate).
RECALL_LIMIT = 6
_TOKEN_RE = re.compile(r"[^\wа-яё]+", re.IGNORECASE | re.UNICODE)
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "i", "you", "he", "she", "it", "to", "of", "and",
    "и", "в", "на", "я", "ты", "он", "она", "это", "что", "как", "мне", "тебя", "не", "с",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.split(text.lower()) if len(t) > 2 and t not in _STOPWORDS}


async def active_facts(db: AsyncSession, user_id: int) -> list[UserFact]:
    """All of a user's active (non-superseded) facts, newest first. Scoped to the user (FR-004-36)."""
    stmt = (
        select(UserFact)
        .where(UserFact.user_id == user_id, UserFact.status == FactStatus.active)
        .order_by(UserFact.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def apply_memory_ops(
    db: AsyncSession, user_id: int, ops: MemoryOps, index: MemoryIndex | None = None
) -> list[UserFact]:
    """Apply extraction results: supersede contradicted facts, dedup, insert new ones.

    Returns the newly-inserted facts. Supersession and dedup are scoped to the acting user so one
    user's memory can never touch another's (FR-004-36). When a vector `index` is given, new facts
    are embedded/indexed and superseded ones removed from it (FR-004-08/33); an index failure is
    logged and swallowed so the SQL write still stands (degrade — FR-004-40).
    """
    existing = await active_facts(db, user_id)
    existing_ids = {f.id for f in existing}
    existing_norm = {(f.category, f.content.strip().lower()) for f in existing}

    # 1. Insert new facts (skipping exact duplicates of an existing active fact — FR-004-15).
    inserted: list[UserFact] = []
    for nf in ops.add:
        key = (nf.category, nf.content.strip().lower())
        if key in existing_norm:
            continue  # dedup: same fact already stored
        fact = UserFact(
            user_id=user_id, category=nf.category, content=nf.content.strip(),
            status=FactStatus.active, confidence=nf.confidence,
        )
        db.add(fact)
        inserted.append(fact)
        existing_norm.add(key)
    await db.flush()  # assign ids to inserted facts

    # 2. Supersede contradicted facts (only this user's active facts — FR-004-11/12).
    replacement_id = inserted[0].id if inserted else None
    superseded_ids: list[int] = []
    for fid in ops.supersede:
        if fid not in existing_ids:
            continue
        fact = await db.get(UserFact, fid)
        if fact is not None and fact.user_id == user_id and fact.status == FactStatus.active:
            fact.status = FactStatus.superseded
            fact.superseded_by = replacement_id
            fact.updated_at = datetime.now(timezone.utc)
            superseded_ids.append(fid)
    await db.flush()

    # 3. Vector half: index new facts, drop superseded points (off the SQL correctness path).
    if index is not None:
        try:
            for fact in inserted:
                await asyncio.to_thread(index.index_fact, user_id, fact.id, fact.content)
                fact.embedding_ref = str(fact.id)  # SQL row ↔ vector point 1:1 (FR-004-04)
            if superseded_ids:
                await asyncio.to_thread(index.remove_facts, superseded_ids)
            await db.flush()
        except VectorStoreUnavailable as exc:
            log.warning("vector indexing skipped (store unavailable): %s", exc)  # degrade
    return inserted


def _score(fact: UserFact, query_tokens: set[str], newest_id: int) -> float:
    """Relevance score: keyword overlap (primary) + recency + confidence (FR-004-13/25)."""
    overlap = len(_tokens(fact.content) & query_tokens)
    recency = (fact.id / newest_id) if newest_id else 0.0  # 0..1, newer → higher
    return overlap * 10.0 + recency * 2.0 + fact.confidence


async def recall_facts(
    db: AsyncSession, user_id: int, message: str, limit: int = RECALL_LIMIT
) -> list[UserFact]:
    """Return up to `limit` of the user's active facts most relevant to `message`.

    Ranked by keyword overlap, then recency and confidence (FR-004-09/13/25). Bounded by `limit`
    so irrelevant facts can't dominate the context (FR-004-26).
    """
    facts = await active_facts(db, user_id)
    if not facts:
        return []
    query_tokens = _tokens(message)
    newest_id = max(f.id for f in facts)
    ranked = sorted(facts, key=lambda f: _score(f, query_tokens, newest_id), reverse=True)
    return ranked[:limit]


async def recall_relevant(
    db: AsyncSession,
    user_id: int,
    message: str,
    index: MemoryIndex | None = None,
    limit: int = RECALL_LIMIT,
) -> list[UserFact]:
    """Recall the user's facts most relevant to `message`, preferring semantic search.

    With a vector `index`, embeds the message and retrieves by cosine similarity, filtered to this
    user (FR-004-10/28/36). Falls back to keyword recall when there is no index or the vector store
    is unavailable (degrade — FR-004-40 / NFR-004-07). Only **active** facts are returned.
    """
    if index is None:
        return await recall_facts(db, user_id, message, limit)
    try:
        fact_ids = await asyncio.to_thread(index.search, user_id, message, limit)
    except VectorStoreUnavailable as exc:
        log.warning("semantic recall degraded to keyword (store unavailable): %s", exc)
        return await recall_facts(db, user_id, message, limit)

    if not fact_ids:
        return []
    # Load the hit rows, keep only this user's active facts, preserve the similarity order.
    rows = (
        await db.execute(
            select(UserFact).where(
                UserFact.id.in_(fact_ids),
                UserFact.user_id == user_id,
                UserFact.status == FactStatus.active,
            )
        )
    ).scalars().all()
    by_id = {f.id: f for f in rows}
    return [by_id[fid] for fid in fact_ids if fid in by_id]
