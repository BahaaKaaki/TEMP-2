"""Context-local tracing helpers.

Workflow nodes set the current execution/node context before doing work. LLM
wrappers and tool helpers can then emit normalized trace spans without each
caller passing execution metadata around.
"""

from __future__ import annotations

import time
import uuid
import logging
from contextvars import ContextVar, Token
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, TypeVar

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

T = TypeVar("T")

_execution_id: ContextVar[Optional[str]] = ContextVar("trace_execution_id", default=None)
_session_id: ContextVar[Optional[str]] = ContextVar("trace_session_id", default=None)
_node_id: ContextVar[Optional[str]] = ContextVar("trace_node_id", default=None)
_node_label: ContextVar[Optional[str]] = ContextVar("trace_node_label", default=None)
_node_type: ContextVar[Optional[str]] = ContextVar("trace_node_type", default=None)
_span_id: ContextVar[Optional[str]] = ContextVar("trace_span_id", default=None)

TraceTokens = Tuple[Token, Token, Token, Token, Token, Token]


class TraceEvent(BaseModel):
    """Normalized event sent to the frontend Trace panel."""

    execution_id: str
    session_id: Optional[str] = None
    node_id: Optional[str] = None
    node_label: Optional[str] = None
    node_type: Optional[str] = None
    span_id: str
    parent_span_id: Optional[str] = None
    event_type: str
    status: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    duration_ms: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


def set_trace_context(
    *,
    execution_id: Optional[str | int] = None,
    session_id: Optional[str] = None,
    node_id: Optional[str] = None,
    node_label: Optional[str] = None,
    node_type: Optional[str] = None,
    span_id: Optional[str] = None,
) -> TraceTokens:
    """Set trace context for the current async task."""
    return (
        _execution_id.set(str(execution_id) if execution_id is not None else None),
        _session_id.set(session_id),
        _node_id.set(node_id),
        _node_label.set(node_label),
        _node_type.set(node_type),
        _span_id.set(span_id),
    )


def reset_trace_context(tokens: TraceTokens) -> None:
    """Restore a previous trace context."""
    for var, token in zip(
        (_execution_id, _session_id, _node_id, _node_label, _node_type, _span_id),
        tokens,
    ):
        var.reset(token)


def get_trace_context() -> Dict[str, Optional[str]]:
    return {
        "execution_id": _execution_id.get(),
        "session_id": _session_id.get(),
        "node_id": _node_id.get(),
        "node_label": _node_label.get(),
        "node_type": _node_type.get(),
        "span_id": _span_id.get(),
    }


async def emit_trace_event(
    event_type: str,
    *,
    status: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
    span_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    node_id: Optional[str] = None,
    node_label: Optional[str] = None,
    node_type: Optional[str] = None,
) -> Optional[str]:
    """Emit a trace event if an execution context is active."""
    execution_id = _execution_id.get()
    if not execution_id:
        return None

    event = TraceEvent(
        execution_id=execution_id,
        session_id=_session_id.get(),
        node_id=node_id or _node_id.get(),
        node_label=node_label or _node_label.get(),
        node_type=node_type or _node_type.get(),
        span_id=span_id or _span_id.get() or _new_span_id("event"),
        parent_span_id=parent_span_id,
        event_type=event_type,
        status=status,
        duration_ms=duration_ms,
        payload=sanitize_payload(payload or {}),
    )

    try:
        from .trace_bus import TRACE_KIND, get_trace_bus

        bus = await get_trace_bus()
        return await bus.publish(
            execution_id,
            kind=TRACE_KIND,
            event_type=event_type,
            data=event.model_dump(exclude_none=True),
        )
    except Exception:
        logger.debug("Trace event dropped: %s", event_type, exc_info=True)
        return None


class TraceSpan:
    """Async context manager that emits started/completed/failed events."""

    def __init__(
        self,
        kind: str,
        *,
        label: str,
        payload: Optional[Dict[str, Any]] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
    ):
        self.kind = kind
        self.label = label
        self.payload: Dict[str, Any] = {"label": label, **(payload or {})}
        self.span_id = span_id or _new_span_id(kind)
        self.parent_span_id = parent_span_id
        self._started = 0.0
        self._token: Optional[Token] = None

    async def __aenter__(self) -> "TraceSpan":
        self._started = time.perf_counter()
        parent = self.parent_span_id if self.parent_span_id is not None else _span_id.get()
        self.parent_span_id = parent
        self._token = _span_id.set(self.span_id)
        await emit_trace_event(
            f"{self.kind}.started",
            status="running",
            payload=self.payload,
            span_id=self.span_id,
            parent_span_id=parent,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        duration_ms = (time.perf_counter() - self._started) * 1000
        if exc is None:
            await emit_trace_event(
                f"{self.kind}.completed",
                status="success",
                payload=self.payload,
                duration_ms=duration_ms,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
            )
        else:
            await emit_trace_event(
                f"{self.kind}.failed",
                status="error",
                payload={**self.payload, "error": str(exc)[:500]},
                duration_ms=duration_ms,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
            )
        if self._token is not None:
            _span_id.reset(self._token)
        return False

    def add_payload(self, **payload: Any) -> None:
        self.payload.update(payload)


async def trace_tool_call(
    tool_name: str,
    tool_args: Dict[str, Any],
    invoke: Callable[[], Awaitable[T]],
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> T:
    """Trace an async tool invocation."""
    span_payload = {
        "tool_name": tool_name,
        "args": tool_args,
        **(payload or {}),
    }
    async with TraceSpan("tool", label=tool_name, payload=span_payload):
        return await invoke()


def sanitize_payload(value: Any, *, max_string: int = 1200, depth: int = 0) -> Any:
    """Trim trace payloads and avoid storing prompts or large content."""
    if depth > 4:
        return "[truncated]"
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + "... [truncated]"
    if isinstance(value, (list, tuple)):
        items = [sanitize_payload(v, max_string=max_string, depth=depth + 1) for v in value[:10]]
        if len(value) > 10:
            items.append(f"... [{len(value) - 10} more]")
        return items
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= 24:
                result["..."] = f"[{len(value) - 24} more keys]"
                break
            key_str = str(key)
            if _should_omit_key(key_str):
                result[key_str] = "[omitted]"
                continue
            result[key_str] = sanitize_payload(item, max_string=max_string, depth=depth + 1)
        return result
    return sanitize_payload(str(value), max_string=max_string, depth=depth + 1)


def _should_omit_key(key: str) -> bool:
    lower = key.lower()
    blocked = (
        "api_key",
        "password",
        "token",
        "secret",
        "prompt",
        "messages",
        "semantic_model",
        "file_content",
        "code",
    )
    return any(term in lower for term in blocked)


def _new_span_id(kind: str) -> str:
    return f"{kind}:{uuid.uuid4().hex[:12]}"
