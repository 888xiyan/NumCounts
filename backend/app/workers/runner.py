"""Separate process entry point for the MVP's one-at-a-time calculation loop."""

import asyncio
import logging

from app.core.config import settings
from app.db.session import async_session_factory
from app.services.calculation_service import recover_interrupted_records, run_pending

logger = logging.getLogger(__name__)


async def run() -> None:
    """Poll pending records in FIFO order; the service serializes executions."""
    async with async_session_factory() as session:
        recovered = await recover_interrupted_records(session)
    if recovered:
        logger.warning("recovered %s interrupted calculation records", len(recovered))
    while True:
        async with async_session_factory() as session:
            records, skipped = await run_pending(
                session, limit=settings.runner_batch_size
            )
        if records or skipped:
            logger.info(
                "calculation batch finished: processed=%s skipped=%s",
                len(records),
                skipped,
            )
            continue
        await asyncio.sleep(settings.runner_poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run())
