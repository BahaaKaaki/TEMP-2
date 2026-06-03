"""Utilities for safe error handling in API responses."""
import logging

logger = logging.getLogger(__name__)


def safe_error_detail(exc: Exception, fallback: str) -> str:
    """Log the full exception server-side and return a generic message for the client."""
    logger.exception("%s: %s", fallback, exc)
    return fallback
