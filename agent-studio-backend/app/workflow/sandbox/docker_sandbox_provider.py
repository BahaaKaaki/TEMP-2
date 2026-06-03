"""
Docker sandbox provider — manages sandbox lifecycle via the Docker daemon.

For dev parity with the ACI provider, this implements:

* **Reservations** (pause-hold): in-memory dict of reserved sandboxes with
  per-sandbox asyncio timers. When the timer fires, the sandbox is
  destroyed. A matching ``reclaim`` cancels the timer and hands the
  sandbox back.
* **Wash-and-return hot pool**: on ``release`` we try to wash the sandbox
  (wipe /workspace + /outputs, confirm health) and keep it ready for the
  next acquire instead of destroying it. Falls back to destroy on wash
  failure.

The Docker provider is single-process (no Redis), so all state is in
memory and scoped to the current worker.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from typing import Any

from .docker_sandbox import DockerSandbox
from .sandbox import Sandbox
from .sandbox_provider import SandboxProvider

logger = logging.getLogger(__name__)


class DockerSandboxProvider(SandboxProvider):
    """Creates and tracks Docker-backed sandboxes with reservation support."""

    def __init__(
        self,
        *,
        image: str = "agent-studio-sandbox:latest",
        cpu_count: float = 1.0,
        mem_limit: str = "512m",
        pids_limit: int = 100,
    ):
        self._image = image
        self._cpu = cpu_count
        self._mem = mem_limit
        self._pids = pids_limit
        self._sandboxes: dict[str, DockerSandbox] = {}
        self._reserved: dict[str, DockerSandbox] = {}
        self._reservation_timers: dict[str, asyncio.Task] = {}
        self._hot_pool: deque[DockerSandbox] = deque()

        from config.keyvault import cfg
        self._pause_idle_timeout = max(
            30, int(getattr(cfg, "SANDBOX_PAUSE_IDLE_TIMEOUT_SECONDS", None) or 600)
        )
        self._wash_enabled = bool(
            getattr(cfg, "SANDBOX_WASH_CYCLE_ENABLED", True)
        )
        self._wash_timeout = max(
            5, int(getattr(cfg, "SANDBOX_WASH_CYCLE_TIMEOUT_SECONDS", None) or 15)
        )
        self._hot_min = max(
            0, int(getattr(cfg, "SANDBOX_HOT_TIER_MIN", None) or 0)
        )

        self._wash_success_count = 0
        self._wash_failure_count = 0
        self._reclaim_success_count = 0
        self._reclaim_miss_count = 0
        self._reservation_expiry_count = 0

    async def acquire(self, execution_id: str) -> str:
        sandbox_id = f"{execution_id}-{uuid.uuid4().hex[:8]}"

        if self._hot_pool:
            pooled = self._hot_pool.popleft()
            pooled._id = sandbox_id
            if await pooled.health_check():
                self._sandboxes[sandbox_id] = pooled
                logger.info(
                    "Acquired sandbox %s from hot pool (image %s)",
                    sandbox_id, self._image,
                )
                return sandbox_id
            else:
                try:
                    await pooled.cleanup()
                except Exception:
                    pass

        sandbox = DockerSandbox(
            sandbox_id,
            cpu_count=self._cpu,
            mem_limit=self._mem,
            pids_limit=self._pids,
            image=self._image,
        )
        self._sandboxes[sandbox_id] = sandbox
        logger.info("Acquired sandbox %s for execution %s", sandbox_id, execution_id)
        return sandbox_id

    async def get(self, sandbox_id: str) -> Sandbox | None:
        return self._sandboxes.get(sandbox_id) or self._reserved.get(sandbox_id)

    async def release(self, sandbox_id: str) -> None:
        sandbox = self._sandboxes.pop(sandbox_id, None)
        if sandbox is None:
            sandbox = self._reserved.pop(sandbox_id, None)
            timer = self._reservation_timers.pop(sandbox_id, None)
            if timer is not None and not timer.done():
                timer.cancel()
        if sandbox is None:
            return

        if self._wash_enabled:
            try:
                washed = await sandbox.wash(timeout=self._wash_timeout)
            except Exception as exc:
                logger.warning(
                    "Docker wash raised for %s: %s; will destroy",
                    sandbox_id, exc,
                )
                washed = False

            if washed and len(self._hot_pool) < max(1, self._hot_min):
                self._hot_pool.append(sandbox)
                self._wash_success_count += 1
                logger.info(
                    "Released %s → washed and returned to hot pool (size %d)",
                    sandbox_id, len(self._hot_pool),
                )
                return
            if not washed:
                self._wash_failure_count += 1

        try:
            await sandbox.cleanup()
        except Exception as exc:
            logger.warning("Cleanup for %s failed: %s", sandbox_id, exc)
        logger.info("Released sandbox %s (destroyed)", sandbox_id)

    async def reserve(self, sandbox_id: str, ttl_seconds: int) -> None:
        sandbox = self._sandboxes.pop(sandbox_id, None)
        if sandbox is None:
            logger.warning("Docker reserve: unknown sandbox %s", sandbox_id)
            return

        ttl = max(30, int(ttl_seconds or self._pause_idle_timeout))
        self._reserved[sandbox_id] = sandbox

        async def _expire() -> None:
            try:
                await asyncio.sleep(ttl)
                stale = self._reserved.pop(sandbox_id, None)
                self._reservation_timers.pop(sandbox_id, None)
                if stale is None:
                    return
                self._reservation_expiry_count += 1
                logger.info(
                    "Reservation expired for %s after %ds; destroying",
                    sandbox_id, ttl,
                )
                try:
                    await stale.cleanup()
                except Exception as exc:
                    logger.warning(
                        "Expiry cleanup failed for %s: %s",
                        sandbox_id, exc,
                    )
            except asyncio.CancelledError:
                pass

        timer = asyncio.create_task(_expire())
        self._reservation_timers[sandbox_id] = timer
        logger.info("Reserved Docker sandbox %s for %ds", sandbox_id, ttl)

    async def reclaim(self, sandbox_id: str) -> Sandbox | None:
        if not sandbox_id:
            self._reclaim_miss_count += 1
            return None

        sandbox = self._reserved.pop(sandbox_id, None)
        if sandbox is None:
            self._reclaim_miss_count += 1
            return None

        timer = self._reservation_timers.pop(sandbox_id, None)
        if timer is not None and not timer.done():
            timer.cancel()

        if not await sandbox.health_check():
            try:
                await sandbox.cleanup()
            except Exception:
                pass
            self._reclaim_miss_count += 1
            logger.info("Reclaim miss (unhealthy) for %s", sandbox_id)
            return None

        self._sandboxes[sandbox_id] = sandbox
        self._reclaim_success_count += 1
        logger.info("Reclaimed Docker sandbox %s", sandbox_id)
        return sandbox

    async def pool_status(self) -> dict[str, Any]:
        return {
            "provider": "docker",
            "hot_target": self._hot_min,
            "hot_current": len(self._hot_pool),
            "cold_target": 0,
            "cold_current": 0,
            "reserved_current": len(self._reserved),
            "active_total": len(self._sandboxes) + len(self._reserved),
            "pool_target": self._hot_min,
            "pool_current": len(self._hot_pool),
            "worker_active_count": len(self._sandboxes),
            "worker_inflight_creates": 0,
            "pause_idle_timeout_s": self._pause_idle_timeout,
            "wash_enabled": self._wash_enabled,
            "wash_success_count": self._wash_success_count,
            "wash_failure_count": self._wash_failure_count,
            "reclaim_success_count": self._reclaim_success_count,
            "reclaim_miss_count": self._reclaim_miss_count,
            "reservation_expiry_count": self._reservation_expiry_count,
            "recent_errors": [],
        }

    async def shutdown(self) -> None:
        for timer in list(self._reservation_timers.values()):
            if not timer.done():
                timer.cancel()
        self._reservation_timers.clear()

        for sid in list(self._reserved.keys()):
            sandbox = self._reserved.pop(sid, None)
            if sandbox is not None:
                try:
                    await sandbox.cleanup()
                except Exception:
                    pass

        ids = list(self._sandboxes.keys())
        for sid in ids:
            sandbox = self._sandboxes.pop(sid, None)
            if sandbox is not None:
                try:
                    await sandbox.cleanup()
                except Exception:
                    pass

        while self._hot_pool:
            sandbox = self._hot_pool.popleft()
            try:
                await sandbox.cleanup()
            except Exception:
                pass

        logger.info("Shutdown: released %d active sandbox(es)", len(ids))
