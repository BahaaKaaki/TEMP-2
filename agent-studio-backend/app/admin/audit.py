"""Shared admin audit logging."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminAuditLog, User


async def write_admin_audit(
    db: AsyncSession,
    admin: User,
    action: str,
    entity_type: str,
    entity_id: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(
        AdminAuditLog(
            id=str(uuid.uuid4()),
            adminUserId=admin.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=json.dumps(details) if details else None,
            createdAt=datetime.utcnow(),
        )
    )
