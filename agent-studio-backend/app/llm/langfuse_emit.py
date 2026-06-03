"""
Emit Langfuse generations for central LLM and embedding calls.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from app.llm.observability_context import (
    build_langfuse_metadata,
    get_llm_observability_context,
    resolve_user_identity,
)
from app.llm.pricing_for_langfuse import compute_cost_details
from app.llm.usage_for_langfuse import extract_usage_for_langfuse
from app.tracing.context import sanitize_payload

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _langfuse_client():
    from utils.langfuse_config import is_langfuse_enabled

    if not is_langfuse_enabled():
        return None
    try:
        from langfuse import get_client

        return get_client()
    except Exception:
        logger.debug("Langfuse client unavailable", exc_info=True)
        return None


def _resolve_llm_role(
    *,
    llm_role: Optional[str],
    binding_key: Optional[str],
    operation: str,
    node_type: Optional[str],
) -> str:
    if llm_role:
        return llm_role
    ctx = get_llm_observability_context()
    if ctx.get("llm_role"):
        return ctx["llm_role"]  # type: ignore[return-value]
    if binding_key:
        from app.llm.observability_context import llm_role_from_binding

        derived = llm_role_from_binding(binding_key)
        if derived:
            return derived
    if operation == "llm.tool_calling":
        return "tool_calling"
    if operation == "llm.structured_output":
        return "structured_output"
    node_type_lower = (node_type or "").lower()
    if node_type_lower in ("agent", "researcher", "subagent", "code-executor"):
        return "main_llm"
    return operation.replace(".", "_") if operation else "llm"


def _langfuse_session_id(ctx: Dict[str, Optional[str]]) -> Optional[str]:
    if ctx.get("execution_id"):
        return str(ctx["execution_id"])
    if ctx.get("session_id"):
        return str(ctx["session_id"])
    return None


def _extract_usage(response: Any) -> Optional[Dict[str, int]]:
    return extract_usage_for_langfuse(response)


def _update_generation(
    generation: Any,
    *,
    model: str,
    output_summary: Dict[str, Any],
    metadata: Dict[str, Any],
    duration_ms: float,
    usage: Optional[Dict[str, int]],
) -> None:
    """Push usage_details, cost_details, and metadata mirrors for Langfuse."""
    merged_metadata: Dict[str, Any] = {
        **metadata,
        "duration_ms": round(duration_ms, 2),
        **output_summary,
    }
    cost_details: Optional[Dict[str, float]] = None
    if usage:
        merged_metadata["usage"] = usage
        cost_details = compute_cost_details(usage, model_name=model)
        if cost_details:
            merged_metadata["cost"] = cost_details

    update_kwargs: Dict[str, Any] = {
        "output": output_summary,
        "metadata": merged_metadata,
    }
    if usage:
        update_kwargs["usage_details"] = usage
    if cost_details:
        update_kwargs["cost_details"] = cost_details

    try:
        generation.update(**update_kwargs)
    except TypeError:
        generation.update(
            output=output_summary,
            metadata=merged_metadata,
            usage_details=usage,
            cost_details=cost_details,
        )


def _summarize_output(response: Any) -> Dict[str, Any]:
    if isinstance(response, dict) and "raw" in response:
        return sanitize_payload({
            "response_type": "structured",
            "parsed": response.get("parsed") is not None,
            "parsing_error": bool(response.get("parsing_error")),
        })
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return sanitize_payload({"response_type": type(response).__name__, "content_chars": len(content)})
    if isinstance(content, list):
        return sanitize_payload({"response_type": type(response).__name__, "content_blocks": len(content)})
    return sanitize_payload({"response_type": type(response).__name__})


async def record_llm_generation(
    *,
    model: str,
    operation: str,
    input_summary: Dict[str, Any],
    invoke: Callable[[], Awaitable[T]],
    binding_key: Optional[str] = None,
    llm_role: Optional[str] = None,
    tool_name: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> T:
    """
    Run an LLM coroutine and record a Langfuse generation (no-op when disabled).
    """
    client = _langfuse_client()
    if client is None:
        return await invoke()

    ctx = get_llm_observability_context()
    role = _resolve_llm_role(
        llm_role=llm_role,
        binding_key=binding_key,
        operation=operation,
        node_type=ctx.get("node_type"),
    )
    identity = resolve_user_identity()
    user_id = identity.get("user_id")

    metadata = build_langfuse_metadata(
        model=model,
        operation=operation,
        binding_key=binding_key,
        llm_role=role,
        tool_name=tool_name,
        extra={**(extra_metadata or {}), "input": sanitize_payload(input_summary)},
    )
    session_id = _langfuse_session_id(ctx)
    name = role or operation

    started = time.perf_counter()
    try:
        with client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            metadata=metadata,
        ) as generation:
            if user_id or session_id:
                try:
                    generation.update_trace(
                        user_id=user_id,
                        session_id=session_id,
                        metadata=metadata,
                    )
                except Exception:
                    logger.debug("Langfuse update_trace failed", exc_info=True)

            response = await invoke()
            duration_ms = (time.perf_counter() - started) * 1000
            output_summary = _summarize_output(response)
            usage = _extract_usage(response)
            _update_generation(
                generation,
                model=model,
                output_summary=output_summary,
                metadata=metadata,
                duration_ms=duration_ms,
                usage=usage,
            )
            return response
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        try:
            with client.start_as_current_observation(
                as_type="generation",
                name=name,
                model=model,
                metadata={**metadata, "status": "error", "error": str(exc)[:500]},
            ) as generation:
                if user_id or session_id:
                    try:
                        generation.update_trace(user_id=user_id, session_id=session_id)
                    except Exception:
                        pass
                generation.update(
                    level="ERROR",
                    status_message=str(exc)[:500],
                    metadata={**metadata, "duration_ms": round(duration_ms, 2)},
                )
        except Exception:
            logger.debug("Langfuse error generation failed", exc_info=True)
        raise


async def record_embedding_generation(
    *,
    model: str,
    text_count: int,
    invoke: Callable[[], Awaitable[T]],
    operation: str = "embedding",
) -> T:
    """Record an embedding API call as a Langfuse generation."""
    client = _langfuse_client()
    if client is None:
        return await invoke()

    ctx = get_llm_observability_context()
    user_id = resolve_user_identity().get("user_id")

    metadata = build_langfuse_metadata(
        model=model,
        operation=operation,
        llm_role="embedding",
        extra={"text_count": text_count},
    )
    session_id = _langfuse_session_id(ctx)
    started = time.perf_counter()

    try:
        with client.start_as_current_observation(
            as_type="generation",
            name="embedding",
            model=model,
            metadata=metadata,
        ) as generation:
            if user_id or session_id:
                try:
                    generation.update_trace(
                        user_id=user_id,
                        session_id=session_id,
                        metadata=metadata,
                    )
                except Exception:
                    pass
            result = await invoke()
            duration_ms = (time.perf_counter() - started) * 1000
            vector_count = len(result) if isinstance(result, list) else 1
            generation.update(
                output=sanitize_payload({
                    "vector_count": vector_count,
                    "text_count": text_count,
                }),
                metadata={**metadata, "duration_ms": round(duration_ms, 2)},
            )
            return result
    except Exception as exc:
        logger.debug("Langfuse embedding generation failed: %s", exc)
        raise
