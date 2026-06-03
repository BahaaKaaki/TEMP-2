"""LangChain runnable wrappers that emit trace spans."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, Iterable, Optional

from langchain_core.messages import message_chunk_to_message

from app.llm.langfuse_emit import record_llm_generation
from app.llm.prompt_cache import prepare_messages_for_cache

from .context import TraceSpan, emit_trace_event, get_trace_context

logger = logging.getLogger(__name__)


class TracedChatModel:
    """Transparent wrapper around a LangChain chat model/runnable.

    It traces ``ainvoke`` and preserves wrapper behavior through
    ``bind_tools`` and ``with_structured_output``.
    """

    def __init__(
        self,
        inner: Any,
        *,
        model: str,
        operation: str = "llm",
        stream_trace: bool = False,
        stream_chat: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        binding_key: Optional[str] = None,
        llm_role: Optional[str] = None,
    ):
        self._inner = inner
        self._trace_model = model
        self._trace_operation = operation
        self._stream_trace = stream_trace
        self._stream_chat = stream_chat
        self._trace_metadata = metadata or {}
        self._binding_key = binding_key
        self._llm_role = llm_role

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _prepare_invoke(self, input: Any, kwargs: Dict[str, Any]) -> tuple[Any, Dict[str, Any]]:
        """Apply centralized prompt-cache message shaping and invoke kwargs."""
        if not isinstance(input, list):
            return input, kwargs
        messages, cache_kwargs = prepare_messages_for_cache(input, self._trace_model)
        merged = {**cache_kwargs, **kwargs}
        return messages, merged

    async def _record_langfuse_completion(self, input_value: Any, response: Any) -> Any:
        async def _return_response() -> Any:
            return response

        return await record_llm_generation(
            model=self._trace_model,
            operation=self._trace_operation,
            input_summary=_summarize_input(input_value),
            invoke=_return_response,
            binding_key=self._binding_key,
            llm_role=self._llm_role,
        )

    async def ainvoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
        input, kwargs = self._prepare_invoke(input, dict(kwargs))
        if self._stream_trace and hasattr(self._inner, "astream"):
            final_chunk = None
            async for chunk in self.astream(input, *args, **kwargs):
                final_chunk = _merge_chunks(final_chunk, chunk)

            if final_chunk is None:
                return await self._inner.ainvoke(input, *args, **kwargs)

            response = message_chunk_to_message(final_chunk)
            _normalize_response_content(response)
            return await self._record_langfuse_completion(input, response)

        payload = {
            "operation": self._trace_operation,
            "model": self._trace_model,
            **self._trace_metadata,
            **_summarize_input(input),
        }
        async with TraceSpan("llm", label=self._trace_operation, payload=payload) as span:
            async def _invoke() -> Any:
                response = await self._inner.ainvoke(input, *args, **kwargs)
                summary = _extract_reasoning_summary(response)
                if summary:
                    span.add_payload(reasoning_summary=summary)
                _normalize_response_content(response)
                span.add_payload(**_summarize_response(response))
                return response

            return await record_llm_generation(
                model=self._trace_model,
                operation=self._trace_operation,
                input_summary=_summarize_input(input),
                invoke=_invoke,
                binding_key=self._binding_key,
                llm_role=self._llm_role,
            )

    async def astream(self, input: Any, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        input, kwargs = self._prepare_invoke(input, dict(kwargs))
        payload = {
            "operation": self._trace_operation,
            "model": self._trace_model,
            **self._trace_metadata,
            **_summarize_input(input),
        }
        async with TraceSpan("llm", label=self._trace_operation, payload=payload) as span:
            final_chunk = None
            reasoning_summary = ""
            output_text_chars = 0

            async for chunk in self._inner.astream(input, *args, **kwargs):
                final_chunk = _merge_chunks(final_chunk, chunk)

                text_delta = _extract_response_text(getattr(chunk, "content", None))
                if text_delta:
                    output_text_chars += len(text_delta)
                    await _publish_chat_delta(
                        text_delta,
                        span_id=span.span_id,
                        enabled=self._stream_chat,
                    )

                summary_delta = _extract_reasoning_summary(chunk, preserve_whitespace=True)
                if summary_delta:
                    reasoning_summary += summary_delta
                    span.add_payload(reasoning_summary=reasoning_summary)
                    await emit_trace_event(
                        "llm.reasoning_summary.delta",
                        status="running",
                        payload={
                            "reasoning_summary": reasoning_summary,
                            "reasoning_summary_delta_chars": len(summary_delta),
                        },
                        span_id=span.span_id,
                        parent_span_id=span.parent_span_id,
                    )

                yield chunk

            if final_chunk is not None:
                response = message_chunk_to_message(final_chunk)
                summary = _extract_reasoning_summary(response)
                if summary:
                    span.add_payload(reasoning_summary=summary)
                _normalize_response_content(response)
                span.add_payload(
                    output_text_chars=output_text_chars,
                    **_summarize_response(response),
                )
                await self._record_langfuse_completion(input, response)

    def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
        # Keep sync call behavior untouched. The workflow uses async LLM calls;
        # avoiding an event-loop bridge here prevents surprises in sync callers.
        return self._inner.invoke(input, *args, **kwargs)

    def bind_tools(self, tools: Iterable[Any], *args: Any, **kwargs: Any) -> "TracedChatModel":
        tool_names = [getattr(t, "name", str(t)) for t in (tools or [])]
        bound = self._inner.bind_tools(tools, *args, **kwargs)
        return TracedChatModel(
            bound,
            model=self._trace_model,
            operation="llm.tool_calling",
            stream_trace=self._stream_trace,
            stream_chat=self._stream_chat,
            metadata={**self._trace_metadata, "tools": tool_names},
            binding_key=self._binding_key,
            llm_role=self._llm_role or "tool_calling",
        )

    def with_structured_output(self, *args: Any, **kwargs: Any) -> "TracedChatModel":
        schema = kwargs.get("schema") or (args[0] if args else None)
        structured = self._inner.with_structured_output(*args, **kwargs)
        return TracedChatModel(
            structured,
            model=self._trace_model,
            operation="llm.structured_output",
            stream_trace=False,
            stream_chat=False,
            metadata={**self._trace_metadata, "schema": _summarize_schema(schema)},
            binding_key=self._binding_key,
            llm_role=self._llm_role or "structured_output",
        )


def _merge_chunks(current: Any, chunk: Any) -> Any:
    if current is None:
        return chunk
    try:
        return current + chunk
    except Exception:
        return chunk


async def _publish_chat_delta(delta: str, *, span_id: str, enabled: bool) -> None:
    if not enabled:
        return

    try:
        from .chat_stream import buffer_chat_delta, is_chat_stream_deferred

        if is_chat_stream_deferred():
            buffer_chat_delta(delta, span_id)
            return
    except Exception:
        logger.debug("Chat stream defer check failed", exc_info=True)

    context = get_trace_context()
    execution_id = context.get("execution_id")
    if not execution_id:
        return

    data = {
        "delta": delta,
        "span_id": span_id,
        "node_id": context.get("node_id"),
        "node_label": context.get("node_label"),
        "node_type": context.get("node_type"),
    }

    try:
        from .trace_bus import EXECUTION_KIND, get_trace_bus

        bus = await get_trace_bus()
        await bus.publish(
            execution_id,
            kind=EXECUTION_KIND,
            event_type="chat.delta",
            data=data,
        )
    except Exception:
        try:
            from app.routers.sse_routes import push_execution_event

            await push_execution_event(execution_id, "chat.delta", data)
        except Exception:
            logger.debug("Chat delta stream event dropped", exc_info=True)


def _summarize_input(input_value: Any) -> Dict[str, Any]:
    if isinstance(input_value, list):
        return {
            "message_count": len(input_value),
            "message_types": [type(m).__name__ for m in input_value[-6:]],
            "message_preview": [_summarize_message(m) for m in input_value[-6:]],
        }
    return {"input_type": type(input_value).__name__}


def _summarize_message(message: Any) -> Dict[str, Any]:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        text_parts = []
        for block in content[:8]:
            if isinstance(block, dict):
                text_parts.append(str(block.get("text") or block.get("content") or block.get("type") or block))
            else:
                text_parts.append(str(block))
        content_text = "\n".join(text_parts)
    else:
        content_text = str(content or "")

    content_text = content_text.strip()
    if len(content_text) > 900:
        content_text = content_text[:900] + "... [truncated]"

    return {
        "type": type(message).__name__,
        "content": content_text,
    }


def _summarize_response(response: Any) -> Dict[str, Any]:
    if isinstance(response, dict) and "raw" in response:
        return {
            "response_type": "structured",
            "parsed": response.get("parsed") is not None,
            "parsing_error": bool(response.get("parsing_error")),
        }
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return {"response_type": type(response).__name__, "content_chars": len(content)}
    if isinstance(content, list):
        return {"response_type": type(response).__name__, "content_blocks": len(content)}
    return {"response_type": type(response).__name__}


def _normalize_response_content(response: Any) -> None:
    """Keep downstream workflow code on string-shaped AIMessage content.

    The Responses API can return content as blocks (reasoning, text, tool
    calls). The workflow code was written for chat-completion style strings, so
    we preserve trace extraction from the blocks and then collapse display text
    back to a plain string for the caller.
    """
    candidates = []
    if isinstance(response, dict):
        raw = response.get("raw")
        if raw is not None:
            candidates.append(raw)
    else:
        candidates.append(response)

    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if isinstance(content, list):
            text = _extract_response_text(content)
            if text or hasattr(candidate, "tool_calls"):
                try:
                    setattr(candidate, "content", text)
                except Exception:
                    pass


def _extract_response_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_response_text(item) for item in value)
    if isinstance(value, dict):
        block_type = str(value.get("type") or "").lower()
        if "reasoning" in block_type:
            return ""
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), str):
            return value["content"]
        if isinstance(value.get("content"), list):
            return _extract_response_text(value["content"])
    return ""


def _summarize_schema(schema: Any) -> Dict[str, Any]:
    if isinstance(schema, dict):
        return {
            "title": schema.get("title"),
            "type": schema.get("type"),
            "properties": list((schema.get("properties") or {}).keys())[:20],
        }
    return {"type": type(schema).__name__}


def _extract_reasoning_summary(
    response: Any,
    *,
    preserve_whitespace: bool = False,
) -> Optional[str]:
    """Extract provider-supported reasoning summaries only.

    Hidden/raw chain-of-thought fields are intentionally ignored unless the
    provider labels them as summaries.
    """
    candidates = []
    if isinstance(response, dict):
        raw = response.get("raw")
        if raw is not None:
            candidates.append(raw)
        candidates.append(response)
    else:
        candidates.append(response)

    for candidate in candidates:
        summary = _find_summary(candidate, preserve_whitespace=preserve_whitespace)
        if summary:
            return summary
    return None


def _find_summary(
    value: Any,
    depth: int = 0,
    *,
    in_reasoning: bool = False,
    preserve_whitespace: bool = False,
) -> Optional[str]:
    if depth > 5 or value is None:
        return None
    if hasattr(value, "additional_kwargs"):
        found = _find_summary(
            getattr(value, "additional_kwargs"),
            depth + 1,
            preserve_whitespace=preserve_whitespace,
        )
        if found:
            return found
    if hasattr(value, "response_metadata"):
        found = _find_summary(
            getattr(value, "response_metadata"),
            depth + 1,
            preserve_whitespace=preserve_whitespace,
        )
        if found:
            return found
    if hasattr(value, "content") and not isinstance(value, (dict, list, str)):
        found = _find_summary(
            getattr(value, "content"),
            depth + 1,
            in_reasoning=in_reasoning,
            preserve_whitespace=preserve_whitespace,
        )
        if found:
            return found
    if hasattr(value, "model_dump"):
        try:
            found = _find_summary(
                value.model_dump(),
                depth + 1,
                in_reasoning=in_reasoning,
                preserve_whitespace=preserve_whitespace,
            )
            if found:
                return found
        except Exception:
            pass
    if isinstance(value, dict):
        block_type = str(value.get("type") or "").lower()
        is_reasoning_block = in_reasoning or "reasoning" in block_type

        if is_reasoning_block:
            for key in ("summary", "summaries"):
                text = _extract_text(
                    value.get(key),
                    preserve_whitespace=preserve_whitespace,
                )
                if text:
                    return text

        for key, item in value.items():
            lower = str(key).lower()
            if "reasoning" in lower and "summary" in lower:
                text = _extract_text(
                    item,
                    preserve_whitespace=preserve_whitespace,
                )
                if text:
                    return text
            found = _find_summary(
                item,
                depth + 1,
                in_reasoning=is_reasoning_block or lower == "reasoning",
                preserve_whitespace=preserve_whitespace,
            )
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_summary(
                item,
                depth + 1,
                in_reasoning=in_reasoning,
                preserve_whitespace=preserve_whitespace,
            )
            if found:
                return found
    return None


def _extract_text(value: Any, *, preserve_whitespace: bool = False) -> str:
    if isinstance(value, str):
        return value if preserve_whitespace else value.strip()
    if isinstance(value, dict):
        for key in ("text", "summary", "content"):
            if isinstance(value.get(key), str):
                return value[key] if preserve_whitespace else value[key].strip()
        text = " ".join(
            filter(
                None,
                (
                    _extract_text(v, preserve_whitespace=preserve_whitespace)
                    for k, v in value.items()
                    if str(k).lower() not in {"id", "index", "signature", "type"}
                ),
            )
        )
        return text if preserve_whitespace else text.strip()
    if isinstance(value, list):
        text = " ".join(
            filter(
                None,
                (
                    _extract_text(v, preserve_whitespace=preserve_whitespace)
                    for v in value
                ),
            )
        )
        return text if preserve_whitespace else text.strip()
    text = getattr(value, "text", None)
    if not isinstance(text, str):
        return ""
    return text if preserve_whitespace else text.strip()
