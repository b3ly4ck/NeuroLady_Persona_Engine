"""F-004 supplementary coverage — automatable TC cases not covered by test_f004_memory.py /
test_f004_semantic.py (recency ranking, faithful recall, confidence stored, supersession never
resurfaces, durability across a restart). Performance/load/statistical/manual TCs are out of scope.

Maps to `TC-` ids from developer files/tests/F-004-memory-system.md.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from services.bot.domain import memory as mem
from services.bot.domain.fact_extraction import MemoryOps, NewFact
from services.bot.domain.users import get_or_create_user
from services.bot.db import init_models, make_sessionmaker
from services.bot.models import FactStatus, UserFact


async def _user(db, tg_id=5001):
    user, _ = await get_or_create_user(db, telegram_id=tg_id, locale="ru")
    return user


async def _fact(db, user_id, category, content, confidence=1.0, status=FactStatus.active):
    f = UserFact(user_id=user_id, category=category, content=content,
                 confidence=confidence, status=status)
    db.add(f)
    await db.flush()
    return f


# ── FR-004-13 — recency handling ───────────────────────────────────────────────────────────────


async def test_fr_004_13_01_newer_fact_ranks_higher_when_no_keyword_match(db):
    """TC-FR-004-13-01 — with no keyword overlap, the more recent fact ranks first (recency)."""
    user = await _user(db)
    await _fact(db, user.id, "preferences", "aaa bbb ccc")   # older
    await _fact(db, user.id, "preferences", "ddd eee fff")   # newer
    ranked = await mem.recall_facts(db, user.id, "zzz unrelated query", limit=2)
    assert ranked[0].content == "ddd eee fff"  # newer preferred


# ── FR-004-14 — confidence stored ──────────────────────────────────────────────────────────────


async def test_fr_004_14_01_confidence_persisted(db):
    """TC-FR-004-14-01 — a hedged fact is stored with a lower confidence than a firm one."""
    user = await _user(db)
    inserted = await mem.apply_memory_ops(db, user.id, MemoryOps(add=[
        NewFact("work", "he is definitely a teacher", confidence=1.0),
        NewFact("plans", "he might move to Berlin", confidence=0.4),
    ]))
    by_content = {f.content: f.confidence for f in inserted}
    assert by_content["he is definitely a teacher"] == 1.0
    assert by_content["he might move to Berlin"] == 0.4


# ── FR-004-29 — recall faithful to stored content ──────────────────────────────────────────────


async def test_fr_004_29_01_recall_returns_content_verbatim(db):
    """TC-FR-004-29-01 — recalled facts carry the stored content unchanged (no mutation)."""
    user = await _user(db)
    original = "his sister Katya is getting married in June"
    await _fact(db, user.id, "family", original)
    ranked = await mem.recall_facts(db, user.id, "sister Katya", limit=1)
    assert ranked[0].content == original


# ── FR-004-12 / NFR-004-12 — superseded fact never resurfaces ──────────────────────────────────


async def test_nfr_004_12_01_superseded_never_resurfaces(db):
    """TC-NFR-004-12-01 — after supersession, repeated recalls never return the outdated fact."""
    user = await _user(db)
    old = await _fact(db, user.id, "work", "he works at company A")
    await mem.apply_memory_ops(db, user.id, MemoryOps(
        add=[NewFact("work", "he works at company B")], supersede=[old.id]))
    for q in ("company", "work", "job A", "where does he work"):
        ranked = await mem.recall_facts(db, user.id, q, limit=10)
        assert all(f.id != old.id for f in ranked)


async def test_nfr_004_12_02_one_active_fact_per_superseded_subject(db):
    """TC-NFR-004-12-02 — after a supersession chain, exactly one fact on the subject is active."""
    user = await _user(db)
    f1 = await _fact(db, user.id, "work", "he works at A")
    await mem.apply_memory_ops(db, user.id, MemoryOps(add=[NewFact("work", "he works at B")], supersede=[f1.id]))
    active = [f for f in await mem.active_facts(db, user.id) if f.category == "work"]
    assert len(active) == 1 and active[0].content == "he works at B"


# ── FR-004-32 / NFR-004-04 — durability across a restart ───────────────────────────────────────


async def test_fr_004_32_01_facts_survive_restart(tmp_path):
    """TC-FR-004-32-01 — stored facts persist across a service restart (disk-backed store)."""
    db_url = f"sqlite+aiosqlite:///{tmp_path/'mem.sqlite3'}"

    eng1 = create_async_engine(db_url)
    await init_models(eng1)
    sm1 = make_sessionmaker(eng1)
    async with sm1() as db:
        user, _ = await get_or_create_user(db, 9999, "ru")
        await mem.apply_memory_ops(db, user.id, MemoryOps(add=[
            NewFact("family", "his sister is Katya"),
            NewFact("work", "he works at a studio"),
        ]))
        await db.commit()
        uid = user.id
    await eng1.dispose()

    eng2 = create_async_engine(db_url)
    sm2 = make_sessionmaker(eng2)
    async with sm2() as db:
        facts = await mem.active_facts(db, uid)
        contents = {f.content for f in facts}
        assert "his sister is Katya" in contents and "he works at a studio" in contents
    await eng2.dispose()


# ── FR-004-30 — recalled facts are the acting user's real stored facts ─────────────────────────


async def test_fr_004_30_01_recall_only_returns_real_stored_facts(db):
    """TC-FR-004-30-01 — recall returns exactly the user's stored facts, inventing nothing."""
    user = await _user(db)
    stored = {"he loves jazz", "his dog is named Rex"}
    for c in stored:
        await _fact(db, user.id, "preferences", c)
    ranked = await mem.recall_facts(db, user.id, "jazz dog music", limit=10)
    assert {f.content for f in ranked} <= stored  # never anything not stored
