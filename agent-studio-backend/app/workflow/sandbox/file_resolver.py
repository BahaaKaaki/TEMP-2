"""
Resolve files from the chat session (Azure Blob) and upstream node outputs
so they can be injected into a sandbox at /workspace/uploads/.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


async def resolve_session_files(
    session_id: str | None,
) -> List[Tuple[str, bytes]]:
    """Download all files attached to *session_id* from Azure Blob.

    Returns a list of ``(filename, content_bytes)`` tuples.
    """
    if not session_id:
        return []

    try:
        from db.pgsql import PrimarySessionLocal
        from repositories import FileRepository
        from connectors import AzureStorageConnector
        from config.keyvault import cfg

        async with PrimarySessionLocal() as db:
            repo = FileRepository(db)
            files = await repo.get_by_session_id(session_id)
            if not files:
                return []

            use_mi = getattr(cfg, "AZURE_STORAGE_USE_MANAGED_IDENTITY", False)
            container_name = getattr(cfg, "AZURE_STORAGE_CONTAINER_NAME", "")

            if use_mi:
                storage = AzureStorageConnector(
                    container_name=container_name,
                    account_name=getattr(cfg, "AZURE_STORAGE_ACCOUNT_NAME", ""),
                    use_managed_identity=True,
                    managed_identity_client_id=getattr(cfg, "AZURE_CLIENT_ID_ADSLGEN2", ""),
                )
            else:
                conn_str = getattr(
                    cfg,
                    "AZURE_STORAGE_CONNECTION_STRING",
                    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
                    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
                    "K1SZFPTOtr/KBHBeksoGMGw==;"
                    "BlobEndpoint=http://localhost:10000/devstoreaccount1;",
                )
                storage = AzureStorageConnector(
                    container_name=container_name,
                    connection_string=conn_str,
                )

            await storage.initialize()

            results: List[Tuple[str, bytes]] = []
            for f in files:
                if not f.blob_name:
                    continue
                try:
                    sas_url = await storage.generate_scoped_sas(
                        f.blob_name, permissions="r", expiry_minutes=15,
                    )
                    data = await storage.download_blob(f.blob_name)
                    results.append((f.file_name, data))
                    logger.debug(
                        "Downloaded session file %s via scoped SAS (%d bytes)",
                        f.file_name, len(data),
                    )
                except Exception:
                    logger.warning("Failed to download session file %s", f.file_name, exc_info=True)

            return results

    except Exception:
        logger.warning("Could not resolve session files for %s", session_id, exc_info=True)
        return []


def resolve_upstream_output_files(
    state: Dict[str, Any],
    current_node_id: str,
) -> List[Tuple[str, str]]:
    """Collect file paths from upstream code-executor node outputs.

    Returns a list of ``(filename, local_path)`` tuples.
    """
    results: List[Tuple[str, str]] = []
    node_outputs = state.get("node_outputs", {})

    for nid, nout in node_outputs.items():
        if nid == current_node_id:
            continue
        if not isinstance(nout, dict):
            continue
        exec_result = nout.get("execution_result", {})
        if not isinstance(exec_result, dict):
            continue
        for fpath in exec_result.get("output_files", []):
            if isinstance(fpath, str) and os.path.isfile(fpath):
                results.append((os.path.basename(fpath), fpath))

    deliverables = state.get("deliverables", [])
    for d in deliverables:
        deliv = d.get("deliverable", {})
        if not isinstance(deliv, dict):
            continue
        for frec in deliv.get("_output_files", []):
            if isinstance(frec, dict) and "name" in frec:
                local = frec.get("local_path") or frec.get("sandbox_path", "")
                if local and os.path.isfile(local):
                    results.append((frec["name"], local))

    return results
