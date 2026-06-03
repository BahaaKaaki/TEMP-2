"""
Active-agent resolution for chat uploads (service layer).

Pure file-scope rules live in ``workflow.utils.file_scope`` to avoid circular
imports between workflow nodes and services/repositories.
"""
from dataclasses import dataclass
from typing import Optional
import logging

from repositories import ExecutionRepository, WorkflowRepository
from workflow.utils.file_scope import (
    first_agent_node,
    label_for_agent,
    _label_for_node,
)

logger = logging.getLogger(__name__)

DEFAULT_FILE_SCOPE = "local"


@dataclass
class ActiveAgent:
    agent_id: Optional[str]
    agent_label: Optional[str]


async def resolve_active_agent(
    session_id: str,
    workflow_id: str,
    execution_repo: ExecutionRepository,
    workflow_repo: WorkflowRepository,
    *,
    user_id: Optional[str] = None,
) -> ActiveAgent:
    """Resolve the agent the chat is currently talking to in a session."""
    workflow = await workflow_repo.get_effective_by_id(workflow_id, user_id=user_id)

    try:
        latest_exec = await execution_repo.get_latest_by_session(session_id)
    except Exception as e:
        logger.warning("file_scope: failed to load latest execution: %s", e)
        latest_exec = None

    if latest_exec:
        try:
            state = await execution_repo.get_execution_data(latest_exec.id)
        except Exception as e:
            logger.warning("file_scope: failed to load execution state: %s", e)
            state = None

        if state:
            current_id = state.get("current_agent_id")
            if current_id:
                return ActiveAgent(
                    agent_id=current_id,
                    agent_label=label_for_agent(workflow, current_id),
                )

            messages = state.get("messages", []) or []
            for msg in reversed(messages):
                kwargs = getattr(msg, "additional_kwargs", None) or {}
                if not isinstance(kwargs, dict):
                    continue
                agent_id = kwargs.get("agent_id")
                if not agent_id:
                    continue
                return ActiveAgent(
                    agent_id=agent_id,
                    agent_label=(
                        kwargs.get("agent_label")
                        or label_for_agent(workflow, agent_id)
                    ),
                )

    if workflow:
        first = first_agent_node(workflow)
        if first:
            return ActiveAgent(
                agent_id=first.get("id"),
                agent_label=_label_for_node(first),
            )

    return ActiveAgent(agent_id=None, agent_label=None)
