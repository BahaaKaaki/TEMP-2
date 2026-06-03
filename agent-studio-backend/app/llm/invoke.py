"""
LLM invocation with catalog-backed fallback on retryable errors.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from app.llm.observability_context import pop_langfuse_extra, push_langfuse_extra
from app.llm.registry import LlmModelRegistry, ResolvedModel

logger = logging.getLogger(__name__)

_RETRYABLE_MARKERS = (
    "rate limit",
    "429",
    "503",
    "502",
    "500",
    "timeout",
    "timed out",
    "model_not_found",
    "does not exist",
    "not found",
    "overloaded",
    "unavailable",
)


def is_retryable_llm_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _RETRYABLE_MARKERS)


async def ainvoke_with_fallback(
    llm: Any,
    messages: List[Any],
    *,
    resolved: Optional[ResolvedModel] = None,
    binding_key: Optional[str] = None,
    model_name: Optional[str] = None,
    provider: Optional[str] = None,
    **invoke_kwargs: Any,
) -> Any:
    """
    Invoke LLM; on retryable failure, retry once with catalog fallback model.
    """
    if resolved is None:
        resolved = LlmModelRegistry.resolve_for_invoke(
            binding_key=binding_key,
            model_name=model_name,
            provider=provider,
        )

    try:
        return await llm.ainvoke(messages, **invoke_kwargs)
    except Exception as exc:
        if not resolved.fallback or not is_retryable_llm_error(exc):
            raise
        logger.warning(
            "LLM invoke failed for %s (binding=%s), retrying with fallback %s: %s",
            resolved.primary,
            resolved.binding_key or model_name,
            resolved.fallback,
            exc,
        )
        from app.config.llm_config import LLMClientManager

        fallback_llm = LLMClientManager.get_client(
            model=resolved.fallback,
            binding_key=binding_key or resolved.binding_key,
        )
        extra_token = push_langfuse_extra({
            "fallback_used": True,
            "fallback_model": resolved.fallback,
            "primary_model": resolved.primary,
        })
        try:
            response = await fallback_llm.ainvoke(messages, **invoke_kwargs)
        finally:
            pop_langfuse_extra(extra_token)
        if hasattr(response, "response_metadata") and isinstance(response.response_metadata, dict):
            response.response_metadata["llm_fallback_used"] = True
            response.response_metadata["llm_fallback_model"] = resolved.fallback
        return response
