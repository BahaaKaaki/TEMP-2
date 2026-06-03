"""
Resolve effective share access for workflows and knowledge bases.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import KnowledgeBaseShare, WorkflowShare

ShareAccess = Literal["owner", "read", "write"]


async def load_user_group_ids(db: AsyncSession, user_id: str) -> List[str]:
    from db.models import UserGroup

    result = await db.execute(
        select(UserGroup.groupId).where(UserGroup.userId == user_id)
    )
    return [row[0] for row in result.all()]


def _principal_filter(user_id: str, group_ids: List[str]):
    predicates = [
        and_(
            WorkflowShare.principalType == "user",
            WorkflowShare.principalId == user_id,
        )
    ]
    if group_ids:
        predicates.append(
            and_(
                WorkflowShare.principalType == "group",
                WorkflowShare.principalId.in_(group_ids),
            )
        )
    return or_(*predicates)


async def resolve_workflow_share_access(
    db: AsyncSession,
    workflow_id: str,
    user_id: str,
    *,
    owner_id: str,
    group_ids: Optional[List[str]] = None,
) -> Optional[ShareAccess]:
    if str(owner_id) == str(user_id):
        return "owner"

    if group_ids is None:
        group_ids = await load_user_group_ids(db, user_id)

    result = await db.execute(
        select(WorkflowShare.permission).where(
            WorkflowShare.workflowId == workflow_id,
            _principal_filter(user_id, group_ids),
        )
    )
    perms = [row[0] for row in result.all()]
    if not perms:
        return None
    return "write" if "write" in perms else "read"


async def resolve_kb_share_access(
    db: AsyncSession,
    kb_id: str,
    user_id: str,
    *,
    owner_id: str,
    group_ids: Optional[List[str]] = None,
) -> Optional[ShareAccess]:
    if str(owner_id) == str(user_id):
        return "owner"

    if group_ids is None:
        group_ids = await load_user_group_ids(db, user_id)

    predicates = [
        and_(
            KnowledgeBaseShare.principalType == "user",
            KnowledgeBaseShare.principalId == user_id,
        )
    ]
    if group_ids:
        predicates.append(
            and_(
                KnowledgeBaseShare.principalType == "group",
                KnowledgeBaseShare.principalId.in_(group_ids),
            )
        )

    result = await db.execute(
        select(KnowledgeBaseShare.permission).where(
            KnowledgeBaseShare.knowledgeBaseId == kb_id,
            or_(*predicates),
        )
    )
    perms = [row[0] for row in result.all()]
    if not perms:
        return None
    return "write" if "write" in perms else "read"


def can_write(access: Optional[ShareAccess]) -> bool:
    return access in ("owner", "write")


def kb_shows_in_my_tools(access: Optional[ShareAccess]) -> bool:
    """True for KBs the user may manage in My Tools (not consume-only)."""
    return access in ("owner", "write")


async def resolve_kb_effective_access(
    db: AsyncSession,
    kb_id: str,
    user_id: str,
    *,
    owner_id: str,
    is_public: bool = False,
    group_ids: Optional[List[str]] = None,
) -> Optional[ShareAccess]:
    """Owner / share grant, or read for marketplace-public KBs."""
    access = await resolve_kb_share_access(
        db, kb_id, user_id, owner_id=owner_id, group_ids=group_ids
    )
    if access is not None:
        return access
    if is_public and str(owner_id) != str(user_id):
        return "read"
    return None


def can_view_on_storefront(
    access: Optional[ShareAccess], *, is_public: bool
) -> bool:
    if is_public:
        return True
    return access in ("read", "write")
