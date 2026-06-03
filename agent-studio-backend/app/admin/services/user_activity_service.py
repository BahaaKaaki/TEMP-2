"""
User activity analytics: distinct users with at least one workflow run.

Activity = ≥1 execution_entity row per user (non-deleted).
Admins = user.roleSlug contains 'admin' (e.g. global:Admin).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionEntity, User, WorkflowEntity


def _execution_ts():
    return func.coalesce(ExecutionEntity.startedAt, ExecutionEntity.createdAt)


def _execution_base_filters():
    ts = _execution_ts()
    return and_(ExecutionEntity.deletedAt.is_(None), ts.isnot(None))


def _utc_start_of_day(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def _utc_start_of_week(d: date) -> datetime:
    """Monday 00:00 UTC for the week containing d."""
    monday = d - timedelta(days=d.weekday())
    return _utc_start_of_day(monday)


def _utc_start_of_month(d: date) -> datetime:
    return _utc_start_of_day(d.replace(day=1))


class UserActivityAnalyticsService:
    @classmethod
    async def get_summary(cls, db: AsyncSession) -> Dict[str, Any]:
        ts = _execution_ts()
        base = _execution_base_filters()
        now = datetime.utcnow()
        today_start = _utc_start_of_day(now.date())
        week_start = _utc_start_of_week(now.date())
        month_start = _utc_start_of_month(now.date())

        async def _count_active(*extra_filters) -> int:
            stmt = select(func.count(func.distinct(ExecutionEntity.triggeredById))).where(
                base, *extra_filters
            )
            return int((await db.execute(stmt)).scalar() or 0)

        return {
            "timezone": "UTC",
            "active_all_time": await _count_active(),
            "active_today": await _count_active(ts >= today_start),
            "active_this_week": await _count_active(ts >= week_start),
            "active_this_month": await _count_active(ts >= month_start),
            "period_starts": {
                "today": today_start.isoformat(),
                "week": week_start.isoformat(),
                "month": month_start.isoformat(),
            },
        }

    @classmethod
    async def get_monthly_activity(
        cls,
        db: AsyncSession,
        *,
        months: int = 12,
    ) -> Dict[str, Any]:
        ts = _execution_ts()
        base = _execution_base_filters()

        month_expr = func.date_trunc("month", ts).label("month_start")
        stmt = (
            select(
                month_expr,
                func.count(func.distinct(ExecutionEntity.triggeredById)).label("active_users"),
            )
            .where(base)
            .group_by(month_expr)
            .order_by(month_expr.desc())
            .limit(max(1, min(months, 36)))
        )
        rows = (await db.execute(stmt)).all()
        rows = list(reversed(rows))

        series: List[Dict[str, Any]] = []
        prev: Optional[int] = None
        for r in rows:
            month_dt: datetime = r.month_start
            active = int(r.active_users or 0)
            delta = active - prev if prev is not None else None
            pct_change = None
            if prev is not None and prev > 0:
                pct_change = round((active - prev) / prev * 100, 1)
            elif prev is not None and prev == 0 and active > 0:
                pct_change = 100.0

            series.append(
                {
                    "month": month_dt.strftime("%Y-%m"),
                    "month_label": month_dt.strftime("%b %Y"),
                    "active_users": active,
                    "delta": delta,
                    "pct_change": pct_change,
                    "is_drop": delta is not None and delta < 0,
                }
            )
            prev = active

        return {
            "timezone": "UTC",
            "months": len(series),
            "series": series,
        }

    @classmethod
    async def get_workflows_created_breakdown(cls, db: AsyncSession) -> Dict[str, Any]:
        is_admin_role = func.lower(User.roleSlug).contains("admin")
        stmt = (
            select(
                func.sum(case((is_admin_role, 1), else_=0)).label("admin_count"),
                func.sum(case((is_admin_role, 0), else_=1)).label("user_count"),
                func.count(WorkflowEntity.id).label("total"),
            )
            .select_from(WorkflowEntity)
            .join(User, WorkflowEntity.createdById == User.id)
            .where(WorkflowEntity.isArchived.is_(False))
        )
        row = (await db.execute(stmt)).one()
        admin_count = int(row.admin_count or 0)
        user_count = int(row.user_count or 0)

        return {
            "workflows_by_admins": admin_count,
            "workflows_by_users": user_count,
            "workflows_total": int(row.total or 0),
            "admin_definition": "roleSlug contains 'admin' (e.g. global:Admin)",
        }

    @classmethod
    async def get_dashboard(cls, db: AsyncSession, *, months: int = 12) -> Dict[str, Any]:
        summary = await cls.get_summary(db)
        monthly = await cls.get_monthly_activity(db, months=months)
        workflows = await cls.get_workflows_created_breakdown(db)
        return {
            **summary,
            "monthly": monthly["series"],
            "workflows_created": workflows,
        }
