"""
Redis-backed queue for analytics refresh jobs.

Survives process restarts (jobs remain in the list until processed) and ensures
only one worker consumes each job across replicas (BRPOP).

The worker uses a dedicated Redis client with no socket read timeout so BRPOP
does not fight the default REDIS_TIMEOUT (5s) used by the shared pool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.analytics_service import AnalyticsRefreshService
from app.db.models import AnalyticsRefreshLog

logger = logging.getLogger(__name__)

QUEUE_KEY = "admin:analytics_refresh:queue"
LOOKBACK_DAYS = int(os.environ.get("ANALYTICS_INCREMENTAL_DAYS", "7"))
# BRPOP block time; socket timeout must exceed this (worker client uses None).
BRPOP_WAIT_SECONDS = int(os.environ.get("ANALYTICS_QUEUE_BRPOP_SECONDS", "5"))
WORKER_IDLE_SLEEP_SECONDS = 2
WORKER_ERROR_SLEEP_SECONDS = 5

_worker_client: Optional[Redis] = None


async def _get_worker_redis_client() -> Redis:
    """Dedicated client for blocking BRPOP (socket_timeout=None)."""
    global _worker_client
    if _worker_client is not None:
        return _worker_client

    from db.redis import EntraIdCredentialProvider, get_redis
    from redis.asyncio.connection import ConnectionPool, SSLConnection

    shared = await get_redis()
    # Mirror shared connector settings but allow long-blocking reads.
    pool_kwargs: Dict[str, Any] = {
        "host": shared.host,
        "port": shared.port,
        "db": shared.db,
        "decode_responses": shared.decode_responses,
        "max_connections": 4,
        "socket_timeout": None,
        "socket_connect_timeout": max(10, shared.socket_connect_timeout or 10),
    }
    if shared.use_entra_auth and shared._token_manager and shared.entra_principal_id:
        pool_kwargs["credential_provider"] = EntraIdCredentialProvider(
            shared.entra_principal_id,
            shared._token_manager,
        )
    elif shared.password:
        pool_kwargs["password"] = shared.password
    if shared.ssl:
        pool_kwargs["connection_class"] = SSLConnection
        if shared.ssl_cert_reqs:
            pool_kwargs["ssl_cert_reqs"] = shared.ssl_cert_reqs
        if shared.ssl_ca_certs:
            pool_kwargs["ssl_ca_certs"] = shared.ssl_ca_certs

    _worker_client = Redis(connection_pool=ConnectionPool(**pool_kwargs))

    await _worker_client.ping()
    logger.info(
        "Analytics refresh worker Redis client ready (host=%s:%s, brpop_wait=%ss)",
        shared.host,
        shared.port,
        BRPOP_WAIT_SECONDS,
    )
    return _worker_client


async def _close_worker_redis_client() -> None:
    global _worker_client
    if _worker_client is not None:
        await _worker_client.aclose()
        _worker_client = None


class AnalyticsRefreshQueue:
    @classmethod
    async def recover_pending_jobs(cls) -> None:
        """Re-queue DB rows left in 'queued' after a restart or Redis outage."""
        from app.db.pgsql import get_admin_db

        async for db in get_admin_db():
            await AnalyticsRefreshService.reconcile_stale_refreshes(db)
            stmt = (
                select(AnalyticsRefreshLog)
                .where(AnalyticsRefreshLog.status == "queued")
                .order_by(AnalyticsRefreshLog.started_at.asc())
            )
            pending = (await db.execute(stmt)).scalars().all()
            if not pending:
                return

            for log in pending:
                if log.date_from and log.date_to:
                    days_back = max(1, (log.date_to.date() - log.date_from.date()).days)
                else:
                    days_back = LOOKBACK_DAYS
                job = {
                    "log_id": log.id,
                    "days_back": days_back,
                    "refresh_type": log.refresh_type or "incremental",
                    "triggered_by": log.triggered_by,
                }
                payload = json.dumps(job)
                try:
                    from db.redis import get_redis

                    redis = await get_redis()
                    await redis.rpush(QUEUE_KEY, payload)
                    logger.info("Recovered analytics refresh log_id=%s onto Redis queue", log.id)
                except Exception as exc:
                    logger.warning(
                        "Recovering analytics refresh log_id=%s in-process: %s",
                        log.id,
                        exc,
                    )
                    cls._spawn_in_process_job(
                        log_id=log.id,
                        days_back=days_back,
                        refresh_type=job["refresh_type"],
                        triggered_by=job.get("triggered_by"),
                    )
            return

    @classmethod
    async def enqueue_scheduled(cls, db: AsyncSession) -> Dict[str, Any]:
        """Called from the midnight admin scheduler."""
        return await cls._enqueue(
            db,
            days_back=LOOKBACK_DAYS,
            refresh_type="incremental",
            triggered_by=None,
        )

    @classmethod
    async def enqueue_manual(
        cls,
        db: AsyncSession,
        *,
        triggered_by: Optional[str],
        days_back: int = LOOKBACK_DAYS,
        refresh_type: str = "incremental",
    ) -> Dict[str, Any]:
        return await cls._enqueue(
            db,
            days_back=days_back,
            refresh_type=refresh_type,
            triggered_by=triggered_by,
        )

    @classmethod
    async def _has_completed_refresh(cls, db: AsyncSession) -> bool:
        stmt = (
            select(AnalyticsRefreshLog.id)
            .where(AnalyticsRefreshLog.status == "completed")
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none() is not None

    @classmethod
    def _spawn_in_process_job(
        cls,
        *,
        log_id: int,
        days_back: int,
        refresh_type: str,
        triggered_by: Optional[str],
    ) -> None:
        asyncio.create_task(
            AnalyticsRefreshService.run_queued_job(
                log_id=log_id,
                days_back=days_back,
                refresh_type=refresh_type,
                triggered_by=triggered_by,
            ),
            name=f"analytics_refresh_{log_id}",
        )

    @classmethod
    async def _enqueue(
        cls,
        db: AsyncSession,
        *,
        days_back: int,
        refresh_type: str,
        triggered_by: Optional[str],
    ) -> Dict[str, Any]:
        active = await AnalyticsRefreshService._find_active_refresh(db)
        if active:
            return {
                "status": "already_running",
                "refresh_log_id": active.id,
                "message": "An analytics refresh is already in progress.",
            }

        to_date = date.today()
        from_date = to_date - timedelta(days=days_back)
        log = AnalyticsRefreshLog(
            refresh_type=refresh_type,
            started_at=datetime.utcnow(),
            status="queued",
            triggered_by=triggered_by,
            date_from=datetime.combine(from_date, datetime.min.time()),
            date_to=datetime.combine(to_date, datetime.min.time()),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

        job = {
            "log_id": log.id,
            "days_back": days_back,
            "refresh_type": refresh_type,
            "triggered_by": triggered_by,
        }
        payload = json.dumps(job)

        queued_via_redis = False
        try:
            from db.redis import get_redis

            redis = await get_redis()
            await redis.rpush(QUEUE_KEY, payload)
            queued_via_redis = True
            logger.info(
                "Analytics refresh queued in Redis (log_id=%s, type=%s, days_back=%s)",
                log.id,
                refresh_type,
                days_back,
            )
        except Exception as exc:
            logger.warning(
                "Redis unavailable for analytics queue (log_id=%s), running in-process: %s",
                log.id,
                exc,
            )
            cls._spawn_in_process_job(
                log_id=log.id,
                days_back=days_back,
                refresh_type=refresh_type,
                triggered_by=triggered_by,
            )

        return {
            "status": "queued" if queued_via_redis else "accepted",
            "refresh_log_id": log.id,
            "refresh_type": refresh_type,
            "date_from": str(from_date),
            "date_to": str(to_date),
            "days_back": days_back,
            "delivery": "redis" if queued_via_redis else "in_process",
        }

    @classmethod
    async def worker_loop(cls) -> None:
        """BRPOP consumer; uses a blocking-safe Redis client."""
        logger.info("Analytics refresh queue worker started")
        try:
            await cls.recover_pending_jobs()
        except Exception as exc:
            logger.warning("Analytics refresh recovery skipped: %s", exc)
        while True:
            try:
                client = await _get_worker_redis_client()
                result = await client.brpop(QUEUE_KEY, timeout=BRPOP_WAIT_SECONDS)
                if not result:
                    continue
                _, raw = result
                job = json.loads(raw)
                log_id = job["log_id"]
                logger.info("Analytics refresh worker picked up log_id=%s", log_id)

                await AnalyticsRefreshService.run_queued_job(
                    log_id=log_id,
                    days_back=int(job["days_back"]),
                    refresh_type=str(job["refresh_type"]),
                    triggered_by=job.get("triggered_by"),
                )
            except asyncio.CancelledError:
                await _close_worker_redis_client()
                raise
            except (RedisTimeoutError, RedisError, ConnectionError, OSError) as exc:
                logger.warning(
                    "Analytics refresh worker Redis error (will retry in %ss): %s",
                    WORKER_ERROR_SLEEP_SECONDS,
                    exc,
                )
                await _close_worker_redis_client()
                await asyncio.sleep(WORKER_ERROR_SLEEP_SECONDS)
            except Exception as exc:
                logger.exception("Analytics refresh worker error: %s", exc)
                await asyncio.sleep(WORKER_IDLE_SLEEP_SECONDS)
