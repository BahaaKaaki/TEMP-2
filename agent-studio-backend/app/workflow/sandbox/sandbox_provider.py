"""
Abstract sandbox provider with acquire / get / release lifecycle.

The active provider is resolved from application config at startup and
cached as a module-level singleton.
"""

from abc import ABC, abstractmethod
from typing import Any
import logging

from .sandbox import Sandbox

logger = logging.getLogger(__name__)

_default_provider: "SandboxProvider | None" = None


class SandboxProvider(ABC):
    """Factory that manages sandbox lifecycle."""

    @abstractmethod
    async def acquire(self, execution_id: str) -> str:
        """Provision a new sandbox and return its id."""
        ...

    @abstractmethod
    async def get(self, sandbox_id: str) -> Sandbox | None:
        """Retrieve an existing sandbox by id."""
        ...

    @abstractmethod
    async def release(self, sandbox_id: str) -> None:
        """Finalise a sandbox — provider chooses between wash-and-return-to-pool
        (if supported and wash succeeds) or full destroy.

        Call this on workflow completion / error, NOT when a code-pause has
        preserved meaningful in-memory state the resume flow wants to reuse.
        Use ``reserve`` for the pause case.
        """
        ...

    async def reserve(self, sandbox_id: str, ttl_seconds: int) -> None:
        """Hold a sandbox alive across a pause so the matching resume can
        reclaim it instantly (no new container, no checkpoint inject,
        no file re-inject).

        The sandbox keeps running; the provider is responsible for
        automatically releasing it if ``ttl_seconds`` elapses with no
        ``reclaim`` call — that covers users who walk away from a pause
        and avoids a hostage container.

        Default implementation falls back to ``release`` — providers that
        don't support holding just treat this as a normal completion.
        Checkpoint-based slow-path resume still works in that case.
        """
        await self.release(sandbox_id)

    async def reclaim(self, sandbox_id: str) -> Sandbox | None:
        """Try to re-take a previously reserved sandbox.

        Returns the ``Sandbox`` object if the reservation is still live AND
        the container is still healthy.  Returns ``None`` if the
        reservation expired, the container was destroyed, or the provider
        doesn't support reservations — the caller must then fall back to
        ``acquire`` + checkpoint injection.

        Default implementation always returns None (forces slow-path
        resume).
        """
        return None

    async def shutdown(self) -> None:
        """Release every sandbox owned by this provider (app shutdown)."""
        pass

    async def pool_status(self) -> dict[str, Any]:
        """Return a snapshot of the provider's pool state.

        Providers without a warm pool (e.g. Docker) can return a minimal
        object so the ``/api/sandbox/pool-status`` endpoint behaves
        uniformly regardless of the deployment target.
        """
        return {
            "provider": type(self).__name__,
            "hot_target": 0,
            "hot_current": 0,
            "cold_target": 0,
            "cold_current": 0,
            "reserved_current": 0,
            "active_total": 0,
            "worker_active_count": 0,
            "worker_inflight_creates": 0,
            "recent_errors": [],
        }


def get_sandbox_provider() -> SandboxProvider:
    """Return the cached provider singleton, creating it on first call.

    Reads ``SANDBOX_PROVIDER`` from settings to decide between Docker
    (local dev) and ACI (production on Azure Container Apps).
    """
    global _default_provider
    if _default_provider is not None:
        return _default_provider

    from config.keyvault import cfg
    provider_type = (getattr(cfg, "SANDBOX_PROVIDER", None) or "docker").lower()

    if provider_type == "aci":
        from .aci_sandbox_provider import AciSandboxProvider

        _default_provider = AciSandboxProvider()
        logger.info("Initialised AciSandboxProvider (Azure Container Instances)")
    else:
        from .docker_sandbox_provider import DockerSandboxProvider

        _default_provider = DockerSandboxProvider()
        logger.info("Initialised DockerSandboxProvider (local Docker)")

    return _default_provider


def set_sandbox_provider(provider: SandboxProvider) -> None:
    """Inject a custom provider (useful for tests)."""
    global _default_provider
    _default_provider = provider


async def shutdown_sandbox_provider() -> None:
    """Cleanly shut down the current provider."""
    global _default_provider
    if _default_provider is not None:
        await _default_provider.shutdown()
        _default_provider = None
