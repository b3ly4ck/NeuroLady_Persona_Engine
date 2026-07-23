"""Async database engine/session helpers (architecture.md §6.2 — relational store).

Dev uses SQLite (aiosqlite); production a Postgres URL. `init_models` creates tables for the
dev/local path; a real deployment would use migrations.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.bot.models import Base


def make_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, future=True)
    if database_url.startswith("sqlite"):
        # Reasoning-inclusive turns + the F-007 scheduler mean several sessions write concurrently.
        # Default (rollback-journal, ~5s busy wait) threw "database is locked" live when a second
        # message arrived while a long turn's transaction was open. WAL lets readers run alongside
        # a writer, and busy_timeout makes a competing writer WAIT instead of failing.
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - dev-sqlite plumbing
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # `create_all` only creates tables that do not exist yet, so a constraint added to an
        # already-created table never lands on an existing dev DB. This one carries a correctness
        # invariant (ISS-011: the same photo delivered twice), so it is applied explicitly and
        # idempotently rather than waiting for a fresh database.
        if conn.dialect.name == "sqlite":
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_send_user_asset "
                "ON media_sends (user_id, asset_id)"
            )


@asynccontextmanager
async def session_scope(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A transactional scope: commit on success, rollback on error."""
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
