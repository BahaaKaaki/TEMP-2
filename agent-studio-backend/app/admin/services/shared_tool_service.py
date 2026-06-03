"""
Service for shared external tools: CRUD, CSV import, audit logging.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdGroup,
    SharedTool,
    SharedToolAuditLog,
    SharedToolPermission,
    User,
)

logger = logging.getLogger(__name__)


class SharedToolService:
    """Manages shared external tools lifecycle."""

    # ──────────────────────────────────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    async def list_all(db: AsyncSession) -> List[Dict[str, Any]]:
        """List all shared tools with permissions (admin view)."""
        result = await db.execute(
            select(SharedTool).order_by(SharedTool.tool_name)
        )
        tools = list(result.scalars().all())

        tool_ids = [t.id for t in tools]
        perms_result = await db.execute(
            select(SharedToolPermission).where(
                SharedToolPermission.shared_tool_id.in_(tool_ids)
            )
        )
        perms = list(perms_result.scalars().all())

        perms_by_tool: Dict[str, List[Dict]] = {}
        for p in perms:
            perms_by_tool.setdefault(p.shared_tool_id, []).append({
                "id": p.id,
                "principal_type": p.principal_type,
                "principal_id": p.principal_id,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })

        # Resolve AD group display names
        group_ids = {p.principal_id for p in perms if p.principal_type == "group"}
        group_names: Dict[str, str] = {}
        if group_ids:
            groups_result = await db.execute(
                select(AdGroup).where(AdGroup.id.in_(group_ids))
            )
            for g in groups_result.scalars().all():
                group_names[g.id] = g.displayName or g.id

        # Resolve user emails
        user_ids = {p.principal_id for p in perms if p.principal_type == "user"}
        user_emails: Dict[str, str] = {}
        if user_ids:
            users_result = await db.execute(
                select(User).where(User.id.in_(user_ids))
            )
            for u in users_result.scalars().all():
                user_emails[u.id] = u.email or u.id

        items = []
        for t in tools:
            tool_perms = perms_by_tool.get(t.id, [])
            for p in tool_perms:
                if p["principal_type"] == "group":
                    p["display_name"] = group_names.get(p["principal_id"], p["principal_id"])
                else:
                    p["display_name"] = user_emails.get(p["principal_id"], p["principal_id"])

            items.append({
                "id": t.id,
                "tool_name": t.tool_name,
                "description": t.description,
                "url": t.url,
                "is_public": t.is_public,
                "status": t.status,
                "created_by": t.created_by,
                "approved_by": t.approved_by,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                "permissions": tool_perms,
            })
        return items

    @staticmethod
    async def list_visible(db: AsyncSession) -> List[Dict[str, Any]]:
        """List tools visible to current user (RLS handles filtering)."""
        result = await db.execute(
            select(SharedTool)
            .where(SharedTool.status == "approved")
            .order_by(SharedTool.tool_name)
        )
        tools = list(result.scalars().all())
        return [
            {
                "id": t.id,
                "tool_name": t.tool_name,
                "description": t.description,
                "url": t.url,
                "is_public": t.is_public,
            }
            for t in tools
        ]

    @staticmethod
    async def create_tool(
        db: AsyncSession,
        *,
        tool_name: str,
        description: Optional[str],
        url: str,
        is_public: bool,
        ad_group_names: List[str],
        emails: List[str],
        created_by: str,
        auto_approve: bool = True,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Create a shared tool with permissions.
        Returns (tool_dict, None) on success or (None, error_message) on failure.
        """
        # Check duplicate
        existing = await db.execute(
            select(SharedTool).where(
                and_(SharedTool.tool_name == tool_name, SharedTool.url == url)
            )
        )
        if existing.scalar_one_or_none():
            return None, f"Tool with name '{tool_name}' and URL '{url}' already exists"

        tool_id = str(uuid.uuid4())
        status = "approved" if auto_approve else "pending"

        tool = SharedTool(
            id=tool_id,
            tool_name=tool_name,
            description=description,
            url=url,
            is_public=is_public,
            status=status,
            created_by=created_by,
            approved_by=created_by if auto_approve else None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(tool)

        # Resolve and create permissions (skip if public)
        if not is_public:
            await SharedToolService._create_permissions(
                db, tool_id, ad_group_names, emails
            )

        # Audit
        await SharedToolService._audit(
            db, tool_id, "created", created_by,
            {"tool_name": tool_name, "url": url, "is_public": is_public,
             "auto_approve": auto_approve}
        )

        await db.flush()
        return {
            "id": tool_id,
            "tool_name": tool_name,
            "description": description,
            "url": url,
            "is_public": is_public,
            "status": status,
        }, None

    @staticmethod
    async def update_tool(
        db: AsyncSession,
        tool_id: str,
        *,
        tool_name: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        is_public: Optional[bool] = None,
        ad_group_names: Optional[List[str]] = None,
        emails: Optional[List[str]] = None,
        admin_user_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Update a shared tool. Returns (tool_dict, None) or (None, error)."""
        result = await db.execute(
            select(SharedTool).where(SharedTool.id == tool_id)
        )
        tool = result.scalar_one_or_none()
        if not tool:
            return None, "Tool not found"

        changes = {}
        if tool_name is not None and tool_name != tool.tool_name:
            changes["tool_name"] = {"from": tool.tool_name, "to": tool_name}
            tool.tool_name = tool_name
        if description is not None and description != tool.description:
            changes["description"] = {"from": tool.description, "to": description}
            tool.description = description
        if url is not None and url != tool.url:
            changes["url"] = {"from": tool.url, "to": url}
            tool.url = url
        if is_public is not None and is_public != tool.is_public:
            changes["is_public"] = {"from": tool.is_public, "to": is_public}
            tool.is_public = is_public

        tool.updated_at = datetime.utcnow()

        # Replace permissions if provided
        if ad_group_names is not None or emails is not None:
            # Delete existing permissions
            existing_perms = await db.execute(
                select(SharedToolPermission).where(
                    SharedToolPermission.shared_tool_id == tool_id
                )
            )
            for p in existing_perms.scalars().all():
                await db.delete(p)

            await SharedToolService._create_permissions(
                db, tool_id,
                ad_group_names or [],
                emails or [],
            )
            changes["permissions_updated"] = True

        if changes:
            await SharedToolService._audit(
                db, tool_id, "updated", admin_user_id, changes
            )

        await db.flush()
        return {
            "id": tool.id,
            "tool_name": tool.tool_name,
            "description": tool.description,
            "url": tool.url,
            "is_public": tool.is_public,
            "status": tool.status,
        }, None

    @staticmethod
    async def delete_tool(
        db: AsyncSession, tool_id: str, admin_user_id: str
    ) -> Optional[str]:
        """Delete a shared tool. Returns None on success or error message."""
        result = await db.execute(
            select(SharedTool).where(SharedTool.id == tool_id)
        )
        tool = result.scalar_one_or_none()
        if not tool:
            return "Tool not found"

        await SharedToolService._audit(
            db, tool_id, "deleted", admin_user_id,
            {"tool_name": tool.tool_name, "url": tool.url}
        )

        await db.delete(tool)
        await db.flush()
        return None

    # ──────────────────────────────────────────────────────────────────────
    # CSV Import
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    async def parse_and_import_csv(
        db: AsyncSession, file_content: str, admin_user_id: str, filename: str = "upload.csv"
    ) -> Dict[str, Any]:
        """
        Parse CSV and create shared tools.
        Expected header: tool_name,description,url,is_public,ad_group_csv,email_csv
        Returns summary of created/skipped items.
        """
        reader = csv.DictReader(io.StringIO(file_content))

        required_fields = {"tool_name", "description", "url", "is_public"}
        if not reader.fieldnames:
            return {"error": "Empty CSV file", "created": 0, "skipped": 0}

        normalized_fields = {f.strip().lower() for f in reader.fieldnames}
        missing = required_fields - normalized_fields
        if missing:
            return {"error": f"Missing required columns: {', '.join(missing)}", "created": 0, "skipped": 0}

        created = 0
        skipped = 0
        skipped_details: List[Dict[str, str]] = []
        errors: List[Dict[str, str]] = []

        for row_num, row in enumerate(reader, start=2):
            # Normalize keys
            row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items()}

            tool_name = row.get("tool_name", "").strip()
            description = row.get("description", "").strip() or None
            url = row.get("url", "").strip()
            is_public_str = row.get("is_public", "false").strip().lower()
            ad_group_csv = row.get("ad_group_csv", "").strip()
            email_csv = row.get("email_csv", "").strip()

            if not tool_name or not url:
                errors.append({"row": str(row_num), "reason": "Missing tool_name or url"})
                continue

            is_public = is_public_str in ("true", "1", "yes")

            # Parse comma-separated values within cells
            ad_group_names = [g.strip() for g in ad_group_csv.split(",") if g.strip()] if ad_group_csv else []
            emails = [e.strip() for e in email_csv.split(",") if e.strip()] if email_csv else []

            # Check duplicate
            existing = await db.execute(
                select(SharedTool).where(
                    and_(SharedTool.tool_name == tool_name, SharedTool.url == url)
                )
            )
            if existing.scalar_one_or_none():
                skipped += 1
                skipped_details.append({"tool_name": tool_name, "url": url, "reason": "Already exists"})
                continue

            # Create tool
            tool_id = str(uuid.uuid4())
            tool = SharedTool(
                id=tool_id,
                tool_name=tool_name,
                description=description,
                url=url,
                is_public=is_public,
                status="approved",
                created_by=admin_user_id,
                approved_by=admin_user_id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(tool)

            if not is_public:
                await SharedToolService._create_permissions(
                    db, tool_id, ad_group_names, emails
                )

            created += 1

        # Audit the CSV upload
        await SharedToolService._audit(
            db, None, "csv_uploaded", admin_user_id,
            {"filename": filename, "created": created, "skipped": skipped,
             "skipped_details": skipped_details, "errors": errors}
        )

        await db.flush()
        return {
            "created": created,
            "skipped": skipped,
            "skipped_details": skipped_details,
            "errors": errors,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Audit Log
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_audit_log(
        db: AsyncSession, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Fetch audit log entries (admin only, RLS enforces)."""
        result = await db.execute(
            select(SharedToolAuditLog)
            .order_by(SharedToolAuditLog.performed_at.desc())
            .offset(offset)
            .limit(limit)
        )
        entries = list(result.scalars().all())

        # Resolve performer names
        performer_ids = {e.performed_by for e in entries}
        performers: Dict[str, str] = {}
        if performer_ids:
            users_result = await db.execute(
                select(User).where(User.id.in_(performer_ids))
            )
            for u in users_result.scalars().all():
                performers[u.id] = u.email or f"{u.firstName} {u.lastName}".strip() or u.id

        return [
            {
                "id": e.id,
                "shared_tool_id": e.shared_tool_id,
                "action": e.action,
                "performed_by": e.performed_by,
                "performer_display": performers.get(e.performed_by, e.performed_by),
                "performed_at": e.performed_at.isoformat() if e.performed_at else None,
                "details": (
                    e.details
                    if isinstance(e.details, dict)
                    else (json.loads(e.details) if e.details else None)
                ),
            }
            for e in entries
        ]

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    async def _create_permissions(
        db: AsyncSession,
        tool_id: str,
        ad_group_names: List[str],
        emails: List[str],
    ) -> None:
        """Resolve AD group names and emails, then create permission rows."""
        # Resolve AD group names to IDs
        for name in ad_group_names:
            if not name:
                continue
            result = await db.execute(
                select(AdGroup).where(
                    func.lower(AdGroup.displayName) == func.lower(name)
                )
            )
            group = result.scalar_one_or_none()
            if group:
                perm = SharedToolPermission(
                    id=str(uuid.uuid4()),
                    shared_tool_id=tool_id,
                    principal_type="group",
                    principal_id=group.id,
                    created_at=datetime.utcnow(),
                )
                db.add(perm)
            else:
                logger.warning("AD group '%s' not found in local cache — skipping", name)

        # Resolve emails to user IDs
        for email in emails:
            if not email:
                continue
            result = await db.execute(
                select(User).where(func.lower(User.email) == func.lower(email))
            )
            user = result.scalar_one_or_none()
            if user:
                perm = SharedToolPermission(
                    id=str(uuid.uuid4()),
                    shared_tool_id=tool_id,
                    principal_type="user",
                    principal_id=user.id,
                    created_at=datetime.utcnow(),
                )
                db.add(perm)
            else:
                logger.warning("User with email '%s' not found — skipping", email)

    @staticmethod
    async def _audit(
        db: AsyncSession,
        tool_id: Optional[str],
        action: str,
        performed_by: str,
        details: Any = None,
    ) -> None:
        """Write an audit log entry."""
        entry = SharedToolAuditLog(
            id=str(uuid.uuid4()),
            shared_tool_id=tool_id,
            action=action,
            performed_by=performed_by,
            performed_at=datetime.utcnow(),
            details=details if details else None,
        )
        db.add(entry)
