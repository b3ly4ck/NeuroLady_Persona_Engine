"""F-006 Life Engine — persistence + hand-off to Memory (F-004 store, architecture.md §3.5/§4.5).

F-006 **authors** `DAILY_PLAN` / `REFLECTION` / `GOAL` / `BIOGRAPHY_LAYER` rows; it does not
implement storage itself — this module only writes through SQLAlchemy models that live in the
Memory subsystem's schema (FR-006-17), and hands compressed layers to the same vector index F-004
uses for semantic recall (FR-006-08), in a separate collection so persona biography never mixes
with user facts.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain.life_engine_llm import GoalUpdate
from services.bot.domain.vector_store import MemoryIndex, VectorStoreUnavailable
from services.bot.models import BiographyLayer, DailyPlan, Goal, GoalStatus, Reflection

log = logging.getLogger(__name__)

BIOGRAPHY_COLLECTION = "biography_layers"  # kept separate from F-004's "user_facts" collection


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── daily plan ───────────────────────────────────────────────────────────────────────────────


async def get_plan_for_date(db: AsyncSession, persona_id: int, date_key: str) -> DailyPlan | None:
    return (
        await db.execute(
            select(DailyPlan).where(DailyPlan.persona_id == persona_id, DailyPlan.date == date_key)
        )
    ).scalar_one_or_none()


async def get_latest_plan(db: AsyncSession, persona_id: int) -> DailyPlan | None:
    return (
        await db.execute(
            select(DailyPlan).where(DailyPlan.persona_id == persona_id)
            .order_by(DailyPlan.date.desc())
        )
    ).scalars().first()


async def get_current_plan_text(db: AsyncSession, persona_id: int, date_key: str) -> str:
    """Today's plan if it exists, else the most recent prior plan (degrade — never "no day",
    NFR-006-03), else an empty string only if nothing has ever been planned."""
    today = await get_plan_for_date(db, persona_id, date_key)
    if today is not None:
        return today.plan_text
    latest = await get_latest_plan(db, persona_id)
    return latest.plan_text if latest is not None else ""


async def get_current_activity(db: AsyncSession, persona_id: int, tz_name: str) -> str | None:
    """FR-006-03: what she's doing right now, derived from her plan (today's, or the last known
    one if today's isn't ready yet — NFR-006-03) + the current local time. None if she has never
    been planned at all (nothing to expose yet)."""
    from services.bot.domain.life_engine import current_activity, local_date_key, local_now

    now_utc = _now()
    date_key = local_date_key(tz_name, now_utc)
    plan_text = await get_current_plan_text(db, persona_id, date_key)
    if not plan_text:
        return None
    return current_activity(plan_text, local_now(tz_name, now_utc))


async def store_plan(
    db: AsyncSession, persona_id: int, date_key: str, plan_text: str, prompt_version: str
) -> DailyPlan:
    """Store today's plan, idempotently — one plan per (persona, local date) (FR-006-01-03)."""
    existing = await get_plan_for_date(db, persona_id, date_key)
    if existing is not None:
        return existing  # already planned today — do not duplicate
    plan = DailyPlan(persona_id=persona_id, date=date_key, plan_text=plan_text,
                     prompt_version=prompt_version)
    db.add(plan)
    await db.flush()
    return plan


# ── daily reflections ────────────────────────────────────────────────────────────────────────


async def store_reflection(
    db: AsyncSession, persona_id: int, date_key: str, content: str,
    source_period: str, prompt_version: str,
) -> Reflection:
    row = Reflection(
        persona_id=persona_id, scope="day", period_key=date_key, content=content,
        source_period=source_period, prompt_version=prompt_version,
    )
    db.add(row)
    await db.flush()
    return row


async def recent_reflections(db: AsyncSession, persona_id: int, limit: int = 7) -> list[Reflection]:
    rows = (
        await db.execute(
            select(Reflection).where(Reflection.persona_id == persona_id, Reflection.scope == "day")
            .order_by(Reflection.period_key.desc()).limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))  # chronological order


# ── biography compression (hierarchical, hand-off to Memory/vector index) ──────────────────────


async def uncompressed_daily(db: AsyncSession, persona_id: int) -> list[Reflection]:
    """Daily reflections not yet folded into any weekly layer (oldest first)."""
    latest_week = (
        await db.execute(
            select(BiographyLayer).where(
                BiographyLayer.persona_id == persona_id, BiographyLayer.scope == "week")
            .order_by(BiographyLayer.created_at.desc())
        )
    ).scalars().first()
    stmt = select(Reflection).where(Reflection.persona_id == persona_id, Reflection.scope == "day")
    if latest_week is not None:
        stmt = stmt.where(Reflection.created_at > latest_week.created_at)
    stmt = stmt.order_by(Reflection.period_key.asc())
    return list((await db.execute(stmt)).scalars().all())


async def uncompressed_layers(db: AsyncSession, persona_id: int, scope: str) -> list[BiographyLayer]:
    """Layers of `scope` not yet folded into the next scope up (oldest first)."""
    from services.bot.domain.life_engine import SCOPES

    upper = SCOPES[SCOPES.index(scope) + 1]
    latest_upper = (
        await db.execute(
            select(BiographyLayer).where(
                BiographyLayer.persona_id == persona_id, BiographyLayer.scope == upper)
            .order_by(BiographyLayer.created_at.desc())
        )
    ).scalars().first()
    stmt = select(BiographyLayer).where(
        BiographyLayer.persona_id == persona_id, BiographyLayer.scope == scope)
    if latest_upper is not None:
        stmt = stmt.where(BiographyLayer.created_at > latest_upper.created_at)
    stmt = stmt.order_by(BiographyLayer.created_at.asc())
    return list((await db.execute(stmt)).scalars().all())


async def store_biography_layer(
    db: AsyncSession, persona_id: int, scope: str, period_key: str, content: str,
    source_period: str, prompt_version: str, index: MemoryIndex | None = None,
) -> BiographyLayer:
    """Store a compressed layer and hand it to the vector index for semantic recall (FR-006-08).

    Uses a **separate Qdrant collection** from F-004's user facts, so persona biography never mixes
    with any user's private data (NFR-006-05). An index failure is logged and swallowed — the SQL
    write (the authoritative record) always stands (degrade, FR-006-20).
    """
    layer = BiographyLayer(
        persona_id=persona_id, scope=scope, period_key=period_key, content=content,
        source_period=source_period, prompt_version=prompt_version,
    )
    db.add(layer)
    await db.flush()
    if index is not None:
        try:
            # Reusing F-004's generic owner-scoped index API: persona_id is the owner key here,
            # in the biography_layers collection — never the user_facts collection (isolation).
            await asyncio.to_thread(index.index_fact, persona_id, layer.id, content)
            layer.embedding_ref = str(layer.id)
            await db.flush()
        except VectorStoreUnavailable as exc:
            log.warning("biography layer indexing skipped (store unavailable): %s", exc)
    return layer


# ── goals ────────────────────────────────────────────────────────────────────────────────────


async def active_goals(db: AsyncSession, persona_id: int) -> list[Goal]:
    return list(
        (
            await db.execute(
                select(Goal).where(Goal.persona_id == persona_id, Goal.status == GoalStatus.active)
                .order_by(Goal.priority.desc())
            )
        ).scalars().all()
    )


async def apply_goal_update(db: AsyncSession, persona_id: int, update: GoalUpdate) -> list[Goal]:
    """Apply progress/complete/drop/add to this persona's own goals (FR-006-12/13)."""
    for goal_id in update.complete:
        g = await db.get(Goal, goal_id)
        if g is not None and g.persona_id == persona_id:
            g.status = GoalStatus.completed
            g.updated_at = _now()
    for goal_id in update.drop:
        g = await db.get(Goal, goal_id)
        if g is not None and g.persona_id == persona_id:
            g.status = GoalStatus.dropped
            g.updated_at = _now()
    for goal_id, _note in update.progress.items():
        g = await db.get(Goal, goal_id)
        if g is not None and g.persona_id == persona_id and g.status == GoalStatus.active:
            g.updated_at = _now()  # progress noted via updated_at; content stays in the reflection

    added: list[Goal] = []
    for a in update.add:
        g = Goal(
            persona_id=persona_id, description=a["description"],
            priority=int(a.get("priority", 3)), horizon=str(a.get("horizon", "medium")),
        )
        db.add(g)
        added.append(g)
    await db.flush()
    return added
