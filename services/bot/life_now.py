"""On-demand Life Engine run for one persona (F-007 FR-007-12).

Usage:  python -m services.bot.life_now [PersonaName]   (default: Alina)

Runs the full loop now — plan → reflect → compress cascade → goals → future-self — regardless of
her local hour, idempotent per period. Useful to advance a persona for a demo/test without waiting
for the scheduled window. Uses the same DATABASE_URL/CHAT_BASE_URL as the bot; runs without the
vector index (new layers are stored in SQL but not embedded), so it is safe to run while the bot
holds the embedded vector store open.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from services.bot.chat_client import ChatClient
from services.bot.config import get_settings
from services.bot.db import make_engine, make_sessionmaker
from services.bot.domain import life_engine_runner
from services.bot.models import Persona


async def _run(name: str) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with sessionmaker() as db:
            persona = (
                await db.execute(select(Persona).where(Persona.name == name))
            ).scalar_one_or_none()
            if persona is None:
                print(f"no persona named {name!r}")
                return
            report = await life_engine_runner.run_persona_now(
                db, persona, ChatClient(settings.chat_base_url), None)
            await db.commit()
            print(report)
    finally:
        await engine.dispose()


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "Alina"
    asyncio.run(_run(name))


if __name__ == "__main__":
    main()
