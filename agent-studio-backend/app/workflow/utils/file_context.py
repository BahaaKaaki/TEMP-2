"""
Uploaded file context injection for agents.

Receiving-agent ``fileScope`` controls which session files are visible.
Injection is split to avoid duplicating content in one turn:

- **User message** (chat send): files stamped to the current agent.
- **System prompt** (workflow): files from other agents / legacy unstamped rows.
"""
from typing import Iterable, List, Optional
import logging

from utils.text_truncation import smart_truncate_for_llm
from config.settings import settings
from domain.entities import File, Workflow
from .file_scope import (
    filter_files_for_agent,
    get_node_config_for_agent,
    partition_files_for_injection,
    resolve_allowed_upload_agent_ids,
)

logger = logging.getLogger(__name__)


def format_file_block(
    files: Iterable[File],
    *,
    header_title: str = "UPLOADED DOCUMENTS",
) -> str:
    """Format files as a prompt block. Returns ``""`` when empty."""
    file_list = [f for f in files if f is not None]
    if not file_list:
        return ""

    parts: List[str] = [
        "\n\n" + "=" * 80 + "\n",
        f"📁 {header_title}\n",
        "=" * 80 + "\n\n",
    ]
    for f in file_list:
        try:
            size_kb = f.get_size_kb()
        except Exception:
            size_kb = 0.0

        parts.append(f"**File: {f.file_name}** ({size_kb:.1f} KB)\n")
        parts.append(f"Type: {f.file_type}\n")
        label = getattr(f, "uploaded_at_agent_label", None)
        if label:
            parts.append(f"Uploaded at: {label}\n")
        parts.append("-" * 80 + "\n")

        if f.has_extracted_text():
            text_content = smart_truncate_for_llm(
                f.extracted_text,
                max_length=settings.FILE_CONTENT_MAX_LENGTH,
                keep_start=True,
                keep_end=False,
            )
            parts.append(f"{text_content}\n")
        else:
            parts.append("[No text content extracted]\n")

        parts.append("=" * 80 + "\n\n")

    parts.append("END OF UPLOADED DOCUMENTS\n")
    parts.append("=" * 80 + "\n")
    return "".join(parts)


def format_global_file_block(files: Iterable[File]) -> str:
    """Backward-compatible alias for system-prompt file blocks."""
    return format_file_block(
        files,
        header_title="UPLOADED DOCUMENTS (from previous steps)",
    )


async def _load_parsed_session_files(
    session_id: str,
    file_repo=None,
) -> List[File]:
    if file_repo is not None:
        return await file_repo.get_parsed_files_by_session(session_id)

    try:
        from db.pgsql import PrimarySessionLocal  # type: ignore
        from repositories import FileRepository  # type: ignore
    except Exception as e:
        logger.warning("file_scope: cannot import DB session/repo: %s", e)
        return []

    try:
        async with PrimarySessionLocal() as db:
            repo = FileRepository(db)
            return await repo.get_parsed_files_by_session(session_id)
    except Exception as e:
        logger.warning(
            "file_scope: failed to load session files for %s: %s",
            session_id,
            e,
        )
        return []


async def _load_workflow(workflow_id: Optional[str]) -> Optional[Workflow]:
    if not workflow_id:
        return None
    try:
        from db.pgsql import PrimarySessionLocal  # type: ignore
        from repositories import WorkflowRepository  # type: ignore
    except Exception as e:
        logger.warning("file_scope: cannot import workflow repo: %s", e)
        return None

    try:
        async with PrimarySessionLocal() as db:
            repo = WorkflowRepository(db)
            return await repo.get_effective_by_id(workflow_id)
    except Exception as e:
        logger.warning("file_scope: failed to load workflow %s: %s", workflow_id, e)
        return None


async def build_agent_file_context(
    session_id: Optional[str],
    current_agent_id: str,
    node_config: dict,
    *,
    for_system: bool,
    workflow: Optional[Workflow] = None,
    workflow_id: Optional[str] = None,
    file_repo=None,
) -> str:
    """
    Build a file context block for the receiving agent.

    ``for_system=True`` → files from other steps; ``False`` → this agent's uploads.
    """
    if not session_id or not current_agent_id:
        return ""

    if workflow is None and workflow_id:
        workflow = await _load_workflow(workflow_id)

    allowed, mode = resolve_allowed_upload_agent_ids(
        workflow, current_agent_id, node_config or {},
    )

    all_files = await _load_parsed_session_files(session_id, file_repo=file_repo)
    visible = filter_files_for_agent(all_files, allowed, mode)
    own, other = partition_files_for_injection(visible, current_agent_id)

    logger.debug(
        "file_scope: agent=%s mode=%s allowed_agents=%s visible=%d own=%d other=%d",
        current_agent_id,
        mode,
        sorted(allowed),
        len(visible),
        len(own),
        len(other),
    )

    if for_system:
        return format_global_file_block(other)

    return format_file_block(own, header_title="UPLOADED DOCUMENTS - CONTEXT")


async def build_global_file_context(
    session_id: Optional[str],
    file_repo=None,
    *,
    current_agent_id: Optional[str] = None,
    node_config: Optional[dict] = None,
    workflow: Optional[Workflow] = None,
    workflow_id: Optional[str] = None,
) -> str:
    """
    Load file context for workflow system prompts.

    When ``current_agent_id`` and ``node_config`` are provided, uses receiving-agent
    rules. Otherwise falls back to legacy global-scope DB rows (backward compat).
    """
    if session_id and current_agent_id:
        return await build_agent_file_context(
            session_id,
            current_agent_id,
            node_config or {},
            for_system=True,
            workflow=workflow,
            workflow_id=workflow_id,
            file_repo=file_repo,
        )

    if file_repo is not None:
        try:
            files = await file_repo.get_global_files_by_session(session_id)
        except Exception as e:
            logger.warning(
                "file_scope: legacy global file load failed for %s: %s",
                session_id,
                e,
            )
            return ""
        return format_global_file_block(files)

    try:
        from db.pgsql import PrimarySessionLocal  # type: ignore
        from repositories import FileRepository  # type: ignore
    except Exception as e:
        logger.warning("file_scope: cannot import DB session/repo: %s", e)
        return ""

    try:
        async with PrimarySessionLocal() as db:
            repo = FileRepository(db)
            files = await repo.get_global_files_by_session(session_id)
    except Exception as e:
        logger.warning(
            "file_scope: legacy global file load failed for %s: %s",
            session_id,
            e,
        )
        return ""

    return format_global_file_block(files)
