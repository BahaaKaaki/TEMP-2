"""
Agent Builder API - Main application entry point.
FastAPI server with PostgreSQL and Redis integration.
"""
# Populate the central secrets cache BEFORE any other app imports
# so that get_config() returns correct values for import-time reads.
from config.keyvault import load_secrets
load_secrets()

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
import logging
from logging.config import dictConfig
import re
from routers import workflow_entity, workflow_execution, marketplace_approval, workflow_version_routes
from routers.shared_tool_router import public_router as shared_tool_public_router, admin_router as shared_tool_admin_router
from app.admin.routers import admin_analytics, admin_llm, admin_sharing, admin_users
from routers import (
    session_routes,
    chat_routes,
    citation_routes,
    deliverable_routes,
    openui_routes,
    file_routes,
    document_routes,
    knowledge_base_routes,
    health_routes,
    models,
    auth_router,
    powerpoint_routes,
    feedback_routes,
    template_routes,
    code_executor_routes,
    code_executor_kb_routes,
    sse_routes,
    sharing_router,
    project_routes,
)
import uvicorn
import platform
import sys
import multiprocessing
import os
import signal
import asyncio
from datetime import datetime
from config.settings import settings, get_max_request_size_bytes
from core.dependencies import get_current_user
from utils.rate_limit import limiter, rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Configure logging
_console_level = settings.LOG_LEVEL.upper()

log_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.ColourizedFormatter",
            "fmt": "%(levelprefix)s %(asctime)s - %(name)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": True,
        },
        "detailed": {
            "()": "uvicorn.logging.ColourizedFormatter",
            "fmt": "%(levelprefix)s %(asctime)s - %(name)s - [%(filename)s:%(lineno)d] - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": True,
        },
        "file": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": _console_level,
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": _console_level,
            "formatter": "file",
            "filename": f"logs/agent_builder_{datetime.now().strftime('%Y%m%d')}.log",
            "maxBytes": settings.LOG_MAX_BYTES,
            "backupCount": settings.LOG_BACKUP_COUNT,
            "encoding": "utf8",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": "file",
            "filename": f"logs/agent_builder_error_{datetime.now().strftime('%Y%m%d')}.log",
            "maxBytes": settings.LOG_MAX_BYTES,
            "backupCount": settings.LOG_BACKUP_COUNT,
            "encoding": "utf8",
        },
        "console_errors": {
            "class": "logging.StreamHandler",
            "level": "ERROR",
            "formatter": "detailed",
            "stream": "ext://sys.stderr",
        }
    },
    "loggers": {
        "": {
            "handlers": ["console", "file", "error_file", "console_errors"],
            "level": _console_level,
        },
        "uvicorn": {
            "handlers": ["console", "file"],
            "level": _console_level,
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["error_file", "console_errors"],
            "level": "ERROR",
            "propagate": False,
        },
        "database": {
            "handlers": ["console", "file", "error_file", "console_errors"],
            "level": _console_level,
            "propagate": False,
        },
        # Silence noisy per-request RLS logging
        "db.rls": {"level": "WARNING"},
        # Silence noisy third-party libraries — only WARNING+ reaches handlers
        "pdfminer": {"level": "WARNING"},
        "unstructured": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
        "openai": {"level": "WARNING"},
        "langchain": {"level": "WARNING"},
        "langchain_core": {"level": "WARNING"},
        "langchain_openai": {"level": "WARNING"},
        "langchain_community": {"level": "WARNING"},
        "langgraph": {"level": "WARNING"},
        "sqlalchemy": {"level": "WARNING"},
        "asyncpg": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
        "asyncio": {"level": "WARNING"},
        "msal": {"level": "WARNING"},
        "azure": {"level": "WARNING"},
        "google": {"level": "WARNING"},
        "charset_normalizer": {"level": "WARNING"},
        "PIL": {"level": "WARNING"},
        "nltk": {"level": "WARNING"},
        "langfuse": {"level": "WARNING"},
    },
}

# Apply logging configuration
dictConfig(log_config)

# Create logger for this file
logger = logging.getLogger(__name__)

# Suppress repetitive debug/access logs for high-frequency chat polling endpoints
_QUIET_POLL_PATH_RE = re.compile(
    r"^/api/chat/sessions/[^/]+$"
    r"|^/api/chat/sessions/[^/]+/deliverables$"
)
_QUIET_POLL_ACCESS_RE = re.compile(
    r"/api/chat/sessions/[^/\s]+ HTTP/"
    r"|/api/chat/sessions/[^/]+/deliverables HTTP/"
)


def _is_quiet_poll_path(path: str) -> bool:
    return bool(_QUIET_POLL_PATH_RE.match(path))


class _QuietPollAccessFilter(logging.Filter):
    """Drop uvicorn.access records for known polling endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not bool(_QUIET_POLL_ACCESS_RE.search(record.getMessage()))


logging.getLogger("uvicorn.access").addFilter(_QuietPollAccessFilter())

_is_prod = settings.ENVIRONMENT.lower() == "production"
app = FastAPI(
    title="Agent Builder API",
    description="API for managing automation workflows and agents",
    version="1.0.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

# Graceful shutdown state
shutdown_event = asyncio.Event()
is_shutting_down = False

# Add rate limiter state to app
app.state.limiter = limiter

# Add rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

@app.middleware("http")
async def request_validation_middleware(request: Request, call_next):
    """
    Validate request size and log requests/responses.
    
    Prevents memory exhaustion from large payloads by checking Content-Length
    before reading the body. Also logs all incoming requests.
    
    Also rejects new requests during graceful shutdown.
    Also clears user context after each request to prevent context leakage.
    """
    # Reject new requests during shutdown
    if is_shutting_down:
        logger.warning(
            "Rejecting request during shutdown: %s %s",
            request.method,
            request.url.path
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Server is shutting down. Please retry in a few moments.",
                "error_code": "SERVICE_UNAVAILABLE"
            },
            headers={"Retry-After": "10"}
        )
    
    # Check request size BEFORE reading body
    # File upload endpoints use MAX_FILE_SIZE_MB (50MB); all others use MAX_REQUEST_SIZE_MB (10MB)
    content_length = request.headers.get("content-length")
    if content_length:
        content_length = int(content_length)
        
        is_file_upload = (
            request.method == "POST"
            and any(
                request.url.path.startswith(prefix)
                for prefix in (
                    "/api/chat/sessions/",
                    "/api/documents/knowledge-bases/",
                    "/api/templates/upload",
                    "/api/workflows/",
                )
            )
            and "multipart/form-data" in (request.headers.get("content-type") or "")
        )
        
        if is_file_upload:
            from config.settings import get_max_file_size_bytes
            max_size = get_max_file_size_bytes()
            max_mb = settings.MAX_FILE_SIZE_MB
        else:
            max_size = get_max_request_size_bytes()
            max_mb = settings.MAX_REQUEST_SIZE_MB
        
        if content_length > max_size:
            size_mb = content_length / (1024 * 1024)
            logger.warning(
                "Request too large: %s %s - Size: %.2f MB (max: %d MB) - IP: %s",
                request.method,
                request.url.path,
                size_mb,
                max_mb,
                request.client.host if request.client else 'unknown'
            )
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Request too large ({size_mb:.2f}MB). Maximum allowed: {max_mb}MB",
                    "error_code": "REQUEST_TOO_LARGE",
                    "max_size_mb": max_mb
                }
            )
    
    # Log incoming request (skip noisy polling endpoints)
    _quiet = _is_quiet_poll_path(request.url.path)
    if not _quiet:
        logger.debug("Incoming %s request to %s", request.method, request.url.path)
    
    # Process request
    response = await call_next(request)
    
    # Clear user context after request to prevent leakage across requests
    from core.request_context import (
        clear_current_user_email,
        clear_current_user_id,
        clear_current_user_name,
    )
    clear_current_user_id()
    clear_current_user_name()
    clear_current_user_email()
    
    # Log 403 Forbidden responses at the middleware level
    if response.status_code == 403:
        logger.warning(
            "403 Forbidden response: %s %s - IP: %s, User-Agent: %s",
            request.method,
            request.url.path,
            request.client.host if request.client else 'unknown',
            request.headers.get('user-agent', 'unknown')
        )
    
    # Log response (skip noisy polling endpoints)
    if not _quiet:
        logger.debug(
            "Finished %s request to %s with status %s",
            request.method,
            request.url.path,
            response.status_code
        )
    
    return response

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
# Health checks (no prefix - mounted at /health/*)
app.include_router(health_routes.router)

# Authentication router
app.include_router(auth_router.router)

# Models configuration (dynamic LLM provider/model discovery)
app.include_router(models.router)

# Public (unauthenticated) workflow-icon serving — must be registered
# before the authenticated workflow router so it isn't shadowed.
@app.get("/api/workflows/{workflow_id}/icon", tags=["Workflows"])
async def get_workflow_icon(workflow_id: str):
    """Serve the workflow icon image (no auth required for <img> tags)."""
    from core.dependencies import get_azure_storage_connector
    from fastapi import HTTPException

    storage = get_azure_storage_connector()
    prefix = f"workflow-icons/{workflow_id}."
    blobs = await storage.list_blobs(prefix=prefix, max_results=1)
    if not blobs:
        raise HTTPException(status_code=404, detail="No icon found for this workflow")

    blob_meta = blobs[0]
    data = await storage.download_blob(blob_meta.name)
    content_type = blob_meta.content_type or "image/png"

    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )

# Workflow routers
app.include_router(workflow_entity.router)
app.include_router(workflow_execution.router)
app.include_router(marketplace_approval.router)
app.include_router(admin_analytics.router)
app.include_router(admin_llm.router)
app.include_router(admin_sharing.router)
app.include_router(admin_users.router)
app.include_router(workflow_version_routes.router)

# AD-group / per-user sharing for workflows + knowledge bases
app.include_router(sharing_router.router)

# Shared external tools (storefront + admin CRUD)
app.include_router(shared_tool_public_router)
app.include_router(shared_tool_admin_router)

# Project management (session grouping)
app.include_router(project_routes.router)

# Chat routers (clean architecture with service layer)
app.include_router(session_routes.router)
app.include_router(chat_routes.router)
app.include_router(citation_routes.router)
app.include_router(deliverable_routes.router)
app.include_router(openui_routes.router)
app.include_router(file_routes.router)
app.include_router(document_routes.router)
app.include_router(knowledge_base_routes.router)

# PowerPoint generation
app.include_router(powerpoint_routes.router)

# Template engine (generic PPTX template upload / fill)
app.include_router(template_routes.router)

# Feedback routes
app.include_router(feedback_routes.router)

# Code executor utilities (validation)
app.include_router(code_executor_routes.router)

# Code executor Knowledge Base callback endpoints (sandbox -> host)
app.include_router(code_executor_kb_routes.router)

# SSE streaming for real-time execution output
app.include_router(sse_routes.router)

_SANDBOX_LEADER_KEY = "sandbox:pool-leader"
_SANDBOX_LEADER_TTL = 300           # seconds
_SANDBOX_LEADER_RENEW_EVERY = 60    # seconds (renew well before TTL)
_SANDBOX_LEADER_RETRY_EVERY = 15    # seconds (retry SETNX when not leader)


async def _sandbox_leader_supervisor(redis, provider) -> None:
    """Supervised leader election for the sandbox pool manager.

    Previous implementation tried SETNX exactly once at startup.  On a
    rolling ACA deploy the new revision's startup almost always races with
    the old revision's Redis lock (300 s TTL): SETNX returns False, the
    new worker permanently believes "someone else is leader", and the
    replenisher / rebalancer never run.  Result: hot tier stays at
    whatever the old revision left behind, cold tier never fills.

    This supervisor removes that race entirely:

    * While NOT leader, it re-attempts SETNX every ~15 s.  As soon as the
      old lock expires (or the former leader crashed and its TTL lapsed),
      this worker takes over.
    * While leader, it EXPIREs the key every ~60 s so the TTL never
      elapses under a healthy leader.
    * If a renewal ever fails (Redis partition, key was taken over), we
      drop leadership, stop the pool background tasks, and fall back to
      the retry loop.  Another worker will have (or will soon) taken
      over; this worker will re-acquire only if it wins the next race.

    On graceful cancellation we delete the key so the next process can
    acquire it immediately rather than waiting out the full TTL.
    """
    leader_held = False
    try:
        while True:
            try:
                if not leader_held:
                    # Try to win the election.  SETNX returns True only if
                    # the key did not already exist.
                    got = await redis.client.set(
                        _SANDBOX_LEADER_KEY,
                        "1",
                        nx=True,
                        ex=_SANDBOX_LEADER_TTL,
                    )
                    if got:
                        leader_held = True
                        try:
                            await provider.start_background_tasks()
                            logger.info(
                                "✅ Sandbox pool leadership acquired "
                                "(this worker is now pool leader)"
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to start pool background tasks: %s",
                                exc,
                            )
                            # Release the lock so another worker can try.
                            try:
                                await redis.client.delete(_SANDBOX_LEADER_KEY)
                            except Exception:
                                pass
                            leader_held = False
                    await asyncio.sleep(_SANDBOX_LEADER_RETRY_EVERY)
                else:
                    # Renew lease; fall back to retry loop if Redis says
                    # the key no longer exists (EXPIRE returns 0).
                    try:
                        ok = await redis.client.expire(
                            _SANDBOX_LEADER_KEY, _SANDBOX_LEADER_TTL,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Leader lease renewal errored (%s); "
                            "dropping leadership", exc,
                        )
                        ok = False
                    if not ok:
                        logger.warning(
                            "Leader lease lost (EXPIRE=0); "
                            "another worker will take over"
                        )
                        leader_held = False
                        try:
                            await provider.stop_background_tasks()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        continue
                    await asyncio.sleep(_SANDBOX_LEADER_RENEW_EVERY)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Sandbox leader supervisor loop error: %s", exc,
                )
                await asyncio.sleep(_SANDBOX_LEADER_RETRY_EVERY)
    except asyncio.CancelledError:
        if leader_held:
            try:
                await redis.client.delete(_SANDBOX_LEADER_KEY)
            except Exception:
                pass
        raise


# Backwards-compat shim for shutdown handler (still attached as
# `_leader_lock_task` on the provider).
async def _renew_sandbox_leader_lock(redis) -> None:  # pragma: no cover
    """Deprecated: replaced by ``_sandbox_leader_supervisor``."""
    await asyncio.sleep(0)


@app.on_event("startup")
async def startup_event():
    """Initialize database connections and resources on startup"""
    logger.info("Starting Agent Builder API")
    logger.info("Platform: %s %s", platform.system(), platform.release())
    logger.info("Python version: %s", sys.version)
    logger.info("Number of CPU cores: %s", multiprocessing.cpu_count())
    
    # Initialize Prometheus metrics
    try:
        from utils.metrics import init_metrics
        init_metrics(enabled=True)
        logger.info("✅ Prometheus metrics initialized")
    except Exception as e:
        logger.warning("⚠️  Failed to initialize Prometheus metrics: %s", e)
    
    try:
        from utils.langfuse_config import init_langfuse, is_langfuse_enabled
        if is_langfuse_enabled():
            if init_langfuse():
                logger.info("✅ Langfuse observability initialized")
            else:
                logger.warning("⚠️  Langfuse enabled but failed to initialize")
        else:
            logger.info("ℹ️  Langfuse disabled (LANGFUSE_ENABLED=false or missing keys)")
    except Exception as e:
        logger.warning("⚠️  Failed to initialize Langfuse: %s", e)
    
    # Verify NLTK data (downloaded at Docker build time)
    try:
        import nltk
        nltk.data.find('tokenizers/punkt_tab')
        logger.info("✅ NLTK punkt_tab verified and accessible")
    except Exception as e:
        logger.error("❌ NLTK data not found: %s", e)
        logger.warning("   Document parsing may not work correctly. NLTK data should be downloaded during Docker build.")
    
    # Initialize PostgreSQL database cluster
    try:
        from db.pgsql import init_db
        await init_db()
        logger.info("✅ PostgreSQL cluster initialized successfully")
    except Exception as e:
        logger.error("❌ Failed to initialize PostgreSQL cluster: %s", e)
        raise
    
    # Initialize Row-Level Security policies
    try:
        from db.pgsql import get_write_db
        from db.init_security import init_database_security
        
        async for db in get_write_db():
            await init_database_security(db)
            break
    except Exception as e:
        logger.warning("⚠️  Failed to initialize RLS policies: %s", e)
        logger.warning("   (This is normal if tables don't exist yet)")

    # Unified LLM catalog: insert missing YAML rows, then load from DB (insert-only, safe every deploy)
    try:
        from app.llm.registry import LlmModelRegistry
        from db.pgsql import get_admin_db

        async for db in get_admin_db():
            result = await LlmModelRegistry.ensure_catalog_loaded(db)
            logger.info("✅ LLM catalog ready: %s", result)
            break
    except Exception as e:
        logger.warning("⚠️  LLM registry DB init failed, using YAML cache: %s", e)
        from app.llm.registry import LlmModelRegistry
        LlmModelRegistry.load_from_yaml()
    
    # Initialize Redis connection
    try:
        from db.redis import init_redis
        await init_redis()
        logger.info("✅ Redis initialized successfully")
    except Exception as e:
        logger.error("❌ Failed to initialize Redis: %s", e)
        # Redis is optional, don't raise
        logger.warning("Continuing without Redis")
    
    # Initialize Azure Storage connector (singleton, reused across all requests)
    try:
        from core.dependencies import init_azure_storage_connector
        await init_azure_storage_connector()
        logger.info("✅ Azure Storage connector initialized (singleton)")
    except Exception as e:
        logger.warning("⚠️  Failed to initialize Azure Storage connector: %s", e)
        logger.warning("   File/document operations may not work")

    # Initialize sandbox provider (warm pool for ACI, no-op for Docker).
    # In multi-worker / multi-replica deployments every process runs this
    # startup.  We elect a single pool-manager worker via a supervised
    # Redis lease (see _sandbox_leader_supervisor).  The supervisor retries
    # SETNX every ~15 s until it wins, so a rolling deploy no longer
    # leaves all new replicas thinking "someone else is leader".
    try:
        from workflow.sandbox.sandbox_provider import get_sandbox_provider
        provider = get_sandbox_provider()
        if hasattr(provider, "start_background_tasks"):
            try:
                from db.redis import get_redis
                redis = await get_redis()
                provider._leader_lock_task = asyncio.create_task(
                    _sandbox_leader_supervisor(redis, provider)
                )
                logger.info(
                    "✅ Sandbox provider ready (leader election supervisor started)"
                )
            except Exception as exc:
                # Redis unavailable → single-process fallback: run the
                # pool locally without leader election.
                logger.warning(
                    "Redis unavailable for leader election (%s); "
                    "running sandbox pool locally without coordination",
                    exc,
                )
                await provider.start_background_tasks()
        else:
            logger.info("✅ Sandbox provider ready (Docker, no warm pool)")
    except Exception as e:
        logger.warning("⚠️  Failed to initialize sandbox provider: %s", e)
        logger.warning("   Code execution may not work")

    # Admin midnight jobs (workflow LLM scan + analytics refresh) + Redis queue worker
    try:
        from db.redis import get_redis
        from app.admin.scheduler import admin_scheduler_supervisor
        from app.admin.services.analytics_refresh_queue import AnalyticsRefreshQueue

        redis = await get_redis()
        app.state.admin_scheduler_task = asyncio.create_task(
            admin_scheduler_supervisor(redis)
        )
        app.state.analytics_refresh_worker_task = asyncio.create_task(
            AnalyticsRefreshQueue.worker_loop()
        )

        async def _bootstrap_analytics_snapshot() -> None:
            try:
                from db.pgsql import get_admin_db

                async for db in get_admin_db():
                    if not await AnalyticsRefreshQueue._has_completed_refresh(db):
                        result = await AnalyticsRefreshQueue.enqueue_scheduled(db)
                        logger.info("Analytics bootstrap refresh queued: %s", result)
                    break
            except Exception as exc:
                logger.warning("Analytics bootstrap skipped: %s", exc)

        asyncio.create_task(_bootstrap_analytics_snapshot())
        logger.info("✅ Admin scheduler + analytics refresh queue worker started")
    except Exception as e:
        logger.warning("⚠️  Admin scheduler / analytics worker not started: %s", e)


@app.on_event("shutdown")
async def shutdown_handler():
    """
    Graceful shutdown handler for SIGTERM/SIGINT signals.
    
    Ensures:
    1. No new requests are accepted
    2. Active requests complete (with timeout)
    3. Resources are cleaned up properly
    4. Data is saved/flushed
    """
    global is_shutting_down
    is_shutting_down = True
    
    logger.info("=" * 80)
    logger.info("🛑 GRACEFUL SHUTDOWN INITIATED")
    logger.info("=" * 80)
    
    # Wait briefly for active requests to complete (max 30s)
    logger.info("⏳ Waiting for active requests to complete (max 30s)...")
    try:
        await asyncio.wait_for(asyncio.sleep(2), timeout=2)
    except asyncio.TimeoutError:
        pass
    
    # Close LLM HTTP clients
    logger.info("🔌 Closing LLM HTTP client connections...")
    try:
        from config.llm_config import LLMClientManager
        await LLMClientManager.close_all()
        logger.info("✅ LLM HTTP clients closed")
    except Exception as e:
        logger.warning("⚠️  Failed to close LLM clients: %s", e)
    
    # Flush Langfuse observability data
    logger.info("📊 Flushing observability data...")
    try:
        from utils.langfuse_config import flush_langfuse, is_langfuse_enabled
        if is_langfuse_enabled():
            flush_langfuse()
            logger.info("✅ Langfuse data flushed")
    except Exception as e:
        logger.warning("⚠️  Failed to flush Langfuse: %s", e)
    
    # Shutdown sandbox provider (drain warm pool, destroy containers)
    logger.info("🔌 Shutting down sandbox provider...")
    try:
        from workflow.sandbox.sandbox_provider import get_sandbox_provider, shutdown_sandbox_provider
        provider = get_sandbox_provider()
        lock_task = getattr(provider, "_leader_lock_task", None)
        if lock_task and not lock_task.done():
            lock_task.cancel()
        await shutdown_sandbox_provider()
        logger.info("✅ Sandbox provider shut down")
    except Exception as e:
        logger.warning("⚠️  Failed to shut down sandbox provider: %s", e)

    # Close Azure Storage connector
    logger.info("🔌 Closing Azure Storage connector...")
    try:
        from core.dependencies import close_azure_storage_connector
        await close_azure_storage_connector()
        logger.info("✅ Azure Storage connector closed")
    except Exception as e:
        logger.warning("⚠️  Failed to close Azure Storage connector: %s", e)
    
    # Close Redis connection
    logger.info("🔌 Closing Redis connection...")
    try:
        from db.redis import close_redis
        await close_redis()
        logger.info("✅ Redis connection closed")
    except Exception as e:
        logger.warning("⚠️  Failed to close Redis: %s", e)
    
    # Close database connections
    logger.info("🔌 Closing database connections...")
    try:
        from db.pgsql import close_db
        await close_db()
        logger.info("✅ Database connections closed")
    except Exception as e:
        logger.warning("⚠️  Failed to close database: %s", e)
    
    logger.info("=" * 80)
    logger.info("✅ GRACEFUL SHUTDOWN COMPLETE")
    logger.info("=" * 80)
    
    # Signal shutdown complete
    shutdown_event.set()


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "Agent Builder API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/metrics")
async def metrics(current_user=Depends(get_current_user)):
    """
    Prometheus metrics endpoint.
    
    Exposes application metrics in Prometheus exposition format for monitoring:
    - HTTP request/response metrics
    - LLM API call statistics (tokens, cost, duration)
    - Database query performance
    - Cache hit rates
    - Business metrics (workflows, sessions, KB searches)
    - System metrics (active sessions, workflows)
    """
    from utils.metrics import get_prometheus_metrics
    data, content_type = get_prometheus_metrics()
    return Response(content=data, media_type=content_type)


# Health check endpoints moved to routers/health_routes.py
# Available endpoints:
#   GET /health/live   - Fast liveness probe (< 100ms)
#   GET /health/ready  - Readiness probe with dependency checks (< 5s)
#   GET /health        - Basic health check (legacy)
#   GET /health/detailed - Detailed check with system resources


if __name__ == "__main__":
    # Calculate optimal workers based on CPU cores
    workers = settings.WORKER_COUNT if settings.WORKER_COUNT else multiprocessing.cpu_count() * 2 + 1
    logger.info("Starting server with %s workers", workers)
    
    # Configure event loop based on platform
    if platform.system() == "Windows":
        loop_setup = {
            "loop": "asyncio",
            "http": "httptools",
        }
        logger.info("Using asyncio event loop for Windows")
    else:
        loop_setup = {
            "loop": "uvloop",
            "http": "httptools",
        }
        logger.info("Using uvloop event loop")

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=workers,  
        limit_concurrency=2000,  
        backlog=4000, 
        timeout_keep_alive=30,  
        access_log=True,
        log_level=settings.LOG_LEVEL.lower(), 
        reload=True, 
        proxy_headers=True, 
        forwarded_allow_ips=settings.FORWARDED_ALLOW_IPS,  
        **loop_setup
    )

