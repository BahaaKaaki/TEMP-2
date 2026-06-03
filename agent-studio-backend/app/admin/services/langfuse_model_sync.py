"""
Push llm_models catalog pricing to Langfuse model definitions (public API).

Uses pricingTiers so usage types (input, output, cache read/write, reasoning) align
with generation.usage_details for automatic Langfuse cost calculation.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.services.all_models_service import default_langfuse_match_pattern
from app.admin.services.langfuse_model_upsert_helpers import (
    is_model_name_exists_error,
    parse_http_error,
)
from app.db.models import LlmModel
from app.llm.pricing_for_langfuse import (
    build_langfuse_pricing_tiers,
    has_any_catalog_pricing,
)

logger = logging.getLogger(__name__)


def _langfuse_base_url() -> Optional[str]:
    from utils.langfuse_config import _langfuse_ui_base_url, is_langfuse_enabled

    if not is_langfuse_enabled():
        return None
    return _langfuse_ui_base_url() or None


def _langfuse_headers() -> Dict[str, str]:
    from utils.langfuse_config import _gcass_proxy_headers

    return {
        **_gcass_proxy_headers(include_langfuse_auth=True),
        "Content-Type": "application/json",
    }


def _langfuse_verify():
    from utils.langfuse_config import _langfuse_http_verify

    return _langfuse_http_verify()


def _build_payload(row: LlmModel) -> Optional[Dict[str, Any]]:
    tiers = build_langfuse_pricing_tiers(row)
    if not tiers:
        return None

    pattern = row.langfuse_match_pattern or default_langfuse_match_pattern(row.model_name)
    return {
        "modelName": row.model_name,
        "matchPattern": pattern,
        "unit": "TOKENS",
        "pricingTiers": tiers,
    }


async def _post_model_definition(
    client: httpx.AsyncClient, base_url: str, payload: Dict[str, Any]
) -> Tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/api/public/models"
    try:
        response = await client.post(url, json=payload, headers=_langfuse_headers())
    except Exception as exc:
        logger.warning("Langfuse model sync HTTP error: %s", exc)
        return False, str(exc)

    if response.status_code in (200, 201):
        return True, "ok"
    body = (response.text or "")[:300]
    return False, f"HTTP {response.status_code}: {body}"


async def _list_models_by_name(
    client: httpx.AsyncClient, base_url: str, model_name: str
) -> List[Dict[str, Any]]:
    """Return Langfuse model definitions whose modelName equals model_name."""
    base = base_url.rstrip("/")
    url = f"{base}/api/public/models"
    headers = _langfuse_headers()
    matches: List[Dict[str, Any]] = []
    page = 1
    limit = 100

    while True:
        try:
            response = await client.get(
                url, params={"page": page, "limit": limit}, headers=headers
            )
        except Exception as exc:
            logger.warning("Langfuse model list HTTP error: %s", exc)
            break

        if response.status_code != 200:
            logger.warning(
                "Langfuse model list failed: HTTP %s %s",
                response.status_code,
                (response.text or "")[:200],
            )
            break

        body = response.json()
        for item in body.get("data") or []:
            if (item.get("modelName") or item.get("model_name")) == model_name:
                matches.append(item)

        meta = body.get("meta") or {}
        total_pages = meta.get("totalPages") or meta.get("total_pages") or 1
        if page >= total_pages:
            break
        page += 1

    return matches


async def _delete_model_definition(
    client: httpx.AsyncClient, base_url: str, model_id: str
) -> Tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/api/public/models/{model_id}"
    try:
        response = await client.delete(url, headers=_langfuse_headers())
    except Exception as exc:
        logger.warning("Langfuse model delete HTTP error: %s", exc)
        return False, str(exc)

    if response.status_code in (200, 204):
        return True, "ok"
    body = (response.text or "")[:300]
    return False, f"HTTP {response.status_code}: {body}"


async def _upsert_model_definition(
    base_url: str, payload: Dict[str, Any]
) -> Tuple[bool, str, str]:
    """
    Create a Langfuse model definition, or replace an existing one with the same modelName.

    Langfuse public API has POST (create) and DELETE but no PATCH; on duplicate modelName
    we delete project-owned definitions and POST again.
    """
    model_name = payload.get("modelName") or ""

    try:
        async with httpx.AsyncClient(verify=_langfuse_verify(), timeout=30.0) as client:
            ok, detail = await _post_model_definition(client, base_url, payload)
            if ok:
                return True, detail, "created"

            status, _ = parse_http_error(detail)
            if not is_model_name_exists_error(status, detail):
                return False, detail, "error"

            existing = await _list_models_by_name(client, base_url, model_name)
            if not existing:
                return False, f"{detail}; no existing definition found to update", "error"

            deleted_any = False
            delete_errors: List[str] = []
            for item in existing:
                model_id = item.get("id")
                if not model_id:
                    continue
                del_ok, del_detail = await _delete_model_definition(client, base_url, model_id)
                if del_ok:
                    deleted_any = True
                else:
                    delete_errors.append(f"{model_id}: {del_detail}")

            if not deleted_any:
                err = "; ".join(delete_errors) if delete_errors else detail
                return False, f"could not replace existing model: {err}", "error"

            ok, detail = await _post_model_definition(client, base_url, payload)
            if ok:
                return True, detail, "updated"
            return False, detail, "error"
    except Exception as exc:
        logger.warning("Langfuse model upsert error: %s", exc)
        return False, str(exc), "error"


class LangfuseModelSyncService:
    @classmethod
    async def sync_model(cls, db: AsyncSession, model_name: str) -> Dict[str, Any]:
        base_url = _langfuse_base_url()
        if not base_url:
            return {"model_name": model_name, "status": "skipped", "reason": "langfuse_disabled"}

        row = await db.get(LlmModel, model_name)
        if not row:
            return {"model_name": model_name, "status": "error", "reason": "model_not_found"}

        if not has_any_catalog_pricing(row):
            return {"model_name": model_name, "status": "skipped", "reason": "no_pricing_set"}

        payload = _build_payload(row)
        if not payload:
            return {"model_name": model_name, "status": "skipped", "reason": "no_pricing_set"}

        ok, detail, action = await _upsert_model_definition(base_url, payload)
        if ok:
            row.langfuse_last_synced_at = datetime.utcnow()
            row.updatedAt = datetime.utcnow()
            await db.flush()
            return {
                "model_name": model_name,
                "status": "synced",
                "action": action,
                "payload": payload,
            }

        return {"model_name": model_name, "status": "error", "reason": detail, "payload": payload}

    @classmethod
    async def sync_all_with_pricing(cls, db: AsyncSession) -> Dict[str, Any]:
        from sqlalchemy import select

        base_url = _langfuse_base_url()
        if not base_url:
            return {"status": "skipped", "reason": "langfuse_disabled", "results": []}

        rows = (
            await db.execute(
                select(LlmModel).where(
                    (LlmModel.input_price_per_1m_tokens.isnot(None))
                    | (LlmModel.output_price_per_1m_tokens.isnot(None))
                )
            )
        ).scalars().all()

        results: List[Dict[str, Any]] = []
        synced = 0
        failed = 0
        skipped = 0

        for row in rows:
            result = await cls.sync_model(db, row.model_name)
            results.append(result)
            st = result.get("status")
            if st == "synced":
                synced += 1
            elif st == "error":
                failed += 1
            else:
                skipped += 1

        await db.commit()
        return {
            "status": "completed",
            "synced": synced,
            "failed": failed,
            "skipped": skipped,
            "total": len(rows),
            "results": results,
        }
