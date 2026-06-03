"""
Sandbox -> host callback endpoints for Knowledge Base access from
Code Executor nodes.

The sandbox runs untrusted user code and must never talk to the database
directly. Instead it calls these endpoints with an opaque, per-run
**session id** minted by the host right before execution and revoked the
moment the run ends.  Session ids are looked up in the in-process registry
(``services.code_executor_kb_session``); there is no cryptographic
material, no long-lived bearer, and nothing written into the sandbox
filesystem.

Every request:

1. Looks up ``session_id`` in the registry.  Rejects 401 if missing,
   revoked, or expired.
2. Pushes the session's ``user_id`` into the request context so that
   Row-Level Security on the ``knowledge_base`` table auto-filters
   visibility.
3. Confirms the requested ``kb_id`` is in the session's allowlist (403).
4. Re-checks the KB is actually visible to that user (belt-and-braces
   alongside RLS).
5. Routes SQL through ``StructuredDataRepository.execute_query``, which
   switches ``search_path`` to the per-KB schema and enforces SELECT-only
   syntax (via the shared ``_validate_select_only`` helper) with a row
   and timeout cap.

Writes of any kind are rejected at the SQL validator; there is no
INSERT/UPDATE/DELETE path.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.request_context import clear_current_user_id, set_current_user_id
from db.pgsql import get_write_db, set_user_context
from repositories.knowledge_base_repository import KnowledgeBaseRepository
from repositories.structured_data_repository import StructuredDataRepository
from services.code_executor_kb_session import (
    SandboxKbSession,
    get_session,
)
from utils.structured_data_tool import _validate_select_only

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/code-executor/kb",
    tags=["Code Executor KB"],
)


_MAX_ROWS_CEILING = 10_000
_DEFAULT_MAX_ROWS = 1_000
_DEFAULT_TIMEOUT_SECONDS = 30


# ── Request / response models ──────────────────────────────────────────

class _KbRequestBase(BaseModel):
    session_id: str = Field(
        ...,
        description="Opaque per-run session id, issued when the sandbox was spawned",
    )


class KbTablesRequest(_KbRequestBase):
    kb_ids: Optional[List[str]] = Field(
        default=None,
        description="If omitted, returns metadata for every KB in the session allowlist",
    )


class KbColumnOut(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    nullable: bool = True


class KbTableOut(BaseModel):
    kb_id: str
    kb_name: str
    schema_name: str
    table: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    row_count: int = 0
    columns: List[KbColumnOut] = Field(default_factory=list)


class KbTablesResponse(BaseModel):
    tables: List[KbTableOut]


class KbQueryRequest(_KbRequestBase):
    kb_id: str
    sql: str
    max_rows: int = _DEFAULT_MAX_ROWS


class KbReadTableRequest(_KbRequestBase):
    kb_id: str
    table: str
    limit: int = 100
    where: Optional[str] = None


class KbQueryResponse(BaseModel):
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    truncated: bool = False


# ── Helpers ────────────────────────────────────────────────────────────

async def _resolve_session(
    session_id: str,
    kb_id: Optional[str],
    db: AsyncSession,
) -> SandboxKbSession:
    """Verify the signed session token, enforce kb allowlist, and push
    the session's ``user_id`` into RLS context.
    """
    if not session_id:
        logger.info("Rejected KB request: empty session id")
        raise HTTPException(status_code=401, detail="Missing KB session")

    session = get_session(session_id)
    if session is None:
        # Keep logs informative without leaking the token.
        preview = (session_id[:6] + "…") if len(session_id) > 6 else "<short>"
        logger.info(
            "Rejected KB request: invalid signature or expired session (id=%s)",
            preview,
        )
        raise HTTPException(status_code=401, detail="Invalid or expired KB session")

    if kb_id is not None and kb_id not in session.kb_ids:
        logger.warning(
            "KB request rejected: kb_id=%s not in session allowlist (user=%s)",
            kb_id, session.user_id,
        )
        raise HTTPException(status_code=403, detail="kb_id is not authorized for this session")

    set_current_user_id(session.user_id)
    await set_user_context(db, session.user_id)
    return session


def _sanitize_identifier(name: str) -> Optional[str]:
    """Return ``name`` only if it's a plain identifier, else None.

    Belt-and-braces for the drag-drop / read_table path -- the generated
    SELECT is still validated by ``_validate_select_only``.
    """
    if not name:
        return None
    safe = "".join(ch for ch in str(name) if ch.isalnum() or ch == "_")
    return safe if safe and safe == str(name) else None


async def _ensure_kb_access(
    db: AsyncSession,
    kb_id: str,
    user_id: str,
) -> tuple[str, str]:
    """Verify the user can see this KB and return ``(schema_name, kb_name)``.

    RLS already restricts ``knowledge_base`` reads; this re-check surfaces
    an explicit 403 instead of a silent empty result.
    """
    kb_repo = KnowledgeBaseRepository(db)
    kb = await kb_repo.get_by_id(kb_id)
    if kb is None:
        logger.warning("KB %s not accessible to user %s", kb_id, user_id)
        raise HTTPException(status_code=403, detail="Knowledge base not accessible")

    schema_name = f"kb_data_{kb_id[:8]}"
    return schema_name, kb.name or kb_id


async def _build_table_metadata(
    db: AsyncSession,
    kb_ids: List[str],
) -> List[KbTableOut]:
    """Load structured table + column metadata for the given KBs.

    KBs hidden by RLS are silently skipped.
    """
    kb_repo = KnowledgeBaseRepository(db)
    structured_repo = StructuredDataRepository(db)

    out: List[KbTableOut] = []
    for kb_id in kb_ids:
        kb = await kb_repo.get_by_id(kb_id)
        if kb is None:
            continue
        try:
            tables = await structured_repo.get_tables_for_kb(kb_id)
        except Exception as exc:
            logger.warning("Failed to list tables for KB %s: %s", kb_id, exc)
            continue

        for t in tables:
            cols = [
                KbColumnOut(
                    name=c.column_name,
                    type=(
                        c.data_type.value
                        if hasattr(c.data_type, "value")
                        else str(c.data_type)
                    ),
                    description=c.description or None,
                    nullable=bool(c.nullable),
                )
                for c in (t.columns or [])
            ]
            out.append(
                KbTableOut(
                    kb_id=kb_id,
                    kb_name=kb.name or kb_id,
                    schema_name=t.schema_name,
                    table=t.table_name,
                    display_name=t.display_name or t.table_name,
                    description=t.description or None,
                    row_count=int(t.row_count or 0),
                    columns=cols,
                )
            )
    return out


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/tables", response_model=KbTablesResponse)
async def list_kb_tables(body: KbTablesRequest) -> KbTablesResponse:
    """Return table + column metadata for every KB in the session allowlist.

    Used by the sandbox SDK at runtime (there is no pre-injected metadata
    file in this model -- the SDK fetches on first ``list_tables()`` call
    and caches in process memory).
    """
    async for db in get_write_db():
        try:
            session = await _resolve_session(body.session_id, None, db)

            requested = body.kb_ids or session.kb_ids
            filtered = [k for k in requested if k in session.kb_ids]
            if not filtered:
                return KbTablesResponse(tables=[])

            tables = await _build_table_metadata(db, filtered)
            return KbTablesResponse(tables=tables)
        finally:
            clear_current_user_id()


@router.post("/query", response_model=KbQueryResponse)
async def run_kb_query(body: KbQueryRequest) -> KbQueryResponse:
    """Execute a single SELECT against the KB's structured-data schema."""
    if not _validate_select_only(body.sql):
        raise HTTPException(
            status_code=400,
            detail="Only single SELECT statements are allowed (no ';', comments, or DML/DDL)",
        )

    max_rows = max(1, min(int(body.max_rows or _DEFAULT_MAX_ROWS), _MAX_ROWS_CEILING))

    async for db in get_write_db():
        try:
            session = await _resolve_session(body.session_id, body.kb_id, db)
            schema_name, _kb_name = await _ensure_kb_access(db, body.kb_id, session.user_id)

            structured_repo = StructuredDataRepository(db)
            try:
                rows = await structured_repo.execute_query(
                    schema_name,
                    body.sql,
                    timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
                    max_rows=max_rows,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except Exception as exc:
                logger.warning(
                    "KB query failed (user=%s, kb=%s): %s",
                    session.user_id, body.kb_id, exc,
                )
                raise HTTPException(status_code=400, detail=f"Query failed: {exc}")

            columns: List[str] = list(rows[0].keys()) if rows else []
            values: List[List[Any]] = [list(r.values()) for r in rows]
            return KbQueryResponse(
                columns=columns,
                rows=values,
                row_count=len(values),
                truncated=len(values) >= max_rows,
            )
        finally:
            clear_current_user_id()


@router.post("/read_table", response_model=KbQueryResponse)
async def read_kb_table(body: KbReadTableRequest) -> KbQueryResponse:
    """Convenience path: ``SELECT * FROM "<table>" [WHERE ...] LIMIT <n>``."""
    table = _sanitize_identifier(body.table)
    if not table:
        raise HTTPException(status_code=400, detail="Invalid table name")

    limit = max(1, min(int(body.limit or 100), _MAX_ROWS_CEILING))

    where_clause = ""
    if body.where:
        probe = f"SELECT 1 WHERE {body.where}"
        if not _validate_select_only(probe):
            raise HTTPException(status_code=400, detail="Invalid WHERE clause")
        where_clause = f" WHERE {body.where}"

    sql = f'SELECT * FROM "{table}"{where_clause}'

    async for db in get_write_db():
        try:
            session = await _resolve_session(body.session_id, body.kb_id, db)
            schema_name, _kb_name = await _ensure_kb_access(db, body.kb_id, session.user_id)

            structured_repo = StructuredDataRepository(db)
            try:
                rows = await structured_repo.execute_query(
                    schema_name,
                    sql,
                    timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
                    max_rows=limit,
                )
            except Exception as exc:
                logger.warning(
                    "KB read_table failed (user=%s, kb=%s, table=%s): %s",
                    session.user_id, body.kb_id, table, exc,
                )
                raise HTTPException(status_code=400, detail=f"read_table failed: {exc}")

            columns: List[str] = list(rows[0].keys()) if rows else []
            values: List[List[Any]] = [list(r.values()) for r in rows]
            return KbQueryResponse(
                columns=columns,
                rows=values,
                row_count=len(values),
                truncated=len(values) >= limit,
            )
        finally:
            clear_current_user_id()
