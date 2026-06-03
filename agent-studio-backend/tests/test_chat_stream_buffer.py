"""Tests for deferred chat.delta buffering."""

import pytest

from app.tracing.chat_stream import (
    buffer_chat_delta,
    clear_chat_stream_buffer,
    defer_chat_stream,
    flush_chat_stream_buffer,
    is_chat_stream_deferred,
    reset_defer_chat_stream,
)
from app.tracing.context import reset_trace_context, set_trace_context
from app.tracing.trace_bus import EXECUTION_KIND


@pytest.mark.asyncio
async def test_defer_buffers_until_flush(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return f"{len(published)}-0"

    async def fake_get_trace_bus():
        return FakeBus()

    monkeypatch.setattr("app.tracing.trace_bus.get_trace_bus", fake_get_trace_bus)

    trace_tokens = set_trace_context(execution_id="42", span_id="node:agent_1")
    defer_token = defer_chat_stream()
    try:
        assert is_chat_stream_deferred()
        buffer_chat_delta("hel", "span-1")
        buffer_chat_delta("lo", "span-1")
        assert published == []

        await flush_chat_stream_buffer()
        assert len(published) == 2
        assert published[0][2] == "chat.delta"
        assert published[0][3]["delta"] == "hel"
        assert published[1][3]["delta"] == "lo"
    finally:
        reset_defer_chat_stream(defer_token)
        reset_trace_context(trace_tokens)


@pytest.mark.asyncio
async def test_clear_discards_buffered_deltas(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return "1-0"

    monkeypatch.setattr(
        "app.tracing.trace_bus.get_trace_bus",
        lambda: FakeBus(),
    )

    trace_tokens = set_trace_context(execution_id="42", span_id="node:agent_1")
    defer_token = defer_chat_stream()
    try:
        buffer_chat_delta("hidden", "span-1")
        clear_chat_stream_buffer()
        await flush_chat_stream_buffer()
        assert published == []
    finally:
        reset_defer_chat_stream(defer_token)
        reset_trace_context(trace_tokens)
