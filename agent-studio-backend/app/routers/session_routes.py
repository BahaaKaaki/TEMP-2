"""
Session management routes.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
import logging

from services import SessionService, ChatService
from core.dependencies import get_session_service, get_chat_service, get_current_user
from db.models import User
from core.exceptions import (
    SessionNotFoundException,
    WorkflowNotFoundException,
    DomainException
)
from schemas import (
    CreateSessionRequest,
    UpdateSessionRequest,
    ChatSessionResponse,
    ChatSessionDetailResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["Chat Sessions"],
    dependencies=[Depends(get_current_user)],  # Secure ALL endpoints
    responses={404: {"description": "Not found"}}
)


@router.post(
    "/workflows/{workflow_id}/sessions",
    response_model=ChatSessionResponse,
    status_code=201
)
async def create_chat_session(
    workflow_id: str,
    session_data: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
    chat_service: ChatService = Depends(get_chat_service),
):
    """Create a new chat session/instance for a workflow.

    If the first agent or code-executor after the chat node has no startup
    message, the workflow is kicked off immediately in the background so
    it runs without requiring the user to send a first chat message.
    """
    try:
        session = await session_service.create_session(
            workflow_id=workflow_id,
            name=session_data.name,
            description=session_data.description,
            variables=session_data.variables,
            metadata=session_data.metadata,
            user_id=current_user.id,
            project_id=session_data.project_id,
        )

        try:
            await chat_service.auto_start_session_if_needed(
                session_id=session.id,
                user_id=current_user.id,
            )
        except Exception as auto_start_err:
            # Auto-start is best-effort — never fail session creation if it
            # breaks; the user can still send a message to trigger the run.
            logger.warning(
                "Auto-start check failed for session %s: %s",
                session.id,
                auto_start_err,
            )

        return ChatSessionResponse(
            id=session.id,
            workflowId=session.workflow_id,
            name=session.name,
            description=session.description,
            status=session.status,
            messageCount=session.message_count,
            createdAt=session.created_at,
            updatedAt=session.updated_at,
            lastMessageAt=session.last_message_at,
            isPinned=session.is_pinned,
            lastAccessedAt=session.last_accessed_at,
            projectId=session.project_id,
        )
    
    except WorkflowNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error creating session: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create chat session")


@router.get("/my-sessions")
async def list_my_sessions(
    limit: int = Query(200, ge=1, le=500),
    session_service: SessionService = Depends(get_session_service),
):
    """Return all sessions for the current user across every workflow.

    RLS ensures only the caller's rows are returned.  The response
    includes the workflow name so the frontend can render the list
    without fetching each workflow individually.
    """
    try:
        rows = await session_service.list_all_user_sessions(limit=limit)
        return [
            {
                "session": ChatSessionResponse(
                    id=r["session"].id,
                    workflowId=r["session"].workflow_id,
                    name=r["session"].name,
                    description=r["session"].description,
                    status=r["session"].status,
                    messageCount=r["session"].message_count,
                    createdAt=r["session"].created_at,
                    updatedAt=r["session"].updated_at,
                    lastMessageAt=r["session"].last_message_at,
                    isPinned=r["session"].is_pinned,
                    lastAccessedAt=r["session"].last_accessed_at,
                    projectId=r["session"].project_id,
                ),
                "workflowName": r["workflow_name"],
                "workflowMarketplaceName": r["workflow_marketplace_name"],
                "workflowIcon": r.get("workflow_icon"),
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("Error listing user sessions: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list sessions")


@router.get(
    "/workflows/{workflow_id}/sessions",
    response_model=List[ChatSessionResponse]
)
async def list_chat_sessions(
    workflow_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    session_service: SessionService = Depends(get_session_service)
):
    """List all chat sessions/instances for a workflow."""
    try:
        sessions = await session_service.list_sessions(
            workflow_id=workflow_id,
            status=status,
            limit=limit
        )
        
        return [
            ChatSessionResponse(
                id=s.id,
                workflowId=s.workflow_id,
                name=s.name,
                description=s.description,
                status=s.status,
                messageCount=s.message_count,
                createdAt=s.created_at,
                updatedAt=s.updated_at,
                lastMessageAt=s.last_message_at,
                isPinned=s.is_pinned,
                lastAccessedAt=s.last_accessed_at,
                projectId=s.project_id,
            )
            for s in sessions
        ]
    
    except Exception as e:
        logger.error("Error listing sessions: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list sessions")


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse
)
async def get_chat_session(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """Get detailed information about a specific chat session."""
    try:
        detail = await session_service.get_session_detail(session_id)
        
        session = detail["session"]
        
        return ChatSessionDetailResponse(
            session=ChatSessionResponse(
                id=session.id,
                workflowId=session.workflow_id,
                name=session.name,
                description=session.description,
                status=session.status,
                messageCount=session.message_count,
                createdAt=session.created_at,
                updatedAt=session.updated_at,
                lastMessageAt=session.last_message_at,
                isPinned=session.is_pinned,
                lastAccessedAt=session.last_accessed_at,
                projectId=session.project_id,
            ),
            execution_count=detail["execution_count"],
            execution_status=detail.get("execution_status"),
            execution_id=detail.get("execution_id"),
            conversation_history=detail["conversation_history"]
        )
    
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error getting session: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get session")


@router.patch(
    "/sessions/{session_id}",
    response_model=ChatSessionResponse
)
async def update_chat_session(
    session_id: str,
    update_data: UpdateSessionRequest,
    session_service: SessionService = Depends(get_session_service)
):
    """Update session metadata."""
    try:
        session = await session_service.update_session(
            session_id=session_id,
            name=update_data.name,
            description=update_data.description,
            status=update_data.status,
            metadata=update_data.metadata
        )
        
        return ChatSessionResponse(
            id=session.id,
            workflowId=session.workflow_id,
            name=session.name,
            description=session.description,
            status=session.status,
            messageCount=session.message_count,
            createdAt=session.created_at,
            updatedAt=session.updated_at,
            lastMessageAt=session.last_message_at,
            isPinned=session.is_pinned,
            lastAccessedAt=session.last_accessed_at,
            projectId=session.project_id,
        )
    
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error updating session: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update session")


@router.patch(
    "/sessions/{session_id}/pin",
    response_model=ChatSessionResponse
)
async def toggle_session_pin(
    session_id: str,
    pinned: bool = Query(..., description="True to pin, False to unpin"),
    session_service: SessionService = Depends(get_session_service)
):
    """Toggle pin status for a chat session."""
    try:
        session = await session_service.toggle_pin(session_id, pinned)
        return ChatSessionResponse(
            id=session.id,
            workflowId=session.workflow_id,
            name=session.name,
            description=session.description,
            status=session.status,
            messageCount=session.message_count,
            createdAt=session.created_at,
            updatedAt=session.updated_at,
            lastMessageAt=session.last_message_at,
            isPinned=session.is_pinned,
            lastAccessedAt=session.last_accessed_at,
            projectId=session.project_id,
        )
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error toggling session pin: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to toggle pin")


@router.patch("/sessions/{session_id}/last-accessed")
async def update_session_last_accessed(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """Update last accessed timestamp for a chat session."""
    try:
        await session_service.update_last_accessed(session_id)
        return {"message": "Last accessed updated"}
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error updating last accessed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update last accessed")


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    permanent: bool = Query(False, description="Permanently delete"),
    session_service: SessionService = Depends(get_session_service)
):
    """Delete a chat session."""
    try:
        await session_service.delete_session(
            session_id=session_id,
            permanent=permanent
        )
        
        return {"message": f"Session {session_id} deleted successfully"}
    
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error deleting session: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete session")

