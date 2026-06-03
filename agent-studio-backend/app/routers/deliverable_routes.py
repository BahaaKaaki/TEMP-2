"""
Deliverable management routes for HITL workflows.
"""
from fastapi import APIRouter, Depends, HTTPException
import logging

from services import DeliverableService
from core.dependencies import get_deliverable_service, get_current_user
from db.models import User
from core.exceptions import (
    DeliverableNotFoundException,
    DeliverableNotPendingException,
    DomainException
)
from schemas import (
    DeliverableResponse,
    DeliverableListResponse,
    DeliverableApprovalRequest,
    DeliverableRejectionRequest,
    DeliverableApprovalResponse,
    DeliverableWidgetResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["Deliverables"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


@router.get(
    "/sessions/{session_id}/deliverables",
    response_model=DeliverableListResponse
)
async def list_session_deliverables(
    session_id: str,
    current_user: User = Depends(get_current_user),
    deliverable_service: DeliverableService = Depends(get_deliverable_service)
):
    """List all deliverables for a chat session."""
    try:
        deliverables = await deliverable_service.list_session_deliverables(session_id)
        
        items = []
        for d in deliverables:
            dd = d.get_deliverable_dict()
            items.append(
                DeliverableResponse(
                    id=d.id,
                    sessionId=d.session_id,
                    executionId=d.execution_id,
                    agentId=d.agent_id,
                    agentLabel=d.agent_label,
                    agentType=d.agent_type,
                    deliverable=dd,
                    deliverableSchema=d.deliverable_schema,
                    status=d.status,
                    iteration=d.iteration,
                    reviewedAt=d.reviewed_at,
                    reviewedBy=d.reviewed_by,
                    reviewNotes=d.review_notes,
                    previousDeliverableId=d.previous_deliverable_id,
                    createdAt=d.created_at,
                    updatedAt=d.updated_at,
                    outputType=dd.get("_output_type") if isinstance(dd, dict) else None,
                    interactive=bool(dd.get("_interactive")) if isinstance(dd, dict) else False,
                    userResponse=dd.get("_user_response") if isinstance(dd, dict) else None,
                    openuiLang=getattr(d, "openui_lang", None),
                )
            )

        return DeliverableListResponse(
            session_id=session_id,
            total=len(items),
            deliverables=items,
        )
    
    except Exception as e:
        logger.error("Error listing deliverables: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list deliverables")


@router.get(
    "/deliverables/{deliverable_id}",
    response_model=DeliverableResponse
)
async def get_deliverable(
    deliverable_id: str,
    current_user: User = Depends(get_current_user),
    deliverable_service: DeliverableService = Depends(get_deliverable_service)
):
    """Get details of a specific deliverable."""
    try:
        d = await deliverable_service.get_deliverable(deliverable_id)
        dd = d.get_deliverable_dict()
        
        return DeliverableResponse(
            id=d.id,
            sessionId=d.session_id,
            executionId=d.execution_id,
            agentId=d.agent_id,
            agentLabel=d.agent_label,
            agentType=d.agent_type,
            deliverable=dd,
            deliverableSchema=d.deliverable_schema,
            status=d.status,
            iteration=d.iteration,
            reviewedAt=d.reviewed_at,
            reviewedBy=d.reviewed_by,
            reviewNotes=d.review_notes,
            previousDeliverableId=d.previous_deliverable_id,
            createdAt=d.created_at,
            updatedAt=d.updated_at,
            outputType=dd.get("_output_type") if isinstance(dd, dict) else None,
            interactive=bool(dd.get("_interactive")) if isinstance(dd, dict) else False,
            userResponse=dd.get("_user_response") if isinstance(dd, dict) else None,
            openuiLang=getattr(d, "openui_lang", None),
        )

    except DeliverableNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error getting deliverable: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get deliverable")


@router.post(
    "/deliverables/{deliverable_id}/approve",
    response_model=DeliverableApprovalResponse
)
async def approve_deliverable(
    deliverable_id: str,
    approval_request: DeliverableApprovalRequest,
    current_user: User = Depends(get_current_user),
    deliverable_service: DeliverableService = Depends(get_deliverable_service)
):
    """Approve a deliverable and resume workflow execution."""
    try:
        result = await deliverable_service.approve_deliverable(
            deliverable_id=deliverable_id,
            reviewed_by=approval_request.reviewed_by or str(current_user.id),
            review_notes=approval_request.review_notes,
            edited_deliverable=approval_request.edited_deliverable
        )
        
        return DeliverableApprovalResponse(
            deliverable_id=result["deliverable_id"],
            status=result["status"],
            workflow_resumed=result["workflow_resumed"],
            next_agent=result.get("next_agent"),
            startup_message=result.get("startup_message"),
            startup_message_full=result.get("startup_message_full"),
            message=result["message"]
        )
    
    except DeliverableNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DeliverableNotPendingException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error approving deliverable: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to approve deliverable")


@router.post(
    "/deliverables/{deliverable_id}/reject",
    response_model=DeliverableApprovalResponse
)
async def reject_deliverable(
    deliverable_id: str,
    rejection_request: DeliverableRejectionRequest,
    current_user: User = Depends(get_current_user),
    deliverable_service: DeliverableService = Depends(get_deliverable_service)
):
    """Reject a deliverable and provide feedback."""
    try:
        result = await deliverable_service.reject_deliverable(
            deliverable_id=deliverable_id,
            reviewed_by=rejection_request.reviewed_by or str(current_user.id),
            review_notes=rejection_request.review_notes
        )
        
        return DeliverableApprovalResponse(
            deliverable_id=result["deliverable_id"],
            status=result["status"],
            workflow_resumed=result["workflow_resumed"],
            next_agent=result.get("next_agent"),
            startup_message=result.get("startup_message"),
            startup_message_full=result.get("startup_message_full"),
            message=result["message"]
        )
    
    except DeliverableNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DeliverableNotPendingException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error rejecting deliverable: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reject deliverable")


@router.post(
    "/deliverables/{deliverable_id}/respond",
    response_model=DeliverableApprovalResponse,
)
async def respond_to_widget(
    deliverable_id: str,
    body: DeliverableWidgetResponse,
    current_user: User = Depends(get_current_user),
    deliverable_service: DeliverableService = Depends(get_deliverable_service),
):
    """Accept a user's response to an interactive widget and resume the workflow.

    Works like approve but also stores the widget response so that downstream
    nodes can read it from the deliverable.
    """
    try:
        result = await deliverable_service.respond_to_widget(
            deliverable_id=deliverable_id,
            user_response=body.response,
            reviewed_by=body.reviewed_by or str(current_user.id),
        )

        return DeliverableApprovalResponse(
            deliverable_id=result["deliverable_id"],
            status=result["status"],
            workflow_resumed=result["workflow_resumed"],
            next_agent=result.get("next_agent"),
            startup_message=result.get("startup_message"),
            startup_message_full=result.get("startup_message_full"),
            message=result["message"],
            # Post-resume snapshot: lets the UI render the next ask
            # deliverable synchronously for chained output.ask() sequences
            # without waiting for (or racing with) a follow-up GET.
            updated_deliverables=result.get("updated_deliverables"),
            execution_status=result.get("execution_status"),
            execution_id=result.get("execution_id"),
        )

    except DeliverableNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DeliverableNotPendingException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error responding to widget: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process widget response")


@router.post("/deliverables/{deliverable_id}/edwin-handoff")
async def create_deliverable_edwin_handoff(
    deliverable_id: str,
    current_user: User = Depends(get_current_user),
    deliverable_service: DeliverableService = Depends(get_deliverable_service),
):
    """Create an on-demand Edwin handoff for a single deliverable.

    Mirrors the powerpoint_generator workflow node, but is triggered by the
    user from the deliverable export menu. Returns ``{id, url}`` for the
    frontend to open Edwin in a new tab.
    """
    # Lazy imports avoid the repositories -> workflow -> services import cycle.
    from services.edwin_handoff_service import EdwinHandoffError, create_handoff
    from workflow.state import format_deliverables_as_markdown

    try:
        d = await deliverable_service.get_deliverable(deliverable_id)
        entry = {
            "agent_label": d.agent_label,
            "agent_type": d.agent_type,
            "status": d.status,
            "deliverable": d.get_deliverable_dict(),
        }
        markdown = format_deliverables_as_markdown([entry])
        if not markdown.strip():
            raise HTTPException(
                status_code=422,
                detail="Deliverable could not be formatted for Edwin.",
            )

        handoff = await create_handoff(
            question="Create a presentation from this deliverable.",
            answer=markdown,
            suggested_prompt="Create a presentation from the deliverable above.",
        )
        return {"id": handoff.get("id", ""), "url": handoff.get("url", "")}

    except DeliverableNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except EdwinHandoffError as e:
        logger.error("Edwin handoff failed for deliverable %s: %s", deliverable_id, e)
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating Edwin handoff: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create Edwin handoff")
