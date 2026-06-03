"""
Health check routes for Kubernetes and monitoring.

Provides three levels of health checks:
1. /health/live - Fast liveness probe (< 100ms)
2. /health/ready - Readiness probe with dependency checks (< 5s)
3. /health (legacy) - Basic health check for backwards compatibility
"""
from fastapi import APIRouter, Depends, Response, status
from typing import Dict, Any
import logging

from services.health_service import HealthService
from core.dependencies import get_current_user
from db.models import User
from db.pgsql import get_instance_info

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["Health Checks"],
    responses={
        200: {"description": "Service is healthy"},
        503: {"description": "Service is not ready"}
    }
)


@router.get("/live")
async def liveness_probe() -> Dict[str, Any]:
    """
    Kubernetes liveness probe.
    
    Fast check (< 100ms) to verify the process is alive and responding.
    Does NOT check dependencies - only verifies the app can handle requests.
    
    K8s will restart the pod if this fails repeatedly.
    
    Returns:
        200: Process is alive
    """
    return await HealthService.liveness_check()


@router.get("/ready")
async def readiness_probe(response: Response) -> Dict[str, Any]:
    """
    Kubernetes readiness probe.
    
    Comprehensive check (< 5s) of all critical dependencies:
    - PostgreSQL database (primary)
    - Redis (optional)
    - Azure Storage (optional)
    
    K8s will remove pod from load balancer if this fails.
    Pod will be re-added when it becomes ready again.
    
    Returns:
        200: Service is ready to accept traffic
        503: Service is not ready (dependencies unhealthy)
    """
    health_status = await HealthService.readiness_check()
    
    # Return 503 if not ready
    if health_status.get("status") != "ready":
        logger.warning(
            "Readiness check failed: %s",
            health_status.get("checks", {})
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    
    return health_status


@router.get("")
@router.get("/")
async def basic_health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint (legacy).
    
    Provides instance information and basic status.
    For backwards compatibility with existing monitoring.
    
    Use /health/live or /health/ready for K8s probes.
    
    Returns:
        Basic health status with instance info
    """
    from datetime import datetime
    
    instance_info = get_instance_info()
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "agent-builder-api",
        "database": "cluster-ready",
        "instance": instance_info,
        "cluster_mode": "multi-instance-ready"
    }


@router.get("/sandbox")
async def sandbox_health(response: Response) -> Dict[str, Any]:
    """Report sandbox provider health and warm-pool status."""
    from workflow.sandbox.sandbox_provider import get_sandbox_provider, _default_provider
    from config.keyvault import cfg

    provider_type = (getattr(cfg, "SANDBOX_PROVIDER", None) or "docker").lower()
    result: Dict[str, Any] = {"provider": provider_type, "healthy": False}

    try:
        if provider_type == "aci" and _default_provider is not None:
            provider = _default_provider
            pool_size = await provider._pool_len()
            rc = await provider._redis_client()
            leader_active = bool(await rc.exists("sandbox:pool-leader"))
            result.update({
                "healthy": True,
                "pool_size": pool_size,
                "pool_target": provider._pool_size,
                "active_count": len(provider._active),
                "leader_active": leader_active,
            })
        else:
            import docker  # type: ignore[import-untyped]
            client = docker.from_env()
            client.ping()
            running = client.containers.list(
                filters={"label": "managed-by=agent-studio-sandbox"}
            )
            result.update({
                "healthy": True,
                "running_containers": len(running),
            })
    except Exception as exc:
        logger.warning("Sandbox health check failed: %s", exc)
        result["error"] = str(exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return result


@router.get("/detailed")
async def detailed_health_check(
    response: Response,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Detailed health check for ops/debugging.
    
    Includes:
    - All readiness checks
    - System resource usage (CPU, memory, disk)
    - Instance information
    - Component latencies
    
    Useful for:
    - Debugging health issues
    - Performance monitoring
    - Capacity planning
    
    Returns:
        Comprehensive health status
    """
    health_status = await HealthService.detailed_check()
    
    # Return 503 if not ready
    if health_status.get("status") != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    
    return health_status

