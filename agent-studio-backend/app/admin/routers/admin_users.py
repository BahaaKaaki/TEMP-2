"""
Admin API: list app admins and grant or revoke admin role.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.audit import write_admin_audit
from app.core.dependencies import get_current_admin_user, is_admin
from app.db.models import User
from app.db.pgsql import get_admin_db

ADMIN_ROLE_SLUG = "global:admin"
MEMBER_ROLE_SLUG = "global:member"

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)],
)


class GrantAdminRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: Optional[str] = Field(None, min_length=3, max_length=255)
    user_id: Optional[str] = Field(None, alias="userId", min_length=1, max_length=36)

    @model_validator(mode="after")
    def require_email_or_user_id(self) -> "GrantAdminRequest":
        if not self.email and not self.user_id:
            raise ValueError("email or userId is required")
        return self


def _admin_user_payload(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "firstName": user.firstName,
        "lastName": user.lastName,
        "roleSlug": user.roleSlug,
        "disabled": user.disabled,
        "lastActiveAt": user.lastActiveAt.isoformat() if user.lastActiveAt else None,
        "createdAt": user.createdAt.isoformat() if user.createdAt else None,
    }


@router.get("/users/search")
async def search_users(
    q: str = Query(..., min_length=2, max_length=128),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_admin_db),
) -> List[Dict[str, Any]]:
    """Search local users by email or name (signed-in users only)."""
    pattern = f"%{q}%"
    full_name = func.trim(
        func.concat(
            func.coalesce(User.firstName, ""),
            " ",
            func.coalesce(User.lastName, ""),
        )
    )
    rows = (
        await db.execute(
            select(User)
            .where(User.disabled.is_(False))
            .where(
                or_(
                    User.email.ilike(pattern),
                    User.firstName.ilike(pattern),
                    User.lastName.ilike(pattern),
                    full_name.ilike(pattern),
                )
            )
            .order_by(User.email.asc())
            .limit(limit)
        )
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for u in rows:
        display = " ".join(p for p in [u.firstName, u.lastName] if p) or u.email
        out.append({
            "id": u.id,
            "email": u.email,
            "displayName": display,
            "isAdmin": is_admin(u),
        })
    return out


@router.get("/users/admins")
async def list_admins(
    db: AsyncSession = Depends(get_admin_db),
) -> List[Dict[str, Any]]:
    """List all users with app admin role."""
    rows = (
        await db.execute(
            select(User)
            .where(User.roleSlug.ilike("%admin%"))
            .order_by(User.email)
        )
    ).scalars().all()
    return [_admin_user_payload(u) for u in rows]


@router.post("/users/admins")
async def grant_admin(
    body: GrantAdminRequest,
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Grant app admin role to an existing user (must have signed in at least once)."""
    if body.user_id:
        user = await db.get(User, body.user_id)
    else:
        email = (body.email or "").strip().lower()
        if not email:
            raise HTTPException(400, "Email is required")
        user = (
            await db.execute(select(User).where(func.lower(User.email) == email))
        ).scalar_one_or_none()
    if not user:
        raise HTTPException(
            404,
            "User not found. They must sign in at least once before being granted admin.",
        )
    if user.disabled:
        raise HTTPException(400, "Cannot grant admin to a disabled account")
    if is_admin(user):
        return {"status": "already_admin", "user": _admin_user_payload(user)}

    user.roleSlug = ADMIN_ROLE_SLUG
    user.updatedAt = datetime.utcnow()
    await write_admin_audit(db, admin, "grant_admin", "user", user.id, {"email": user.email})
    await db.commit()
    return {"status": "granted", "user": _admin_user_payload(user)}


@router.delete("/users/admins/{user_id}")
async def revoke_admin(
    user_id: str,
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Remove app admin role from a user (reverts to member)."""
    if user_id == admin.id:
        raise HTTPException(400, "Cannot remove your own admin access")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if not is_admin(user):
        raise HTTPException(400, "User is not an admin")

    admin_count = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.roleSlug.ilike("%admin%"))
        )
    ).scalar_one()
    if admin_count <= 1:
        raise HTTPException(400, "Cannot remove the last app admin")

    user.roleSlug = MEMBER_ROLE_SLUG
    user.updatedAt = datetime.utcnow()
    await write_admin_audit(db, admin, "revoke_admin", "user", user.id, {"email": user.email})
    await db.commit()
    return {"status": "revoked", "user": _admin_user_payload(user)}
