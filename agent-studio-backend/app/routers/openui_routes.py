"""OpenUI runtime translation API.

The deliverable→Lang translation is now driven entirely by server-side
pretranslation in `chat_service` and persisted on `agent_deliverable.openuiLang`.
Only an ops health probe remains here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.services.openui_prompt import system_prompt_available
from app.services.openui_translate_service import get_translation_prompt_debug
from core.dependencies import get_current_user
from db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/openui",
    tags=["OpenUI"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/health")
async def openui_health(current_user: User = Depends(get_current_user)):
    """Verify OpenUI system prompt is present for runtime translation."""
    del current_user
    if system_prompt_available():
        return {"status": "ok", "system_prompt": True}
    raise HTTPException(
        status_code=503,
        detail=(
            "OpenUI system prompt missing. Run "
            "`cd agent-studio-frontend && npm run generate:openui`."
        ),
    )


@router.get("/debug/prompt")
async def openui_debug_prompt(current_user: User = Depends(get_current_user)):
    """Return the JSON->OpenUI translation prompt for the in-app debug panel."""
    del current_user
    if not system_prompt_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "OpenUI system prompt missing. Run "
                "`cd agent-studio-frontend && npm run generate:openui`."
            ),
        )
    return get_translation_prompt_debug()
