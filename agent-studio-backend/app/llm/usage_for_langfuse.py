"""
Extract LangChain/provider token usage for Langfuse usage_details.

Kept free of tracing imports so unit tests can import without app bootstrap.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        coerced = _coerce_int(value)
        if coerced is not None:
            return coerced
    return None


def _normalize_usage_source(usage: Dict[str, Any]) -> Dict[str, Any]:
    """Map provider/LangChain usage dicts to Langfuse usage_details."""
    details: Dict[str, Any] = {}

    inp = _first_int(usage.get("input_tokens"), usage.get("prompt_tokens"))
    out = _first_int(usage.get("output_tokens"), usage.get("completion_tokens"))
    total = _first_int(usage.get("total_tokens"))
    if inp is not None:
        details["input"] = inp
    if out is not None:
        details["output"] = out
    if total is not None:
        details["total"] = total
    elif inp is not None and out is not None:
        details["total"] = inp + out

    in_breakdown = (
        usage.get("input_token_details")
        or usage.get("input_tokens_details")
        or usage.get("prompt_tokens_details")
        or {}
    )
    out_breakdown = (
        usage.get("output_token_details")
        or usage.get("output_tokens_details")
        or usage.get("completion_tokens_details")
        or {}
    )
    if not isinstance(in_breakdown, dict):
        in_breakdown = {}
    if not isinstance(out_breakdown, dict):
        out_breakdown = {}

    cache_read = _first_int(
        usage.get("cache_read_input_tokens"),
        in_breakdown.get("cache_read"),
        in_breakdown.get("cached_tokens"),
        in_breakdown.get("cached"),
    )
    if cache_read is not None and cache_read > 0:
        details["input_cache_read"] = cache_read

    cache_creation = _first_int(
        usage.get("cache_creation_input_tokens"),
        in_breakdown.get("cache_creation"),
        in_breakdown.get("cache_creation_tokens"),
    )
    if cache_creation is not None and cache_creation > 0:
        details["input_cache_creation"] = cache_creation

    reasoning = _first_int(
        out_breakdown.get("reasoning"),
        out_breakdown.get("reasoning_tokens"),
    )
    if reasoning is not None and reasoning > 0:
        details["output_reasoning"] = reasoning

    return details


def finalize_usage_details_for_langfuse(details: Dict[str, Any]) -> Dict[str, int]:
    """
    Normalize to Langfuse ingestion keys (flat int map).

    See https://langfuse.com/docs/observability/features/token-and-cost-tracking
    - Anthropic: cache_read_input_tokens, cache_creation_input_tokens
    - OpenAI flatten: input_cached_tokens (from cached_tokens)
    """
    out: Dict[str, int] = {}

    for key in ("input", "output", "total"):
        val = _coerce_int(details.get(key))
        if val is not None:
            out[key] = val

    cache_read = _first_int(details.get("input_cache_read"))
    if cache_read is not None and cache_read > 0:
        out["cache_read_input_tokens"] = cache_read
        out["input_cached_tokens"] = cache_read
        out["input_cache_read"] = cache_read

    cache_creation = _first_int(details.get("input_cache_creation"))
    if cache_creation is not None and cache_creation > 0:
        out["cache_creation_input_tokens"] = cache_creation
        out["input_cache_creation"] = cache_creation

    reasoning = _first_int(details.get("output_reasoning"))
    if reasoning is not None and reasoning > 0:
        out["output_reasoning_tokens"] = reasoning
        out["output_reasoning"] = reasoning

    # OpenAI-style aliases (Langfuse maps prompt_tokens → input, etc.)
    if "input" in out:
        out["prompt_tokens"] = out["input"]
    if "output" in out:
        out["completion_tokens"] = out["output"]
    if "total" in out:
        out["total_tokens"] = out["total"]

    return out


def _collect_usage_dicts(response: Any) -> list[Dict[str, Any]]:
    """Gather raw usage payloads from AIMessage-style responses."""
    sources: list[Dict[str, Any]] = []

    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict) and usage_metadata:
        sources.append(usage_metadata)

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        nested = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(nested, dict) and nested:
            sources.append(nested)

    if isinstance(response, dict):
        nested = response.get("token_usage") or response.get("usage")
        if isinstance(nested, dict) and nested:
            sources.append(nested)

    return sources


def extract_usage_for_langfuse(response: Any) -> Optional[Dict[str, Any]]:
    """
    Build Langfuse usage_details from LangChain AIMessage usage fields.

    Supports flat usage_metadata (Responses API path) and nested token_usage
    (chat/completions). Propagates reasoning and prompt-cache breakdown when present.
    """
    merged: Dict[str, Any] = {}
    for usage in _collect_usage_dicts(response):
        for key, value in _normalize_usage_source(usage).items():
            if key not in merged or merged[key] is None:
                merged[key] = value
            elif key in ("input", "output", "total") and value is not None:
                merged[key] = value

    if not merged:
        return None
    finalized = finalize_usage_details_for_langfuse(merged)
    return finalized or None
