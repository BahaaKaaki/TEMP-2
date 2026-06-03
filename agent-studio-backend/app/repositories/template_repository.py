"""
Template repository for workflow PPTX template data access.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import WorkflowTemplate

logger = logging.getLogger(__name__)


class TemplateRepository:
    """Repository for workflow_template CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        workflow_id: str,
        agent_node_id: str,
        name: str,
        file_name: str,
        container_name: Optional[str] = None,
        blob_name: Optional[str] = None,
        blob_url: Optional[str] = None,
        placeholders: Optional[List[Dict[str, Any]]] = None,
        generated_schema: Optional[Dict[str, Any]] = None,
        created_by_id: str,
    ) -> WorkflowTemplate:
        """Insert a new template record."""
        row = WorkflowTemplate(
            id=str(uuid.uuid4()),
            workflowId=workflow_id,
            agentNodeId=agent_node_id,
            name=name,
            fileName=file_name,
            containerName=container_name,
            blobName=blob_name,
            blobUrl=blob_url,
            placeholders=json.dumps(placeholders) if placeholders else None,
            generatedSchema=json.dumps(generated_schema) if generated_schema else None,
            createdById=created_by_id,
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow(),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_by_id(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Fetch a single template by its primary key."""
        result = await self.db.execute(
            select(WorkflowTemplate).where(WorkflowTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def list_by_workflow(self, workflow_id: str) -> List[WorkflowTemplate]:
        """Return all templates belonging to a workflow."""
        result = await self.db.execute(
            select(WorkflowTemplate)
            .where(WorkflowTemplate.workflowId == workflow_id)
            .order_by(WorkflowTemplate.createdAt.desc())
        )
        return list(result.scalars().all())

    async def get_by_workflow_and_node(
        self, workflow_id: str, agent_node_id: str
    ) -> Optional[WorkflowTemplate]:
        """Get the template attached to a specific agent node."""
        result = await self.db.execute(
            select(WorkflowTemplate).where(
                and_(
                    WorkflowTemplate.workflowId == workflow_id,
                    WorkflowTemplate.agentNodeId == agent_node_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, template_id: str) -> bool:
        """Delete a template record.  Returns True if a row was removed."""
        row = await self.get_by_id(template_id)
        if not row:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def update_analysis(
        self,
        template_id: str,
        placeholders: List[Dict[str, Any]],
        generated_schema: Dict[str, Any],
    ) -> Optional[WorkflowTemplate]:
        """Update the cached placeholder / schema analysis on a template."""
        row = await self.get_by_id(template_id)
        if not row:
            return None
        row.placeholders = json.dumps(placeholders)
        row.generatedSchema = json.dumps(generated_schema)
        row.updatedAt = datetime.utcnow()
        await self.db.flush()
        return row
