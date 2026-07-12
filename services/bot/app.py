"""Bot application wiring: build the Dispatcher and run polling (architecture.md §2.1, §6.1).

`build_dispatcher` is separated from `main` so tests can construct the wired dispatcher against an
in-memory DB without any network/token.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.bot.config import get_settings
from services.bot.db import init_models, make_engine, make_sessionmaker
from services.bot.handlers import router
from services.bot.middlewares import DbSessionMiddleware
from services.bot.personas_seed import seed_personas


def build_dispatcher(sessionmaker: async_sessionmaker[AsyncSession]) -> Dispatcher:
    dp = Dispatcher()
    db_mw = DbSessionMiddleware(sessionmaker)
    dp.message.middleware(db_mw)
    dp.callback_query.middleware(db_mw)
    dp.include_router(router)
    return dp


async def _run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and put your @BotFather "
            "token in .env (never in .env.example)."
        )

    engine = make_engine(settings.database_url)
    await init_models(engine)  # dev convenience; production uses migrations
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as db:
        inserted = await seed_personas(db)
        await db.commit()
        if inserted:
            logging.getLogger(__name__).info("seeded %d personas", inserted)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher(sessionmaker)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
