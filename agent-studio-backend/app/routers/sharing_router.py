"""
Sharing router: AD group / per-user grants for workflows and knowledge bases.

Endpoints
---------
Workflows:
  POST   /api/sharing/workflows/{workflow_id}/shares          create grant
  GET    /api/sharing/workflows/{workflow_id}/shares          list grants
  DELETE /api/sharing/workflows/{workflow_id}/shares/{share}  revoke grant

Knowledge bases:
  POST   /api/sharing/knowledge-bases/{kb_id}/shares
  GET    /api/sharing/knowledge-bases/{kb_id}/shares
  DELETE /api/sharing/knowledge-bases/{kb_id}/shares/{share}

Shared-with-me feed:
  GET    /api/sharing/shared-with-me/workflows
  GET    /api/sharing/shared-with-me/knowledge-bases

Discovery / pickers:
  GET    /api/sharing/groups/search?q=...      AD-group typeahead (admin/Graph)
  GET    /api/sharing/groups/me                groups the caller is in
  GET    /api/sharing/users/search?q=...       local user typeahead

Authorization
-------------
RLS enforces that:
  * Only the resource owner can SELECT/INSERT/UPDATE/DELETE rows in the
    workflow_share / knowledge_base_share tables for their resource.
  * Group members and explicit user grantees can SELECT shares targeting
    them (so the UI can render "I have access via group X").

We therefore rely on RLS for the heavy authorization lifting and only
sanity-check ownership in the service layer where the UX needs a friendly
403 instead of a silent 404.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.dependencies import get_current_user, get_db_with_user_context
from db.models import (
    AdGroup,
    KnowledgeBaseEntity,
    KnowledgeBaseShare,
    MarketplaceSubmission,
    User,
    UserGroup,
    WorkflowEntity,
    WorkflowShare,
)
from workflow_share_approval import (
    SUBMISSION_TYPE_SHARE_GRANT,
    build_grant_meta,
    get_pending_submission,
    grant_requires_approval,
    SUBMISSION_TYPE_SHARE_VERSION,
)
from utils.errors import safe_error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/sharing",
    tags=["Sharing"],
    dependencies=[Depends(get_current_user)],
)


# ============================================================================
# Schemas
# ============================================================================

PrincipalType = Literal["group", "user"]
Permission = Literal["read", "write"]


class CreateShareRequest(BaseModel):
    principalType: PrincipalType
    principalId: str = Field(..., min_length=1, max_length=36)
    permission: Permission = "read"
    # Optional metadata used to auto-populate the ad_group cache when the
    # caller picks a group from the search dropdown (so we don't have to make
    # another Graph round-trip server-side).
    displayName: Optional[str] = Field(None, max_length=255)

    @validator("principalId")
    def _validate_principal_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("principalId must be a UUID/GUID")
        return v


class ShareResponse(BaseModel):
    id: str
    resourceId: str
    principalType: PrincipalType
    principalId: str
    principalDisplayName: Optional[str] = None
    principalEmail: Optional[str] = None
    permission: Permission
    grantedById: str
    grantedAt: datetime

    class Config:
        from_attributes = True


class PendingGrantSummary(BaseModel):
    submissionId: str
    submissionType: str
    marketplaceName: str
    meta: Optional[dict] = None
    createdAt: datetime


class ShareListResponse(BaseModel):
    shares: List[ShareResponse]
    pendingGrants: List[PendingGrantSummary] = []


class PendingShareResponse(BaseModel):
    status: Literal["pending"] = "pending"
    submissionId: str
    message: str


class GroupSearchResult(BaseModel):
    id: str
    displayName: Optional[str] = None
    description: Optional[str] = None


class UserSearchResult(BaseModel):
    id: str
    email: str
    displayName: Optional[str] = None


# ============================================================================
# Helpers
# ============================================================================


async def _ensure_workflow_owner(
    db: AsyncSession, workflow_id: str, current_user: User
) -> WorkflowEntity:
    """Return the workflow if the caller owns it; raise 404/403 otherwise.

    Note: RLS already filters out workflows the user can't see, but it admits
    workflows shared with the user too — for the *write* endpoints below we
    additionally require ownership.
    """
    result = await db.execute(
        select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if wf.createdById != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the workflow owner can manage sharing",
        )
    return wf


async def _ensure_kb_owner(
    db: AsyncSession, kb_id: str, current_user: User
) -> KnowledgeBaseEntity:
    result = await db.execute(
        select(KnowledgeBaseEntity).where(KnowledgeBaseEntity.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.createdBy != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the knowledge base owner can manage sharing",
        )
    return kb


async def _upsert_ad_group_cache(
    db: AsyncSession,
    group_id: str,
    display_name: Optional[str],
) -> None:
    """Insert or update a row in ad_group so the share UI can render names."""
    existing = await db.execute(select(AdGroup).where(AdGroup.id == group_id))
    ag = existing.scalar_one_or_none()
    now = datetime.utcnow()
    if ag:
        if display_name and ag.displayName != display_name:
            ag.displayName = display_name
        ag.lastSyncedAt = now
    else:
        db.add(AdGroup(
            id=group_id,
            displayName=display_name,
            lastSyncedAt=now,
            createdAt=now,
        ))
    await db.flush()


async def _hydrate_workflow_shares(
    db: AsyncSession, shares: List[WorkflowShare]
) -> List[ShareResponse]:
    return await _hydrate_shares(
        db,
        [(s.id, s.workflowId, s.principalType, s.principalId,
          s.permission, s.grantedById, s.grantedAt) for s in shares],
    )


async def _hydrate_kb_shares(
    db: AsyncSession, shares: List[KnowledgeBaseShare]
) -> List[ShareResponse]:
    return await _hydrate_shares(
        db,
        [(s.id, s.knowledgeBaseId, s.principalType, s.principalId,
          s.permission, s.grantedById, s.grantedAt) for s in shares],
    )


async def _hydrate_shares(
    db: AsyncSession, rows: List[tuple]
) -> List[ShareResponse]:
    """Resolve principal display names for a batch of share rows."""
    if not rows:
        return []

    user_ids = {pid for (_, _, ptype, pid, *_) in rows if ptype == "user"}
    group_ids = {pid for (_, _, ptype, pid, *_) in rows if ptype == "group"}

    users_by_id: dict[str, User] = {}
    if user_ids:
        users = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_by_id = {u.id: u for u in users.scalars().all()}

    groups_by_id: dict[str, AdGroup] = {}
    if group_ids:
        groups = await db.execute(select(AdGroup).where(AdGroup.id.in_(group_ids)))
        groups_by_id = {g.id: g for g in groups.scalars().all()}

    out: List[ShareResponse] = []
    for sid, rid, ptype, pid, perm, granted_by, granted_at in rows:
        display: Optional[str] = None
        email: Optional[str] = None
        if ptype == "user":
            u = users_by_id.get(pid)
            if u:
                display = " ".join(
                    part for part in [u.firstName, u.lastName] if part
                ) or u.email
                email = u.email
        else:
            g = groups_by_id.get(pid)
            if g:
                display = g.displayName
        out.append(ShareResponse(
            id=sid,
            resourceId=rid,
            principalType=ptype,
            principalId=pid,
            principalDisplayName=display,
            principalEmail=email,
            permission=perm,
            grantedById=granted_by,
            grantedAt=granted_at,
        ))
    return out


# ============================================================================
# Workflow share endpoints
# ============================================================================


@router.post(
    "/workflows/{workflow_id}/shares",
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_share(
    workflow_id: str,
    body: CreateShareRequest,
    force: bool = Query(
        False,
        description="Replace an existing pending approval submission for this workflow",
    ),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """Grant access to a workflow for an AD group or a specific user."""
    workflow = await _ensure_workflow_owner(db, workflow_id, current_user)

    if body.principalType == "user":
        target = await db.execute(select(User).where(User.id == body.principalId))
        if target.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Target user not found")
    else:
        await _upsert_ad_group_cache(db, body.principalId, body.displayName)

    existing_q = await db.execute(
        select(WorkflowShare).where(
            and_(
                WorkflowShare.workflowId == workflow_id,
                WorkflowShare.principalType == body.principalType,
                WorkflowShare.principalId == body.principalId,
            )
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing:
        existing.permission = body.permission
        await db.commit()
        rows = await _hydrate_workflow_shares(db, [existing])
        return rows[0]

    needs_approval = await grant_requires_approval(
        db,
        workflow_id,
        principal_type=body.principalType,
        principal_id=body.principalId,
        is_new_grant=True,
    )

    if needs_approval:
        if not workflow.versionId:
            raise HTTPException(
                status_code=400,
                detail="Publish the workflow at least once before sharing with AD groups or 16+ users.",
            )

        pending = await get_pending_submission(db, workflow_id)
        if pending and not force:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "A share approval is already pending for this workflow.",
                    "has_pending_submission": True,
                    "submissionId": pending.id,
                },
            )
        if pending and force:
            await db.delete(pending)

        label = body.displayName or body.principalId
        if body.principalType == "user":
            u = await db.execute(select(User).where(User.id == body.principalId))
            user_row = u.scalar_one_or_none()
            if user_row and user_row.email:
                label = user_row.email

        submission = MarketplaceSubmission(
            id=str(uuid.uuid4()),
            workflowId=workflow_id,
            submittedById=current_user.id,
            marketplaceName=f"{workflow.name}: share with {label}",
            marketplaceDescription=(
                f"Pending {body.principalType} share ({body.permission})"
            ),
            status="pending",
            submission_type=SUBMISSION_TYPE_SHARE_GRANT,
            meta=build_grant_meta(
                principal_type=body.principalType,
                principal_id=body.principalId,
                permission=body.permission,
                display_name=body.displayName,
            ),
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow(),
        )
        db.add(submission)
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=safe_error_detail(exc, "Failed to submit share for approval"),
            ) from exc

        return PendingShareResponse(
            submissionId=submission.id,
            message="Share submitted for admin approval. Recipients will gain access after approval.",
        )

    share = WorkflowShare(
        id=str(uuid.uuid4()),
        workflowId=workflow_id,
        principalType=body.principalType,
        principalId=body.principalId,
        permission=body.permission,
        grantedById=current_user.id,
        grantedAt=datetime.utcnow(),
    )
    db.add(share)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(exc, "Failed to create share"),
        ) from exc

    rows = await _hydrate_workflow_shares(db, [share])
    return rows[0]


@router.get(
    "/workflows/{workflow_id}/shares",
    response_model=ShareListResponse,
)
async def list_workflow_shares(
    workflow_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """List all sharing grants on a workflow (owner-only)."""
    await _ensure_workflow_owner(db, workflow_id, current_user)
    result = await db.execute(
        select(WorkflowShare)
        .where(WorkflowShare.workflowId == workflow_id)
        .order_by(WorkflowShare.grantedAt.desc())
    )
    shares = list(result.scalars().all())

    pending_result = await db.execute(
        select(MarketplaceSubmission).where(
            MarketplaceSubmission.workflowId == workflow_id,
            MarketplaceSubmission.status == "pending",
            MarketplaceSubmission.submission_type.in_(
                [SUBMISSION_TYPE_SHARE_GRANT, SUBMISSION_TYPE_SHARE_VERSION]
            ),
        ).order_by(MarketplaceSubmission.createdAt.desc())
    )
    pending_rows = [
        PendingGrantSummary(
            submissionId=p.id,
            submissionType=p.submission_type,
            marketplaceName=p.marketplaceName,
            meta=p.meta if isinstance(p.meta, dict) else None,
            createdAt=p.createdAt,
        )
        for p in pending_result.scalars().all()
    ]

    return ShareListResponse(
        shares=await _hydrate_workflow_shares(db, shares),
        pendingGrants=pending_rows,
    )


@router.delete(
    "/workflows/{workflow_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow_share(
    workflow_id: str,
    share_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """Revoke a sharing grant on a workflow."""
    await _ensure_workflow_owner(db, workflow_id, current_user)
    result = await db.execute(
        select(WorkflowShare).where(
            and_(
                WorkflowShare.id == share_id,
                WorkflowShare.workflowId == workflow_id,
            )
        )
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    await db.delete(share)
    await db.commit()


# ============================================================================
# Knowledge base share endpoints
# ============================================================================


@router.post(
    "/knowledge-bases/{kb_id}/shares",
    response_model=ShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_kb_share(
    kb_id: str,
    body: CreateShareRequest,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """Grant access to a knowledge base for an AD group or a specific user."""
    await _ensure_kb_owner(db, kb_id, current_user)

    if body.principalType == "user":
        target = await db.execute(select(User).where(User.id == body.principalId))
        if target.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Target user not found")
    else:
        await _upsert_ad_group_cache(db, body.principalId, body.displayName)

    existing_q = await db.execute(
        select(KnowledgeBaseShare).where(
            and_(
                KnowledgeBaseShare.knowledgeBaseId == kb_id,
                KnowledgeBaseShare.principalType == body.principalType,
                KnowledgeBaseShare.principalId == body.principalId,
            )
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing:
        existing.permission = body.permission
        await db.commit()
        rows = await _hydrate_kb_shares(db, [existing])
        return rows[0]

    share = KnowledgeBaseShare(
        id=str(uuid.uuid4()),
        knowledgeBaseId=kb_id,
        principalType=body.principalType,
        principalId=body.principalId,
        permission=body.permission,
        grantedById=current_user.id,
        grantedAt=datetime.utcnow(),
    )
    db.add(share)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(exc, "Failed to create share"),
        ) from exc

    rows = await _hydrate_kb_shares(db, [share])
    return rows[0]


@router.get(
    "/knowledge-bases/{kb_id}/shares",
    response_model=ShareListResponse,
)
async def list_kb_shares(
    kb_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    await _ensure_kb_owner(db, kb_id, current_user)
    result = await db.execute(
        select(KnowledgeBaseShare)
        .where(KnowledgeBaseShare.knowledgeBaseId == kb_id)
        .order_by(KnowledgeBaseShare.grantedAt.desc())
    )
    shares = list(result.scalars().all())
    return ShareListResponse(shares=await _hydrate_kb_shares(db, shares))


@router.delete(
    "/knowledge-bases/{kb_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_kb_share(
    kb_id: str,
    share_id: str,
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    await _ensure_kb_owner(db, kb_id, current_user)
    result = await db.execute(
        select(KnowledgeBaseShare).where(
            and_(
                KnowledgeBaseShare.id == share_id,
                KnowledgeBaseShare.knowledgeBaseId == kb_id,
            )
        )
    )
    share = result.scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    await db.delete(share)
    await db.commit()


# ============================================================================
# "Shared with me" feed
# ============================================================================


class SharedWorkflowItem(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    isDraft: bool
    createdById: str
    createdByName: Optional[str] = None
    updatedAt: datetime
    via: Literal["group", "user"]
    viaPrincipalId: str
    viaPrincipalDisplayName: Optional[str] = None
    permission: Permission

    class Config:
        from_attributes = True


class SharedKBItem(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    createdBy: str
    createdByName: Optional[str] = None
    via: Literal["group", "user"]
    viaPrincipalId: str
    viaPrincipalDisplayName: Optional[str] = None
    permission: Permission


@router.get(
    "/shared-with-me/workflows",
    response_model=List[SharedWorkflowItem],
)
async def list_shared_with_me_workflows(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Workflows shared with write access (My Tools collaborators).
    Read-only shares appear on the Storefront only, not here.
    Excludes workflows the user owns.
    """
    # Collect "via" rows first (one per principal targeting me)
    my_groups_q = await db.execute(
        select(UserGroup.groupId).where(UserGroup.userId == current_user.id)
    )
    my_group_ids = [row[0] for row in my_groups_q.all()]

    # Build the OR-filter dynamically so an empty group list doesn't generate
    # a SQL "principalId IN ()" (invalid in postgres) or a literal False that
    # short-circuits the whole OR.
    principal_predicates = [
        and_(
            WorkflowShare.principalType == "user",
            WorkflowShare.principalId == current_user.id,
        )
    ]
    if my_group_ids:
        principal_predicates.append(and_(
            WorkflowShare.principalType == "group",
            WorkflowShare.principalId.in_(my_group_ids),
        ))
    principal_filter = or_(*principal_predicates)

    rows_result = await db.execute(
        select(WorkflowShare, WorkflowEntity)
        .join(WorkflowEntity, WorkflowEntity.id == WorkflowShare.workflowId)
        .where(principal_filter)
        .where(WorkflowShare.permission == "write")
        .where(WorkflowEntity.isArchived.is_(False))
        .where(WorkflowEntity.versionId.isnot(None))
        .where(WorkflowEntity.createdById != current_user.id)
        .order_by(WorkflowEntity.updatedAt.desc())
    )
    pairs = list(rows_result.all())

    group_id_set = {ws.principalId for ws, _ in pairs if ws.principalType == "group"}
    group_names: dict[str, Optional[str]] = {}
    if group_id_set:
        groups = await db.execute(
            select(AdGroup).where(AdGroup.id.in_(group_id_set))
        )
        group_names = {g.id: g.displayName for g in groups.scalars().all()}

    # Dedupe by workflow id (a user could be reached via both group and user)
    seen: dict[str, SharedWorkflowItem] = {}
    for ws, wf in pairs:
        if wf.id in seen:
            # Prefer 'write' permission over 'read' if the user has both
            if ws.permission == "write" and seen[wf.id].permission == "read":
                seen[wf.id].permission = "write"
            continue
        via_name = (
            group_names.get(ws.principalId) if ws.principalType == "group" else None
        )
        seen[wf.id] = SharedWorkflowItem(
            id=wf.id,
            name=wf.name,
            description=wf.description,
            isDraft=wf.isDraft,
            createdById=wf.createdById,
            createdByName=wf.createdByName,
            updatedAt=wf.updatedAt,
            via=ws.principalType,
            viaPrincipalId=ws.principalId,
            viaPrincipalDisplayName=via_name,
            permission=ws.permission,
        )
    return list(seen.values())


@router.get(
    "/shared-with-me/knowledge-bases",
    response_model=List[SharedKBItem],
)
async def list_shared_with_me_kbs(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """KBs shared with write access (My Tools). Read-only shares are view-only."""
    my_groups_q = await db.execute(
        select(UserGroup.groupId).where(UserGroup.userId == current_user.id)
    )
    my_group_ids = [row[0] for row in my_groups_q.all()]

    principal_predicates = [
        and_(
            KnowledgeBaseShare.principalType == "user",
            KnowledgeBaseShare.principalId == current_user.id,
        )
    ]
    if my_group_ids:
        principal_predicates.append(and_(
            KnowledgeBaseShare.principalType == "group",
            KnowledgeBaseShare.principalId.in_(my_group_ids),
        ))
    principal_filter = or_(*principal_predicates)

    rows = await db.execute(
        select(KnowledgeBaseShare, KnowledgeBaseEntity)
        .join(
            KnowledgeBaseEntity,
            KnowledgeBaseEntity.id == KnowledgeBaseShare.knowledgeBaseId,
        )
        .where(principal_filter)
        .where(KnowledgeBaseShare.permission == "write")
        .where(KnowledgeBaseEntity.createdBy != current_user.id)
    )

    pairs = list(rows.all())
    group_id_set = {kbs.principalId for kbs, _ in pairs if kbs.principalType == "group"}
    group_names: dict[str, Optional[str]] = {}
    if group_id_set:
        groups = await db.execute(
            select(AdGroup).where(AdGroup.id.in_(group_id_set))
        )
        group_names = {g.id: g.displayName for g in groups.scalars().all()}

    creator_ids = {kb.createdBy for _, kb in pairs if kb.createdBy}
    creator_names: dict[str, Optional[str]] = {}
    if creator_ids:
        creators = await db.execute(
            select(User).where(User.id.in_(creator_ids))
        )
        for u in creators.scalars().all():
            parts = [u.firstName, u.lastName]
            creator_names[u.id] = " ".join(p for p in parts if p) or None

    seen: dict[str, SharedKBItem] = {}
    for kbs, kb in pairs:
        if kb.id in seen:
            if kbs.permission == "write" and seen[kb.id].permission == "read":
                seen[kb.id].permission = "write"
            continue

        if kbs.principalType == "group":
            via_display = group_names.get(kbs.principalId)
        else:
            via_display = creator_names.get(kb.createdBy)

        seen[kb.id] = SharedKBItem(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            createdBy=kb.createdBy,
            createdByName=creator_names.get(kb.createdBy),
            via=kbs.principalType,
            viaPrincipalId=kbs.principalId,
            viaPrincipalDisplayName=via_display,
            permission=kbs.permission,
        )
    return list(seen.values())


# ============================================================================
# Discovery endpoints (used by the share dialog)
# ============================================================================


@router.get(
    "/groups/me",
    response_model=List[GroupSearchResult],
)
async def list_my_groups(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Groups the calling user is a member of (read from our cached
    user_group / ad_group tables, refreshed at login).
    """
    rows = await db.execute(
        select(AdGroup)
        .join(UserGroup, UserGroup.groupId == AdGroup.id)
        .where(UserGroup.userId == current_user.id)
        .order_by(AdGroup.displayName.asc().nullslast())
    )
    return [
        GroupSearchResult(id=g.id, displayName=g.displayName, description=g.description)
        for g in rows.scalars().all()
    ]


@router.get(
    "/groups/search",
    response_model=List[GroupSearchResult],
)
async def search_ad_groups(
    q: str = Query("", min_length=0, max_length=128),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Typeahead search over Microsoft Entra ID security groups.

    Calls Microsoft Graph **as the signed-in user** (delegated
    Group.Read.All), using the user's stored refresh token to mint a
    fresh access token on demand. Falls back to the local ad_group cache
    if the user has no stored refresh token, the refresh fails, or
    Graph is down.

    Why delegated rather than app-only:
        * Application Group.Read.All requires admin consent for a very
          broad permission ("read every group in the tenant as the app").
          Many enterprises (incl. PwC) push back on granting it.
        * Delegated lets the app see groups the user could already see
          via the regular UI, which most admins are comfortable with.
        * No client_secret is involved in the Graph call — the user's
          short-lived access token is the only credential in flight.
    """
    results: dict[str, GroupSearchResult] = {}

    # 1. Try Microsoft Graph as the user (delegated Group.Read.All).
    try:
        token = await _acquire_user_graph_token(current_user.id, db)
        if token:
            async with httpx.AsyncClient(timeout=5.0) as client:
                qp: dict[str, str] = {
                    "$select": "id,displayName,description",
                    "$top": str(limit),
                }
                if q:
                    # startswith search is the most discoverable; switch
                    # to contains() if you also send ConsistencyLevel: eventual.
                    qp["$filter"] = (
                        f"securityEnabled eq true and "
                        f"startswith(displayName, '{q.replace(chr(39), chr(39)*2)}')"
                    )
                else:
                    qp["$filter"] = "securityEnabled eq true"
                resp = await client.get(
                    "https://graph.microsoft.com/v1.0/groups",
                    headers={"Authorization": f"Bearer {token}"},
                    params=qp,
                )
                if resp.status_code == 200:
                    for g in resp.json().get("value", []):
                        gid = g.get("id")
                        if gid:
                            results[gid] = GroupSearchResult(
                                id=gid,
                                displayName=g.get("displayName"),
                                description=g.get("description"),
                            )
                else:
                    logger.warning(
                        "Graph group search failed (%s): %s",
                        resp.status_code, resp.text[:300],
                    )
    except Exception as exc:
        logger.warning("Graph group search threw: %s", exc)

    # 2. Always merge in cached entries that match (so even if Graph is down
    #    the user can still see groups we've already seen).
    cache_q = select(AdGroup)
    if q:
        cache_q = cache_q.where(AdGroup.displayName.ilike(f"%{q}%"))
    cache_q = cache_q.order_by(AdGroup.displayName.asc().nullslast()).limit(limit)
    cached = await db.execute(cache_q)
    for g in cached.scalars().all():
        results.setdefault(g.id, GroupSearchResult(
            id=g.id, displayName=g.displayName, description=g.description,
        ))

    return list(results.values())[:limit]


@router.get(
    "/users/search",
    response_model=List[UserSearchResult],
)
async def search_users(
    q: str = Query(..., min_length=2, max_length=128),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user),
):
    """
    Search local users by email / first / last name. We deliberately do NOT
    proxy this to Microsoft Graph because users that have never logged in
    won't have a local user.id we can store in workflow_share.principalId.
    """
    pattern = f"%{q}%"
    rows = await db.execute(
        select(User)
        .where(or_(
            User.email.ilike(pattern),
            User.firstName.ilike(pattern),
            User.lastName.ilike(pattern),
        ))
        .where(User.disabled.is_(False))
        .where(User.id != current_user.id)
        .order_by(User.email.asc())
        .limit(limit)
    )
    out: List[UserSearchResult] = []
    for u in rows.scalars().all():
        display = " ".join(p for p in [u.firstName, u.lastName] if p) or u.email
        out.append(UserSearchResult(
            id=u.id, email=u.email, displayName=display,
        ))
    return out


# ============================================================================
# Per-user delegated Graph access tokens
# ============================================================================
# Strategy:
#   * On Microsoft SSO callback we persist each user's *refresh token*,
#     encrypted at rest (see services/auth_service.upsert_ms_refresh_token).
#   * When that user hits /groups/search we exchange the refresh token for
#     a short-lived (~1h) access token and call Graph as them.
#   * We cache the resulting access token in-process keyed by user id so
#     we don't burn a Microsoft round-trip on every keystroke.
#
# Why this lives here and not in auth_service:
#   The cache is tightly coupled to the search endpoint's hot path and we
#   want it to disappear on process restart (one less place where a token
#   could leak). auth_service only deals with the persistent refresh
#   token in encrypted form.

import time as _time

# user_id -> {"access_token": str, "expires_at": float (unix seconds)}
_user_graph_token_cache: dict[str, dict] = {}
_USER_TOKEN_REFRESH_MARGIN_S = 60  # refresh 1 min before expiry


async def _acquire_user_graph_token(
    user_id: str,
    db: AsyncSession,
) -> Optional[str]:
    """
    Return a fresh delegated Microsoft Graph access token for ``user_id``.

    Returns None if:
        * Microsoft SSO isn't configured on this server.
        * The user has never logged in via Microsoft (no stored refresh
          token), or their stored token has been wiped.
        * The refresh exchange fails (token revoked, scope changed, the
          user's password reset, conditional-access requires re-auth, etc.)

    Callers MUST treat None as "fall back to cached groups, don't error".
    """
    if not (settings.MICROSOFT_TENANT_ID and settings.MICROSOFT_CLIENT_ID
            and settings.MICROSOFT_CLIENT_SECRET):
        return None

    now = _time.time()
    cached = _user_graph_token_cache.get(user_id)
    if cached and now < cached["expires_at"] - _USER_TOKEN_REFRESH_MARGIN_S:
        return cached["access_token"]

    # Read the stored refresh token. We do NOT use auth_service here because
    # that would require importing the whole DI graph; a direct query is
    # simpler and the encryption helper handles the unwrap.
    from db.models import MicrosoftOAuthToken
    from utils.token_crypto import get_token_crypto

    row_result = await db.execute(
        select(MicrosoftOAuthToken).where(MicrosoftOAuthToken.userId == user_id)
    )
    row = row_result.scalar_one_or_none()
    if row is None:
        return None

    try:
        crypto = get_token_crypto()
    except RuntimeError as e:
        logger.warning("MS_TOKEN_ENCRYPTION_KEY missing: %s", e)
        return None

    refresh_token = crypto.decrypt(row.refreshTokenEncrypted)
    if not refresh_token:
        return None

    # Exchange refresh token for a fresh access token.
    # We use the OAuth token endpoint directly (not MSAL) because we already
    # have an httpx client pattern here and avoid reimporting MSAL state.
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/"
                f"{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token",
                data={
                    "client_id": settings.MICROSOFT_CLIENT_ID,
                    "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    # Same scopes the original consent covered. We pass them
                    # explicitly because the token endpoint uses them to
                    # decide whether to issue a new refresh token.
                    "scope": "User.Read GroupMember.Read.All Group.Read.All",
                },
            )
    except Exception as exc:
        logger.warning("MS refresh-token exchange threw for user %s: %s", user_id, exc)
        return None

    if resp.status_code != 200:
        # Most common cause: user revoked consent, password changed,
        # conditional access tightened, or the refresh token expired
        # (default 90 days). Drop the dead row so we don't keep retrying.
        logger.warning(
            "MS refresh-token exchange failed for user %s (%s): %s",
            user_id, resp.status_code, resp.text[:300],
        )
        try:
            from db.models import MicrosoftOAuthToken as _Tok
            await db.execute(
                _Tok.__table__.delete().where(_Tok.userId == user_id)
            )
            await db.commit()
        except Exception:
            await db.rollback()
        _user_graph_token_cache.pop(user_id, None)
        return None

    body = resp.json()
    new_access = body.get("access_token")
    new_refresh = body.get("refresh_token")  # MS may rotate
    expires_in = int(body.get("expires_in", 3600))
    if not new_access:
        return None

    _user_graph_token_cache[user_id] = {
        "access_token": new_access,
        "expires_at": now + expires_in,
    }

    # Persist the rotated refresh token if Microsoft handed us a new one.
    # (For confidential clients this often happens.) RLS on ms_oauth_token
    # is owner-only, so we set the user context first.
    if new_refresh and new_refresh != refresh_token:
        try:
            from db.pgsql import set_user_context
            await set_user_context(db, user_id)
            row.refreshTokenEncrypted = crypto.encrypt(new_refresh)
            row.updatedAt = datetime.utcnow()
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to persist rotated refresh token for user %s: %s",
                user_id, exc,
            )
            await db.rollback()

    return new_access
