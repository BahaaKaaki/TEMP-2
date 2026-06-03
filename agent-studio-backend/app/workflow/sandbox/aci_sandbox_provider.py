"""
ACI sandbox provider with a Redis-backed three-tier pool.

Tier model
----------
* **HOT tier** (``sandbox:pool:hot``): running, idle containers, immediately
  acquirable. Target size = ``max(HOT_TIER_MIN, active + HEADROOM)``.
* **COLD tier** (``sandbox:pool:cold``): pre-created and *stopped* containers
  (no CPU/memory billing). Fast to restart (10-30s) without re-pulling the
  image. Target size = ``COLD_TIER_TARGET``.
* **ACTIVE**: running and in use by a workflow — either executing code or
  *reserved* during an ``output.ask()`` pause.

Reservations (pause-hold)
-------------------------
When a script exits 42, the node calls :meth:`reserve` instead of
:meth:`release`. The container stays alive for up to
``SANDBOX_PAUSE_IDLE_TIMEOUT_SECONDS``; if the user responds within that
window, :meth:`reclaim` hands the same container back, preserving in-memory
globals and avoiding re-injection of files and checkpoint data. If the timer
expires, a background sweeper destroys the container — the Postgres
checkpoint is still authoritative, so eventual resume falls back to the
slow path (new container + checkpoint injection).

Wash cycle
----------
On a clean :meth:`release`, the provider asks the sandbox to :meth:`wash`
itself (rm /workspace/*, /outputs/*, health check). A washed container is
pushed back to the hot tier for immediate reuse by the next workflow. A
failed wash destroys the container instead — we never return a dirty
sandbox to the pool.

Leader / multi-worker
---------------------
Any worker may acquire/release/reserve/reclaim against Redis. A single
leader worker (elected via Redis SETNX in main.py) runs the replenisher,
TTL loop, orphan cleanup, reservation sweeper, and tier rebalancer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from collections import deque
from typing import Any

from .aci_sandbox import AciSandbox
from .sandbox import Sandbox
from .sandbox_provider import SandboxProvider

logger = logging.getLogger(__name__)

_LABEL_KEY = "managed-by"
_LABEL_VALUE = "agent-studio-sandbox"

_REDIS_HOT_POOL_KEY = "sandbox:pool:hot"
_REDIS_COLD_POOL_KEY = "sandbox:pool:cold"
_REDIS_ACTIVE_COUNT_KEY = "sandbox:active:count"
_REDIS_RESERVATION_PREFIX = "sandbox:reserved:"
_REDIS_RESERVATION_INDEX = "sandbox:reserved:index"

# Backwards-compat alias (old deployments still push to this key).
_REDIS_LEGACY_POOL_KEY = "sandbox:pool"

_RECENT_ERRORS_MAX = 20
_COUNTER_RESET_MAX = 10000  # sanity cap


def _is_transient_azure_error(exc: BaseException) -> bool:
    """Classify Azure SDK errors worth retrying.

    We retry registry-pull failures (ACR / JFrog temporarily rejecting the
    image), 429/502/503/504 throttling / gateway issues, and raw network
    errors (DNS / TCP flakes).  Quota and auth errors are NOT retried: they
    won't self-heal.
    """
    msg = str(exc) or ""
    lower = msg.lower()

    try:
        from azure.core.exceptions import (
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        )
    except Exception:
        HttpResponseError = tuple()  # type: ignore[assignment]
        ServiceRequestError = tuple()  # type: ignore[assignment]
        ServiceResponseError = tuple()  # type: ignore[assignment]

    if isinstance(exc, (ServiceRequestError, ServiceResponseError)):
        return True

    if "registryerrorresponse" in lower or "please retry later" in lower:
        return True

    status = getattr(exc, "status_code", None)
    if status is None and isinstance(exc, HttpResponseError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int) and status in {408, 429, 500, 502, 503, 504}:
        return True

    if "timed out" in lower or "connection reset" in lower:
        return True

    # ARM long-running operation finished with HTTP 200 but provisioning
    # state is Canceled (quota, policy, concurrent delete, Azure-side flake).
    # The SDK surfaces this as "Operation returned an invalid status 'OK'".
    if "invalid status" in lower and ("canceled" in lower or "cancelled" in lower):
        return True

    # Occasional race: CG deleted or not yet visible while poller / follow-up
    # GET runs — a fresh create with a new name often succeeds.
    if "resourcenotfound" in lower and "sandbox-" in lower:
        return True

    return False


class AciSandboxProvider(SandboxProvider):
    """ACI provider with three-tier pool, reservations, and wash-and-reuse."""

    def __init__(self):
        from config.keyvault import cfg

        self._rg = getattr(cfg, "SANDBOX_ACI_RESOURCE_GROUP", None) or ""
        self._image = getattr(cfg, "SANDBOX_IMAGE", None) or "agent-studio-sandbox:latest"
        self._cpu = getattr(cfg, "SANDBOX_ACI_CPU", None) or 1.0
        self._memory_gb = getattr(cfg, "SANDBOX_ACI_MEMORY_GB", None) or 1.5
        self._subnet_id = getattr(cfg, "SANDBOX_ACI_SUBNET_ID", None)
        self._registry_server = getattr(cfg, "SANDBOX_REGISTRY_SERVER", None)
        self._registry_username = getattr(cfg, "SANDBOX_REGISTRY_USERNAME", None)
        self._registry_password = getattr(cfg, "SANDBOX_REGISTRY_PASSWORD", None)
        self._registry_identity_id = getattr(
            cfg, "SANDBOX_REGISTRY_IDENTITY_RESOURCE_ID", None
        )

        # Autoscaling tier config.  ``SANDBOX_WARM_POOL_SIZE`` is legacy —
        # when set, it pins HOT_TIER_MIN to that value for back-compat.
        legacy_pool_size = getattr(cfg, "SANDBOX_WARM_POOL_SIZE", None)
        default_hot_min = getattr(cfg, "SANDBOX_HOT_TIER_MIN", None) or 2
        self._hot_min = int(
            legacy_pool_size
            if legacy_pool_size is not None
            else default_hot_min
        )
        self._hot_headroom = max(
            0, int(getattr(cfg, "SANDBOX_HOT_TIER_HEADROOM", None) or 2)
        )
        self._cold_target = max(
            0, int(getattr(cfg, "SANDBOX_COLD_TIER_TARGET", None) or 0)
        )
        self._rebalancer_interval = max(
            10, int(getattr(cfg, "SANDBOX_REBALANCER_INTERVAL_SECONDS", None) or 60)
        )

        self._parallel_create = max(
            1, int(getattr(cfg, "SANDBOX_POOL_PARALLEL_CREATE", None) or 2)
        )
        self._create_max_retries = max(
            0, int(getattr(cfg, "SANDBOX_CREATE_MAX_RETRIES", None) or 3)
        )
        self._create_retry_base = max(
            0.1, float(getattr(cfg, "SANDBOX_CREATE_RETRY_BASE_SECONDS", None) or 2.0)
        )
        self._ttl_minutes = getattr(cfg, "SANDBOX_CONTAINER_TTL_MINUTES", None) or 30
        self._pause_idle_timeout = max(
            30, int(getattr(cfg, "SANDBOX_PAUSE_IDLE_TIMEOUT_SECONDS", None) or 600)
        )
        self._wash_enabled = bool(
            getattr(cfg, "SANDBOX_WASH_CYCLE_ENABLED", True)
        )
        self._wash_timeout = max(
            5, int(getattr(cfg, "SANDBOX_WASH_CYCLE_TIMEOUT_SECONDS", None) or 15)
        )

        self._aci_client: Any = None
        self._active: dict[str, AciSandbox] = {}
        self._replenish_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._orphan_task: asyncio.Task | None = None
        self._reservation_sweeper_task: asyncio.Task | None = None
        self._rebalancer_task: asyncio.Task | None = None
        self._closing = False

        self._inflight_creates: int = 0
        self._recent_errors: deque[dict[str, Any]] = deque(maxlen=_RECENT_ERRORS_MAX)
        self._is_leader: bool = False

        self._wash_success_count = 0
        self._wash_failure_count = 0
        self._reclaim_success_count = 0
        self._reclaim_miss_count = 0
        self._reservation_expiry_count = 0
        self._cold_start_count = 0

    def _record_error(
        self, stage: str, exc: BaseException, sandbox_id: str | None = None
    ) -> None:
        self._recent_errors.append({
            "at": time.time(),
            "stage": stage,
            "sandbox_id": sandbox_id,
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        })

    def _worker_id(self) -> str:
        """Stable worker identifier (process-lifetime)."""
        if not hasattr(self, "_cached_worker_id"):
            import os
            self._cached_worker_id = f"w-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        return self._cached_worker_id

    def _get_client(self) -> Any:
        if self._aci_client is not None:
            return self._aci_client

        from azure.mgmt.containerinstance import ContainerInstanceManagementClient
        from config.keyvault import cfg

        aci_client_id = getattr(cfg, "AZURE_CLIENT_ID_ACI", None)
        if aci_client_id:
            from azure.identity import ManagedIdentityCredential
            credential = ManagedIdentityCredential(client_id=aci_client_id)
            logger.info("ACI auth: UAMI (client_id=%s...)", aci_client_id[:8])
        else:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            logger.info("ACI auth: DefaultAzureCredential (az CLI / system MI)")

        sub_id = getattr(cfg, "AZURE_SUBSCRIPTION_ID", None) or ""
        self._aci_client = ContainerInstanceManagementClient(
            credential=credential,
            subscription_id=sub_id,
        )
        return self._aci_client

    async def _redis_client(self):
        from db.redis import get_redis
        connector = await get_redis()
        return connector.client

    # ──────────────────────────────────────────────────────────────────
    # Autoscaling
    # ──────────────────────────────────────────────────────────────────

    async def _active_count(self) -> int:
        """Global count of acquired-or-reserved sandboxes across all workers."""
        try:
            rc = await self._redis_client()
            raw = await rc.get(_REDIS_ACTIVE_COUNT_KEY)
            if raw is None:
                return 0
            val = int(raw)
            if val < 0 or val > _COUNTER_RESET_MAX:
                await rc.set(_REDIS_ACTIVE_COUNT_KEY, 0)
                return 0
            return val
        except Exception:
            return 0

    async def _incr_active(self, by: int = 1) -> None:
        try:
            rc = await self._redis_client()
            await rc.incrby(_REDIS_ACTIVE_COUNT_KEY, by)
        except Exception:
            pass

    async def _decr_active(self, by: int = 1) -> None:
        try:
            rc = await self._redis_client()
            new_val = await rc.decrby(_REDIS_ACTIVE_COUNT_KEY, by)
            if new_val is not None and int(new_val) < 0:
                await rc.set(_REDIS_ACTIVE_COUNT_KEY, 0)
        except Exception:
            pass

    async def _hot_target(self) -> int:
        """Current hot-tier target = max(MIN, active + HEADROOM)."""
        active = await self._active_count()
        return max(self._hot_min, active + self._hot_headroom)

    # ──────────────────────────────────────────────────────────────────
    # SandboxProvider ABC
    # ──────────────────────────────────────────────────────────────────

    async def acquire(self, execution_id: str) -> str:
        sandbox_id = f"{execution_id}-{uuid.uuid4().hex[:8]}"

        sandbox = await self._claim_from_hot(sandbox_id)

        if sandbox is None:
            sandbox = await self._promote_from_cold(sandbox_id)
            if sandbox is not None:
                self._cold_start_count += 1

        if sandbox is None:
            logger.warning(
                "Both hot and cold tiers empty — creating ACI on demand for %s",
                sandbox_id,
            )
            sandbox, _ = await self._create_sandbox_with_retry(sandbox_id)

        self._active[sandbox_id] = sandbox
        await self._incr_active(1)
        logger.info("Acquired ACI sandbox %s (cg %s)", sandbox_id, sandbox._cg_name)
        return sandbox_id

    async def get(self, sandbox_id: str) -> Sandbox | None:
        return self._active.get(sandbox_id)

    async def release(self, sandbox_id: str) -> None:
        sandbox = self._active.pop(sandbox_id, None)
        if sandbox is None:
            return

        washed = False
        if self._wash_enabled:
            try:
                washed = await sandbox.wash(timeout=self._wash_timeout)
            except Exception as exc:
                logger.warning(
                    "Wash on %s raised; will destroy instead: %s",
                    sandbox._cg_name, exc,
                )
                washed = False

        try:
            if washed:
                try:
                    await self._push_to_hot(
                        sandbox._cg_name, sandbox_id, self._ip_of(sandbox)
                    )
                    self._wash_success_count += 1
                    logger.info(
                        "Released %s → washed and returned to hot pool",
                        sandbox._cg_name,
                    )
                    return
                except Exception as exc:
                    logger.warning(
                        "Wash succeeded but push-to-pool failed on %s: %s; "
                        "falling back to destroy",
                        sandbox._cg_name, exc,
                    )
                    self._wash_failure_count += 1

            self._wash_failure_count += 1 if self._wash_enabled else 0
            await sandbox.cleanup()
            logger.info("Released ACI sandbox %s (destroyed)", sandbox_id)
        finally:
            await self._decr_active(1)

    async def reserve(self, sandbox_id: str, ttl_seconds: int) -> None:
        sandbox = self._active.pop(sandbox_id, None)
        if sandbox is None:
            logger.warning("Reserve called for unknown sandbox %s", sandbox_id)
            return

        ttl = max(30, int(ttl_seconds or self._pause_idle_timeout))
        now = time.time()

        entry = {
            "cg_name": sandbox._cg_name,
            "ip": self._ip_of(sandbox),
            "sandbox_id": sandbox_id,
            "worker_id": self._worker_id(),
            "reserved_at": now,
            "expires_at": now + ttl,
        }
        try:
            rc = await self._redis_client()
            await rc.set(
                _REDIS_RESERVATION_PREFIX + sandbox_id,
                json.dumps(entry),
                ex=ttl + 30,
            )
            await rc.zadd(
                _REDIS_RESERVATION_INDEX, {sandbox_id: entry["expires_at"]}
            )
            logger.info(
                "Reserved %s for %ds (expires at %.0f)",
                sandbox._cg_name, ttl, entry["expires_at"],
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist reservation for %s: %s — releasing instead",
                sandbox_id, exc,
            )
            try:
                await sandbox.cleanup()
            finally:
                await self._decr_active(1)

    async def reclaim(self, sandbox_id: str) -> Sandbox | None:
        if not sandbox_id:
            self._reclaim_miss_count += 1
            return None

        try:
            rc = await self._redis_client()
            key = _REDIS_RESERVATION_PREFIX + sandbox_id
            raw = await rc.get(key)
            if raw is None:
                self._reclaim_miss_count += 1
                logger.info("Reclaim miss for %s (reservation gone)", sandbox_id)
                return None

            deleted = await rc.delete(key)
            await rc.zrem(_REDIS_RESERVATION_INDEX, sandbox_id)
            if not deleted:
                self._reclaim_miss_count += 1
                return None

            entry = json.loads(raw)
            now = time.time()
            if now > entry.get("expires_at", now):
                self._reclaim_miss_count += 1
                logger.info("Reclaim miss for %s (expired)", sandbox_id)
                asyncio.create_task(self._delete_container_group(entry["cg_name"]))
                return None

            client = self._get_client()
            sandbox = AciSandbox(
                sandbox_id,
                resource_group=self._rg,
                container_group_name=entry["cg_name"],
                container_name="sandbox",
                aci_client=client,
                container_ip=entry.get("ip", ""),
            )

            if not await sandbox.health_check():
                logger.warning(
                    "Reclaim: sandbox %s failed health check; destroying",
                    entry["cg_name"],
                )
                asyncio.create_task(self._delete_container_group(entry["cg_name"]))
                self._reclaim_miss_count += 1
                return None

            self._active[sandbox_id] = sandbox
            self._reclaim_success_count += 1
            logger.info(
                "Reclaimed %s (cg %s) — fast-path resume",
                sandbox_id, entry["cg_name"],
            )
            return sandbox
        except Exception as exc:
            logger.warning("Reclaim failed for %s: %s", sandbox_id, exc)
            self._record_error("reclaim", exc, sandbox_id)
            self._reclaim_miss_count += 1
            return None

    async def shutdown(self) -> None:
        self._closing = True

        for task in (
            self._replenish_task,
            self._cleanup_task,
            self._orphan_task,
            self._reservation_sweeper_task,
            self._rebalancer_task,
        ):
            if task and not task.done():
                task.cancel()

        active_ids = list(self._active.keys())
        for sid in active_ids:
            try:
                sandbox = self._active.pop(sid, None)
                if sandbox is not None:
                    await sandbox.cleanup()
                    await self._decr_active(1)
            except Exception as exc:
                logger.warning("Shutdown release of %s failed: %s", sid, exc)

        logger.info(
            "ACI sandbox provider shut down (released %d active; shared pool untouched)",
            len(active_ids),
        )

    # ──────────────────────────────────────────────────────────────────
    # Redis pool operations — hot tier
    # ──────────────────────────────────────────────────────────────────

    async def _claim_from_hot(self, sandbox_id: str) -> AciSandbox | None:
        """Pop a running warm container from the hot tier."""
        try:
            rc = await self._redis_client()
            raw = await rc.lpop(_REDIS_HOT_POOL_KEY)
            if raw is None:
                raw = await rc.lpop(_REDIS_LEGACY_POOL_KEY)
                if raw is None:
                    return None

            entry = json.loads(raw)
            cg_name = entry["cg_name"]
            container_ip = entry.get("ip", "")
            client = self._get_client()
            sandbox = AciSandbox(
                sandbox_id,
                resource_group=self._rg,
                container_group_name=cg_name,
                container_name="sandbox",
                aci_client=client,
                container_ip=container_ip,
            )
            logger.info(
                "Claimed hot container %s (cg %s, ip %s)",
                sandbox_id, cg_name, container_ip,
            )
            return sandbox
        except Exception as exc:
            logger.warning("Redis hot-pool claim failed: %s", exc)
            return None

    async def _push_to_hot(
        self, cg_name: str, sandbox_id: str, container_ip: str
    ) -> None:
        entry = json.dumps({
            "cg_name": cg_name,
            "sandbox_id": sandbox_id,
            "ip": container_ip,
            "created_at": time.time(),
        })
        rc = await self._redis_client()
        await rc.rpush(_REDIS_HOT_POOL_KEY, entry)

    async def _hot_len(self) -> int:
        try:
            rc = await self._redis_client()
            a = await rc.llen(_REDIS_HOT_POOL_KEY)
            b = await rc.llen(_REDIS_LEGACY_POOL_KEY)
            return int(a or 0) + int(b or 0)
        except Exception:
            return 0

    # ──────────────────────────────────────────────────────────────────
    # Redis pool operations — cold tier (stopped ACIs)
    # ──────────────────────────────────────────────────────────────────

    async def _push_to_cold(
        self, cg_name: str, container_ip: str, stopped_at: float | None = None
    ) -> None:
        entry = json.dumps({
            "cg_name": cg_name,
            "ip": container_ip,
            "stopped_at": stopped_at or time.time(),
        })
        rc = await self._redis_client()
        await rc.rpush(_REDIS_COLD_POOL_KEY, entry)

    async def _lpop_cold(self) -> dict[str, Any] | None:
        try:
            rc = await self._redis_client()
            raw = await rc.lpop(_REDIS_COLD_POOL_KEY)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    async def _cold_len(self) -> int:
        try:
            rc = await self._redis_client()
            return int(await rc.llen(_REDIS_COLD_POOL_KEY) or 0)
        except Exception:
            return 0

    async def _promote_from_cold(self, sandbox_id: str) -> AciSandbox | None:
        """Start a stopped container from the cold tier and return it running.

        This is materially faster than ``_create_sandbox_with_retry`` because
        the container group already exists — Azure just starts it. Image
        is usually cached on the node so no pull is needed.
        """
        entry = await self._lpop_cold()
        if entry is None:
            return None

        cg_name = entry["cg_name"]
        try:
            await self._start_container_group(cg_name)
        except Exception as exc:
            logger.warning(
                "Cold → hot start failed for %s (%s); destroying stale entry",
                cg_name, exc,
            )
            self._record_error("cold_start", exc, cg_name)
            asyncio.create_task(self._delete_container_group(cg_name))
            return None

        ip = await self._read_container_ip(cg_name) or entry.get("ip", "")
        client = self._get_client()
        sandbox = AciSandbox(
            sandbox_id,
            resource_group=self._rg,
            container_group_name=cg_name,
            container_name="sandbox",
            aci_client=client,
            container_ip=ip,
        )

        for attempt in range(6):
            if await sandbox.health_check():
                break
            await asyncio.sleep(2 ** attempt)
        else:
            logger.warning(
                "Cold → hot %s never became healthy; destroying", cg_name,
            )
            asyncio.create_task(self._delete_container_group(cg_name))
            return None

        logger.info("Promoted cold → hot: %s (%s)", cg_name, ip)
        return sandbox

    # ──────────────────────────────────────────────────────────────────
    # Observability
    # ──────────────────────────────────────────────────────────────────

    async def pool_status(self) -> dict[str, Any]:
        hot_current = await self._hot_len()
        cold_current = await self._cold_len()
        hot_target = await self._hot_target()
        active_total = await self._active_count()

        reserved_current = 0
        try:
            rc = await self._redis_client()
            reserved_current = int(
                await rc.zcard(_REDIS_RESERVATION_INDEX) or 0
            )
        except Exception:
            pass

        return {
            "provider": "aci",
            "resource_group": self._rg,
            "image": self._image,

            "hot_target": hot_target,
            "hot_min": self._hot_min,
            "hot_headroom": self._hot_headroom,
            "hot_current": hot_current,

            "cold_target": self._cold_target,
            "cold_current": cold_current,

            "reserved_current": reserved_current,
            "active_total": active_total,

            "pool_target": hot_target,
            "pool_current": hot_current,

            "parallel_create": self._parallel_create,
            "create_max_retries": self._create_max_retries,
            "ttl_minutes": self._ttl_minutes,
            "pause_idle_timeout_s": self._pause_idle_timeout,
            "wash_enabled": self._wash_enabled,

            "worker_is_leader": self._is_leader,
            "worker_active_count": len(self._active),
            "worker_inflight_creates": self._inflight_creates,

            "wash_success_count": self._wash_success_count,
            "wash_failure_count": self._wash_failure_count,
            "reclaim_success_count": self._reclaim_success_count,
            "reclaim_miss_count": self._reclaim_miss_count,
            "reservation_expiry_count": self._reservation_expiry_count,
            "cold_start_count": self._cold_start_count,

            "recent_errors": list(self._recent_errors),
        }

    # ──────────────────────────────────────────────────────────────────
    # Background tasks (leader-only)
    # ──────────────────────────────────────────────────────────────────

    async def start_background_tasks(self) -> None:
        """Start (or restart) all leader-only background loops.

        Safe to call repeatedly — the leader supervisor will re-invoke
        this when it re-acquires leadership after briefly losing the
        Redis lease.  Tasks already alive are left in place; only
        missing / dead tasks are respawned.
        """
        self._closing = False
        self._is_leader = True

        def _alive(t: asyncio.Task | None) -> bool:
            return t is not None and not t.done()

        if not _alive(self._replenish_task):
            self._replenish_task = asyncio.create_task(self._replenish_loop())
        if not _alive(self._cleanup_task):
            self._cleanup_task = asyncio.create_task(self._ttl_loop())
        if not _alive(self._orphan_task):
            self._orphan_task = asyncio.create_task(self._orphan_cleanup_loop())
        if not _alive(self._reservation_sweeper_task):
            self._reservation_sweeper_task = asyncio.create_task(
                self._reservation_sweeper_loop()
            )
        if not _alive(self._rebalancer_task):
            self._rebalancer_task = asyncio.create_task(self._rebalancer_loop())

    async def stop_background_tasks(self) -> None:
        """Cancel all leader-only background loops without shutting the
        provider down.  Called by the leader supervisor when this worker
        temporarily loses the Redis lease.  ``shutdown()`` is still used
        for full process teardown.
        """
        self._is_leader = False
        for task in (
            self._replenish_task,
            self._cleanup_task,
            self._orphan_task,
            self._reservation_sweeper_task,
            self._rebalancer_task,
        ):
            if task and not task.done():
                task.cancel()
        self._replenish_task = None
        self._cleanup_task = None
        self._orphan_task = None
        self._reservation_sweeper_task = None
        self._rebalancer_task = None

    async def _replenish_loop(self) -> None:
        """Keep hot tier at its autoscaling target by pulling from cold first.

        Cold-tier promotion is materially cheaper (no image pull) than a
        fresh create, so it's always preferred when a cold entry is
        available. Only when cold is empty do we create from scratch.
        """
        while not self._closing:
            try:
                hot_target = await self._hot_target()
                hot_current = await self._hot_len()
                deficit = hot_target - hot_current
                if deficit <= 0:
                    await asyncio.sleep(5)
                    continue

                cold_available = await self._cold_len()
                cold_to_promote = min(deficit, cold_available)
                create_needed = deficit - cold_to_promote

                if cold_to_promote > 0:
                    await self._promote_cold_to_hot_batch(cold_to_promote)

                if create_needed > 0:
                    concurrency = min(create_needed, self._parallel_create)
                    sem = asyncio.Semaphore(concurrency)

                    async def _one_create() -> None:
                        async with sem:
                            placeholder_id = f"pool-{uuid.uuid4().hex[:8]}"
                            try:
                                sandbox, container_ip = await self._create_sandbox_with_retry(
                                    placeholder_id
                                )
                                await self._push_to_hot(
                                    sandbox._cg_name, placeholder_id, container_ip
                                )
                                new_size = await self._hot_len()
                                logger.info(
                                    "Hot pool replenished %s (%d/%d)",
                                    placeholder_id, new_size, hot_target,
                                )
                            except Exception as inner:
                                logger.warning(
                                    "Replenish create %s failed: %s",
                                    placeholder_id, inner,
                                )
                                self._record_error(
                                    "replenish", inner, placeholder_id
                                )

                    tasks = [
                        asyncio.create_task(_one_create())
                        for _ in range(create_needed)
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)

                await asyncio.sleep(5)
            except Exception as exc:
                logger.warning("Replenish loop iteration error: %s", exc)
                self._record_error("replenish_loop", exc)
                await asyncio.sleep(10)

    async def _promote_cold_to_hot_batch(self, n: int) -> None:
        if n <= 0:
            return

        async def _one() -> None:
            placeholder_id = f"pool-{uuid.uuid4().hex[:8]}"
            sandbox = await self._promote_from_cold(placeholder_id)
            if sandbox is None:
                return
            try:
                await self._push_to_hot(
                    sandbox._cg_name, placeholder_id, self._ip_of(sandbox)
                )
            except Exception as exc:
                logger.warning("Push-to-hot after cold promotion failed: %s", exc)
                asyncio.create_task(self._delete_container_group(sandbox._cg_name))

        await asyncio.gather(*(asyncio.create_task(_one()) for _ in range(n)),
                             return_exceptions=True)

    async def _rebalancer_loop(self) -> None:
        """Keep cold tier at ``COLD_TIER_TARGET``.

        Two directions:

        * **Shrink hot, grow cold**: when hot_current > hot_target AND cold
          is under target, stop the excess hot entries and push them to
          cold. This is the cost-saving path after a demand spike subsides.
        * **Top up cold**: when cold is under target AND no shrinking
          opportunity, create a new container group and stop it
          immediately. This pre-warms capacity for the next spike cheaply.
        """
        if self._cold_target <= 0:
            logger.info("Cold tier disabled (COLD_TIER_TARGET=0)")
            return

        while not self._closing:
            try:
                await asyncio.sleep(self._rebalancer_interval)
                hot_target = await self._hot_target()
                hot_current = await self._hot_len()
                cold_current = await self._cold_len()

                hot_surplus = max(0, hot_current - hot_target)
                cold_deficit = max(0, self._cold_target - cold_current)

                if hot_surplus > 0 and cold_deficit > 0:
                    move = min(hot_surplus, cold_deficit)
                    await self._move_hot_to_cold(move)
                    continue

                if cold_deficit > 0:
                    concurrency = min(cold_deficit, self._parallel_create)
                    sem = asyncio.Semaphore(concurrency)

                    async def _one_cold_create() -> None:
                        async with sem:
                            await self._create_and_stop_for_cold()

                    tasks = [
                        asyncio.create_task(_one_cold_create())
                        for _ in range(cold_deficit)
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as exc:
                logger.warning("Rebalancer loop error: %s", exc)
                self._record_error("rebalancer", exc)

    async def _move_hot_to_cold(self, n: int) -> None:
        if n <= 0:
            return

        try:
            rc = await self._redis_client()
            moved = 0
            for _ in range(n):
                raw = await rc.lpop(_REDIS_HOT_POOL_KEY)
                if raw is None:
                    break
                entry = json.loads(raw)
                cg_name = entry["cg_name"]
                try:
                    await self._stop_container_group(cg_name)
                    await self._push_to_cold(cg_name, entry.get("ip", ""))
                    moved += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to stop %s for cold-tier move: %s",
                        cg_name, exc,
                    )
                    await rc.rpush(_REDIS_HOT_POOL_KEY, raw)
            if moved:
                logger.info("Rebalancer: moved %d container(s) hot → cold", moved)
        except Exception as exc:
            logger.warning("_move_hot_to_cold error: %s", exc)

    async def _create_and_stop_for_cold(self) -> None:
        """Create a fresh container group, wait for healthy, then stop it.

        A stopped entry in cold costs ~$0 but can start 2-3× faster than
        a fresh create. The small initial create cost is paid once at
        provisioning time, not at acquire time.
        """
        placeholder_id = f"cold-{uuid.uuid4().hex[:8]}"
        try:
            sandbox, container_ip = await self._create_sandbox_with_retry(
                placeholder_id
            )
            cg_name = sandbox._cg_name
            for attempt in range(6):
                if await sandbox.health_check():
                    break
                await asyncio.sleep(2 ** attempt)

            await self._stop_container_group(cg_name)
            await self._push_to_cold(cg_name, container_ip)
            logger.info("Cold tier topped up: %s", cg_name)
        except Exception as exc:
            logger.warning("Create-and-stop for cold failed: %s", exc)
            self._record_error("cold_create", exc, placeholder_id)

    async def _reservation_sweeper_loop(self) -> None:
        """Destroy reservations that exceeded their idle timeout.

        Redis TTL on ``sandbox:reserved:*`` keys already auto-expires the
        lookup, but the actual container group lives in Azure. This loop
        scans the ZSET index by expiry time and destroys anything past due.
        """
        while not self._closing:
            try:
                await asyncio.sleep(30)
                rc = await self._redis_client()
                now = time.time()

                expired = await rc.zrangebyscore(
                    _REDIS_RESERVATION_INDEX, "-inf", now, start=0, num=50,
                )
                if not expired:
                    continue

                for item in expired:
                    sid = item.decode() if isinstance(item, bytes) else str(item)
                    key = _REDIS_RESERVATION_PREFIX + sid
                    raw = await rc.get(key)
                    await rc.delete(key)
                    await rc.zrem(_REDIS_RESERVATION_INDEX, sid)
                    if raw is not None:
                        try:
                            entry = json.loads(raw)
                            cg_name = entry["cg_name"]
                            logger.info(
                                "Reservation expired for %s (cg %s); destroying",
                                sid, cg_name,
                            )
                            asyncio.create_task(
                                self._delete_container_group(cg_name)
                            )
                            self._reservation_expiry_count += 1
                        except Exception as exc:
                            logger.warning(
                                "Failed to destroy expired reservation %s: %s",
                                sid, exc,
                            )
                    await self._decr_active(1)
            except Exception as exc:
                logger.warning("Reservation sweeper error: %s", exc)
                self._record_error("reservation_sweep", exc)

    async def _create_sandbox_with_retry(
        self, sandbox_id: str
    ) -> tuple[AciSandbox, str]:
        attempts = self._create_max_retries + 1
        last_exc: BaseException | None = None
        self._inflight_creates += 1
        try:
            for attempt in range(1, attempts + 1):
                try:
                    return await self._create_sandbox(sandbox_id)
                except Exception as exc:
                    last_exc = exc
                    self._record_error("create", exc, sandbox_id)
                    if attempt >= attempts or not _is_transient_azure_error(exc):
                        logger.error(
                            "ACI create failed for %s (attempt %d/%d, non-retryable): %s",
                            sandbox_id, attempt, attempts, exc,
                        )
                        raise
                    backoff = self._create_retry_base * (2 ** (attempt - 1))
                    jitter = random.uniform(0, backoff * 0.25)
                    total = backoff + jitter
                    logger.warning(
                        "ACI create transient failure for %s (attempt %d/%d): %s "
                        "— retrying in %.1fs",
                        sandbox_id, attempt, attempts, exc, total,
                    )
                    await asyncio.sleep(total)
        finally:
            self._inflight_creates = max(0, self._inflight_creates - 1)

        assert last_exc is not None
        raise last_exc  # noqa: RSE102

    async def _ttl_loop(self) -> None:
        ttl_seconds = self._ttl_minutes * 60
        while not self._closing:
            await asyncio.sleep(60)
            try:
                rc = await self._redis_client()
                for key in (_REDIS_HOT_POOL_KEY, _REDIS_LEGACY_POOL_KEY):
                    entries = await rc.lrange(key, 0, -1)
                    if not entries:
                        continue

                    now = time.time()
                    keep: list[bytes | str] = []
                    evicted = 0
                    for raw in entries:
                        entry = json.loads(raw)
                        if now - entry["created_at"] > ttl_seconds:
                            asyncio.create_task(
                                self._delete_container_group(entry["cg_name"])
                            )
                            evicted += 1
                        else:
                            keep.append(raw)

                    if evicted:
                        pipe = rc.pipeline()
                        await pipe.delete(key)
                        if keep:
                            await pipe.rpush(key, *keep)
                        await pipe.execute()
                        logger.info(
                            "TTL evicted %d idle container(s) from %s",
                            evicted, key,
                        )
            except Exception as exc:
                logger.warning("TTL loop error: %s", exc)

    async def _orphan_cleanup_loop(self) -> None:
        interval = 300
        max_age_seconds = self._ttl_minutes * 60 * 2
        while not self._closing:
            await asyncio.sleep(interval)
            try:
                loop = asyncio.get_running_loop()
                client = self._get_client()

                groups = await loop.run_in_executor(
                    None,
                    lambda: list(client.container_groups.list_by_resource_group(self._rg)),
                )

                rc = await self._redis_client()
                pooled_cg_names = set()
                for key in (
                    _REDIS_HOT_POOL_KEY,
                    _REDIS_COLD_POOL_KEY,
                    _REDIS_LEGACY_POOL_KEY,
                ):
                    for raw in await rc.lrange(key, 0, -1):
                        try:
                            pooled_cg_names.add(json.loads(raw)["cg_name"])
                        except Exception:
                            pass

                reserved_cg_names = set()
                for item in await rc.zrange(_REDIS_RESERVATION_INDEX, 0, -1):
                    sid = item.decode() if isinstance(item, bytes) else str(item)
                    raw = await rc.get(_REDIS_RESERVATION_PREFIX + sid)
                    if raw is not None:
                        try:
                            reserved_cg_names.add(json.loads(raw)["cg_name"])
                        except Exception:
                            pass

                active_cg_names = {s._cg_name for s in self._active.values()}
                now = time.time()
                orphans_cleaned = 0

                for group in groups:
                    tags = group.tags or {}
                    if tags.get(_LABEL_KEY) != _LABEL_VALUE:
                        continue
                    if (
                        group.name in pooled_cg_names
                        or group.name in active_cg_names
                        or group.name in reserved_cg_names
                    ):
                        continue

                    group_age = None
                    try:
                        if group.instance_view and group.instance_view.events:
                            first_event = group.instance_view.events[0]
                            event_time = first_event.first_timestamp
                            if event_time:
                                group_age = now - event_time.timestamp()
                    except Exception:
                        pass

                    if group_age is None:
                        sid = tags.get("sandbox-id", "")
                        if sid.startswith("pool-") or sid.startswith("cold-"):
                            group_age = max_age_seconds + 1
                        else:
                            continue

                    if group_age > max_age_seconds:
                        logger.info(
                            "Orphan cleanup: deleting %s (age %.0fs, max %ds)",
                            group.name, group_age, max_age_seconds,
                        )
                        asyncio.create_task(
                            self._delete_container_group(group.name)
                        )
                        orphans_cleaned += 1

                if orphans_cleaned:
                    logger.info(
                        "Orphan cleanup complete: deleted %d container group(s)",
                        orphans_cleaned,
                    )
            except Exception as exc:
                logger.warning("Orphan cleanup loop error: %s", exc)

    # ──────────────────────────────────────────────────────────────────
    # Azure management-plane helpers
    # ──────────────────────────────────────────────────────────────────

    async def _delete_container_group(self, cg_name: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            client = self._get_client()
            await loop.run_in_executor(
                None,
                lambda: client.container_groups.begin_delete(
                    self._rg, cg_name
                ).result(),
            )
            logger.info("Deleted container group %s", cg_name)
        except Exception as exc:
            logger.warning("Failed to delete container group %s: %s", cg_name, exc)

    async def _stop_container_group(self, cg_name: str) -> None:
        loop = asyncio.get_running_loop()
        client = self._get_client()
        try:
            await loop.run_in_executor(
                None,
                lambda: client.container_groups.stop(self._rg, cg_name),
            )
            logger.info("Stopped container group %s", cg_name)
        except Exception as exc:
            logger.warning("Failed to stop container group %s: %s", cg_name, exc)
            raise

    async def _start_container_group(self, cg_name: str) -> None:
        loop = asyncio.get_running_loop()
        client = self._get_client()
        try:
            await loop.run_in_executor(
                None,
                lambda: client.container_groups.begin_start(
                    self._rg, cg_name
                ).result(),
            )
            logger.info("Started container group %s", cg_name)
        except Exception as exc:
            logger.warning("Failed to start container group %s: %s", cg_name, exc)
            raise

    async def _read_container_ip(self, cg_name: str) -> str | None:
        loop = asyncio.get_running_loop()
        client = self._get_client()
        try:
            group = await loop.run_in_executor(
                None,
                lambda: client.container_groups.get(self._rg, cg_name),
            )
            ip = group.ip_address.ip if group.ip_address else None
            return ip
        except Exception as exc:
            logger.warning("Read container IP for %s failed: %s", cg_name, exc)
            return None

    @staticmethod
    def _ip_of(sandbox: AciSandbox) -> str:
        """Best-effort IP extraction from an AciSandbox wrapper."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(sandbox._base_url)
            return parsed.hostname or ""
        except Exception:
            return ""

    # ──────────────────────────────────────────────────────────────────
    # ACI container group creation
    # ──────────────────────────────────────────────────────────────────

    async def _create_sandbox(self, sandbox_id: str) -> tuple[AciSandbox, str]:
        loop = asyncio.get_running_loop()
        client = self._get_client()
        cg_name = f"sandbox-{sandbox_id}"

        proxy_env = _resolve_proxy_env()

        def _create():
            from azure.mgmt.containerinstance.models import (
                Container,
                ContainerGroup,
                ContainerGroupIdentity,
                ContainerGroupSubnetId,
                ContainerPort,
                EnvironmentVariable,
                ImageRegistryCredential,
                IpAddress,
                OperatingSystemTypes,
                Port,
                ResourceIdentityType,
                ResourceLimits,
                ResourceRequirements,
                ResourceRequests,
            )

            env_vars = [
                EnvironmentVariable(name=k, value=v) for k, v in proxy_env.items()
            ]

            container = Container(
                name="sandbox",
                image=self._image,
                resources=ResourceRequirements(
                    requests=ResourceRequests(
                        cpu=self._cpu, memory_in_gb=self._memory_gb
                    ),
                    limits=ResourceLimits(
                        cpu=self._cpu, memory_in_gb=self._memory_gb
                    ),
                ),
                environment_variables=env_vars,
                ports=[ContainerPort(port=443, protocol="TCP")],
            )

            subnet_ids = None
            ip_address = None
            if self._subnet_id:
                subnet_ids = [ContainerGroupSubnetId(id=self._subnet_id)]
                ip_address = IpAddress(
                    ports=[Port(port=443, protocol="TCP")],
                    type="Private",
                )

            registry_creds = None
            identity = None
            if self._registry_server and self._registry_identity_id:
                registry_creds = [ImageRegistryCredential(
                    server=self._registry_server,
                    identity=self._registry_identity_id,
                )]
                identity = ContainerGroupIdentity(
                    type=ResourceIdentityType.user_assigned,
                    user_assigned_identities={self._registry_identity_id: {}},
                )
            elif (
                self._registry_server
                and self._registry_username
                and self._registry_password
            ):
                registry_creds = [ImageRegistryCredential(
                    server=self._registry_server,
                    username=self._registry_username,
                    password=self._registry_password,
                )]

            from config.keyvault import cfg as _cfg
            _location = getattr(_cfg, "AZURE_LOCATION", None) or "uaenorth"

            group = ContainerGroup(
                location=_location,
                containers=[container],
                os_type=OperatingSystemTypes.linux,
                restart_policy="Never",
                subnet_ids=subnet_ids,
                ip_address=ip_address,
                image_registry_credentials=registry_creds,
                identity=identity,
                tags={_LABEL_KEY: _LABEL_VALUE, "sandbox-id": sandbox_id},
            )

            poller = client.container_groups.begin_create_or_update(
                self._rg, cg_name, group,
            )
            return poller.result()

        result = await loop.run_in_executor(None, _create)
        container_ip = result.ip_address.ip if result.ip_address else ""
        logger.info("Created ACI container group %s (ip %s)", cg_name, container_ip)

        sandbox = AciSandbox(
            sandbox_id,
            resource_group=self._rg,
            container_group_name=cg_name,
            container_name="sandbox",
            aci_client=client,
            container_ip=container_ip,
        )
        return sandbox, container_ip


def _resolve_proxy_env() -> dict[str, str]:
    """Build environment variables for the GenAI proxy inside ACI."""
    env: dict[str, str] = {}
    try:
        from config.keyvault import cfg
        url = getattr(cfg, "GENAI_PROXY_URL", None)
        key = getattr(cfg, "GENAI_PROXY_API_KEY", None)
        if url:
            env["AGENT_STUDIO_LLM_URL"] = url
        if key:
            env["AGENT_STUDIO_LLM_KEY"] = key
    except Exception:
        pass
    return env
