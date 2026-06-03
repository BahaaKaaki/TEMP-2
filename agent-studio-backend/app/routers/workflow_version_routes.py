"""
Workflow version history and marketplace-update endpoints.

Mounted under /api/workflows/{workflow_id}/versions (history CRUD)
and         /api/workflows/{workflow_id}          (check-updates, pull-update).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text as sql_text
from datetime import datetime
import json
import logging

from db.models import WorkflowEntity, WorkflowHistory, User
from core.dependencies import get_current_user, get_db_with_user_context
from services.sharing_access import can_write, resolve_workflow_share_access
from schemas import (
    WorkflowVersionResponse,
    WorkflowVersionSummaryListResponse,
    WorkflowVersionSummaryResponse,
    WorkflowVersionNameUpdate,
    WorkflowUpdateCheckResponse,
    WorkflowEntityResponse,
)
from services.workflow_version_service import (
    list_versions,
    get_version_by_id,
    get_published_snapshot,
    create_version_snapshot,
)
from utils.errors import safe_error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/workflows",
    tags=["Workflow Versions"],
    dependencies=[Depends(get_current_user)],
)


# ============================================================================
# VERSION HISTORY CRUD
# ============================================================================

@router.get(
    "/{workflow_id}/versions",
    response_model=WorkflowVersionSummaryListResponse,
)
async def list_workflow_versions(
    workflow_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """List version history for a workflow (newest first, lightweight summaries)."""
    try:
        workflow = await _get_workflow_or_404(db, workflow_id)
        rows, total = await list_versions(db, workflow.id, page=page, page_size=page_size)
        total_pages = (total + page_size - 1) // page_size if page_size else 1

        return WorkflowVersionSummaryListResponse(
            workflowId=workflow.id,
            total=total,
            items=[
                WorkflowVersionSummaryResponse(
                    versionId=v.versionId,
                    versionNumber=v.versionNumber,
                    authors=v.authors,
                    description=v.description,
                    isPublishedSnapshot=v.isPublishedSnapshot,
                    event=v.event,
                    createdAt=v.createdAt,
                )
                for v in rows
            ],
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to list versions")) from e


@router.get(
    "/{workflow_id}/versions/{version_id}",
    response_model=WorkflowVersionResponse,
)
async def get_workflow_version(
    workflow_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """Get a specific version's full snapshot (includes nodes/connections)."""
    try:
        await _get_workflow_or_404(db, workflow_id)
        version = await get_version_by_id(db, workflow_id, version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")
        return version
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to get version")) from e


@router.post(
    "/{workflow_id}/versions/{version_id}/restore",
    response_model=WorkflowEntityResponse,
)
async def restore_workflow_version(
    workflow_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Restore a workflow to a previous version.

    Creates a new version with event='restore' and updates the workflow
    entity's draft columns. Does NOT auto-publish -- the user must
    explicitly publish if they want the restored content to go live.
    """
    try:
        workflow = await _get_workflow_or_404(db, workflow_id)
        access = await resolve_workflow_share_access(
            db, workflow.id, current_user.id, owner_id=workflow.createdById
        )
        if not can_write(access):
            raise HTTPException(
                status_code=403,
                detail="You have read-only access to this workflow",
            )
        old_version = await get_version_by_id(db, workflow_id, version_id)
        if not old_version:
            raise HTTPException(status_code=404, detail="Version not found")

        workflow.nodes = old_version.nodes
        workflow.connections = old_version.connections
        workflow.settings = old_version.settings

        author = _author_name(current_user)
        await create_version_snapshot(
            db, workflow,
            author_name=author,
            event="restore",
            description=f"Restored from v{old_version.versionNumber}",
        )

        await db.commit()
        logger.info("Restored workflow %s to v%d", workflow_id, old_version.versionNumber)
        return workflow

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to restore version")) from e


@router.patch(
    "/{workflow_id}/versions/{version_id}/name",
    response_model=WorkflowVersionResponse,
)
async def update_version_name(
    workflow_id: str,
    version_id: str,
    body: WorkflowVersionNameUpdate,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """Label a version with a human-readable description."""
    try:
        await _get_workflow_or_404(db, workflow_id)
        version = await get_version_by_id(db, workflow_id, version_id)
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")

        version.description = body.description
        await db.commit()
        return version
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to update version name")) from e


# ============================================================================
# MARKETPLACE IMPORT UPDATE ENDPOINTS
# ============================================================================

@router.get(
    "/{workflow_id}/check-updates",
    response_model=WorkflowUpdateCheckResponse,
)
async def check_marketplace_updates(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Check whether a marketplace-imported workflow has a newer published
    version available from the source.
    """
    try:
        workflow = await _get_workflow_or_404(db, workflow_id)
        meta = _parse_meta(workflow.meta)

        source_id = meta.get("sourceMarketplaceId")
        if not source_id:
            return WorkflowUpdateCheckResponse(
                hasUpdate=False,
                currentVersionId=meta.get("sourceVersionId"),
                sourceWorkflowId=None,
            )

        source_vid = await _get_source_published_version_id(db, source_id)
        current_vid = meta.get("sourceVersionId")

        has_update = bool(source_vid and source_vid != current_vid)
        return WorkflowUpdateCheckResponse(
            hasUpdate=has_update,
            currentVersionId=current_vid,
            availableVersionId=source_vid if has_update else None,
            sourceWorkflowId=source_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to check updates")) from e


@router.post(
    "/{workflow_id}/pull-update",
    response_model=WorkflowEntityResponse,
)
async def pull_marketplace_update(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Pull the latest published version from the source marketplace workflow
    into this imported workflow.
    """
    try:
        workflow = await _get_workflow_or_404(db, workflow_id)
        meta = _parse_meta(workflow.meta)

        source_id = meta.get("sourceMarketplaceId")
        if not source_id:
            raise HTTPException(status_code=400, detail="This workflow is not a marketplace import")

        source_snapshot = await _get_source_published_snapshot(db, source_id)
        if not source_snapshot:
            raise HTTPException(status_code=404, detail="Source workflow has no published version")

        if meta.get("sourceVersionId") == source_snapshot.versionId:
            raise HTTPException(status_code=400, detail="Already up to date")

        workflow.nodes = source_snapshot.nodes
        workflow.connections = source_snapshot.connections
        workflow.settings = source_snapshot.settings

        meta["sourceVersionId"] = source_snapshot.versionId
        meta["lastUpdatedAt"] = datetime.utcnow().isoformat()
        workflow.meta = json.dumps(meta)

        author = _author_name(current_user)
        await create_version_snapshot(
            db, workflow,
            author_name=author,
            event="import_update",
            description=f"Updated from marketplace source v{source_snapshot.versionNumber}",
        )

        await db.commit()
        logger.info("Pulled update for workflow %s from source %s", workflow_id, source_id)
        return workflow

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to pull update")) from e


# ============================================================================
# HELPERS
# ============================================================================

async def _get_workflow_or_404(db: AsyncSession, workflow_id: str) -> WorkflowEntity:
    result = await db.execute(
        select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return workflow


def _parse_meta(meta_str: str | None) -> dict:
    if not meta_str:
        return {}
    try:
        return json.loads(meta_str) if isinstance(meta_str, str) else meta_str
    except (json.JSONDecodeError, TypeError):
        return {}


def _author_name(user: User) -> str:
    name = f"{user.firstName or ''} {user.lastName or ''}".strip()
    return name or user.email


async def _get_source_published_version_id(db: AsyncSession, source_workflow_id: str) -> str | None:
    """Get the versionId of the source workflow (bypasses RLS via raw SQL for public data)."""
    result = await db.execute(
        sql_text(
            'SELECT "versionId" FROM workflow_entity '
            'WHERE id = :wid AND "isPublic" = true'
        ),
        {"wid": source_workflow_id},
    )
    row = result.fetchone()
    return row[0] if row else None


async def _get_source_published_snapshot(
    db: AsyncSession, source_workflow_id: str
) -> WorkflowHistory | None:
    """Get the published snapshot from the source (bypasses RLS via raw SQL)."""
    vid = await _get_source_published_version_id(db, source_workflow_id)
    if not vid:
        return None
    result = await db.execute(
        sql_text(
            "SELECT * FROM workflow_history "
            'WHERE "versionId" = :vid AND "workflowId" = :wid'
        ),
        {"vid": vid, "wid": source_workflow_id},
    )
    row = result.fetchone()
    if not row:
        return None
    return WorkflowHistory(
        versionId=row.versionId,
        workflowId=row.workflowId,
        versionNumber=row.versionNumber,
        authors=row.authors,
        nodes=row.nodes,
        connections=row.connections,
        settings=row.settings,
        description=row.description,
        isPublishedSnapshot=row.isPublishedSnapshot,
        event=row.event,
        createdAt=row.createdAt,
    )
