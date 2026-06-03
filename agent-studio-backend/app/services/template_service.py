"""
Template service -- orchestrates PPTX template upload, analysis, and filling.

Workflow:
  1. Upload  -- store blob in Azure Storage, extract placeholders, generate
                JSON Schema, persist metadata in DB.
  2. Schema  -- return the cached generated schema for a template.
  3. Fill    -- download the template blob, fill it with deliverable data,
                return the populated PPTX bytes.
  4. Delete  -- remove blob + DB record.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from connectors import AzureStorageConnector
from db.models import WorkflowTemplate
from repositories.template_repository import TemplateRepository
from services.template_engine import (
    extract_placeholders,
    fill_template,
    generate_schema,
    sanitize_template,
)

logger = logging.getLogger(__name__)

TEMPLATE_BLOB_PREFIX = "workflow-templates"


class TemplateService:
    """High-level operations for workflow PPTX templates."""

    def __init__(
        self,
        repo: TemplateRepository,
        storage: AzureStorageConnector,
    ):
        self.repo = repo
        self.storage = storage

    async def upload_template(
        self,
        *,
        workflow_id: str,
        agent_node_id: str,
        file_name: str,
        file_bytes: bytes,
        user_id: str,
        template_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload, analyse, and persist a new PPTX template.

        Returns a dict with ``id``, ``placeholders``, and ``generatedSchema``.
        """
        template_id = str(uuid.uuid4())
        blob_name = (
            f"{TEMPLATE_BLOB_PREFIX}/{workflow_id}/"
            f"{template_id}_{file_name}"
        )

        logger.info(
            "Uploading template %s for workflow %s node %s (%d bytes)",
            file_name, workflow_id, agent_node_id, len(file_bytes),
        )

        file_bytes = sanitize_template(file_bytes)

        blob_url = await self.storage.upload_blob(
            blob_name=blob_name,
            data=file_bytes,
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".presentationml.presentation"
            ),
        )

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pptx", delete=False
            ) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            placeholders = extract_placeholders(tmp_path)
            schema = generate_schema(
                placeholders,
                title=template_name or os.path.splitext(file_name)[0],
            )
            placeholder_dicts = [asdict(p) for p in placeholders]
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        display_name = template_name or os.path.splitext(file_name)[0]

        existing = await self.repo.get_by_workflow_and_node(
            workflow_id, agent_node_id
        )
        if existing:
            logger.info(
                "Replacing existing template %s for node %s",
                existing.id, agent_node_id,
            )
            await self._delete_blob(existing.blobName)
            await self.repo.delete(existing.id)

        row = await self.repo.create(
            workflow_id=workflow_id,
            agent_node_id=agent_node_id,
            name=display_name,
            file_name=file_name,
            container_name=self.storage.container_name,
            blob_name=blob_name,
            blob_url=blob_url,
            placeholders=placeholder_dicts,
            generated_schema=schema,
            created_by_id=user_id,
        )
        await self.repo.db.commit()

        logger.info(
            "Template %s created with %d placeholders",
            row.id, len(placeholder_dicts),
        )

        return {
            "id": row.id,
            "name": row.name,
            "fileName": row.fileName,
            "placeholders": placeholder_dicts,
            "generatedSchema": schema,
        }

    async def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Return template metadata including cached schema."""
        row = await self.repo.get_by_id(template_id)
        if not row:
            return None
        return self._row_to_dict(row)

    async def get_template_schema(
        self, template_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return only the generated JSON Schema for a template."""
        row = await self.repo.get_by_id(template_id)
        if not row or not row.generatedSchema:
            return None
        return json.loads(row.generatedSchema)

    async def list_templates(self, workflow_id: str) -> List[Dict[str, Any]]:
        """List all templates for a workflow."""
        rows = await self.repo.list_by_workflow(workflow_id)
        return [self._row_to_dict(r) for r in rows]

    async def fill(
        self, template_id: str, data: Dict[str, Any]
    ) -> Optional[bytes]:
        """Download the template blob, fill it with *data*, return PPTX bytes."""
        row = await self.repo.get_by_id(template_id)
        if not row or not row.blobName:
            return None

        logger.info("Filling template %s with %d top-level keys", template_id, len(data))

        blob_bytes = await self.storage.download_blob(row.blobName)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pptx", delete=False
            ) as tmp:
                tmp.write(blob_bytes)
                tmp_path = tmp.name

            result = fill_template(tmp_path, data)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        logger.info(
            "Template %s filled successfully (%d bytes output)",
            template_id, len(result),
        )
        return result

    async def delete_template(self, template_id: str) -> bool:
        """Delete template blob and DB record."""
        row = await self.repo.get_by_id(template_id)
        if not row:
            return False

        await self._delete_blob(row.blobName)
        await self.repo.delete(template_id)
        await self.repo.db.commit()

        logger.info("Template %s deleted", template_id)
        return True

    async def _delete_blob(self, blob_name: Optional[str]) -> None:
        if not blob_name:
            return
        try:
            await self.storage.delete_blob(blob_name)
        except Exception:
            logger.warning("Could not delete blob %s", blob_name, exc_info=True)

    @staticmethod
    def _row_to_dict(row: WorkflowTemplate) -> Dict[str, Any]:
        return {
            "id": row.id,
            "workflowId": row.workflowId,
            "agentNodeId": row.agentNodeId,
            "name": row.name,
            "fileName": row.fileName,
            "blobUrl": row.blobUrl,
            "placeholders": json.loads(row.placeholders) if row.placeholders else [],
            "generatedSchema": json.loads(row.generatedSchema) if row.generatedSchema else None,
            "createdById": row.createdById,
            "createdAt": row.createdAt.isoformat() if row.createdAt else None,
            "updatedAt": row.updatedAt.isoformat() if row.updatedAt else None,
        }
