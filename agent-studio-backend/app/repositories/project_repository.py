"""
Project repository for data access.
"""
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_
from datetime import datetime
import logging

from .base import BaseRepository
from db.models import Project, ChatSession

logger = logging.getLogger(__name__)


class ProjectRepository(BaseRepository[Project, Project]):
    """Repository for project data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, Project)

    async def get_by_id_for_user(self, project_id: str, user_id: str) -> Optional[Project]:
        """Get project by ID, scoped to user."""
        query = select(Project).where(
            Project.id == project_id,
            Project.userId == user_id,
            Project.isArchived == False,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> List[Tuple[Project, int]]:
        """List all active projects for a user with session counts."""
        session_count = (
            select(func.count(ChatSession.id))
            .where(
                ChatSession.projectId == Project.id,
                ChatSession.deletedAt == None,
            )
            .correlate(Project)
            .scalar_subquery()
        )

        query = (
            select(Project, session_count.label("session_count"))
            .where(
                Project.userId == user_id,
                Project.isArchived == False,
            )
            .order_by(Project.updatedAt.desc())
        )
        result = await self.db.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def create_project(
        self,
        project_id: str,
        name: str,
        user_id: str,
        description: Optional[str] = None,
    ) -> Project:
        """Create a new project."""
        project = Project(
            id=project_id,
            name=name,
            description=description,
            userId=user_id,
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow(),
        )
        await self.create(project)
        return project

    async def update_project(
        self,
        project_id: str,
        user_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[Project]:
        """Update project name/description."""
        project = await self.get_by_id_for_user(project_id, user_id)
        if not project:
            return None

        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        project.updatedAt = datetime.utcnow()

        await self.db.flush()
        return project

    async def soft_delete(self, project_id: str, user_id: str) -> bool:
        """Soft-delete a project and unassign all its sessions."""
        project = await self.get_by_id_for_user(project_id, user_id)
        if not project:
            return False

        project.isArchived = True
        project.updatedAt = datetime.utcnow()

        await self.db.execute(
            update(ChatSession)
            .where(ChatSession.projectId == project_id)
            .values(projectId=None, updatedAt=datetime.utcnow())
        )

        await self.db.flush()
        return True

    async def assign_session(
        self, project_id: str, session_id: str, user_id: str
    ) -> bool:
        """Assign a session to a project. Both must belong to the user."""
        project = await self.get_by_id_for_user(project_id, user_id)
        if not project:
            return False

        query = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.userId == user_id,
            ChatSession.deletedAt == None,
        )
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()
        if not session:
            return False

        session.projectId = project_id
        session.updatedAt = datetime.utcnow()
        await self.db.flush()
        return True

    async def remove_session(self, project_id: str, session_id: str, user_id: str) -> bool:
        """Remove a session from a project (unassign)."""
        query = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.projectId == project_id,
            ChatSession.userId == user_id,
        )
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()
        if not session:
            return False

        session.projectId = None
        session.updatedAt = datetime.utcnow()
        await self.db.flush()
        return True

    async def get_session_count(self, project_id: str) -> int:
        """Get the number of active sessions in a project."""
        query = select(func.count(ChatSession.id)).where(
            ChatSession.projectId == project_id,
            ChatSession.deletedAt == None,
        )
        result = await self.db.execute(query)
        return result.scalar() or 0
