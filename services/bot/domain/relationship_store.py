"""F-005 relationship persistence — get/create, apply a reflection, decay, milestone (F-004 store).

F-005 authors the updates; the rows live in the Memory subsystem (FR-005-24). Every write is scoped
to the `(user_id, persona_id)` pair so relationships are strictly per-user isolated (FR-005-25). A
failed reflection never reaches here (the caller passes `None`), so the last good state is preserved
(FR-005-27).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain.relationship import (
    DEFAULT_CONFIG,
    ApplyResult,
    RelationshipConfig,
    RelState,
    apply_deltas,
    apply_decay,
)
from services.bot.domain.relationship_reflection import ReflectionResult
from services.bot.models import Relationship, RelationshipReflection


def to_state(rel: Relationship) -> RelState:
    return RelState(rel.closeness, rel.trust, rel.attraction, rel.stage)


async def get_or_create(
    db: AsyncSession, user_id: int, persona_id: int, cfg: RelationshipConfig = DEFAULT_CONFIG
) -> Relationship:
    """Fetch the (user, persona) relationship, creating a Stranger baseline on first contact
    (FR-005-02). Scoped to this pair only (FR-005-25)."""
    rel = (
        await db.execute(
            select(Relationship).where(
                Relationship.user_id == user_id, Relationship.persona_id == persona_id)
        )
    ).scalar_one_or_none()
    if rel is None:
        rel = Relationship(
            user_id=user_id, persona_id=persona_id,
            closeness=cfg.baseline_closeness, trust=cfg.baseline_trust,
            attraction=cfg.baseline_attraction, stage="Stranger", summary="",
        )
        db.add(rel)
        await db.flush()
    return rel


def _write_back(rel: Relationship, res: ApplyResult) -> None:
    rel.closeness = res.state.closeness
    rel.trust = res.state.trust
    rel.attraction = res.state.attraction
    rel.stage = res.state.stage
    rel.updated_at = datetime.now(timezone.utc)
    if res.advanced:
        rel.pending_milestone = res.state.stage  # she may acknowledge crossing this (FR-005-22)


async def apply_reflection(
    db: AsyncSession, rel: Relationship, result: ReflectionResult,
    cfg: RelationshipConfig = DEFAULT_CONFIG,
) -> ApplyResult:
    """Apply a parsed reflection to the relationship: bounded deltas → clamp → re-derive stage →
    persist state + summary + timestamp, write the audit log, and mark a milestone if a boundary was
    crossed (FR-005-08/09/10/22). Deterministic (NFR-005-13)."""
    res = apply_deltas(
        to_state(rel), result.dc, result.dt, result.da, cfg,
        breach=result.breach, pushing_fast=result.pushing_fast,
    )
    _write_back(rel, res)
    if result.summary:
        rel.summary = result.summary
    rel.last_interaction_at = datetime.now(timezone.utc)

    reasons = "; ".join(f"{k}: {v}" for k, v in result.reasons.items())
    db.add(RelationshipReflection(
        relationship_id=rel.id,
        delta_closeness=result.dc, delta_trust=result.dt, delta_attraction=result.da,
        reasons=reasons, resulting_stage=res.state.stage,
    ))
    await db.flush()
    return res


async def apply_decay_now(
    db: AsyncSession, rel: Relationship, days: float, cfg: RelationshipConfig = DEFAULT_CONFIG
) -> ApplyResult:
    """Apply neglect decay for `days` of silence and persist (FR-005-14/15)."""
    res = apply_decay(to_state(rel), days, cfg)
    _write_back(rel, res)
    await db.flush()
    return res


async def clear_milestone(db: AsyncSession, rel: Relationship) -> None:
    """Clear a pending milestone once the persona has had the chance to acknowledge it."""
    rel.pending_milestone = None
    await db.flush()
