"""
Analytics service: aggregates execution metrics from PostgreSQL
and token/cost data from the Langfuse API into pre-computed daily snapshots.

Design goals:
- Never runs heavy queries in the request path
- Refresh is triggered explicitly by admin (or scheduled)
- Token/cost analytics are offloaded to Langfuse; we pull aggregates via API
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalyticsExecutionDaily,
    AnalyticsModelDaily,
    AnalyticsRefreshLog,
    AnalyticsServiceDaily,
    ExecutionEntity,
    User,
    WorkflowEntity,
)

logger = logging.getLogger(__name__)

# All refreshes (manual, scheduled, bootstrap) use this window unless overridden per request.
DEFAULT_LOOKBACK_DAYS = int(os.environ.get("ANALYTICS_INCREMENTAL_DAYS", "7"))
INCREMENTAL_LOOKBACK_DAYS = DEFAULT_LOOKBACK_DAYS
BULK_UPSERT_CHUNK = 500
LANGFUSE_TEMP_INSERT_CHUNK = 500
ADVISORY_LOCK_KEY = 284101
STALE_RUNNING_REFRESH_HOURS = int(os.environ.get("ANALYTICS_STALE_RUNNING_HOURS", "3"))
STALE_QUEUED_REFRESH_MINUTES = int(os.environ.get("ANALYTICS_STALE_QUEUED_MINUTES", "10"))


def _date_start(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def _window_bounds(from_date: date, to_date: date) -> Tuple[datetime, datetime]:
    return _date_start(from_date), _date_start(to_date)


# ---------------------------------------------------------------------------
# Langfuse API helpers
# ---------------------------------------------------------------------------

def _langfuse_api_config() -> Optional[Dict[str, Any]]:
    """Return Langfuse API config or None if disabled."""
    from utils.langfuse_config import (
        _gcass_proxy_headers,
        _langfuse_http_verify,
        _langfuse_ui_base_url,
        is_langfuse_enabled,
    )

    if not is_langfuse_enabled():
        return None

    base_url = _langfuse_ui_base_url()
    if not base_url:
        return None

    return {
        "base_url": base_url.rstrip("/"),
        "headers": _gcass_proxy_headers(include_langfuse_auth=True),
        "verify": _langfuse_http_verify(),
    }


async def _fetch_langfuse_observations_page(
    client: httpx.AsyncClient,
    config: Dict[str, Any],
    *,
    from_timestamp: str,
    to_timestamp: str,
    page: int = 1,
    limit: int = 100,
    obs_type: str = "GENERATION",
) -> Dict[str, Any]:
    """
    Fetch observations from Langfuse public API.

    Tries endpoints in order of preference:
    1. /api/public/observations (v1, works on self-hosted)
    2. /api/public/generations (v1 legacy, some deployments)
    """
    base = config["base_url"]
    headers = config["headers"]
    params: Dict[str, Any] = {
        "page": page,
        "limit": limit,
        "type": obs_type,
        "fromStartTime": from_timestamp,
        "toStartTime": to_timestamp,
    }

    url = f"{base}/api/public/observations"
    response = await client.get(url, params=params, headers=headers)

    if response.status_code == 405 or response.status_code == 404:
        params_alt = {
            "page": page,
            "limit": limit,
            "fromTimestamp": from_timestamp,
            "toTimestamp": to_timestamp,
        }
        url = f"{base}/api/public/generations"
        response = await client.get(url, params=params_alt, headers=headers)

    if response.status_code != 200:
        logger.warning(
            "Langfuse observations API returned %s: %s",
            response.status_code,
            (response.text or "")[:300],
        )
        return {"data": [], "meta": {"totalItems": 0, "totalPages": 0}}

    return response.json()


async def _fetch_all_langfuse_generations(
    config: Dict[str, Any],
    from_date: date,
    to_date: date,
) -> List[Dict[str, Any]]:
    """Paginate through all Langfuse generations in date range."""
    from_ts = datetime.combine(from_date, datetime.min.time()).isoformat() + "Z"
    to_ts = datetime.combine(to_date + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

    all_generations: List[Dict[str, Any]] = []
    page = 1
    limit = 100
    max_pages = 200

    async with httpx.AsyncClient(verify=config["verify"], timeout=60.0) as client:
        while page <= max_pages:
            result = await _fetch_langfuse_observations_page(
                client, config,
                from_timestamp=from_ts, to_timestamp=to_ts,
                page=page, limit=limit,
            )
            data = result.get("data") or []
            all_generations.extend(data)

            meta = result.get("meta") or {}
            total_pages = meta.get("totalPages") or meta.get("total_pages") or 1
            if page >= total_pages or not data:
                break
            page += 1

    logger.info("Langfuse: fetched %d generations across %d pages", len(all_generations), page)
    if all_generations:
        sample = all_generations[0]
        logger.info(
            "Langfuse sample observation keys: %s",
            list(sample.keys()),
        )
        logger.info(
            "Langfuse sample: model=%s, usage=%s, cost=%s, startTime=%s, metadata_keys=%s",
            sample.get("model"),
            sample.get("usage") or sample.get("usageDetails"),
            sample.get("calculatedTotalCost") or sample.get("totalCost"),
            sample.get("startTime") or sample.get("start_time"),
            list((sample.get("metadata") or {}).keys())[:10] if sample.get("metadata") else "none",
        )
    return all_generations


def _extract_obs_usage(gen: Dict[str, Any]) -> Dict[str, int]:
    """
    Normalize usage from a Langfuse observation.
    Handles multiple response formats across Langfuse versions.
    """
    usage = gen.get("usage") or gen.get("usageDetails") or gen.get("usage_details") or {}
    if isinstance(usage, dict):
        inp = int(usage.get("input") or usage.get("promptTokens") or usage.get("prompt_tokens") or usage.get("inputTokens") or 0)
        out = int(usage.get("output") or usage.get("completionTokens") or usage.get("completion_tokens") or usage.get("outputTokens") or 0)
        total = int(usage.get("total") or usage.get("totalTokens") or usage.get("total_tokens") or 0)
        if total <= 0 and (inp > 0 or out > 0):
            total = inp + out
        return {
            "input": inp,
            "output": out,
            "total": total,
            "cache_read": int(usage.get("cache_read_input_tokens") or usage.get("cacheReadInputTokens") or 0),
            "cache_creation": int(usage.get("cache_creation_input_tokens") or usage.get("cacheCreationInputTokens") or 0),
        }
    return {"input": 0, "output": 0, "total": 0, "cache_read": 0, "cache_creation": 0}


def _estimate_cost_from_catalog(usage: Dict[str, int], model_name: str) -> float:
    """Estimate USD when Langfuse API returns no calculated cost on observations."""
    if not model_name or not any(usage.get(k, 0) > 0 for k in ("input", "output", "total")):
        return 0.0
    try:
        from app.llm.model_normalizer import normalize_model_name
        from app.llm.pricing_for_langfuse import compute_cost_details
        from app.llm.registry import LlmModelRegistry

        candidates = [model_name]
        normalized = normalize_model_name(model_name)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

        rates = None
        for candidate in candidates:
            rates = compute_cost_details(usage, model_name=candidate)
            if rates:
                break
            catalog = LlmModelRegistry.get_model_pricing(candidate)
            if catalog:
                rates = compute_cost_details(usage, model_name=candidate, catalog_pricing=catalog)
                if rates:
                    break
        if not rates:
            return 0.0
        total = 0.0
        for key, token_count in usage.items():
            if token_count <= 0:
                continue
            rate = rates.get(key)
            if rate is not None:
                total += token_count * rate
        return total
    except Exception:
        logger.debug("Catalog cost estimate failed for model=%s", model_name, exc_info=True)
        return 0.0


def _extract_obs_cost(gen: Dict[str, Any], *, usage: Optional[Dict[str, int]] = None) -> float:
    """Extract cost from Langfuse observation; fall back to catalog pricing from usage."""
    for key in ("calculatedTotalCost", "calculated_total_cost", "totalCost", "total_cost"):
        val = gen.get(key)
        if val:
            return float(val)

    cost_details = gen.get("costDetails") or gen.get("cost_details") or {}
    if isinstance(cost_details, dict):
        if cost_details.get("total"):
            return float(cost_details["total"])
        detail_sum = sum(
            float(v) for v in cost_details.values()
            if isinstance(v, (int, float)) and v
        )
        if detail_sum > 0:
            return detail_sum

    u = usage if usage is not None else _extract_obs_usage(gen)
    model = gen.get("model") or (gen.get("metadata") or {}).get("model") or ""
    return _estimate_cost_from_catalog(u, str(model))


def _extract_obs_start_time(gen: Dict[str, Any]) -> Optional[date]:
    """Extract and parse the start time from a Langfuse observation."""
    start_time = gen.get("startTime") or gen.get("start_time") or gen.get("createdAt") or ""
    if not start_time:
        return None
    try:
        return datetime.fromisoformat(start_time.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _aggregate_langfuse_by_model_day(
    generations: List[Dict[str, Any]],
) -> Dict[Tuple[date, str], Dict[str, Any]]:
    """Group Langfuse generation data by (date, model_name)."""
    aggregates: Dict[Tuple[date, str], Dict[str, Any]] = {}

    for gen in generations:
        model = gen.get("model") or "unknown"
        gen_date = _extract_obs_start_time(gen)
        if not gen_date:
            continue

        key = (gen_date, model)
        if key not in aggregates:
            aggregates[key] = {
                "generation_count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "total_cost_usd": 0.0,
            }

        agg = aggregates[key]
        agg["generation_count"] += 1

        usage = _extract_obs_usage(gen)
        agg["total_input_tokens"] += usage["input"]
        agg["total_output_tokens"] += usage["output"]
        agg["total_tokens"] += usage["total"]
        agg["cache_read_tokens"] += usage["cache_read"]
        agg["cache_creation_tokens"] += usage["cache_creation"]
        agg["total_cost_usd"] += _extract_obs_cost(gen, usage=usage)

    return aggregates


def _aggregate_langfuse_by_execution_day(
    generations: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """
    Group Langfuse generation tokens/cost by trace session_id (= execution_id).
    Returns {session_id: {input_tokens, output_tokens, total_tokens, cost, count}}.
    """
    by_session: Dict[str, Dict[str, Any]] = {}

    for gen in generations:
        session_id = gen.get("traceSessionId") or gen.get("sessionId") or ""
        if not session_id:
            # Also check metadata for execution_id (set by our observability context)
            metadata = gen.get("metadata") or {}
            session_id = str(metadata.get("execution_id") or "") if metadata.get("execution_id") else ""
        if not session_id:
            continue

        if session_id not in by_session:
            by_session[session_id] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
                "count": 0,
            }

        entry = by_session[session_id]
        entry["count"] += 1

        usage = _extract_obs_usage(gen)
        entry["input_tokens"] += usage["input"]
        entry["output_tokens"] += usage["output"]
        entry["total_tokens"] += usage["total"]
        usage = _extract_obs_usage(gen)
        entry["cost"] += _extract_obs_cost(gen, usage=usage)

    return by_session


def _classify_service_name(gen: Dict[str, Any]) -> Optional[str]:
    """
    Classify a Langfuse generation as a non-workflow service operation.
    Returns the service_name or None if it belongs to a workflow execution.
    """
    metadata = gen.get("metadata") or {}
    execution_id = metadata.get("execution_id")
    if execution_id:
        return None

    llm_role = metadata.get("llm_role") or ""
    binding_key = metadata.get("binding_key") or ""
    operation = metadata.get("operation") or ""
    name = gen.get("name") or ""

    if llm_role == "embedding" or operation == "embedding" or name == "embedding":
        return "embedding"
    if "code_executor" in binding_key or "code_executor" in llm_role:
        return "code_executor"
    if "ocr" in binding_key or "ocr" in llm_role.lower():
        return "ocr"
    if "image" in binding_key or "image" in llm_role.lower() or "vision" in llm_role.lower():
        return "image_processing"
    if "web_search" in binding_key or "web_search" in llm_role:
        return "web_search"
    if "deep_research" in binding_key or "deep_research" in llm_role:
        return "deep_research"
    if "schema" in binding_key or "schema" in llm_role:
        return "schema_inference"
    if "grader" in binding_key or "grader" in llm_role:
        return "kb_grader"
    if "pptx" in binding_key or "powerpoint" in llm_role:
        return "pptx_generation"
    if llm_role in ("tool_calling", "main_llm", "structured_output") or operation.startswith("llm."):
        return llm_role or operation.replace("llm.", "") or "standalone_llm"

    if not execution_id and binding_key:
        return binding_key.split(".")[-1] if "." in binding_key else binding_key

    if not execution_id and llm_role:
        return llm_role

    return None


def _aggregate_langfuse_by_service_day(
    generations: List[Dict[str, Any]],
) -> Dict[Tuple[date, str, str, str, str], Dict[str, Any]]:
    """
    Group non-workflow Langfuse generations by (date, service_name, binding_key, model, user_id).
    Only includes generations that don't belong to a workflow execution.
    """
    aggregates: Dict[Tuple[date, str, str, str, str], Dict[str, Any]] = {}

    for gen in generations:
        service_name = _classify_service_name(gen)
        if not service_name:
            continue

        gen_date = _extract_obs_start_time(gen)
        if not gen_date:
            continue

        metadata = gen.get("metadata") or {}
        binding_key = metadata.get("binding_key") or ""
        model = gen.get("model") or "unknown"
        user_id = metadata.get("user_id") or gen.get("traceUserId") or ""

        key = (gen_date, service_name, binding_key, model, user_id)
        if key not in aggregates:
            aggregates[key] = {
                "user_email": metadata.get("user_email") or "",
                "call_count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
            }

        agg = aggregates[key]
        agg["call_count"] += 1

        usage = _extract_obs_usage(gen)
        agg["total_input_tokens"] += usage["input"]
        agg["total_output_tokens"] += usage["output"]
        agg["total_tokens"] += usage["total"]
        usage = _extract_obs_usage(gen)
        agg["total_cost_usd"] += _extract_obs_cost(gen, usage=usage)

    return aggregates


# ---------------------------------------------------------------------------
# PostgreSQL execution aggregation
# ---------------------------------------------------------------------------

async def _load_langfuse_tokens_temp_table(
    db: AsyncSession,
    langfuse_by_session: Dict[str, Dict[str, Any]],
) -> None:
    """Load per-execution Langfuse totals into a temp table for SQL join."""
    await db.execute(text("DROP TABLE IF EXISTS tmp_lf_session_tokens"))
    await db.execute(
        text(
            """
            CREATE TEMP TABLE tmp_lf_session_tokens (
                session_id TEXT PRIMARY KEY,
                input_tokens BIGINT NOT NULL DEFAULT 0,
                output_tokens BIGINT NOT NULL DEFAULT 0,
                total_tokens BIGINT NOT NULL DEFAULT 0,
                cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                llm_call_count INTEGER NOT NULL DEFAULT 0
            ) ON COMMIT DROP
            """
        )
    )
    if not langfuse_by_session:
        return

    items = list(langfuse_by_session.items())
    for offset in range(0, len(items), LANGFUSE_TEMP_INSERT_CHUNK):
        chunk = items[offset : offset + LANGFUSE_TEMP_INSERT_CHUNK]
        params: Dict[str, Any] = {}
        value_rows: List[str] = []
        for idx, (sid, vals) in enumerate(chunk):
            params[f"sid{idx}"] = sid
            params[f"in{idx}"] = int(vals.get("input_tokens", 0))
            params[f"out{idx}"] = int(vals.get("output_tokens", 0))
            params[f"tot{idx}"] = int(vals.get("total_tokens", 0))
            params[f"cost{idx}"] = float(vals.get("cost", 0.0))
            params[f"cnt{idx}"] = int(vals.get("count", 0))
            value_rows.append(
                f"(:sid{idx}, :in{idx}, :out{idx}, :tot{idx}, :cost{idx}, :cnt{idx})"
            )
        insert_sql = text(
            f"""
            INSERT INTO tmp_lf_session_tokens (
                session_id, input_tokens, output_tokens, total_tokens, cost_usd, llm_call_count
            ) VALUES {", ".join(value_rows)}
            ON CONFLICT (session_id) DO UPDATE SET
                input_tokens = EXCLUDED.input_tokens,
                output_tokens = EXCLUDED.output_tokens,
                total_tokens = EXCLUDED.total_tokens,
                cost_usd = EXCLUDED.cost_usd,
                llm_call_count = EXCLUDED.llm_call_count
            """
        )
        await db.execute(insert_sql, params)


async def _compute_execution_daily(
    db: AsyncSession,
    from_date: date,
    to_date: date,
    langfuse_by_session: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Single-pass aggregation: execution_entity grouped by day + LEFT JOIN
    Langfuse token totals via temp table (no per-row Python loop).
    """
    started_from = datetime.combine(from_date, datetime.min.time())
    started_to = datetime.combine(to_date + timedelta(days=1), datetime.min.time())

    await _load_langfuse_tokens_temp_table(db, langfuse_by_session)

    agg_sql = text(
        """
        SELECT
            DATE(e."startedAt") AS day,
            e."workflowId" AS workflow_id,
            e."triggeredById" AS user_id,
            e.status AS status,
            e.mode AS mode,
            COUNT(e.id) AS execution_count,
            AVG(EXTRACT(EPOCH FROM (e."stoppedAt" - e."startedAt")) * 1000) AS avg_duration_ms,
            MIN(EXTRACT(EPOCH FROM (e."stoppedAt" - e."startedAt")) * 1000) AS min_duration_ms,
            MAX(EXTRACT(EPOCH FROM (e."stoppedAt" - e."startedAt")) * 1000) AS max_duration_ms,
            SUM(EXTRACT(EPOCH FROM (e."stoppedAt" - e."startedAt")) * 1000) AS total_duration_ms,
            COALESCE(SUM(lf.input_tokens), 0) AS total_input_tokens,
            COALESCE(SUM(lf.output_tokens), 0) AS total_output_tokens,
            COALESCE(SUM(lf.total_tokens), 0) AS total_tokens,
            COALESCE(SUM(lf.cost_usd), 0) AS total_cost_usd,
            COALESCE(SUM(lf.llm_call_count), 0) AS llm_call_count
        FROM execution_entity e
        LEFT JOIN tmp_lf_session_tokens lf ON lf.session_id = e.id::text
        WHERE e."startedAt" >= :started_from
          AND e."startedAt" < :started_to
          AND e."deletedAt" IS NULL
        GROUP BY
            DATE(e."startedAt"),
            e."workflowId",
            e."triggeredById",
            e.status,
            e.mode
        """
    )
    result = await db.execute(
        agg_sql,
        {"started_from": started_from, "started_to": started_to},
    )
    rows = result.all()

    workflow_ids = {r.workflow_id for r in rows}
    user_ids = {r.user_id for r in rows}

    workflow_names: Dict[str, str] = {}
    if workflow_ids:
        wf_result = await db.execute(
            select(WorkflowEntity.id, WorkflowEntity.name).where(WorkflowEntity.id.in_(workflow_ids))
        )
        workflow_names = {r.id: r.name for r in wf_result.all()}

    user_emails: Dict[str, str] = {}
    if user_ids:
        u_result = await db.execute(
            select(User.id, User.email).where(User.id.in_(user_ids))
        )
        user_emails = {r.id: r.email for r in u_result.all()}

    records: List[Dict[str, Any]] = []
    for r in rows:
        records.append({
            "date": r.day,
            "workflow_id": r.workflow_id,
            "workflow_name": workflow_names.get(r.workflow_id, ""),
            "user_id": r.user_id,
            "user_email": user_emails.get(r.user_id, ""),
            "status": r.status,
            "mode": r.mode,
            "execution_count": int(r.execution_count or 0),
            "avg_duration_ms": float(r.avg_duration_ms) if r.avg_duration_ms is not None else None,
            "min_duration_ms": float(r.min_duration_ms) if r.min_duration_ms is not None else None,
            "max_duration_ms": float(r.max_duration_ms) if r.max_duration_ms is not None else None,
            "total_duration_ms": float(r.total_duration_ms) if r.total_duration_ms is not None else None,
            "total_input_tokens": int(r.total_input_tokens or 0),
            "total_output_tokens": int(r.total_output_tokens or 0),
            "total_tokens": int(r.total_tokens or 0),
            "total_cost_usd": float(r.total_cost_usd or 0),
            "llm_call_count": int(r.llm_call_count or 0),
        })

    return records


# ---------------------------------------------------------------------------
# Bulk upsert helpers (no delete-first window; prune stale keys after batch)
# ---------------------------------------------------------------------------

async def _bulk_upsert_execution_daily(
    db: AsyncSession,
    records: List[Dict[str, Any]],
    *,
    batch_ts: datetime,
) -> int:
    if not records:
        return 0

    table = AnalyticsExecutionDaily.__table__
    total = 0
    for i in range(0, len(records), BULK_UPSERT_CHUNK):
        chunk = records[i : i + BULK_UPSERT_CHUNK]
        rows = []
        for rec in chunk:
            row_date = rec["date"]
            if isinstance(row_date, date) and not isinstance(row_date, datetime):
                row_date = _date_start(row_date)
            rows.append({
                **rec,
                "date": row_date,
                "computed_at": batch_ts,
                "snapshot_version": 1,
            })
        stmt = pg_insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "workflow_id", "user_id", "status", "mode"],
            set_={
                "workflow_name": stmt.excluded.workflow_name,
                "user_email": stmt.excluded.user_email,
                "execution_count": stmt.excluded.execution_count,
                "avg_duration_ms": stmt.excluded.avg_duration_ms,
                "min_duration_ms": stmt.excluded.min_duration_ms,
                "max_duration_ms": stmt.excluded.max_duration_ms,
                "total_duration_ms": stmt.excluded.total_duration_ms,
                "total_input_tokens": stmt.excluded.total_input_tokens,
                "total_output_tokens": stmt.excluded.total_output_tokens,
                "total_tokens": stmt.excluded.total_tokens,
                "total_cost_usd": stmt.excluded.total_cost_usd,
                "llm_call_count": stmt.excluded.llm_call_count,
                "snapshot_version": stmt.excluded.snapshot_version,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        await db.execute(stmt)
        total += len(chunk)
    return total


async def _prune_stale_execution_daily(
    db: AsyncSession,
    *,
    from_dt: datetime,
    to_dt: datetime,
    batch_ts: datetime,
) -> None:
    await db.execute(
        delete(AnalyticsExecutionDaily).where(
            AnalyticsExecutionDaily.date >= from_dt,
            AnalyticsExecutionDaily.date <= to_dt,
            AnalyticsExecutionDaily.computed_at < batch_ts,
        )
    )


async def _bulk_upsert_model_daily(
    db: AsyncSession,
    model_aggregates: Dict[Tuple[date, str], Dict[str, Any]],
    *,
    model_provider_map: Dict[str, str],
    batch_ts: datetime,
) -> int:
    if not model_aggregates:
        return 0

    table = AnalyticsModelDaily.__table__
    rows = [
        {
            "date": _date_start(d),
            "model_name": model_name,
            "provider": model_provider_map.get(model_name, ""),
            "generation_count": agg["generation_count"],
            "total_input_tokens": agg["total_input_tokens"],
            "total_output_tokens": agg["total_output_tokens"],
            "total_tokens": agg["total_tokens"],
            "cache_read_tokens": agg["cache_read_tokens"],
            "cache_creation_tokens": agg["cache_creation_tokens"],
            "total_cost_usd": agg["total_cost_usd"],
            "computed_at": batch_ts,
        }
        for (d, model_name), agg in model_aggregates.items()
    ]
    total = 0
    for i in range(0, len(rows), BULK_UPSERT_CHUNK):
        chunk = rows[i : i + BULK_UPSERT_CHUNK]
        stmt = pg_insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "model_name"],
            set_={
                "provider": stmt.excluded.provider,
                "generation_count": stmt.excluded.generation_count,
                "total_input_tokens": stmt.excluded.total_input_tokens,
                "total_output_tokens": stmt.excluded.total_output_tokens,
                "total_tokens": stmt.excluded.total_tokens,
                "cache_read_tokens": stmt.excluded.cache_read_tokens,
                "cache_creation_tokens": stmt.excluded.cache_creation_tokens,
                "total_cost_usd": stmt.excluded.total_cost_usd,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        await db.execute(stmt)
        total += len(chunk)
    return total


async def _prune_stale_model_daily(
    db: AsyncSession,
    *,
    from_dt: datetime,
    to_dt: datetime,
    batch_ts: datetime,
) -> None:
    await db.execute(
        delete(AnalyticsModelDaily).where(
            AnalyticsModelDaily.date >= from_dt,
            AnalyticsModelDaily.date <= to_dt,
            AnalyticsModelDaily.computed_at < batch_ts,
        )
    )


async def _bulk_upsert_service_daily(
    db: AsyncSession,
    service_aggregates: Dict[Tuple, Dict[str, Any]],
    *,
    batch_ts: datetime,
) -> int:
    if not service_aggregates:
        return 0

    table = AnalyticsServiceDaily.__table__
    rows = [
        {
            "date": _date_start(d),
            "service_name": service_name,
            "binding_key": binding_key or None,
            "model_name": model_name,
            "user_id": user_id or None,
            "user_email": agg.get("user_email") or None,
            "call_count": agg["call_count"],
            "total_input_tokens": agg["total_input_tokens"],
            "total_output_tokens": agg["total_output_tokens"],
            "total_tokens": agg["total_tokens"],
            "total_cost_usd": agg["total_cost_usd"],
            "computed_at": batch_ts,
        }
        for (d, service_name, binding_key, model_name, user_id), agg in service_aggregates.items()
    ]
    total = 0
    for i in range(0, len(rows), BULK_UPSERT_CHUNK):
        chunk = rows[i : i + BULK_UPSERT_CHUNK]
        stmt = pg_insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "service_name", "binding_key", "model_name", "user_id"],
            set_={
                "user_email": stmt.excluded.user_email,
                "call_count": stmt.excluded.call_count,
                "total_input_tokens": stmt.excluded.total_input_tokens,
                "total_output_tokens": stmt.excluded.total_output_tokens,
                "total_tokens": stmt.excluded.total_tokens,
                "total_cost_usd": stmt.excluded.total_cost_usd,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        await db.execute(stmt)
        total += len(chunk)
    return total


async def _prune_stale_service_daily(
    db: AsyncSession,
    *,
    from_dt: datetime,
    to_dt: datetime,
    batch_ts: datetime,
) -> None:
    await db.execute(
        delete(AnalyticsServiceDaily).where(
            AnalyticsServiceDaily.date >= from_dt,
            AnalyticsServiceDaily.date <= to_dt,
            AnalyticsServiceDaily.computed_at < batch_ts,
        )
    )


# ---------------------------------------------------------------------------
# Refresh orchestrator
# ---------------------------------------------------------------------------

class AnalyticsRefreshService:
    """Orchestrates analytics refresh (Redis queue + bulk upsert)."""

    @classmethod
    async def enqueue_refresh(
        cls,
        db: AsyncSession,
        *,
        triggered_by: Optional[str] = None,
        days_back: int = INCREMENTAL_LOOKBACK_DAYS,
        refresh_type: str = "incremental",
    ) -> Dict[str, Any]:
        """Queue a refresh job in Redis (non-blocking). Prefer scheduled runs in production."""
        from app.admin.services.analytics_refresh_queue import AnalyticsRefreshQueue

        return await AnalyticsRefreshQueue.enqueue_manual(
            db,
            triggered_by=str(triggered_by) if triggered_by else None,
            days_back=days_back,
            refresh_type=refresh_type,
        )

    @classmethod
    async def run_queued_job(
        cls,
        *,
        log_id: int,
        triggered_by: Optional[str],
        days_back: int,
        refresh_type: str,
    ) -> None:
        """Worker entry point: process one job from the Redis queue."""
        if triggered_by:
            from core.request_context import set_current_user_id

            set_current_user_id(triggered_by)

        from app.db.pgsql import get_admin_db

        async for db in get_admin_db():
            log = await db.get(AnalyticsRefreshLog, log_id)
            if log and log.status == "queued":
                log.status = "running"
                await db.commit()

            locked = await cls._try_advisory_lock(db)
            if not locked:
                await cls._fail_log(db, log_id, "Another refresh holds the advisory lock.")
                return
            try:
                await cls._execute_refresh(
                    db,
                    log_id=log_id,
                    triggered_by=triggered_by,
                    days_back=days_back,
                    refresh_type=refresh_type,
                )
            except Exception as exc:
                logger.exception("Analytics refresh failed (log_id=%s)", log_id)
                await cls._fail_log(db, log_id, str(exc))
            finally:
                await cls._release_advisory_lock(db)
            break

    @classmethod
    async def refresh(
        cls,
        db: AsyncSession,
        *,
        triggered_by: Optional[str] = None,
        days_back: int = INCREMENTAL_LOOKBACK_DAYS,
        refresh_type: str = "incremental",
    ) -> Dict[str, Any]:
        """Synchronous refresh (tests / scripts). Prefer enqueue_refresh in production."""
        active = await cls._find_active_refresh(db)
        if active:
            return {
                "status": "already_running",
                "refresh_log_id": active.id,
            }

        to_date = date.today()
        from_date = to_date - timedelta(days=days_back)
        log = AnalyticsRefreshLog(
            refresh_type=refresh_type,
            started_at=datetime.utcnow(),
            status="running",
            triggered_by=triggered_by,
            date_from=_date_start(from_date),
            date_to=_date_start(to_date),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)

        locked = await cls._try_advisory_lock(db)
        if not locked:
            await cls._fail_log(db, log.id, "Another refresh holds the advisory lock.")
            return {"status": "already_running", "refresh_log_id": log.id}

        try:
            return await cls._execute_refresh(
                db,
                log_id=log.id,
                triggered_by=triggered_by,
                days_back=days_back,
                refresh_type=refresh_type,
            )
        finally:
            await cls._release_advisory_lock(db)

    @classmethod
    async def _execute_refresh(
        cls,
        db: AsyncSession,
        *,
        log_id: int,
        triggered_by: Optional[str],
        days_back: int,
        refresh_type: str,
    ) -> Dict[str, Any]:
        log = await db.get(AnalyticsRefreshLog, log_id)
        if not log:
            raise ValueError(f"Refresh log {log_id} not found")

        to_date = date.today()
        from_date = to_date - timedelta(days=days_back)
        from_dt, to_dt = _window_bounds(from_date, to_date)
        log.date_from = from_dt
        log.date_to = to_dt
        batch_ts = datetime.utcnow()

        try:
            langfuse_config = _langfuse_api_config()
            langfuse_generations: List[Dict[str, Any]] = []
            langfuse_by_session: Dict[str, Dict[str, Any]] = {}
            model_aggregates: Dict[Tuple[date, str], Dict[str, Any]] = {}
            service_aggregates: Dict[Tuple, Dict[str, Any]] = {}

            if langfuse_config:
                logger.info("Analytics refresh: fetching Langfuse generations %s to %s", from_date, to_date)
                langfuse_generations = await _fetch_all_langfuse_generations(
                    langfuse_config, from_date, to_date
                )
                log.langfuse_traces = len(langfuse_generations)
                langfuse_by_session = _aggregate_langfuse_by_execution_day(langfuse_generations)
                model_aggregates = _aggregate_langfuse_by_model_day(langfuse_generations)
                service_aggregates = _aggregate_langfuse_by_service_day(langfuse_generations)
            else:
                logger.info("Analytics refresh: Langfuse disabled, skipping token data")

            logger.info("Analytics refresh: computing execution aggregates %s to %s", from_date, to_date)
            exec_records = await _compute_execution_daily(db, from_date, to_date, langfuse_by_session)

            rows_upserted = 0
            if exec_records:
                rows_upserted += await _bulk_upsert_execution_daily(
                    db, exec_records, batch_ts=batch_ts
                )
                await _prune_stale_execution_daily(
                    db, from_dt=from_dt, to_dt=to_dt, batch_ts=batch_ts
                )

            if model_aggregates:
                model_provider_map: Dict[str, str] = {}
                try:
                    from app.llm.registry import LlmModelRegistry

                    catalog = LlmModelRegistry._catalog or {}
                    for name, info in catalog.items():
                        model_provider_map[name] = info.get("provider", "")
                except Exception:
                    pass

                rows_upserted += await _bulk_upsert_model_daily(
                    db,
                    model_aggregates,
                    model_provider_map=model_provider_map,
                    batch_ts=batch_ts,
                )
                await _prune_stale_model_daily(
                    db, from_dt=from_dt, to_dt=to_dt, batch_ts=batch_ts
                )

            if service_aggregates:
                rows_upserted += await _bulk_upsert_service_daily(
                    db, service_aggregates, batch_ts=batch_ts
                )
                await _prune_stale_service_daily(
                    db, from_dt=from_dt, to_dt=to_dt, batch_ts=batch_ts
                )

            log.rows_upserted = rows_upserted
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            await db.commit()

            return {
                "status": "completed",
                "refresh_log_id": log_id,
                "refresh_type": refresh_type,
                "date_from": str(from_date),
                "date_to": str(to_date),
                "execution_rows": len(exec_records),
                "model_rows": len(model_aggregates),
                "service_rows": len(service_aggregates),
                "langfuse_generations": len(langfuse_generations),
                "rows_upserted": rows_upserted,
            }

        except Exception as exc:
            await cls._fail_log(db, log_id, str(exc))
            raise

    @classmethod
    def _refresh_is_stale(cls, log: AnalyticsRefreshLog) -> bool:
        if not log.started_at:
            return True
        age = datetime.utcnow() - log.started_at
        if log.status == "queued":
            return age > timedelta(minutes=STALE_QUEUED_REFRESH_MINUTES)
        return age > timedelta(hours=STALE_RUNNING_REFRESH_HOURS)

    @classmethod
    async def _mark_refresh_failed(
        cls,
        db: AsyncSession,
        log: AnalyticsRefreshLog,
        message: str,
    ) -> None:
        log.status = "failed"
        log.error_message = message[:2000]
        log.completed_at = datetime.utcnow()
        await db.commit()

    @classmethod
    async def reconcile_stale_refreshes(cls, db: AsyncSession) -> int:
        """Fail queued/running rows that exceeded their stale window."""
        stmt = select(AnalyticsRefreshLog).where(
            AnalyticsRefreshLog.status.in_(("queued", "running"))
        )
        rows = (await db.execute(stmt)).scalars().all()
        count = 0
        for log in rows:
            if cls._refresh_is_stale(log):
                await cls._mark_refresh_failed(
                    db,
                    log,
                    f"Marked failed: stuck in '{log.status}' without completing.",
                )
                count += 1
        return count

    @classmethod
    async def cancel_stuck_refreshes(
        cls,
        db: AsyncSession,
        *,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Clear active refresh rows so a new job can be enqueued."""
        stmt = select(AnalyticsRefreshLog).where(
            AnalyticsRefreshLog.status.in_(("queued", "running"))
        )
        rows = (await db.execute(stmt)).scalars().all()
        cancelled = 0
        for log in rows:
            if force or cls._refresh_is_stale(log):
                await cls._mark_refresh_failed(
                    db,
                    log,
                    "Cancelled: refresh did not complete (stuck or forced reset).",
                )
                cancelled += 1
        return {"cancelled": cancelled}

    @classmethod
    async def _find_active_refresh(cls, db: AsyncSession) -> Optional[AnalyticsRefreshLog]:
        await cls.reconcile_stale_refreshes(db)
        stmt = (
            select(AnalyticsRefreshLog)
            .where(AnalyticsRefreshLog.status.in_(("queued", "running")))
            .order_by(AnalyticsRefreshLog.started_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def _fail_log(cls, db: AsyncSession, log_id: int, message: str) -> None:
        log = await db.get(AnalyticsRefreshLog, log_id)
        if not log:
            return
        log.status = "failed"
        log.error_message = message[:2000]
        log.completed_at = datetime.utcnow()
        await db.commit()

    @classmethod
    async def _try_advisory_lock(cls, db: AsyncSession) -> bool:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": ADVISORY_LOCK_KEY},
        )
        return bool(result.scalar())

    @classmethod
    async def _release_advisory_lock(cls, db: AsyncSession) -> None:
        await db.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": ADVISORY_LOCK_KEY},
        )


# ---------------------------------------------------------------------------
# Query service (serves dashboard data from pre-computed tables)
# ---------------------------------------------------------------------------

class AnalyticsQueryService:
    """Query pre-computed analytics snapshots for dashboard display."""

    @classmethod
    def _date_range_filters(cls, date_column, from_date: Optional[date], to_date: Optional[date]) -> list:
        """Inclusive calendar-day window on a snapshot date column."""
        filters: list = []
        if from_date:
            filters.append(date_column >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            filters.append(
                date_column < datetime.combine(to_date + timedelta(days=1), datetime.min.time())
            )
        return filters

    @classmethod
    async def _sum_platform_from_models(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> Dict[str, float]:
        """Same totals as the Token Consumption tab (sum of model_daily rows)."""
        models = await cls.get_model_consumption(db, from_date=from_date, to_date=to_date)
        return {
            "platform_cost_usd": sum(float(m.get("total_cost_usd") or 0) for m in models),
            "platform_tokens": sum(int(m.get("total_tokens") or 0) for m in models),
            "platform_llm_calls": sum(int(m.get("generation_count") or 0) for m in models),
            "total_input_tokens": sum(int(m.get("total_input_tokens") or 0) for m in models),
            "total_output_tokens": sum(int(m.get("total_output_tokens") or 0) for m in models),
        }

    @classmethod
    async def get_execution_summary(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Overview KPIs. Executions respect workflow/user/status/mode filters.
        Platform tokens/cost/LLM calls come from model_daily (all Langfuse usage).
        With a workflow filter, the headline cost is workflow-attributed cost only.
        """
        exec_filters = cls._build_exec_filters(from_date, to_date, workflow_id, user_id, status, mode)

        exec_stmt = select(
            func.sum(AnalyticsExecutionDaily.execution_count).label("total_executions"),
            func.sum(AnalyticsExecutionDaily.total_duration_ms).label("total_duration_ms"),
            func.avg(AnalyticsExecutionDaily.avg_duration_ms).label("avg_duration_ms"),
            func.sum(AnalyticsExecutionDaily.total_tokens).label("workflow_tokens"),
            func.sum(AnalyticsExecutionDaily.total_cost_usd).label("workflow_cost_usd"),
            func.sum(AnalyticsExecutionDaily.llm_call_count).label("workflow_llm_calls"),
        ).where(*exec_filters)
        exec_row = (await db.execute(exec_stmt)).one_or_none()

        svc_filters = cls._date_range_filters(AnalyticsServiceDaily.date, from_date, to_date)
        if user_id:
            svc_filters.append(AnalyticsServiceDaily.user_id == user_id)

        svc_stmt = select(
            func.sum(AnalyticsServiceDaily.call_count).label("service_calls"),
            func.sum(AnalyticsServiceDaily.total_tokens).label("service_tokens"),
            func.sum(AnalyticsServiceDaily.total_cost_usd).label("service_cost_usd"),
        ).where(*svc_filters) if svc_filters else select(
            func.sum(AnalyticsServiceDaily.call_count).label("service_calls"),
            func.sum(AnalyticsServiceDaily.total_tokens).label("service_tokens"),
            func.sum(AnalyticsServiceDaily.total_cost_usd).label("service_cost_usd"),
        )
        svc_row = (await db.execute(svc_stmt)).one_or_none()

        platform = await cls._sum_platform_from_models(db, from_date=from_date, to_date=to_date)

        workflow_tokens = int(exec_row.workflow_tokens or 0) if exec_row else 0
        service_tokens = int(svc_row.service_tokens or 0) if svc_row else 0
        workflow_cost = float(exec_row.workflow_cost_usd or 0) if exec_row else 0.0
        service_cost = float(svc_row.service_cost_usd or 0) if svc_row else 0.0
        platform_cost = platform["platform_cost_usd"]
        platform_tokens = int(platform["platform_tokens"])
        platform_calls = int(platform["platform_llm_calls"])

        if workflow_id:
            headline_cost = workflow_cost
            cost_scope = "workflow"
        else:
            headline_cost = platform_cost if platform_cost > 0 else (workflow_cost + service_cost)
            cost_scope = "platform"

        return {
            "total_executions": int(exec_row.total_executions or 0) if exec_row else 0,
            "total_duration_ms": float(exec_row.total_duration_ms or 0) if exec_row else 0,
            "avg_duration_ms": float(exec_row.avg_duration_ms or 0) if exec_row else 0,
            "total_input_tokens": int(platform["total_input_tokens"]),
            "total_output_tokens": int(platform["total_output_tokens"]),
            "total_tokens": platform_tokens or (workflow_tokens + service_tokens),
            "total_cost_usd": headline_cost,
            "total_llm_calls": platform_calls,
            "cost_scope": cost_scope,
            "platform_cost_usd": platform_cost,
            "workflow_tokens": workflow_tokens,
            "service_tokens": service_tokens,
            "workflow_cost_usd": workflow_cost,
            "service_cost_usd": service_cost,
        }

    @classmethod
    async def get_execution_timeseries(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        group_by: str = "date",
    ) -> List[Dict[str, Any]]:
        """Time-series execution data grouped by the chosen dimension."""
        filters = cls._build_exec_filters(from_date, to_date, workflow_id, user_id, status, mode)

        group_col = cls._resolve_group_column(group_by)

        stmt = (
            select(
                group_col.label("dimension"),
                func.sum(AnalyticsExecutionDaily.execution_count).label("execution_count"),
                func.avg(AnalyticsExecutionDaily.avg_duration_ms).label("avg_duration_ms"),
                func.sum(AnalyticsExecutionDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsExecutionDaily.total_cost_usd).label("total_cost_usd"),
                func.sum(AnalyticsExecutionDaily.llm_call_count).label("llm_call_count"),
            )
            .where(*filters)
            .group_by(group_col)
            .order_by(group_col)
        )

        result = await db.execute(stmt)
        return [
            {
                "dimension": str(r.dimension) if r.dimension else "unknown",
                "execution_count": int(r.execution_count or 0),
                "avg_duration_ms": float(r.avg_duration_ms or 0),
                "total_tokens": int(r.total_tokens or 0),
                "total_cost_usd": float(r.total_cost_usd or 0),
                "llm_call_count": int(r.llm_call_count or 0),
            }
            for r in result.all()
        ]

    @classmethod
    async def get_model_consumption(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        model_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Model-level token consumption."""
        filters = cls._date_range_filters(AnalyticsModelDaily.date, from_date, to_date)
        if model_name:
            filters.append(AnalyticsModelDaily.model_name == model_name)

        stmt = (
            select(
                AnalyticsModelDaily.model_name,
                AnalyticsModelDaily.provider,
                func.sum(AnalyticsModelDaily.generation_count).label("generation_count"),
                func.sum(AnalyticsModelDaily.total_input_tokens).label("total_input_tokens"),
                func.sum(AnalyticsModelDaily.total_output_tokens).label("total_output_tokens"),
                func.sum(AnalyticsModelDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsModelDaily.cache_read_tokens).label("cache_read_tokens"),
                func.sum(AnalyticsModelDaily.total_cost_usd).label("total_cost_usd"),
            )
            .where(*filters) if filters else select(
                AnalyticsModelDaily.model_name,
                AnalyticsModelDaily.provider,
                func.sum(AnalyticsModelDaily.generation_count).label("generation_count"),
                func.sum(AnalyticsModelDaily.total_input_tokens).label("total_input_tokens"),
                func.sum(AnalyticsModelDaily.total_output_tokens).label("total_output_tokens"),
                func.sum(AnalyticsModelDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsModelDaily.cache_read_tokens).label("cache_read_tokens"),
                func.sum(AnalyticsModelDaily.total_cost_usd).label("total_cost_usd"),
            )
        )

        if filters:
            stmt = (
                select(
                    AnalyticsModelDaily.model_name,
                    AnalyticsModelDaily.provider,
                    func.sum(AnalyticsModelDaily.generation_count).label("generation_count"),
                    func.sum(AnalyticsModelDaily.total_input_tokens).label("total_input_tokens"),
                    func.sum(AnalyticsModelDaily.total_output_tokens).label("total_output_tokens"),
                    func.sum(AnalyticsModelDaily.total_tokens).label("total_tokens"),
                    func.sum(AnalyticsModelDaily.cache_read_tokens).label("cache_read_tokens"),
                    func.sum(AnalyticsModelDaily.total_cost_usd).label("total_cost_usd"),
                )
                .where(*filters)
                .group_by(AnalyticsModelDaily.model_name, AnalyticsModelDaily.provider)
                .order_by(func.sum(AnalyticsModelDaily.total_cost_usd).desc())
            )
        else:
            stmt = (
                select(
                    AnalyticsModelDaily.model_name,
                    AnalyticsModelDaily.provider,
                    func.sum(AnalyticsModelDaily.generation_count).label("generation_count"),
                    func.sum(AnalyticsModelDaily.total_input_tokens).label("total_input_tokens"),
                    func.sum(AnalyticsModelDaily.total_output_tokens).label("total_output_tokens"),
                    func.sum(AnalyticsModelDaily.total_tokens).label("total_tokens"),
                    func.sum(AnalyticsModelDaily.cache_read_tokens).label("cache_read_tokens"),
                    func.sum(AnalyticsModelDaily.total_cost_usd).label("total_cost_usd"),
                )
                .group_by(AnalyticsModelDaily.model_name, AnalyticsModelDaily.provider)
                .order_by(func.sum(AnalyticsModelDaily.total_cost_usd).desc())
            )

        result = await db.execute(stmt)
        return [
            {
                "model_name": r.model_name,
                "provider": r.provider or "",
                "generation_count": int(r.generation_count or 0),
                "total_input_tokens": int(r.total_input_tokens or 0),
                "total_output_tokens": int(r.total_output_tokens or 0),
                "total_tokens": int(r.total_tokens or 0),
                "cache_read_tokens": int(r.cache_read_tokens or 0),
                "total_cost_usd": float(r.total_cost_usd or 0),
            }
            for r in result.all()
        ]

    @classmethod
    async def get_model_timeseries(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        model_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Daily model consumption time-series."""
        filters = []
        if from_date:
            filters.append(AnalyticsModelDaily.date >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            filters.append(AnalyticsModelDaily.date <= datetime.combine(to_date, datetime.min.time()))
        if model_name:
            filters.append(AnalyticsModelDaily.model_name == model_name)

        stmt = (
            select(
                AnalyticsModelDaily.date,
                func.sum(AnalyticsModelDaily.generation_count).label("generation_count"),
                func.sum(AnalyticsModelDaily.total_input_tokens).label("total_input_tokens"),
                func.sum(AnalyticsModelDaily.total_output_tokens).label("total_output_tokens"),
                func.sum(AnalyticsModelDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsModelDaily.total_cost_usd).label("total_cost_usd"),
            )
            .where(*filters)
            .group_by(AnalyticsModelDaily.date)
            .order_by(AnalyticsModelDaily.date)
        )

        result = await db.execute(stmt)
        return [
            {
                "date": str(r.date),
                "generation_count": int(r.generation_count or 0),
                "total_input_tokens": int(r.total_input_tokens or 0),
                "total_output_tokens": int(r.total_output_tokens or 0),
                "total_tokens": int(r.total_tokens or 0),
                "total_cost_usd": float(r.total_cost_usd or 0),
            }
            for r in result.all()
        ]

    @classmethod
    async def get_top_workflows(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Top workflows by execution count or cost."""
        filters = []
        if from_date:
            filters.append(AnalyticsExecutionDaily.date >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            filters.append(AnalyticsExecutionDaily.date <= datetime.combine(to_date, datetime.min.time()))

        stmt = (
            select(
                AnalyticsExecutionDaily.workflow_id,
                AnalyticsExecutionDaily.workflow_name,
                func.sum(AnalyticsExecutionDaily.execution_count).label("execution_count"),
                func.avg(AnalyticsExecutionDaily.avg_duration_ms).label("avg_duration_ms"),
                func.sum(AnalyticsExecutionDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsExecutionDaily.total_cost_usd).label("total_cost_usd"),
                func.sum(AnalyticsExecutionDaily.llm_call_count).label("llm_call_count"),
            )
            .where(*filters)
            .group_by(AnalyticsExecutionDaily.workflow_id, AnalyticsExecutionDaily.workflow_name)
            .order_by(func.sum(AnalyticsExecutionDaily.execution_count).desc())
            .limit(limit)
        )

        result = await db.execute(stmt)
        return [
            {
                "workflow_id": r.workflow_id,
                "workflow_name": r.workflow_name or r.workflow_id[:8],
                "execution_count": int(r.execution_count or 0),
                "avg_duration_ms": float(r.avg_duration_ms or 0),
                "total_tokens": int(r.total_tokens or 0),
                "total_cost_usd": float(r.total_cost_usd or 0),
                "llm_call_count": int(r.llm_call_count or 0),
            }
            for r in result.all()
        ]

    @classmethod
    async def get_top_users(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Top users by execution count or cost (combines workflow + service costs)."""
        exec_filters = []
        svc_filters = []
        if from_date:
            exec_filters.append(AnalyticsExecutionDaily.date >= datetime.combine(from_date, datetime.min.time()))
            svc_filters.append(AnalyticsServiceDaily.date >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            exec_filters.append(AnalyticsExecutionDaily.date <= datetime.combine(to_date, datetime.min.time()))
            svc_filters.append(AnalyticsServiceDaily.date <= datetime.combine(to_date, datetime.min.time()))

        # Execution-based metrics (workflows)
        exec_stmt = (
            select(
                AnalyticsExecutionDaily.user_id,
                AnalyticsExecutionDaily.user_email,
                func.sum(AnalyticsExecutionDaily.execution_count).label("execution_count"),
                func.sum(AnalyticsExecutionDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsExecutionDaily.total_cost_usd).label("total_cost_usd"),
                func.sum(AnalyticsExecutionDaily.llm_call_count).label("llm_call_count"),
            )
            .where(*exec_filters)
            .group_by(AnalyticsExecutionDaily.user_id, AnalyticsExecutionDaily.user_email)
        )
        exec_result = await db.execute(exec_stmt)
        exec_rows = exec_result.all()

        # Service-based metrics (tools, embeddings, etc.)
        svc_stmt = (
            select(
                AnalyticsServiceDaily.user_id,
                AnalyticsServiceDaily.user_email,
                func.sum(AnalyticsServiceDaily.call_count).label("call_count"),
                func.sum(AnalyticsServiceDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsServiceDaily.total_cost_usd).label("total_cost_usd"),
            )
            .where(AnalyticsServiceDaily.user_id.isnot(None), *svc_filters)
            .group_by(AnalyticsServiceDaily.user_id, AnalyticsServiceDaily.user_email)
        )
        svc_result = await db.execute(svc_stmt)
        svc_rows = svc_result.all()

        # Merge both into a single per-user dict
        user_map: Dict[str, Dict[str, Any]] = {}
        for r in exec_rows:
            uid = r.user_id
            if uid not in user_map:
                user_map[uid] = {
                    "user_id": uid,
                    "user_email": r.user_email or "",
                    "execution_count": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "llm_call_count": 0,
                }
            user_map[uid]["execution_count"] += int(r.execution_count or 0)
            user_map[uid]["total_tokens"] += int(r.total_tokens or 0)
            user_map[uid]["total_cost_usd"] += float(r.total_cost_usd or 0)
            user_map[uid]["llm_call_count"] += int(r.llm_call_count or 0)
            if r.user_email and not user_map[uid]["user_email"]:
                user_map[uid]["user_email"] = r.user_email

        for r in svc_rows:
            uid = r.user_id
            if not uid:
                continue
            if uid not in user_map:
                user_map[uid] = {
                    "user_id": uid,
                    "user_email": r.user_email or "",
                    "execution_count": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "llm_call_count": 0,
                }
            user_map[uid]["total_tokens"] += int(r.total_tokens or 0)
            user_map[uid]["total_cost_usd"] += float(r.total_cost_usd or 0)
            user_map[uid]["llm_call_count"] += int(r.call_count or 0)
            if r.user_email and not user_map[uid]["user_email"]:
                user_map[uid]["user_email"] = r.user_email

        # Sort by execution count (descending) and apply limit
        sorted_users = sorted(user_map.values(), key=lambda u: u["execution_count"], reverse=True)
        return sorted_users[:limit]

    @classmethod
    async def get_status_breakdown(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Execution count by status."""
        filters = []
        if from_date:
            filters.append(AnalyticsExecutionDaily.date >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            filters.append(AnalyticsExecutionDaily.date <= datetime.combine(to_date, datetime.min.time()))

        stmt = (
            select(
                AnalyticsExecutionDaily.status,
                func.sum(AnalyticsExecutionDaily.execution_count).label("count"),
            )
            .where(*filters)
            .group_by(AnalyticsExecutionDaily.status)
            .order_by(func.sum(AnalyticsExecutionDaily.execution_count).desc())
        )

        result = await db.execute(stmt)
        return [{"status": r.status, "count": int(r.count or 0)} for r in result.all()]

    @classmethod
    async def get_last_refresh(cls, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Most recent refresh log (running job takes priority over last completed)."""
        await AnalyticsRefreshService.reconcile_stale_refreshes(db)
        active_stmt = (
            select(AnalyticsRefreshLog)
            .where(AnalyticsRefreshLog.status.in_(("queued", "running")))
            .order_by(AnalyticsRefreshLog.started_at.desc())
            .limit(1)
        )
        active = (await db.execute(active_stmt)).scalar_one_or_none()
        if active:
            return {
                "status": "running" if active.status == "running" else "queued",
                "refresh_log_id": active.id,
                "refresh_type": active.refresh_type,
                "started_at": active.started_at.isoformat() if active.started_at else None,
                "date_from": str(active.date_from) if active.date_from else None,
                "date_to": str(active.date_to) if active.date_to else None,
            }

        stmt = (
            select(AnalyticsRefreshLog)
            .where(AnalyticsRefreshLog.status == "completed")
            .order_by(AnalyticsRefreshLog.completed_at.desc())
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if not row:
            failed_stmt = (
                select(AnalyticsRefreshLog)
                .where(AnalyticsRefreshLog.status == "failed")
                .order_by(AnalyticsRefreshLog.completed_at.desc())
                .limit(1)
            )
            failed = (await db.execute(failed_stmt)).scalar_one_or_none()
            if failed:
                return {
                    "status": "failed",
                    "refresh_log_id": failed.id,
                    "completed_at": failed.completed_at.isoformat() if failed.completed_at else None,
                    "error_message": failed.error_message,
                }
            return None

        return {
            "status": "completed",
            "refresh_type": row.refresh_type,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "date_from": str(row.date_from) if row.date_from else None,
            "date_to": str(row.date_to) if row.date_to else None,
            "rows_upserted": row.rows_upserted,
            "langfuse_traces": row.langfuse_traces,
        }

    @classmethod
    async def get_available_filters(cls, db: AsyncSession) -> Dict[str, List[str]]:
        """Return distinct values for filter dropdowns."""
        workflows_stmt = select(
            AnalyticsExecutionDaily.workflow_id,
            AnalyticsExecutionDaily.workflow_name,
        ).distinct().limit(500)
        wf_result = await db.execute(workflows_stmt)
        workflows = [
            {"id": r.workflow_id, "name": r.workflow_name or r.workflow_id[:8]}
            for r in wf_result.all()
        ]

        users_stmt = select(
            AnalyticsExecutionDaily.user_id,
            AnalyticsExecutionDaily.user_email,
        ).distinct().limit(500)
        u_result = await db.execute(users_stmt)
        users = [
            {"id": r.user_id, "email": r.user_email or ""}
            for r in u_result.all()
        ]

        statuses_stmt = select(AnalyticsExecutionDaily.status).distinct()
        s_result = await db.execute(statuses_stmt)
        statuses = [r.status for r in s_result.all()]

        modes_stmt = select(AnalyticsExecutionDaily.mode).distinct()
        m_result = await db.execute(modes_stmt)
        modes = [r.mode for r in m_result.all()]

        models_stmt = select(AnalyticsModelDaily.model_name).distinct().limit(100)
        mod_result = await db.execute(models_stmt)
        models = [r.model_name for r in mod_result.all()]

        services_stmt = select(AnalyticsServiceDaily.service_name).distinct().limit(50)
        svc_result = await db.execute(services_stmt)
        services = [r.service_name for r in svc_result.all()]

        return {
            "workflows": workflows,
            "users": users,
            "statuses": statuses,
            "modes": modes,
            "models": models,
            "services": services,
        }

    @classmethod
    async def get_service_consumption(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        service_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Service-level consumption (non-workflow: embeddings, code executor, etc.)."""
        filters = []
        if from_date:
            filters.append(AnalyticsServiceDaily.date >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            filters.append(AnalyticsServiceDaily.date <= datetime.combine(to_date, datetime.min.time()))
        if service_name:
            filters.append(AnalyticsServiceDaily.service_name == service_name)

        stmt = (
            select(
                AnalyticsServiceDaily.service_name,
                AnalyticsServiceDaily.model_name,
                func.sum(AnalyticsServiceDaily.call_count).label("call_count"),
                func.sum(AnalyticsServiceDaily.total_input_tokens).label("total_input_tokens"),
                func.sum(AnalyticsServiceDaily.total_output_tokens).label("total_output_tokens"),
                func.sum(AnalyticsServiceDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsServiceDaily.total_cost_usd).label("total_cost_usd"),
            )
            .where(*filters)
            .group_by(AnalyticsServiceDaily.service_name, AnalyticsServiceDaily.model_name)
            .order_by(func.sum(AnalyticsServiceDaily.total_cost_usd).desc())
        )

        result = await db.execute(stmt)
        return [
            {
                "service_name": r.service_name,
                "model_name": r.model_name or "",
                "call_count": int(r.call_count or 0),
                "total_input_tokens": int(r.total_input_tokens or 0),
                "total_output_tokens": int(r.total_output_tokens or 0),
                "total_tokens": int(r.total_tokens or 0),
                "total_cost_usd": float(r.total_cost_usd or 0),
            }
            for r in result.all()
        ]

    @classmethod
    async def get_service_timeseries(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        service_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Daily time-series for service consumption."""
        filters = []
        if from_date:
            filters.append(AnalyticsServiceDaily.date >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            filters.append(AnalyticsServiceDaily.date <= datetime.combine(to_date, datetime.min.time()))
        if service_name:
            filters.append(AnalyticsServiceDaily.service_name == service_name)

        stmt = (
            select(
                AnalyticsServiceDaily.date,
                func.sum(AnalyticsServiceDaily.call_count).label("call_count"),
                func.sum(AnalyticsServiceDaily.total_input_tokens).label("total_input_tokens"),
                func.sum(AnalyticsServiceDaily.total_output_tokens).label("total_output_tokens"),
                func.sum(AnalyticsServiceDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsServiceDaily.total_cost_usd).label("total_cost_usd"),
            )
            .where(*filters)
            .group_by(AnalyticsServiceDaily.date)
            .order_by(AnalyticsServiceDaily.date)
        )

        result = await db.execute(stmt)
        return [
            {
                "date": str(r.date),
                "call_count": int(r.call_count or 0),
                "total_input_tokens": int(r.total_input_tokens or 0),
                "total_output_tokens": int(r.total_output_tokens or 0),
                "total_tokens": int(r.total_tokens or 0),
                "total_cost_usd": float(r.total_cost_usd or 0),
            }
            for r in result.all()
        ]

    @classmethod
    async def get_service_by_user(
        cls,
        db: AsyncSession,
        *,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        service_name: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Service consumption broken down by user."""
        filters = []
        if from_date:
            filters.append(AnalyticsServiceDaily.date >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            filters.append(AnalyticsServiceDaily.date <= datetime.combine(to_date, datetime.min.time()))
        if service_name:
            filters.append(AnalyticsServiceDaily.service_name == service_name)

        stmt = (
            select(
                AnalyticsServiceDaily.user_id,
                AnalyticsServiceDaily.user_email,
                AnalyticsServiceDaily.service_name,
                func.sum(AnalyticsServiceDaily.call_count).label("call_count"),
                func.sum(AnalyticsServiceDaily.total_tokens).label("total_tokens"),
                func.sum(AnalyticsServiceDaily.total_cost_usd).label("total_cost_usd"),
            )
            .where(*filters)
            .group_by(AnalyticsServiceDaily.user_id, AnalyticsServiceDaily.user_email, AnalyticsServiceDaily.service_name)
            .order_by(func.sum(AnalyticsServiceDaily.total_cost_usd).desc())
            .limit(limit)
        )

        result = await db.execute(stmt)
        return [
            {
                "user_id": r.user_id or "",
                "user_email": r.user_email or "",
                "service_name": r.service_name,
                "call_count": int(r.call_count or 0),
                "total_tokens": int(r.total_tokens or 0),
                "total_cost_usd": float(r.total_cost_usd or 0),
            }
            for r in result.all()
        ]

    # ---- helpers ----

    @classmethod
    def _build_exec_filters(cls, from_date, to_date, workflow_id, user_id, status, mode):
        filters = cls._date_range_filters(AnalyticsExecutionDaily.date, from_date, to_date)
        if workflow_id:
            filters.append(AnalyticsExecutionDaily.workflow_id == workflow_id)
        if user_id:
            filters.append(AnalyticsExecutionDaily.user_id == user_id)
        if status:
            filters.append(AnalyticsExecutionDaily.status == status)
        if mode:
            filters.append(AnalyticsExecutionDaily.mode == mode)
        return filters

    @classmethod
    def _resolve_group_column(cls, group_by: str):
        mapping = {
            "date": AnalyticsExecutionDaily.date,
            "workflow": AnalyticsExecutionDaily.workflow_name,
            "user": AnalyticsExecutionDaily.user_email,
            "status": AnalyticsExecutionDaily.status,
            "mode": AnalyticsExecutionDaily.mode,
        }
        return mapping.get(group_by, AnalyticsExecutionDaily.date)
