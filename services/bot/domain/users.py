"""User records — get-or-create on `/start` (FR-001-01, FR-001-15).

`/start` from a brand-new Telegram id creates exactly one USER; a repeat `/start` from an existing
id must NOT create a duplicate.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import User

# Locales the product ships copy/personas for; anything else falls back to English (FR-001-08).
SUPPORTED_LOCALES = ("en", "ru")
DEFAULT_LOCALE = "en"


def normalize_locale(raw: str | None) -> str:
    """Map a Telegram language code (e.g. 'ru', 'ru-RU', 'en-US') to a supported locale."""
    if not raw:
        return DEFAULT_LOCALE
    code = raw.strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LOCALES else DEFAULT_LOCALE


async def get_or_create_user(
    db: AsyncSession, telegram_id: int, locale: str | None = None
) -> tuple[User, bool]:
    """Return `(user, created)`. Never creates a duplicate for an existing telegram_id.

    FR-001-01 (create exactly once) and FR-001-15 (no duplicate on repeat /start).
    """
    existing = (
        await db.execute(select(User).where(User.telegram_id == telegram_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    user = User(telegram_id=telegram_id, locale=normalize_locale(locale))
    db.add(user)
    await db.flush()  # assign PK without ending the caller's transaction
    return user, True
