"""Tests for the F-006 biography extension — seeded biography, persona-time identity & future-self.
One test per declared TC in developer files/tests/F-006-life-engine.md (FR-006-22..28, NFR-006-14/15).

All automated (fast, no live model): a fake biography vector index stands in for Qdrant so semantic
recall is exercised deterministically.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select

from services.bot.biographies.alina import ALINA
from services.bot.domain import biography as bio
from services.bot.domain.biography import (
    BiographySeed,
    assemble_biography_context,
    future_self_block,
    graded_biography_block,
    recall_biography,
    seed_biography,
)
from services.bot.domain.persona_prompt import build_system_prompt
from services.bot.domain.persona_time import age_phrase, age_years_days
from services.bot.models import BiographyLayer, FutureProjection, Horizon, Persona


# ── helpers ──────────────────────────────────────────────────────────────────────────────────


async def _persona(db, name="Alina", tz="Europe/Moscow", language="ru"):
    p = Persona(name=name, profession="Psychologist", age=28, language=language, timezone=tz,
                card_description="teaser", big_five="warm, curious")
    db.add(p)
    await db.flush()
    return p


class FakeBioIndex:
    """In-memory stand-in for the biography vector collection. Owner key = persona_id; search ranks
    by naive word-overlap so a 'childhood' query surfaces the childhood layer."""

    def __init__(self):
        self._points: list[tuple[int, int, str]] = []  # (owner, id, content)

    def index_fact(self, owner_id: int, point_id: int, content: str) -> None:
        self._points = [(o, i, c) for (o, i, c) in self._points if i != point_id]
        self._points.append((owner_id, point_id, content))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 3}

    def search(self, owner_id: int, query: str, k: int) -> list[int]:
        q = self._tokens(query)
        scored = [
            (len(q & self._tokens(c)), i)
            for (o, i, c) in self._points if o == owner_id
        ]
        scored = [(s, i) for (s, i) in scored if s > 0]
        scored.sort(reverse=True)
        return [i for _, i in scored[:k]]


async def _seed(db, index=None, seed=ALINA):
    p = await _persona(db)
    await seed_biography(db, p, seed, index)
    return p


async def _count(db, model, **where):
    stmt = select(func.count()).select_from(model)
    for k, v in where.items():
        stmt = stmt.where(getattr(model, k) == v)
    return (await db.execute(stmt)).scalar_one()


# ── FR-006-22 — seeded initial biography (idempotent) ───────────────────────────────────────────


async def test_tc_fr_006_22_01(db):
    """Seeding imports layers across every scope."""
    p = await _seed(db)
    scopes = {
        s for (s,) in (
            await db.execute(select(BiographyLayer.scope).where(BiographyLayer.persona_id == p.id))
        ).all()
    }
    assert {"epoch", "year", "month", "week", "day"} <= scopes


async def test_tc_fr_006_22_02(db):
    """Re-seeding does not duplicate layers."""
    p = await _persona(db)
    await seed_biography(db, p, ALINA)
    first = await _count(db, BiographyLayer, persona_id=p.id)
    counts = await seed_biography(db, p, ALINA)  # second import
    second = await _count(db, BiographyLayer, persona_id=p.id)
    assert first == second == len(ALINA.layers)
    assert counts["layers"] == 0


async def test_tc_fr_006_22_03(db):
    """Childhood/youth epoch anchors are present with content."""
    p = await _seed(db)
    rows = {
        pk: c for (pk, c) in (
            await db.execute(
                select(BiographyLayer.period_key, BiographyLayer.content).where(
                    BiographyLayer.persona_id == p.id, BiographyLayer.scope == "epoch")
            )
        ).all()
    }
    assert "childhood" in rows and rows["childhood"].strip()
    assert "youth" in rows and rows["youth"].strip()


# ── FR-006-23 — fixed anchors as structured fields ──────────────────────────────────────────────


async def test_tc_fr_006_23_01(db):
    p = await _seed(db)
    assert p.birthdate == date(1997, 2, 15)
    assert p.core_values.strip() and p.motivation.strip()


async def test_tc_fr_006_23_02(db):
    """Anchors appear verbatim in the identity prompt."""
    p = await _seed(db)
    prompt = build_system_prompt(p, date(2026, 7, 15))
    assert p.core_values.strip() in prompt
    assert p.motivation.strip() in prompt


# ── FR-006-24 — birthdate-derived, daily-versioned age ──────────────────────────────────────────


async def test_tc_fr_006_24_01(db):
    assert age_years_days(date(1990, 1, 1), date(2020, 1, 4)) == (30, 3)
    assert age_phrase(date(1990, 1, 1), date(2020, 1, 4)) == "30 years and 3 days"


async def test_tc_fr_006_24_02(db):
    """Exact on the birthday and the day after."""
    assert age_years_days(date(2000, 6, 15), date(2026, 6, 15)) == (26, 0)
    assert age_years_days(date(2000, 6, 15), date(2026, 6, 16)) == (26, 1)
    assert age_phrase(date(2000, 6, 15), date(2026, 6, 16)).endswith("1 day")


async def test_tc_fr_006_24_03(db):
    """Leap-day birthdate resolves without error in a non-leap year."""
    years, days = age_years_days(date(2000, 2, 29), date(2023, 3, 1))
    assert years == 23 and days >= 0


# ── FR-006-25 — evolving persona-time fields in identity ────────────────────────────────────────


async def test_tc_fr_006_25_01(db):
    p = await _seed(db)
    prompt = build_system_prompt(p, date(2026, 7, 15), goal_text="собрать сообщество девчонок")
    assert "фитнес" in prompt  # interests
    assert "собрать сообщество девчонок" in prompt  # current goal


async def test_tc_fr_006_25_02(db):
    """Changing interests changes the prompt (not a fixed anchor)."""
    p = await _seed(db)
    before = build_system_prompt(p, date(2026, 7, 15))
    p.interests = "сальса, керамика, бег"
    await db.flush()
    after = build_system_prompt(p, date(2026, 7, 15))
    assert "сальса" in after and "сальса" not in before


# ── FR-006-26 — future-self projections ─────────────────────────────────────────────────────────


async def test_tc_fr_006_26_01(db):
    p = await _seed(db)
    horizons = {
        h for (h,) in (
            await db.execute(
                select(FutureProjection.horizon).where(FutureProjection.persona_id == p.id))
        ).all()
    }
    assert horizons == {Horizon.week, Horizon.month, Horizon.year, Horizon.epoch, Horizon.lifetime}


async def test_tc_fr_006_26_02(db):
    """One row per horizon (upsert) after re-seed."""
    p = await _persona(db)
    await seed_biography(db, p, ALINA)
    await seed_biography(db, p, ALINA)
    assert await _count(db, FutureProjection, persona_id=p.id) == 5


# ── FR-006-27 — biography served into the reply context ─────────────────────────────────────────


async def test_tc_fr_006_27_01(db):
    """The always-on graded recency block spans coarse→fine scopes."""
    p = await _seed(db)
    block = await graded_biography_block(db, p.id)
    assert block is not None
    for marker in ("[epoch:", "[year:", "[month:", "[week:", "[day:"):
        assert marker in block


async def test_tc_fr_006_27_02(db):
    """A childhood question semantically retrieves the childhood epoch."""
    index = FakeBioIndex()
    p = await _seed(db, index)
    got = await recall_biography(db, p.id, "расскажи про своё детство и двор", index)
    assert any(l.period_key == "childhood" for l in got)
    # and it lands in the assembled context (childhood isn't in the graded 'current' epoch block)
    ctx = await assemble_biography_context(db, p, "какое у тебя было детство?", index)
    assert "Детство" in ctx


async def test_tc_fr_006_27_03(db):
    """Served biography is present and does not mutate the fixed anchors."""
    p = await _seed(db)
    values_before, motivation_before = p.core_values, p.motivation
    ctx = await assemble_biography_context(db, p, "как дела?", None)
    assert "Your life so far" in ctx
    assert p.core_values == values_before and p.motivation == motivation_before


# ── FR-006-28 — future-self served when relevant ────────────────────────────────────────────────


async def test_tc_fr_006_28_01(db):
    p = await _seed(db)
    fut = await future_self_block(db, p.id)
    assert fut is not None and "[week]" in fut and "[lifetime]" in fut
    ctx = await assemble_biography_context(db, p, "какие у тебя планы на будущее?", None)
    assert "heading" in ctx


async def test_tc_fr_006_28_02(db):
    """No projections → block absent, turn still assembles."""
    p = await _persona(db, name="Vika")  # no authored biography
    assert await future_self_block(db, p.id) is None
    ctx = await assemble_biography_context(db, p, "привет", None)
    assert ctx == ""  # graceful: nothing to add, no crash


# ── NFR-006-14 — persona-time determinism ───────────────────────────────────────────────────────


async def test_tc_nfr_006_14_01(db):
    """Same date + state → identical identity block."""
    p = await _seed(db)
    a = build_system_prompt(p, date(2026, 7, 15), goal_text="g")
    b = build_system_prompt(p, date(2026, 7, 15), goal_text="g")
    assert a == b


async def test_tc_nfr_006_14_02(db):
    """Next local day increments the derived age by exactly one day."""
    bd = date(1997, 2, 15)
    y0, d0 = age_years_days(bd, date(2026, 7, 15))
    y1, d1 = age_years_days(bd, date(2026, 7, 16))
    assert y1 == y0 and d1 == d0 + 1


# ── NFR-006-15 — bounded biography context ──────────────────────────────────────────────────────


async def test_tc_nfr_006_15_01(db):
    """Served biography stays under the length bound even with a long history."""
    p = await _persona(db)
    long_seed = BiographySeed(
        birthdate=date(1997, 2, 15), core_values="v", motivation="m", interests="i",
        layers=[("day", f"2025-01-{d:02d}", "сегодня был насыщенный день. " * 60)
                for d in range(1, 29)]
        + [("epoch", "current", "эпоха. " * 200), ("year", "2025", "год. " * 200)],
    )
    await seed_biography(db, p, long_seed)
    block = await graded_biography_block(db, p.id)
    assert block is not None and len(block) <= bio._CHAR_BOUND


async def test_tc_nfr_006_15_02(db):
    """The graded block caps the number of day layers included."""
    p = await _persona(db)
    seed = BiographySeed(
        birthdate=date(1997, 2, 15), core_values="v", motivation="m", interests="i",
        layers=[("day", f"2025-03-{d:02d}", f"день {d}") for d in range(1, 21)],
    )
    await seed_biography(db, p, seed)
    block = await graded_biography_block(db, p.id)
    assert block.count("[day:") <= bio._MAX_DAYS


# ── FR-006-29 — she always knows her own local clock ────────────────────────────────────────────


async def test_tc_fr_006_29_01(db):
    """TC-FR-006-29-01 — the turn context carries her local weekday + time (Moscow, fixed UTC)."""
    from datetime import datetime, timezone

    from services.bot.orchestrator import _local_time_block

    p = await _persona(db, name="Alina", tz="Europe/Moscow", language="ru")
    # 2026-07-16 16:00 UTC == 19:00 Moscow, Thursday
    block = _local_time_block(p, datetime(2026, 7, 16, 16, 0, tzinfo=timezone.utc))
    assert "четверг" in block and "19:0" in block


async def test_tc_fr_006_29_02(db):
    """TC-FR-006-29-02 — one UTC instant, per-persona correct local clocks (DST zones incl.)."""
    from datetime import datetime, timezone

    from services.bot.orchestrator import _local_time_block

    inst = datetime(2026, 7, 16, 16, 0, tzinfo=timezone.utc)
    msk = await _persona(db, name="Alina", tz="Europe/Moscow", language="ru")
    ny = await _persona(db, name="Olivia", tz="America/New_York", language="en")
    assert "19:0" in _local_time_block(msk, inst)          # UTC+3
    assert "12:0" in _local_time_block(ny, inst)           # EDT, UTC-4
    assert "Thursday" in _local_time_block(ny, inst)


# ── FR-006-30 — daily plans are time-addressable (HH:MM markers) ────────────────────────────────


async def test_tc_fr_006_30_01(db):
    """TC-FR-006-30-01 — the active plan prompt mandates HH:MM markers."""
    from services.bot.domain.life_engine import DEFAULT_CONFIG
    from services.bot.prompts import load_prompt

    assert DEFAULT_CONFIG.plan_prompt_version == "plan_day_v2"
    asset = load_prompt(DEFAULT_CONFIG.plan_prompt_version)
    assert "HH:MM" in asset and "mandatory" in asset


async def test_tc_fr_006_30_02(db):
    """TC-FR-006-30-02 — a marker-formatted plan returns the matching slot, not the whole text."""
    from datetime import datetime

    from services.bot.domain.life_engine import current_activity

    plan = ("8:00 — пробежка в парке у пруда. 13:30 — сессии с клиентками по Zoom. "
            "19:00-21:00 — репетиция саксофона дома.")
    got = current_activity(plan, datetime(2026, 7, 16, 19, 30))
    assert "саксофон" in got and "пробежка" not in got
