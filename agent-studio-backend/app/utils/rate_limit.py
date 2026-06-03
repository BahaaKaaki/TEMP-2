"""
Rate limiting utilities for API endpoints.

Uses slowapi (FastAPI-native rate limiter) with Redis backend for distributed rate limiting.
Falls back to in-memory storage if Redis is not available.
"""
import logging
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from config.settings import settings
from config.keyvault import cfg

logger = logging.getLogger(__name__)


def _get_rate_limit_key(request: Request) -> str:
    """
    Get rate limit key from request.
    
    Uses IP address as the key, with fallback to 'unknown' if not available.
    In production behind a proxy, ensure X-Forwarded-For is properly set.
    
    Args:
        request: FastAPI request object
    
    Returns:
        str: Rate limit key (IP address)
    """
    # Try to get real IP from X-Forwarded-For header (when behind proxy/load balancer)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can be: "client, proxy1, proxy2"
        # We want the first (leftmost) IP which is the original client
        ip = forwarded_for.split(",")[0].strip()
        return ip
    
    # Fallback to direct connection IP
    if request.client:
        return request.client.host
    
    # Last resort fallback
    logger.warning("Could not determine client IP for rate limiting")
    return "unknown"


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.
    
    Returns a clear JSON response with:
    - Error message
    - Retry-After header (seconds until limit resets)
    - Rate limit information
    
    Args:
        request: FastAPI request object
        exc: RateLimitExceeded exception
    
    Returns:
        JSONResponse: 429 Too Many Requests with details
    """
    # Extract retry-after from exception (seconds until reset)
    retry_after = getattr(exc, "retry_after", 60)
    
    # Get client IP for logging
    client_ip = _get_rate_limit_key(request)
    
    logger.warning(
        "Rate limit exceeded: %s %s - IP: %s - Retry after: %ds",
        request.method,
        request.url.path,
        client_ip,
        retry_after
    )
    
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please slow down and try again later.",
            "retry_after_seconds": retry_after
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(getattr(exc, "limit", "unknown")),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(retry_after)
        }
    )


# Initialize rate limiter
def get_limiter() -> Limiter:
    """
    Get or create rate limiter instance.
    
    Uses Redis if available (for distributed rate limiting across multiple instances),
    otherwise falls back to in-memory storage (single instance only).
    
    Returns:
        Limiter: Configured rate limiter
    """
    # Determine storage URL (Redis or memory)
    storage_uri = settings.RATE_LIMIT_STORAGE_URL
    
    if not storage_uri:
        # Try to use Redis from environment
        redis_url = cfg.REDIS_URL
        if redis_url:
            storage_uri = redis_url
            logger.debug("Rate limiter using Redis storage: %s", redis_url)
        else:
            storage_uri = "memory://"
            logger.warning(
                "Rate limiter using in-memory storage. "
                "For multi-instance deployments, configure REDIS_URL."
            )
    
    # Create limiter with custom key function
    limiter = Limiter(
        key_func=_get_rate_limit_key,
        storage_uri=storage_uri,
        default_limits=[
            f"{settings.RATE_LIMIT_PER_MINUTE}/minute",
            f"{settings.RATE_LIMIT_PER_HOUR}/hour"
        ],
        enabled=settings.RATE_LIMIT_ENABLED,
        headers_enabled=True,  # Add X-RateLimit-* headers to responses
        strategy="fixed-window"  # Simple fixed window strategy
    )
    
    logger.debug(
        "Rate limiter initialized: %s req/min, %s req/hour (enabled: %s)",
        settings.RATE_LIMIT_PER_MINUTE,
        settings.RATE_LIMIT_PER_HOUR,
        settings.RATE_LIMIT_ENABLED
    )
    
    return limiter


# Global limiter instance
limiter = get_limiter()


# Helper function to add rate limit headers to response
def add_rate_limit_headers(
    response: Response,
    limit: int,
    remaining: int,
    reset: int
) -> None:
    """
    Add rate limit headers to response.
    
    Follows the IETF draft standard for rate limit headers:
    https://datatracker.ietf.org/doc/html/draft-polli-ratelimit-headers
    
    Args:
        response: FastAPI response object
        limit: Total requests allowed in window
        remaining: Requests remaining in window
        reset: Seconds until window resets
    """
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset)


# Convenience decorators for common rate limits
def rate_limit_chat():
    """Rate limit decorator for chat endpoints (10 req/min)."""
    return limiter.limit(f"{settings.RATE_LIMIT_CHAT_PER_MINUTE}/minute")


def rate_limit_file_upload():
    """Rate limit decorator for file upload endpoints (5 req/min)."""
    return limiter.limit(f"{settings.RATE_LIMIT_FILE_UPLOAD_PER_MINUTE}/minute")


def rate_limit_kb_upload():
    """Rate limit decorator for KB document upload endpoints (3 req/min)."""
    return limiter.limit(f"{settings.RATE_LIMIT_KB_UPLOAD_PER_MINUTE}/minute")


def rate_limit_workflow():
    """Rate limit decorator for workflow execution endpoints (20 req/min)."""
    return limiter.limit(f"{settings.RATE_LIMIT_WORKFLOW_PER_MINUTE}/minute")


def rate_limit_auth():
    """Rate limit decorator for auth endpoints (login/register)."""
    return limiter.limit(f"{settings.RATE_LIMIT_AUTH_PER_MINUTE}/minute")


def rate_limit_refresh():
    """Rate limit decorator for token refresh endpoint."""
    return limiter.limit(f"{settings.RATE_LIMIT_REFRESH_PER_MINUTE}/minute")

