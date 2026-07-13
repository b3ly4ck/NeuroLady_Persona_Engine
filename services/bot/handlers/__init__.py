"""aiogram handlers (the thin Telegram I/O layer over the domain, architecture.md §3.1/§3.2)."""
from services.bot.handlers.onboarding import router

__all__ = ["router"]
