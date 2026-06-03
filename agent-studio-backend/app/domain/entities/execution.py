"""
Execution domain entity.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from core.enums import ExecutionStatus


@dataclass
class Execution:
    """Workflow execution domain entity."""
    
    id: int
    workflow_id: str
    session_id: Optional[str]
    finished: bool
    mode: str
    retry_of: Optional[str]
    retry_success_id: Optional[str]
    started_at: Optional[datetime]
    stopped_at: Optional[datetime]
    wait_till: Optional[datetime]
    status: str
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    
    def is_running(self) -> bool:
        """Check if execution is running."""
        return self.status == ExecutionStatus.RUNNING.value
    
    def is_completed(self) -> bool:
        """Check if execution is completed."""
        return self.status == ExecutionStatus.COMPLETED.value
    
    def is_failed(self) -> bool:
        """Check if execution is failed."""
        return self.status == ExecutionStatus.FAILED.value
    
    def is_pending_review(self) -> bool:
        """Check if execution is pending review."""
        return self.status == ExecutionStatus.PENDING_REVIEW.value
    
    def is_paused(self) -> bool:
        """Check if execution is paused."""
        return self.status == ExecutionStatus.PAUSED.value
    
    def is_waiting(self) -> bool:
        """Check if execution is waiting."""
        return self.status == "waiting"
    
    def can_be_resumed(self) -> bool:
        """Check if execution can be resumed."""
        return self.status in ["pending_review", "paused"]
    
    def get_duration_seconds(self) -> Optional[float]:
        """Get execution duration in seconds."""
        if self.started_at and self.stopped_at:
            return (self.stopped_at - self.started_at).total_seconds()
        return None
    
    def is_finished(self) -> bool:
        """Check if execution has finished."""
        return self.finished
    
    def mark_as_running(self) -> None:
        """Mark execution as running."""
        self.status = ExecutionStatus.RUNNING.value
    
    def mark_as_completed(self) -> None:
        """Mark execution as completed."""
        self.status = ExecutionStatus.COMPLETED.value
        self.finished = True
    
    def mark_as_failed(self) -> None:
        """Mark execution as failed."""
        self.status = ExecutionStatus.FAILED.value
        self.finished = True
    
    def mark_as_cancelled(self) -> None:
        """Mark execution as cancelled."""
        self.status = ExecutionStatus.CANCELLED.value
        self.finished = True
    
    def mark_as_paused(self) -> None:
        """Mark execution as paused."""
        self.status = ExecutionStatus.PAUSED.value
    
    def mark_as_pending_review(self) -> None:
        """Mark execution as pending review."""
        self.status = ExecutionStatus.PENDING_REVIEW.value

