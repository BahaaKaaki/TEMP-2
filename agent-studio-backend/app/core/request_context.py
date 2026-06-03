"""
Request context for tracking authenticated user across database sessions.
"""
from contextvars import ContextVar
from typing import List, Optional

current_user_id: ContextVar[Optional[str]] = ContextVar('current_user_id', default=None)
current_user_name: ContextVar[Optional[str]] = ContextVar('current_user_name', default=None)
current_user_email: ContextVar[Optional[str]] = ContextVar('current_user_email', default=None)

# Holds the current user's AD group GUIDs so RLS can evaluate group sharing
current_user_groups: ContextVar[Optional[List[str]]] = ContextVar('current_user_groups', default=None)


def set_current_user_id(user_id: Optional[str]):
    """Set the current user ID for this request context."""
    current_user_id.set(user_id)


def get_current_user_id() -> Optional[str]:
    """Get the current user ID from request context."""
    return current_user_id.get()


def clear_current_user_id():
    """Clear the current user ID from request context."""
    current_user_id.set(None)


def set_current_user_name(user_name: Optional[str]):
    """Set the current user's display name for this request context."""
    current_user_name.set(user_name)


def get_current_user_name() -> Optional[str]:
    """Get the current user's display name from request context."""
    return current_user_name.get()


def clear_current_user_name():
    """Clear the current user display name from request context."""
    current_user_name.set(None)


def set_current_user_email(user_email: Optional[str]):
    """Set the current user's email for this request context."""
    current_user_email.set(user_email)


def get_current_user_email() -> Optional[str]:
    """Get the current user's email from request context."""
    return current_user_email.get()


def clear_current_user_email():
    """Clear the current user email from request context."""
    current_user_email.set(None)


def set_current_user_groups(group_ids: Optional[List[str]]):
    """Set the current user's AD group IDs for this request context."""
    current_user_groups.set(group_ids)


def get_current_user_groups() -> Optional[List[str]]:
    """Get the current user's AD group IDs from request context."""
    return current_user_groups.get()


def clear_current_user_groups():
    """Clear the current user's AD groups from request context."""
    current_user_groups.set(None)
