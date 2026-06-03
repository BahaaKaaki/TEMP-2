"""
Shared External Tools router.

Public endpoints:
- GET  /api/shared-tools/list   — tools visible to current user (Storefront)
- POST /api/shared-tools/submit — user submits a tool for admin approval

Admin endpoints:
- GET    /api/admin/shared-tools            — list all tools (any status)
- POST   /api/admin/shared-tools            — create single tool (auto-approved)
- PUT    /api/admin/shared-tools/{id}       — update tool
- DELETE /api/admin/shared-tools/{id}       — delete tool
- POST   /api/admin/shared-tools/csv-upload — bulk CSV import
- GET    /api/admin/shared-tools/audit-log  — view audit trail
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
import uuid
import logging
from datetime import datetime

from db.pgsql import get_write_db
from db.models import User, MarketplaceSubmission
from core.dependencies import get_current_user, get_current_admin_user, get_db_with_user_context
from admin.services.shared_tool_service import SharedToolService

logger = logging.getLogger(__name__)


# ============================================================================
# SCHEMAS
# ============================================================================

class SharedToolCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    url: str
    is_public: bool = False
    ad_group_names: List[str] = []
    emails: List[str] = []


class SharedToolUpdate(BaseModel):
    tool_name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    is_public: Optional[bool] = None
    ad_group_names: Optional[List[str]] = None
    emails: Optional[List[str]] = None


class SharedToolSubmit(BaseModel):
    tool_name: str
    description: Optional[str] = None
    url: str
    is_public: bool = False
    ad_group_names: List[str] = []
    emails: List[str] = []


# ============================================================================
# PUBLIC ROUTER (authenticated users)
# ============================================================================

public_router = APIRouter(
    prefix="/api/shared-tools",
    tags=["Shared Tools"],
    dependencies=[Depends(get_current_user)],
)


@public_router.get("/list")
async def list_visible_tools(
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """List shared tools visible to the current user (Storefront)."""
    tools = await SharedToolService.list_visible(db)
    return {"items": tools}


@public_router.post("/submit")
async def submit_tool_for_approval(
    body: SharedToolSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """
    Submit an external tool for admin approval.
    Creates a marketplace_submission with submission_type='shared_tool'.
    """
    submission_id = str(uuid.uuid4())

    meta = {
        "tool_name": body.tool_name,
        "description": body.description,
        "url": body.url,
        "is_public": body.is_public,
        "ad_group_names": body.ad_group_names,
        "emails": body.emails,
    }

    submission = MarketplaceSubmission(
        id=submission_id,
        workflowId=None,
        submittedById=current_user.id,
        marketplaceName=body.tool_name,
        marketplaceDescription=body.description,
        status="pending",
        submission_type="shared_tool",
        meta=meta,
        createdAt=datetime.utcnow(),
        updatedAt=datetime.utcnow(),
    )
    db.add(submission)
    await db.commit()

    return {
        "id": submission_id,
        "status": "pending",
        "message": "Tool submitted for admin approval",
    }


# ============================================================================
# ADMIN ROUTER
# ============================================================================

admin_router = APIRouter(
    prefix="/api/admin/shared-tools",
    tags=["Admin - Shared Tools"],
    dependencies=[Depends(get_current_admin_user)],
)


@admin_router.get("")
async def list_all_shared_tools(
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """List all shared tools with permissions (admin only)."""
    tools = await SharedToolService.list_all(db)
    return {"items": tools, "total": len(tools)}


@admin_router.post("")
async def create_shared_tool(
    body: SharedToolCreate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """Create a single shared tool (auto-approved, admin only)."""
    result, error = await SharedToolService.create_tool(
        db,
        tool_name=body.tool_name,
        description=body.description,
        url=body.url,
        is_public=body.is_public,
        ad_group_names=body.ad_group_names,
        emails=body.emails,
        created_by=current_user.id,
        auto_approve=True,
    )
    if error:
        raise HTTPException(status_code=409, detail=error)
    await db.commit()
    return result


@admin_router.put("/{tool_id}")
async def update_shared_tool(
    tool_id: str,
    body: SharedToolUpdate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """Update a shared tool (admin only)."""
    result, error = await SharedToolService.update_tool(
        db,
        tool_id,
        tool_name=body.tool_name,
        description=body.description,
        url=body.url,
        is_public=body.is_public,
        ad_group_names=body.ad_group_names,
        emails=body.emails,
        admin_user_id=current_user.id,
    )
    if error:
        raise HTTPException(status_code=404, detail=error)
    await db.commit()
    return result


@admin_router.delete("/{tool_id}")
async def delete_shared_tool(
    tool_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """Delete a shared tool (admin only)."""
    error = await SharedToolService.delete_tool(db, tool_id, current_user.id)
    if error:
        raise HTTPException(status_code=404, detail=error)
    await db.commit()
    return {"message": "Tool deleted successfully"}


@admin_router.post("/csv-upload")
async def upload_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """
    Bulk import shared tools from CSV.
    Expected header: tool_name,description,url,is_public,ad_group_csv,email_csv
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    result = await SharedToolService.parse_and_import_csv(
        db, text, current_user.id, filename=file.filename
    )

    if "error" in result and result.get("created", 0) == 0:
        raise HTTPException(status_code=400, detail=result["error"])

    await db.commit()
    return result


@admin_router.get("/audit-log")
async def get_audit_log(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """Get shared tool audit log (admin only)."""
    entries = await SharedToolService.get_audit_log(db, limit=limit, offset=offset)
    return {"items": entries, "total": len(entries)}
