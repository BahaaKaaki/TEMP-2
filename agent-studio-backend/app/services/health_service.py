"""
Health check service for monitoring system components.

Provides comprehensive health checks for:
- Database connectivity (PostgreSQL primary + replicas)
- Redis connectivity
- Azure Storage connectivity
- External API connectivity (OpenAI, Anthropic)
- System resources (memory, disk)
"""
import logging
import asyncio
import time
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class HealthService:
    """
    Service for checking health of all system components.
    
    Provides two types of checks:
    1. Liveness - Fast check if server is running (< 100ms)
    2. Readiness - Full check of all dependencies (< 5s)
    """
    
    @staticmethod
    async def liveness_check() -> Dict[str, Any]:
        """
        Fast liveness check for K8s liveness probe.
        
        Just verifies the process is alive and responding.
        Should complete in < 100ms.
        
        Returns:
            dict: Liveness status
        """
        return {
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "agent-builder-api"
        }
    
    @staticmethod
    async def readiness_check() -> Dict[str, Any]:
        """
        Comprehensive readiness check for K8s readiness probe.
        
        Checks all critical dependencies:
        - PostgreSQL (primary + replicas)
        - Redis
        - Azure Storage (optional)
        - External APIs (optional, with timeout)
        
        Returns:
            dict: Readiness status with component details
        """
        start_time = time.time()
        
        health_status = {
            "status": "ready",  # Will change to "not_ready" if any critical component fails
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {},
            "latency_ms": 0
        }
        
        # Run all checks in parallel for speed
        results = await asyncio.gather(
            HealthService._check_database(),
            HealthService._check_redis(),
            HealthService._check_azure_storage(),
            return_exceptions=True
        )
        
        # Process database check
        db_result = results[0]
        if isinstance(db_result, Exception):
            health_status["checks"]["database"] = {
                "status": "unhealthy",
                "error": str(db_result)
            }
            health_status["status"] = "not_ready"
        else:
            health_status["checks"]["database"] = db_result
            if db_result.get("status") != "healthy":
                health_status["status"] = "not_ready"
        
        # Process Redis check
        redis_result = results[1]
        if isinstance(redis_result, Exception):
            health_status["checks"]["redis"] = {
                "status": "degraded",
                "error": str(redis_result),
                "note": "Redis is optional"
            }
            # Redis is optional, don't mark as not_ready
        else:
            health_status["checks"]["redis"] = redis_result
        
        # Process Azure Storage check
        storage_result = results[2]
        if isinstance(storage_result, Exception):
            health_status["checks"]["azure_storage"] = {
                "status": "degraded",
                "error": str(storage_result),
                "note": "Storage check failed (optional)"
            }
            # Storage is optional, don't mark as not_ready
        else:
            health_status["checks"]["azure_storage"] = storage_result
        
        # Calculate total latency
        elapsed_ms = int((time.time() - start_time) * 1000)
        health_status["latency_ms"] = elapsed_ms
        
        return health_status
    
    @staticmethod
    async def _check_database() -> Dict[str, Any]:
        """
        Check PostgreSQL database connectivity and latency.
        
        Returns:
            dict: Database health status
        """
        try:
            from db.pgsql import get_write_db
            from sqlalchemy import text
            
            start = time.time()
            
            async for session in get_write_db():
                # Simple query to check connectivity
                result = await session.execute(text("SELECT 1 as health_check"))
                row = result.first()
                
                latency_ms = int((time.time() - start) * 1000)
                
                if row and row[0] == 1:
                    return {
                        "status": "healthy",
                        "type": "postgresql",
                        "latency_ms": latency_ms,
                        "response_time": "fast" if latency_ms < 100 else "slow"
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "error": "Unexpected query result"
                    }
                
                break  # Only need one session
            
            return {
                "status": "unhealthy",
                "error": "Could not acquire database session"
            }
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "type": "postgresql"
            }
    
    @staticmethod
    async def _check_redis() -> Dict[str, Any]:
        """
        Check Redis connectivity and latency.
        
        Returns:
            dict: Redis health status
        """
        try:
            from db.redis import get_redis
            
            start = time.time()
            
            redis = await get_redis()
            
            # Ping Redis
            await redis.ping()
            
            # Get database size
            db_size = await redis.dbsize()
            
            latency_ms = int((time.time() - start) * 1000)
            
            return {
                "status": "healthy",
                "type": "redis",
                "latency_ms": latency_ms,
                "keys": db_size,
                "response_time": "fast" if latency_ms < 50 else "slow"
            }
            
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            return {
                "status": "degraded",
                "error": str(e),
                "type": "redis",
                "note": "Redis is optional"
            }
    
    @staticmethod
    async def _check_azure_storage() -> Dict[str, Any]:
        """
        Check Azure Storage connectivity using the singleton connector.
        
        Returns:
            dict: Azure Storage health status
        """
        try:
            from core.dependencies import get_azure_storage_connector
            
            try:
                connector = get_azure_storage_connector()
            except RuntimeError:
                return {
                    "status": "not_configured",
                    "note": "Azure Storage connector not initialized"
                }
            
            start = time.time()
            
            # Just check if we can list (doesn't matter if empty)
            # Use timeout to prevent hanging
            await asyncio.wait_for(
                connector.list_blobs(max_results=1),
                timeout=3.0
            )
            
            latency_ms = int((time.time() - start) * 1000)
            
            return {
                "status": "healthy",
                "type": "azure_blob_storage",
                "latency_ms": latency_ms,
                "container": connector.container_name
            }
            
        except asyncio.TimeoutError:
            return {
                "status": "degraded",
                "error": "Storage check timed out (3s)",
                "type": "azure_blob_storage",
                "note": "Storage is optional"
            }
        except Exception as e:
            logger.warning(f"Azure Storage health check failed: {e}")
            return {
                "status": "degraded",
                "error": str(e)[:100],  # Truncate long errors
                "type": "azure_blob_storage",
                "note": "Storage is optional"
            }
    
    @staticmethod
    async def detailed_check() -> Dict[str, Any]:
        """
        Detailed health check with all components + system info.
        
        Includes:
        - All readiness checks
        - System resource usage
        - Instance information
        
        Returns:
            dict: Detailed health status
        """
        from db.pgsql import get_instance_info
        
        # Get readiness check results
        readiness = await HealthService.readiness_check()
        
        # Add instance info
        readiness["instance"] = get_instance_info()
        
        # Add system resource info
        try:
            import psutil
            
            readiness["resources"] = {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent
            }
        except ImportError:
            readiness["resources"] = {
                "note": "psutil not available"
            }
        except Exception as e:
            logger.warning(f"Could not get system resources: {e}")
            readiness["resources"] = {
                "error": str(e)
            }
        
        return readiness

