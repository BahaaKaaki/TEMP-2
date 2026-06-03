"""
Knowledge Base client for the agent_studio sandbox SDK.

Security model
--------------
This module never reads or writes anything under ``/workspace``.  The host
injects up to three values as **environment variables** right before the
user script launches:

* ``AGENT_STUDIO_KB_URL``         — base URL of the host's callback API
* ``AGENT_STUDIO_KB_SESSION``     — opaque, per-run session id
* ``AGENT_STUDIO_KB_PRIVATE_IP``  — optional; private IP to resolve the
  callback URL's hostname to when public DNS returns a non-routable
  address (ACA internal env via Private Endpoint, etc.). The process-local
  DNS override is installed on ``socket.getaddrinfo`` only; nothing is
  written to ``/etc/hosts`` and no other hostname is affected.

All three values are read **exactly once** at module import time and
immediately popped from ``os.environ`` so that user code doing
``os.environ.get("AGENT_STUDIO_KB_SESSION")`` or ``print(os.environ)``
sees nothing.

The session id is not a signed token: it's a lookup key in the host's
in-memory session registry.  The host maps it back to the authenticated
user and a KB allowlist, enforces Row-Level Security at the database
session level, and revokes the entry the moment the run finishes.  Any
session id that leaks (e.g. printed by user code) becomes useless as
soon as ``revoke_session`` runs — typically within a second of the last
SELECT.

All SELECTs are further validated server-side (no semicolons, no
comments, no DDL/DML, no INSERT/UPDATE/DELETE) and capped at 10 000
rows / 30 s.

Typical usage::

    from agent_studio import knowledge_base as kb

    for t in kb.list_tables():
        print(t["kb_name"], t["table"])

    df = kb.read_table("customers", limit=100)
    df = kb.read_table("orders", limit=500, where="status = 'paid'")

    df = kb.query("SELECT COUNT(*) AS n FROM customers", kb_id="<id>")

``read_table`` / ``query`` return a pandas DataFrame when pandas is
available and a list of dicts otherwise (so the SDK still imports on
trimmed-down images).
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit


# ── Load & scrub credentials at import time ────────────────────────────

# ``pop`` so a subsequent ``os.environ.get(...)`` / ``printenv`` from
# user code sees nothing.  We hold the values in module-level locals
# that aren't accessible without introspecting the module (which we
# can't prevent, but at least nothing leaks via the obvious channel).
_KB_URL: Optional[str] = os.environ.pop("AGENT_STUDIO_KB_URL", None)
_KB_SESSION: Optional[str] = os.environ.pop("AGENT_STUDIO_KB_SESSION", None)
_KB_PRIVATE_IP: Optional[str] = os.environ.pop("AGENT_STUDIO_KB_PRIVATE_IP", None)


# ── Private Endpoint DNS override (no /etc/hosts, no shell out) ─────────
#
# In ACA internal environments the backend's callback URL may resolve via
# public DNS to a non-routable address (the env's public "virtual" IP).
# When the host deploys us with ``AGENT_STUDIO_KB_PRIVATE_IP`` set, we
# force urllib + TLS to connect to that IP while still preserving the
# URL's hostname for SNI and the Host header.  The override is scoped to
# this Python process (only ``socket.getaddrinfo`` is patched) and only
# affects the exact hostname embedded in ``AGENT_STUDIO_KB_URL`` — every
# other DNS lookup (e.g. pip, user code hitting PyPI) works normally.


def _install_private_ip_override() -> None:
    if not _KB_URL or not _KB_PRIVATE_IP:
        return
    try:
        target_host = urlsplit(_KB_URL).hostname
    except Exception:
        return
    if not target_host:
        return

    _orig_getaddrinfo = socket.getaddrinfo
    pinned_host = target_host
    pinned_ip = _KB_PRIVATE_IP

    def _patched_getaddrinfo(host, *args, **kwargs):
        if host == pinned_host:
            return _orig_getaddrinfo(pinned_ip, *args, **kwargs)
        return _orig_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = _patched_getaddrinfo


_install_private_ip_override()


class KnowledgeBaseError(RuntimeError):
    """Raised when a KB call fails (no KBs configured, HTTP error, etc.)."""


# ── Internal HTTP layer ────────────────────────────────────────────────

_MISSING_CONFIG_MSG = (
    "No Knowledge Base is configured on this Code Executor node. "
    "Select one or more KBs in the node configuration to use "
    "agent_studio.knowledge_base."
)


def _require_credentials() -> tuple[str, str]:
    if not _KB_URL or not _KB_SESSION:
        raise KnowledgeBaseError(_MISSING_CONFIG_MSG)
    return _KB_URL, _KB_SESSION


def _post_json(
    url_path: str,
    payload: Dict[str, Any],
    *,
    timeout: int = 60,
) -> Dict[str, Any]:
    """POST JSON to the host KB endpoints and parse the response."""
    import urllib.error
    import urllib.request

    base, session_id = _require_credentials()
    url = f"{base.rstrip('/')}{url_path}"

    body = {"session_id": session_id, **payload}
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ssl_ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        detail = err_body
        try:
            parsed = json.loads(err_body)
            if isinstance(parsed, dict) and "detail" in parsed:
                detail = str(parsed["detail"])
        except Exception:
            pass
        raise KnowledgeBaseError(
            f"KB request failed ({exc.code}): {detail[:500]}"
        ) from exc
    except Exception as exc:
        raise KnowledgeBaseError(f"KB request error: {exc}") from exc


# ── Lazy metadata cache ────────────────────────────────────────────────

_META_LOCK = threading.Lock()
_META_CACHE: Optional[List[Dict[str, Any]]] = None


def _tables_metadata(*, refresh: bool = False) -> List[Dict[str, Any]]:
    """Fetch and cache the table list from the host.

    One HTTP call on first use; subsequent ``list_tables`` / ``read_table``
    / ``describe`` reuse the in-process cache.  Callers can pass
    ``refresh=True`` to bypass.
    """
    global _META_CACHE
    with _META_LOCK:
        if _META_CACHE is not None and not refresh:
            return _META_CACHE
        resp = _post_json("/api/code-executor/kb/tables", {})
        tables = list(resp.get("tables") or [])
        _META_CACHE = tables
        return tables


def _resolve_kb_for_table(
    table: str,
    kb_id: Optional[str],
    meta: List[Dict[str, Any]],
) -> str:
    """Find the KB that owns ``table``; disambiguate via ``kb_id`` if needed."""
    candidates = [
        t for t in meta
        if t.get("table") == table and (kb_id is None or t.get("kb_id") == kb_id)
    ]
    if not candidates:
        raise KnowledgeBaseError(
            f"Table '{table}' is not available"
            + (f" in KB {kb_id}" if kb_id else "")
            + ". Use knowledge_base.list_tables() to see available tables."
        )

    distinct_kbs = {t.get("kb_id") for t in candidates}
    if len(distinct_kbs) > 1:
        names = ", ".join(sorted(str(k) for k in distinct_kbs))
        raise KnowledgeBaseError(
            f"Table '{table}' exists in multiple KBs ({names}). "
            f"Pass kb_id=... to disambiguate."
        )
    return candidates[0]["kb_id"]


def _rows_to_df(columns: List[str], rows: List[List[Any]]):
    """Return a pandas DataFrame when available, else a list of dicts."""
    try:
        import pandas as pd  # type: ignore

        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows, columns=columns)
    except Exception:
        return [dict(zip(columns, r)) for r in rows]


# ── Public API ──────────────────────────────────────────────────────────

class _KnowledgeBase:
    """Read-only client for structured tables attached to selected KBs."""

    # ---- Discovery ---------------------------------------------------

    @staticmethod
    def list_tables(
        kb_id: Optional[str] = None,
        *,
        refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return every table available to this node.

        Each entry contains ``kb_id``, ``kb_name``, ``schema_name``,
        ``table``, ``display_name``, ``description``, ``row_count``, and
        ``columns`` (list of ``{name, type, description, nullable}``).

        Args:
            kb_id: If provided, restrict the list to one KB.
            refresh: If True, re-query the host instead of using the
                     in-process cache.
        """
        meta = _tables_metadata(refresh=refresh)
        return [t for t in meta if kb_id is None or t.get("kb_id") == kb_id]

    @staticmethod
    def describe(table: str, kb_id: Optional[str] = None) -> Dict[str, Any]:
        """Return the metadata for a single table."""
        meta = _tables_metadata()
        resolved_kb = _resolve_kb_for_table(table, kb_id, meta)
        for t in meta:
            if t.get("table") == table and t.get("kb_id") == resolved_kb:
                return t
        raise KnowledgeBaseError(f"Table '{table}' not found")

    # ---- Data access -------------------------------------------------

    @staticmethod
    def read_table(
        table: str,
        *,
        limit: int = 100,
        where: Optional[str] = None,
        kb_id: Optional[str] = None,
    ):
        """Read rows from ``table`` as a pandas DataFrame.

        Equivalent to ``SELECT * FROM table [WHERE ...] LIMIT limit``.
        The host enforces a hard ceiling on ``limit`` (10 000 rows) and
        rejects anything that isn't a pure SELECT.
        """
        meta = _tables_metadata()
        resolved_kb = _resolve_kb_for_table(table, kb_id, meta)

        payload: Dict[str, Any] = {
            "kb_id": resolved_kb,
            "table": table,
            "limit": int(limit),
        }
        if where:
            payload["where"] = where

        resp = _post_json("/api/code-executor/kb/read_table", payload)
        columns = list(resp.get("columns") or [])
        rows = list(resp.get("rows") or [])
        return _rows_to_df(columns, rows)

    @staticmethod
    def query(
        sql: str,
        *,
        kb_id: str,
        max_rows: int = 1000,
    ):
        """Run an arbitrary SELECT against one KB's schema.

        The SQL must be a single SELECT -- no semicolons, comments, or
        DDL/DML. The host runs it with ``search_path`` set to the KB's
        per-user schema and caps results at ``max_rows`` (hard ceiling
        of 10 000).
        """
        if not sql or not isinstance(sql, str):
            raise KnowledgeBaseError("sql must be a non-empty string")
        if not kb_id:
            raise KnowledgeBaseError(
                "kb_id is required for knowledge_base.query(); use "
                "read_table() if you just want SELECT * FROM one table."
            )

        payload = {"kb_id": str(kb_id), "sql": sql, "max_rows": int(max_rows)}
        resp = _post_json("/api/code-executor/kb/query", payload)
        columns = list(resp.get("columns") or [])
        rows = list(resp.get("rows") or [])
        return _rows_to_df(columns, rows)

    @staticmethod
    def query_df(sql: str, *, kb_id: str, max_rows: int = 1000):
        """Alias of :meth:`query` for users who prefer explicit naming."""
        return _KnowledgeBase.query(sql, kb_id=kb_id, max_rows=max_rows)


knowledge_base = _KnowledgeBase()
