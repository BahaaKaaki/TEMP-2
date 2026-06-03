"""
Workflow gated distribution: admin approval for AD-group shares, 16+ user shares,
and version republishes.

Kept at app root (not under services/) to avoid circular imports with repositories.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MarketplaceSubmission, WorkflowShare

USER_SHARE_APPROVAL_THRESHOLD = 16

SUBMISSION_TYPE_SHARE_GRANT = "workflow_share_grant"
SUBMISSION_TYPE_SHARE_VERSION = "workflow_share_version"


async def count_group_shares(db: AsyncSession, workflow_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(WorkflowShare)
        .where(
            WorkflowShare.workflowId == workflow_id,
            WorkflowShare.principalType == "group",
        )
    )
    return int(result.scalar() or 0)


async def count_user_shares(db: AsyncSession, workflow_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(WorkflowShare)
        .where(
            WorkflowShare.workflowId == workflow_id,
            WorkflowShare.principalType == "user",
        )
    )
    return int(result.scalar() or 0)


async def is_distribution_gated(db: AsyncSession, workflow_id: str) -> bool:
    """True if workflow has any AD group share or >= 16 distinct user shares."""
    group_count = await count_group_shares(db, workflow_id)
    if group_count > 0:
        return True
    user_count = await count_user_shares(db, workflow_id)
    return user_count >= USER_SHARE_APPROVAL_THRESHOLD


async def grant_requires_approval(
    db: AsyncSession,
    workflow_id: str,
    *,
    principal_type: str,
    principal_id: str,
    is_new_grant: bool,
) -> bool:
    """Whether creating/updating this grant needs admin approval."""
    if not is_new_grant:
        return False
    if principal_type == "group":
        return True
    if principal_type == "user":
        existing = await db.execute(
            select(WorkflowShare.id).where(
                WorkflowShare.workflowId == workflow_id,
                WorkflowShare.principalType == "user",
                WorkflowShare.principalId == principal_id,
            )
        )
        if existing.scalar_one_or_none():
            return False
        user_count = await count_user_shares(db, workflow_id)
        return (user_count + 1) >= USER_SHARE_APPROVAL_THRESHOLD
    return False


async def get_pending_submission(
    db: AsyncSession, workflow_id: str
) -> Optional[MarketplaceSubmission]:
    result = await db.execute(
        select(MarketplaceSubmission).where(
            MarketplaceSubmission.workflowId == workflow_id,
            MarketplaceSubmission.status == "pending",
        )
    )
    return result.scalar_one_or_none()


def build_grant_meta(
    *,
    principal_type: str,
    principal_id: str,
    permission: str,
    display_name: Optional[str] = None,
) -> dict:
    return {
        "action": "grant",
        "principalType": principal_type,
        "principalId": principal_id,
        "permission": permission,
        "displayName": display_name,
    }


async def apply_share_grants_from_meta(
    db: AsyncSession,
    workflow_id: str,
    meta: dict,
    granted_by_id: str,
) -> List[WorkflowShare]:
    """Insert workflow_share row(s) from approved submission meta."""
    from datetime import datetime
    import uuid

    principals = meta.get("principals")
    if not principals:
        principals = [
            {
                "principalType": meta.get("principalType"),
                "principalId": meta.get("principalId"),
                "permission": meta.get("permission", "read"),
                "displayName": meta.get("displayName"),
            }
        ]

    created: List[WorkflowShare] = []
    now = datetime.utcnow()
    for p in principals:
        ptype = p.get("principalType")
        pid = p.get("principalId")
        if not ptype or not pid:
            continue
        existing = await db.execute(
            select(WorkflowShare).where(
                WorkflowShare.workflowId == workflow_id,
                WorkflowShare.principalType == ptype,
                WorkflowShare.principalId == pid,
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            row.permission = p.get("permission", "read")
            created.append(row)
            continue
        share = WorkflowShare(
            id=str(uuid.uuid4()),
            workflowId=workflow_id,
            principalType=ptype,
            principalId=pid,
            permission=p.get("permission", "read"),
            grantedById=granted_by_id,
            grantedAt=now,
        )
        db.add(share)
        created.append(share)
    return created
