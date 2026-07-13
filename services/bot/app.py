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
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.bot.chat_client import ChatClient
from services.bot.config import get_settings
from services.bot.db import init_models, make_engine, make_sessionmaker
from services.bot.handlers import router
from services.bot.middlewares import DbSessionMiddleware
from services.bot.personas_seed import seed_personas

log = logging.getLogger(__name__)

# Capped exponential backoff for reconnecting after a Telegram connectivity blip (NFR-001-11 /
# architecture.md §6.1). The process must self-heal, never crash-and-exit, on a transient network
# failure — including the very first `getMe` check before polling even starts.
_BACKOFF_SEQUENCE_S = (1, 2, 4, 8, 16, 30, 60)


async def _run_polling_with_reconnect(dp: Dispatcher, bot: Bot) -> None:
    attempt = 0
    while True:
        try:
            await dp.start_polling(bot)
            return  # normal shutdown (e.g. external stop signal)
        except (TelegramNetworkError, OSError) as exc:
            delay = _BACKOFF_SEQUENCE_S[min(attempt, len(_BACKOFF_SEQUENCE_S) - 1)]
            attempt += 1
            log.warning(
                "Telegram connectivity failure (%s: %s) — retrying in %ss (attempt %d)",
                type(exc).__name__, exc, delay, attempt,
            )
            await asyncio.sleep(delay)


def build_dispatcher(
    sessionmaker: async_sessionmaker[AsyncSession],
    chat_client: ChatClient | None = None,
) -> Dispatcher:
    # `chat_client` is injected into handlers by name via workflow data; tests pass a fake.
    dp = Dispatcher(chat_client=chat_client or ChatClient())
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
    dp = build_dispatcher(sessionmaker, ChatClient(settings.chat_base_url))
    try:
        await _run_polling_with_reconnect(dp, bot)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
