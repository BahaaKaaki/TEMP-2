"""
Bulk-replace a deprecated LLM model across workflow definitions (batched, safe).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.workflow_llm_nodes import replace_models_in_nodes_json
from app.db.models import WorkflowEntity, WorkflowHistory
from app.llm.model_normalizer import normalize_model_name
from app.llm.registry import LlmModelRegistry

logger = logging.getLogger(__name__)

BATCH_SIZE = 40


def required_confirmation_phrase(from_model: str, to_model: str) -> str:
    from_norm = normalize_model_name(from_model)
    to_norm = normalize_model_name(to_model)
    return f"REPLACE {from_norm} WITH {to_norm}"


class WorkflowModelReplaceService:
    @classmethod
    async def preview(
        cls,
        db: AsyncSession,
        *,
        from_model: str,
        to_model: str,
        include_live: bool = True,
        include_published: bool = True,
    ) -> Dict[str, Any]:
        from_norm = normalize_model_name(from_model)
        to_norm = normalize_model_name(to_model)

        if from_norm == to_norm:
            return {
                "from_model": from_norm,
                "to_model": to_norm,
                "error": "Source and target model are the same after normalization.",
            }

        live_wf = 0
        live_nodes = 0
        pub_wf = 0
        pub_nodes = 0
        live_workflow_names: set[str] = set()
        published_workflow_names: set[str] = set()

        if include_live:
            rows = (
                await db.execute(select(WorkflowEntity.id, WorkflowEntity.name, WorkflowEntity.nodes))
            ).all()
            for _wf_id, name, nodes in rows:
                _new, changed, fields = replace_models_in_nodes_json(nodes, from_norm, to_norm)
                if changed:
                    live_wf += 1
                    live_nodes += fields
                    if name:
                        live_workflow_names.add(name)

        if include_published:
            id_to_name = dict(
                (await db.execute(select(WorkflowEntity.id, WorkflowEntity.name))).all()
            )
            rows = (
                await db.execute(
                    select(WorkflowHistory.versionId, WorkflowHistory.workflowId, WorkflowHistory.nodes).where(
                        WorkflowHistory.isPublishedSnapshot == True  # noqa: E712
                    )
                )
            ).all()
            for _vid, wf_id, nodes in rows:
                _new, changed, fields = replace_models_in_nodes_json(nodes, from_norm, to_norm)
                if changed:
                    pub_wf += 1
                    pub_nodes += fields
                    if wf_id:
                        published_workflow_names.add(
                            id_to_name.get(wf_id) or f"(deleted workflow {wf_id})"
                        )

        live_sorted = sorted(live_workflow_names)
        pub_sorted = sorted(published_workflow_names)
        all_names = sorted(live_workflow_names | published_workflow_names)

        return {
            "from_model": from_norm,
            "to_model": to_norm,
            "include_live": include_live,
            "include_published": include_published,
            "live_workflows_affected": live_wf,
            "live_node_fields_affected": live_nodes,
            "published_snapshots_affected": pub_wf,
            "published_node_fields_affected": pub_nodes,
            "live_workflow_names": live_sorted,
            "published_workflow_names": pub_sorted,
            "affected_workflow_names": all_names,
            "required_confirmation": required_confirmation_phrase(from_norm, to_norm),
        }

    @classmethod
    async def execute(
        cls,
        db: AsyncSession,
        *,
        from_model: str,
        to_model: str,
        confirmation: str,
        include_live: bool = True,
        include_published: bool = True,
    ) -> Dict[str, Any]:
        from_norm = normalize_model_name(from_model)
        to_norm = normalize_model_name(to_model)
        expected = required_confirmation_phrase(from_norm, to_norm)

        if (confirmation or "").strip() != expected:
            raise ValueError(
                f'Confirmation must match exactly: {expected}'
            )

        if from_norm == to_norm:
            raise ValueError("Source and target model are the same.")

        await LlmModelRegistry.ensure_model_in_catalog(db, to_norm)

        stats = {
            "from_model": from_norm,
            "to_model": to_norm,
            "live_workflows_updated": 0,
            "live_node_fields_updated": 0,
            "published_snapshots_updated": 0,
            "published_node_fields_updated": 0,
        }

        if include_live:
            live_stats = await cls._replace_live_batch(db, from_norm, to_norm)
            stats.update(live_stats)

        if include_published:
            pub_stats = await cls._replace_published_batch(db, from_norm, to_norm)
            stats.update(pub_stats)

        await db.commit()

        # Refresh usage counts after bulk change
        from app.admin.services.workflow_model_scan_service import WorkflowModelScanService
        scan_summary = await WorkflowModelScanService.run_full_scan(db)
        stats["usage_rescan"] = scan_summary

        logger.info("Workflow model replace completed: %s -> %s (%s)", from_norm, to_norm, stats)
        return stats

    @classmethod
    async def _replace_live_batch(cls, db: AsyncSession, from_norm: str, to_norm: str) -> Dict[str, int]:
        workflows_updated = 0
        fields_updated = 0
        offset = 0

        while True:
            batch = (
                await db.execute(
                    select(WorkflowEntity)
                    .order_by(WorkflowEntity.id)
                    .offset(offset)
                    .limit(BATCH_SIZE)
                )
            ).scalars().all()

            if not batch:
                break

            for wf in batch:
                new_nodes, changed, fields = replace_models_in_nodes_json(wf.nodes, from_norm, to_norm)
                if not changed or new_nodes is None:
                    continue
                wf.nodes = new_nodes
                workflows_updated += 1
                fields_updated += fields

            await db.flush()
            offset += BATCH_SIZE

        return {
            "live_workflows_updated": workflows_updated,
            "live_node_fields_updated": fields_updated,
        }

    @classmethod
    async def _replace_published_batch(cls, db: AsyncSession, from_norm: str, to_norm: str) -> Dict[str, int]:
        snapshots_updated = 0
        fields_updated = 0
        offset = 0

        while True:
            batch = (
                await db.execute(
                    select(WorkflowHistory)
                    .where(WorkflowHistory.isPublishedSnapshot == True)  # noqa: E712
                    .order_by(WorkflowHistory.versionId)
                    .offset(offset)
                    .limit(BATCH_SIZE)
                )
            ).scalars().all()

            if not batch:
                break

            for snap in batch:
                new_nodes, changed, fields = replace_models_in_nodes_json(snap.nodes, from_norm, to_norm)
                if not changed or new_nodes is None:
                    continue
                snap.nodes = new_nodes
                snapshots_updated += 1
                fields_updated += fields

            await db.flush()
            offset += BATCH_SIZE

        return {
            "published_snapshots_updated": snapshots_updated,
            "published_node_fields_updated": fields_updated,
        }
