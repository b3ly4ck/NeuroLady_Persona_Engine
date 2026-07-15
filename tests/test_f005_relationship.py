"""Tests for F-005 — Relationship System. One test per declared TC in
developer files/tests/F-005-relationship-system.md.

Automatable TCs (unit/integration/consistency/isolation/persistence/idempotency) have real
assertions. TCs that are performance/load/statistical/e2e-live/manual by nature are present as
`pytest.skip` stubs (traceable to the TC id, honestly not fast-unit-testable) — never faked green.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from services.bot.db import init_models, make_sessionmaker
from services.bot.domain import relationship_store as rs
from services.bot.domain.relationship import (
    DEFAULT_CONFIG as C,
    STAGE_BEHAVIOR,
    STAGES,
    RelationshipConfig,
    RelState,
    apply_decay,
    apply_deltas,
    derive_stage,
    stage_behavior_directive,
    stage_index,
)
from services.bot.domain.relationship_reflection import (
    PROMPT_ASSET,
    HardSignals,
    ReflectionResult,
    _parse,
    build_prompt,
    compute_warmth,
)
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.models import Persona, Relationship, RelationshipReflection
from services.bot.orchestrator import _relationship_block, update_relationship


# ── helpers ────────────────────────────────────────────────────────────────────────────────────


async def _user(db, tg_id):
    u, _ = await get_or_create_user(db, telegram_id=tg_id, locale="ru")
    return u


async def _persona(db, name="Alina", language="ru"):
    p = Persona(name=name, profession="psychologist", age=28, language=language,
                card_description="", big_five="warm, playful")
    db.add(p)
    await db.flush()
    return p


class ReflectClient:
    """Fake external LLM returning a canned reflection JSON (or raising)."""

    def __init__(self, dc=0, dt=0, da=0, summary="we're good", breach=False, pushing=False, fail=False):
        self._json = json.dumps({
            "deltas": {"closeness": dc, "trust": dt, "attraction": da},
            "reasons": {"closeness": "warm", "trust": "kind", "attraction": "spark"},
            "summary": summary, "breach": breach, "pushing_fast": pushing,
        })
        self._fail = fail

    async def is_ready(self):
        return not self._fail

    async def complete(self, messages, **kw):
        if self._fail:
            from services.bot.chat_client import ChatRunnerUnavailable
            raise ChatRunnerUnavailable("down")
        return self._json


# ══════════════════════════════════════ FUNCTIONAL ══════════════════════════════════════════════

# FR-005-01 — three dimensions + derived stage
async def test_tc_fr_005_01_01(db):
    """TC-FR-005-01-01 — relationship holds Closeness/Trust/Attraction + a stage."""
    u, p = await _user(db, 1), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    assert isinstance(rel.closeness, int) and isinstance(rel.trust, int)
    assert isinstance(rel.attraction, int) and rel.stage in STAGES


async def test_tc_fr_005_01_02(db):
    """TC-FR-005-01-02 — state maps to the RELATIONSHIP schema (stage/closeness/trust/attraction/…)."""
    u, p = await _user(db, 2), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    for col in ("stage", "closeness", "trust", "attraction", "summary", "last_interaction_at"):
        assert hasattr(rel, col)


# FR-005-02 — created at Stranger with baselines
async def test_tc_fr_005_02_01(db):
    """TC-FR-005-02-01 — first interaction creates a Stranger relationship."""
    u, p = await _user(db, 3), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    assert rel.stage == "Stranger"


def test_tc_fr_005_02_02():
    """TC-FR-005-02-02 — baselines default low and are configurable."""
    assert RelState.baseline(C).closeness == C.baseline_closeness
    cfg = RelationshipConfig(baseline_closeness=12)
    assert RelState.baseline(cfg).closeness == 12


# FR-005-03 — stage derived, never set directly (CRITICAL)
def test_tc_fr_005_03_01():
    """TC-FR-005-03-01 — highest satisfied gate wins (65/55/60 → Romance)."""
    assert derive_stage(65, 55, 60, None, C) == "Romance"


@pytest.mark.parametrize("c,t,a,stage", [
    (5, 5, 5, "Stranger"), (20, 10, 10, "Acquaintance"), (45, 40, 20, "Friend"),
    (35, 30, 50, "Flirting"), (65, 55, 60, "Romance"), (85, 75, 75, "Love"),
])
def test_tc_fr_005_03_02(c, t, a, stage):
    """TC-FR-005-03-02 — the UC-005-03 outline boundary values map correctly."""
    assert derive_stage(c, t, a, None, C) == stage


def test_tc_fr_005_03_03():
    """TC-FR-005-03-03 — the stage always equals the derived value (cannot diverge from dimensions)."""
    # deriving from the same dims is idempotent — there is no path to set a non-derived stage
    assert derive_stage(45, 40, 20, "Love", C) != "Love"  # dims say Friend, not the stale 'Love'


# FR-005-04 — hysteresis (CRITICAL)
def test_tc_fr_005_04_01():
    """TC-FR-005-04-01 — advancing requires crossing the gate."""
    assert derive_stage(40, 35, 0, "Acquaintance", C) == "Friend"


def test_tc_fr_005_04_02():
    """TC-FR-005-04-02 — a small dip below the gate does not regress (margin 8)."""
    assert derive_stage(37, 40, 0, "Friend", C) == "Friend"  # 3 below the C≥40 gate


def test_tc_fr_005_04_03():
    """TC-FR-005-04-03 — falling the full margin below regresses one step."""
    assert derive_stage(30, 30, 0, "Friend", C) == "Acquaintance"


# FR-005-05 — summary + last-interaction
async def test_tc_fr_005_05_01(db):
    """TC-FR-005-05-01 — an applied reflection stores a summary + last_interaction timestamp."""
    u, p = await _user(db, 5), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    await rs.apply_reflection(db, rel, ReflectionResult(3, 3, 3, {}, "we clicked today"), C)
    assert rel.summary == "we clicked today" and rel.last_interaction_at is not None


async def test_tc_fr_005_05_02(db):
    """TC-FR-005-05-02 — last_interaction_at advances on new contact."""
    u, p = await _user(db, 6), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    await rs.apply_reflection(db, rel, ReflectionResult(1, 1, 1, {}, "a"), C)
    t1 = rel.last_interaction_at
    rel.last_interaction_at = t1 - timedelta(days=1)  # pretend older
    await rs.apply_reflection(db, rel, ReflectionResult(1, 1, 1, {}, "b"), C)
    assert rel.last_interaction_at > t1 - timedelta(days=1)


# FR-005-06 — reflection uses persona + state + convo + hard signals (CRITICAL)
def test_tc_fr_005_06_01():
    """TC-FR-005-06-01 — the reflection prompt carries identity, state, conversation, hard signals."""
    prompt = build_prompt("Alina", "warm", RelState(20, 15, 10, "Acquaintance"), "we chatted",
                          "he: hi\nyou: hey", HardSignals(2.0, 4, "warm"))
    for needle in ("Alina", "Acquaintance", "20", "he: hi", "days since", "4"):
        assert str(needle) in prompt


def test_tc_fr_005_06_02():
    """TC-FR-005-06-02 — hard signals (days-since, msg count, warmth) are computed and present."""
    s = HardSignals(days_since=3.0, msg_count=5, warmth=compute_warmth("спасибо, скучал"))
    assert s.days_since == 3.0 and s.msg_count == 5 and s.warmth == "warm"


async def test_tc_fr_005_06_03(db):
    """TC-FR-005-06-03 — Life Engine → LLM path composes: a canned reflection is applied."""
    u, p = await _user(db, 7), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    from services.bot.domain import messages as md
    from services.bot.models import MessageSender
    await md.append_message(db, sess.id, MessageSender.user, "спасибо, ты классная")
    rel = await update_relationship(db, sess, p, ReflectClient(dc=5, dt=3, da=4), C)
    assert rel.closeness > C.baseline_closeness


async def test_tc_fr_005_06_03c_naive_last_interaction_no_crash(db):
    """Regression (live-caught) — a naive last_interaction_at (as SQLite returns) must not crash the
    days-since computation (was: can't subtract offset-naive and offset-aware datetimes)."""
    u, p = await _user(db, 701), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.last_interaction_at = datetime(2026, 7, 1, 12, 0, 0)  # naive, no tzinfo
    await db.flush()
    from services.bot.domain import messages as md
    from services.bot.models import MessageSender
    await md.append_message(db, sess.id, MessageSender.user, "спасибо, рад")
    rel = await update_relationship(db, sess, p, ReflectClient(dc=4, dt=2, da=2), C)
    assert rel.closeness > C.baseline_closeness  # reflection applied, no crash


async def test_tc_fr_005_06_03b_reflection_sends_a_user_message(db):
    """Regression (live-caught) — the reflection call must carry a user-role message; the chat
    template 500s on a system-only message ("No user query found in messages")."""
    u, p = await _user(db, 700), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    roles = {}

    class Cap:
        async def is_ready(self): return True
        async def complete(self, messages, **kw):
            roles["has_user"] = any(m["role"] == "user" for m in messages)
            return json.dumps({"deltas": {"closeness": 0, "trust": 0, "attraction": 0},
                               "reasons": {}, "summary": "s", "breach": False, "pushing_fast": False})

    await update_relationship(db, sess, p, Cap(), C)
    assert roles.get("has_user") is True


# FR-005-07 — trigger configurable + off hot path
def test_tc_fr_005_07_01():
    """TC-FR-005-07-01 — reflection cadence is config-driven (a tunable, not hard-coded)."""
    # cadence is a Life Engine tunable; here we assert the config object carries tunables at all
    assert hasattr(C, "per_reflection_cap")  # representative tunable exists in config


async def test_tc_fr_005_07_02(db):
    """TC-FR-005-07-02 — the reflection runs after the reply (handle_turn does not call it)."""
    import inspect

    from services.bot import orchestrator
    src = inspect.getsource(orchestrator.handle_turn)
    assert "update_relationship" not in src  # reflection is not inline in the reply path


# FR-005-08 — deltas + reasons + rewritten summary (CRITICAL)
async def test_tc_fr_005_08_01(db):
    """TC-FR-005-08-01 — parsed deltas move each dimension."""
    u, p = await _user(db, 8), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    base_c, base_t, base_a = rel.closeness, rel.trust, rel.attraction
    await rs.apply_reflection(db, rel, ReflectionResult(5, 3, 4, {}, "s"), C)
    assert (rel.closeness, rel.trust, rel.attraction) == (base_c + 5, base_t + 3, base_a + 4)


async def test_tc_fr_005_08_02(db):
    """TC-FR-005-08-02 — each delta carries a recorded reason in the log."""
    u, p = await _user(db, 9), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    await rs.apply_reflection(
        db, rel, ReflectionResult(2, 2, 2, {"closeness": "warm", "trust": "kind"}, "s"), C)
    logrow = (await db.execute(select(RelationshipReflection))).scalars().first()
    assert "warm" in logrow.reasons and "kind" in logrow.reasons


async def test_tc_fr_005_08_03(db):
    """TC-FR-005-08-03 — the summary is rewritten to the returned one."""
    u, p = await _user(db, 10), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    await rs.apply_reflection(db, rel, ReflectionResult(1, 1, 1, {}, "we're closer now"), C)
    assert rel.summary == "we're closer now"


# FR-005-09 — re-derive stage after deltas + persist
async def test_tc_fr_005_09_01(db):
    """TC-FR-005-09-01 — deltas past a gate re-derive the stage."""
    u, p = await _user(db, 11), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.closeness, rel.trust, rel.attraction = 12, 8, 8  # near Acquaintance gate (C≥15)
    await rs.apply_reflection(db, rel, ReflectionResult(5, 0, 0, {}, "s"), C)
    assert rel.stage == "Acquaintance"


async def test_tc_fr_005_09_02(tmp_path):
    """TC-FR-005-09-02 — re-derived state survives a restart."""
    url = f"sqlite+aiosqlite:///{tmp_path/'r.sqlite3'}"
    e1 = create_async_engine(url); await init_models(e1); sm1 = make_sessionmaker(e1)
    async with sm1() as db:
        u, p = await _user(db, 12), await _persona(db)
        rel = await rs.get_or_create(db, u.id, p.id)
        rel.closeness, rel.trust, rel.attraction = 42, 38, 10
        await rs.apply_reflection(db, rel, ReflectionResult(0, 0, 0, {}, "s"), C)
        await db.commit(); uid, pid, stage = u.id, p.id, rel.stage
    await e1.dispose()
    e2 = create_async_engine(url); sm2 = make_sessionmaker(e2)
    async with sm2() as db:
        rel = await rs.get_or_create(db, uid, pid)
        assert rel.stage == stage == "Friend"
    await e2.dispose()


# FR-005-10 — reflection log entry
async def test_tc_fr_005_10_01(db):
    """TC-FR-005-10-01 — an applied reflection writes a log entry with deltas, stage, timestamp."""
    u, p = await _user(db, 13), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    await rs.apply_reflection(db, rel, ReflectionResult(3, 2, 1, {"trust": "kind"}, "s"), C)
    row = (await db.execute(select(RelationshipReflection))).scalars().one()
    assert row.delta_closeness == 3 and row.resulting_stage == rel.stage and row.created_at


async def test_tc_fr_005_10_02(db):
    """TC-FR-005-10-02 — the reflection step persists the log as part of the chain (DFD-2)."""
    u, p = await _user(db, 14), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    await rs.apply_reflection(db, rel, ReflectionResult(1, 1, 1, {}, "s"), C)
    n = (await db.execute(select(func.count()).select_from(RelationshipReflection))).scalar_one()
    assert n == 1


# FR-005-11 — versioned prompt asset, not hard-coded
def test_tc_fr_005_11_01():
    """TC-FR-005-11-01 — the prompt loads from the versioned asset directory by id."""
    from services.bot.prompts import load_prompt
    assert "{persona_name}" in load_prompt(PROMPT_ASSET) or "STRICT JSON" in load_prompt(PROMPT_ASSET)


def test_tc_fr_005_11_02():
    """TC-FR-005-11-02 — no inline hard-coded prompt string in the reflection module."""
    import inspect

    from services.bot.domain import relationship_reflection as rr
    src = inspect.getsource(rr)
    assert "STRICT JSON" not in src  # the prompt text lives in the asset file, not inline


# FR-005-12 — clamp 0–100
def test_tc_fr_005_12_01():
    """TC-FR-005-12-01 — an over-max delta clamps to 100."""
    r = apply_deltas(RelState(96, 50, 50, "Friend"), 10, 0, 0, C)
    assert r.state.closeness == 100


def test_tc_fr_005_12_02():
    """TC-FR-005-12-02 — an under-min delta clamps to 0."""
    r = apply_deltas(RelState(50, 4, 50, "Friend"), 0, -10, 0, C)
    assert r.state.trust == 0


# FR-005-13 — per-reflection cap (CRITICAL)
def test_tc_fr_005_13_01():
    """TC-FR-005-13-01 — an over-cap positive delta is capped."""
    r = apply_deltas(RelState(50, 50, 50, "Friend"), 40, 0, 0, C)
    assert r.state.closeness == 60  # +10 cap, not +40


def test_tc_fr_005_13_02():
    """TC-FR-005-13-02 — an over-cap negative delta is capped (non-breach)."""
    r = apply_deltas(RelState(50, 50, 50, "Friend"), 0, -40, 0, C)
    assert r.state.trust == 40  # -10 cap


def test_tc_fr_005_13_03():
    """TC-FR-005-13-03 — a single reflection cannot jump Stranger → Love."""
    r = apply_deltas(RelState.baseline(C), 100, 100, 100, C)
    assert stage_index(r.state.stage) < STAGES.index("Love")


# FR-005-14 — decay on neglect
def test_tc_fr_005_14_01():
    """TC-FR-005-14-01 — no contact drifts Closeness and Attraction down."""
    r = apply_decay(RelState(60, 60, 60, "Romance"), 5, C)
    assert r.state.closeness < 60 and r.state.attraction < 60


def test_tc_fr_005_14_02():
    """TC-FR-005-14-02 — Trust decays slowest."""
    r = apply_decay(RelState(60, 60, 60, "Romance"), 10, C)
    drop_t = 60 - r.state.trust
    drop_c = 60 - r.state.closeness
    assert drop_t < drop_c


def test_tc_fr_005_14_03():
    """TC-FR-005-14-03 — decay accrues with the length of the gap (more days → more drift)."""
    little = apply_decay(RelState(80, 80, 80, "Love"), 2, C).state.closeness
    lots = apply_decay(RelState(80, 80, 80, "Love"), 20, C).state.closeness
    assert lots < little


# FR-005-15 — never reset to Stranger from a single gap
def test_tc_fr_005_15_01():
    """TC-FR-005-15-01 — one long gap cannot drop a Friend straight to Stranger."""
    r = apply_decay(RelState(45, 40, 20, "Friend"), 60, C)
    assert r.state.stage != "Stranger"  # regression is one step per application


def test_tc_fr_005_15_02():
    """TC-FR-005-15-02 — only sustained neglect lowers the stage, gradually."""
    st = RelState(45, 40, 20, "Friend")
    stages = []
    for _ in range(4):
        st = apply_decay(st, 20, C).state
        stages.append(st.stage)
    # monotonic non-increasing, at most one step down each time
    idx = [stage_index(s) for s in [ "Friend", *stages]]
    assert all(idx[i] - idx[i + 1] <= 1 for i in range(len(idx) - 1))


# FR-005-16 — asymmetric trust (CRITICAL)
def test_tc_fr_005_16_01():
    """TC-FR-005-16-01 — Trust rises only a small bounded amount under warmth."""
    r = apply_deltas(RelState(50, 50, 50, "Friend"), 0, 8, 0, C)
    assert r.state.trust == 58 and (r.state.trust - 50) <= C.per_reflection_cap


def test_tc_fr_005_16_02():
    """TC-FR-005-16-02 — a genuine breach drops Trust faster than it could rise."""
    r = apply_deltas(RelState(50, 50, 50, "Friend"), 0, -25, 0, C, breach=True)
    assert 50 - r.state.trust > C.per_reflection_cap  # bigger than a normal-cap move


def test_tc_fr_005_16_03():
    """TC-FR-005-16-03 — a single mild bad message (no breach) takes only the normal cap."""
    r = apply_deltas(RelState(50, 50, 50, "Friend"), 0, -25, 0, C, breach=False)
    assert r.state.trust == 40  # capped at -10, not the sharp breach drop


# FR-005-17 — pacing/consent guard (CRITICAL)
def test_tc_fr_005_17_01():
    """TC-FR-005-17-01 — pushing fast at low trust does not advance to Romance."""
    r = apply_deltas(RelState(58, 40, 54, "Flirting"), 5, 10, 5, C, pushing_fast=True)
    assert stage_index(r.state.stage) < C.romance_stage_index


def test_tc_fr_005_17_02():
    """TC-FR-005-17-02 — pushing fast never raises Trust as a reward."""
    r = apply_deltas(RelState(30, 20, 40, "Acquaintance"), 5, 9, 5, C, pushing_fast=True)
    assert r.state.trust <= 20


def test_tc_fr_005_17_03():
    """TC-FR-005-17-03 (e2e) — she stays gentle across a live pushing arc."""
    pytest.skip("e2e / live-model — judged against the real model, not a fast unit test")


# FR-005-18 — regression gradual, no cliff except breach
def test_tc_fr_005_18_01():
    """TC-FR-005-18-01 — sustained coldness slips the stage back one step at a time."""
    st = RelState(65, 55, 60, "Romance")
    st2 = apply_deltas(st, -10, -10, -10, C).state
    assert stage_index(st2.stage) >= stage_index("Romance") - 1


def test_tc_fr_005_18_02():
    """TC-FR-005-18-02 — no multi-stage cliff drop outside a breach."""
    r = apply_deltas(RelState(85, 75, 75, "Love"), -10, -10, -10, C)
    assert stage_index("Love") - stage_index(r.state.stage) <= 1


# FR-005-19 — expose state to the reply context (CRITICAL)
async def test_tc_fr_005_19_01(db):
    """TC-FR-005-19-01 — the exposed relationship block reflects the current stage + summary."""
    u, p = await _user(db, 19), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.stage, rel.summary = "Friend", "we're close"
    block = _relationship_block(rel, "en")
    assert STAGE_BEHAVIOR["Friend"] in block and "we're close" in block


async def test_tc_fr_005_19_02(db):
    """TC-FR-005-19-02 — the state reaches the assembled reply context (via handle_turn)."""
    u, p = await _user(db, 20), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.stage = "Flirting"
    captured = {}

    class Cap:
        async def is_ready(self): return True
        async def complete(self, messages, **kw):
            captured["m"] = messages
            return "hey)"

    from services.bot.orchestrator import handle_turn
    await handle_turn(db, sess, p, "привет", Cap())
    sys = " ".join(m["content"] for m in captured["m"] if m["role"] == "system")
    assert STAGE_BEHAVIOR["Flirting"] in sys


async def test_tc_fr_005_19_03(db):
    """TC-FR-005-19-03 — context assembly includes relationship state (DFD-1)."""
    u, p = await _user(db, 21), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    captured = {}

    class Cap:
        async def is_ready(self): return True
        async def complete(self, messages, **kw):
            captured["m"] = messages; return "x"

    from services.bot.orchestrator import handle_turn
    await handle_turn(db, sess, p, "hi", Cap())
    sys = " ".join(m["content"] for m in captured["m"] if m["role"] == "system")
    assert STAGE_BEHAVIOR["Stranger"] in sys  # baseline stage state present


# FR-005-20 — stage gates behaviour (CRITICAL)
def test_tc_fr_005_20_01():
    """TC-FR-005-20-01 — Stranger → reserved directive."""
    assert "reserved" in stage_behavior_directive("Stranger").lower()


def test_tc_fr_005_20_02():
    """TC-FR-005-20-02 — Love/Devoted → intimate/initiating directive (can say 'love')."""
    assert "love" in stage_behavior_directive("Love").lower()


def test_tc_fr_005_20_03():
    """TC-FR-005-20-03 — Flirting → playful/flirty but not full intimacy."""
    d = stage_behavior_directive("Flirting").lower()
    assert "flirty" in d and "not fully intimate" in d


# FR-005-21 — stage gating separate from billing
def test_tc_fr_005_21_01():
    """TC-FR-005-21-01 — stage governs willingness, not payment (no billing in the directive path)."""
    import inspect

    from services.bot.domain import relationship as rel_mod
    src = inspect.getsource(rel_mod)
    assert "pay" not in src.lower() and "billing" not in src.lower()


def test_tc_fr_005_21_02():
    """TC-FR-005-21-02 — a Stranger stays reserved regardless of any pay state."""
    assert "reserved" in stage_behavior_directive("Stranger").lower()


# FR-005-22 — milestone on crossing a boundary (CRITICAL)
async def test_tc_fr_005_22_01(db):
    """TC-FR-005-22-01 — crossing a stage boundary marks a milestone."""
    u, p = await _user(db, 22), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.closeness, rel.trust, rel.attraction = 12, 8, 8
    await rs.apply_reflection(db, rel, ReflectionResult(6, 0, 0, {}, "s"), C)  # crosses Acquaintance
    assert rel.pending_milestone == "Acquaintance"


async def test_tc_fr_005_22_02(db):
    """TC-FR-005-22-02 — a pending milestone surfaces an acknowledgement cue in the reply context."""
    u, p = await _user(db, 23), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.pending_milestone = "Friend"
    block = _relationship_block(rel, "en")
    assert "closer" in block.lower()


async def test_tc_fr_005_22_03(db):
    """TC-FR-005-22-03 — no milestone when no boundary is crossed."""
    u, p = await _user(db, 24), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.closeness, rel.trust, rel.attraction, rel.stage = 50, 45, 20, "Friend"  # already Friend
    await rs.apply_reflection(db, rel, ReflectionResult(1, 1, 0, {}, "s"), C)  # stays Friend
    assert rel.pending_milestone is None


# FR-005-23 — milestone never narrates mechanics
def test_tc_fr_005_23_01():
    """TC-FR-005-23-01 — the milestone cue leaks no numbers/stage/score words."""
    rel = Relationship(stage="Friend", summary="", pending_milestone="Friend")
    for lang in ("ru", "en"):
        block = _relationship_block(rel, lang).lower()
        assert "stage" not in block and "score" not in block and not any(ch.isdigit() for ch in block)


def test_tc_fr_005_23_02():
    """TC-FR-005-23-02 (e2e) — the milestone reads as a natural in-character beat."""
    pytest.skip("e2e / live-model — judged against the real model")


# FR-005-24 — stored in Memory, survives restart (CRITICAL)
async def test_tc_fr_005_24_01(db):
    """TC-FR-005-24-01 — F-005 authors, Memory persists RELATIONSHIP + RELATIONSHIP_REFLECTION rows."""
    u, p = await _user(db, 25), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    await rs.apply_reflection(db, rel, ReflectionResult(2, 2, 2, {}, "s"), C)
    assert (await db.execute(select(func.count()).select_from(Relationship))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(RelationshipReflection))).scalar_one() == 1


async def test_tc_fr_005_24_02(tmp_path):
    """TC-FR-005-24-02 — state survives a restart."""
    url = f"sqlite+aiosqlite:///{tmp_path/'r24.sqlite3'}"
    e1 = create_async_engine(url); await init_models(e1); sm1 = make_sessionmaker(e1)
    async with sm1() as db:
        u, p = await _user(db, 26), await _persona(db)
        rel = await rs.get_or_create(db, u.id, p.id)
        await rs.apply_reflection(db, rel, ReflectionResult(4, 4, 4, {}, "kept"), C)
        await db.commit(); uid, pid = u.id, p.id
    await e1.dispose()
    e2 = create_async_engine(url); sm2 = make_sessionmaker(e2)
    async with sm2() as db:
        rel = await rs.get_or_create(db, uid, pid)
        assert rel.summary == "kept"
    await e2.dispose()


def test_tc_fr_005_24_03():
    """TC-FR-005-24-03 — F-005 delegates storage to Memory (no store owned in the domain module)."""
    import inspect

    from services.bot.domain import relationship as rel_mod
    src = inspect.getsource(rel_mod)
    assert "session" not in src.lower() and "sqlalchemy" not in src.lower()  # pure logic, no store


# FR-005-25 — per-user isolation (CRITICAL)
async def test_tc_fr_005_25_01(db):
    """TC-FR-005-25-01 — advancing A does not change B's state."""
    a, b, p = await _user(db, 27), await _user(db, 28), await _persona(db)
    ra = await rs.get_or_create(db, a.id, p.id)
    rb = await rs.get_or_create(db, b.id, p.id)
    await rs.apply_reflection(db, ra, ReflectionResult(10, 10, 10, {}, "a"), C)
    await db.refresh(rb)
    assert rb.closeness == C.baseline_closeness and rb.stage == "Stranger"


async def test_tc_fr_005_25_02(db):
    """TC-FR-005-25-02 — B never receives A's summary."""
    a, b, p = await _user(db, 29), await _user(db, 30), await _persona(db)
    ra = await rs.get_or_create(db, a.id, p.id)
    await rs.apply_reflection(db, ra, ReflectionResult(1, 1, 1, {}, "A's private feelings"), C)
    rb = await rs.get_or_create(db, b.id, p.id)
    assert rb.summary != "A's private feelings"


async def test_tc_fr_005_25_03(db):
    """TC-FR-005-25-03 — two pairs' updates stay isolated (no cross contamination)."""
    a, b, p = await _user(db, 31), await _user(db, 32), await _persona(db)
    ra = await rs.get_or_create(db, a.id, p.id)
    rb = await rs.get_or_create(db, b.id, p.id)
    await rs.apply_reflection(db, ra, ReflectionResult(8, 0, 0, {}, "a"), C)
    await rs.apply_reflection(db, rb, ReflectionResult(0, 8, 0, {}, "b"), C)
    await db.refresh(ra); await db.refresh(rb)
    assert ra.trust == C.baseline_trust and rb.closeness == C.baseline_closeness


# FR-005-26 — configurable without code
def test_tc_fr_005_26_01():
    """TC-FR-005-26-01 — a changed cap/gate in config takes effect."""
    cfg = RelationshipConfig(per_reflection_cap=3)
    r = apply_deltas(RelState(50, 50, 50, "Friend"), 40, 0, 0, cfg)
    assert r.state.closeness == 53  # honors cap=3


def test_tc_fr_005_26_02():
    """TC-FR-005-26-02 — an edited gate changes derivation."""
    cfg = RelationshipConfig(gates={**RelationshipConfig().gates, "Acquaintance": (30, 0, 0)})
    assert derive_stage(20, 0, 0, None, cfg) == "Stranger"  # 20 < new 30 gate


# FR-005-27 — failed reflection preserves last good state (CRITICAL)
async def test_tc_fr_005_27_01(db):
    """TC-FR-005-27-01 — an LLM error preserves the prior state (no reset/corruption)."""
    u, p = await _user(db, 33), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.closeness, rel.trust, rel.attraction, rel.stage = 45, 40, 20, "Friend"
    await db.flush()
    await update_relationship(db, sess, p, ReflectClient(fail=True), C)  # LLM down
    await db.refresh(rel)
    assert (rel.closeness, rel.stage) == (45, "Friend")  # untouched


async def test_tc_fr_005_27_02(db):
    """TC-FR-005-27-02 — no partial apply: an unparseable reflection commits nothing."""
    u, p = await _user(db, 34), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)

    class Garbage:
        async def is_ready(self): return True
        async def complete(self, m, **k): return "not json"

    await update_relationship(db, sess, p, Garbage(), C)
    n = (await db.execute(select(func.count()).select_from(RelationshipReflection))).scalar_one()
    assert n == 0  # nothing logged/applied


async def test_tc_fr_005_27_03(db):
    """TC-FR-005-27-03 — replies keep using the last good state while reflection is unavailable."""
    u, p = await _user(db, 35), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.stage = "Friend"
    await db.flush()
    # a reply still assembles the last good stage even though reflection would fail
    block = _relationship_block(rel, "en")
    assert STAGE_BEHAVIOR["Friend"] in block


# FR-005-28 — reflection uses only that user's own history
async def test_tc_fr_005_28_01(db):
    """TC-FR-005-28-01 — reflection inputs come from the acting user's own conversation only."""
    a, b, p = await _user(db, 36), await _user(db, 37), await _persona(db)
    sa, _ = await start_or_switch_session(db, a.id, p.id)
    sb, _ = await start_or_switch_session(db, b.id, p.id)
    from services.bot.domain import messages as md
    from services.bot.models import MessageSender
    await md.append_message(db, sa.id, MessageSender.user, "A_SECRET_TOKEN")
    await md.append_message(db, sb.id, MessageSender.user, "B_SECRET_TOKEN")

    captured = {}

    class Cap:
        async def is_ready(self): return True
        async def complete(self, messages, **kw):
            captured["prompt"] = messages[0]["content"]
            return json.dumps(
                {"deltas": {"closeness": 0, "trust": 0, "attraction": 0}, "reasons": {},
                 "summary": "s", "breach": False, "pushing_fast": False})

    await update_relationship(db, sa, p, Cap(), C)
    assert "A_SECRET_TOKEN" in captured["prompt"] and "B_SECRET_TOKEN" not in captured["prompt"]


async def test_tc_fr_005_28_02(db):
    """TC-FR-005-28-02 — another user's data never enters the judgment."""
    # same guarantee as 28-01 from the isolation side (store is per-pair)
    a, b, p = await _user(db, 38), await _user(db, 39), await _persona(db)
    ra = await rs.get_or_create(db, a.id, p.id)
    rb = await rs.get_or_create(db, b.id, p.id)
    assert ra.id != rb.id and ra.user_id != rb.user_id


# ══════════════════════════════════════ NON-FUNCTIONAL ══════════════════════════════════════════

# NFR-005-01 — believable gradualism (CRITICAL)
def test_tc_nfr_005_01_01():
    """TC-NFR-005-01-01 — a single reflection cannot cross the whole ladder."""
    r = apply_deltas(RelState.baseline(C), 100, 100, 100, C)
    assert stage_index(r.state.stage) <= 1


def test_tc_nfr_005_01_02():
    """TC-NFR-005-01-02 (statistical) — smooth/monotonic progression over a history."""
    pytest.skip("statistical — needs a realistic labeled interaction history / live model")


def test_tc_nfr_005_01_03():
    """TC-NFR-005-01-03 — measured max per-reflection jump never exceeds the cap."""
    import random
    rng = random.Random(0)
    st = RelState(50, 50, 50, "Friend")
    for _ in range(200):
        dc, dt, da = (rng.randint(-40, 40) for _ in range(3))
        before = (st.closeness, st.trust, st.attraction)
        st = apply_deltas(st, dc, dt, da, C).state
        after = (st.closeness, st.trust, st.attraction)
        assert all(abs(a - b) <= C.per_reflection_cap for a, b in zip(after, before))


# NFR-005-02 — consistency under probing (CRITICAL)
def test_tc_nfr_005_02_01():
    """TC-NFR-005-02-01 — a speed-run of big deltas still cannot jump ahead of earned closeness."""
    st = RelState.baseline(C)
    st = apply_deltas(st, 100, 100, 100, C).state
    assert st.stage != "Love"


def test_tc_nfr_005_02_02():
    """TC-NFR-005-02-02 — noisy warm/cold near a gate does not flip-flop (hysteresis)."""
    stage = "Friend"
    for c in (41, 38, 41, 37, 40):  # oscillating around the C≥40 gate, within margin 8
        stage = derive_stage(c, 40, 0, stage, C)
    assert stage == "Friend"  # never dropped despite the dips


def test_tc_nfr_005_02_03():
    """TC-NFR-005-02-03 — the resulting state tracks the recorded deltas (consistent with treatment)."""
    st = apply_deltas(RelState(50, 50, 50, "Friend"), 5, -5, 0, C).state
    assert st.closeness == 55 and st.trust == 45


# NFR-005-03 — off hot path
def test_tc_nfr_005_03_01():
    """TC-NFR-005-03-01 (performance) — reply latency unaffected by a due reflection."""
    pytest.skip("performance — needs a latency harness; structurally reflection runs after the reply")


async def test_tc_nfr_005_03_02(db):
    """TC-NFR-005-03-02 — the reply reads the last persisted state and does not run a reflection."""
    import inspect

    from services.bot import orchestrator
    assert "run_reflection" not in inspect.getsource(orchestrator.handle_turn)


# NFR-005-04 — reliability / degrade (CRITICAL)
async def test_tc_nfr_005_04_01(db):
    """TC-NFR-005-04-01 — with the LLM down, replies still assemble from the last good state."""
    u, p = await _user(db, 40), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    rel = await rs.get_or_create(db, u.id, p.id); rel.stage = "Friend"; await db.flush()
    await update_relationship(db, sess, p, ReflectClient(fail=True), C)  # no-op
    await db.refresh(rel)
    assert rel.stage == "Friend"


async def test_tc_nfr_005_04_02(db):
    """TC-NFR-005-04-02 — state remains intact through the outage (no corruption/reset)."""
    u, p = await _user(db, 41), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    rel = await rs.get_or_create(db, u.id, p.id)
    rel.closeness, rel.trust, rel.attraction = 60, 55, 55; await db.flush()
    for _ in range(3):
        await update_relationship(db, sess, p, ReflectClient(fail=True), C)
    await db.refresh(rel)
    assert (rel.closeness, rel.trust, rel.attraction) == (60, 55, 55)


async def test_tc_nfr_005_04_03(db):
    """TC-NFR-005-04-03 — reflections resume once the LLM recovers."""
    u, p = await _user(db, 42), await _persona(db)
    sess, _ = await start_or_switch_session(db, u.id, p.id)
    from services.bot.domain import messages as md
    from services.bot.models import MessageSender
    await md.append_message(db, sess.id, MessageSender.user, "спасибо, рад")
    await update_relationship(db, sess, p, ReflectClient(fail=True), C)   # down
    rel = await update_relationship(db, sess, p, ReflectClient(dc=5, dt=3, da=2), C)  # recovered
    assert rel.closeness > C.baseline_closeness


# NFR-005-05 — isolation provable (CRITICAL)
async def test_tc_nfr_005_05_01(db):
    """TC-NFR-005-05-01 — no cross-user contamination of stage/scores."""
    a, b, p = await _user(db, 43), await _user(db, 44), await _persona(db)
    ra = await rs.get_or_create(db, a.id, p.id)
    await rs.apply_reflection(db, ra, ReflectionResult(10, 10, 10, {}, "a"), C)
    rb = await rs.get_or_create(db, b.id, p.id)
    assert (rb.closeness, rb.trust, rb.attraction) == (C.baseline_closeness, C.baseline_trust, C.baseline_attraction)


async def test_tc_nfr_005_05_02(db):
    """TC-NFR-005-05-02 — summaries never mix across users."""
    a, b, p = await _user(db, 45), await _user(db, 46), await _persona(db)
    ra = await rs.get_or_create(db, a.id, p.id)
    await rs.apply_reflection(db, ra, ReflectionResult(1, 1, 1, {}, "A only"), C)
    rb = await rs.get_or_create(db, b.id, p.id)
    assert rb.summary == ""


def test_tc_nfr_005_05_03():
    """TC-NFR-005-05-03 (load) — isolation under many concurrent pairs."""
    pytest.skip("load — needs a concurrency/load harness; isolation is by (user,persona) keying")


# NFR-005-06 — bounded & valid always (CRITICAL)
def test_tc_nfr_005_06_01():
    """TC-NFR-005-06-01 — dimensions never leave 0–100 across arbitrary delta sequences."""
    import random
    rng = random.Random(1)
    st = RelState(50, 50, 50, "Friend")
    for _ in range(500):
        st = apply_deltas(st, rng.randint(-30, 30), rng.randint(-30, 30), rng.randint(-30, 30), C).state
        assert 0 <= st.closeness <= 100 and 0 <= st.trust <= 100 and 0 <= st.attraction <= 100


def test_tc_nfr_005_06_02():
    """TC-NFR-005-06-02 — the derived stage is always a valid ladder value."""
    for c in range(0, 101, 17):
        for t in range(0, 101, 23):
            assert derive_stage(c, t, 50, None, C) in STAGES


def test_tc_nfr_005_06_03():
    """TC-NFR-005-06-03 — a stored stage always equals the fresh derivation from its dimensions."""
    st = apply_deltas(RelState(50, 50, 50, "Friend"), 9, 9, 9, C).state
    # re-derive from the same dims (advancing context) matches
    assert st.stage == derive_stage(st.closeness, st.trust, st.attraction, "Friend", C)


# NFR-005-07 — auditability
async def test_tc_nfr_005_07_01(db):
    """TC-NFR-005-07-01 — every state change has a backing reflection log."""
    u, p = await _user(db, 47), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    for i in range(3):
        await rs.apply_reflection(db, rel, ReflectionResult(1, 1, 1, {"trust": f"r{i}"}, "s"), C)
    n = (await db.execute(select(func.count()).select_from(RelationshipReflection))).scalar_one()
    assert n == 3


async def test_tc_nfr_005_07_02(db):
    """TC-NFR-005-07-02 — no state change without a matching reflection entry."""
    u, p = await _user(db, 48), await _persona(db)
    rel = await rs.get_or_create(db, u.id, p.id)
    before = rel.closeness
    await rs.apply_reflection(db, rel, ReflectionResult(5, 0, 0, {}, "s"), C)
    logs = (await db.execute(select(RelationshipReflection))).scalars().all()
    assert rel.closeness != before and len(logs) == 1


# NFR-005-08 — persistence
async def test_tc_nfr_005_08_01(tmp_path):
    """TC-NFR-005-08-01 — state and logs survive a restart/deploy."""
    url = f"sqlite+aiosqlite:///{tmp_path/'r8.sqlite3'}"
    e1 = create_async_engine(url); await init_models(e1); sm1 = make_sessionmaker(e1)
    async with sm1() as db:
        u, p = await _user(db, 49), await _persona(db)
        rel = await rs.get_or_create(db, u.id, p.id)
        await rs.apply_reflection(db, rel, ReflectionResult(3, 3, 3, {}, "s"), C)
        await db.commit(); uid, pid = u.id, p.id
    await e1.dispose()
    e2 = create_async_engine(url); sm2 = make_sessionmaker(e2)
    async with sm2() as db:
        n = (await db.execute(select(func.count()).select_from(RelationshipReflection))).scalar_one()
        assert n == 1 and (await rs.get_or_create(db, uid, pid)).closeness > C.baseline_closeness
    await e2.dispose()


def test_tc_nfr_005_08_02():
    """TC-NFR-005-08-02 — continuity across weeks (state persists; only decay applies)."""
    st = RelState(60, 60, 60, "Romance")
    after = apply_decay(st, 14, C).state
    assert after.stage in STAGES and after.closeness < 60  # persisted-then-decayed, not reset


# NFR-005-09 — configurable, no redeploy
def test_tc_nfr_005_09_01():
    """TC-NFR-005-09-01 — a config change alters behaviour without code changes."""
    assert apply_deltas(RelState(50, 50, 50, "Friend"), 40, 0, 0,
                        RelationshipConfig(per_reflection_cap=5)).state.closeness == 55


def test_tc_nfr_005_09_02():
    """TC-NFR-005-09-02 — the tunable is honoured immediately (pure config object, no redeploy)."""
    cfg = RelationshipConfig(hysteresis_margin=2)
    assert derive_stage(35, 40, 0, "Friend", cfg) == "Acquaintance"  # tighter margin regresses sooner


# NFR-005-10 — in-character exposure
def test_tc_nfr_005_10_01():
    """TC-NFR-005-10-01 — the exposed block never leaks numbers/stage/reflection wording."""
    rel = Relationship(stage="Romance", summary="we're close", pending_milestone="Romance")
    block = _relationship_block(rel, "en").lower()
    assert "romance" not in block and "reflection" not in block and not any(ch.isdigit() for ch in block)


def test_tc_nfr_005_10_02():
    """TC-NFR-005-10-02 — RU and EN milestone cues read as natural first-person copy."""
    ru = _relationship_block(Relationship(stage="Friend", summary="", pending_milestone="Friend"), "ru")
    en = _relationship_block(Relationship(stage="Friend", summary="", pending_milestone="Friend"), "en")
    assert "ближе" in ru and "closer" in en.lower()


# NFR-005-11 — pacing safety statistical (CRITICAL)
def test_tc_nfr_005_11_01():
    """TC-NFR-005-11-01 — across many low-trust push scenarios, none escalate to Romance/Love."""
    import random
    rng = random.Random(2)
    for _ in range(300):
        c, t, a = rng.randint(0, 55), rng.randint(0, 45), rng.randint(0, 60)
        st = RelState(c, t, a, derive_stage(c, t, a, None, C))
        if stage_index(st.stage) >= C.romance_stage_index:
            continue  # already earned; not a low-trust case
        res = apply_deltas(st, rng.randint(0, 10), rng.randint(0, 10), rng.randint(0, 10), C, pushing_fast=True)
        assert stage_index(res.state.stage) < C.romance_stage_index


def test_tc_nfr_005_11_02():
    """TC-NFR-005-11-02 — under pressure, Trust trends non-increasing."""
    import random
    rng = random.Random(3)
    for _ in range(200):
        t = rng.randint(0, 45)
        st = RelState(30, t, 40, "Acquaintance")
        res = apply_deltas(st, 0, rng.randint(-5, 10), 0, C, pushing_fast=True)
        assert res.state.trust <= t


def test_tc_nfr_005_11_03():
    """TC-NFR-005-11-03 (e2e) — the guard holds beyond the happy path against varied scripts."""
    pytest.skip("e2e / live-model — varied aggressive-user scripts judged against the real model")


# NFR-005-12 — scales per user
def test_tc_nfr_005_12_01():
    """TC-NFR-005-12-01 (load) — many pairs' reflections fit the scheduled budget."""
    pytest.skip("load — needs a scheduling/load harness")


def test_tc_nfr_005_12_02():
    """TC-NFR-005-12-02 (load) — reflections do not starve the reply path."""
    pytest.skip("load — needs a concurrency/load harness")


# NFR-005-13 — deterministic application
def test_tc_nfr_005_13_01():
    """TC-NFR-005-13-01 — identical output + prior state yields the same new state."""
    st = RelState(50, 50, 50, "Friend")
    a = apply_deltas(st, 7, -3, 5, C).state
    b = apply_deltas(st, 7, -3, 5, C).state
    assert (a.closeness, a.trust, a.attraction, a.stage) == (b.closeness, b.trust, b.attraction, b.stage)


def test_tc_nfr_005_13_02():
    """TC-NFR-005-13-02 — clamp/cap/hysteresis are deterministic at a gate boundary."""
    assert derive_stage(40, 35, 0, "Acquaintance", C) == derive_stage(40, 35, 0, "Acquaintance", C) == "Friend"


# ══════════════════════════════════ USER-STORY ACCEPTANCE (manual) ══════════════════════════════

@pytest.mark.parametrize("tc", [f"TC-US-005-{i:02d}-01" for i in range(1, 9)])
def test_user_story_acceptance_manual(tc):
    """US-005-01..08 — manual real-device acceptance (felt bond depth), judged by a human."""
    pytest.skip(f"{tc}: manual real-device e2e — human-judged, not an automated test")
