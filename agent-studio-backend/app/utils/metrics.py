"""
Observability and telemetry metrics for Prometheus monitoring.

Provides Prometheus-compatible metrics for monitoring application health,
performance, and business metrics.
"""

import time
import logging
from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import contextmanager
import asyncio

logger = logging.getLogger(__name__)

# Try to import prometheus_client (optional dependency)
try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        Summary,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    logger.warning("prometheus_client not installed. Metrics will be no-ops. "
                  "Install with: pip install prometheus-client")
    PROMETHEUS_AVAILABLE = False


class MetricsCollector:
    """
    Central metrics collector for the application.
    
    Provides Prometheus-compatible metrics for:
    - Request/response metrics
    - LLM API calls
    - Database queries
    - Cache hit rates
    - Business metrics (workflows, agents, etc.)
    """
    
    def __init__(self, enabled: bool = True):
        """
        Initialize metrics collector.
        
        Args:
            enabled: Whether metrics collection is enabled
        """
        self.enabled = enabled and PROMETHEUS_AVAILABLE
        
        if not self.enabled:
            logger.info("Metrics collection disabled")
            return
        
        # ========================================================================
        # HTTP REQUEST METRICS
        # ========================================================================
        
        self.http_requests_total = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status']
        )
        
        self.http_request_duration_seconds = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        self.http_request_size_bytes = Summary(
            'http_request_size_bytes',
            'HTTP request size in bytes',
            ['method', 'endpoint']
        )
        
        self.http_response_size_bytes = Summary(
            'http_response_size_bytes',
            'HTTP response size in bytes',
            ['method', 'endpoint']
        )
        
        # ========================================================================
        # LLM API METRICS
        # ========================================================================
        
        self.llm_requests_total = Counter(
            'llm_requests_total',
            'Total LLM API requests',
            ['provider', 'model', 'status']
        )
        
        self.llm_request_duration_seconds = Histogram(
            'llm_request_duration_seconds',
            'LLM API request duration in seconds',
            ['provider', 'model'],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0]
        )
        
        self.llm_tokens_used = Counter(
            'llm_tokens_used_total',
            'Total LLM tokens used',
            ['provider', 'model', 'type']  # type: prompt, completion, total
        )
        
        self.llm_cost_usd = Counter(
            'llm_cost_usd_total',
            'Estimated LLM cost in USD',
            ['provider', 'model']
        )
        
        self.llm_errors_total = Counter(
            'llm_errors_total',
            'Total LLM API errors',
            ['provider', 'model', 'error_type']
        )
        
        # ========================================================================
        # DATABASE METRICS
        # ========================================================================
        
        self.db_queries_total = Counter(
            'db_queries_total',
            'Total database queries',
            ['operation', 'table', 'status']
        )
        
        self.db_query_duration_seconds = Histogram(
            'db_query_duration_seconds',
            'Database query duration in seconds',
            ['operation', 'table'],
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
        )
        
        self.db_connection_pool_size = Gauge(
            'db_connection_pool_size',
            'Current database connection pool size',
            ['pool_type']  # read, write
        )
        
        self.db_connection_pool_available = Gauge(
            'db_connection_pool_available',
            'Available database connections in pool',
            ['pool_type']
        )
        
        # ========================================================================
        # CACHE METRICS
        # ========================================================================
        
        self.cache_operations_total = Counter(
            'cache_operations_total',
            'Total cache operations',
            ['operation', 'cache_type', 'status']  # operation: get, set, delete
        )
        
        self.cache_hit_rate = Gauge(
            'cache_hit_rate',
            'Cache hit rate (0-1)',
            ['cache_type']
        )
        
        self.cache_size_bytes = Gauge(
            'cache_size_bytes',
            'Current cache size in bytes',
            ['cache_type']
        )
        
        # ========================================================================
        # BUSINESS METRICS
        # ========================================================================
        
        self.workflows_total = Counter(
            'workflows_total',
            'Total workflow executions',
            ['status']  # completed, failed, running
        )
        
        self.workflow_duration_seconds = Histogram(
            'workflow_duration_seconds',
            'Workflow execution duration in seconds',
            buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        )
        
        self.agent_tool_calls_total = Counter(
            'agent_tool_calls_total',
            'Total agent tool calls',
            ['tool_name', 'status']
        )
        
        self.chat_messages_total = Counter(
            'chat_messages_total',
            'Total chat messages',
            ['direction']  # user, assistant
        )
        
        self.knowledge_base_searches_total = Counter(
            'knowledge_base_searches_total',
            'Total knowledge base searches',
            ['kb_id', 'search_method']  # semantic, bm25, hybrid
        )
        
        self.document_uploads_total = Counter(
            'document_uploads_total',
            'Total document uploads',
            ['file_type', 'status']
        )
        
        # ========================================================================
        # SYSTEM METRICS
        # ========================================================================
        
        self.active_sessions = Gauge(
            'active_sessions',
            'Number of active chat sessions'
        )
        
        self.active_workflows = Gauge(
            'active_workflows',
            'Number of currently running workflows'
        )
        
        self.background_tasks = Gauge(
            'background_tasks',
            'Number of pending background tasks'
        )
        
        self.rate_limit_hits_total = Counter(
            'rate_limit_hits_total',
            'Total rate limit hits',
            ['endpoint', 'limit_type']
        )
        
        # ========================================================================
        # ERROR METRICS
        # ========================================================================
        
        self.errors_total = Counter(
            'errors_total',
            'Total application errors',
            ['error_type', 'component']
        )
        
        self.circuit_breaker_state = Gauge(
            'circuit_breaker_state',
            'Circuit breaker state (0=closed, 1=open, 2=half-open)',
            ['service']
        )
        
        logger.info("✅ Metrics collector initialized with %d metric families", 
                   len(REGISTRY._collector_to_names))
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def record_http_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration: float,
        request_size: Optional[int] = None,
        response_size: Optional[int] = None
    ):
        """Record HTTP request metrics."""
        if not self.enabled:
            return
        
        self.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=str(status_code)
        ).inc()
        
        self.http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
        
        if request_size is not None:
            self.http_request_size_bytes.labels(
                method=method,
                endpoint=endpoint
            ).observe(request_size)
        
        if response_size is not None:
            self.http_response_size_bytes.labels(
                method=method,
                endpoint=endpoint
            ).observe(response_size)
    
    def record_llm_request(
        self,
        provider: str,
        model: str,
        duration: float,
        status: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        error_type: Optional[str] = None
    ):
        """Record LLM API request metrics."""
        if not self.enabled:
            return
        
        self.llm_requests_total.labels(
            provider=provider,
            model=model,
            status=status
        ).inc()
        
        self.llm_request_duration_seconds.labels(
            provider=provider,
            model=model
        ).observe(duration)
        
        if prompt_tokens:
            self.llm_tokens_used.labels(
                provider=provider,
                model=model,
                type='prompt'
            ).inc(prompt_tokens)
        
        if completion_tokens:
            self.llm_tokens_used.labels(
                provider=provider,
                model=model,
                type='completion'
            ).inc(completion_tokens)
        
        if total_tokens:
            self.llm_tokens_used.labels(
                provider=provider,
                model=model,
                type='total'
            ).inc(total_tokens)
        
        if cost_usd:
            self.llm_cost_usd.labels(
                provider=provider,
                model=model
            ).inc(cost_usd)
        
        if error_type:
            self.llm_errors_total.labels(
                provider=provider,
                model=model,
                error_type=error_type
            ).inc()
    
    def record_db_query(
        self,
        operation: str,
        table: str,
        duration: float,
        status: str = "success"
    ):
        """Record database query metrics."""
        if not self.enabled:
            return
        
        self.db_queries_total.labels(
            operation=operation,
            table=table,
            status=status
        ).inc()
        
        self.db_query_duration_seconds.labels(
            operation=operation,
            table=table
        ).observe(duration)
    
    def record_workflow_execution(
        self,
        duration: float,
        status: str
    ):
        """Record workflow execution metrics."""
        if not self.enabled:
            return
        
        self.workflows_total.labels(status=status).inc()
        self.workflow_duration_seconds.observe(duration)
    
    def record_cache_operation(
        self,
        operation: str,
        cache_type: str,
        status: str
    ):
        """Record cache operation metrics."""
        if not self.enabled:
            return
        
        self.cache_operations_total.labels(
            operation=operation,
            cache_type=cache_type,
            status=status
        ).inc()
    
    @contextmanager
    def measure_time(self, metric_fn: Callable[[float], None]):
        """
        Context manager to measure execution time.
        
        Example:
            with metrics.measure_time(
                lambda duration: metrics.db_query_duration_seconds.labels(
                    operation='select', table='users'
                ).observe(duration)
            ):
                # ... database operation ...
        """
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            metric_fn(duration)


# ============================================================================
# DECORATORS
# ============================================================================

def track_llm_call(provider: str, model: str):
    """
    Decorator to track LLM API calls.
    
    Usage:
        @track_llm_call(provider="openai", model="gpt-4")
        async def call_llm(messages):
            # ... LLM call ...
            return response
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            error_type = None
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_type = type(e).__name__
                raise
            finally:
                duration = time.time() - start_time
                get_metrics().record_llm_request(
                    provider=provider,
                    model=model,
                    duration=duration,
                    status=status,
                    error_type=error_type
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            error_type = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_type = type(e).__name__
                raise
            finally:
                duration = time.time() - start_time
                get_metrics().record_llm_request(
                    provider=provider,
                    model=model,
                    duration=duration,
                    status=status,
                    error_type=error_type
                )
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def track_db_query(operation: str, table: str):
    """
    Decorator to track database queries.
    
    Usage:
        @track_db_query(operation="select", table="workflows")
        async def get_workflow(workflow_id):
            # ... database query ...
            return workflow
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                get_metrics().record_db_query(
                    operation=operation,
                    table=table,
                    duration=duration,
                    status=status
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            status = "success"
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.time() - start_time
                get_metrics().record_db_query(
                    operation=operation,
                    table=table,
                    duration=duration,
                    status=status
                )
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


# ============================================================================
# GLOBAL METRICS INSTANCE
# ============================================================================

_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """
    Get the global metrics collector instance.
    
    Returns:
        MetricsCollector: Singleton instance
    """
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def init_metrics(enabled: bool = True) -> MetricsCollector:
    """
    Initialize the global metrics collector.
    
    Args:
        enabled: Whether to enable metrics collection
        
    Returns:
        MetricsCollector: Initialized instance
    """
    global _metrics
    _metrics = MetricsCollector(enabled=enabled)
    return _metrics


# ============================================================================
# FASTAPI INTEGRATION
# ============================================================================

def get_prometheus_metrics() -> tuple[bytes, str]:
    """
    Get Prometheus metrics in exposition format.
    
    Returns:
        Tuple of (metrics_bytes, content_type)
    """
    if not PROMETHEUS_AVAILABLE:
        return b"# Prometheus client not installed\n", "text/plain"
    
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# Example usage in main.py:
#
# from utils.metrics import get_prometheus_metrics
#
# @app.get("/metrics")
# async def metrics():
#     """Prometheus metrics endpoint."""
#     data, content_type = get_prometheus_metrics()
#     return Response(content=data, media_type=content_type)


