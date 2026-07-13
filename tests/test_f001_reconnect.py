"""NFR-001-11 — the bot process must retry (never crash-exit) on Telegram network blips."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.exceptions import TelegramNetworkError

from services.bot.app import _run_polling_with_reconnect


async def test_nfr_001_11_01_retries_after_network_failure_then_succeeds():
    """TC-NFR-001-11-01 — a transient network failure is retried with backoff, not raised/crashed."""
    dp = AsyncMock()
    bot = AsyncMock()
    # First call fails with a Telegram network error; second call "succeeds" (returns normally,
    # simulating polling exiting cleanly once connectivity is restored).
    dp.start_polling.side_effect = [
        TelegramNetworkError(method="getMe", message="boom"),
        None,
    ]
    with patch("services.bot.app.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await _run_polling_with_reconnect(dp, bot)  # must not raise

    assert dp.start_polling.await_count == 2
    sleep_mock.assert_awaited_once()  # backed off exactly once before the successful retry


async def test_nfr_001_11_02_retries_on_os_error_too():
    """TC-NFR-001-11-02 — a raw OSError (e.g. WinError 121 semaphore timeout) is retried, not fatal."""
    dp = AsyncMock()
    bot = AsyncMock()
    dp.start_polling.side_effect = [OSError("semaphore timeout"), None]
    with patch("services.bot.app.asyncio.sleep", new=AsyncMock()):
        await _run_polling_with_reconnect(dp, bot)
    assert dp.start_polling.await_count == 2


async def test_nfr_001_11_03_backoff_is_capped_and_grows():
    """TC-NFR-001-11-03 — repeated failures back off with growing, capped delays (never 0, never unbounded)."""
    dp = AsyncMock()
    bot = AsyncMock()
    dp.start_polling.side_effect = [TelegramNetworkError(method="getMe", message="x")] * 5 + [None]
    with patch("services.bot.app.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await _run_polling_with_reconnect(dp, bot)

    delays = [call.args[0] for call in sleep_mock.await_args_list]
    assert len(delays) == 5
    assert delays == sorted(delays)  # non-decreasing (grows or plateaus at the cap)
    assert all(0 < d <= 60 for d in delays)
