"""Persona biography — seeding + serving into the reply context (F-006 biography extension).

Two jobs:
1. **Seed** an authored initial biography (FR-006-22): fixed anchors onto PERSONA, epoch/year/month/
   week/day layers into BIOGRAPHY_LAYER (embedded for semantic recall), goals, and future-self
   projections — all **idempotent** so re-seeding never duplicates.
2. **Serve** her biography into every reply (FR-006-27/28): a bounded **graded recency block**
   (current-epoch → year → month → week → recent days) plus **semantically-retrieved deep layers**
   relevant to the user's message, and her **future-self** — so she answers about her past/future
   consistently instead of confabulating. Length-bounded (NFR-006-15).

Persona biography is **persona-shared, never per-user** (NFR-006-05): the vector points live in the
`biography_layers` collection keyed by `persona_id`, never mixed with user facts.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain import life_engine_store as life_store
from services.bot.domain.vector_store import MemoryIndex, VectorStoreUnavailable
from services.bot.models import (
    BiographyLayer,
    FutureProjection,
    Goal,
    GoalStatus,
    Horizon,
    Persona,
)

log = logging.getLogger(__name__)

# Coarse → fine order used both for the graded block and for pyramid queries.
_GRADED_SCOPES = ("epoch", "year", "month", "week", "day")
# NFR-006-15 bounds — keep the served biography from blowing the token/latency budget.
_MAX_DAYS = 3
_MAX_SEMANTIC = 3
_CHAR_BOUND = 3000


@dataclass
class BiographySeed:
    """An authored initial biography for one persona (imported at provisioning)."""

    birthdate: date
    core_values: str
    motivation: str
    interests: str
    goals: list[str] = field(default_factory=list)
    # (scope, period_key, content) — scope ∈ epoch|year|month|week|day
    layers: list[tuple[str, str, str]] = field(default_factory=list)
    # (horizon, content) — horizon ∈ week|month|year|epoch|lifetime
    future: list[tuple[str, str]] = field(default_factory=list)


# ── seeding (idempotent) ───────────────────────────────────────────────────────────────────────


async def seed_biography(
    db: AsyncSession,
    persona: Persona,
    seed: BiographySeed,
    bio_index: MemoryIndex | None = None,
) -> dict[str, int]:
    """Import `seed` for `persona`, idempotently (FR-006-22). Returns counts of newly-added rows.

    Anchors + interests are set to the authored (canonical) values; goals, layers and future-self
    are added only if absent, so calling this repeatedly is safe. `bio_index` (the biography-layers
    collection) embeds each new layer for semantic recall.
    """
    counts = {"layers": 0, "goals": 0, "future": 0}

    # Fixed anchors + evolving interests (FR-006-23/25). Authored values are canonical.
    persona.birthdate = seed.birthdate
    persona.core_values = seed.core_values
    persona.motivation = seed.motivation
    persona.interests = seed.interests
    await db.flush()

    # Goals — add any not already present by description (FR-006-13/22).
    existing_goals = {
        g.description
        for g in (
            await db.execute(select(Goal).where(Goal.persona_id == persona.id))
        ).scalars()
    }
    for i, desc in enumerate(seed.goals):
        if desc not in existing_goals:
            db.add(Goal(persona_id=persona.id, description=desc,
                        status=GoalStatus.active, priority=max(1, 5 - i)))
            counts["goals"] += 1

    # Biography layers — skip any (scope, period_key) already stored (idempotent).
    existing_layers = {
        (l.scope, l.period_key)
        for l in (
            await db.execute(
                select(BiographyLayer).where(BiographyLayer.persona_id == persona.id)
            )
        ).scalars()
    }
    for scope, period_key, content in seed.layers:
        if (scope, period_key) in existing_layers:
            continue
        await life_store.store_biography_layer(
            db, persona.id, scope, period_key, content,
            source_period="authored:seed", prompt_version="seed_v1", index=bio_index,
        )
        counts["layers"] += 1

    # Future-self — one row per horizon, upserted (FR-006-26).
    existing_future = {
        fp.horizon: fp
        for fp in (
            await db.execute(
                select(FutureProjection).where(FutureProjection.persona_id == persona.id)
            )
        ).scalars()
    }
    for horizon_name, content in seed.future:
        horizon = Horizon(horizon_name)
        if horizon in existing_future:
            existing_future[horizon].content = content
        else:
            db.add(FutureProjection(persona_id=persona.id, horizon=horizon,
                                    content=content, prompt_version="seed_v1"))
            counts["future"] += 1

    await db.flush()
    return counts


# ── serving into the reply context ──────────────────────────────────────────────────────────────


async def _latest_by_scope(db: AsyncSession, persona_id: int, scope: str, period_key: str | None,
                           limit: int) -> list[BiographyLayer]:
    stmt = select(BiographyLayer).where(
        BiographyLayer.persona_id == persona_id, BiographyLayer.scope == scope
    )
    if period_key is not None:
        stmt = stmt.where(BiographyLayer.period_key == period_key)
    stmt = stmt.order_by(BiographyLayer.period_key.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def graded_biography_block(db: AsyncSession, persona_id: int) -> str | None:
    """The always-on coarse→fine recency block (FR-006-27): current epoch → year → month → week →
    recent days. Bounded in layer count (NFR-006-15) and total length."""
    picked: list[BiographyLayer] = []
    # current epoch (fall back to any epoch if no explicit "current")
    epoch = await _latest_by_scope(db, persona_id, "epoch", "current", 1)
    if not epoch:
        epoch = await _latest_by_scope(db, persona_id, "epoch", None, 1)
    picked += epoch
    picked += await _latest_by_scope(db, persona_id, "year", None, 1)
    picked += await _latest_by_scope(db, persona_id, "month", None, 1)
    picked += await _latest_by_scope(db, persona_id, "week", None, 1)
    picked += await _latest_by_scope(db, persona_id, "day", None, _MAX_DAYS)
    if not picked:
        return None
    lines = [f"[{l.scope}:{l.period_key}] {l.content.strip()}" for l in picked]
    block = "Your life so far (your own memories — stay consistent with these):\n" + "\n".join(lines)
    return block[:_CHAR_BOUND]


async def recall_biography(
    db: AsyncSession, persona_id: int, query: str, bio_index: MemoryIndex | None,
    k: int = _MAX_SEMANTIC, exclude_ids: set[int] | None = None,
) -> list[BiographyLayer]:
    """Semantically retrieve deep biography layers relevant to `query` (FR-006-27). Degrades to []
    when there is no index or the store is unavailable (never breaks the turn)."""
    if bio_index is None or not query.strip():
        return []
    try:
        ids = await asyncio.to_thread(bio_index.search, persona_id, query, k + (len(exclude_ids or []) or 0))
    except VectorStoreUnavailable as exc:
        log.warning("biography semantic recall skipped (store unavailable): %s", exc)
        return []
    exclude = exclude_ids or set()
    ids = [i for i in ids if i not in exclude][:k]
    if not ids:
        return []
    rows = (
        await db.execute(select(BiographyLayer).where(BiographyLayer.id.in_(ids)))
    ).scalars().all()
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


async def future_self_block(db: AsyncSession, persona_id: int) -> str | None:
    """Her forward projections as a compact 'where you're heading' block (FR-006-28)."""
    order = {h: i for i, h in enumerate(
        [Horizon.week, Horizon.month, Horizon.year, Horizon.epoch, Horizon.lifetime])}
    rows = list(
        (await db.execute(
            select(FutureProjection).where(FutureProjection.persona_id == persona_id)
        )).scalars().all()
    )
    if not rows:
        return None
    rows.sort(key=lambda fp: order.get(fp.horizon, 99))
    lines = [f"[{fp.horizon.value}] {fp.content.strip()}" for fp in rows if fp.content.strip()]
    if not lines:
        return None
    block = "Where you see yourself heading (your own hopes — bring up naturally, never as a list):\n" \
            + "\n".join(lines)
    return block[:_CHAR_BOUND]


async def assemble_biography_context(
    db: AsyncSession, persona: Persona, query: str, bio_index: MemoryIndex | None,
) -> str:
    """Compose the full biography context for one reply: graded recency + semantically-relevant deep
    layers + future-self, joined and length-bounded (FR-006-27/28, NFR-006-15). Returns "" if she has
    no biography yet (graceful — the turn still works)."""
    sections: list[str] = []
    graded = await graded_biography_block(db, persona.id)
    graded_ids: set[int] = set()
    if graded:
        sections.append(graded)
    # relevant deep layers not already surfaced by the graded block
    if graded:
        # collect ids present in the graded block to avoid repeating them
        graded_rows = (
            await db.execute(
                select(BiographyLayer.id, BiographyLayer.content).where(
                    BiographyLayer.persona_id == persona.id)
            )
        ).all()
        graded_ids = {rid for rid, content in graded_rows if content.strip() and content.strip() in graded}
    relevant = await recall_biography(db, persona.id, query, bio_index, exclude_ids=graded_ids)
    if relevant:
        lines = [f"[{l.scope}:{l.period_key}] {l.content.strip()}" for l in relevant]
        sections.append("Relevant memories for what he's asking about:\n" + "\n".join(lines))
    future = await future_self_block(db, persona.id)
    if future:
        sections.append(future)
    return ("\n\n".join(sections))[: _CHAR_BOUND * 2]
