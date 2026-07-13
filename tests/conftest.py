"""Shared test fixtures — an isolated in-memory async DB per test.

Runnable test code for the merge gate (CLAUDE.md: a feature branch merges only after all tests in
`tests/` pass). Tests trace to the F-001 spec via `TC-...` ids in their names/docstrings.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from services.bot.db import init_models, make_sessionmaker
from services.bot.personas_seed import seed_personas


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # StaticPool keeps the in-memory DB alive across sessions within a single test.
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await init_models(engine)
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(sessionmaker) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def seeded_db(db: AsyncSession) -> AsyncSession:
    await seed_personas(db)
    await db.commit()
    return db
