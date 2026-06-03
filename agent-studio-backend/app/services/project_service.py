"""
Project service for business logic.
"""
from typing import Optional, List, Dict, Any
import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseService
from repositories.project_repository import ProjectRepository
from core.exceptions import DomainException

logger = logging.getLogger(__name__)


class ProjectNotFoundException(DomainException):
    def __init__(self, project_id: str):
        super().__init__(f"Project {project_id} not found")


class ProjectService(BaseService):
    """Service for project business logic."""

    def __init__(self, db: AsyncSession, project_repo: ProjectRepository):
        super().__init__(db)
        self.project_repo = project_repo

    async def create_project(
        self,
        name: str,
        user_id: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new project."""
        project_id = str(uuid.uuid4())

        project = await self.project_repo.create_project(
            project_id=project_id,
            name=name,
            user_id=user_id,
            description=description,
        )
        await self.commit()

        logger.debug("Created project %s for user %s", project_id, user_id)
        return {"project": project, "session_count": 0}

    async def list_projects(self, user_id: str) -> List[Dict[str, Any]]:
        """List all projects for a user with session counts."""
        rows = await self.project_repo.list_for_user(user_id)
        return [
            {"project": project, "session_count": count}
            for project, count in rows
        ]

    async def get_project(self, project_id: str, user_id: str) -> Dict[str, Any]:
        """Get a single project."""
        project = await self.project_repo.get_by_id_for_user(project_id, user_id)
        if not project:
            raise ProjectNotFoundException(project_id)

        count = await self.project_repo.get_session_count(project_id)
        return {"project": project, "session_count": count}

    async def update_project(
        self,
        project_id: str,
        user_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update project metadata."""
        project = await self.project_repo.update_project(
            project_id, user_id, name=name, description=description
        )
        if not project:
            raise ProjectNotFoundException(project_id)

        await self.commit()
        count = await self.project_repo.get_session_count(project_id)
        return {"project": project, "session_count": count}

    async def delete_project(self, project_id: str, user_id: str) -> None:
        """Soft-delete a project and unassign its sessions."""
        deleted = await self.project_repo.soft_delete(project_id, user_id)
        if not deleted:
            raise ProjectNotFoundException(project_id)
        await self.commit()
        logger.debug("Deleted project %s", project_id)

    async def assign_session(
        self, project_id: str, session_id: str, user_id: str
    ) -> None:
        """Assign a session to a project."""
        ok = await self.project_repo.assign_session(project_id, session_id, user_id)
        if not ok:
            raise DomainException(
                "Could not assign session — project or session not found"
            )
        await self.commit()

    async def remove_session(
        self, project_id: str, session_id: str, user_id: str
    ) -> None:
        """Remove a session from a project."""
        ok = await self.project_repo.remove_session(project_id, session_id, user_id)
        if not ok:
            raise DomainException(
                "Could not remove session — session not found in this project"
            )
        await self.commit()
