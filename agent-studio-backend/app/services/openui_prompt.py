"""OpenUI Lang system prompt loader for runtime deliverable rendering."""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "openui_prompts"
_PROMPT_FILE = "system.txt"
_MANIFEST_FILE = "manifest.json"


def system_prompt_available() -> bool:
    """True when ``system.txt`` exists (run ``npm run generate:openui``)."""
    return (_PROMPTS_DIR / _PROMPT_FILE).exists()


@lru_cache(maxsize=1)
def _read_prompt() -> str:
    path = _PROMPTS_DIR / _PROMPT_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"OpenUI system prompt not found at {path}. "
            "Run `npm run generate:openui` in agent-studio-frontend "
            "to produce the prompt file."
        )
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _read_manifest() -> dict[str, Any]:
    path = _PROMPTS_DIR / _MANIFEST_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("OpenUI prompt manifest is invalid JSON: %s", path)
        return {}


def build_system_prompt() -> str:
    """Return the generated OpenUI prompt for JSON-to-UI translation."""
    return _read_prompt()


def openui_prompt_metadata() -> dict[str, Any]:
    """Return prompt metadata used for health checks and cache invalidation."""
    prompt = _read_prompt()
    manifest = _read_manifest()
    return {
        "prompt": manifest.get("prompt", _PROMPT_FILE),
        "component_count": manifest.get("componentCount"),
        "component_spec_hash": manifest.get("componentSpecHash"),
        "prompt_hash": manifest.get("promptHash")
        or hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "generated_at": manifest.get("generatedAt"),
    }
