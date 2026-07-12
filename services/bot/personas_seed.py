"""Seed personas for the "Choose Lady" gallery.

A minimal starter roster so onboarding is demonstrable; the full target is 10 personas (5 RU +
5 EN) authored via Persona Studio (architecture.md §3.8). `gallery_photo_ref` / `intro_videonote_ref`
are media paths (architecture.md §5.1); left None here so the graceful text/photo fallback path
(FR-001-18) is exercised until real media is produced.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import Persona, PersonaStatus

# (name, profession, age, timezone, language, card_description)
_SEED: list[dict] = [
    dict(name="Alina", profession="Psychologist", age=28, timezone="Europe/Moscow",
         language="ru", card_description="Слушаю лучше всех и сама не молчу. Люблю зал и долгие разговоры за полночь."),
    dict(name="Vika", profession="Barista", age=23, timezone="Europe/Moscow",
         language="ru", card_description="Варю кофе и настроение. Дерзкая, но своя."),
    dict(name="Sofia", profession="Fitness coach", age=26, timezone="Europe/Kiev",
         language="ru", card_description="Заставлю тебя двигаться — и не только в зале 😏"),
    dict(name="Olivia", profession="Psychologist", age=30, timezone="America/New_York",
         language="en", card_description="I listen closely and tease often. Late-night talks are my thing."),
    dict(name="Mia", profession="Photographer", age=25, timezone="Europe/London",
         language="en", card_description="I catch the light and the moment. Curious about you already."),
    dict(name="Emma", profession="Bartender", age=27, timezone="America/Los_Angeles",
         language="en", card_description="I mix drinks and trouble. Come sit at my bar."),
]


async def seed_personas(db: AsyncSession) -> int:
    """Insert the starter roster if the persona table is empty. Returns the number inserted."""
    already = (await db.execute(select(Persona.id).limit(1))).first()
    if already is not None:
        return 0
    for row in _SEED:
        db.add(Persona(status=PersonaStatus.active, **row))
    await db.flush()
    return len(_SEED)
