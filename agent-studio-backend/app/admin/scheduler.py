"""
Daily workflow LLM scan scheduler (Redis leader election).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

ADMIN_SCAN_LOCK_KEY = "admin:llm_workflow_scan:leader"
ADMIN_SCAN_LOCK_TTL = 120


def _seconds_until_midnight(tz_name: str) -> float:
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, (tomorrow - now).total_seconds())


async def _run_scan_once() -> None:
    from db.pgsql import get_admin_db
    from app.admin.services.workflow_model_scan_service import WorkflowModelScanService

    async for db in get_admin_db():
        summary = await WorkflowModelScanService.run_full_scan(db)
        logger.info("Admin workflow LLM scan complete: %s", summary)
        break


async def _run_analytics_refresh_once() -> None:
    """Queue nightly analytics snapshot rebuild (incremental or weekly full)."""
    from db.pgsql import get_admin_db
    from app.admin.services.analytics_refresh_queue import AnalyticsRefreshQueue

    async for db in get_admin_db():
        result = await AnalyticsRefreshQueue.enqueue_scheduled(db)
        logger.info("Analytics refresh scheduled: %s", result)
        break


async def _run_midnight_admin_jobs() -> None:
    """Jobs run once per day at midnight (leader-elected)."""
    await _run_scan_once()
    await _run_analytics_refresh_once()


async def admin_scheduler_supervisor(redis) -> None:
    """Elect leader and run workflow model scan daily at midnight."""
    import uuid

    worker_id = str(uuid.uuid4())[:8]
    tz_name = os.environ.get("ADMIN_SCAN_TIMEZONE", "UTC")
    logger.info("Admin LLM scheduler supervisor started (worker=%s, tz=%s)", worker_id, tz_name)

    while True:
        try:
            acquired = await redis.set(
                ADMIN_SCAN_LOCK_KEY,
                worker_id,
                nx=True,
                ex=ADMIN_SCAN_LOCK_TTL,
            )
            if acquired:
                wait = _seconds_until_midnight(tz_name)
                logger.info("Admin scan leader: sleeping %.0fs until midnight", wait)
                await asyncio.sleep(wait)
                try:
                    await _run_midnight_admin_jobs()
                except Exception as exc:
                    logger.error("Admin midnight jobs failed: %s", exc, exc_info=True)
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Admin scheduler loop error: %s", exc)
            await asyncio.sleep(30)
