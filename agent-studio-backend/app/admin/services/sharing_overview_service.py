"""
Admin overview of workflows and knowledge bases shared via marketplace,
AD groups, or individual users.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdGroup,
    KnowledgeBaseEntity,
    KnowledgeBaseShare,
    User,
    WorkflowEntity,
    WorkflowHistory,
    WorkflowShare,
)


def _user_display(user: Optional[User]) -> Optional[str]:
    if not user:
        return None
    name = " ".join(part for part in [user.firstName, user.lastName] if part)
    return name or user.email


class SharingOverviewService:
    @staticmethod
    async def get_overview(db: AsyncSession) -> Dict[str, Any]:
        workflows = await SharingOverviewService._load_workflows(db)
        knowledge_bases = await SharingOverviewService._load_knowledge_bases(db)
        return {
            "workflows": workflows,
            "knowledge_bases": knowledge_bases,
            "summary": {
                "workflow_count": len(workflows),
                "knowledge_base_count": len(knowledge_bases),
            },
        }

    @staticmethod
    async def _load_workflows(db: AsyncSession) -> List[Dict[str, Any]]:
        shared_ids = select(WorkflowShare.workflowId).distinct()
        result = await db.execute(
            select(WorkflowEntity).where(
                WorkflowEntity.isArchived.is_(False),
                or_(
                    WorkflowEntity.isPublic.is_(True),
                    WorkflowEntity.id.in_(shared_ids),
                ),
            ).order_by(WorkflowEntity.name)
        )
        workflows = list(result.scalars().all())
        if not workflows:
            return []

        wf_ids = [w.id for w in workflows]
        shares_by_wf = await SharingOverviewService._workflow_shares(db, wf_ids)
        version_map = await SharingOverviewService._version_numbers(
            db,
            {
                vid
                for w in workflows
                for vid in (w.versionId, w.approvedVersionId)
                if vid
            },
        )
        owners = await SharingOverviewService._users_by_id(
            db, {w.createdById for w in workflows}
        )

        rows: List[Dict[str, Any]] = []
        for wf in workflows:
            shares = shares_by_wf.get(wf.id, [])
            channels = SharingOverviewService._share_channels(
                is_public=wf.isPublic,
                shares=shares,
            )
            owner = owners.get(wf.createdById)
            rows.append(
                {
                    "id": wf.id,
                    "name": wf.name,
                    "marketplace_name": wf.marketplaceName,
                    "owner_id": wf.createdById,
                    "owner_name": wf.createdByName or _user_display(owner),
                    "owner_email": owner.email if owner else None,
                    "is_marketplace": wf.isPublic,
                    "share_channels": channels,
                    "current_version_id": wf.versionId,
                    "current_version_number": version_map.get(wf.versionId),
                    "approved_version_id": wf.approvedVersionId,
                    "approved_version_number": version_map.get(wf.approvedVersionId),
                    "is_draft": wf.isDraft,
                    "updated_at": wf.updatedAt.isoformat() if wf.updatedAt else None,
                    "shares": shares,
                }
            )
        return rows

    @staticmethod
    async def _load_knowledge_bases(db: AsyncSession) -> List[Dict[str, Any]]:
        shared_ids = select(KnowledgeBaseShare.knowledgeBaseId).distinct()
        result = await db.execute(
            select(KnowledgeBaseEntity).where(
                KnowledgeBaseEntity.deletedAt.is_(None),
                or_(
                    KnowledgeBaseEntity.isPublic.is_(True),
                    KnowledgeBaseEntity.id.in_(shared_ids),
                ),
            ).order_by(KnowledgeBaseEntity.name)
        )
        kbs = list(result.scalars().all())
        if not kbs:
            return []

        kb_ids = [kb.id for kb in kbs]
        shares_by_kb = await SharingOverviewService._kb_shares(db, kb_ids)
        owners = await SharingOverviewService._users_by_id(
            db, {kb.createdBy for kb in kbs}
        )

        rows: List[Dict[str, Any]] = []
        for kb in kbs:
            shares = shares_by_kb.get(kb.id, [])
            channels = SharingOverviewService._share_channels(
                is_public=kb.isPublic,
                shares=shares,
            )
            owner = owners.get(kb.createdBy)
            rows.append(
                {
                    "id": kb.id,
                    "name": kb.name,
                    "marketplace_name": kb.marketplaceName,
                    "owner_id": kb.createdBy,
                    "owner_name": _user_display(owner),
                    "owner_email": owner.email if owner else None,
                    "is_marketplace": kb.isPublic,
                    "share_channels": channels,
                    "status": kb.status,
                    "document_count": kb.documentCount,
                    "updated_at": kb.updatedAt.isoformat() if kb.updatedAt else None,
                    "shares": shares,
                }
            )
        return rows

    @staticmethod
    async def _workflow_shares(
        db: AsyncSession, workflow_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        result = await db.execute(
            select(WorkflowShare).where(WorkflowShare.workflowId.in_(workflow_ids))
        )
        shares = list(result.scalars().all())
        return await SharingOverviewService._group_hydrated_shares(db, shares, "workflowId")

    @staticmethod
    async def _kb_shares(
        db: AsyncSession, kb_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        result = await db.execute(
            select(KnowledgeBaseShare).where(
                KnowledgeBaseShare.knowledgeBaseId.in_(kb_ids)
            )
        )
        shares = list(result.scalars().all())
        return await SharingOverviewService._group_hydrated_shares(
            db, shares, "knowledgeBaseId"
        )

    @staticmethod
    async def _group_hydrated_shares(
        db: AsyncSession, shares: list, resource_key: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not shares:
            return {}

        user_ids = {s.principalId for s in shares if s.principalType == "user"}
        group_ids = {s.principalId for s in shares if s.principalType == "group"}

        users_by_id = await SharingOverviewService._users_by_id(db, user_ids)
        groups_by_id: Dict[str, AdGroup] = {}
        if group_ids:
            groups = await db.execute(select(AdGroup).where(AdGroup.id.in_(group_ids)))
            groups_by_id = {g.id: g for g in groups.scalars().all()}

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for share in shares:
            resource_id = getattr(share, resource_key)
            display: Optional[str] = None
            email: Optional[str] = None
            if share.principalType == "user":
                user = users_by_id.get(share.principalId)
                if user:
                    display = _user_display(user)
                    email = user.email
            else:
                group = groups_by_id.get(share.principalId)
                if group:
                    display = group.displayName

            grouped.setdefault(resource_id, []).append(
                {
                    "id": share.id,
                    "principal_type": share.principalType,
                    "principal_id": share.principalId,
                    "principal_display_name": display,
                    "principal_email": email,
                    "permission": share.permission,
                    "granted_at": share.grantedAt.isoformat() if share.grantedAt else None,
                }
            )
        return grouped

    @staticmethod
    async def _users_by_id(
        db: AsyncSession, user_ids: Set[str]
    ) -> Dict[str, User]:
        if not user_ids:
            return {}
        result = await db.execute(select(User).where(User.id.in_(user_ids)))
        return {u.id: u for u in result.scalars().all()}

    @staticmethod
    async def _version_numbers(
        db: AsyncSession, version_ids: Set[str]
    ) -> Dict[str, int]:
        if not version_ids:
            return {}
        result = await db.execute(
            select(WorkflowHistory.versionId, WorkflowHistory.versionNumber).where(
                WorkflowHistory.versionId.in_(version_ids)
            )
        )
        return {row.versionId: row.versionNumber for row in result.all()}

    @staticmethod
    def _share_channels(
        *, is_public: bool, shares: List[Dict[str, Any]]
    ) -> List[str]:
        channels: List[str] = []
        if is_public:
            channels.append("marketplace")
        principal_types = {s["principal_type"] for s in shares}
        if "group" in principal_types:
            channels.append("ad_group")
        if "user" in principal_types:
            channels.append("user")
        return channels
