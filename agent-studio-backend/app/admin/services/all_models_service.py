"""
Build the unified "All models" catalog view and ensure every known model exists in llm_models.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LlmModel, LlmModelBinding, LlmModelWorkflowUsage
from app.llm.model_normalizer import infer_provider
from app.llm.pricing_for_langfuse import resolve_model_pricing
from app.llm.registry import LlmModelRegistry


def default_langfuse_match_pattern(model_name: str) -> str:
    """Langfuse regex that matches the exact model id used in generations."""
    escaped = re.escape(model_name)
    return f"(?i)^({escaped})$"


def _decimal_to_float(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


class AllModelsService:
    @classmethod
    async def sync_known_models(cls, db: AsyncSession) -> Dict[str, int]:
        """
        Ensure llm_models contains every model referenced by bindings, fallbacks, workflow usage, and YAML.
        """
        yaml_sync = await LlmModelRegistry.seed_from_yaml(db)

        names: Set[str] = set()

        models = (await db.execute(select(LlmModel.model_name, LlmModel.fallback_model_name))).all()
        for name, fb in models:
            if name:
                names.add(name)
            if fb:
                names.add(fb)

        bindings = (await db.execute(select(LlmModelBinding.primary_model_name))).scalars().all()
        names.update(b for b in bindings if b)

        usage = (await db.execute(select(LlmModelWorkflowUsage.model_name))).scalars().all()
        names.update(u for u in usage if u)

        inserted = 0
        for name in sorted(names):
            row = await db.get(LlmModel, name)
            if row:
                continue
            await LlmModelRegistry.ensure_model_in_catalog(db, name, infer_provider(name))
            inserted += 1

        if inserted:
            await db.commit()
            await LlmModelRegistry.refresh_from_db(db)

        return {
            "inserted": inserted,
            "total_known": len(names),
            "yaml": yaml_sync,
        }

    @classmethod
    async def list_all(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        """Single catalog view: metadata, pricing, tool bindings, workflow usage, fallback graph."""
        models = (await db.execute(select(LlmModel).order_by(LlmModel.model_name))).scalars().all()
        bindings = (await db.execute(select(LlmModelBinding))).scalars().all()
        usage_rows = (await db.execute(select(LlmModelWorkflowUsage))).scalars().all()

        bindings_by_model: Dict[str, List[Dict[str, Any]]] = {}
        for b in bindings:
            bindings_by_model.setdefault(b.primary_model_name, []).append({
                "binding_key": b.binding_key,
                "binding_type": b.binding_type,
                "display_name": b.display_name,
                "enabled": b.enabled,
                "source_file": b.source_file,
            })

        fallback_for: Dict[str, List[str]] = {}
        for m in models:
            if m.fallback_model_name:
                fallback_for.setdefault(m.fallback_model_name, []).append(m.model_name)

        usage_map = {u.model_name: u for u in usage_rows}

        out: List[Dict[str, Any]] = []
        for m in models:
            usage = usage_map.get(m.model_name)
            tool_bindings = bindings_by_model.get(m.model_name, [])
            fb_for = fallback_for.get(m.model_name, [])
            live_wf = usage.live_workflows if usage else 0
            pub_wf = usage.published_workflows if usage else 0
            live_refs = usage.live_field_refs if usage else 0
            pub_refs = usage.published_field_refs if usage else 0

            in_tools = len(tool_bindings) > 0
            in_workflows = live_wf > 0 or pub_wf > 0 or live_refs > 0 or pub_refs > 0

            out.append({
                "model_name": m.model_name,
                "provider": m.provider,
                "display_label": m.display_label,
                "fallback_model_name": m.fallback_model_name,
                "is_deprecated": m.is_deprecated,
                "discovered_in_proxy": m.discovered_in_proxy,
                "input_price_per_1m_tokens": _decimal_to_float(m.input_price_per_1m_tokens),
                "output_price_per_1m_tokens": _decimal_to_float(m.output_price_per_1m_tokens),
                "cache_read_price_per_1m_tokens": _decimal_to_float(m.cache_read_price_per_1m_tokens),
                "cache_creation_price_per_1m_tokens": _decimal_to_float(
                    m.cache_creation_price_per_1m_tokens
                ),
                "effective_cache_read_price_per_1m_tokens": resolve_model_pricing(m).get(
                    "cache_read_price_per_1m_tokens"
                ),
                "effective_cache_creation_price_per_1m_tokens": resolve_model_pricing(m).get(
                    "cache_creation_price_per_1m_tokens"
                ),
                "admin_notes": m.admin_notes,
                "langfuse_match_pattern": m.langfuse_match_pattern or default_langfuse_match_pattern(m.model_name),
                "langfuse_last_synced_at": (
                    m.langfuse_last_synced_at.isoformat() if m.langfuse_last_synced_at else None
                ),
                "tool_bindings": tool_bindings,
                "fallback_for_models": sorted(fb_for),
                "live_workflows": live_wf,
                "published_workflows": pub_wf,
                "live_field_refs": live_refs,
                "published_field_refs": pub_refs,
                "published_snapshots": usage.published_snapshots if usage else 0,
                "last_scanned_at": (
                    usage.lastScannedAt.isoformat() if usage and usage.lastScannedAt else None
                ),
                "in_tools": in_tools,
                "in_workflows": in_workflows,
                "is_fallback_for_others": len(fb_for) > 0,
                "binding_count": len(tool_bindings),
            })

        out.sort(
            key=lambda r: (
                -(r["live_workflows"] + r["published_workflows"]),
                -r["binding_count"],
                r["model_name"],
            ),
        )
        return out
