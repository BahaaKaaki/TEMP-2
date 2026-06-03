"""
Apply provider prompt-cache hints to LangChain messages before proxy invocation.

All LLM traffic goes through TracedChatModel, which calls prepare_messages_for_cache()
here so caching is configured in one place (no env flags).

- OpenAI (openai.*): automatic prefix caching; we add a stable prompt_cache_key.
- Anthropic / Bedrock (bedrock.anthropic.*, anthropic.*): cache_control on long
  system prompts (required by Bedrock; verified via GenAI proxy).
- Google / Vertex (vertex_ai.*, google.*, gemini): same cache_control shape works
  on the OpenAI-compatible proxy.

Uses a fast char-based token estimate (no tiktoken) to avoid blocking the event loop.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import BaseMessage, SystemMessage

_CACHE_CONTROL = {"type": "ephemeral"}
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _model_family(model: str) -> str:
    name = (model or "").lower()
    if name.startswith("openai.") or name.startswith("gpt-"):
        return "openai"
    if name.startswith("bedrock.") or name.startswith("anthropic.") or "claude" in name:
        return "anthropic"
    if name.startswith("vertex_ai.") or name.startswith("google.") or "gemini" in name:
        return "google"
    return "other"


def _min_cache_tokens(model: str) -> int:
    """Provider minimum prefix size for cache breakpoints (conservative)."""
    if "haiku" in (model or "").lower():
        return 4096
    return 1024


def _is_system_message(message: BaseMessage) -> bool:
    if isinstance(message, SystemMessage):
        return True
    role = getattr(message, "type", None) or getattr(message, "role", None)
    return role in ("system", "developer")


def _copy_message(message: BaseMessage, content: Any) -> BaseMessage:
    if hasattr(message, "model_copy"):
        return message.model_copy(update={"content": content})
    return type(message)(content=content, additional_kwargs=getattr(message, "additional_kwargs", None) or {})


def _content_has_cache_control(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, dict) and block.get("cache_control"):
            return True
    return False


def _wrap_text_with_cache_control(text: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": text, "cache_control": dict(_CACHE_CONTROL)}]


def _cache_message_content(message: BaseMessage, min_tokens: int) -> BaseMessage:
    content = getattr(message, "content", None)
    if _content_has_cache_control(content):
        return message
    if isinstance(content, str):
        if _estimate_tokens(content) < min_tokens:
            return message
        return _copy_message(message, _wrap_text_with_cache_control(content))
    return message


def _first_system_text(messages: List[BaseMessage]) -> str:
    for message in messages:
        if not _is_system_message(message):
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
    return ""


def _openai_prompt_cache_key(model: str, messages: List[BaseMessage]) -> Optional[str]:
    system_text = _first_system_text(messages)
    if not system_text or _estimate_tokens(system_text) < 1024:
        return None
    digest = hashlib.sha256(f"{model}\n{system_text[:16384]}".encode()).hexdigest()[:20]
    return f"as-{digest}"


def prepare_messages_for_cache(
    messages: List[BaseMessage],
    model: str,
) -> Tuple[List[BaseMessage], Dict[str, Any]]:
    """
    Return (messages, extra invoke kwargs) with prompt-cache configuration applied.

    Idempotent for messages that already include cache_control.
    """
    if not messages:
        return messages, {}

    family = _model_family(model)
    if family == "openai":
        key = _openai_prompt_cache_key(model, messages)
        return messages, ({"prompt_cache_key": key} if key else {})

    if family not in ("anthropic", "google"):
        return messages, {}

    min_tokens = _min_cache_tokens(model)
    out: List[BaseMessage] = []
    cached_system = False
    for message in messages:
        if _is_system_message(message) and not cached_system:
            cached = _cache_message_content(message, min_tokens)
            if cached is not message:
                cached_system = True
            out.append(cached)
        else:
            out.append(message)
    return out, {}
