"""
Admin API for analytics dashboard.

Provides pre-computed execution and consumption metrics. Snapshots are rebuilt
on a schedule (midnight incremental, Sunday full) via a Redis-backed worker.
Token/cost data is sourced from Langfuse to avoid burdening the main server.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.analytics_service import (
    AnalyticsQueryService,
    AnalyticsRefreshService,
)
from app.admin.services.user_activity_service import UserActivityAnalyticsService
from app.core.dependencies import get_current_admin_user
from app.db.models import User
from app.db.pgsql import get_admin_db

router = APIRouter(
    prefix="/api/admin/analytics",
    tags=["admin-analytics"],
    dependencies=[Depends(get_current_admin_user)],
)


# ---------------------------------------------------------------------------
# Refresh (manual for testing; scheduled runs at midnight — see admin.scheduler)
# ---------------------------------------------------------------------------

@router.post("/refresh/cancel-stuck")
async def cancel_stuck_refresh(
    force: bool = Query(
        default=False,
        description="Fail all queued/running rows immediately (not only stale ones).",
    ),
    db: AsyncSession = Depends(get_admin_db),
):
    """Clear a stuck refresh so POST /refresh can run again."""
    return await AnalyticsRefreshService.cancel_stuck_refreshes(db, force=force)


@router.post("/refresh")
async def trigger_refresh(
    days_back: int = Query(default=7, ge=1, le=31),
    refresh_type: str = Query(default="incremental"),
    force: bool = Query(
        default=False,
        description="Cancel any stuck refresh, then queue a new job.",
    ),
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Queue an analytics refresh (non-blocking). Poll GET /last-refresh for status.
    """
    if force:
        await AnalyticsRefreshService.cancel_stuck_refreshes(db, force=True)
    result = await AnalyticsRefreshService.enqueue_refresh(
        db,
        triggered_by=current_user.id,
        days_back=days_back,
        refresh_type=refresh_type,
    )
    if result.get("status") == "already_running":
        raise HTTPException(
            status_code=409,
            detail=result.get("message", "Refresh already in progress."),
        )
    return result


@router.get("/last-refresh")
async def get_last_refresh(
    db: AsyncSession = Depends(get_admin_db),
):
    """Get info about the most recent successful refresh."""
    return await AnalyticsQueryService.get_last_refresh(db) or {
        "status": "never_refreshed"
    }


# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------

@router.get("/summary")
async def get_summary(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    workflow_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_admin_db),
):
    """Get aggregated execution + consumption KPIs."""
    return await AnalyticsQueryService.get_execution_summary(
        db,
        from_date=from_date,
        to_date=to_date,
        workflow_id=workflow_id,
        user_id=user_id,
        status=status,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Time-series
# ---------------------------------------------------------------------------

@router.get("/timeseries")
async def get_timeseries(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    workflow_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
    group_by: str = Query(default="date"),
    db: AsyncSession = Depends(get_admin_db),
):
    """Get time-series execution data grouped by a chosen dimension."""
    valid_groups = ["date", "workflow", "user", "status", "mode"]
    if group_by not in valid_groups:
        raise HTTPException(400, f"group_by must be one of: {valid_groups}")

    return await AnalyticsQueryService.get_execution_timeseries(
        db,
        from_date=from_date,
        to_date=to_date,
        workflow_id=workflow_id,
        user_id=user_id,
        status=status,
        mode=mode,
        group_by=group_by,
    )


# ---------------------------------------------------------------------------
# Model consumption
# ---------------------------------------------------------------------------

@router.get("/models")
async def get_model_consumption(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    model_name: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_admin_db),
):
    """Get model-level token consumption breakdown."""
    return await AnalyticsQueryService.get_model_consumption(
        db, from_date=from_date, to_date=to_date, model_name=model_name
    )


@router.get("/models/timeseries")
async def get_model_timeseries(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    model_name: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_admin_db),
):
    """Get daily model consumption time-series."""
    return await AnalyticsQueryService.get_model_timeseries(
        db, from_date=from_date, to_date=to_date, model_name=model_name
    )


# ---------------------------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Service consumption (non-workflow: embeddings, code executor, OCR, etc.)
# ---------------------------------------------------------------------------

@router.get("/services")
async def get_service_consumption(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    service_name: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_admin_db),
):
    """Get service-level consumption (non-workflow operations)."""
    return await AnalyticsQueryService.get_service_consumption(
        db, from_date=from_date, to_date=to_date, service_name=service_name
    )


@router.get("/services/timeseries")
async def get_service_timeseries(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    service_name: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_admin_db),
):
    """Daily service consumption time-series."""
    return await AnalyticsQueryService.get_service_timeseries(
        db, from_date=from_date, to_date=to_date, service_name=service_name
    )


@router.get("/services/by-user")
async def get_service_by_user(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    service_name: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_admin_db),
):
    """Service consumption broken down by user."""
    return await AnalyticsQueryService.get_service_by_user(
        db, from_date=from_date, to_date=to_date,
        service_name=service_name, limit=limit,
    )


# ---------------------------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------------------------

@router.get("/top-workflows")
async def get_top_workflows(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_admin_db),
):
    """Top workflows by execution count."""
    return await AnalyticsQueryService.get_top_workflows(
        db, from_date=from_date, to_date=to_date, limit=limit
    )


@router.get("/top-users")
async def get_top_users(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_admin_db),
):
    """Top users by execution count."""
    return await AnalyticsQueryService.get_top_users(
        db, from_date=from_date, to_date=to_date, limit=limit
    )


@router.get("/status-breakdown")
async def get_status_breakdown(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_admin_db),
):
    """Execution counts by status."""
    return await AnalyticsQueryService.get_status_breakdown(
        db, from_date=from_date, to_date=to_date
    )


# ---------------------------------------------------------------------------
# User activity (live execution_entity queries)
# ---------------------------------------------------------------------------

@router.get("/user-activity")
async def get_user_activity(
    months: int = Query(default=12, ge=1, le=36),
    db: AsyncSession = Depends(get_admin_db),
):
    """
    Active users (≥1 workflow run), monthly trend with deltas, workflows by admin vs user.
    """
    return await UserActivityAnalyticsService.get_dashboard(db, months=months)


# ---------------------------------------------------------------------------
# Filters & metadata
# ---------------------------------------------------------------------------

@router.get("/filters")
async def get_available_filters(
    db: AsyncSession = Depends(get_admin_db),
):
    """Return available filter values for the dashboard UI."""
    return await AnalyticsQueryService.get_available_filters(db)


# ---------------------------------------------------------------------------
# Export (CSV)
# ---------------------------------------------------------------------------

@router.get("/export")
async def export_data(
    dataset: str = Query(default="executions"),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    workflow_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_admin_db),
):
    """
    Export analytics data as JSON (frontend converts to CSV).
    dataset: 'executions' | 'models' | 'workflows' | 'users' | 'services'
    """
    from fastapi.responses import JSONResponse

    if dataset == "executions":
        data = await AnalyticsQueryService.get_execution_timeseries(
            db, from_date=from_date, to_date=to_date,
            workflow_id=workflow_id, user_id=user_id,
            group_by="date",
        )
    elif dataset == "models":
        data = await AnalyticsQueryService.get_model_consumption(
            db, from_date=from_date, to_date=to_date
        )
    elif dataset == "workflows":
        data = await AnalyticsQueryService.get_top_workflows(
            db, from_date=from_date, to_date=to_date, limit=100
        )
    elif dataset == "users":
        data = await AnalyticsQueryService.get_top_users(
            db, from_date=from_date, to_date=to_date, limit=100
        )
    elif dataset == "services":
        data = await AnalyticsQueryService.get_service_consumption(
            db, from_date=from_date, to_date=to_date
        )
    else:
        raise HTTPException(400, f"Unknown dataset: {dataset}")

    return JSONResponse(
        content={"dataset": dataset, "data": data},
        headers={"Content-Disposition": f"attachment; filename=analytics_{dataset}.json"},
    )
