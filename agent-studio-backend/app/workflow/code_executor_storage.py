"""ADLS-backed storage facade for the Code Executor node.

Two kinds of artefacts are stored here, both in the same Azure Blob
container the rest of the application already uses
(:data:`cfg.AZURE_STORAGE_CONTAINER_NAME`), under dedicated prefixes:

``code-executor/midway-uploads/<user_id>/<upload_id>/<filename>``
    Files uploaded by the end-user in response to ``output.ask(type='file')``
    while a Code Executor script is paused.  Previously these were written
    to the backend pod's local disk (``sandbox_midway_uploads/``), which is
    ephemeral on ACA and not shared across replicas — pod restarts or
    replicas-other-than-the-one-that-handled-the-upload would lose the file
    and fail the resume with ``FileNotFoundError``.

``code-executor/checkpoints/<user_id>/<execution_id>/pause_<pause_index>.pkl``
    Cloudpickle blobs produced at pause time so the sandbox can resume from
    a fresh container without re-executing the pre-pause code.  Previously
    stored base64-encoded inside ``execution_data.data`` (the whole
    WorkflowState JSON), which meant every single ``_save_state_to_db``
    rewrote the fat blob alongside messages/node outputs, bloating WAL and
    replication lag.

Security model
--------------

* **Authentication**: reuses the application-wide ``AzureStorageConnector``
  (``get_azure_storage_connector``), which is already wired up with a
  User-Assigned Managed Identity in production (``AZURE_CLIENT_ID_ADSLGEN2``)
  and Azurite in local dev.  No new credentials or infra.
* **Path scoping**: every blob path embeds the owning ``user_id`` as the
  first path segment.  Even if another bug surfaced a blob name, it'd be
  self-describing which tenant owns it and any downstream ACL/audit rule
  has a clean anchor.
* **No public exposure**: checkpoint blobs are only ever read by the backend
  itself (and then streamed as bytes into the sandbox over the Docker/ACI
  exec API).  Midway upload blobs are the same — the sandbox never sees a
  URL, just the raw bytes the backend has already authenticated and pulled.
  We therefore do *not* mint SAS URLs; the blob is auth-only.
* **TTL**: terminal workflow transitions (``completed``/``failed``/
  ``cancelled``) trigger :func:`cleanup_run` which prefix-deletes everything
  for that ``execution_id``.  A daily sweeper (cron-style) on a longer
  window can be added later if orphans become a problem.

All functions are best-effort with logged failures.  The consuming code
falls back to legacy in-Postgres / on-disk behaviour when a blob read
returns ``None`` so an in-flight pause at deploy time doesn't break.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


# Top-level prefix under the shared blob container.  Kept as a module
# constant so tests / cleanup tools can discover the namespace.
_PREFIX_ROOT = "code-executor"
_MIDWAY_PREFIX = f"{_PREFIX_ROOT}/midway-uploads"
_CHECKPOINT_PREFIX = f"{_PREFIX_ROOT}/checkpoints"


# ─── Safety helpers ────────────────────────────────────────────────────

# Azure blob names are permissive (pretty much any UTF-8), but we still
# scrub input to keep paths predictable and avoid accidental traversal
# (``../``) or empty-segment quirks.  Anything not matching the allowed
# set collapses to ``_``.
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._\-]+")


def _sanitize_segment(segment: str, *, fallback: str) -> str:
    """Return a filesystem-ish safe version of a single path segment."""
    if not segment:
        return fallback
    cleaned = _SAFE_SEGMENT_RE.sub("_", segment).strip("._-")
    return cleaned or fallback


def _sanitize_filename(filename: str) -> str:
    """Keep the extension; scrub the rest.

    FastAPI already gives us ``os.path.basename(file.filename)`` at the
    route layer so we don't need to re-defend against directory traversal,
    but we still normalise weird characters for nicer audit logs.
    """
    if not filename:
        return "upload"
    base = os.path.basename(filename)
    # Preserve the final extension verbatim (lowercase it), sanitize the
    # stem — this matters for pandas / magic-based file-type detection in
    # the user's own code.
    stem, dot, ext = base.rpartition(".")
    if dot:
        safe_stem = _sanitize_segment(stem, fallback="upload")
        safe_ext = _sanitize_segment(ext.lower(), fallback="bin")
        return f"{safe_stem}.{safe_ext}"
    return _sanitize_segment(base, fallback="upload")


# ─── Path builders ─────────────────────────────────────────────────────

def midway_blob_name(user_id: str, upload_id: str, filename: str) -> str:
    """Canonical blob path for a midway upload."""
    return (
        f"{_MIDWAY_PREFIX}/"
        f"{_sanitize_segment(str(user_id), fallback='anon')}/"
        f"{_sanitize_segment(str(upload_id), fallback='upload')}/"
        f"{_sanitize_filename(filename)}"
    )


def checkpoint_blob_name(user_id: str, execution_id: str, pause_index: int) -> str:
    """Canonical blob path for a pause checkpoint."""
    return (
        f"{_CHECKPOINT_PREFIX}/"
        f"{_sanitize_segment(str(user_id), fallback='anon')}/"
        f"{_sanitize_segment(str(execution_id), fallback='exec')}/"
        f"pause_{int(pause_index)}.pkl"
    )


def run_artefact_prefixes(user_id: str, execution_id: str) -> List[str]:
    """Every prefix owned by a single workflow run — used by cleanup.

    Midway upload blobs are keyed by ``upload_id`` (not ``execution_id``)
    so we *cannot* prefix-delete them here; ``cleanup_run`` enumerates
    them via the ``pause_file_map`` instead.  Checkpoints, however, are
    cleanly scoped by execution_id and get a prefix entry.
    """
    safe_user = _sanitize_segment(str(user_id), fallback="anon")
    safe_exec = _sanitize_segment(str(execution_id), fallback="exec")
    return [f"{_CHECKPOINT_PREFIX}/{safe_user}/{safe_exec}/"]


# ─── Storage accessors ─────────────────────────────────────────────────

def _get_connector():
    """Return the shared :class:`AzureStorageConnector` or ``None`` if it
    hasn't been initialised (local dev without Azurite, tests, …).

    We deliberately return ``None`` instead of raising so callers can
    degrade gracefully.  Upload paths log a warning; read paths fall back
    to the legacy in-Postgres / on-disk lookup.
    """
    try:
        from core.dependencies import get_azure_storage_connector
        return get_azure_storage_connector()
    except Exception as exc:  # noqa: BLE001 — startup ordering issues, etc.
        logger.warning("Azure Storage connector unavailable: %s", exc)
        return None


# ─── Midway uploads ────────────────────────────────────────────────────

async def upload_midway(
    *,
    user_id: str,
    upload_id: str,
    filename: str,
    data: bytes,
    content_type: Optional[str] = None,
) -> Optional[str]:
    """Upload a midway file to ADLS and return its blob name.

    Returns the blob name on success, ``None`` if storage is unavailable
    (caller should surface an error to the UI in that case — we don't
    silently drop user uploads).
    """
    connector = _get_connector()
    if connector is None:
        return None

    blob_name = midway_blob_name(user_id, upload_id, filename)
    try:
        await connector.upload_blob(
            blob_name=blob_name,
            data=data,
            content_type=content_type or "application/octet-stream",
            metadata={
                "user_id": str(user_id),
                "upload_id": str(upload_id),
                "kind": "midway_upload",
            },
            overwrite=True,
        )
        logger.info(
            "Midway upload stored in blob %s (%d bytes)", blob_name, len(data),
        )
        return blob_name
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to upload midway file %s: %s", blob_name, exc)
        return None


async def download_midway(blob_name: str) -> Optional[bytes]:
    """Download a previously-uploaded midway file.  Returns ``None`` on
    missing/permission error so the injector can skip it with a warning
    instead of blowing up the whole resume."""
    if not blob_name:
        return None
    connector = _get_connector()
    if connector is None:
        return None
    try:
        return await connector.download_blob(blob_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to download midway blob %s: %s", blob_name, exc)
        return None


async def delete_midway(blob_name: str) -> None:
    """Best-effort delete of a single midway blob (used on terminal cleanup)."""
    if not blob_name:
        return
    connector = _get_connector()
    if connector is None:
        return
    try:
        await connector.delete_blob(blob_name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Midway blob delete skipped for %s: %s", blob_name, exc)


# ─── Checkpoints ───────────────────────────────────────────────────────

async def save_checkpoint(
    *,
    user_id: str,
    execution_id: str,
    pause_index: int,
    data: bytes,
) -> Optional[str]:
    """Upload a pickled checkpoint and return the blob name.

    Returns ``None`` on failure; the caller can choose whether to fall back
    to the legacy in-Postgres base64 path or to error out.
    """
    if not data:
        return None
    connector = _get_connector()
    if connector is None:
        return None

    blob_name = checkpoint_blob_name(user_id, execution_id, pause_index)
    try:
        await connector.upload_blob(
            blob_name=blob_name,
            data=data,
            content_type="application/octet-stream",
            metadata={
                "user_id": str(user_id),
                "execution_id": str(execution_id),
                "pause_index": str(pause_index),
                "kind": "checkpoint",
            },
            overwrite=True,
        )
        logger.info(
            "Checkpoint stored in blob %s (%d bytes)", blob_name, len(data),
        )
        return blob_name
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to upload checkpoint %s: %s", blob_name, exc)
        return None


async def load_checkpoint(blob_name: str) -> Optional[bytes]:
    """Download a checkpoint blob.  Returns ``None`` if missing."""
    if not blob_name:
        return None
    connector = _get_connector()
    if connector is None:
        return None
    try:
        return await connector.download_blob(blob_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to download checkpoint %s: %s", blob_name, exc)
        return None


# ─── Terminal cleanup ──────────────────────────────────────────────────

async def cleanup_run(
    *,
    user_id: str,
    execution_id: str,
    midway_blob_names: Optional[List[str]] = None,
) -> None:
    """Prefix-delete this run's checkpoints and delete each midway blob.

    Called from :meth:`WorkflowExecutor._update_execution_record` on
    ``completed``/``failed``/``cancelled`` transitions.  Safe to call
    multiple times — every sub-operation is best-effort and a missing
    blob is a no-op.
    """
    connector = _get_connector()
    if connector is None:
        return

    # Checkpoints: prefix-delete.
    for prefix in run_artefact_prefixes(user_id, execution_id):
        try:
            blobs = await connector.list_blobs(prefix=prefix)
            for b in blobs:
                try:
                    await connector.delete_blob(b.name)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Checkpoint delete skipped for %s: %s", b.name, exc)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Checkpoint prefix list skipped for %s: %s", prefix, exc)

    # Midway files: delete exactly what the state recorded.
    for name in midway_blob_names or []:
        await delete_midway(name)
