"""
Session repository for data access.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime
import logging

from .base import BaseRepository
from db.models import ChatSession, WorkflowEntity
from domain.entities import Session

logger = logging.getLogger(__name__)


class SessionRepository(BaseRepository[ChatSession, Session]):
    """Repository for session data access."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, ChatSession)
    
    async def get_by_id(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        query = select(ChatSession).where(ChatSession.id == session_id)
        result = await self.db.execute(query)
        db_session = result.scalar_one_or_none()
        
        if not db_session:
            return None
        
        return self._to_domain(db_session)
    
    async def get_by_workflow_id(
        self,
        workflow_id: str,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Session]:
        """Get sessions by workflow ID."""
        query = select(ChatSession).where(
            ChatSession.workflowId == workflow_id,
            ChatSession.deletedAt == None
        )
        
        if status:
            query = query.where(ChatSession.status == status)
        
        query = query.order_by(
            ChatSession.isPinned.desc(),
            ChatSession.lastAccessedAt.desc().nullslast(),
            ChatSession.lastMessageAt.desc().nullslast()
        ).limit(limit)
        
        result = await self.db.execute(query)
        sessions = result.scalars().all()
        
        return [self._to_domain(s) for s in sessions]
    
    async def get_all_for_user(self, limit: int = 200) -> list[dict]:
        """Get all sessions for the current user with workflow name.

        RLS on both ``chat_session`` and ``workflow_entity`` ensures only
        the caller's rows are visible, so no explicit user filter is needed.
        Returns dicts (not domain objects) because the response includes
        workflow metadata not present on the Session entity.
        """
        query = (
            select(
                ChatSession,
                WorkflowEntity.name.label("workflow_name"),
                WorkflowEntity.marketplaceName.label("workflow_marketplace_name"),
                WorkflowEntity.icon.label("workflow_icon"),
            )
            .outerjoin(WorkflowEntity, ChatSession.workflowId == WorkflowEntity.id)
            .where(ChatSession.deletedAt == None)
            .order_by(
                ChatSession.isPinned.desc(),
                ChatSession.lastAccessedAt.desc().nullslast(),
                ChatSession.lastMessageAt.desc().nullslast(),
            )
            .limit(limit)
        )
        result = await self.db.execute(query)
        rows = result.all()
        return [
            {
                "session": self._to_domain(row[0]),
                "workflow_name": row[1],
                "workflow_marketplace_name": row[2],
                "workflow_icon": row[3],
            }
            for row in rows
        ]

    async def create_session(
        self,
        session_id: str,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        variables: Optional[dict] = None,
        metadata: Optional[dict] = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> Session:
        """Create new session."""
        import json
        
        db_session = ChatSession(
            id=session_id,
            workflowId=workflow_id,
            name=name,
            description=description,
            status='active',
            messageCount=0,
            sessionVariables=json.dumps(variables) if variables else None,
            sessionMetadata=json.dumps(metadata) if metadata else None,
            userId=user_id,
            projectId=project_id,
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow()
        )
        
        await self.create(db_session)
        return self._to_domain(db_session)
    
    async def update_session(
        self,
        session_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Session:
        """Update session."""
        import json
        
        db_session = await self.get_by_id(session_id)
        if not db_session:
            return None
        
        query = select(ChatSession).where(ChatSession.id == session_id)
        result = await self.db.execute(query)
        db_obj = result.scalar_one()
        
        if name is not None:
            db_obj.name = name
        if description is not None:
            db_obj.description = description
        if status is not None:
            db_obj.status = status
        if metadata is not None:
            db_obj.sessionMetadata = json.dumps(metadata)
        
        db_obj.updatedAt = datetime.utcnow()
        
        await self.db.flush()
        await self.db.refresh(db_obj)
        
        return self._to_domain(db_obj)
    
    async def increment_message_count(self, session_id: str) -> None:
        """Increment message count."""
        query = select(ChatSession).where(ChatSession.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()
        
        if not session:
            logger.warning("Session %s not found for message count increment (possibly RLS filtered)", session_id)
            return
        
        session.messageCount += 1
        session.lastMessageAt = datetime.utcnow()
        session.updatedAt = datetime.utcnow()
        
        await self.db.flush()
    
    async def update_message_count(self, session_id: str, count: int) -> None:
        """Set message count to a specific value. Used during revert."""
        query = select(ChatSession).where(ChatSession.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()
        if not session:
            logger.warning("Session %s not found for message count update (possibly RLS filtered)", session_id)
            return
        session.messageCount = count
        session.updatedAt = datetime.utcnow()
        await self.db.flush()

    async def soft_delete(self, session_id: str) -> None:
        """Soft delete session."""
        query = select(ChatSession).where(ChatSession.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one()
        
        session.deletedAt = datetime.utcnow()
        session.status = 'deleted'
        
        await self.db.flush()
    
    async def toggle_pin(self, session_id: str, pinned: bool) -> Optional[Session]:
        """Toggle pin status for a session."""
        query = select(ChatSession).where(ChatSession.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()
        if not session:
            return None
        session.isPinned = pinned
        session.updatedAt = datetime.utcnow()
        await self.db.flush()
        return self._to_domain(session)

    async def update_last_accessed(self, session_id: str) -> None:
        """Update last accessed timestamp."""
        query = select(ChatSession).where(ChatSession.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()
        if session:
            session.lastAccessedAt = datetime.utcnow()
            await self.db.flush()

    def _to_domain(self, db_session: ChatSession) -> Session:
        """Convert database model to domain entity."""
        return Session(
            id=db_session.id,
            workflow_id=db_session.workflowId,
            name=db_session.name,
            description=db_session.description,
            status=db_session.status,
            message_count=db_session.messageCount,
            session_variables=db_session.sessionVariables,
            session_metadata=db_session.sessionMetadata,
            user_id=db_session.userId,
            created_at=db_session.createdAt,
            updated_at=db_session.updatedAt,
            last_message_at=db_session.lastMessageAt,
            deleted_at=db_session.deletedAt,
            is_pinned=db_session.isPinned,
            last_accessed_at=db_session.lastAccessedAt,
            project_id=db_session.projectId,
        )

