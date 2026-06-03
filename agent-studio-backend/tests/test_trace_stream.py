import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessageChunk
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.routers.sse_routes import stream_execution_trace
from app.tracing import reset_trace_context, set_trace_context
from app.tracing.langchain import TracedChatModel
from app.tracing.trace_bus import ExecutionTraceBus, TRACE_KIND
from app.workflow.nodes.base import BaseNode


class FakeRedisClient:
    def __init__(self):
        self.rows = []
        self.xread_blocks = []

    async def xadd(self, key, fields, maxlen=None, approximate=True):
        stream_id = f"{len(self.rows) + 1}-0"
        self.rows.append((stream_id, fields))
        return stream_id

    async def xrange(self, key, min="0-0", max="+", count=None):
        return self.rows[: count or None]

    async def xread(self, streams, block=15000, count=100):
        self.xread_blocks.append(block)
        return []


class FakeRedis:
    socket_timeout = 5

    def __init__(self):
        self.client = FakeRedisClient()
        self.expires = {}

    async def expire(self, key, seconds):
        self.expires[key] = seconds
        return True

    async def _retry_on_moved(self, coro_factory):
        return await coro_factory()


@pytest.mark.asyncio
async def test_trace_bus_publish_and_replay():
    redis = FakeRedis()
    bus = ExecutionTraceBus(redis, ttl_seconds=60, maxlen=10)

    stream_id = await bus.publish(
        "123",
        kind=TRACE_KIND,
        event_type="node.started",
        data={"hello": "world"},
    )

    assert stream_id == "1-0"
    assert redis.expires["trace:execution:123"] == 60

    rows = await bus.read("123", kinds=[TRACE_KIND])
    assert len(rows) == 1
    assert rows[0][0] == "1-0"
    assert rows[0][1]["event_type"] == "node.started"
    assert json.loads(rows[0][1]["data"]) == {"hello": "world"}


@pytest.mark.asyncio
async def test_trace_bus_listen_keeps_xread_block_below_socket_timeout():
    redis = FakeRedis()
    bus = ExecutionTraceBus(redis, ttl_seconds=60, maxlen=10)

    listener = bus.listen("123", kinds=[TRACE_KIND], block_ms=15000)
    try:
        stream_id, event = await anext(listener)
    finally:
        await listener.aclose()

    assert (stream_id, event) == (None, None)
    assert redis.client.xread_blocks == [4000]


@pytest.mark.asyncio
async def test_trace_bus_listen_treats_redis_timeout_as_keepalive():
    class TimeoutRedisClient(FakeRedisClient):
        async def xread(self, streams, block=15000, count=100):
            self.xread_blocks.append(block)
            raise RedisTimeoutError("Timeout reading from localhost:6379")

    redis = FakeRedis()
    redis.client = TimeoutRedisClient()
    bus = ExecutionTraceBus(redis, ttl_seconds=60, maxlen=10)

    listener = bus.listen("123", kinds=[TRACE_KIND], block_ms=15000)
    try:
        stream_id, event = await anext(listener)
    finally:
        await listener.aclose()

    assert (stream_id, event) == (None, None)
    assert redis.client.xread_blocks == [4000]


class ExampleNode(BaseNode):
    async def execute(self, state):
        return {"response": "ok"}


@pytest.mark.asyncio
async def test_base_node_emits_node_timing(monkeypatch):
    emitted = []

    async def fake_emit(event_type, **kwargs):
        emitted.append((event_type, kwargs))

    monkeypatch.setattr("app.workflow.nodes.base.emit_trace_event", fake_emit)

    node = ExampleNode(
        SimpleNamespace(
            id="agent_1",
            type="agent",
            config={"label": "Research Agent"},
        )
    )
    result = await node(
        {
            "metadata": {"execution_id": 42, "session_id": "s1"},
            "node_outputs": {},
        }
    )

    assert result["response"] == "ok"
    assert [e[0] for e in emitted] == ["node.started", "node.completed"]
    assert emitted[-1][1]["duration_ms"] >= 0


class FakeInnerModel:
    response_kwargs = {"reasoning_summary": [{"text": "checked the sources"}]}
    response_metadata = {}

    def __init__(self):
        self.bound_tools = None
        self.structured = False

    async def ainvoke(self, input, *args, **kwargs):
        return SimpleNamespace(
            content="answer",
            additional_kwargs=self.response_kwargs,
            response_metadata=self.response_metadata,
        )

    def bind_tools(self, tools, *args, **kwargs):
        clone = FakeInnerModel()
        clone.bound_tools = tools
        return clone

    def with_structured_output(self, *args, **kwargs):
        clone = FakeInnerModel()
        clone.structured = True
        return clone


class OpenAIReasoningShapeModel(FakeInnerModel):
    response_kwargs = {
        "reasoning": {
            "summary": [
                {"type": "summary_text", "text": "checked the evidence"},
            ],
        },
    }


class ReasoningBlockShapeModel(FakeInnerModel):
    response_kwargs = {
        "output": [
            {
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "planned the next action"},
                ],
            },
            {"type": "message", "content": [{"type": "output_text", "text": "answer"}]},
        ],
    }


class ContentReasoningBlockShapeModel(FakeInnerModel):
    response_kwargs = {}

    async def ainvoke(self, input, *args, **kwargs):
        return SimpleNamespace(
            content=[
                {
                    "type": "reasoning",
                    "summary": [
                        {"type": "summary_text", "text": "reviewed the context"},
                    ],
                },
                {"type": "text", "text": "answer"},
            ],
            additional_kwargs=self.response_kwargs,
            response_metadata=self.response_metadata,
        )


class RawReasoningContentModel(FakeInnerModel):
    response_kwargs = {"reasoning_content": "private chain of thought"}


class StreamingReasoningModel(FakeInnerModel):
    async def astream(self, input, *args, **kwargs):
        yield AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "summary": [
                        {"index": 0, "type": "summary_text", "text": "reviewed "},
                    ],
                    "index": 0,
                }
            ]
        )
        yield AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "summary": [
                        {"index": 0, "type": "summary_text", "text": "the context"},
                    ],
                    "index": 0,
                }
            ]
        )
        yield AIMessageChunk(content=[{"type": "text", "text": "answer", "index": 1}])


@pytest.mark.asyncio
async def test_traced_chat_model_preserves_methods_and_emits(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return f"{len(published)}-0"

    async def fake_get_trace_bus():
        return FakeBus()

    monkeypatch.setattr("app.tracing.trace_bus.get_trace_bus", fake_get_trace_bus)

    tokens = set_trace_context(
        execution_id="99",
        session_id="s1",
        node_id="agent_1",
        node_label="Agent",
        node_type="agent",
        span_id="node:agent_1",
    )
    try:
        model = TracedChatModel(FakeInnerModel(), model="openai.test")
        bound = model.bind_tools([SimpleNamespace(name="search_docs")])
        structured = bound.with_structured_output(schema={"title": "Out", "type": "object"})
        response = await structured.ainvoke([])
    finally:
        reset_trace_context(tokens)

    assert response.content == "answer"
    assert len(published) == 2
    assert published[0][2] == "llm.started"
    assert published[1][2] == "llm.completed"
    assert published[1][3]["payload"]["reasoning_summary"] == "checked the sources"
    assert published[1][3]["payload"]["schema"]["title"] == "Out"


@pytest.mark.asyncio
async def test_traced_chat_model_extracts_nested_reasoning_summary(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return f"{len(published)}-0"

    async def fake_get_trace_bus():
        return FakeBus()

    monkeypatch.setattr("app.tracing.trace_bus.get_trace_bus", fake_get_trace_bus)

    tokens = set_trace_context(execution_id="99", span_id="node:agent_1")
    try:
        model = TracedChatModel(OpenAIReasoningShapeModel(), model="openai.test")
        await model.ainvoke([])
    finally:
        reset_trace_context(tokens)

    assert published[-1][2] == "llm.completed"
    assert published[-1][3]["payload"]["reasoning_summary"] == "checked the evidence"


@pytest.mark.asyncio
async def test_traced_chat_model_extracts_reasoning_block_summary(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return f"{len(published)}-0"

    async def fake_get_trace_bus():
        return FakeBus()

    monkeypatch.setattr("app.tracing.trace_bus.get_trace_bus", fake_get_trace_bus)

    tokens = set_trace_context(execution_id="99", span_id="node:agent_1")
    try:
        model = TracedChatModel(ReasoningBlockShapeModel(), model="openai.test")
        await model.ainvoke([])
    finally:
        reset_trace_context(tokens)

    assert published[-1][2] == "llm.completed"
    assert published[-1][3]["payload"]["reasoning_summary"] == "planned the next action"


@pytest.mark.asyncio
async def test_traced_chat_model_extracts_content_reasoning_block_summary(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return f"{len(published)}-0"

    async def fake_get_trace_bus():
        return FakeBus()

    monkeypatch.setattr("app.tracing.trace_bus.get_trace_bus", fake_get_trace_bus)

    tokens = set_trace_context(execution_id="99", span_id="node:agent_1")
    try:
        model = TracedChatModel(ContentReasoningBlockShapeModel(), model="openai.test")
        response = await model.ainvoke([])
    finally:
        reset_trace_context(tokens)

    assert response.content == "answer"
    assert published[-1][2] == "llm.completed"
    assert published[-1][3]["payload"]["reasoning_summary"] == "reviewed the context"


@pytest.mark.asyncio
async def test_traced_chat_model_ignores_raw_reasoning_content(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return f"{len(published)}-0"

    async def fake_get_trace_bus():
        return FakeBus()

    monkeypatch.setattr("app.tracing.trace_bus.get_trace_bus", fake_get_trace_bus)

    tokens = set_trace_context(execution_id="99", span_id="node:agent_1")
    try:
        model = TracedChatModel(RawReasoningContentModel(), model="openai.test")
        await model.ainvoke([])
    finally:
        reset_trace_context(tokens)

    assert published[-1][2] == "llm.completed"
    assert "reasoning_summary" not in published[-1][3]["payload"]


@pytest.mark.asyncio
async def test_traced_chat_model_streams_reasoning_summary_and_chat_delta(monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, execution_id, *, kind, event_type, data):
            published.append((execution_id, kind, event_type, data))
            return f"{len(published)}-0"

    async def fake_get_trace_bus():
        return FakeBus()

    monkeypatch.setattr("app.tracing.trace_bus.get_trace_bus", fake_get_trace_bus)

    tokens = set_trace_context(execution_id="99", span_id="node:agent_1")
    try:
        model = TracedChatModel(
            StreamingReasoningModel(),
            model="openai.test",
            stream_trace=True,
            stream_chat=True,
        )
        response = await model.ainvoke([])
    finally:
        reset_trace_context(tokens)

    assert response.content == "answer"

    trace_events = [event for event in published if event[1] == TRACE_KIND]
    execution_events = [event for event in published if event[1] != TRACE_KIND]

    assert [event[2] for event in trace_events] == [
        "llm.started",
        "llm.reasoning_summary.delta",
        "llm.reasoning_summary.delta",
        "llm.completed",
    ]
    assert trace_events[-2][3]["payload"]["reasoning_summary"] == "reviewed the context"
    assert trace_events[-1][3]["payload"]["reasoning_summary"] == "reviewed the context"
    assert execution_events[0][2] == "chat.delta"
    assert execution_events[0][3]["delta"] == "answer"


@pytest.mark.asyncio
async def test_trace_stream_rejects_missing_token():
    with pytest.raises(HTTPException) as exc:
        await stream_execution_trace("123", token=None)

    assert exc.value.status_code == 401
