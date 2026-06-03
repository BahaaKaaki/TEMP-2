"""
Admin API: overview of shared workflows and knowledge bases.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.sharing_overview_service import SharingOverviewService
from app.core.dependencies import get_current_admin_user
from app.db.models import User
from app.db.pgsql import get_admin_db

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)],
)


@router.get("/sharing/overview")
async def sharing_overview(
    db: AsyncSession = Depends(get_admin_db),
    _admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """List workflows and KBs shared on marketplace, with users, or AD groups."""
    return await SharingOverviewService.get_overview(db)
