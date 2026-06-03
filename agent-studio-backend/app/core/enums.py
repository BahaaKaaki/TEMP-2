"""
Core enumerations for the application.

Defines all status values and other enumerated types to replace magic strings.
"""

from enum import Enum


class ExecutionStatus(str, Enum):
    """Execution status values."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_REVIEW = "pending_review"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    WAITING = "waiting"


class DeliverableStatus(str, Enum):
    """Deliverable review status values."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentStatus(str, Enum):
    """Document processing status values."""
    PENDING = "pending"
    PENDING_SCHEMA_REVIEW = "schema_review"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class FileParsingStatus(str, Enum):
    """File parsing status values."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeBaseStatus(str, Enum):
    """Knowledge base status values."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EmbeddingStatus(str, Enum):
    """Embedding generation status values."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Convenience methods for backwards compatibility
def is_terminal_status(status: str) -> bool:
    """Check if execution status is terminal (won't change)."""
    return status in (
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.FAILED.value,
        ExecutionStatus.CANCELLED.value
    )


def is_active_status(status: str) -> bool:
    """Check if execution is actively running."""
    return status == ExecutionStatus.RUNNING.value


def is_paused_status(status: str) -> bool:
    """Check if execution is paused (can be resumed)."""
    return status in (
        ExecutionStatus.PAUSED.value,
        ExecutionStatus.PENDING_REVIEW.value,
        ExecutionStatus.WAITING.value
    )

