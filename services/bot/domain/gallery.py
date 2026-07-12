"""The "Choose Lady" gallery: which personas to show, ordering, and cyclic pagination.

Covers FR-001-05 (one per view + counter), FR-001-06 (cyclic ◀/▶), FR-001-07 (active-only, stable
order), FR-001-08 (locale-appropriate personas), and NFR-001-10 (nav never desyncs card/counter).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import Persona, PersonaStatus


async def list_gallery_personas(db: AsyncSession, user_locale: str) -> list[Persona]:
    """Active personas for this user's locale, in a deterministic, stable order (by id).

    FR-001-07 (only `status = active`, stable order) + FR-001-08 (personas matching the user's
    language). If the locale has no personas, fall back to all active ones so the gallery is
    never empty.
    """
    stmt = (
        select(Persona)
        .where(Persona.status == PersonaStatus.active)
        .order_by(Persona.id)
    )
    active = list((await db.execute(stmt)).scalars().all())
    localized = [p for p in active if p.language == user_locale]
    return localized if localized else active


def cyclic_index(current: int, delta: int, total: int) -> int:
    """Wrap-around index for ◀/▶ (FR-001-06). `delta` is +1 (▶) or -1 (◀).

    ▶ past the last card wraps to the first; ◀ before the first wraps to the last. Robust to any
    integer `current`/`delta` so rapidly repeated taps can never land out of range (NFR-001-10).
    """
    if total <= 0:
        raise ValueError("cannot paginate an empty gallery")
    return (current + delta) % total


def counter_label(index: int, total: int) -> str:
    """The '1/N'-style position counter shown on a card (FR-001-05); `index` is 0-based."""
    return f"{index + 1}/{total}"
