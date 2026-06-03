"""
Edwin handoff API client.

Creates a temporary handoff record in Edwin so the Edwin SPA can open with
``?handoff=<id>`` and load workflow deliverables formatted as markdown.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from config.keyvault import cfg

logger = logging.getLogger(__name__)

HANDOFF_TIMEOUT_SECONDS = 30.0


class EdwinHandoffError(Exception):
    """Raised when Edwin handoff creation fails."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _edwin_api_base() -> str:
    base = (cfg.EDWIN_API_URL or "").strip().rstrip("/")
    if not base:
        raise EdwinHandoffError(
            "EDWIN_API_URL is not configured. Set it in the backend environment."
        )
    return base


async def create_handoff(
    *,
    question: str,
    answer: str,
    source: str = "Agent Studio",
    suggested_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    POST /api/handoffs on Edwin and return ``{ id, url }``.

    Args:
        question: Short prompt describing the handoff intent.
        answer: Markdown body (workflow deliverables).
        source: Caller metadata for Edwin.
        suggested_prompt: Optional Edwin starter prompt.

    Returns:
        Parsed JSON body from Edwin (expects ``id`` and ``url``).

    Raises:
        EdwinHandoffError: Missing config, HTTP error, or unexpected response.
    """
    url = f"{_edwin_api_base()}/api/handoffs"
    payload: Dict[str, Any] = {
        "source": source,
        "question": question,
        "answer": answer,
    }
    if suggested_prompt:
        payload["suggestedPrompt"] = suggested_prompt

    try:
        async with httpx.AsyncClient(timeout=HANDOFF_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
    except httpx.RequestError as exc:
        logger.error("Edwin handoff request failed: %s", exc)
        raise EdwinHandoffError(f"Could not reach Edwin API: {exc}") from exc

    if resp.status_code != 201:
        detail = resp.text[:500] if resp.text else resp.reason_phrase
        logger.error(
            "Edwin handoff failed status=%s body=%s",
            resp.status_code,
            detail,
        )
        raise EdwinHandoffError(
            f"Edwin handoff failed ({resp.status_code}): {detail}",
            status_code=resp.status_code,
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise EdwinHandoffError("Edwin returned a non-JSON response") from exc

    handoff_id = data.get("id")
    handoff_url = data.get("url")
    if not handoff_id or not handoff_url:
        raise EdwinHandoffError(
            "Edwin response missing required fields (id, url)"
        )

    logger.info("Edwin handoff created id=%s", handoff_id)
    return data
