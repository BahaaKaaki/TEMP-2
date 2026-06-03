"""Defer / flush chat.delta events until the UI outcome is known."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import List, Tuple

_defer_chat_stream: ContextVar[bool] = ContextVar("defer_chat_stream", default=False)
_buffered_chat_deltas: ContextVar[List[Tuple[str, str]]] = ContextVar(
    "buffered_chat_deltas",
    default=[],
)


def defer_chat_stream() -> Token:
    """Buffer ``chat.delta`` publishes until flush or clear."""
    _buffered_chat_deltas.set([])
    return _defer_chat_stream.set(True)


def reset_defer_chat_stream(token: Token) -> None:
    _defer_chat_stream.reset(token)
    _buffered_chat_deltas.set([])


def is_chat_stream_deferred() -> bool:
    return bool(_defer_chat_stream.get())


def buffer_chat_delta(delta: str, span_id: str) -> None:
    if not delta:
        return
    buffer = list(_buffered_chat_deltas.get())
    buffer.append((delta, span_id))
    _buffered_chat_deltas.set(buffer)


def clear_chat_stream_buffer() -> None:
    _buffered_chat_deltas.set([])


async def flush_chat_stream_buffer() -> None:
    """Publish all buffered deltas in order."""
    from .langchain import _publish_chat_delta

    buffer = list(_buffered_chat_deltas.get())
    _buffered_chat_deltas.set([])
    for delta, span_id in buffer:
        await _publish_chat_delta(delta, span_id=span_id, enabled=True)
