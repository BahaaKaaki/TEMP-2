"""
Context-local metadata for LLM observability (Langfuse + internal traces).

Workflow executors and HTTP auth set baseline fields; nodes merge per-step
context. TracedChatModel reads this at invoke time.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_user_id: ContextVar[Optional[str]] = ContextVar("llm_obs_user_id", default=None)
_user_name: ContextVar[Optional[str]] = ContextVar("llm_obs_user_name", default=None)
_user_email: ContextVar[Optional[str]] = ContextVar("llm_obs_user_email", default=None)
_workflow_id: ContextVar[Optional[str]] = ContextVar("llm_obs_workflow_id", default=None)
_workflow_name: ContextVar[Optional[str]] = ContextVar("llm_obs_workflow_name", default=None)
_execution_id: ContextVar[Optional[str]] = ContextVar("llm_obs_execution_id", default=None)
_session_id: ContextVar[Optional[str]] = ContextVar("llm_obs_session_id", default=None)
_node_id: ContextVar[Optional[str]] = ContextVar("llm_obs_node_id", default=None)
_node_label: ContextVar[Optional[str]] = ContextVar("llm_obs_node_label", default=None)
_node_type: ContextVar[Optional[str]] = ContextVar("llm_obs_node_type", default=None)
_binding_key: ContextVar[Optional[str]] = ContextVar("llm_obs_binding_key", default=None)
_llm_role: ContextVar[Optional[str]] = ContextVar("llm_obs_llm_role", default=None)
_tool_name: ContextVar[Optional[str]] = ContextVar("llm_obs_tool_name", default=None)
_langfuse_extra: ContextVar[Optional[Dict[str, Any]]] = ContextVar("llm_obs_langfuse_extra", default=None)

# Each entry is (ContextVar, Token) from .set() — required for correct reset after merge.
ObservabilityTokens = Tuple[Tuple[ContextVar[Any], Token], ...]

_CONTEXT_VARS = (
    _user_id,
    _user_name,
    _user_email,
    _workflow_id,
    _workflow_name,
    _execution_id,
    _session_id,
    _node_id,
    _node_label,
    _node_type,
    _binding_key,
    _llm_role,
    _tool_name,
)


def format_user_display_name(user: Any) -> Optional[str]:
    """Build a display name from a User entity or similar object."""
    if user is None:
        return None
    first = (getattr(user, "firstName", None) or "").strip()
    last = (getattr(user, "lastName", None) or "").strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    email = getattr(user, "email", None)
    return str(email).strip() if email else None


def format_user_email(user: Any) -> Optional[str]:
    """Normalized email from a User entity or similar object."""
    if user is None:
        return None
    email = getattr(user, "email", None)
    if not email:
        return None
    return str(email).strip().lower()


def llm_role_from_binding(binding_key: Optional[str]) -> Optional[str]:
    """Derive a default llm_role label from a catalog binding_key."""
    if not binding_key:
        return None
    if binding_key == "tool.tool_caller":
        return "tool_decider"
    if binding_key.startswith("tool."):
        suffix = binding_key.removeprefix("tool.")
        return suffix.replace(".", "_")
    if binding_key.startswith("service."):
        return binding_key.removeprefix("service.").replace(".", "_")
    if binding_key.startswith("settings."):
        return binding_key.removeprefix("settings.").replace(".", "_")
    return binding_key.replace(".", "_")


def set_llm_observability_context(
    *,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    user_email: Optional[str] = None,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    execution_id: Optional[str | int] = None,
    session_id: Optional[str] = None,
    node_id: Optional[str] = None,
    node_label: Optional[str] = None,
    node_type: Optional[str] = None,
    binding_key: Optional[str] = None,
    llm_role: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> ObservabilityTokens:
    """Replace observability context for the current async task."""
    exec_str = str(execution_id) if execution_id is not None else None
    return tuple(
        (var, var.set(value))
        for var, value in (
            (_user_id, user_id),
            (_user_name, user_name),
            (_user_email, user_email),
            (_workflow_id, workflow_id),
            (_workflow_name, workflow_name),
            (_execution_id, exec_str),
            (_session_id, session_id),
            (_node_id, node_id),
            (_node_label, node_label),
            (_node_type, node_type),
            (_binding_key, binding_key),
            (_llm_role, llm_role),
            (_tool_name, tool_name),
        )
    )


def merge_llm_observability_context(
    *,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    user_email: Optional[str] = None,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    execution_id: Optional[str | int] = None,
    session_id: Optional[str] = None,
    node_id: Optional[str] = None,
    node_label: Optional[str] = None,
    node_type: Optional[str] = None,
    binding_key: Optional[str] = None,
    llm_role: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> ObservabilityTokens:
    """Update only provided fields; return (var, token) pairs to reset merged values."""
    pairs: list[Tuple[ContextVar[Any], Token]] = []
    if user_id is not None:
        pairs.append((_user_id, _user_id.set(user_id)))
    if user_name is not None:
        pairs.append((_user_name, _user_name.set(user_name)))
    if user_email is not None:
        pairs.append((_user_email, _user_email.set(user_email)))
    if workflow_id is not None:
        pairs.append((_workflow_id, _workflow_id.set(workflow_id)))
    if workflow_name is not None:
        pairs.append((_workflow_name, _workflow_name.set(workflow_name)))
    if execution_id is not None:
        pairs.append((_execution_id, _execution_id.set(str(execution_id))))
    if session_id is not None:
        pairs.append((_session_id, _session_id.set(session_id)))
    if node_id is not None:
        pairs.append((_node_id, _node_id.set(node_id)))
    if node_label is not None:
        pairs.append((_node_label, _node_label.set(node_label)))
    if node_type is not None:
        pairs.append((_node_type, _node_type.set(node_type)))
    if binding_key is not None:
        pairs.append((_binding_key, _binding_key.set(binding_key)))
    if llm_role is not None:
        pairs.append((_llm_role, _llm_role.set(llm_role)))
    if tool_name is not None:
        pairs.append((_tool_name, _tool_name.set(tool_name)))
    return tuple(pairs)


def reset_llm_observability_context(tokens: ObservabilityTokens) -> None:
    """Restore observability context from (var, token) pairs returned by set/merge."""
    for var, token in tokens:
        try:
            var.reset(token)
        except ValueError:
            # LangGraph may run node cleanup in a copied task context.
            logger.debug(
                "Skipped observability reset for %s (context mismatch)",
                getattr(var, "name", var),
                exc_info=True,
            )


def clear_llm_observability_context() -> None:
    """Clear all observability context fields."""
    for var in _CONTEXT_VARS:
        var.set(None)


def get_llm_observability_context() -> Dict[str, Optional[str]]:
    return {
        "user_id": _user_id.get(),
        "user_name": _user_name.get(),
        "user_email": _user_email.get(),
        "workflow_id": _workflow_id.get(),
        "workflow_name": _workflow_name.get(),
        "execution_id": _execution_id.get(),
        "session_id": _session_id.get(),
        "node_id": _node_id.get(),
        "node_label": _node_label.get(),
        "node_type": _node_type.get(),
        "binding_key": _binding_key.get(),
        "llm_role": _llm_role.get(),
        "tool_name": _tool_name.get(),
    }


def push_langfuse_extra(extra: Dict[str, Any]) -> Token:
    """Temporarily merge extra fields into Langfuse metadata for the next generation."""
    current = _langfuse_extra.get() or {}
    merged = {**current, **extra}
    return _langfuse_extra.set(merged)


def pop_langfuse_extra(token: Token) -> None:
    _langfuse_extra.reset(token)


def apply_workflow_observability_context(
    state: Optional[Dict[str, Any]] = None,
) -> ObservabilityTokens:
    """Set baseline Langfuse fields for a workflow run from state metadata."""
    meta = (state or {}).get("metadata") or {}
    user_id = meta.get("user_id")
    user_name = None
    user_email = meta.get("user_email")
    try:
        from core.request_context import (
            get_current_user_email,
            get_current_user_id,
            get_current_user_name,
        )

        user_id = user_id or get_current_user_id()
        user_name = get_current_user_name()
        user_email = user_email or get_current_user_email()
    except Exception:
        pass

    return set_llm_observability_context(
        user_id=str(user_id) if user_id else None,
        user_name=user_name,
        user_email=user_email,
        workflow_id=str(meta["workflow_id"]) if meta.get("workflow_id") else None,
        workflow_name=meta.get("workflow_name"),
        execution_id=meta.get("execution_id"),
        session_id=str(meta["session_id"]) if meta.get("session_id") else None,
    )


def resolve_user_identity() -> Dict[str, Optional[str]]:
    """
    user_id / user_name / user_email for Langfuse from workflow context or HTTP auth.

    Workflow nodes set llm observability contextvars; routes like code executor,
    KB upload, and OCR only set request_context via get_current_user — merge both.
    """
    ctx = get_llm_observability_context()
    user_id = ctx.get("user_id")
    user_name = ctx.get("user_name")
    user_email = ctx.get("user_email")
    try:
        from core.request_context import (
            get_current_user_email,
            get_current_user_id,
            get_current_user_name,
        )

        user_id = user_id or get_current_user_id()
        user_name = user_name or get_current_user_name()
        user_email = user_email or get_current_user_email()
    except Exception:
        pass
    return {
        "user_id": user_id,
        "user_name": user_name,
        "user_email": user_email,
    }


async def lookup_user_email(db: Any, user_id: Optional[str]) -> Optional[str]:
    """Resolve email from request context or a one-off DB lookup (background workflows)."""
    if not user_id:
        return None
    try:
        from core.request_context import get_current_user_email

        email = get_current_user_email()
        if email:
            return email
    except Exception:
        pass
    try:
        from repositories.user_repository import UserRepository

        user = await UserRepository(db).get_by_id(user_id)
        return format_user_email(user)
    except Exception:
        logger.debug("Could not resolve user email for %s", user_id, exc_info=True)
        return None


def build_langfuse_metadata(
    *,
    model: Optional[str] = None,
    operation: Optional[str] = None,
    binding_key: Optional[str] = None,
    llm_role: Optional[str] = None,
    tool_name: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge contextvars with call-site overrides for Langfuse trace metadata."""
    ctx = get_llm_observability_context()
    identity = resolve_user_identity()
    meta: Dict[str, Any] = {
        "invoked_at": datetime.utcnow().isoformat() + "Z",
        "user_id": identity.get("user_id"),
        "user_name": identity.get("user_name"),
        "user_email": identity.get("user_email"),
        "workflow_id": ctx.get("workflow_id"),
        "workflow_name": ctx.get("workflow_name"),
        "execution_id": ctx.get("execution_id"),
        "session_id": ctx.get("session_id"),
        "node_id": ctx.get("node_id"),
        "node_label": ctx.get("node_label"),
        "node_type": ctx.get("node_type"),
        "binding_key": binding_key or ctx.get("binding_key"),
        "llm_role": llm_role or ctx.get("llm_role"),
        "tool_name": tool_name or ctx.get("tool_name"),
        "operation": operation,
        "model": model,
    }
    lf_extra = _langfuse_extra.get()
    if lf_extra:
        meta.update(lf_extra)
    if extra:
        meta.update(extra)
    return {k: v for k, v in meta.items() if v is not None}
