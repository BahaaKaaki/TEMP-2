"""
PowerPoint Generator node — Edwin handoff.

Collects upstream deliverables (per ``deliverableSources``), formats them as
markdown, creates an Edwin handoff session, and returns the Edwin URL for the
frontend to open automatically.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from .base import BaseNode
from ..state import (
    WorkflowState,
    resolve_deliverable_sources,
    format_deliverables_as_markdown,
)

logger = logging.getLogger(__name__)

EDWIN_QUESTION = "Create a presentation from the workflow outputs below."
EDWIN_SUGGESTED_PROMPT = "Create a presentation from the workflow analysis above."
EDWIN_READY_MESSAGE = "Continue your powerpoint presentation in Edwin"


class PowerpointGeneratorNode(BaseNode):
    """Send workflow deliverables to Edwin and return a handoff URL."""

    def _make_status_message(
        self,
        text: str,
        *,
        edwin_url: str = "",
        edwin_handoff_id: str = "",
    ) -> AIMessage:
        kwargs: Dict[str, Any] = {
            "message_id": str(uuid.uuid4()),
            "agent_id": self.node_id,
            "agent_label": self.label,
            "agent_type": "powerpoint-generator",
            "timestamp": datetime.utcnow().isoformat(),
            "hide_deliverable": True,
        }
        if edwin_url:
            kwargs["edwin_url"] = edwin_url
        if edwin_handoff_id:
            kwargs["edwin_handoff_id"] = edwin_handoff_id
        return AIMessage(content=text, additional_kwargs=kwargs)

    def _error(self, message: str) -> Dict[str, Any]:
        logger.error("PowerPoint generator %s: %s", self.label, message)
        deliverable_data = {
            "_output_type": "error",
            "_metadata": {"title": "PowerPoint Generator Error"},
            "error": message,
        }
        deliverable_entry = {
            "deliverable_id": str(uuid.uuid4()),
            "agent_id": self.node_id,
            "agent_label": self.label,
            "agent_type": "powerpoint-generator",
            "deliverable": deliverable_data,
            "output_type": "error",
            "interactive": False,
            "status": "approved",
            "iteration": 1,
            "created_at": datetime.utcnow().isoformat(),
        }
        return {
            "error": message,
            "has_deliverable": False,
            "deliverables": [deliverable_entry],
            "messages": [
                self._make_status_message(f"PowerPoint generation failed: {message}")
            ],
        }

    async def execute(self, state: WorkflowState) -> Dict[str, Any]:
        config = self.node_config or {}
        deliverables = resolve_deliverable_sources(
            state, self.node_id, config
        )
        if not deliverables:
            return self._error(
                "No upstream deliverables available for the configured sources."
            )

        markdown = format_deliverables_as_markdown(deliverables)
        if not markdown.strip():
            return self._error("Deliverables could not be formatted for Edwin.")

        # Lazy import avoids circular import: repositories → workflow.nodes → services → repositories
        from services.edwin_handoff_service import EdwinHandoffError, create_handoff

        try:
            handoff = await create_handoff(
                question=EDWIN_QUESTION,
                answer=markdown,
                suggested_prompt=EDWIN_SUGGESTED_PROMPT,
            )
        except EdwinHandoffError as exc:
            return self._error(str(exc))

        handoff_id = handoff.get("id", "")
        handoff_url = handoff.get("url", "")
        preview = markdown[:2000] + ("…" if len(markdown) > 2000 else "")

        deliverable_data = {
            "_output_type": "edwin_handoff",
            "_metadata": {"title": "Edwin presentation"},
            "edwin_handoff_id": handoff_id,
            "edwin_url": handoff_url,
            "markdown_preview": preview,
            "source_count": len(deliverables),
        }
        deliverable_entry = {
            "deliverable_id": str(uuid.uuid4()),
            "agent_id": self.node_id,
            "agent_label": self.label,
            "agent_type": "powerpoint-generator",
            "deliverable": deliverable_data,
            "output_type": "edwin_handoff",
            "interactive": False,
            "status": "approved",
            "iteration": 1,
            "created_at": datetime.utcnow().isoformat(),
        }

        emit_messages: List[AIMessage] = [
            self._make_status_message(
                EDWIN_READY_MESSAGE,
                edwin_url=handoff_url,
                edwin_handoff_id=handoff_id,
            )
        ]

        logger.info(
            "PowerPoint generator %s created Edwin handoff %s",
            self.label,
            handoff_id,
        )

        return {
            # Hidden from chat UI; Edwin URL is opened via the status message + poll.
            "has_deliverable": False,
            "deliverables": [deliverable_entry],
            "messages": emit_messages,
            "response": {
                "edwin_handoff_id": handoff_id,
                "edwin_url": handoff_url,
            },
        }
