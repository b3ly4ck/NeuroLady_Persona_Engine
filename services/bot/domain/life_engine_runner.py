"""F-007 Life Engine Scheduler — the driver that actually runs the F-006 loop.

`run_tick` runs the *due* steps for one persona at a given instant (morning ⇒ plan; end-of-day ⇒
reflect → compression cascade → goal update → future-self update), idempotent per period and
degrade-safe. `scheduler_pass` ticks the whole active roster (one failure never stops the rest).
`run_scheduler` is the dev in-process loop; `run_persona_now` forces a full run for ops/testing.

F-007 owns the orchestration/cadence only — every content step is F-006 (`life_engine_llm`) and
every write is F-004's store (`life_engine_store`).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.bot.chat_client import ChatClient
from services.bot.domain import biography as bio_domain
from services.bot.domain import life_engine as le
from services.bot.domain import life_engine_llm as llm
from services.bot.domain import life_engine_store as ls
from services.bot.domain.vector_store import MemoryIndex
from services.bot.models import Persona, PersonaStatus, Reflection

log = logging.getLogger(__name__)


@dataclass
class TickReport:
    """What one tick actually did (observability — NFR-007-07)."""
    persona: str = ""
    planned: bool = False
    reflected: bool = False
    compressed: list[str] = field(default_factory=list)   # scopes newly compressed
    goals_added: int = 0
    future_updated: bool = False
    skipped: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def did_anything(self) -> bool:
        return bool(self.planned or self.reflected or self.compressed
                    or self.goals_added or self.future_updated)


async def _recent_biography_text(db: AsyncSession, persona_id: int) -> str:
    return (await bio_domain.graded_biography_block(db, persona_id)) or ""


async def _goals_text(db: AsyncSession, persona_id: int, with_ids: bool = True) -> str:
    goals = await ls.active_goals(db, persona_id)
    if with_ids:
        return "\n".join(f"[{g.id}] {g.description}" for g in goals)
    return "\n".join(g.description for g in goals)


async def _reflection_for_date(db: AsyncSession, persona_id: int, date_key: str) -> Reflection | None:
    return (
        await db.execute(
            select(Reflection).where(
                Reflection.persona_id == persona_id,
                Reflection.scope == "day",
                Reflection.period_key == date_key,
            )
        )
    ).scalar_one_or_none()


def _range_key(period_keys: list[str]) -> str:
    if not period_keys:
        return ""
    return period_keys[0] if len(period_keys) == 1 else f"{period_keys[0]}..{period_keys[-1]}"


async def _run_cascade(
    db: AsyncSession, persona: Persona, chat_client: ChatClient,
    bio_index: MemoryIndex | None, cfg: le.LifeEngineConfig,
) -> list[str]:
    """Compress day→week→month→year→epoch while thresholds are met (FR-007-04)."""
    compressed: list[str] = []
    for target in ("week", "month", "year", "epoch"):
        lower = le.lower_scope_of(target)
        if lower == "day":
            rows = await ls.uncompressed_daily(db, persona.id)
        else:
            rows = await ls.uncompressed_layers(db, persona.id, lower)
        if not le.should_compress(len(rows), target, cfg):
            continue
        entries = [r.content for r in rows]
        period_keys = [r.period_key for r in rows]
        text = await llm.run_compress(chat_client, persona.name, persona.big_five,
                                      lower, target, entries, cfg)
        if not text:
            continue
        await ls.store_biography_layer(
            db, persona.id, target, _range_key(period_keys), text,
            source_period=f"{lower}:{_range_key(period_keys)}",
            prompt_version=cfg.compress_prompt_version, index=bio_index,
        )
        compressed.append(target)
    return compressed


async def _run_goals(db: AsyncSession, persona: Persona, chat_client: ChatClient,
                     cfg: le.LifeEngineConfig) -> int:
    goals_text = await _goals_text(db, persona.id, with_ids=True)
    if not goals_text:
        return 0
    refs = await ls.recent_reflections(db, persona.id, limit=7)
    update = await llm.run_update_goals(
        chat_client, persona.name, persona.big_five, goals_text,
        "\n".join(r.content for r in refs), cfg)
    if update is None:
        return 0
    added = await ls.apply_goal_update(db, persona.id, update)
    return len(added)


async def _run_future(db: AsyncSession, persona: Persona, chat_client: ChatClient,
                      cfg: le.LifeEngineConfig) -> bool:
    recent_bio = await _recent_biography_text(db, persona.id)
    goals_text = await _goals_text(db, persona.id, with_ids=False)
    fut = await llm.run_update_future(chat_client, persona.name, persona.big_five,
                                      recent_bio, goals_text, cfg)
    if not fut:
        return False
    for horizon, content in fut.items():
        await ls.store_future_projection(db, persona.id, horizon, content, cfg.future_prompt_version)
    return True


async def run_tick(
    db: AsyncSession, persona: Persona, chat_client: ChatClient, now_utc: datetime,
    bio_index: MemoryIndex | None = None, cfg: le.LifeEngineConfig = le.DEFAULT_CONFIG,
    force: bool = False,
) -> TickReport:
    """Run the due steps for one persona at `now_utc`. Idempotent per period; never raises for a
    step failure (degrade — FR-007-08). `force=True` runs the full loop regardless of local hour
    (on-demand — FR-007-12), still idempotent per period."""
    report = TickReport(persona=persona.name)
    tz = persona.timezone
    date_key = le.local_date_key(tz, now_utc)

    # MORNING → plan (once per local day)
    if force or le.is_local_morning(tz, now_utc, cfg):
        if await ls.get_plan_for_date(db, persona.id, date_key) is None:
            recent_bio = await _recent_biography_text(db, persona.id)
            goals = await _goals_text(db, persona.id, with_ids=False)
            yesterday_rows = await ls.recent_reflections(db, persona.id, limit=1)
            yesterday = yesterday_rows[-1].content if yesterday_rows else ""
            plan_text = await llm.run_plan_day(
                chat_client, persona.name, persona.big_five, recent_bio, goals, yesterday, cfg)
            if plan_text:
                await ls.store_plan(db, persona.id, date_key, plan_text, cfg.plan_prompt_version)
                report.planned = True
            else:
                report.failures.append("plan")
        else:
            report.skipped.append("plan(exists)")

    # END OF DAY → reflect (once per local day) → cascade → goals → future
    if force or le.is_local_end_of_day(tz, now_utc, cfg):
        if await _reflection_for_date(db, persona.id, date_key) is None:
            plan_text = await ls.get_current_plan_text(db, persona.id, date_key)
            recent_bio = await _recent_biography_text(db, persona.id)
            content = await llm.run_reflect_day(
                chat_client, persona.name, persona.big_five, plan_text, "", recent_bio, cfg)
            if content:
                await ls.store_reflection(
                    db, persona.id, date_key, content,
                    source_period=f"day:{date_key}", prompt_version=cfg.reflect_prompt_version)
                report.reflected = True
            else:
                report.failures.append("reflect")
        else:
            report.skipped.append("reflect(exists)")
        # cascade / goals / future run on the end-of-day cadence (and always under force)
        report.compressed = await _run_cascade(db, persona, chat_client, bio_index, cfg)
        report.goals_added = await _run_goals(db, persona, chat_client, cfg)
        report.future_updated = await _run_future(db, persona, chat_client, cfg)

    return report


async def run_persona_now(
    db: AsyncSession, persona: Persona, chat_client: ChatClient,
    bio_index: MemoryIndex | None = None, cfg: le.LifeEngineConfig = le.DEFAULT_CONFIG,
    now_utc: datetime | None = None,
) -> TickReport:
    """Force a full loop for one persona right now (ops/testing/demo — FR-007-12)."""
    return await run_tick(db, persona, chat_client, now_utc or datetime.now(timezone.utc),
                          bio_index, cfg, force=True)


async def scheduler_pass(
    sessionmaker: async_sessionmaker[AsyncSession], chat_client: ChatClient,
    memory_index: MemoryIndex | None, now_utc: datetime,
    cfg: le.LifeEngineConfig = le.DEFAULT_CONFIG,
) -> dict[str, TickReport]:
    """Tick every active persona once. Each runs in its own session/transaction; a failure for one
    is logged and does not stop the others (NFR-007-06/FR-007-08)."""
    bio_index = memory_index.for_collection(ls.BIOGRAPHY_COLLECTION) if memory_index else None
    async with sessionmaker() as db:
        persona_ids = [
            p.id for p in (
                await db.execute(select(Persona).where(Persona.status == PersonaStatus.active))
            ).scalars().all()
        ]
    reports: dict[str, TickReport] = {}
    for pid in persona_ids:
        try:
            async with sessionmaker() as db:
                persona = await db.get(Persona, pid)
                if persona is None:
                    continue
                rep = await run_tick(db, persona, chat_client, now_utc, bio_index, cfg)
                await db.commit()
                reports[persona.name] = rep
                if rep.did_anything() or rep.failures:
                    log.info("life-engine tick %s: %s", persona.name, rep)
        except Exception:  # noqa: BLE001 - one persona must never stop the roster
            log.warning("life-engine tick raised for persona id=%s", pid, exc_info=True)
    return reports


async def run_scheduler(
    sessionmaker: async_sessionmaker[AsyncSession], chat_client: ChatClient,
    memory_index: MemoryIndex | None, cfg: le.LifeEngineConfig = le.DEFAULT_CONFIG,
) -> None:
    """Dev in-process loop: tick the roster every `cfg.tick_interval_s` (FR-007-01). Runs as a
    background task alongside the bot; a failing pass is logged and the loop continues."""
    log.info("life-engine scheduler started (interval=%ss)", cfg.tick_interval_s)
    while True:
        try:
            await scheduler_pass(sessionmaker, chat_client, memory_index,
                                 datetime.now(timezone.utc), cfg)
        except Exception:  # noqa: BLE001 - the loop must never die
            log.warning("life-engine scheduler pass failed", exc_info=True)
        await asyncio.sleep(cfg.tick_interval_s)
