"""
Marketplace Approval router for workflow submission and approval workflow.

Handles:
- Submitting workflows for marketplace approval
- Admin review, testing, approval, and rejection of submissions
- KB auto-sharing when workflows are approved
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from typing import Optional, Dict, Any, List, Iterable
from pydantic import BaseModel
import uuid
import logging
import json
from datetime import datetime

from db.pgsql import get_write_db, get_admin_db, set_user_context
from db.models import WorkflowEntity, User, MarketplaceSubmission, WorkflowHistory
from core.dependencies import get_current_user, get_current_admin_user, get_db_with_user_context, is_admin
from workflow_share_approval import (
    SUBMISSION_TYPE_SHARE_GRANT,
    SUBMISSION_TYPE_SHARE_VERSION,
    apply_share_grants_from_meta,
)
from utils.errors import safe_error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/marketplace/approval",
    tags=["Marketplace Approval"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


async def _fetch_workflow_row_as_owner(
    db: AsyncSession,
    workflow_id: str,
    owner_id: str,
    admin_id: str,
    *,
    select_sql: str,
) -> Optional[Any]:
    """
    Read workflow_entity rows as the workflow owner.

    Raw SQL does not bypass RLS on Azure Postgres; admin sessions still only
    see workflow_entity rows allowed by policy (owner / public / share).
    Temporarily set app.current_user_id to the submitter so review endpoints
    can load private workflows pending approval.
    """
    if not owner_id:
        return None
    await set_user_context(db, owner_id)
    try:
        result = await db.execute(
            text(select_sql),
            {"workflow_id": workflow_id},
        )
        return result.fetchone()
    finally:
        if admin_id:
            await set_user_context(db, admin_id)


async def _fetch_workflow_names_as_owners(
    db: AsyncSession,
    submissions: List[Any],
    admin_id: str,
) -> Dict[str, str]:
    """Batch-load workflow names keyed by workflow id (RLS-safe per owner)."""
    by_owner: Dict[str, List[str]] = {}
    for sub in submissions:
        wf_id, submitter_id = sub[1], sub[2]
        if wf_id and submitter_id:
            by_owner.setdefault(submitter_id, []).append(wf_id)

    wf_name_map: Dict[str, str] = {}
    for owner_id, wf_ids in by_owner.items():
        await set_user_context(db, owner_id)
        try:
            wf_result = await db.execute(
                text("SELECT id, name FROM workflow_entity WHERE id = ANY(:ids)"),
                {"ids": list(set(wf_ids))},
            )
            for row in wf_result.fetchall():
                wf_name_map[row[0]] = row[1]
        finally:
            if admin_id:
                await set_user_context(db, admin_id)
    return wf_name_map


# ============================================================================
# SCHEMAS
# ============================================================================

class SubmissionCreate(BaseModel):
    """Schema for creating a marketplace submission."""
    workflowId: str
    marketplaceName: str
    marketplaceDescription: Optional[str] = None


class SubmissionResponse(BaseModel):
    """Schema for submission response."""
    id: str
    workflowId: Optional[str] = None
    submittedById: str
    marketplaceName: str
    marketplaceDescription: Optional[str]
    status: str
    submission_type: str = "workflow"
    meta: Optional[Dict[str, Any]] = None
    reviewedById: Optional[str]
    reviewedAt: Optional[datetime]
    rejectionReason: Optional[str]
    createdAt: datetime
    updatedAt: datetime
    
    # Include workflow details
    workflowName: Optional[str] = None
    submitterName: Optional[str] = None
    submitterEmail: Optional[str] = None
    
    class Config:
        from_attributes = True


class SubmissionList(BaseModel):
    """Schema for paginated submission list."""
    items: List[SubmissionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class RejectionRequest(BaseModel):
    """Schema for rejection request."""
    reason: str


class ApproveSubmissionRequest(BaseModel):
    """Optional overrides when approving (external tool sharing targets)."""
    is_public: Optional[bool] = None
    ad_group_names: Optional[List[str]] = None
    emails: Optional[List[str]] = None


class SubmissionWorkflowPreview(BaseModel):
    """Workflow graph snapshot for admin review (read-only canvas)."""
    workflowId: str
    name: str
    description: Optional[str] = None
    nodes: Any
    connections: Any
    settings: Optional[Any] = None
    meta: Optional[Any] = None
    marketplaceName: Optional[str] = None
    marketplaceDescription: Optional[str] = None


# ============================================================================
# USER ENDPOINTS - Submit workflows for approval
# ============================================================================

@router.post("/submit", response_model=SubmissionResponse, status_code=201)
async def submit_workflow_for_approval(
    submission_data: SubmissionCreate,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    Submit a workflow for marketplace approval.
    
    The workflow must be published (not a draft) and owned by the current user.
    Creates a pending submission that admins can review.
    
    Args:
        submission_data: Submission details
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Created submission
    """
    try:
        # Get the workflow
        result = await db.execute(
            select(WorkflowEntity).where(WorkflowEntity.id == submission_data.workflowId)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # Verify ownership
        if workflow.createdById != current_user.id:
            raise HTTPException(status_code=403, detail="You can only submit your own workflows")
        
        if not workflow.versionId:
            raise HTTPException(status_code=400, detail="Publish the workflow at least once before submitting.")
        
        # Check if workflow is already in marketplace
        if workflow.isPublic:
            raise HTTPException(status_code=400, detail="Workflow is already in marketplace")
        
        # Check for existing pending submission
        existing_result = await db.execute(
            select(MarketplaceSubmission).where(
                MarketplaceSubmission.workflowId == submission_data.workflowId,
                MarketplaceSubmission.status == 'pending'
            )
        )
        existing = existing_result.scalar_one_or_none()
        
        if existing:
            raise HTTPException(status_code=400, detail="Workflow already has a pending submission")
        
        # Create submission
        submission_id = str(uuid.uuid4())
        submission = MarketplaceSubmission(
            id=submission_id,
            workflowId=submission_data.workflowId,
            submittedById=current_user.id,
            marketplaceName=submission_data.marketplaceName,
            marketplaceDescription=submission_data.marketplaceDescription,
            status='pending'
        )
        
        db.add(submission)
        await db.commit()
        
        logger.info(f"✅ Workflow {submission_data.workflowId} submitted for approval by user {current_user.id}")
        
        # Build response with workflow details
        response = SubmissionResponse(
            id=submission.id,
            workflowId=submission.workflowId,
            submittedById=submission.submittedById,
            marketplaceName=submission.marketplaceName,
            marketplaceDescription=submission.marketplaceDescription,
            status=submission.status,
            reviewedById=submission.reviewedById,
            reviewedAt=submission.reviewedAt,
            rejectionReason=submission.rejectionReason,
            createdAt=submission.createdAt,
            updatedAt=submission.updatedAt,
            workflowName=workflow.name,
            submitterName=f"{current_user.firstName or ''} {current_user.lastName or ''}".strip() or None,
            submitterEmail=current_user.email
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to submit workflow for approval"),
        ) from e


@router.get("/my-submissions", response_model=SubmissionList)
async def list_my_submissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected"),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """
    List current user's submissions.
    
    Args:
        page: Page number
        page_size: Items per page
        status_filter: Filter by status
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Paginated list of user's submissions
    """
    try:
        query = select(MarketplaceSubmission).where(
            MarketplaceSubmission.submittedById == current_user.id
        )
        
        if status_filter:
            query = query.where(MarketplaceSubmission.status == status_filter)
        
        # Get total count
        count_query = select(func.count(MarketplaceSubmission.id)).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar()
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.order_by(MarketplaceSubmission.createdAt.desc()).offset(offset).limit(page_size)
        
        result = await db.execute(query)
        submissions = result.scalars().all()
        
        # Batch-fetch workflow names for all submissions in one query
        wf_ids = [sub.workflowId for sub in submissions if sub.workflowId]
        wf_name_map = {}
        if wf_ids:
            wf_result = await db.execute(
                select(WorkflowEntity.id, WorkflowEntity.name).where(
                    WorkflowEntity.id.in_(wf_ids)
                )
            )
            wf_name_map = {row[0]: row[1] for row in wf_result.all()}
        
        items = []
        for sub in submissions:
            items.append(SubmissionResponse(
                id=sub.id,
                workflowId=sub.workflowId,
                submittedById=sub.submittedById,
                marketplaceName=sub.marketplaceName,
                marketplaceDescription=sub.marketplaceDescription,
                status=sub.status,
                reviewedById=sub.reviewedById,
                reviewedAt=sub.reviewedAt,
                rejectionReason=sub.rejectionReason,
                createdAt=sub.createdAt,
                updatedAt=sub.updatedAt,
                workflowName=wf_name_map.get(sub.workflowId),
                submitterName=f"{current_user.firstName or ''} {current_user.lastName or ''}".strip() or None,
                submitterEmail=current_user.email
            ))
        
        total_pages = (total + page_size - 1) // page_size
        
        return SubmissionList(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to list submissions"),
        ) from e


# ============================================================================
# ADMIN ENDPOINTS - Review and approve submissions
# ============================================================================

@router.get("/pending", response_model=SubmissionList)
async def list_pending_submissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    List all pending submissions (admin only).
    
    Args:
        page: Page number
        page_size: Items per page
        current_user: Authenticated admin user
        db: Database session
        
    Returns:
        Paginated list of pending submissions
    """
    from sqlalchemy import text
    
    try:
        # Use raw SQL to bypass RLS for admin access to all submissions
        offset_val = (page - 1) * page_size
        
        # Get total count using raw SQL
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM marketplace_submission WHERE status = 'pending'")
        )
        total = count_result.scalar()
        
        # Get paginated submissions using raw SQL
        result = await db.execute(
            text("""
                SELECT id, "workflowId", "submittedById", "marketplaceName", 
                       "marketplaceDescription", status, "reviewedById", 
                       "reviewedAt", "rejectionReason", "createdAt", "updatedAt",
                       submission_type, meta
                FROM marketplace_submission 
                WHERE status = 'pending'
                ORDER BY "createdAt" ASC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": page_size, "offset": offset_val}
        )
        submissions = result.fetchall()
        
        # Batch-fetch workflow names and user details
        user_ids = list({sub[2] for sub in submissions if sub[2]})
        
        wf_name_map = await _fetch_workflow_names_as_owners(
            db, submissions, current_user.id
        )
        
        user_map = {}
        if user_ids:
            user_result = await db.execute(
                text('SELECT id, email, "firstName", "lastName" FROM "user" WHERE id = ANY(:ids)'),
                {"ids": user_ids}
            )
            for row in user_result.fetchall():
                user_map[row[0]] = {
                    "email": row[1],
                    "name": f"{row[2] or ''} {row[3] or ''}".strip() or None
                }
        
        items = []
        for sub in submissions:
            sub_id = sub[0]
            workflow_id = sub[1]
            submitted_by_id = sub[2]
            marketplace_name = sub[3]
            marketplace_desc = sub[4]
            sub_status = sub[5]
            reviewed_by_id = sub[6]
            reviewed_at = sub[7]
            rejection_reason = sub[8]
            created_at = sub[9]
            updated_at = sub[10]
            sub_type = sub[11] or "workflow"
            sub_meta = sub[12]
            
            user_info = user_map.get(submitted_by_id, {})

            parsed_meta = None
            if sub_meta is not None:
                if isinstance(sub_meta, dict):
                    parsed_meta = sub_meta
                elif isinstance(sub_meta, str):
                    try:
                        parsed_meta = json.loads(sub_meta)
                    except (json.JSONDecodeError, TypeError):
                        parsed_meta = None
            
            items.append(SubmissionResponse(
                id=sub_id,
                workflowId=workflow_id,
                submittedById=submitted_by_id,
                marketplaceName=marketplace_name,
                marketplaceDescription=marketplace_desc,
                status=sub_status,
                submission_type=sub_type,
                meta=parsed_meta,
                reviewedById=reviewed_by_id,
                reviewedAt=reviewed_at,
                rejectionReason=rejection_reason,
                createdAt=created_at,
                updatedAt=updated_at,
                workflowName=wf_name_map.get(workflow_id) if workflow_id else None,
                submitterName=user_info.get("name"),
                submitterEmail=user_info.get("email"),
            ))
        
        total_pages = (total + page_size - 1) // page_size
        
        return SubmissionList(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to list pending submissions"),
        ) from e


@router.get("/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get submission details.
    
    Users can only see their own submissions. Admins can see all.
    
    Args:
        submission_id: Submission ID
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Submission details
    """
    from sqlalchemy import text
    
    try:
        # Use raw SQL to bypass RLS (needed for admin access)
        result = await db.execute(
            text("""
                SELECT id, "workflowId", "submittedById", "marketplaceName", 
                       "marketplaceDescription", status, "reviewedById", 
                       "reviewedAt", "rejectionReason", "createdAt", "updatedAt"
                FROM marketplace_submission 
                WHERE id = :submission_id
            """),
            {"submission_id": submission_id}
        )
        sub = result.fetchone()
        
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        
        sub_id = sub[0]
        workflow_id = sub[1]
        submitted_by_id = sub[2]
        marketplace_name = sub[3]
        marketplace_desc = sub[4]
        sub_status = sub[5]
        reviewed_by_id = sub[6]
        reviewed_at = sub[7]
        rejection_reason = sub[8]
        created_at = sub[9]
        updated_at = sub[10]
        
        # Check access: users can only see their own, admins can see all
        if submitted_by_id != current_user.id and not is_admin(current_user):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get workflow using raw SQL
        wf_result = await db.execute(
            text("SELECT name FROM workflow_entity WHERE id = :wf_id"),
            {"wf_id": workflow_id}
        )
        wf_row = wf_result.fetchone()
        workflow_name = wf_row[0] if wf_row else None
        
        # Get submitter using raw SQL
        user_result = await db.execute(
            text('SELECT email, "firstName", "lastName" FROM "user" WHERE id = :user_id'),
            {"user_id": submitted_by_id}
        )
        user_row = user_result.fetchone()
        submitter_email = user_row[0] if user_row else None
        submitter_name = f"{user_row[1] or ''} {user_row[2] or ''}".strip() if user_row else None
        
        return SubmissionResponse(
            id=sub_id,
            workflowId=workflow_id,
            submittedById=submitted_by_id,
            marketplaceName=marketplace_name,
            marketplaceDescription=marketplace_desc,
            status=sub_status,
            reviewedById=reviewed_by_id,
            reviewedAt=reviewed_at,
            rejectionReason=rejection_reason,
            createdAt=created_at,
            updatedAt=updated_at,
            workflowName=workflow_name,
            submitterName=submitter_name if submitter_name else None,
            submitterEmail=submitter_email
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to get submission"),
        ) from e


@router.get("/{submission_id}/workflow", response_model=SubmissionWorkflowPreview)
async def get_submission_workflow_preview(
    submission_id: str,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Return the submitted workflow graph for admin inspection (read-only preview).

    Loads the graph under the submitter's RLS context (admin cannot SELECT
    another user's private workflow_entity rows directly).
    """
    try:
        sub_result = await db.execute(
            text("""
                SELECT id, "workflowId", "submittedById", "marketplaceName",
                       "marketplaceDescription", status, submission_type
                FROM marketplace_submission
                WHERE id = :submission_id
            """),
            {"submission_id": submission_id},
        )
        sub_row = sub_result.fetchone()

        if not sub_row:
            raise HTTPException(status_code=404, detail="Submission not found")

        if (sub_row[6] or "workflow") != "workflow":
            raise HTTPException(status_code=400, detail="Submission is not a workflow")

        if sub_row[5] != "pending":
            raise HTTPException(status_code=400, detail="Can only preview pending submissions")

        workflow_id = sub_row[1]
        owner_id = sub_row[2]
        if not workflow_id:
            raise HTTPException(status_code=404, detail="Submission has no workflow")

        source_row = await _fetch_workflow_row_as_owner(
            db,
            workflow_id,
            owner_id,
            current_user.id,
            select_sql="""
                SELECT id, name, description, nodes, connections, settings, meta
                FROM workflow_entity
                WHERE id = :workflow_id
            """,
        )

        if not source_row:
            raise HTTPException(
                status_code=404,
                detail="Source workflow not found (may have been deleted)",
            )

        return SubmissionWorkflowPreview(
            workflowId=source_row[0],
            name=source_row[1],
            description=source_row[2],
            nodes=source_row[3],
            connections=source_row[4],
            settings=source_row[5],
            meta=source_row[6],
            marketplaceName=sub_row[3],
            marketplaceDescription=sub_row[4],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to load submission workflow"),
        ) from e


@router.post("/{submission_id}/test")
async def test_submission_workflow(
    submission_id: str,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    Copy submission workflow to admin's workflows for testing (admin only).
    
    Creates a copy of the workflow in the admin's account so they can test it.
    
    Args:
        submission_id: Submission ID
        current_user: Authenticated admin user
        db: Database session
        
    Returns:
        New workflow created for testing
    """
    from sqlalchemy import text
    
    try:
        # Get submission using raw SQL to bypass RLS
        # (Admin needs to see submissions from all users)
        sub_result = await db.execute(
            text("""
                SELECT id, "workflowId", "submittedById", "marketplaceName",
                       "marketplaceDescription", status
                FROM marketplace_submission
                WHERE id = :submission_id
            """),
            {"submission_id": submission_id}
        )
        sub_row = sub_result.fetchone()
        
        if not sub_row:
            raise HTTPException(status_code=404, detail="Submission not found")
        
        submission_status = sub_row[5]
        if submission_status != 'pending':
            raise HTTPException(status_code=400, detail="Can only test pending submissions")
        
        workflow_id = sub_row[1]
        owner_id = sub_row[2]
        marketplace_name = sub_row[3]
        marketplace_desc = sub_row[4]
        
        source_row = await _fetch_workflow_row_as_owner(
            db,
            workflow_id,
            owner_id,
            current_user.id,
            select_sql="""
                SELECT id, name, description, nodes, connections, settings, "staticData", meta
                FROM workflow_entity
                WHERE id = :workflow_id
            """,
        )
        
        if not source_row:
            raise HTTPException(status_code=404, detail="Source workflow not found")
        
        # Create test copy for admin
        new_workflow_id = str(uuid.uuid4())
        test_workflow = WorkflowEntity(
            id=new_workflow_id,
            name=f"[TEST] {marketplace_name}",
            description=f"Test copy of submission: {marketplace_desc or ''}",
            active=True,
            nodes=source_row[3],       # nodes
            connections=source_row[4], # connections
            settings=source_row[5],    # settings
            staticData=source_row[6],  # staticData
            pinData=None,
            versionId=None,
            triggerCount=0,
            meta=source_row[7],        # meta
            parentFolderId=None,
            isArchived=False,
            isDraft=False,  # Create as published so admin can run it
            createdById=current_user.id,
            createdByName=f"{current_user.firstName or ''} {current_user.lastName or ''}".strip() or current_user.email,
            isPublic=False,
            marketplaceName=None,
            marketplaceDescription=None
        )
        
        db.add(test_workflow)
        await db.commit()
        
        logger.info(f"✅ Admin {current_user.id} created test workflow {new_workflow_id} for submission {submission_id}")
        
        return {
            "message": "Test workflow created successfully",
            "testWorkflowId": new_workflow_id,
            "testWorkflowName": test_workflow.name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to create test workflow"),
        ) from e


@router.post("/{submission_id}/approve")
async def approve_submission(
    submission_id: str,
    body: Optional[ApproveSubmissionRequest] = None,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    Approve a submission and publish workflow to marketplace (admin only).
    
    This will:
    1. Set workflow isPublic=true with marketplace name/description
    2. Auto-share any knowledge bases referenced in the workflow
    3. Update submission status to 'approved'
    
    Args:
        submission_id: Submission ID
        current_user: Authenticated admin user
        db: Database session
        
    Returns:
        Success message
    """
    from sqlalchemy import text
    
    try:
        # Get submission using raw SQL to bypass RLS
        # (Admin needs to see submissions from all users)
        sub_result = await db.execute(
            text("""
                SELECT id, "workflowId", "submittedById", "marketplaceName", 
                       "marketplaceDescription", status, submission_type, meta
                FROM marketplace_submission 
                WHERE id = :submission_id
            """),
            {"submission_id": submission_id}
        )
        sub_row = sub_result.fetchone()
        
        if not sub_row:
            raise HTTPException(status_code=404, detail="Submission not found")
        
        submission_status = sub_row[5]
        if submission_status != 'pending':
            raise HTTPException(status_code=400, detail=f"Submission is already {submission_status}")
        
        submission_type = sub_row[6] or "workflow"
        submission_meta = sub_row[7]

        # ── Handle shared_tool submissions ──────────────────────────────
        if submission_type == "shared_tool":
            return await _approve_shared_tool_submission(
                db, submission_id, submission_meta, current_user, body
            )

        workflow_id = sub_row[1]
        owner_id = sub_row[2]

        if submission_type == SUBMISSION_TYPE_SHARE_GRANT:
            return await _approve_workflow_share_grant(
                db, submission_id, workflow_id, owner_id, submission_meta, current_user
            )

        if submission_type == SUBMISSION_TYPE_SHARE_VERSION:
            return await _approve_workflow_share_version(
                db, submission_id, workflow_id, owner_id, submission_meta, current_user
            )

        # ── Standard marketplace workflow approval (existing logic) ─────
        marketplace_name = sub_row[3]
        marketplace_desc = sub_row[4]
        
        workflow_row = await _fetch_workflow_row_as_owner(
            db,
            workflow_id,
            owner_id,
            current_user.id,
            select_sql="""
                SELECT id, name, nodes, meta
                FROM workflow_entity
                WHERE id = :workflow_id
            """,
        )
        
        if not workflow_row:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        workflow_nodes = workflow_row[2]
        
        # Publish as the workflow owner so RLS permits UPDATE on their row.
        await set_user_context(db, owner_id)
        try:
            await db.execute(
                text("""
                    UPDATE workflow_entity
                    SET "isPublic" = true,
                        "marketplaceName" = :marketplace_name,
                        "marketplaceDescription" = :marketplace_desc,
                        "approvedVersionId" = "versionId",
                        "updatedAt" = NOW()
                    WHERE id = :workflow_id
                """),
                {
                    "workflow_id": workflow_id,
                    "marketplace_name": marketplace_name,
                    "marketplace_desc": marketplace_desc,
                },
            )
        finally:
            await set_user_context(db, current_user.id)
        
        # Auto-share knowledge bases referenced in the workflow
        # Create a simple workflow-like object for the helper function
        class WorkflowStub:
            def __init__(self, nodes):
                self.nodes = nodes
        
        workflow_stub = WorkflowStub(workflow_nodes)
        kb_ids = _extract_kb_ids_from_workflow(workflow_stub)
        
        if kb_ids:
            logger.info(f"📚 Auto-sharing {len(kb_ids)} knowledge bases for workflow {workflow_id}")
            await db.execute(
                text("""
                    UPDATE knowledge_base 
                    SET "isPublic" = true, 
                        "marketplaceName" = :marketplace_name, 
                        "marketplaceDescription" = :marketplace_desc,
                        "updatedAt" = NOW()
                    WHERE id = ANY(:kb_ids)
                """),
                {
                    "kb_ids": kb_ids,
                    "marketplace_name": f"KB for {marketplace_name}",
                    "marketplace_desc": "Knowledge base shared with marketplace workflow"
                }
            )
        
        # Update submission status using raw SQL (bypasses RLS)
        await db.execute(
            text("""
                UPDATE marketplace_submission 
                SET status = 'approved',
                    "reviewedById" = :reviewer_id,
                    "reviewedAt" = NOW(),
                    "updatedAt" = NOW()
                WHERE id = :submission_id
            """),
            {
                "submission_id": submission_id,
                "reviewer_id": current_user.id
            }
        )
        
        await db.commit()
        
        logger.info(f"✅ Admin {current_user.id} approved submission {submission_id}, workflow {workflow_id} now public")
        
        return {
            "message": "Workflow approved and published to marketplace",
            "workflowId": workflow_id,
            "marketplaceName": marketplace_name,
            "sharedKnowledgeBases": len(kb_ids) if kb_ids else 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to approve submission"),
        ) from e


def _parse_submission_meta(meta_value) -> Dict[str, Any]:
    if meta_value is None:
        return {}
    if isinstance(meta_value, dict):
        return meta_value
    if isinstance(meta_value, str):
        try:
            return json.loads(meta_value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


async def _approve_workflow_share_grant(
    db: AsyncSession,
    submission_id: str,
    workflow_id: str,
    owner_id: str,
    meta_value,
    current_user: User,
):
    from sqlalchemy import text

    meta = _parse_submission_meta(meta_value)
    if not meta.get("principalId") and not meta.get("principals"):
        raise HTTPException(status_code=400, detail="Submission metadata is missing grant details")

    await set_user_context(db, owner_id)
    try:
        await apply_share_grants_from_meta(
            db, workflow_id, meta, granted_by_id=owner_id
        )
        for p in meta.get("principals") or [meta]:
            if p.get("principalType") == "group" and p.get("displayName"):
                await db.execute(
                    text("""
                        INSERT INTO ad_group (id, "displayName", "lastSyncedAt", "createdAt")
                        VALUES (:id, :name, NOW(), NOW())
                        ON CONFLICT (id) DO UPDATE
                        SET "displayName" = EXCLUDED."displayName",
                            "lastSyncedAt" = NOW()
                    """),
                    {"id": p["principalId"], "name": p["displayName"]},
                )

        await db.execute(
            text("""
                UPDATE workflow_entity
                SET "approvedVersionId" = "versionId",
                    "updatedAt" = NOW()
                WHERE id = :workflow_id
                  AND "versionId" IS NOT NULL
            """),
            {"workflow_id": workflow_id},
        )
    finally:
        await set_user_context(db, current_user.id)

    await db.execute(
        text("""
            UPDATE marketplace_submission
            SET status = 'approved',
                "reviewedById" = :reviewer_id,
                "reviewedAt" = NOW(),
                "updatedAt" = NOW()
            WHERE id = :submission_id
        """),
        {"submission_id": submission_id, "reviewer_id": current_user.id},
    )
    await db.commit()

    return {
        "message": "Share grant approved. Recipients can now access this workflow.",
        "workflowId": workflow_id,
    }


async def _approve_workflow_share_version(
    db: AsyncSession,
    submission_id: str,
    workflow_id: str,
    owner_id: str,
    meta_value,
    current_user: User,
):
    from sqlalchemy import text

    meta = _parse_submission_meta(meta_value)
    proposed_version_id = meta.get("proposedVersionId")
    if not proposed_version_id:
        raise HTTPException(status_code=400, detail="Submission metadata is missing proposedVersionId")

    snap = await db.execute(
        select(WorkflowHistory).where(
            WorkflowHistory.versionId == proposed_version_id,
            WorkflowHistory.workflowId == workflow_id,
        )
    )
    if snap.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail="Proposed version snapshot not found")

    await set_user_context(db, owner_id)
    try:
        await db.execute(
            text("""
                UPDATE workflow_entity
                SET "approvedVersionId" = :version_id,
                    "updatedAt" = NOW()
                WHERE id = :workflow_id
            """),
            {"workflow_id": workflow_id, "version_id": proposed_version_id},
        )
    finally:
        await set_user_context(db, current_user.id)

    await db.execute(
        text("""
            UPDATE marketplace_submission
            SET status = 'approved',
                "reviewedById" = :reviewer_id,
                "reviewedAt" = NOW(),
                "updatedAt" = NOW()
            WHERE id = :submission_id
        """),
        {"submission_id": submission_id, "reviewer_id": current_user.id},
    )
    await db.commit()

    return {
        "message": "Published version approved for shared recipients.",
        "workflowId": workflow_id,
        "approvedVersionId": proposed_version_id,
    }


async def _approve_shared_tool_submission(
    db: AsyncSession,
    submission_id: str,
    meta_value,
    current_user: User,
    overrides: Optional[ApproveSubmissionRequest] = None,
):
    """Handle approval of a shared_tool submission."""
    from sqlalchemy import text
    from admin.services.shared_tool_service import SharedToolService

    if meta_value is None:
        meta = {}
    elif isinstance(meta_value, dict):
        meta = meta_value
    elif isinstance(meta_value, str):
        try:
            meta = json.loads(meta_value)
        except (json.JSONDecodeError, TypeError):
            meta = {}
    else:
        meta = {}

    tool_name = meta.get("tool_name", "Untitled Tool")
    description = meta.get("description")
    url = meta.get("url")
    is_public = meta.get("is_public", False)
    ad_group_names = meta.get("ad_group_names", [])
    emails = meta.get("emails", [])

    if overrides:
        if overrides.is_public is not None:
            is_public = overrides.is_public
        if overrides.ad_group_names is not None:
            ad_group_names = overrides.ad_group_names
        if overrides.emails is not None:
            emails = overrides.emails

    if not url:
        raise HTTPException(status_code=400, detail="Submission metadata is missing 'url'")

    result, error = await SharedToolService.create_tool(
        db,
        tool_name=tool_name,
        description=description,
        url=url,
        is_public=is_public,
        ad_group_names=ad_group_names,
        emails=emails,
        created_by=current_user.id,
        auto_approve=True,
    )

    if error:
        raise HTTPException(status_code=409, detail=error)

    # Mark submission as approved
    await db.execute(
        text("""
            UPDATE marketplace_submission 
            SET status = 'approved',
                "reviewedById" = :reviewer_id,
                "reviewedAt" = NOW(),
                "updatedAt" = NOW()
            WHERE id = :submission_id
        """),
        {"submission_id": submission_id, "reviewer_id": current_user.id}
    )

    await db.commit()
    logger.info(f"✅ Admin {current_user.id} approved shared_tool submission {submission_id}")

    return {
        "message": "External tool approved and published to storefront",
        "toolId": result["id"] if result else None,
        "toolName": tool_name,
    }


@router.post("/{submission_id}/reject")
async def reject_submission(
    submission_id: str,
    rejection: RejectionRequest,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    Reject a submission with reason (admin only).
    
    The submitter will be notified of the rejection with the reason provided.
    They can resubmit after making changes.
    
    Args:
        submission_id: Submission ID
        rejection: Rejection reason
        current_user: Authenticated admin user
        db: Database session
        
    Returns:
        Success message
    """
    from sqlalchemy import text
    
    try:
        # Get submission using raw SQL to bypass RLS
        # (Admin needs to see submissions from all users)
        sub_result = await db.execute(
            text("""
                SELECT id, status
                FROM marketplace_submission 
                WHERE id = :submission_id
            """),
            {"submission_id": submission_id}
        )
        sub_row = sub_result.fetchone()
        
        if not sub_row:
            raise HTTPException(status_code=404, detail="Submission not found")
        
        submission_status = sub_row[1]
        if submission_status != 'pending':
            raise HTTPException(status_code=400, detail=f"Submission is already {submission_status}")
        
        # Update submission status using raw SQL (bypasses RLS)
        await db.execute(
            text("""
                UPDATE marketplace_submission 
                SET status = 'rejected',
                    "reviewedById" = :reviewer_id,
                    "reviewedAt" = NOW(),
                    "rejectionReason" = :reason,
                    "updatedAt" = NOW()
                WHERE id = :submission_id
            """),
            {
                "submission_id": submission_id,
                "reviewer_id": current_user.id,
                "reason": rejection.reason
            }
        )
        
        await db.commit()
        
        logger.info(f"❌ Admin {current_user.id} rejected submission {submission_id}: {rejection.reason}")
        
        return {
            "message": "Submission rejected",
            "submissionId": submission_id,
            "reason": rejection.reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to reject submission"),
        ) from e


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# Keys that may hold a SINGLE KB id (string). Historically set by the
# Agent node — see `app/workflow/nodes/agent.py::knowledgeBaseId`.
_SCALAR_KB_KEYS = ("knowledgeBaseId", "kbId", "kb_id", "knowledgeBase")

# Keys that may hold a LIST of KB ids. The Code Executor node uses
# `knowledgeBaseIds` (plural) to support multi-KB attachment — see
# `app/workflow/nodes/code_executor.py::_setup_kb_session`. The other
# aliases here are defensive: the generate-code API accepts the snake
# case variant and some older builds of the palette shipped `kbIds`.
_LIST_KB_KEYS = (
    "knowledgeBaseIds",
    "knowledge_base_ids",
    "kbIds",
    "kb_ids",
    "knowledgeBases",
)


def _is_valid_kb_id(value: Any) -> bool:
    """Return True if `value` looks like a KB UUID string."""
    if not isinstance(value, str):
        return False
    # Reject common non-UUID scalar values stored under the same key
    # accidentally (e.g. a boolean toggle that happens to share the name).
    if value.lower() in ("true", "false", "yes", "no", ""):
        return False
    # Accept both dashed (36 char) and undashed (32 char) UUID forms.
    return len(value) >= 32


def _collect_kb_ids_from_dict(src: Any) -> Iterable[str]:
    """
    Yield every KB-id-looking value reachable from a single node-config
    dict. Handles both the scalar form used by Agent nodes and the list
    form used by Code Executor nodes.

    List values are tolerated as:
      * a real list/tuple/set of UUID strings (the typical case), or
      * a comma-separated string — this matches the "be liberal" behavior
        in `code_executor.py`, which splits comma strings at runtime.
    """
    if not isinstance(src, dict):
        return

    for key in _SCALAR_KB_KEYS:
        value = src.get(key)
        if _is_valid_kb_id(value):
            yield value

    for key in _LIST_KB_KEYS:
        value = src.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            # Comma-separated fallback — mirrors the CE runtime loader.
            for piece in value.split(","):
                piece = piece.strip()
                if _is_valid_kb_id(piece):
                    yield piece
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if _is_valid_kb_id(item):
                    yield item


def _extract_kb_ids_from_workflow(workflow: WorkflowEntity) -> List[str]:
    """
    Extract knowledge base IDs referenced in a workflow's nodes.

    Scans each node under three shapes:
      * `data.<key>`           — legacy flat shape used by some nodes
      * `data.parameters.<key>`— older parameter-based shape
      * `data.config.<key>`    — current canonical shape (see parser.py)

    Recognizes both the scalar keys used by Agent nodes
    (`knowledgeBaseId`, ...) and the list keys used by Code Executor
    nodes (`knowledgeBaseIds`, ...). Returning the same KB id from
    multiple keys/locations is fine — the result is a deduped list.

    This is what gets called from `approve_submission` to auto-share
    every KB a workflow depends on, so consumers who install the
    workflow from the marketplace can read those KBs via the public-
    visibility RLS policy in `app/db/init_security.py`.
    """
    kb_ids: set[str] = set()

    if not workflow.nodes:
        return list(kb_ids)

    try:
        nodes = (
            json.loads(workflow.nodes)
            if isinstance(workflow.nodes, str)
            else workflow.nodes
        )

        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data", {}) or {}
            parameters = data.get("parameters", {}) if isinstance(data, dict) else {}
            config = data.get("config", {}) if isinstance(data, dict) else {}

            for src in (data, parameters, config):
                kb_ids.update(_collect_kb_ids_from_dict(src))

    except Exception as e:
        logger.warning(f"Error extracting KB IDs from workflow: {e}")

    return list(kb_ids)
