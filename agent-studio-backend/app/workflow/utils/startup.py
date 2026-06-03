"""Shared helpers for agent / code-executor startup messages.

Universal rule (any graph position, any upstream node type):
  - Empty startup on an agent or code-executor → do **not** pause for startup
    (``should_wait_for_startup`` is False). The node runs as soon as the
    workflow reaches it.
  - Non-empty startup → show greeting and pause until the user responds.

Session creation is separate: ``should_auto_start_on_session_open`` only decides
whether to launch the workflow before the first chat message (when the first
executable after chat/start has no startup to show).
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Tuple

EXECUTABLE_DOWNSTREAM_TYPES = frozenset({"agent", "code-executor"})
INITIATOR_PASS_THROUGH_TYPES = frozenset({"start", "chat"})


def _normalize_questions(config: dict) -> Optional[dict]:
    from app.workflow.tools.ask_user_questions import normalize_questions_payload

    raw = config.get("startupQuestions")
    if not raw:
        return None
    return normalize_questions_payload(raw)


def get_startup_message_text(config: dict) -> str:
    """Plain startup message text after applying startupType rules."""
    startup_type = config.get("startupType")
    startup_message = (config.get("startupMessage") or "").strip()
    questions_payload = _normalize_questions(config)

    if startup_type == "message":
        return startup_message
    if startup_type == "questions":
        return ""
    # Legacy: use whichever side has data
    if startup_message:
        return startup_message
    if questions_payload:
        return ""
    return startup_message


def get_startup_questions_payload(config: dict) -> Optional[dict]:
    """Questionnaire payload after applying startupType rules."""
    startup_type = config.get("startupType")
    startup_message = (config.get("startupMessage") or "").strip()
    questions_payload = _normalize_questions(config)

    if startup_type == "message":
        return None
    if startup_type == "questions":
        return questions_payload
    if startup_message:
        return None
    return questions_payload


def has_startup_content(config: dict) -> bool:
    """True when the node has a non-empty startup message or questionnaire."""
    return bool(get_startup_message_text(config)) or bool(get_startup_questions_payload(config))


def should_wait_for_startup(config: dict) -> bool:
    """Whether this node must pause for startup before doing its work.

    Applies whenever the node runs — after chat, another agent, HITL, a
    code-executor, a condition branch, etc. Empty startup never waits.
    """
    if not has_startup_content(config):
        return False
    if "waitForUserInput" in config:
        return bool(config.get("waitForUserInput"))
    return True


def get_first_executable_after_node(
    workflow: Any,
    source_node_id: str,
    *,
    pass_through_types: FrozenSet[str] = INITIATOR_PASS_THROUGH_TYPES,
) -> Optional[dict]:
    """Walk outgoing edges from ``source_node_id`` to the next runnable node.

    Skips node types in ``pass_through_types`` (chat/start by default).
    Stops at the first agent or code-executor, or returns ``None`` if a
    condition, HITL, branches node, etc. is encountered first.
    """
    nodes = workflow.get_nodes_list()
    edges = workflow.get_edges_list()
    if not nodes or not source_node_id:
        return None

    node_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    outgoing: Dict[str, List[str]] = {}
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt:
            outgoing.setdefault(src, []).append(tgt)

    current = node_by_id.get(source_node_id)
    if not current:
        return None

    visited: set = set()
    while current:
        node_id = current.get("id")
        if not node_id or node_id in visited:
            return None
        visited.add(node_id)

        node_type = current.get("type")
        if node_type in pass_through_types:
            next_ids = outgoing.get(node_id, [])
            if not next_ids:
                return None
            current = node_by_id.get(next_ids[0])
            continue

        if node_type in EXECUTABLE_DOWNSTREAM_TYPES:
            return current
        return None

    return None


def get_first_downstream_executable(
    workflow: Any,
    start_node_id: str,
) -> Optional[dict]:
    """First agent / code-executor on a direct or pass-through path from a node."""
    return get_first_executable_after_node(
        workflow,
        start_node_id,
        pass_through_types=INITIATOR_PASS_THROUGH_TYPES,
    )


def build_startup_display_and_llm_content(
    config: dict,
) -> Tuple[str, str, Optional[dict]]:
    """Build (display_text, llm_content, questions_payload) for chat injection."""
    from app.workflow.tools.ask_user_questions import render_questions_for_llm

    startup_message = get_startup_message_text(config)
    questions_payload = get_startup_questions_payload(config)
    display_text = startup_message or ""

    if questions_payload:
        intro_text = (questions_payload.get("intro") or "").strip()
        rendered = render_questions_for_llm(questions_payload, "")
        llm_parts = [p for p in (display_text, intro_text, rendered) if p]
        llm_content = "\n\n".join(llm_parts)
    else:
        llm_content = display_text

    return display_text, llm_content, questions_payload


def resolve_session_open_content(workflow: Any) -> Optional[Dict[str, Any]]:
    """Resolve greeting shown when a chat session opens (before first user message).

    Priority:
    1. Legacy chat ``initialMessage`` / ``initialQuestions``
    2. First downstream agent / code-executor ``startupMessage`` / ``startupQuestions``
    """
    from app.workflow.tools.ask_user_questions import (
        normalize_questions_payload,
        render_questions_for_llm,
    )

    start_node = workflow.get_start_node()
    if not start_node:
        return None

    start_id = start_node.get("id")
    start_cfg = start_node.get("config", {}) or {}

    display_text = ""
    llm_content = ""
    questions_payload = None
    agent_id = None
    agent_label = None
    agent_type = None

    if legacy_chat_has_initial_content(start_cfg):
        initial_message_text = (start_cfg.get("initialMessage") or "").strip()
        questions_payload = normalize_questions_payload(start_cfg.get("initialQuestions"))
        initial_type = start_cfg.get("initialType")
        if initial_type == "message":
            questions_payload = None
        elif initial_type == "questions":
            initial_message_text = ""
        display_text = initial_message_text or ""
        if questions_payload:
            intro_text = (questions_payload.get("intro") or "").strip()
            rendered = render_questions_for_llm(questions_payload, "")
            llm_parts = [p for p in (display_text, intro_text, rendered) if p]
            llm_content = "\n\n".join(llm_parts)
        else:
            llm_content = display_text
    else:
        downstream = get_first_downstream_executable(workflow, start_id) if start_id else None
        if not downstream:
            return None
        downstream_cfg = downstream.get("config", {}) or {}
        if not has_startup_content(downstream_cfg):
            return None
        display_text, llm_content, questions_payload = build_startup_display_and_llm_content(
            downstream_cfg
        )
        agent_id = downstream.get("id")
        agent_label = downstream_cfg.get("label") or downstream.get("type")
        agent_type = downstream.get("type")

    if not display_text and not questions_payload and not llm_content:
        return None

    if not agent_id and start_id:
        downstream = get_first_downstream_executable(workflow, start_id)
        if downstream:
            downstream_cfg = downstream.get("config", {}) or {}
            agent_id = downstream.get("id")
            agent_label = downstream_cfg.get("label") or downstream.get("type")
            agent_type = downstream.get("type")

    return {
        "display_text": display_text,
        "llm_content": llm_content,
        "questions_payload": questions_payload,
        "agent_id": agent_id,
        "agent_label": agent_label,
        "agent_type": agent_type,
    }


def _node_config(node: dict) -> dict:
    """Extract builder config from a workflow node dict."""
    data = node.get("data") or {}
    return data.get("config") or node.get("config") or {}


def get_entry_chain_first_executable(workflow: Any) -> Optional[dict]:
    """First agent / code-executor reachable from the workflow entry (chat/start)."""
    start_node = None
    if hasattr(workflow, "get_start_node"):
        start_node = workflow.get_start_node()

    if start_node and start_node.get("id"):
        found = get_first_executable_after_node(
            workflow,
            start_node["id"],
            pass_through_types=INITIATOR_PASS_THROUGH_TYPES,
        )
        if found:
            return found

    nodes = workflow.get_nodes_list()
    edges = workflow.get_edges_list()
    if not nodes:
        return None

    incoming_ids = {e.get("target") for e in edges if e.get("target")}
    entries = [n for n in nodes if n.get("id") and n.get("id") not in incoming_ids]
    for entry in entries:
        found = get_first_executable_after_node(
            workflow,
            entry.get("id"),
            pass_through_types=INITIATOR_PASS_THROUGH_TYPES,
        )
        if found:
            return found
    return None


def should_auto_start_on_session_open(workflow: Any) -> bool:
    """Whether to run the workflow immediately when a chat session is created.

    True when the first executable node after chat/start has no startup greeting
    (and, for code-executors, no runtime-input form that must be filled first).
    """
    node = get_entry_chain_first_executable(workflow)
    if not node:
        return False

    config = _node_config(node)
    if has_startup_content(config):
        return False

    node_type = node.get("type")
    if node_type == "agent":
        return True

    if node_type == "code-executor":
        runtime_schema = config.get("runtimeInputs") or []
        if runtime_schema:
            return False
        return True

    return False


def legacy_chat_has_initial_content(chat_config: dict) -> bool:
    """True when a chat node still uses legacy initialMessage / initialQuestions."""
    initial_message = (chat_config.get("initialMessage") or "").strip()
    from app.workflow.tools.ask_user_questions import normalize_questions_payload

    questions_payload = normalize_questions_payload(chat_config.get("initialQuestions"))
    initial_type = chat_config.get("initialType")
    if initial_type == "message":
        questions_payload = None
    elif initial_type == "questions":
        initial_message = ""
    return bool(initial_message) or bool(questions_payload)
