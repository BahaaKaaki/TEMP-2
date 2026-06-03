"""
Checkpoint domain entity.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Checkpoint:
    """Workflow checkpoint domain entity."""

    id: str
    session_id: str
    execution_id: Optional[int]
    user_message_id: str
    user_message_text: str
    user_message_display: Optional[str]
    workflow_state: str
    execution_status: Optional[str]
    deliverable_snapshots: str
    step_index: int
    session_message_count: int
    user_id: str
    created_at: datetime
