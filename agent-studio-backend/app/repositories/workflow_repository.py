"""
Workflow repository for data access.
"""
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from .base import BaseRepository
from db.models import WorkflowEntity, WorkflowHistory
from domain.entities import Workflow
from workflow_share_approval import is_distribution_gated

logger = logging.getLogger(__name__)


@dataclass
class EffectiveWorkflowData:
    """The resolved nodes/connections/settings for a workflow.

    For marketplace workflows with an approved snapshot, these come
    from ``workflow_history``; otherwise they come from the live row.
    """
    nodes: Optional[str]
    connections: Optional[str]
    settings: Optional[str]
    source: str  # "approved_snapshot" | "published_snapshot" | "live"


async def get_effective_workflow_data(
    workflow: WorkflowEntity,
    db: AsyncSession,
    *,
    is_owner: bool = False,
    can_edit: bool = False,
) -> EffectiveWorkflowData:
    """Single source of truth for which workflow data a consumer should see.

    Rules:
    - **Owner** or **write share** (``can_edit``): live row — current working copy.
    - **Marketplace non-owner** (``isPublic`` and ``approvedVersionId``):
      return the admin-approved snapshot.
    - **Read-only shared non-owner** (``versionId`` set): published snapshot.
    - **Fallback**: return the live row data.
    """
    logger.debug(
        "get_effective_workflow_data: wf=%s isPublic=%s approvedVersionId=%s "
        "versionId=%s is_owner=%s",
        workflow.id, workflow.isPublic, workflow.approvedVersionId,
        workflow.versionId, is_owner,
    )

    # Editors (owner or write share) work on the live graph; if live is empty
    # but a published version exists, fall back so the builder is not blank.
    if is_owner or can_edit:
        live_nodes = (workflow.nodes or "").strip()
        if live_nodes and live_nodes not in ("[]", "null"):
            logger.debug("get_effective_workflow_data: returning LIVE data for wf=%s (editor)", workflow.id)
            return EffectiveWorkflowData(
                nodes=workflow.nodes,
                connections=workflow.connections,
                settings=workflow.settings,
                source="live",
            )
        if workflow.versionId:
            snap = await _fetch_snapshot(db, workflow.versionId)
            if snap and (snap.nodes or "").strip() not in ("", "[]"):
                logger.debug(
                    "get_effective_workflow_data: live empty, using published v%s for editor wf=%s",
                    workflow.versionId, workflow.id,
                )
                return EffectiveWorkflowData(
                    nodes=snap.nodes,
                    connections=snap.connections,
                    settings=snap.settings,
                    source="published_snapshot",
                )
        logger.debug("get_effective_workflow_data: returning LIVE data for wf=%s (editor, empty)", workflow.id)
        return EffectiveWorkflowData(
            nodes=workflow.nodes,
            connections=workflow.connections,
            settings=workflow.settings,
            source="live",
        )

    gated = await is_distribution_gated(db, workflow.id)

    # Marketplace or gated distribution: use approved snapshot for non-owners.
    if (workflow.isPublic or gated) and workflow.approvedVersionId:
        snap = await _fetch_snapshot(db, workflow.approvedVersionId)
        if snap:
            logger.debug("get_effective_workflow_data: returning approved_snapshot for wf=%s", workflow.id)
            return EffectiveWorkflowData(
                nodes=snap.nodes,
                connections=snap.connections,
                settings=snap.settings,
                source="approved_snapshot",
            )
        logger.warning(
            "Approved snapshot %s not found for workflow %s, falling back to live",
            workflow.approvedVersionId, workflow.id,
        )

    if gated and not workflow.approvedVersionId:
        logger.debug(
            "get_effective_workflow_data: gated wf=%s has no approvedVersionId yet",
            workflow.id,
        )
        return EffectiveWorkflowData(
            nodes="[]",
            connections="[]",
            settings=workflow.settings,
            source="approved_snapshot",
        )

    # Read-only shared / chat: use published snapshot (non-gated shares)
    if workflow.versionId:
        snap = await _fetch_snapshot(db, workflow.versionId)
        if snap:
            logger.debug("get_effective_workflow_data: returning published_snapshot for wf=%s", workflow.id)
            return EffectiveWorkflowData(
                nodes=snap.nodes,
                connections=snap.connections,
                settings=snap.settings,
                source="published_snapshot",
            )

    logger.debug("get_effective_workflow_data: returning LIVE data for wf=%s", workflow.id)
    return EffectiveWorkflowData(
        nodes=workflow.nodes,
        connections=workflow.connections,
        settings=workflow.settings,
        source="live",
    )


async def _fetch_snapshot(
    db: AsyncSession, version_id: str
) -> Optional[WorkflowHistory]:
    result = await db.execute(
        select(WorkflowHistory).where(WorkflowHistory.versionId == version_id)
    )
    return result.scalar_one_or_none()


class WorkflowRepository(BaseRepository[WorkflowEntity, Workflow]):
    """Repository for workflow data access."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, WorkflowEntity)
    
    async def get_by_id(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow by ID."""
        query = select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        result = await self.db.execute(query)
        db_workflow = result.scalar_one_or_none()
        
        if not db_workflow:
            return None
        
        return self._to_domain(db_workflow)

    async def get_effective_by_id(
        self,
        workflow_id: str,
        *,
        user_id: Optional[str] = None,
    ) -> Optional[Workflow]:
        """Get workflow with effective (possibly snapshot) data applied.

        Use this instead of ``get_by_id`` when the consumer needs
        nodes/connections that respect marketplace or sharing rules.
        """
        query = select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        result = await self.db.execute(query)
        db_workflow = result.scalar_one_or_none()
        if not db_workflow:
            return None

        is_owner = bool(
            user_id and str(user_id) == str(db_workflow.createdById)
        )
        can_edit = is_owner
        if not can_edit and user_id:
            from services.sharing_access import can_write, resolve_workflow_share_access

            access = await resolve_workflow_share_access(
                self.db,
                db_workflow.id,
                user_id,
                owner_id=db_workflow.createdById,
            )
            can_edit = can_write(access)
        eff = await get_effective_workflow_data(
            db_workflow, self.db, is_owner=is_owner, can_edit=can_edit,
        )
        db_workflow.nodes = eff.nodes
        db_workflow.connections = eff.connections
        db_workflow.settings = eff.settings
        return self._to_domain(db_workflow)

    def _to_domain(self, db_workflow: WorkflowEntity) -> Workflow:
        """Convert database model to domain entity."""
        return Workflow(
            id=db_workflow.id,
            name=db_workflow.name,
            active=db_workflow.active,
            nodes=db_workflow.nodes,
            connections=db_workflow.connections,
            settings=db_workflow.settings,
            static_data=db_workflow.staticData,
            pin_data=db_workflow.pinData,
            version_id=db_workflow.versionId,
            trigger_count=db_workflow.triggerCount,
            meta=db_workflow.meta,
            parent_folder_id=db_workflow.parentFolderId,
            created_at=db_workflow.createdAt,
            updated_at=db_workflow.updatedAt,
            is_archived=db_workflow.isArchived
        )

