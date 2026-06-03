"""
Workflow utility modules.

Provides helper functions and utilities for workflow execution,
including context building, formatting, and other shared functionality.
"""

from .context import (
    build_system_context,
    enrich_system_prompt,
    get_current_date_simple,
    get_current_datetime_iso,
    add_date_to_prompt,
)
from .kb_config import (
    resolve_kb_ids,
    primary_kb_id,
    has_kb,
)
from .file_context import (
    build_global_file_context,
    format_global_file_block,
)

__all__ = [
    "build_system_context",
    "enrich_system_prompt",
    "get_current_date_simple",
    "get_current_datetime_iso",
    "add_date_to_prompt",
    "resolve_kb_ids",
    "primary_kb_id",
    "has_kb",
    "build_global_file_context",
    "format_global_file_block",
]

