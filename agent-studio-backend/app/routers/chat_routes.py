"""
Chat message routes.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
import logging
import json

from services import ChatService, CheckpointService
from core.dependencies import get_chat_service, get_current_user, get_checkpoint_service
from db.models import User
from core.exceptions import (
    SessionNotFoundException,
    SessionNotActiveException,
    WorkflowNotActiveException,
    DomainException,
    MessageTooLongException,
    ValidationException,
    CheckpointNotFoundException,
    RevertConflictException,
)
from schemas import (
    SendMessageRequest,
    SessionChatResponse,
    ChatMessage,
    CheckpointListResponse,
    CheckpointSummary,
    RevertResponse,
)
from config.settings import settings
from utils.rate_limit import rate_limit_chat

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["Chat Messages"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SessionChatResponse
)
@rate_limit_chat()
async def send_message_to_session(
    request: Request,
    response: Response,
    session_id: str,
    message_request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Send a message to a specific chat session/instance.
    
    Rate limit: 10 requests per minute per IP address.
    """
    try:
        # Validate message length
        if message_request.message and len(message_request.message) > settings.MAX_MESSAGE_LENGTH:
            raise MessageTooLongException(
                length=len(message_request.message),
                max_length=settings.MAX_MESSAGE_LENGTH
            )
        
        # Validate variables size (prevent memory exhaustion from huge JSON)
        if message_request.variables:
            variables_json = json.dumps(message_request.variables)
            if len(variables_json) > settings.MAX_VARIABLES_SIZE:
                raise ValidationException(
                    f"Variables too large ({len(variables_json):,} chars). "
                    f"Maximum allowed: {settings.MAX_VARIABLES_SIZE:,} characters",
                    field="variables"
                )
        
        response = await chat_service.send_message(
            session_id=session_id,
            message=message_request.message,
            variables=message_request.variables,
            user_id=current_user.id,
            force_deliver=message_request.force_deliver,
            question_message_id=message_request.question_message_id,
            question_response=message_request.question_response,
        )
        
        return SessionChatResponse(
            session_id=response["session_id"],
            message=response["message"],
            role=response["role"],
            timestamp=response["timestamp"],
            status=response["status"],
            execution_id=response.get("execution_id"),
            conversation_history=[
                ChatMessage(
                    message_id=m.get("message_id"),
                    role=m["role"],
                    content=m["content"],
                    timestamp=m.get("timestamp"),
                    agent_id=m.get("agent_id"),
                    agent_label=m.get("agent_label"),
                    agent_type=m.get("agent_type"),
                    citations=m.get("citations"),
                    structured_queries=m.get("structured_queries"),
                    questions=m.get("questions"),
                    answered_at=m.get("answered_at"),
                )
                for m in response["conversation_history"]
            ],
            pending_deliverable=response.get("pending_deliverable")
        )
    
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SessionNotActiveException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except WorkflowNotActiveException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValidationException as e:
        # Return 413 for size-related validation errors
        if isinstance(e, MessageTooLongException):
            raise HTTPException(status_code=413, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error sending message: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send message")


# ============================================================================
# Checkpoint / Revert Endpoints
# ============================================================================

@router.get(
    "/sessions/{session_id}/checkpoints",
    response_model=CheckpointListResponse,
)
async def list_checkpoints(
    session_id: str,
    current_user: User = Depends(get_current_user),
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """List all checkpoints for a session (used by frontend to show revert buttons)."""
    try:
        checkpoints = await checkpoint_service.list_checkpoints(session_id)
        return CheckpointListResponse(
            checkpoints=[
                CheckpointSummary(
                    id=c.id,
                    user_message_id=c.user_message_id,
                    step_index=c.step_index,
                    created_at=c.created_at.isoformat() if c.created_at else "",
                )
                for c in checkpoints
            ]
        )
    except Exception as e:
        logger.error("Error listing checkpoints: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list checkpoints")


@router.post(
    "/sessions/{session_id}/revert/{checkpoint_id}",
    response_model=RevertResponse,
)
async def revert_to_checkpoint(
    session_id: str,
    checkpoint_id: str,
    current_user: User = Depends(get_current_user),
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """
    Revert a session to the state captured before a specific user message.
    Restores messages, deliverables, execution status -- everything.
    Returns the restored conversation history and the user message to prefill.
    """
    try:
        result = await checkpoint_service.revert_to_checkpoint(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            user_id=current_user.id,
        )

        return RevertResponse(
            session_id=result["session_id"],
            checkpoint_id=result["checkpoint_id"],
            conversation_history=[
                ChatMessage(
                    message_id=m.get("message_id"),
                    role=m["role"],
                    content=m["content"],
                    timestamp=m.get("timestamp"),
                    agent_id=m.get("agent_id"),
                    agent_label=m.get("agent_label"),
                    agent_type=m.get("agent_type"),
                    citations=m.get("citations"),
                    structured_queries=m.get("structured_queries"),
                    questions=m.get("questions"),
                    answered_at=m.get("answered_at"),
                )
                for m in result.get("conversation_history", [])
            ],
            prefill_message=result["prefill_message"],
            deliverables=result.get("deliverables", []),
            pending_deliverable=result.get("pending_deliverable"),
            status=result.get("status", "active"),
        )

    except CheckpointNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RevertConflictException as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error reverting to checkpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to revert to checkpoint")
