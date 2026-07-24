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
    # Chat-LLM runner (chat/serve.py) OpenAI-compatible endpoint — the F-002 conversation loop
    # calls this over localhost (architecture.md §6.2c).
    chat_base_url: str = "http://127.0.0.1:8080"
    # F-004 semantic memory (vector half). Qdrant location: a URL (http://…), a local dir path, or
    # ":memory:". Dev default is an embedded on-disk store (no Docker). Empty → keyword recall only.
    qdrant_location: str = "./qdrant_data"
    # Embedding model name (fastembed); empty → the multilingual MiniLM default in embeddings.py.
    embed_model: str = ""
    # F-007 Life Engine Scheduler — run the autonomous plan/reflect/compress/goals/future loop as an
    # in-process background task. Enabled by default; set LIFE_ENGINE_ENABLED=0 to disable. The tick
    # cadence lives in LifeEngineConfig (tick_interval_s); override with LIFE_ENGINE_INTERVAL_S.
    life_engine_enabled: bool = True
    life_engine_interval_s: int = 900
    # F-012 FR-012-20 — photo-frequency pacing on/off (operator override; product default is ON).
    # Set MEDIA_PACING_ENABLED=false to lift the per-stage caps entirely (every valid photo request
    # delivers). The future control panel (F-022) exposes this and finer knobs.
    media_pacing_enabled: bool = True
    env: str = "dev"
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
