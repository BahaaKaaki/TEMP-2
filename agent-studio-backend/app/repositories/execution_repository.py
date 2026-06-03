"""
Execution repository for data access.
"""
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from sqlalchemy import update
from .base import BaseRepository
from db.models import ExecutionEntity, ExecutionData
from domain.entities import Execution
from workflow.state import deserialize_state_from_storage, serialize_state_for_storage


class ExecutionRepository(BaseRepository[ExecutionEntity, Execution]):
    """Repository for execution data access."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, ExecutionEntity)
    
    async def get_by_id(self, execution_id: int) -> Optional[Execution]:
        """Get execution by ID."""
        query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        result = await self.db.execute(query)
        db_exec = result.scalar_one_or_none()
        
        if not db_exec:
            return None
        
        return self._to_domain(db_exec)
    
    async def get_by_session_id(
        self,
        session_id: str,
        order_by: str = "asc",
        limit: Optional[int] = None
    ) -> List[Execution]:
        """
        Get executions for a session with optional pagination.
        Excludes reverted executions (soft-deleted by revert-to-checkpoint).
        
        Args:
            session_id: Session ID
            order_by: Sort order ('asc' or 'desc')
            limit: Maximum number of executions to return (None = all)
                   Used for pagination to prevent loading 1000+ executions
        
        Returns:
            List of executions, optionally limited to most recent
        """
        query = select(ExecutionEntity).where(
            ExecutionEntity.sessionId == session_id,
            ExecutionEntity.status != "reverted",
        )
        
        if order_by == "desc":
            query = query.order_by(ExecutionEntity.startedAt.desc())
        else:
            query = query.order_by(ExecutionEntity.startedAt.asc())
        
        # Apply limit if specified
        if limit is not None:
            query = query.limit(limit)
        
        result = await self.db.execute(query)
        executions = result.scalars().all()
        
        return [self._to_domain(e) for e in executions]
    
    async def get_latest_by_session(
        self,
        session_id: str
    ) -> Optional[Execution]:
        """Get latest non-reverted execution for a session."""
        query = select(ExecutionEntity).where(
            ExecutionEntity.sessionId == session_id,
            ExecutionEntity.status != "reverted",
        ).order_by(ExecutionEntity.createdAt.desc()).limit(1)
        
        result = await self.db.execute(query)
        db_exec = result.scalar_one_or_none()
        
        if not db_exec:
            return None
        
        return self._to_domain(db_exec)
    
    async def create_execution(
        self,
        workflow_id: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> int:
        """Create new execution."""
        execution = ExecutionEntity(
            workflowId=workflow_id,
            sessionId=session_id,
            finished=False,
            mode="manual",
            startedAt=datetime.utcnow(),
            status="running",
            createdAt=datetime.utcnow(),
            triggeredById=user_id
        )
        
        self.db.add(execution)
        await self.db.flush()
        
        return execution.id
    
    async def update_status(
        self,
        execution_id: int,
        status: str,
        finished: bool = False
    ) -> None:
        """Update execution status."""
        query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        result = await self.db.execute(query)
        execution = result.scalar_one()
        
        execution.status = status
        execution.finished = finished
        
        if finished:
            execution.stoppedAt = datetime.utcnow()
        
        await self.db.flush()
    
    async def get_execution_data(self, execution_id: int) -> Optional[dict]:
        """Get execution data (state)."""
        query = select(ExecutionData).where(
            ExecutionData.executionId == execution_id
        )
        result = await self.db.execute(query)
        data = result.scalar_one_or_none()
        
        if not data or not data.data:
            return None
        
        return deserialize_state_from_storage(data.data)
    
    async def get_execution_data_batch(self, execution_ids: List[int]) -> Dict[int, dict]:
        """
        Get execution data for multiple executions in a single query.
        
        Fixes N+1 query problem by batch loading.
        
        Args:
            execution_ids: List of execution IDs to fetch
            
        Returns:
            Dictionary mapping execution_id to deserialized state
        """
        if not execution_ids:
            return {}
        
        query = select(ExecutionData).where(
            ExecutionData.executionId.in_(execution_ids)
        )
        result = await self.db.execute(query)
        data_list = result.scalars().all()
        
        # Build dictionary of execution_id -> state
        result_dict = {}
        for data in data_list:
            if data and data.data:
                try:
                    result_dict[data.executionId] = deserialize_state_from_storage(data.data)
                except Exception:
                    # Skip invalid state data
                    pass
        
        return result_dict
    
    async def save_execution_data(
        self,
        execution_id: int,
        state: dict,
        workflow_data: Optional[dict] = None
    ) -> None:
        """Save execution data (state)."""
        query = select(ExecutionData).where(
            ExecutionData.executionId == execution_id
        )
        result = await self.db.execute(query)
        data = result.scalar_one_or_none()
        
        serialized_state = serialize_state_for_storage(state)
        
        if data:
            data.data = serialized_state
            data.updatedAt = datetime.utcnow()
        else:
            import json
            data = ExecutionData(
                executionId=execution_id,
                workflowData=json.dumps(workflow_data) if workflow_data else "{}",
                data=serialized_state
            )
            self.db.add(data)
        
        await self.db.flush()
    
    async def update_session_id(
        self,
        execution_id: int,
        session_id: str
    ) -> None:
        """Update execution session ID."""

        
        # Direct UPDATE query - no need to SELECT first (avoids RLS issues)
        stmt = update(ExecutionEntity).where(
            ExecutionEntity.id == execution_id
        ).values(sessionId=session_id)
        
        await self.db.execute(stmt)
        await self.db.flush()
    
    def _to_domain(self, db_exec: ExecutionEntity) -> Execution:
        """Convert database model to domain entity."""
        return Execution(
            id=db_exec.id,
            workflow_id=db_exec.workflowId,
            session_id=db_exec.sessionId,
            finished=db_exec.finished,
            mode=db_exec.mode,
            retry_of=db_exec.retryOf,
            retry_success_id=db_exec.retrySuccessId,
            started_at=db_exec.startedAt,
            stopped_at=db_exec.stoppedAt,
            wait_till=db_exec.waitTill,
            status=db_exec.status,
            deleted_at=db_exec.deletedAt,
            created_at=db_exec.createdAt,
            updated_at=db_exec.updatedAt
        )

