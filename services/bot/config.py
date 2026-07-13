"""Runtime configuration, loaded from environment / `.env` (never hard-coded).

Secrets live only in `.env` (git-ignored); `.env.example` documents the keys. Nothing in this
repo should ever contain a real token.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram bot token from @BotFather — required to actually run the bot (not needed for tests).
    telegram_bot_token: str = ""
    # Dev default: local SQLite (async). Use a Postgres URL in production.
    database_url: str = "sqlite+aiosqlite:///./neurolady.sqlite3"
    env: str = "dev"
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
