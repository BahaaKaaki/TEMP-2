"""
Project management routes.
"""
from fastapi import APIRouter, Depends, HTTPException
import logging

from services.project_service import ProjectService, ProjectNotFoundException
from core.dependencies import get_project_service, get_current_user
from core.exceptions import DomainException
from db.models import User
from schemas import (
    CreateProjectRequest,
    UpdateProjectRequest,
    AssignSessionRequest,
    ProjectResponse,
    ProjectListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/projects",
    tags=["Projects"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


def _to_response(data: dict) -> ProjectResponse:
    p = data["project"]
    return ProjectResponse(
        id=p.id,
        name=p.name,
        description=p.description,
        userId=p.userId,
        createdAt=p.createdAt,
        updatedAt=p.updatedAt,
        sessionCount=data["session_count"],
    )


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """Create a new project."""
    try:
        data = await service.create_project(
            name=body.name,
            user_id=current_user.id,
            description=body.description,
        )
        return _to_response(data)
    except Exception as e:
        logger.error("Error creating project: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create project")


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """List all projects for the authenticated user."""
    try:
        items = await service.list_projects(current_user.id)
        return ProjectListResponse(
            items=[_to_response(d) for d in items],
            total=len(items),
        )
    except Exception as e:
        logger.error("Error listing projects: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list projects")


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """Get a single project."""
    try:
        data = await service.get_project(project_id, current_user.id)
        return _to_response(data)
    except ProjectNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error getting project: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get project")


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """Update a project's name or description."""
    try:
        data = await service.update_project(
            project_id=project_id,
            user_id=current_user.id,
            name=body.name,
            description=body.description,
        )
        return _to_response(data)
    except ProjectNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error updating project: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update project")


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """Soft-delete a project. Sessions are unassigned, not deleted."""
    try:
        await service.delete_project(project_id, current_user.id)
    except ProjectNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error deleting project: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete project")


@router.post("/{project_id}/sessions", status_code=204)
async def assign_session_to_project(
    project_id: str,
    body: AssignSessionRequest,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """Assign an existing session to this project."""
    try:
        await service.assign_session(project_id, body.session_id, current_user.id)
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error assigning session: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to assign session")


@router.delete("/{project_id}/sessions/{session_id}", status_code=204)
async def remove_session_from_project(
    project_id: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """Remove a session from this project (unassign, not delete)."""
    try:
        await service.remove_session(project_id, session_id, current_user.id)
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error removing session from project: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to remove session")
