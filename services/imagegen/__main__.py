"""Night-batch entrypoint: `python -m services.imagegen` (architecture.md §6.1, DFD-3).

Run from cron/systemd inside the media window. Gates itself: exits quietly when the window is
closed or the queue is empty (FR-008-11), otherwise drains the queue with the configured backend
and prints the metrics snapshot (NFR-008-08).
"""
from __future__ import annotations

import asyncio
import logging

from services.bot.config import get_settings
from services.bot.db import make_engine, make_sessionmaker
from services.imagegen.config import get_image_settings
from services.imagegen.runner import ImageRunner, check_empty_archive_alert

log = logging.getLogger(__name__)


async def _main() -> None:
    logging.basicConfig(level="INFO")
    engine = make_engine(get_settings().database_url)
    sessionmaker = make_sessionmaker(engine)
    runner = ImageRunner(get_image_settings())
    try:
        if not await runner.should_run(sessionmaker):
            log.info("media window closed or queue empty — nothing to do")
            return
        snapshot = await runner.run_batch(sessionmaker)
        log.info("night batch finished: %s", snapshot)
        await check_empty_archive_alert(sessionmaker)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
