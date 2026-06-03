"""
Checkpoint repository for data access.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from datetime import datetime
import uuid

from .base import BaseRepository
from db.models import WorkflowCheckpoint
from domain.entities import Checkpoint


class CheckpointRepository(BaseRepository[WorkflowCheckpoint, Checkpoint]):
    """Repository for workflow checkpoint data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, WorkflowCheckpoint)

    async def get_by_id(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Get checkpoint by ID."""
        query = select(WorkflowCheckpoint).where(
            WorkflowCheckpoint.id == checkpoint_id
        )
        result = await self.db.execute(query)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain(row)

    async def list_by_session(self, session_id: str) -> List[Checkpoint]:
        """List all checkpoints for a session, ordered by stepIndex ASC."""
        query = (
            select(WorkflowCheckpoint)
            .where(WorkflowCheckpoint.sessionId == session_id)
            .order_by(WorkflowCheckpoint.stepIndex.asc())
        )
        result = await self.db.execute(query)
        rows = result.scalars().all()
        return [self._to_domain(r) for r in rows]

    async def get_next_step_index(self, session_id: str) -> int:
        """Get the next available stepIndex for a session."""
        query = select(func.coalesce(func.max(WorkflowCheckpoint.stepIndex), 0)).where(
            WorkflowCheckpoint.sessionId == session_id
        )
        result = await self.db.execute(query)
        current_max = result.scalar()
        return current_max + 1

    async def create_checkpoint(
        self,
        session_id: str,
        execution_id: Optional[int],
        user_message_id: str,
        user_message_text: str,
        user_message_display: Optional[str],
        workflow_state: str,
        execution_status: Optional[str],
        deliverable_snapshots: str,
        step_index: int,
        session_message_count: int,
        user_id: str,
    ) -> Checkpoint:
        """Create a new checkpoint."""
        checkpoint_id = str(uuid.uuid4())
        row = WorkflowCheckpoint(
            id=checkpoint_id,
            sessionId=session_id,
            executionId=execution_id,
            userMessageId=user_message_id,
            userMessageText=user_message_text,
            userMessageDisplay=user_message_display,
            workflowState=workflow_state,
            executionStatus=execution_status,
            deliverableSnapshots=deliverable_snapshots,
            stepIndex=step_index,
            sessionMessageCount=session_message_count,
            userId=user_id,
            createdAt=datetime.utcnow(),
        )
        await self.create(row)
        return self._to_domain(row)

    async def delete_after_step(self, session_id: str, step_index: int) -> int:
        """Delete all checkpoints with stepIndex > given value. Returns count deleted."""
        stmt = (
            delete(WorkflowCheckpoint)
            .where(
                WorkflowCheckpoint.sessionId == session_id,
                WorkflowCheckpoint.stepIndex > step_index,
            )
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def count_by_session(self, session_id: str) -> int:
        """Count checkpoints for a session."""
        query = select(func.count(WorkflowCheckpoint.id)).where(
            WorkflowCheckpoint.sessionId == session_id
        )
        result = await self.db.execute(query)
        return result.scalar()

    async def delete_oldest(self, session_id: str, keep_count: int) -> int:
        """Delete oldest checkpoints exceeding keep_count. Returns count deleted."""
        subquery = (
            select(WorkflowCheckpoint.id)
            .where(WorkflowCheckpoint.sessionId == session_id)
            .order_by(WorkflowCheckpoint.stepIndex.desc())
            .limit(keep_count)
        )
        stmt = (
            delete(WorkflowCheckpoint)
            .where(
                WorkflowCheckpoint.sessionId == session_id,
                WorkflowCheckpoint.id.notin_(subquery),
            )
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    def _to_domain(self, row: WorkflowCheckpoint) -> Checkpoint:
        """Convert database model to domain entity."""
        return Checkpoint(
            id=row.id,
            session_id=row.sessionId,
            execution_id=row.executionId,
            user_message_id=row.userMessageId,
            user_message_text=row.userMessageText,
            user_message_display=row.userMessageDisplay,
            workflow_state=row.workflowState,
            execution_status=row.executionStatus,
            deliverable_snapshots=row.deliverableSnapshots,
            step_index=row.stepIndex,
            session_message_count=row.sessionMessageCount,
            user_id=row.userId,
            created_at=row.createdAt,
        )
