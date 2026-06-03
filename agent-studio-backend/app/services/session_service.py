"""
Session service for business logic.
"""
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from datetime import datetime
import logging
import json

from .base import BaseService
from repositories import SessionRepository, WorkflowRepository, ExecutionRepository
from domain.entities import Session
from core.exceptions import (
    SessionNotFoundException,
    WorkflowNotFoundException,
)

logger = logging.getLogger(__name__)


class SessionService(BaseService):
    """Service for session business logic."""
    
    def __init__(
        self,
        db: AsyncSession,
        session_repo: SessionRepository,
        workflow_repo: WorkflowRepository,
        execution_repo: ExecutionRepository
    ):
        super().__init__(db)
        self.session_repo = session_repo
        self.workflow_repo = workflow_repo
        self.execution_repo = execution_repo
    
    async def create_session(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        variables: dict = None,
        metadata: dict = None,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> Session:
        """Create new chat session."""
        from db.models import WorkflowEntity
        from sqlalchemy import select
        
        workflow = await self.workflow_repo.get_by_id(workflow_id)
        if not workflow:
            raise WorkflowNotFoundException(workflow_id)
        
        # Activate the workflow if it's not active.
        # Only the owner may UPDATE the row (RLS blocks non-owners), so we
        # check ownership first to avoid a StaleDataError for shared /
        # marketplace users.
        if not workflow.active and user_id:
            query = select(WorkflowEntity).where(
                WorkflowEntity.id == workflow_id,
                WorkflowEntity.createdById == str(user_id),
            )
            result = await self.db.execute(query)
            db_workflow = result.scalar_one_or_none()
            if db_workflow:
                db_workflow.active = True
                logger.debug("Activated workflow %s for new chat session", workflow_id)
        
        session_id = str(uuid.uuid4())
        session_name = name or f"Session {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        
        session = await self.session_repo.create_session(
            session_id=session_id,
            workflow_id=workflow_id,
            name=session_name,
            description=description,
            variables=variables or {},
            metadata=metadata or {},
            user_id=user_id,
            project_id=project_id,
        )
        
        await self.commit()
        
        logger.debug("Created session %s for workflow %s", session_id, workflow_id)
        return session
    
    async def get_session(self, session_id: str) -> Session:
        """Get session by ID."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundException(session_id)
        return session
    
    async def list_sessions(
        self,
        workflow_id: str,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Session]:
        """List sessions for a workflow."""
        return await self.session_repo.get_by_workflow_id(
            workflow_id,
            status,
            limit
        )
    
    async def list_all_user_sessions(self, limit: int = 200) -> list[dict]:
        """List all sessions for the current user with workflow metadata."""
        return await self.session_repo.get_all_for_user(limit=limit)

    async def update_session(
        self,
        session_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Session:
        """Update session."""
        session = await self.session_repo.update_session(
            session_id,
            name,
            description,
            status,
            metadata
        )
        
        if not session:
            raise SessionNotFoundException(session_id)
        
        await self.commit()
        
        logger.debug("Updated session %s", session_id)
        return session
    
    async def toggle_pin(self, session_id: str, pinned: bool) -> Session:
        """Toggle pin status for a session."""
        session = await self.session_repo.toggle_pin(session_id, pinned)
        if not session:
            raise SessionNotFoundException(session_id)
        await self.commit()
        return session

    async def update_last_accessed(self, session_id: str) -> None:
        """Update last accessed timestamp for a session."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundException(session_id)
        await self.session_repo.update_last_accessed(session_id)
        await self.commit()

    async def delete_session(
        self,
        session_id: str,
        permanent: bool = False
    ) -> None:
        """Delete session."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundException(session_id)
        
        if permanent:
            executions = await self.execution_repo.get_by_session_id(session_id)
            
            for execution in executions:
                await self.db.execute(
                    text('DELETE FROM execution_data WHERE "executionId" = :eid'),
                    {"eid": execution.id}
                )
                await self.db.execute(
                    text("DELETE FROM execution_entity WHERE id = :eid"),
                    {"eid": execution.id}
                )
            
            await self.db.execute(
                text("DELETE FROM chat_session WHERE id = :sid"),
                {"sid": session_id}
            )
            
            logger.debug("Permanently deleted session %s", session_id)
        else:
            await self.session_repo.soft_delete(session_id)
            logger.debug("Soft deleted session %s", session_id)
        
        await self.commit()
    
    async def get_session_detail(self, session_id: str) -> dict:
        """Get detailed session information with conversation history."""
        session = await self.get_session(session_id)
        
        latest_execution = await self.execution_repo.get_latest_by_session(session_id)
        
        conversation_history = []
        if latest_execution:
            state = await self.execution_repo.get_execution_data(latest_execution.id)
            if state:
                messages = state.get("messages", [])
                
                for msg in messages:
                    role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
                    message_id = msg.additional_kwargs.get("message_id") if hasattr(msg, "additional_kwargs") else None
                    
                    content = msg.content
                    agent_id = None
                    agent_label = None
                    agent_type = None
                    
                    citations = []
                    questions = None
                    answered_at = None
                    edwin_url = None
                    edwin_handoff_id = None
                    if hasattr(msg, "additional_kwargs") and isinstance(msg.additional_kwargs, dict):
                        # An explicitly stored display_content wins, even
                        # when it's an empty string — that's how a
                        # question-only message signals "render nothing
                        # above the QuestionsCard".
                        if "display_content" in msg.additional_kwargs:
                            content = msg.additional_kwargs["display_content"] or ""

                        # Extract agent information
                        agent_id = msg.additional_kwargs.get("agent_id")
                        agent_label = msg.additional_kwargs.get("agent_label")
                        agent_type = msg.additional_kwargs.get("agent_type")
                        
                        # Extract citations + question payload
                        citations = msg.additional_kwargs.get("citations", [])
                        questions = msg.additional_kwargs.get("questions")
                        answered_at = msg.additional_kwargs.get("answered_at")
                        edwin_url = msg.additional_kwargs.get("edwin_url")
                        edwin_handoff_id = msg.additional_kwargs.get("edwin_handoff_id")
                    
                    if msg.__class__.__name__ == "HumanMessage" and "UPLOADED DOCUMENTS" in msg.content:
                        parts = msg.content.split("USER MESSAGE:")
                        if len(parts) > 1:
                            content = parts[-1].strip()
                    
                    structured_queries = []
                    if hasattr(msg, "additional_kwargs") and isinstance(msg.additional_kwargs, dict):
                        structured_queries = msg.additional_kwargs.get("structured_queries", [])

                    message_dict = {
                        "message_id": message_id,
                        "role": role,
                        "content": content,
                        "timestamp": None,
                        "agent_id": agent_id,
                        "agent_label": agent_label,
                        "agent_type": agent_type
                    }
                    
                    if citations:
                        message_dict["citations"] = citations
                    if structured_queries:
                        message_dict["structured_queries"] = structured_queries
                    if questions:
                        message_dict["questions"] = questions
                    if answered_at:
                        message_dict["answered_at"] = answered_at
                    if edwin_url:
                        message_dict["edwin_url"] = edwin_url
                    if edwin_handoff_id:
                        message_dict["edwin_handoff_id"] = edwin_handoff_id
                    
                    conversation_history.append(message_dict)
        
        if len(conversation_history) == 0 and session.workflow_id:
            workflow = await self.workflow_repo.get_effective_by_id(
                session.workflow_id, user_id=session.user_id,
            )
            if workflow:
                from app.workflow.utils.startup import resolve_session_open_content

                resolved = resolve_session_open_content(workflow)
                if resolved:
                    entry: dict = {
                        "message_id": str(uuid.uuid4()),
                        "role": "assistant",
                        "content": resolved["display_text"] or resolved["llm_content"],
                        "timestamp": session.created_at.isoformat() if session.created_at else None,
                        "agent_id": resolved.get("agent_id"),
                        "agent_label": resolved.get("agent_label"),
                        "agent_type": resolved.get("agent_type"),
                    }
                    if resolved.get("questions_payload"):
                        entry["questions"] = resolved["questions_payload"]
                    conversation_history.append(entry)
        
        executions = await self.execution_repo.get_by_session_id(session_id)

        execution_status = latest_execution.status if latest_execution else None

        return {
            "session": session,
            "execution_count": len(executions),
            "execution_status": execution_status,
            "execution_id": latest_execution.id if latest_execution else None,
            "conversation_history": conversation_history
        }

