"""F-004 memory-system tests (Postgres-only slice: structured user-fact memory).

Maps to `TC-` ids from developer files/tests/F-004-memory-system.md. Covers the implemented slice:
store facts (FR-004-06), categorize (FR-004-07), structured recall active-only + ranked
(FR-004-09/13/25/26), supersede contradictory facts (FR-004-11/12), dedup (FR-004-15), per-user
isolation (FR-004-36), fused recall into the reply context (FR-004-24/28), and the off-hot-path
extract+store (FR-004-42). The semantic/Qdrant half + biography layers are deferred (not tested
here).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

from sqlalchemy import func, select

from services.bot.chat_client import ChatRunnerUnavailable
from services.bot.domain import memory as mem
from services.bot.domain.fact_extraction import MemoryOps, NewFact, _parse, extract_memory_ops
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.models import FactStatus, Persona, UserFact
from services.bot.orchestrator import handle_turn, update_user_memory


class FakeChatClient:
    """Returns a canned string from complete() — used to stand in for the runner."""

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply

    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        return self.reply


async def _user(db, tg_id=7001, locale="ru"):
    user, _ = await get_or_create_user(db, telegram_id=tg_id, locale=locale)
    return user


async def _fact(db, user_id, category, content, status=FactStatus.active, confidence=1.0):
    f = UserFact(user_id=user_id, category=category, content=content,
                 status=status, confidence=confidence)
    db.add(f)
    await db.flush()
    return f


# ── FR-004-06/07 — store + categorize facts ────────────────────────────────────────────────────


async def test_fr_004_06_01_apply_ops_stores_fact(db):
    """TC-FR-004-06-01 — applying an add op writes a USER_FACT for the acting user."""
    user = await _user(db)
    ops = MemoryOps(add=[NewFact(category="family", content="his sister Katya is getting married")])
    inserted = await mem.apply_memory_ops(db, user.id, ops)
    assert len(inserted) == 1
    rows = (await db.execute(select(UserFact).where(UserFact.user_id == user.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].category == "family" and rows[0].user_id == user.id


async def test_fr_004_07_03_fact_retrievable_by_category(db):
    """TC-FR-004-07-03 — a stored fact's category is set and it is retrievable by that category."""
    user = await _user(db)
    await _fact(db, user.id, "work", "he works at a design studio")
    await _fact(db, user.id, "family", "his sister is Katya")
    work = [f for f in await mem.active_facts(db, user.id) if f.category == "work"]
    assert len(work) == 1 and "design studio" in work[0].content


# ── FR-004-09/12 — structured recall active-only, excludes superseded ──────────────────────────


async def test_fr_004_09_03_recall_excludes_superseded(db):
    """TC-FR-004-09-03 — superseded facts are not returned by active recall."""
    user = await _user(db)
    await _fact(db, user.id, "work", "he works at company A", status=FactStatus.superseded)
    await _fact(db, user.id, "work", "he works at company B")
    active = await mem.active_facts(db, user.id)
    assert [f.content for f in active] == ["he works at company B"]


async def test_fr_004_25_01_recall_ranks_relevant_first(db):
    """TC-FR-004-25-01 — the fact most relevant to the message ranks first."""
    user = await _user(db)
    await _fact(db, user.id, "preferences", "he hates horror movies")
    await _fact(db, user.id, "work", "he works at a design studio in Berlin")
    ranked = await mem.recall_facts(db, user.id, "как там работа в студии?", limit=2)
    assert "design studio" in ranked[0].content  # keyword overlap (студи/work) wins


async def test_fr_004_26_02_recall_bounded_by_limit(db):
    """TC-FR-004-26-02 — recall is capped so irrelevant facts can't flood the context."""
    user = await _user(db)
    for i in range(20):
        await _fact(db, user.id, "other", f"random fact number {i}")
    recalled = await mem.recall_facts(db, user.id, "unrelated query", limit=6)
    assert len(recalled) == 6


# ── FR-004-11/12 — supersession ────────────────────────────────────────────────────────────────


async def test_fr_004_11_01_supersede_marks_old_and_adds_new(db):
    """TC-FR-004-11-01 — a contradicting fact makes the new one authoritative, old superseded."""
    user = await _user(db)
    old = await _fact(db, user.id, "work", "he works at company A")
    ops = MemoryOps(add=[NewFact(category="work", content="he works at company B")],
                    supersede=[old.id])
    inserted = await mem.apply_memory_ops(db, user.id, ops)

    await db.refresh(old)
    assert old.status == FactStatus.superseded
    assert old.superseded_by == inserted[0].id
    active = await mem.active_facts(db, user.id)
    assert [f.content for f in active] == ["he works at company B"]


async def test_fr_004_12_02_superseded_row_retained(db):
    """TC-FR-004-12-02 — a superseded fact is soft-superseded (row kept), not hard-deleted."""
    user = await _user(db)
    old = await _fact(db, user.id, "work", "he works at company A")
    await mem.apply_memory_ops(db, user.id,
                               MemoryOps(add=[NewFact("work", "company B")], supersede=[old.id]))
    total = (await db.execute(
        select(func.count()).select_from(UserFact).where(UserFact.user_id == user.id))).scalar_one()
    assert total == 2  # both rows present, one active + one superseded


# ── FR-004-15 — dedup ──────────────────────────────────────────────────────────────────────────


async def test_fr_004_15_01_dedup_no_duplicate_row(db):
    """TC-FR-004-15-01 — restating an already-stored fact creates no duplicate row."""
    user = await _user(db)
    await _fact(db, user.id, "preferences", "he loves jazz")
    inserted = await mem.apply_memory_ops(
        db, user.id, MemoryOps(add=[NewFact("preferences", "he loves jazz")]))
    assert inserted == []
    total = (await db.execute(
        select(func.count()).select_from(UserFact).where(UserFact.user_id == user.id))).scalar_one()
    assert total == 1


# ── FR-004-36 / NFR-004-03 — per-user isolation ────────────────────────────────────────────────


async def test_fr_004_36_01_recall_scoped_to_user(db):
    """TC-FR-004-36-01 — recall returns only the acting user's facts, never another user's."""
    a = await _user(db, tg_id=8001)
    b = await _user(db, tg_id=8002)
    await _fact(db, a.id, "work", "A works at a bakery")
    await _fact(db, b.id, "work", "B works at a bakery")
    a_facts = await mem.recall_facts(db, a.id, "work bakery", limit=10)
    assert all(f.user_id == a.id for f in a_facts)
    assert len(a_facts) == 1


async def test_fr_004_36_01_supersede_scoped_to_user(db):
    """TC-FR-004-36-01 — one user's supersede op cannot touch another user's fact."""
    a = await _user(db, tg_id=8101)
    b = await _user(db, tg_id=8102)
    b_fact = await _fact(db, b.id, "work", "B works at company A")
    # user A tries to supersede B's fact id — must be ignored (not A's fact)
    await mem.apply_memory_ops(db, a.id, MemoryOps(add=[], supersede=[b_fact.id]))
    await db.refresh(b_fact)
    assert b_fact.status == FactStatus.active  # untouched


# ── fact_extraction parsing ────────────────────────────────────────────────────────────────────


def test_parse_valid_json():
    """The extraction JSON is parsed into add/supersede ops, category normalized, confidence clamped."""
    raw = ('here you go: {"add": [{"category": "WORK", "content": "he moved to Berlin", '
           '"confidence": 1.5}], "supersede": [3, "7"]}')
    ops = _parse(raw)
    assert len(ops.add) == 1
    assert ops.add[0].category == "work" and ops.add[0].confidence == 1.0
    assert ops.supersede == [3, 7]


def test_parse_bad_or_empty():
    """Malformed / non-JSON extraction output yields empty ops (never crashes)."""
    assert _parse("not json at all").add == []
    assert _parse('{"add": [], "supersede": []}').supersede == []


def test_parse_unknown_category_falls_back_to_other():
    ops = _parse('{"add": [{"category": "sports", "content": "he plays tennis"}]}')
    assert ops.add[0].category == "other"


async def test_extract_memory_ops_unavailable_returns_empty():
    """TC-FR-004-42 — if the runner is unavailable, extraction returns empty ops (never raises)."""
    class Down:
        async def complete(self, *a, **k):
            raise ChatRunnerUnavailable("down")
    ops = await extract_memory_ops(Down(), "i work at X", [])
    assert ops.add == [] and ops.supersede == []


# ── orchestrator integration ───────────────────────────────────────────────────────────────────


async def _ready_chat(db, tg_id=9001):
    user = await _user(db, tg_id=tg_id)
    persona = Persona(name="Alina", profession="psychologist", age=28, language="ru",
                      card_description="", big_five="")
    db.add(persona)
    await db.flush()
    session, _ = await start_or_switch_session(db, user.id, persona.id)
    return user, persona, session


async def test_fr_004_24_01_recalled_facts_fused_into_context(db):
    """TC-FR-004-24-01 — stored facts are injected into the reply context as a memory block."""
    user, persona, session = await _ready_chat(db)
    await _fact(db, user.id, "family", "his sister Katya is getting married in June")

    captured = {}

    class Capturing(FakeChatClient):
        async def complete(self, messages, **kw):
            captured["messages"] = messages
            return "ага, помню про Катю!"

    await handle_turn(db, session, persona, "что там у сестры?", Capturing())
    system_msgs = [m for m in captured["messages"] if m["role"] == "system"]
    # Regression: exactly ONE system message — the Qwen chat template rejects a second one with
    # "System message must be at the beginning" (a 500). Memory is concatenated into the single
    # system message, not added as an extra system turn.
    assert len(system_msgs) == 1
    assert "Katya" in system_msgs[0]["content"]  # the recalled fact reached the prompt


async def test_fr_004_06_02_update_user_memory_stores_extracted_facts(db):
    """TC-FR-004-06-01 — after a turn, extracted facts are stored for the user."""
    user, _persona, _session = await _ready_chat(db, tg_id=9002)
    client = FakeChatClient(
        reply='{"add": [{"category": "family", "content": "his sister is Katya", '
              '"confidence": 1.0}], "supersede": []}')
    inserted = await update_user_memory(db, user.id, "у меня сестра Катя", client)
    assert len(inserted) == 1
    active = await mem.active_facts(db, user.id)
    assert any("Katya" in f.content for f in active)


async def test_fr_004_11_02_update_user_memory_supersedes(db):
    """TC-FR-004-11-02 — an update that supersedes leaves only the current fact active."""
    user, _persona, _session = await _ready_chat(db, tg_id=9003)
    old = await _fact(db, user.id, "work", "he works at company A")
    client = FakeChatClient(
        reply=f'{{"add": [{{"category": "work", "content": "he works at company B"}}], '
              f'"supersede": [{old.id}]}}')
    await update_user_memory(db, user.id, "я перешёл в компанию B", client)
    active = await mem.active_facts(db, user.id)
    assert [f.content for f in active] == ["he works at company B"]
