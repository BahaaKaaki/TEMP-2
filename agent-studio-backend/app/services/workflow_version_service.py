"""
Workflow version history service.

Provides reusable logic for creating, querying, and restoring workflow
version snapshots. Used by workflow_entity.py (save/publish/unpublish)
and workflow_version_routes.py (history CRUD + marketplace updates).
"""
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import WorkflowEntity, WorkflowHistory

logger = logging.getLogger(__name__)


def _normalize_json(val: Optional[str]) -> str:
    """Parse and re-serialize JSON so whitespace/key-order differences don't cause false mismatches."""
    if not val:
        return ""
    try:
        return json.dumps(json.loads(val), sort_keys=True, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return val or ""


async def get_next_version_number(db: AsyncSession, workflow_id: str) -> int:
    """Return the next sequential version number for a workflow."""
    result = await db.execute(
        select(func.coalesce(func.max(WorkflowHistory.versionNumber), 0))
        .where(WorkflowHistory.workflowId == workflow_id)
    )
    return result.scalar() + 1


async def create_version_snapshot(
    db: AsyncSession,
    workflow: WorkflowEntity,
    *,
    author_name: str,
    event: str,
    is_published: bool = False,
    description: Optional[str] = None,
) -> WorkflowHistory:
    """
    Create a WorkflowHistory snapshot from the current state of a workflow.

    Args:
        db: Async database session (caller manages commit).
        workflow: The WorkflowEntity to snapshot.
        author_name: Display name of the user performing the action.
        event: One of 'save', 'publish', 'restore', 'import_update'.
        is_published: If True, marks this as the published snapshot and
                      clears the flag on any previous published row.
        description: Optional human label for this version.

    Returns:
        The newly created WorkflowHistory row (not yet committed).
    """
    # For regular saves, skip if content is identical to the latest version.
    if event == "save" and not is_published:
        latest = await _get_latest_version(db, workflow.id)
        if latest:
            nodes_same = _normalize_json(workflow.nodes or "[]") == _normalize_json(latest.nodes)
            conn_same = _normalize_json(workflow.connections or "{}") == _normalize_json(latest.connections)
            if nodes_same and conn_same:
                logger.debug("Skipping duplicate save snapshot for workflow %s", workflow.id)
                return latest

    version_number = await get_next_version_number(db, workflow.id)

    if is_published:
        await _clear_published_flag(db, workflow.id)

    version = WorkflowHistory(
        versionId=str(uuid.uuid4()),
        workflowId=workflow.id,
        versionNumber=version_number,
        authors=author_name,
        nodes=workflow.nodes or "[]",
        connections=workflow.connections or "{}",
        settings=workflow.settings,
        description=description,
        isPublishedSnapshot=is_published,
        event=event,
        createdAt=datetime.utcnow(),
    )
    db.add(version)
    logger.info(
        "Created version v%d (%s) for workflow %s [event=%s, published=%s]",
        version_number, version.versionId, workflow.id, event, is_published,
    )
    return version


async def get_published_snapshot(
    db: AsyncSession,
    workflow_id: str,
) -> Optional[WorkflowHistory]:
    """Return the current published snapshot for a workflow, or None."""
    result = await db.execute(
        select(WorkflowHistory)
        .where(and_(
            WorkflowHistory.workflowId == workflow_id,
            WorkflowHistory.isPublishedSnapshot == True,
        ))
        .order_by(WorkflowHistory.createdAt.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_version_by_id(
    db: AsyncSession,
    workflow_id: str,
    version_id: str,
) -> Optional[WorkflowHistory]:
    """Return a specific version, ensuring it belongs to the given workflow."""
    result = await db.execute(
        select(WorkflowHistory).where(and_(
            WorkflowHistory.versionId == version_id,
            WorkflowHistory.workflowId == workflow_id,
        ))
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession,
    workflow_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[list, int]:
    """
    Return paginated version history for a workflow (newest first).

    Returns:
        (list_of_versions, total_count)
    """
    base = select(WorkflowHistory).where(WorkflowHistory.workflowId == workflow_id)

    count_q = select(func.count(WorkflowHistory.versionId)).where(
        WorkflowHistory.workflowId == workflow_id
    )
    total = (await db.execute(count_q)).scalar()

    offset = (page - 1) * page_size
    rows_q = (
        base
        .order_by(WorkflowHistory.versionNumber.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(rows_q)).scalars().all()
    return rows, total


async def _get_latest_version(db: AsyncSession, workflow_id: str) -> Optional[WorkflowHistory]:
    """Return the most recent version snapshot for a workflow."""
    result = await db.execute(
        select(WorkflowHistory)
        .where(WorkflowHistory.workflowId == workflow_id)
        .order_by(WorkflowHistory.versionNumber.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _clear_published_flag(db: AsyncSession, workflow_id: str) -> None:
    """Set isPublishedSnapshot=False on all versions for this workflow."""
    result = await db.execute(
        select(WorkflowHistory).where(and_(
            WorkflowHistory.workflowId == workflow_id,
            WorkflowHistory.isPublishedSnapshot == True,
        ))
    )
    for row in result.scalars().all():
        row.isPublishedSnapshot = False
