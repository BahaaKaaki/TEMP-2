"""Helpers for deciding when assistant text streams to the chat UI."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Tool Caller / agent actions whose UI payloads must appear in one shot.
ONE_SHOT_UI_ACTIONS = frozenset({"ask_user_questions", "submit_deliverable"})


def should_stream_chat_responses(
    *,
    node_config: Optional[Dict[str, Any]] = None,
    node_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True when LLM user-facing text should emit ``chat.delta`` SSE events.

    Used for conversational turns shown in the chat UI. Call sites that produce
    structured deliverables, tool-routing, or other non-chat output should keep
    ``stream_chat=False`` (the default on ``LLMClientManager.get_client``).
    """
    cfg = node_config or {}
    meta = metadata or {}
    return (
        cfg.get("agentMode") == "chat"
        or node_type == "chat"
        or bool(meta.get("session_id"))
    )


def classify_chat_stream_release(
    action_type: str,
    *,
    agent_mode: str = "regular",
) -> str:
    """Whether the next step will stream chat tokens to the UI.

    Returns ``"flush"`` when the Main LLM will run for a chat reply,
    ``"clear"`` for tools, questionnaires, and deliverables.
    """
    if action_type in ONE_SHOT_UI_ACTIONS:
        return "clear"
    if action_type == "submit_deliverable":
        if agent_mode == "chat":
            return "flush"
        return "clear"
    if action_type == "chat":
        return "flush"
    return "clear"
