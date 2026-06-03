"""
Server-Sent Events (SSE) for real-time code execution streaming.

Provides a ``GET /api/executions/{execution_id}/stream`` endpoint that
yields ``text/event-stream`` events so the frontend can display live
stdout/stderr, execution phase transitions, and deliverable updates
without polling.
"""

import json
import logging
import time
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Header, Query, HTTPException, status
from fastapi.responses import StreamingResponse
import asyncio

from app.tracing.trace_bus import EXECUTION_KIND, TRACE_KIND, get_trace_bus

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/executions",
    tags=["Execution Streaming"],
)

_streams: dict[str, "ExecutionStream"] = {}


class ExecutionStream:
    """In-memory event bus for a single execution.

    The ``CodeExecutorNode`` (or sandbox wrapper) pushes events; the SSE
    endpoint consumes them via ``listen()``.
    """

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)
        self._closed = False
        self._created_at = time.monotonic()

    async def push(self, event_type: str, data: dict | str) -> None:
        if self._closed:
            return
        payload = data if isinstance(data, str) else json.dumps(data, default=str)
        try:
            self._queue.put_nowait({"event": event_type, "data": payload})
        except asyncio.QueueFull:
            logger.warning("SSE queue full for execution %s, dropping event", self.execution_id)

    async def listen(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings until the stream is closed."""
        while not self._closed:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=15)
                yield f"event: {msg['event']}\ndata: {msg['data']}\n\n"

                if msg["event"] in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    def close(self) -> None:
        self._closed = True


def get_or_create_stream(execution_id: str) -> ExecutionStream:
    """Get or create an execution stream (called by the workflow engine)."""
    if execution_id not in _streams:
        _streams[execution_id] = ExecutionStream(execution_id)
    return _streams[execution_id]


def remove_stream(execution_id: str) -> None:
    """Clean up a stream after the execution is done."""
    stream = _streams.pop(execution_id, None)
    if stream:
        stream.close()


async def push_execution_event(execution_id: str, event_type: str, data: dict | str) -> None:
    """Convenience function for pushing events from anywhere in the backend."""
    try:
        bus = await get_trace_bus()
        await bus.publish(
            execution_id,
            kind=EXECUTION_KIND,
            event_type=event_type,
            data=data,
        )
        return
    except Exception:
        logger.debug(
            "Redis execution stream unavailable for %s; using in-memory fallback",
            execution_id,
            exc_info=True,
        )

    stream = _streams.get(execution_id)
    if stream:
        await stream.push(event_type, data)


@router.get("/{execution_id}/stream", response_model=None)
async def stream_execution(
    execution_id: str,
    token: Optional[str] = Query(None),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    last_id: Optional[str] = Query(None),
):
    """SSE endpoint for real-time execution updates.

    Accepts auth via ``?token=<access_token>`` query parameter
    (EventSource cannot set Authorization headers).

    Event types:
      - ``status``: phase transitions (validating, creating_sandbox, running, etc.)
      - ``stdout``: incremental stdout lines
      - ``stderr``: incremental stderr lines
      - ``progress``: progress updates (from ``output.progress()`` in the SDK)
      - ``deliverable``: final deliverable payload
      - ``complete``: execution finished successfully
      - ``error``: execution failed
    """
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    from utils.security import verify_token as _verify
    try:
        _verify(token, token_type="access")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    start_id = last_id or last_event_id or "0-0"

    async def _redis_events(bus) -> AsyncGenerator[str, None]:
        async for stream_id, event in bus.listen(
            execution_id,
            kinds=[EXECUTION_KIND],
            last_id=start_id,
        ):
            if event is None:
                yield ": keepalive\n\n"
                continue
            data = event["data"]
            yield (
                f"id: {stream_id}\n"
                f"event: {event['event_type']}\n"
                f"data: {data}\n\n"
            )

    try:
        bus = await get_trace_bus()
        iterator = _redis_events(bus)
    except Exception:
        stream = get_or_create_stream(execution_id)
        iterator = stream.listen()

    return StreamingResponse(
        iterator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{execution_id}/trace/stream", response_model=None)
async def stream_execution_trace(
    execution_id: str,
    token: Optional[str] = Query(None),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    last_id: Optional[str] = Query(None),
):
    """SSE endpoint for the real-time agent Trace panel."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    from utils.security import verify_token as _verify
    try:
        _verify(token, token_type="access")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    start_id = last_id or last_event_id or "0-0"

    try:
        bus = await get_trace_bus()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trace streaming is unavailable",
        )

    async def _trace_events() -> AsyncGenerator[str, None]:
        async for stream_id, event in bus.listen(
            execution_id,
            kinds=[TRACE_KIND],
            last_id=start_id,
        ):
            if event is None:
                yield ": keepalive\n\n"
                continue
            yield (
                f"id: {stream_id}\n"
                "event: trace\n"
                f"data: {event['data']}\n\n"
            )

    return StreamingResponse(
        _trace_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
