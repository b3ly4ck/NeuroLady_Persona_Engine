"""Chat sessions — create/reuse on "Start Chat" and switch persona (FR-001-10/14/17).

Invariant: a user has at most ONE active session at a time. "Start Chat" on a persona activates
(user, persona); any previously-active session for a *different* persona is ended (switch).
Repeating "Start Chat" on the same persona reuses the existing active session (idempotent), so a
double-tap does not create a second session or a second intro.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import Session, SessionState


async def get_active_session(db: AsyncSession, user_id: int) -> Session | None:
    stmt = select(Session).where(
        Session.user_id == user_id, Session.state == SessionState.active
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def start_or_switch_session(
    db: AsyncSession, user_id: int, persona_id: int
) -> tuple[Session, bool]:
    """Activate (user, persona). Returns `(session, is_new_intro)`.

    `is_new_intro` is True when the caller should send the persona's intro — i.e. a brand-new
    session or a switch to a different persona — and False when an already-active session for the
    same persona was reused (double-tap idempotency, FR-001-17), so the intro is not re-sent.
    """
    active = await get_active_session(db, user_id)
    if active is not None and active.persona_id == persona_id:
        return active, False  # idempotent reuse — no duplicate session, no duplicate intro

    if active is not None:  # switching away from another persona (FR-001-14)
        active.state = SessionState.ended
        active.ended_at = datetime.now(timezone.utc)

    # Reuse a prior (ended) session row for this (user, persona) if one exists, else create it.
    existing = (
        await db.execute(
            select(Session).where(
                Session.user_id == user_id, Session.persona_id == persona_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.state = SessionState.active
        existing.ended_at = None
        existing.started_at = datetime.now(timezone.utc)
        await db.flush()
        return existing, True

    session = Session(user_id=user_id, persona_id=persona_id, state=SessionState.active)
    db.add(session)
    await db.flush()
    return session, True
