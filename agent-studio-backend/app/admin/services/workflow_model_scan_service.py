"""
Scan workflow_entity and published workflow_history for LLM model names.

Counts:
- *workflows* = unique workflow_entity rows (live) or workflow IDs (published)
- *field refs* = each modelName / deliverableModelName on an agent-type node
- *snapshots* = published workflow_history rows containing the model
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LlmModelWorkflowUsage, WorkflowEntity, WorkflowHistory
from app.llm.model_normalizer import normalize_model_name
from app.llm.registry import LlmModelRegistry

logger = logging.getLogger(__name__)

AGENT_NODE_TYPES = {
    "agent",
    "researcher",
    "business-analyst",
    "financial-modeler",
    "opportunity-classifier",
    "subagent",
}

MODEL_CONFIG_KEYS = (
    ("modelName", "modelProvider"),
    ("deliverableModelName", "deliverableModelProvider"),
)


def _extract_config(node: Dict[str, Any]) -> Dict[str, Any]:
    cfg = node.get("config") or {}
    if not cfg and isinstance(node.get("data"), dict):
        cfg = node["data"].get("config") or {}
    return cfg if isinstance(cfg, dict) else {}


def _models_from_nodes(nodes_json: str) -> List[Tuple[str, Optional[str]]]:
    """All model field hits in order (duplicates allowed — one per node field)."""
    found: List[Tuple[str, Optional[str]]] = []
    if not nodes_json:
        return found
    try:
        payload = json.loads(nodes_json) if isinstance(nodes_json, str) else nodes_json
    except (json.JSONDecodeError, TypeError):
        return found

    nodes = payload if isinstance(payload, list) else payload.get("nodes", [])
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type", "")
        if ntype not in AGENT_NODE_TYPES:
            continue
        cfg = _extract_config(node)
        for name_key, provider_key in MODEL_CONFIG_KEYS:
            name = cfg.get(name_key)
            if name:
                provider = cfg.get(provider_key)
                found.append((str(name), provider))
    return found


class WorkflowModelScanService:
    @classmethod
    async def run_full_scan(cls, db: AsyncSession) -> Dict[str, Any]:
        live_workflow_ids: Dict[str, Set[str]] = defaultdict(set)
        live_field_refs: Dict[str, int] = defaultdict(int)

        published_workflow_ids: Dict[str, Set[str]] = defaultdict(set)
        published_snapshots: Dict[str, int] = defaultdict(int)
        published_field_refs: Dict[str, int] = defaultdict(int)

        wf_rows = (
            await db.execute(select(WorkflowEntity.id, WorkflowEntity.nodes))
        ).all()
        for wf_id, nodes in wf_rows:
            hits = _models_from_nodes(nodes)
            models_in_wf: Set[str] = set()
            for name, provider in hits:
                key = normalize_model_name(name, provider)
                live_field_refs[key] += 1
                models_in_wf.add(key)
            for key in models_in_wf:
                live_workflow_ids[key].add(wf_id)

        hist_rows = (
            await db.execute(
                select(WorkflowHistory.workflowId, WorkflowHistory.nodes).where(
                    WorkflowHistory.isPublishedSnapshot == True  # noqa: E712
                )
            )
        ).all()
        for wf_id, nodes in hist_rows:
            hits = _models_from_nodes(nodes)
            if not hits:
                continue
            models_in_snap: Set[str] = set()
            for name, provider in hits:
                key = normalize_model_name(name, provider)
                published_field_refs[key] += 1
                models_in_snap.add(key)
            for key in models_in_snap:
                published_snapshots[key] += 1
                if wf_id:
                    published_workflow_ids[key].add(wf_id)

        all_models = (
            set(live_workflow_ids)
            | set(published_workflow_ids)
            | set(live_field_refs)
            | set(published_field_refs)
        )
        now = datetime.utcnow()

        for model_name in all_models:
            await LlmModelRegistry.ensure_model_in_catalog(db, model_name)
            usage = await db.get(LlmModelWorkflowUsage, model_name)
            if not usage:
                usage = LlmModelWorkflowUsage(model_name=model_name)
                db.add(usage)

            lw = len(live_workflow_ids.get(model_name, ()))
            lfr = live_field_refs.get(model_name, 0)
            pw = len(published_workflow_ids.get(model_name, ()))
            ps = published_snapshots.get(model_name, 0)
            pfr = published_field_refs.get(model_name, 0)

            usage.live_workflows = lw
            usage.live_field_refs = lfr
            usage.published_workflows = pw
            usage.published_snapshots = ps
            usage.published_field_refs = pfr
            # Legacy columns mirror field refs for older clients
            usage.live_occurrences = lfr
            usage.published_occurrences = pfr
            usage.lastScannedAt = now

        existing = (await db.execute(select(LlmModelWorkflowUsage))).scalars().all()
        for row in existing:
            if row.model_name not in all_models:
                row.live_workflows = 0
                row.live_field_refs = 0
                row.published_workflows = 0
                row.published_snapshots = 0
                row.published_field_refs = 0
                row.live_occurrences = 0
                row.published_occurrences = 0
                row.lastScannedAt = now

        await db.commit()
        await LlmModelRegistry.refresh_from_db(db)

        return {
            "models_found": len(all_models),
            "live_workflows_total": sum(len(s) for s in live_workflow_ids.values()),
            "live_field_refs_total": sum(live_field_refs.values()),
            "published_workflows_total": sum(len(s) for s in published_workflow_ids.values()),
            "published_snapshots_total": sum(published_snapshots.values()),
            "published_field_refs_total": sum(published_field_refs.values()),
            "scanned_at": now.isoformat(),
        }
