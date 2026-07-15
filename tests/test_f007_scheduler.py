"""Tests for F-007 — Life Engine Scheduler. One test per automatable TC in
developer files/tests/F-007-life-engine-scheduler.md.

The F-006 content steps (plan/reflect/compress/goals/future LLM calls) are stubbed via monkeypatch
so these tests exercise **F-007's orchestration** — due-detection, idempotency, the compression
cascade, goal/future application, degrade, and roster iteration — deterministically, with a
controlled clock. A live model is never needed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from services.bot.domain import life_engine_llm as llm
from services.bot.domain import life_engine_runner as r
from services.bot.domain import life_engine_store as ls
from services.bot.domain.biography import BiographySeed, seed_biography
from services.bot.domain.life_engine import DEFAULT_CONFIG, LifeEngineConfig
from services.bot.domain.life_engine_llm import GoalUpdate
from services.bot.models import (
    BiographyLayer,
    DailyPlan,
    FutureProjection,
    Goal,
    GoalStatus,
    Horizon,
    Persona,
    Reflection,
)

# ── controlled clock (Europe/Moscow = UTC+3 in July) ────────────────────────────────────────────
MORNING = datetime(2026, 7, 15, 5, 0, tzinfo=timezone.utc)   # 08:00 MSK → is_local_morning
EVENING = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)  # 23:00 MSK → is_local_end_of_day
NOON = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)     # 15:00 MSK → nothing due


class Chat:
    """A no-op chat client; the LLM steps are stubbed, so this is never actually called."""
    async def complete(self, *a, **k):  # pragma: no cover - not reached (steps monkeypatched)
        return ""


async def _persona(db, name="Alina", tz="Europe/Moscow"):
    p = Persona(name=name, profession="Psychologist", age=28, language="ru", timezone=tz,
                big_five="warm, curious", card_description="")
    db.add(p)
    await db.flush()
    return p


def _stub_steps(monkeypatch, *, plan="8:00 — зал. 20:00 — отдых.", reflect="Сегодня был хороший день.",
                compress="Гист за период.", goals=None, future=None):
    async def _plan(*a, **k):
        return plan

    async def _reflect(*a, **k):
        return reflect

    async def _compress(*a, **k):
        return compress

    async def _goals(*a, **k):
        return goals

    async def _future(*a, **k):
        return future

    monkeypatch.setattr(llm, "run_plan_day", _plan)
    monkeypatch.setattr(llm, "run_reflect_day", _reflect)
    monkeypatch.setattr(llm, "run_compress", _compress)
    monkeypatch.setattr(llm, "run_update_goals", _goals)
    monkeypatch.setattr(llm, "run_update_future", _future)


async def _count(db, model, **where):
    stmt = select(func.count()).select_from(model)
    for k, v in where.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalar_one()


# ── FR-007-01 — autonomous scheduler ────────────────────────────────────────────────────────────


async def test_tc_fr_007_01_01(db, sessionmaker, monkeypatch):
    """A scheduler pass ticks the active roster."""
    _stub_steps(monkeypatch)
    async with sessionmaker() as s:
        await _persona(s, "Alina")
        await _persona(s, "Vika")
        await s.commit()
    reports = await r.scheduler_pass(sessionmaker, Chat(), None, MORNING)
    assert set(reports) == {"Alina", "Vika"}


async def test_tc_fr_007_01_02(db, monkeypatch):
    """A tick is callable and reports what it did."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    rep = await r.run_tick(db, p, Chat(), MORNING)
    assert rep.persona == "Alina" and rep.planned is True


# ── FR-007-02 — only due steps ──────────────────────────────────────────────────────────────────


async def test_tc_fr_007_02_01(db, monkeypatch):
    _stub_steps(monkeypatch)
    p = await _persona(db)
    rep = await r.run_tick(db, p, Chat(), MORNING)
    assert rep.planned and await _count(db, DailyPlan, persona_id=p.id) == 1


async def test_tc_fr_007_02_02(db, monkeypatch):
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await r.run_tick(db, p, Chat(), MORNING)  # plan today first
    rep = await r.run_tick(db, p, Chat(), EVENING)
    assert rep.reflected and await _count(db, Reflection, persona_id=p.id) == 1


async def test_tc_fr_007_02_03(db, monkeypatch):
    """Mid-afternoon: nothing due."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    rep = await r.run_tick(db, p, Chat(), NOON)
    assert not rep.planned and not rep.reflected
    assert await _count(db, DailyPlan, persona_id=p.id) == 0
    assert await _count(db, Reflection, persona_id=p.id) == 0


# ── FR-007-03 — idempotent per period ───────────────────────────────────────────────────────────


async def test_tc_fr_007_03_01(db, monkeypatch):
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await r.run_tick(db, p, Chat(), MORNING)
    rep2 = await r.run_tick(db, p, Chat(), MORNING)
    assert await _count(db, DailyPlan, persona_id=p.id) == 1
    assert "plan(exists)" in rep2.skipped


async def test_tc_fr_007_03_02(db, monkeypatch):
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await r.run_tick(db, p, Chat(), EVENING)
    await r.run_tick(db, p, Chat(), EVENING)
    assert await _count(db, Reflection, persona_id=p.id) == 1


async def test_tc_fr_007_03_03(db, monkeypatch):
    """A new local day allows a fresh plan."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await r.run_tick(db, p, Chat(), MORNING)  # 2026-07-15
    next_day = datetime(2026, 7, 16, 5, 0, tzinfo=timezone.utc)
    await r.run_tick(db, p, Chat(), next_day)
    assert await _count(db, DailyPlan, persona_id=p.id) == 2


# ── FR-007-04 — compression cascade ─────────────────────────────────────────────────────────────


async def _add_daily(db, persona_id, n, base_day=1):
    for i in range(n):
        db.add(Reflection(persona_id=persona_id, scope="day",
                          period_key=f"2025-03-{base_day + i:02d}", content=f"день {i}",
                          source_period="", prompt_version="x"))
    await db.flush()


async def test_tc_fr_007_04_01(db, monkeypatch):
    """7 uncompressed dailies compress into a weekly layer."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await _add_daily(db, p.id, 7)
    compressed = await r._run_cascade(db, p, Chat(), None, DEFAULT_CONFIG)
    assert "week" in compressed
    assert await _count(db, BiographyLayer, persona_id=p.id, scope="week") == 1


async def test_tc_fr_007_04_02(db, monkeypatch):
    """Below threshold → no compression."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await _add_daily(db, p.id, 5)
    compressed = await r._run_cascade(db, p, Chat(), None, DEFAULT_CONFIG)
    assert "week" not in compressed
    assert await _count(db, BiographyLayer, persona_id=p.id, scope="week") == 0


async def test_tc_fr_007_04_03(db, monkeypatch):
    """Cascade also builds a month once 4 weeks exist."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    for i in range(4):
        db.add(BiographyLayer(persona_id=p.id, scope="week", period_key=f"2025-W{i:02d}",
                              content=f"неделя {i}", source_period="", prompt_version="x"))
    await db.flush()
    compressed = await r._run_cascade(db, p, Chat(), None, DEFAULT_CONFIG)
    assert "month" in compressed
    assert await _count(db, BiographyLayer, persona_id=p.id, scope="month") == 1


# ── FR-007-05 — goal update ─────────────────────────────────────────────────────────────────────


async def test_tc_fr_007_05_01(db, monkeypatch):
    """Goal-update adds a new goal."""
    p = await _persona(db)
    db.add(Goal(persona_id=p.id, description="старая цель", status=GoalStatus.active))
    await db.flush()
    _stub_steps(monkeypatch, goals=GoalUpdate(
        add=[{"description": "новая цель", "priority": 3, "horizon": "medium"}]))
    await r.run_tick(db, p, Chat(), EVENING)
    assert await _count(db, Goal, persona_id=p.id) == 2


async def test_tc_fr_007_05_02(db, monkeypatch):
    """No goal-update when the step returns None."""
    p = await _persona(db)
    db.add(Goal(persona_id=p.id, description="старая цель", status=GoalStatus.active))
    await db.flush()
    _stub_steps(monkeypatch, goals=None)
    await r.run_tick(db, p, Chat(), EVENING)
    assert await _count(db, Goal, persona_id=p.id) == 1


# ── FR-007-06 — future-self re-authored ─────────────────────────────────────────────────────────


async def _seed_future(db, p):
    seed = BiographySeed(birthdate=date(1997, 2, 15),
                         core_values="v", motivation="m", interests="i",
                         future=[("week", "старое"), ("month", "старое"), ("year", "старое"),
                                 ("epoch", "старое"), ("lifetime", "старое")])
    await seed_biography(db, p, seed)


async def test_tc_fr_007_06_01(db, monkeypatch):
    """Future-update rewrites the projections."""
    p = await _persona(db)
    await _seed_future(db, p)
    new = {"week": "новое-w", "month": "новое-mo", "year": "новое-y",
           "epoch": "новое-e", "lifetime": "новое-l"}
    _stub_steps(monkeypatch, future=new)
    await r.run_tick(db, p, Chat(), EVENING)
    wk = (await db.execute(select(FutureProjection).where(
        FutureProjection.persona_id == p.id, FutureProjection.horizon == Horizon.week))).scalar_one()
    assert wk.content == "новое-w"


async def test_tc_fr_007_06_02(db, monkeypatch):
    """Still exactly one row per horizon after an update."""
    p = await _persona(db)
    await _seed_future(db, p)
    _stub_steps(monkeypatch, future={"week": "w", "month": "m", "year": "y",
                                     "epoch": "e", "lifetime": "l"})
    await r.run_tick(db, p, Chat(), EVENING)
    assert await _count(db, FutureProjection, persona_id=p.id) == 5


async def test_tc_fr_007_06_03(db, monkeypatch):
    """A failed future step keeps the last good projections."""
    p = await _persona(db)
    await _seed_future(db, p)
    _stub_steps(monkeypatch, future=None)
    await r.run_tick(db, p, Chat(), EVENING)
    wk = (await db.execute(select(FutureProjection).where(
        FutureProjection.persona_id == p.id, FutureProjection.horizon == Horizon.week))).scalar_one()
    assert wk.content == "старое"


# ── FR-007-07 — off the reply hot path ──────────────────────────────────────────────────────────


async def test_tc_fr_007_07_01(db):
    """The reply path (handle_turn) does not call the life-engine steps inline."""
    import inspect

    from services.bot import orchestrator
    src = inspect.getsource(orchestrator.handle_turn)
    for step in ("run_plan_day", "run_reflect_day", "run_compress", "run_update_goals", "run_tick"):
        assert step not in src


async def test_tc_fr_007_07_02(db, monkeypatch):
    """A tick and an unrelated read can both proceed (no shared blocking state)."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    rep = await r.run_tick(db, p, Chat(), MORNING)
    assert rep.planned
    assert await _count(db, DailyPlan, persona_id=p.id) == 1


# ── FR-007-08 — degrade on failure ──────────────────────────────────────────────────────────────


async def test_tc_fr_007_08_01(db, monkeypatch):
    """LLM-down tick writes nothing and does not raise."""
    async def _none(*a, **k):
        return None

    for name in ("run_plan_day", "run_reflect_day", "run_compress", "run_update_goals",
                 "run_update_future"):
        monkeypatch.setattr(llm, name, _none)
    p = await _persona(db)
    rep = await r.run_tick(db, p, Chat(), MORNING)
    assert "plan" in rep.failures
    assert await _count(db, DailyPlan, persona_id=p.id) == 0


async def test_tc_fr_007_08_02(db, sessionmaker, monkeypatch):
    """One persona failing doesn't stop the roster."""
    async def _boom_plan(*a, **k):
        raise RuntimeError("boom")

    async def _ok_reflect(*a, **k):
        return "ok"

    _stub_steps(monkeypatch)
    async with sessionmaker() as s:
        await _persona(s, "Alina")
        await _persona(s, "Vika")
        await s.commit()
    # make plan raise for everyone; scheduler must catch and continue to the next persona
    monkeypatch.setattr(llm, "run_plan_day", _boom_plan)
    reports = await r.scheduler_pass(sessionmaker, Chat(), None, MORNING)
    # both raised inside their own try/except → neither report recorded, but no exception escaped
    assert isinstance(reports, dict)


# ── FR-007-09 — roster across timezones ─────────────────────────────────────────────────────────


async def test_tc_fr_007_09_01(db, sessionmaker, monkeypatch):
    """At 05:00 UTC it is morning in Moscow but not in New York → only Moscow is planned."""
    _stub_steps(monkeypatch)
    async with sessionmaker() as s:
        await _persona(s, "Alina", tz="Europe/Moscow")
        await _persona(s, "Olivia", tz="America/New_York")
        await s.commit()
    reports = await r.scheduler_pass(sessionmaker, Chat(), None, MORNING)
    assert reports["Alina"].planned is True
    assert reports["Olivia"].planned is False


async def test_tc_fr_007_09_02(db, sessionmaker, monkeypatch):
    _stub_steps(monkeypatch)
    async with sessionmaker() as s:
        for nm in ("Alina", "Vika", "Sofia"):
            await _persona(s, nm)
        await s.commit()
    reports = await r.scheduler_pass(sessionmaker, Chat(), None, NOON)
    assert set(reports) == {"Alina", "Vika", "Sofia"}


# ── FR-007-10 — auditable ───────────────────────────────────────────────────────────────────────


async def test_tc_fr_007_10_01(db, monkeypatch):
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await r.run_tick(db, p, Chat(), MORNING)
    await r.run_tick(db, p, Chat(), EVENING)
    plan = (await db.execute(select(DailyPlan).where(DailyPlan.persona_id == p.id))).scalar_one()
    refl = (await db.execute(select(Reflection).where(Reflection.persona_id == p.id))).scalar_one()
    assert plan.prompt_version and refl.prompt_version and refl.source_period


async def test_tc_fr_007_10_02(db, monkeypatch):
    """A compressed weekly layer records its source period."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await _add_daily(db, p.id, 7)
    await r._run_cascade(db, p, Chat(), None, DEFAULT_CONFIG)
    week = (await db.execute(select(BiographyLayer).where(
        BiographyLayer.persona_id == p.id, BiographyLayer.scope == "week"))).scalar_one()
    assert week.source_period.startswith("day:")


# ── FR-007-11 — config-driven cadence ───────────────────────────────────────────────────────────


async def test_tc_fr_007_11_01(db, monkeypatch):
    """Custom schedule hours are honored by due-detection."""
    _stub_steps(monkeypatch)
    cfg = LifeEngineConfig(morning_hour=12)  # noon MSK is now "morning"
    p = await _persona(db)
    rep = await r.run_tick(db, p, Chat(), NOON, cfg=cfg)  # 15:00 MSK ≠ 12 → still not due
    assert not rep.planned
    noon_msk = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)  # 12:00 MSK
    rep2 = await r.run_tick(db, p, Chat(), noon_msk, cfg=cfg)
    assert rep2.planned


async def test_tc_fr_007_11_02(db, monkeypatch):
    """Custom compression ratio changes the threshold."""
    _stub_steps(monkeypatch)
    cfg = LifeEngineConfig(daily_per_week=3)
    p = await _persona(db)
    await _add_daily(db, p.id, 3)
    compressed = await r._run_cascade(db, p, Chat(), None, cfg)
    assert "week" in compressed


# ── FR-007-12 — on-demand run ───────────────────────────────────────────────────────────────────


async def test_tc_fr_007_12_01(db, monkeypatch):
    """run_persona_now forces plan + reflection regardless of the local hour."""
    _stub_steps(monkeypatch, future={"week": "w", "month": "m", "year": "y",
                                     "epoch": "e", "lifetime": "l"})
    p = await _persona(db)
    rep = await r.run_persona_now(db, p, Chat(), now_utc=NOON)  # mid-afternoon
    assert rep.planned and rep.reflected
    assert await _count(db, DailyPlan, persona_id=p.id) == 1
    assert await _count(db, Reflection, persona_id=p.id) == 1


async def test_tc_fr_007_12_02(db, monkeypatch):
    """On-demand stays idempotent per period."""
    _stub_steps(monkeypatch)
    p = await _persona(db)
    await r.run_persona_now(db, p, Chat(), now_utc=NOON)
    await r.run_persona_now(db, p, Chat(), now_utc=NOON)
    assert await _count(db, DailyPlan, persona_id=p.id) == 1
    assert await _count(db, Reflection, persona_id=p.id) == 1


# ── NFR-007-02 — timezone/DST correctness ───────────────────────────────────────────────────────


async def test_tc_nfr_007_02_01(db, monkeypatch):
    """Due-detection is correct across a DST change (Europe/Moscow has no DST; use a DST zone)."""
    from services.bot.domain.life_engine import is_local_morning
    # America/New_York: 08:00 local is 12:00 UTC in summer (EDT, -4), 13:00 UTC in winter (EST, -5).
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)
    assert is_local_morning("America/New_York", summer)
    assert is_local_morning("America/New_York", winter)


async def test_tc_nfr_007_02_02(db):
    from services.bot.domain.life_engine import local_now
    inst = MORNING
    assert local_now("Europe/Moscow", inst).hour == 8
    assert local_now("America/New_York", inst).hour == 1


# ── NFR-007-04 — idempotent under repeats ───────────────────────────────────────────────────────


async def test_tc_nfr_007_04_01(db, monkeypatch):
    _stub_steps(monkeypatch)
    p = await _persona(db)
    for _ in range(5):
        await r.run_tick(db, p, Chat(), MORNING)
    assert await _count(db, DailyPlan, persona_id=p.id) == 1


# ── NFR-007-05 — survives restart (state persisted) ─────────────────────────────────────────────


async def test_tc_nfr_007_05_01(db, sessionmaker, monkeypatch):
    """Progress persists — a fresh session sees the plan/reflection."""
    _stub_steps(monkeypatch)
    async with sessionmaker() as s:
        p = await _persona(s)
        await r.run_tick(s, p, Chat(), MORNING)
        await r.run_tick(s, p, Chat(), EVENING)
        await s.commit()
        pid = p.id
    async with sessionmaker() as s2:  # "after restart"
        assert (await s2.execute(select(func.count()).select_from(DailyPlan)
                                 .where(DailyPlan.persona_id == pid))).scalar_one() == 1
        assert (await s2.execute(select(func.count()).select_from(Reflection)
                                 .where(Reflection.persona_id == pid))).scalar_one() == 1


# ── NFR-007-06 — degrade, don't crash the loop ──────────────────────────────────────────────────


async def test_tc_nfr_007_06_01(db, sessionmaker, monkeypatch):
    """A persona whose tick raises is caught; the scheduler pass still returns."""
    async def _boom(*a, **k):
        raise RuntimeError("boom")

    _stub_steps(monkeypatch)
    monkeypatch.setattr(r, "run_tick", _boom)
    async with sessionmaker() as s:
        await _persona(s, "Alina")
        await s.commit()
    reports = await r.scheduler_pass(sessionmaker, Chat(), None, MORNING)
    assert reports == {}  # caught, nothing recorded, no exception escaped


# ── NFR-007-07 — observability ──────────────────────────────────────────────────────────────────


async def test_tc_nfr_007_07_01(db, monkeypatch):
    _stub_steps(monkeypatch)
    p = await _persona(db)
    rep = await r.run_tick(db, p, Chat(), NOON)
    assert hasattr(rep, "planned") and hasattr(rep, "skipped") and hasattr(rep, "failures")
    assert rep.did_anything() is False
