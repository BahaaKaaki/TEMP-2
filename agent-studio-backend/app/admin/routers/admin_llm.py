"""
Admin API for unified LLM catalog, tool bindings, and workflow model inventory.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.audit import write_admin_audit
from app.admin.services.all_models_service import AllModelsService
from app.admin.services.langfuse_model_sync import LangfuseModelSyncService
from app.admin.services.workflow_model_scan_service import WorkflowModelScanService
from app.admin.services.workflow_model_replace_service import WorkflowModelReplaceService
from app.core.dependencies import get_current_admin_user
from app.db.models import (
    LlmModel,
    LlmModelBinding,
    LlmModelWorkflowUsage,
    User,
)
from app.db.pgsql import get_admin_db
from app.llm.registry import LlmModelRegistry

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin_user)],
)


class BindingUpdate(BaseModel):
    primary_model_name: Optional[str] = None
    enabled: Optional[bool] = None
    display_name: Optional[str] = None


class ModelPatch(BaseModel):
    fallback_model_name: Optional[str] = None
    is_deprecated: Optional[bool] = None
    display_label: Optional[str] = None
    input_price_per_1m_tokens: Optional[float] = Field(None, ge=0)
    output_price_per_1m_tokens: Optional[float] = Field(None, ge=0)
    cache_read_price_per_1m_tokens: Optional[float] = Field(None, ge=0)
    cache_creation_price_per_1m_tokens: Optional[float] = Field(None, ge=0)
    admin_notes: Optional[str] = None
    langfuse_match_pattern: Optional[str] = None


class WorkflowModelReplaceRequest(BaseModel):
    from_model: str
    to_model: str
    confirmation: Optional[str] = None
    include_live: bool = True
    include_published: bool = True


@router.get("/llm/models")
async def list_all_models(
    db: AsyncSession = Depends(get_admin_db),
    _admin: User = Depends(get_current_admin_user),
) -> List[Dict[str, Any]]:
    """
    Unified catalog: every llm_models row with tool bindings, workflow usage,
    fallback graph, and pricing metadata (single source of truth for admin + Langfuse).
    """
    return await AllModelsService.list_all(db)


@router.post("/llm/models/rebuild")
async def rebuild_model_catalog(
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Ensure llm_models contains all models referenced by bindings, fallbacks, and workflow scans."""
    counts = await AllModelsService.sync_known_models(db)
    await write_admin_audit(db, admin, "rebuild_catalog", "llm_models", "all", counts)
    await db.commit()
    return {"status": "rebuilt", **counts}


@router.post("/llm/models/sync-langfuse")
async def sync_all_models_to_langfuse(
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Push pricing for all catalog models that have input/output prices set."""
    result = await LangfuseModelSyncService.sync_all_with_pricing(db)
    await write_admin_audit(db, admin, "langfuse_sync_all", "llm_models", "all", result)
    return result


@router.post("/llm/models/{model_name:path}/sync-langfuse")
async def sync_model_to_langfuse(
    model_name: str,
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Push one model's pricing to Langfuse."""
    result = await LangfuseModelSyncService.sync_model(db, model_name)
    if result.get("status") == "synced":
        await write_admin_audit(db, admin, "langfuse_sync", "llm_models", model_name, result)
        await db.commit()
    elif result.get("status") == "error" and result.get("reason") == "model_not_found":
        raise HTTPException(404, f"Model not found: {model_name}")
    return result


@router.get("/llm/tools")
async def list_tool_bindings(
    db: AsyncSession = Depends(get_admin_db),
    _admin: User = Depends(get_current_admin_user),
) -> List[Dict[str, Any]]:
    rows = (
        await db.execute(
            select(LlmModelBinding)
            .where(LlmModelBinding.binding_type.in_(["tool", "service", "settings", "env_default"]))
            .order_by(LlmModelBinding.binding_type, LlmModelBinding.binding_key)
        )
    ).scalars().all()

    models = {
        m.model_name: m
        for m in (await db.execute(select(LlmModel))).scalars().all()
    }

    result = []
    for b in rows:
        model_row = models.get(b.primary_model_name)
        result.append({
            "binding_key": b.binding_key,
            "binding_type": b.binding_type,
            "display_name": b.display_name,
            "primary_model_name": b.primary_model_name,
            "fallback_model_name": model_row.fallback_model_name if model_row else None,
            "enabled": b.enabled,
            "source_file": b.source_file,
        })
    return result


@router.put("/llm/tools/{binding_key}")
async def update_tool_binding(
    binding_key: str,
    body: BindingUpdate,
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    row = await db.get(LlmModelBinding, binding_key)
    if not row:
        raise HTTPException(404, f"Binding not found: {binding_key}")

    if body.primary_model_name is not None:
        exists = await db.get(LlmModel, body.primary_model_name)
        if not exists:
            raise HTTPException(400, f"Unknown model: {body.primary_model_name}")
        row.primary_model_name = body.primary_model_name
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.display_name is not None:
        row.display_name = body.display_name
    row.updatedById = admin.id
    row.updatedAt = datetime.utcnow()

    await write_admin_audit(db, admin, "update_binding", "llm_model_bindings", binding_key, body.model_dump())
    await db.commit()
    LlmModelRegistry.invalidate_cache()
    await LlmModelRegistry.refresh_from_db(db)
    from app.config.llm_config import LLMClientManager
    LLMClientManager.clear_cache()
    return {"binding_key": binding_key, "status": "updated"}


@router.patch("/llm/models/{model_name:path}")
async def patch_model(
    model_name: str,
    body: ModelPatch,
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    row = await db.get(LlmModel, model_name)
    if not row:
        raise HTTPException(404, f"Model not found: {model_name}")

    updates = body.model_dump(exclude_unset=True)
    if "fallback_model_name" in updates:
        fb = updates["fallback_model_name"]
        if fb:
            await LlmModelRegistry.ensure_model_in_catalog(db, fb)
        row.fallback_model_name = fb or None
    if "is_deprecated" in updates:
        row.is_deprecated = updates["is_deprecated"]
    if "display_label" in updates:
        row.display_label = updates["display_label"]
    if "input_price_per_1m_tokens" in updates:
        val = updates["input_price_per_1m_tokens"]
        row.input_price_per_1m_tokens = Decimal(str(val)) if val is not None else None
    if "output_price_per_1m_tokens" in updates:
        val = updates["output_price_per_1m_tokens"]
        row.output_price_per_1m_tokens = Decimal(str(val)) if val is not None else None
    if "cache_read_price_per_1m_tokens" in updates:
        val = updates["cache_read_price_per_1m_tokens"]
        row.cache_read_price_per_1m_tokens = Decimal(str(val)) if val is not None else None
    if "cache_creation_price_per_1m_tokens" in updates:
        val = updates["cache_creation_price_per_1m_tokens"]
        row.cache_creation_price_per_1m_tokens = Decimal(str(val)) if val is not None else None
    if "admin_notes" in updates:
        row.admin_notes = updates["admin_notes"] or None
    if "langfuse_match_pattern" in updates:
        row.langfuse_match_pattern = updates["langfuse_match_pattern"] or None
    row.updatedAt = datetime.utcnow()

    await write_admin_audit(db, admin, "patch_model", "llm_models", model_name, body.model_dump())
    await db.commit()
    LlmModelRegistry.invalidate_cache()
    await LlmModelRegistry.refresh_from_db(db)
    return {"model_name": model_name, "status": "updated"}


@router.get("/llm/workflows")
async def list_workflow_models(
    db: AsyncSession = Depends(get_admin_db),
    _admin: User = Depends(get_current_admin_user),
) -> List[Dict[str, Any]]:
    stmt = select(LlmModel, LlmModelWorkflowUsage).outerjoin(
        LlmModelWorkflowUsage,
        LlmModel.model_name == LlmModelWorkflowUsage.model_name,
    )
    rows = (await db.execute(stmt)).all()
    out = []
    for model, usage in rows:
        live_wf = usage.live_workflows if usage else 0
        pub_wf = usage.published_workflows if usage else 0
        live_refs = usage.live_field_refs if usage else 0
        pub_refs = usage.published_field_refs if usage else 0
        pub_snaps = usage.published_snapshots if usage else 0
        out.append({
            "model_name": model.model_name,
            "display_label": model.display_label,
            "fallback_model_name": model.fallback_model_name,
            "live_workflows": live_wf,
            "published_workflows": pub_wf,
            "published_snapshots": pub_snaps,
            "live_field_refs": live_refs,
            "published_field_refs": pub_refs,
            "total_workflows": live_wf + pub_wf,
            "total_field_refs": live_refs + pub_refs,
            # Legacy keys (field ref counts)
            "live_occurrences": live_refs,
            "published_occurrences": pub_refs,
            "total_occurrences": live_refs + pub_refs,
            "last_scanned_at": usage.lastScannedAt.isoformat() if usage and usage.lastScannedAt else None,
        })
    out.sort(key=lambda x: x["total_workflows"], reverse=True)
    return out


@router.post("/llm/workflows/replace-model/preview")
async def preview_workflow_model_replace(
    body: WorkflowModelReplaceRequest,
    db: AsyncSession = Depends(get_admin_db),
    _admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Dry-run: count workflows/snapshots that would be updated (no writes)."""
    return await WorkflowModelReplaceService.preview(
        db,
        from_model=body.from_model,
        to_model=body.to_model,
        include_live=body.include_live,
        include_published=body.include_published,
    )


@router.post("/llm/workflows/replace-model")
async def execute_workflow_model_replace(
    body: WorkflowModelReplaceRequest,
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """
    Replace every use of from_model with to_model in workflow JSON (batched).
    Requires exact confirmation sentence from preview response.
    """
    if not body.confirmation:
        raise HTTPException(400, "confirmation is required")
    try:
        result = await WorkflowModelReplaceService.execute(
            db,
            from_model=body.from_model,
            to_model=body.to_model,
            confirmation=body.confirmation,
            include_live=body.include_live,
            include_published=body.include_published,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    await write_admin_audit(db, admin, "workflow_model_replace", "workflow_entity", body.from_model, result)
    await db.commit()
    return result


@router.post("/llm/workflows/scan")
async def trigger_workflow_scan(
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    summary = await WorkflowModelScanService.run_full_scan(db)
    await write_admin_audit(db, admin, "workflow_scan", "llm_model_workflow_usage", "all", summary)
    return summary


@router.post("/llm/seed")
async def seed_catalog_from_yaml(
    db: AsyncSession = Depends(get_admin_db),
    admin: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Insert missing rows from config/llm_models_inventory.yaml (never overwrites existing keys)."""
    counts = await LlmModelRegistry.seed_from_yaml(db)
    counts["source"] = "yaml_insert_missing"
    await write_admin_audit(db, admin, "seed_catalog", "llm_models", "yaml", counts)
    return {"status": "seeded", **counts}
