"""Redis-backed execution trace bus.

The bus stores both legacy execution-stream events and normalized trace
events in a per-execution Redis Stream. This lets any backend instance serve
SSE replay/live updates for a browser connected to a different instance than
the one running the workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Iterable, Optional, Tuple

from redis.exceptions import TimeoutError as RedisTimeoutError

from config.settings import settings
from db.redis import RedisConnector, get_redis

logger = logging.getLogger(__name__)

TRACE_KIND = "trace"
EXECUTION_KIND = "execution"


def _stream_key(execution_id: str | int) -> str:
    return f"trace:execution:{execution_id}"


class ExecutionTraceBus:
    """Small Redis Streams facade for execution trace events."""

    def __init__(
        self,
        redis: RedisConnector,
        *,
        ttl_seconds: Optional[int] = None,
        maxlen: Optional[int] = None,
    ):
        self.redis = redis
        self.ttl_seconds = ttl_seconds or settings.TRACE_STREAM_TTL_SECONDS
        self.maxlen = maxlen or settings.TRACE_STREAM_MAXLEN

    async def publish(
        self,
        execution_id: str | int,
        *,
        kind: str,
        event_type: str,
        data: Dict[str, Any] | str,
    ) -> Optional[str]:
        """Publish an event and return its Redis stream id."""
        key = _stream_key(execution_id)
        payload = data if isinstance(data, str) else json.dumps(data, default=str)
        fields = {
            "kind": kind,
            "event_type": event_type,
            "data": payload,
        }

        async def _xadd():
            return await self.redis.client.xadd(
                key,
                fields,
                maxlen=self.maxlen,
                approximate=True,
            )

        stream_id = await self.redis._retry_on_moved(_xadd)
        await self.redis.expire(key, self.ttl_seconds)
        return str(stream_id)

    async def read(
        self,
        execution_id: str | int,
        *,
        kinds: Iterable[str],
        last_id: str = "0-0",
        count: int = 200,
    ) -> list[Tuple[str, Dict[str, Any]]]:
        """Read existing events after ``last_id``."""
        key = _stream_key(execution_id)
        kinds_set = set(kinds)
        try:
            rows = await self.redis.client.xrange(key, min=last_id, max="+", count=count)
        except Exception:
            logger.debug("Trace stream %s not readable yet", key, exc_info=True)
            return []

        events: list[Tuple[str, Dict[str, Any]]] = []
        for raw_id, raw_fields in rows:
            stream_id = _decode(raw_id)
            if stream_id == last_id:
                continue
            event = self._decode_fields(raw_fields)
            if event and event.get("kind") in kinds_set:
                events.append((stream_id, event))
        return events

    async def listen(
        self,
        execution_id: str | int,
        *,
        kinds: Iterable[str],
        last_id: str = "0-0",
        block_ms: int = 15000,
    ) -> AsyncGenerator[Tuple[Optional[str], Optional[Dict[str, Any]]], None]:
        """Yield replayed and live events.

        ``(None, None)`` is yielded as a keepalive when no event arrives within
        ``block_ms``.
        """
        key = _stream_key(execution_id)
        kinds_set = set(kinds)
        current_id = last_id or "0-0"
        effective_block_ms = _socket_safe_block_ms(self.redis, block_ms)

        # Replay first so reconnects recover missed events.
        for stream_id, event in await self.read(
            execution_id, kinds=kinds_set, last_id=current_id, count=self.maxlen
        ):
            current_id = stream_id
            yield stream_id, event

        while True:
            try:
                async def _xread():
                    return await self.redis.client.xread(
                        {key: current_id},
                        block=effective_block_ms,
                        count=100,
                    )

                result = await self.redis._retry_on_moved(_xread)
            except asyncio.CancelledError:
                raise
            except RedisTimeoutError:
                logger.debug("Trace stream xread timed out for %s", key, exc_info=True)
                yield None, None
                continue
            except Exception:
                logger.warning("Trace stream xread failed for %s", key, exc_info=True)
                yield None, None
                continue

            if not result:
                yield None, None
                continue

            for _, rows in result:
                for raw_id, raw_fields in rows:
                    stream_id = _decode(raw_id)
                    current_id = stream_id
                    event = self._decode_fields(raw_fields)
                    if event and event.get("kind") in kinds_set:
                        yield stream_id, event

    @staticmethod
    def _decode_fields(raw_fields: Dict[Any, Any]) -> Optional[Dict[str, Any]]:
        fields = {_decode(k): _decode(v) for k, v in raw_fields.items()}
        kind = fields.get("kind")
        event_type = fields.get("event_type")
        data = fields.get("data")
        if not kind or not event_type:
            return None
        return {
            "kind": kind,
            "event_type": event_type,
            "data": data or "{}",
        }


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _socket_safe_block_ms(redis: RedisConnector, requested_ms: int) -> int:
    """Keep Redis blocking reads below the client's socket read timeout."""
    socket_timeout = getattr(redis, "socket_timeout", None)
    if socket_timeout is None:
        return requested_ms

    try:
        socket_timeout_ms = int(float(socket_timeout) * 1000)
    except (TypeError, ValueError):
        return requested_ms

    if socket_timeout_ms <= 0:
        return requested_ms

    safe_block_ms = max(100, int(socket_timeout_ms * 0.8))
    if requested_ms <= 0:
        return safe_block_ms
    return min(requested_ms, safe_block_ms)


async def get_trace_bus() -> ExecutionTraceBus:
    """Return a bus backed by the app's global Redis connection."""
    redis = await get_redis()
    return ExecutionTraceBus(redis)
