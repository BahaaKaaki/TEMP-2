"""
Workflow Entity router for CRUD operations on workflows.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile, File
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, exists
from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import logging
import json

from db.pgsql import get_write_db, get_static_read_db, set_user_context
from db.models import WorkflowEntity, WorkflowHistory, User, MarketplaceSubmission, WorkflowShare
from core.dependencies import get_current_user, get_db_with_user_context
from repositories.workflow_repository import get_effective_workflow_data
from services.sharing_access import (
    can_write,
    load_user_group_ids,
    resolve_workflow_share_access,
)
from schemas import (
    WorkflowEntityCreate,
    WorkflowEntityUpdate,
    WorkflowEntityResponse,
    WorkflowEntityList
)
from workflow.validation import WorkflowValidator, format_validation_report
from services.visualization_analyzer import generate_output_schema
from services.workflow_version_service import create_version_snapshot
from workflow_share_approval import (
    SUBMISSION_TYPE_SHARE_VERSION,
    get_pending_submission,
    is_distribution_gated,
)
from utils.errors import safe_error_detail

logger = logging.getLogger(__name__)


def _workflow_share_exists_clause(user_id: str, group_ids: list):
    """SQL EXISTS: workflow has a read or write share targeting this user."""
    principal_ors = [
        and_(
            WorkflowShare.principalType == "user",
            WorkflowShare.principalId == user_id,
        )
    ]
    if group_ids:
        principal_ors.append(
            and_(
                WorkflowShare.principalType == "group",
                WorkflowShare.principalId.in_(group_ids),
            )
        )
    return exists(
        select(1)
        .select_from(WorkflowShare)
        .where(
            WorkflowShare.workflowId == WorkflowEntity.id,
            or_(*principal_ors),
        )
    )


async def _attach_share_access(
    db: AsyncSession,
    workflow: WorkflowEntity,
    user_id: str,
    group_ids: list | None = None,
) -> dict:
    """Serialize workflow and stamp shareAccess for the current user."""
    if group_ids is None:
        group_ids = await load_user_group_ids(db, user_id)
    access = await resolve_workflow_share_access(
        db,
        workflow.id,
        user_id,
        owner_id=workflow.createdById,
        group_ids=group_ids,
    )
    item = WorkflowEntityResponse.model_validate(workflow).model_dump()
    item["shareAccess"] = access
    return item


async def _require_workflow_write(
    db: AsyncSession,
    workflow: WorkflowEntity,
    current_user: User,
) -> None:
    access = await resolve_workflow_share_access(
        db,
        workflow.id,
        current_user.id,
        owner_id=workflow.createdById,
    )
    if not can_write(access):
        raise HTTPException(
            status_code=403,
            detail="You have read-only access to this workflow",
        )


router = APIRouter(
    prefix="/api/workflows",
    tags=["Workflows"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Workflow not found"}}
)


@router.post("/", response_model=WorkflowEntityResponse, status_code=201)
async def create_workflow(
    workflow_data: WorkflowEntityCreate,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new workflow.
    
    Args:
        workflow_data: Workflow creation data
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Created workflow
    """
    try:
        # DEBUG: Verify RLS context before INSERT
        from sqlalchemy import text
        debug_check = await db.execute(text("SELECT current_setting('app.current_user_id', true)"))
        rls_value = debug_check.scalar()
        logger.debug(f"🔍 CREATE DEBUG: RLS context before INSERT = '{rls_value}', current_user.id = '{current_user.id}'")
        
        # Generate UUID if not provided
        workflow_id = workflow_data.id or str(uuid.uuid4())
        
        # Check if workflow with this ID already exists
        existing = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Workflow with ID {workflow_id} already exists")
        
        # Debug: Log what we're saving
        logger.info("💾 Saving workflow '%s'", workflow_data.name)
        logger.debug("💾 Connections being saved: %s", workflow_data.connections[:200] if workflow_data.connections else "None")
        
        # Create workflow instance
        workflow = WorkflowEntity(
            id=workflow_id,
            name=workflow_data.name,
            description=workflow_data.description,
            active=workflow_data.active,
            nodes=workflow_data.nodes,
            connections=workflow_data.connections,
            settings=workflow_data.settings,
            staticData=workflow_data.staticData,
            pinData=workflow_data.pinData,
            versionId=workflow_data.versionId,
            triggerCount=workflow_data.triggerCount,
            meta=workflow_data.meta,
            parentFolderId=workflow_data.parentFolderId,
            isArchived=workflow_data.isArchived,
            isDraft=workflow_data.isDraft,
            createdById=current_user.id,
            createdByName=f"{current_user.firstName} {current_user.lastName}".strip() if current_user.firstName or current_user.lastName else current_user.email,
            icon=workflow_data.icon,
        )
        
        db.add(workflow)
        await db.commit()
        # await db.refresh(workflow)
        
        logger.info("✅ Created workflow: %s - %s", workflow.id, workflow.name)
        logger.debug("✅ Saved connections: %s", workflow.connections[:200] if workflow.connections else "None")
        return workflow
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to create workflow")) from e


@router.get("/", response_model=WorkflowEntityList)
async def list_workflows(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    include_archived: bool = Query(False, description="Include archived workflows"),
    active_only: bool = Query(False, description="Show only active workflows"),
    search: Optional[str] = Query(None, description="Search by workflow name"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """List workflows with pagination and filters."""
    try:
        # DEBUG: Check what RLS context is set
        from sqlalchemy import text
        debug_result = await db.execute(text("SELECT current_setting('app.current_user_id', true)"))
        current_rls_user = debug_result.scalar()
        logger.debug(f"🔍 RLS Debug: Query running with user_id={current_rls_user}, expected={current_user.id}")
        
        group_ids = await load_user_group_ids(db, current_user.id)

        # My Tools: owned workflows + write-shared workflows from others
        write_principal_ors = [
            and_(
                WorkflowShare.principalType == "user",
                WorkflowShare.principalId == current_user.id,
            ),
        ]
        if group_ids:
            write_principal_ors.append(
                and_(
                    WorkflowShare.principalType == "group",
                    WorkflowShare.principalId.in_(group_ids),
                )
            )
        write_share_exists = exists(
            select(1)
            .select_from(WorkflowShare)
            .where(
                WorkflowShare.workflowId == WorkflowEntity.id,
                WorkflowShare.permission == "write",
                or_(*write_principal_ors),
            )
        )

        query = select(WorkflowEntity).where(
            or_(
                WorkflowEntity.createdById == current_user.id,
                write_share_exists,
            )
        )

        if not include_archived:
            query = query.where(WorkflowEntity.isArchived == False)

        if active_only:
            query = query.where(WorkflowEntity.active == True)

        if search:
            query = query.where(WorkflowEntity.name.ilike(f"%{search}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar()

        offset = (page - 1) * page_size
        query = query.order_by(
            WorkflowEntity.isPinned.desc(),
            WorkflowEntity.lastAccessedAt.desc().nullslast(),
            WorkflowEntity.updatedAt.desc(),
        ).offset(offset).limit(page_size)

        result = await db.execute(query)
        workflows = result.scalars().all()

        items = []
        for wf in workflows:
            items.append(
                await _attach_share_access(
                    db, wf, current_user.id, group_ids=group_ids
                )
            )

        total_pages = (total + page_size - 1) // page_size

        return WorkflowEntityList(
            total=total,
            items=items,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to list workflows")) from e


@router.get("/{workflow_id}", response_model=WorkflowEntityResponse)
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific workflow by ID.
    
    For marketplace workflows the response contains the admin-approved
    snapshot so every consumer of this endpoint (chat UI, etc.) sees
    the correct version.
    """
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        access = await resolve_workflow_share_access(
            db,
            workflow.id,
            current_user.id,
            owner_id=workflow.createdById,
        )
        is_owner = access == "owner"
        eff = await get_effective_workflow_data(
            workflow, db, is_owner=is_owner, can_edit=can_write(access)
        )
        item = await _attach_share_access(
            db, workflow, current_user.id, group_ids=await load_user_group_ids(db, current_user.id)
        )
        if eff.source != "live":
            item["nodes"] = eff.nodes
            item["connections"] = eff.connections
        return item
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to get workflow")) from e


@router.put("/{workflow_id}", response_model=WorkflowEntityResponse)
async def update_workflow(
    workflow_id: str,
    workflow_data: WorkflowEntityUpdate,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Update a workflow.
    
    Args:
        workflow_id: Workflow UUID
        workflow_data: Updated workflow data
        db: Database session
        
    Returns:
        Updated workflow
    """
    try:
        # Check if workflow exists (RLS will filter to rows the user can SELECT)
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            # The workflow either doesn't exist OR is hidden by RLS. Distinguishing
            # the two cases here is hugely useful when debugging a "I just created
            # this workflow and now I get 404 on save" issue. We log:
            #   * the user_id the policy is filtering by
            #   * the createdById of the row (if the row exists at all)
            # We can't bypass RLS as the app role, but we *can* peek at pg_class
            # totals to tell whether the row is just RLS-filtered.
            try:
                from sqlalchemy import text as _text
                ctx = await db.execute(_text(
                    "SELECT current_setting('app.current_user_id', true), "
                    "current_setting('app.current_user_groups', true)"
                ))
                rls_user, rls_groups = ctx.first() or (None, None)
                # This SELECT is subject to RLS too (so the row will only be
                # visible if the user has SELECT on it via owner/public/share);
                # if it returns NULL we know the row is *either* missing *or*
                # hidden — the next query disambiguates.
                visible = await db.execute(_text(
                    'SELECT "createdById" FROM workflow_entity WHERE id = :wid'
                ), {"wid": workflow_id})
                visible_row = visible.first()
                logger.warning(
                    "🔍 update_workflow 404 diag: workflow_id=%s user_id=%s "
                    "ctx_rls_user=%r ctx_rls_groups=%r row_visible=%s row_createdById=%s",
                    workflow_id,
                    current_user.id,
                    rls_user,
                    rls_groups,
                    visible_row is not None,
                    visible_row[0] if visible_row else None,
                )
            except Exception as diag_err:  # noqa: BLE001
                logger.warning("🔍 update_workflow 404 diag failed: %s", diag_err)

            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        await _require_workflow_write(db, workflow, current_user)

        # Update only provided fields
        update_data = workflow_data.model_dump(exclude_unset=True)

        # Debug: Log connections being updated
        if 'connections' in update_data:
            logger.debug("💾 Updating workflow '%s' connections: %s", workflow.name, update_data['connections'][:200] if update_data['connections'] else "None")

        if update_data:
            for field, value in update_data.items():
                setattr(workflow, field, value)

            author = _author_name(current_user)
            await create_version_snapshot(
                db, workflow,
                author_name=author,
                event="save",
            )

            await db.commit()
            await db.refresh(workflow)

            logger.info("✅ Updated workflow: %s - %s", workflow.id, workflow.name)
            if workflow.connections:
                logger.debug("✅ Connections after update: %s", workflow.connections[:200])

        return await _attach_share_access(db, workflow, current_user.id)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to update workflow")) from e


@router.patch("/{workflow_id}/archive", response_model=WorkflowEntityResponse)
async def archive_workflow(
    workflow_id: str,
    archive: bool = Query(True, description="True to archive, False to unarchive"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Archive or unarchive a workflow (soft delete).
    
    Args:
        workflow_id: Workflow UUID
        archive: Whether to archive (True) or unarchive (False)
        db: Database session
        
    Returns:
        Updated workflow
    """
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        await _require_workflow_write(db, workflow, current_user)

        workflow.isArchived = archive
        await db.commit()
        
        action = "archived" if archive else "unarchived"
        logger.info("Workflow %s %s", workflow.id, action)
        
        return workflow
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to archive workflow")) from e


@router.patch("/{workflow_id}/publish")
async def publish_workflow(
    workflow_id: str,
    force: bool = Query(False, description="If true, replace an existing pending marketplace submission"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Publish a workflow version.

    Creates a published snapshot of the current state and stamps
    workflow.versionId so shared users (user/AD group) see this version.
    Re-publishing creates a new published snapshot.

    If the workflow is on the marketplace (isPublic=True) or has gated sharing
    (any AD group share or 16+ user shares), auto-creates a pending
    MarketplaceSubmission for admin re-approval. Recipients keep the last
    approved snapshot until the admin approves.

    When a pending submission already exists and ``force`` is False the
    endpoint returns 409 with ``has_pending_submission: true`` so the
    frontend can show a confirmation dialog. Re-call with ``force=true``
    to replace the pending submission.
    """
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        await _require_workflow_write(db, workflow, current_user)

        gated = await is_distribution_gated(db, workflow.id)
        needs_version_approval = workflow.isPublic or gated

        existing_pending = None
        has_pending = False
        if needs_version_approval:
            existing_pending = await get_pending_submission(db, workflow.id)
            has_pending = existing_pending is not None

            if has_pending and not force:
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "An approval is already pending for this workflow.",
                        "has_pending_submission": True,
                    },
                )

        author = _author_name(current_user)
        version = await create_version_snapshot(
            db, workflow,
            author_name=author,
            event="publish",
            is_published=True,
        )
        workflow.versionId = version.versionId
        workflow.isDraft = False

        replaced_pending = False
        if needs_version_approval:
            if has_pending and existing_pending:
                await db.delete(existing_pending)
                replaced_pending = True
                logger.info(
                    "Replaced existing pending submission %s for workflow %s",
                    existing_pending.id, workflow.id,
                )

            submission_type = "workflow" if workflow.isPublic else SUBMISSION_TYPE_SHARE_VERSION
            meta = None
            if submission_type == SUBMISSION_TYPE_SHARE_VERSION:
                meta = {
                    "action": "version_publish",
                    "proposedVersionId": version.versionId,
                }

            resubmission = MarketplaceSubmission(
                id=str(uuid.uuid4()),
                workflowId=workflow.id,
                submittedById=current_user.id,
                marketplaceName=workflow.marketplaceName or workflow.name,
                marketplaceDescription=workflow.marketplaceDescription or '',
                status='pending',
                submission_type=submission_type,
                meta=meta,
            )
            db.add(resubmission)
            logger.info(
                "Created %s pending submission for workflow %s",
                submission_type, workflow.id,
            )

        await db.commit()

        logger.info("Workflow %s published (version %s)", workflow.id, version.versionId)

        resp = WorkflowEntityResponse.model_validate(workflow).model_dump()
        resp["_replaced_pending_submission"] = replaced_pending
        return resp

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to publish workflow")) from e


@router.patch("/{workflow_id}/activate", response_model=WorkflowEntityResponse)
async def toggle_workflow_active(
    workflow_id: str,
    active: bool = Query(..., description="True to activate, False to deactivate"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Activate or deactivate a workflow.
    
    Args:
        workflow_id: Workflow UUID
        active: Whether to activate (True) or deactivate (False)
        db: Database session
        
    Returns:
        Updated workflow
    """
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        workflow.active = active
        await db.commit()
        
        status = "activated" if active else "deactivated"
        logger.info("Workflow %s %s", workflow.id, status)
        
        return workflow
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to toggle workflow")) from e


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: str,
    permanent: bool = Query(False, description="Permanently delete (True) or archive (False)"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a workflow (archive by default, permanent if specified).
    
    Also cancels any pending marketplace submissions for this workflow.
    
    Args:
        workflow_id: Workflow UUID
        permanent: If True, permanently delete; if False, archive
        db: Database session
        
    Returns:
        No content (204)
    """
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        # Cancel any pending marketplace submissions for this workflow
        pending_submissions = await db.execute(
            select(MarketplaceSubmission).where(
                MarketplaceSubmission.workflowId == workflow_id,
                MarketplaceSubmission.status == 'pending'
            )
        )
        for submission in pending_submissions.scalars().all():
            submission.status = 'cancelled'
            submission.rejectionReason = 'Workflow was deleted by owner'
            submission.updatedAt = datetime.utcnow()
            logger.info("Cancelled marketplace submission %s due to workflow deletion", submission.id)
        
        if permanent:
            await db.delete(workflow)
            logger.info("Permanently deleted workflow: %s", workflow_id)
        else:
            workflow.isArchived = True
            logger.info("Archived workflow: %s", workflow_id)
        
        await db.commit()
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to delete workflow")) from e


@router.get("/stats/summary")
async def get_workflow_stats(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Get workflow statistics summary.
    
    Args:
        db: Database session
        
    Returns:
        Workflow statistics
    """
    try:
        stats_query = select(
            func.count(WorkflowEntity.id).filter(
                WorkflowEntity.isArchived == False
            ).label("total"),
            func.count(WorkflowEntity.id).filter(
                WorkflowEntity.active == True,
                WorkflowEntity.isArchived == False
            ).label("active"),
            func.count(WorkflowEntity.id).filter(
                WorkflowEntity.isArchived == True
            ).label("archived"),
        )
        row = (await db.execute(stats_query)).one()
        
        return {
            "total": row.total,
            "active": row.active,
            "inactive": row.total - row.active,
            "archived": row.archived
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to get statistics")) from e


@router.post("/{workflow_id}/validate", status_code=200)
async def validate_workflow(
    workflow_id: str,
    auto_fix: bool = Query(True, description="Auto-fix common issues"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Validate a workflow configuration.
    
    Checks for common issues that might cause workflow execution problems,
    especially useful for non-technical users building workflows.
    
    Args:
        workflow_id: Workflow ID to validate
        auto_fix: Whether to auto-fix common issues
        db: Database session
        
    Returns:
        Validation report with issues and suggestions
    """
    try:
        # Load workflow
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        # Build workflow JSON
        workflow_json = {
            "workflow": {
                "nodes": workflow.nodes or [],
                "edges": workflow.edges or [],
                "settings": workflow.settings or {}
            }
        }
        
        # Validate (and optionally auto-fix)
        fixed_workflow_json, issues = WorkflowValidator.validate_and_fix(
            workflow_json,
            auto_fix=auto_fix
        )
        
        # Format report
        report = format_validation_report(issues)
        
        # Categorize issues
        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        infos = [i for i in issues if i.get("severity") == "info"]
        
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "is_valid": len(errors) == 0,
            "auto_fix_applied": auto_fix,
            "summary": {
                "errors": len(errors),
                "warnings": len(warnings),
                "infos": len(infos)
            },
            "issues": issues,
            "report": report,
            "fixed_workflow": fixed_workflow_json if auto_fix and issues else None,
            "recommendation": (
                "✅ Workflow is ready to use!" if not issues
                else f"⚠️ Found {len(errors)} error(s), {len(warnings)} warning(s). Please review and fix."
            )
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to validate workflow")
        ) from e


@router.post("/validate-definition", status_code=200)
async def validate_workflow_definition(
    workflow_definition: Dict[str, Any],
    auto_fix: bool = Query(True, description="Auto-fix common issues")
) -> Dict[str, Any]:
    """
    Validate a workflow definition (without saving it).
    
    Useful for real-time validation in the UI as users build workflows.
    
    Args:
        workflow_definition: Workflow definition JSON
        auto_fix: Whether to auto-fix common issues
        
    Returns:
        Validation report with issues and suggestions
    """
    try:
        # Validate (and optionally auto-fix)
        fixed_workflow_json, issues = WorkflowValidator.validate_and_fix(
            workflow_definition,
            auto_fix=auto_fix
        )
        
        # Format report
        report = format_validation_report(issues)
        
        # Categorize issues
        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        infos = [i for i in issues if i.get("severity") == "info"]
        
        return {
            "is_valid": len(errors) == 0,
            "auto_fix_applied": auto_fix,
            "summary": {
                "errors": len(errors),
                "warnings": len(warnings),
                "infos": len(infos)
            },
            "issues": issues,
            "report": report,
            "fixed_workflow": fixed_workflow_json if auto_fix and issues else None,
            "recommendation": (
                "✅ Workflow looks good!" if not issues
                else f"⚠️ Found {len(errors)} error(s), {len(warnings)} warning(s). Please review."
            )
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to validate workflow")
        ) from e


@router.post("/{workflow_id}/nodes/{node_id}/generate-schema")
async def generate_output_schema_endpoint(
    workflow_id: str,
    node_id: str,
    payload: Dict[str, Any] = Body(...)
):
    """
    Generate an output schema for an agent node based on its prompt and user requirements.
    Can generate schemas for visualizations OR general structured data.
    
    Args:
        workflow_id: Workflow ID (for context, not used currently)
        node_id: Node ID (for context, not used currently)
        payload: Dict with 'prompt', 'systemInstructions' (or legacy 'taskInstructions'),
            'userRequirements', and optional 'outputSchema'
        
    Returns:
        Generated schema with type information and reasoning
    """
    try:
        prompt = payload.get('prompt', '')
        task_instructions = (
            payload.get('systemInstructions')
            or payload.get('taskInstructions')
        )
        user_requirements = payload.get('userRequirements')
        output_schema = payload.get('outputSchema')
        
        # Prompt is optional now - user requirements alone might be enough
        
        logger.debug(f"Generating schema for node {node_id} in workflow {workflow_id}")
        
        # Call schema generator service
        result = await generate_output_schema(
            prompt=prompt or '',
            task_instructions=task_instructions,
            user_requirements=user_requirements,
            output_schema=output_schema
        )
        
        return {
            "success": True,
            "nodeId": node_id,
            "workflowId": workflow_id,
            "schema": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to generate schema")
        ) from e


# ============================================================================
# PIN & LAST ACCESSED ENDPOINTS
# ============================================================================

@router.patch("/{workflow_id}/pin", response_model=WorkflowEntityResponse)
async def toggle_workflow_pin(
    workflow_id: str,
    pinned: bool = Query(..., description="True to pin, False to unpin"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """Toggle pin status for a workflow."""
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        workflow.isPinned = pinned
        await db.commit()
        
        return workflow
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to toggle pin")) from e


@router.patch("/{workflow_id}/last-accessed", response_model=WorkflowEntityResponse)
async def update_workflow_last_accessed(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """Update last accessed timestamp for a workflow."""
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
        
        workflow.lastAccessedAt = datetime.utcnow()
        await db.commit()
        
        return workflow
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to update last accessed")) from e


# ============================================================================
# MARKETPLACE ENDPOINTS
# ============================================================================

@router.post("/{workflow_id}/share-to-marketplace", response_model=WorkflowEntityResponse)
async def share_workflow_to_marketplace(
    workflow_id: str,
    marketplace_data: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Share a workflow to the marketplace.
    
    Args:
        workflow_id: ID of workflow to share
        marketplace_data: Dict with 'marketplaceName' and 'marketplaceDescription'
        current_user: Authenticated user (must be workflow owner)
        db: Database session
        
    Returns:
        Updated workflow with marketplace details
    """
    try:
        # Get workflow (RLS ensures user owns it)
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Only workflow owner can share to marketplace
        if workflow.createdById != current_user.id:
            raise HTTPException(status_code=403, detail="Only workflow owner can share to marketplace")
        
        if not workflow.versionId:
            raise HTTPException(status_code=400, detail="Publish the workflow at least once before sharing to marketplace.")
        
        # Update marketplace fields
        workflow.isPublic = True
        workflow.marketplaceName = marketplace_data.get('marketplaceName', workflow.name)
        workflow.marketplaceDescription = marketplace_data.get('marketplaceDescription', '')
        
        await db.commit()
        
        logger.info(f"✅ Shared workflow {workflow_id} to marketplace as '{workflow.marketplaceName}'")
        return workflow
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to share workflow to marketplace"),
        ) from e


@router.delete("/{workflow_id}/unshare-from-marketplace", response_model=WorkflowEntityResponse)
async def unshare_workflow_from_marketplace(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Remove a workflow from the marketplace.
    
    Args:
        workflow_id: ID of workflow to unshare
        current_user: Authenticated user (must be workflow owner)
        db: Database session
        
    Returns:
        Updated workflow
    """
    try:
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        if workflow.createdById != current_user.id:
            raise HTTPException(status_code=403, detail="Only workflow owner can unshare from marketplace")
        
        workflow.isPublic = False
        workflow.marketplaceName = None
        workflow.marketplaceDescription = None
        
        await db.commit()
        
        logger.info(f"✅ Unshared workflow {workflow_id} from marketplace")
        return workflow
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to unshare workflow from marketplace"),
        ) from e


@router.get("/marketplace/list")
async def list_marketplace_workflows(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = Query(None, description="Search by workflow name or description"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    List workflows visible on the Storefront for the current user:
    public marketplace items, plus read/write AD-group or user shares.
    """
    try:
        group_ids = await load_user_group_ids(db, current_user.id)
        share_clause = _workflow_share_exists_clause(current_user.id, group_ids)

        query = select(WorkflowEntity).where(
            WorkflowEntity.isArchived == False,
            or_(
                WorkflowEntity.isPublic == True,
                and_(
                    WorkflowEntity.versionId.isnot(None),
                    share_clause,
                ),
            ),
        )

        if search:
            search_filter = f"%{search}%"
            query = query.where(
                or_(
                    WorkflowEntity.marketplaceName.ilike(search_filter),
                    WorkflowEntity.name.ilike(search_filter),
                    WorkflowEntity.marketplaceDescription.ilike(search_filter),
                )
            )

        count_base = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_base)).scalar()

        query = query.offset(skip).limit(limit)
        workflows = list((await db.execute(query)).scalars().all())

        snapshot_ids = []
        gated_by_wf: dict[str, bool] = {}
        for wf in workflows:
            gated = await is_distribution_gated(db, wf.id)
            gated_by_wf[wf.id] = gated
            if (wf.isPublic or gated) and wf.approvedVersionId:
                snapshot_ids.append(wf.approvedVersionId)
            elif not gated and wf.versionId:
                snapshot_ids.append(wf.versionId)

        snapshot_map = {}
        if snapshot_ids:
            snap_result = await db.execute(
                select(WorkflowHistory).where(
                    WorkflowHistory.versionId.in_(snapshot_ids)
                )
            )
            for snap in snap_result.scalars().all():
                snapshot_map[snap.versionId] = snap

        serialized_items = []
        for wf in workflows:
            gated = gated_by_wf.get(wf.id, False)
            if (
                gated
                and not wf.approvedVersionId
                and wf.createdById != current_user.id
            ):
                continue

            item = await _attach_share_access(
                db, wf, current_user.id, group_ids=group_ids
            )
            snap = None
            if (wf.isPublic or gated) and wf.approvedVersionId:
                snap = snapshot_map.get(wf.approvedVersionId)
            elif not gated and wf.versionId:
                snap = snapshot_map.get(wf.versionId)
            if snap:
                item["nodes"] = snap.nodes
                item["connections"] = snap.connections
            serialized_items.append(item)
        
        logger.info(f"Listed {len(serialized_items)} marketplace workflows (total: {total})")
        
        page = (skip // limit) + 1 if limit > 0 else 1
        total_pages = (total + limit - 1) // limit if limit > 0 else 1
        
        return {
            "items": serialized_items,
            "total": total,
            "page": page,
            "page_size": limit,
            "total_pages": total_pages
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to list marketplace workflows"),
        ) from e


@router.post("/marketplace/{workflow_id}/copy", response_model=WorkflowEntityResponse)
async def copy_marketplace_workflow_to_drafts(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Copy a marketplace workflow to user's drafts.
    
    Creates a new draft workflow owned by the current user with all nodes/edges/config copied.
    
    Args:
        workflow_id: ID of marketplace workflow to copy
        current_user: Authenticated user
        db: Database session
        
    Returns:
        New draft workflow
    """
    try:
        # Get marketplace workflow (use static read db - no RLS needed for public data)
        read_db_gen = get_static_read_db()
        read_db = await anext(read_db_gen)
        
        try:
            result = await read_db.execute(
                select(WorkflowEntity).where(
                    WorkflowEntity.id == workflow_id,
                    WorkflowEntity.isPublic == True
                )
            )
            source_workflow = result.scalar_one_or_none()

            if not source_workflow:
                raise HTTPException(status_code=404, detail="Marketplace workflow not found")

            eff = await get_effective_workflow_data(source_workflow, read_db, is_owner=False)
        finally:
            await read_db.close()

        new_workflow_id = str(uuid.uuid4())
        new_workflow = WorkflowEntity(
            id=new_workflow_id,
            name=f"{source_workflow.marketplaceName or source_workflow.name} (Copy)",
            active=False,
            nodes=eff.nodes,
            connections=eff.connections,
            settings=source_workflow.settings,
            staticData=source_workflow.staticData,
            pinData=None,  # Don't copy pin data
            versionId=None,  # New version
            triggerCount=0,  # Reset trigger count
            meta=source_workflow.meta,  # Copy metadata
            parentFolderId=None,  # No folder
            isArchived=False,
            isDraft=True,  # Create as draft
            createdById=current_user.id,  # Owned by current user
            isPublic=False,  # Not public
            marketplaceName=None,
            marketplaceDescription=None,
            icon=source_workflow.icon,
        )
        
        db.add(new_workflow)
        await db.commit()
        
        logger.info(f"✅ Copied marketplace workflow {workflow_id} to draft {new_workflow_id} for user {current_user.id}")
        return new_workflow
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to copy marketplace workflow"),
        ) from e


@router.post("/marketplace/{workflow_id}/import", response_model=WorkflowEntityResponse)
async def import_marketplace_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Import a marketplace workflow directly to user's workflows (read-only reference).
    
    Creates a linked reference to the marketplace workflow that the user can use
    directly without modification. The workflow appears in their Workflows tab
    and they can chat with it immediately.
    
    Args:
        workflow_id: ID of marketplace workflow to import
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Imported workflow (read-only linked reference)
    """
    from sqlalchemy import text as sql_text
    
    try:
        # Get marketplace workflow using raw SQL to bypass RLS
        result = await db.execute(
            sql_text("""
                SELECT id, name, description, nodes, connections, settings, 
                       "staticData", meta, "marketplaceName", "marketplaceDescription",
                       "approvedVersionId", icon
                FROM workflow_entity 
                WHERE id = :workflow_id AND "isPublic" = true
            """),
            {"workflow_id": workflow_id}
        )
        source_row = result.fetchone()
        
        if not source_row:
            raise HTTPException(status_code=404, detail="Marketplace workflow not found")
        
        source_name = source_row[1]
        source_description = source_row[2]
        source_nodes = source_row[3]
        source_connections = source_row[4]
        source_settings = source_row[5]
        source_static_data = source_row[6]
        source_meta_raw = source_row[7]
        source_marketplace_name = source_row[8]
        source_marketplace_desc = source_row[9]
        approved_vid = source_row[10]
        source_icon = source_row[11]

        # Build a lightweight ORM stand-in to use the shared resolution logic
        source_proxy = WorkflowEntity(
            id=workflow_id, isPublic=True,
            approvedVersionId=approved_vid, versionId=None,
            nodes=source_nodes, connections=source_connections,
            settings=source_settings,
        )
        eff = await get_effective_workflow_data(source_proxy, db, is_owner=False)
        source_nodes = eff.nodes
        source_connections = eff.connections
        
        # Check if user already has this workflow imported using raw SQL
        existing_result = await db.execute(
            sql_text("""
                SELECT id, name, description, active, nodes, connections, settings, 
                       "staticData", "versionId", "triggerCount", meta, "parentFolderId",
                       "createdAt", "updatedAt", "isArchived", "isDraft", "createdById",
                       "createdByName", "isPublic", "marketplaceName", "marketplaceDescription",
                       icon
                FROM workflow_entity 
                WHERE "createdById" = :user_id 
                  AND meta LIKE :meta_pattern
            """),
            {"user_id": current_user.id, "meta_pattern": f'%"sourceMarketplaceId": "{workflow_id}"%'}
        )
        existing_row = existing_result.fetchone()
        
        if existing_row:
            # Return existing imported workflow
            logger.info(f"📋 User {current_user.id} already has workflow {workflow_id} imported as {existing_row[0]}")
            # Convert row to WorkflowEntity for response
            return WorkflowEntity(
                id=existing_row[0],
                name=existing_row[1],
                description=existing_row[2],
                active=existing_row[3],
                nodes=existing_row[4],
                connections=existing_row[5],
                settings=existing_row[6],
                staticData=existing_row[7],
                versionId=existing_row[8],
                triggerCount=existing_row[9],
                meta=existing_row[10],
                parentFolderId=existing_row[11],
                createdAt=existing_row[12],
                updatedAt=existing_row[13],
                isArchived=existing_row[14],
                isDraft=existing_row[15],
                createdById=existing_row[16],
                createdByName=existing_row[17],
                isPublic=existing_row[18],
                marketplaceName=existing_row[19],
                marketplaceDescription=existing_row[20],
                icon=existing_row[21],
            )
        
        # Create new workflow as read-only linked reference
        # This is a published workflow (isDraft=false) that the user owns
        # but is linked to the marketplace version via metadata
        
        # Prepare metadata with source reference
        source_meta = {}
        if source_meta_raw:
            try:
                source_meta = json.loads(source_meta_raw) if isinstance(source_meta_raw, str) else source_meta_raw
            except:
                source_meta = {}
        
        source_version_id = approved_vid

        linked_meta = {
            **source_meta,
            "sourceMarketplaceId": workflow_id,
            "importedAt": datetime.utcnow().isoformat(),
            "isMarketplaceImport": True,
            "readOnly": True,
        }
        if source_version_id:
            linked_meta["sourceVersionId"] = source_version_id
        
        new_workflow_id = str(uuid.uuid4())
        imported_workflow = WorkflowEntity(
            id=new_workflow_id,
            name=source_marketplace_name or source_name,
            description=source_marketplace_desc or source_description,
            active=True,  # Active so they can use it
            nodes=source_nodes,
            connections=source_connections,
            settings=source_settings,
            staticData=source_static_data,
            pinData=None,
            versionId=None,
            triggerCount=0,
            meta=json.dumps(linked_meta),
            parentFolderId=None,
            isArchived=False,
            isDraft=False,  # Published (not a draft) - appears in Workflows tab
            createdById=current_user.id,
            createdByName=f"{current_user.firstName or ''} {current_user.lastName or ''}".strip() or current_user.email,
            isPublic=False,
            marketplaceName=None,
            marketplaceDescription=None,
            icon=source_icon,
        )
        
        db.add(imported_workflow)
        await db.commit()
        
        logger.info(f"✅ Imported marketplace workflow {workflow_id} as {new_workflow_id} for user {current_user.id}")
        return imported_workflow
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to import marketplace workflow"),
        ) from e


# ============================================================================
# WORKFLOW ICON ENDPOINTS
# ============================================================================

ALLOWED_ICON_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/svg+xml"}
MAX_ICON_SIZE = 2 * 1024 * 1024  # 2 MB


@router.post("/{workflow_id}/icon")
async def upload_workflow_icon(
    workflow_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Upload an icon image for a workflow.

    Accepts PNG, JPEG, GIF, WebP, or SVG up to 2 MB.
    Stores the image in Azure Blob Storage under ``workflow-icons/``
    and writes the serving path to ``workflow_entity.icon``.
    """
    from core.dependencies import get_azure_storage_connector

    if file.content_type not in ALLOWED_ICON_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type '{file.content_type}'. Allowed: PNG, JPEG, GIF, WebP, SVG.",
        )

    data = await file.read()
    if len(data) > MAX_ICON_SIZE:
        raise HTTPException(status_code=400, detail="Icon image must be under 2 MB.")

    result = await db.execute(
        select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    ext = (file.filename or "icon").rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "gif", "webp", "svg"}:
        ext = "png"
    blob_name = f"workflow-icons/{workflow_id}.{ext}"

    try:
        storage = get_azure_storage_connector()
        await storage.upload_blob(blob_name, data, content_type=file.content_type, overwrite=True)
    except Exception as e:
        logger.error("Failed to upload icon blob: %s", e)
        raise HTTPException(status_code=500, detail=safe_error_detail(e, "Failed to upload icon")) from e

    icon_path = f"/api/workflows/{workflow_id}/icon"
    workflow.icon = icon_path
    await db.commit()

    logger.info("Uploaded icon for workflow %s (%d bytes)", workflow_id, len(data))
    return {"icon": icon_path}


@router.delete("/{workflow_id}/icon")
async def delete_workflow_icon(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """Remove the workflow icon."""
    from core.dependencies import get_azure_storage_connector

    result = await db.execute(
        select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow.icon:
        try:
            storage = get_azure_storage_connector()
            prefix = f"workflow-icons/{workflow_id}."
            blobs = await storage.list_blobs(prefix=prefix, max_results=5)
            for b in blobs:
                await storage.delete_blob(b.name)
        except Exception as e:
            logger.warning("Failed to delete icon blob for %s: %s", workflow_id, e)

    workflow.icon = None
    await db.commit()

    return {"icon": None}


# ============================================================================
# HELPERS
# ============================================================================

def _author_name(user: User) -> str:
    name = f"{user.firstName or ''} {user.lastName or ''}".strip()
    return name or user.email
