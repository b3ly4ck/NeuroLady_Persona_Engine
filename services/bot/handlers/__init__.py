"""aiogram handlers (the thin Telegram I/O layer over the domain, architecture.md §3.1/§3.2).

`router` is a parent that includes the feature routers in priority order: onboarding first (so
`/start`, gallery callbacks and the "💋 Choose Lady" button win), then conversation (F-002) which
handles all other text typed in an active session.
"""
from aiogram import Router

from services.bot.handlers.conversation import router as conversation_router
from services.bot.handlers.onboarding import router as onboarding_router

router = Router(name="root")
router.include_router(onboarding_router)
router.include_router(conversation_router)

__all__ = ["router"]
