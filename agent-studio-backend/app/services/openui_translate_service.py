"""
Runtime OpenUI Generate: structured JSON -> OpenUI Lang via LLM + system.txt.

Translation runs server-side as a fire-and-forget task after each agent
deliverable is persisted (during workflow execution), and the result is saved
on ``agent_deliverable.openuiLang``. The frontend reads the column directly
and never calls a translate API at render time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.llm_config import LLMClientManager
from app.llm.registry import LlmModelRegistry
from app.services.openui_prompt import build_system_prompt

logger = logging.getLogger(__name__)

OPENUI_TRANSLATE_BINDING = "service.openui_translate"


_FENCE_RE = re.compile(r"^```(?:openui|text)?\s*\n?|\n?```\s*$", re.MULTILINE)
_ROOT_RE = re.compile(r"^root\s*=", re.MULTILINE)

# Max simultaneous per-section translate calls to the LLM proxy.
_SECTION_TRANSLATE_CONCURRENCY = 5
# Backoff before a single per-section retry on transient failure.
_SECTION_RETRY_DELAY_SECONDS = 2.0


_TASK_PROMPT = (
    "# YOUR TASK\n"
    "Convert the deliverable below into OpenUI Lang for the Agent Studio UI.\n"
    "- Use ONLY components from the library in this system prompt.\n"
    "- Use only facts present in the JSON; do not invent data.\n"
    "- Preserve every material fact, number, table row, citation marker, recommendation, caveat, and named entity.\n"
    "- Do not summarize away, omit, collapse, or replace source details with placeholders like 'and more' or 'etc.'.\n"
    "- For dense content, use compact tables, lists, accordions, tabs, or scrollable regions.\n"
    "- The layout entry MUST be `root = Stack([...])`.\n"
    "- Prefer the built-in OpenUI general components for layout, tabs, accordions, tables, and charts.\n"
    "- Use Agent Studio custom components only for true gaps: TreeView for hierarchies/org charts, Slide for slide-shaped data, and QueryTrace for query/tool provenance.\n"
    "- Emit OpenUI Lang only. No markdown, HTML, JSON, or commentary.\n"
)


def get_openui_translate_model() -> str:
    """Return the configured model for JSON-to-OpenUI translation."""
    return LlmModelRegistry.get_primary(OPENUI_TRANSLATE_BINDING)


def get_translation_prompt_debug() -> dict[str, Any]:
    """Return the static prompt used for JSON->OpenUI translation.

    Exposed for the in-app deliverable debug panel. The per-section human
    message is just ``"Structured JSON to render:\\n" + <section JSON>``; the
    section JSON is already visible to the panel, so only the shared
    system/task prompt is returned here.
    """
    system = build_system_prompt()
    return {
        "system": system,
        "task": _TASK_PROMPT,
        "combined": system + "\n\n" + _TASK_PROMPT,
        "human_prefix": "Structured JSON to render:\n",
        "model": get_openui_translate_model(),
    }


def get_openui_translate_temperature(model: str) -> float:
    """Return a model-compatible temperature for OpenUI translation."""
    if "gpt-5.5" in (model or "").lower():
        return 1
    return 0.2


def get_openui_translate_max_tokens() -> int:
    """Return the output token budget for OpenUI Lang generation."""
    raw = os.getenv("OPENUI_TRANSLATE_MAX_TOKENS", "8192")
    try:
        return max(1024, int(raw))
    except (TypeError, ValueError):
        logger.warning(
            "Invalid OPENUI_TRANSLATE_MAX_TOKENS=%r; using 8192",
            raw,
        )
        return 8192


def get_openui_translate_model_kwargs(model: str) -> dict[str, Any]:
    """Return model-specific kwargs for fast, deterministic render translation."""
    if "gpt-5.5" in (model or "").lower():
        # Responses API (used for OpenAI reasoning models via llm_config) expects
        # nested ``reasoning`` / top-level ``verbosity``, not ``reasoning_effort``.
        return {
            "reasoning": {"effort": "low"},
            "verbosity": "low",
        }
    return {}


def _extract_text(response: Any) -> str:
    if hasattr(response, "content") and response.content:
        content = response.content
        return content if isinstance(content, str) else str(content)
    if hasattr(response, "text") and response.text:
        return response.text
    return str(response)


def _normalize_lang(raw: str) -> str:
    return _FENCE_RE.sub("", (raw or "").strip()).strip()


def _strip_externally_rendered_fields(content: Any) -> Any:
    """Remove fields the chat UI renders outside the OpenUI block.

    `summary` is shown as a paragraph above the OpenUI render, so leaving it
    in the payload causes the LLM to re-emit it as a heading and a summaryCard.
    """
    if isinstance(content, dict) and "summary" in content:
        return {k: v for k, v in content.items() if k != "summary"}
    return content


def _payload_json(content: Any) -> str:
    content = _strip_externally_rendered_fields(content)
    try:
        return json.dumps(content, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(content)


async def translate_json_to_openui_lang(content: Any) -> str:
    """Generate OpenUI Lang from a structured deliverable JSON payload."""
    model = get_openui_translate_model()
    llm = LLMClientManager.get_client_for_binding(
        OPENUI_TRANSLATE_BINDING,
        temperature=get_openui_translate_temperature(model),
        max_tokens=get_openui_translate_max_tokens(),
        timeout=120,
        llm_role="openui_translate",
        **get_openui_translate_model_kwargs(model),
    )

    system = build_system_prompt() + "\n\n" + _TASK_PROMPT
    human = "Structured JSON to render:\n" + _payload_json(content)

    response = await llm.ainvoke(
        [SystemMessage(content=system), HumanMessage(content=human)]
    )
    lang = _normalize_lang(_extract_text(response))
    if not _ROOT_RE.search(lang):
        raise ValueError("OpenUI translate produced output without a `root =` entry")
    return lang


def _extract_sections(content: Any) -> list[Any] | None:
    """Return the deliverable's ``sections`` list, or None when not sectioned."""
    if isinstance(content, dict):
        sections = content.get("sections")
        if isinstance(sections, list) and sections:
            return sections
    return None


async def _translate_one_with_retry(payload: Any, sem: asyncio.Semaphore) -> str:
    """Translate one unit (section or whole deliverable) with a single retry.

    Returns an empty string on persistent failure so a single bad section does
    not break the rest of the deliverable; the caller persists "" for that slot
    and the self-heal path can retry later.
    """
    async with sem:
        try:
            return await translate_json_to_openui_lang(payload)
        except Exception as exc:
            logger.info(
                "OpenUI section translate failed (retry in %.1fs): %s",
                _SECTION_RETRY_DELAY_SECONDS,
                exc,
            )
            await asyncio.sleep(_SECTION_RETRY_DELAY_SECONDS)
            try:
                return await translate_json_to_openui_lang(payload)
            except Exception as exc2:
                logger.warning("OpenUI section translate failed after retry: %s", exc2)
                return ""


async def translate_deliverable_section_langs(content: Any) -> list[str]:
    """Translate a deliverable into a list of per-section OpenUI Lang strings.

    The list is index-aligned to the deliverable's ``sections`` array so the
    frontend can pair each Lang with its ``section_title``. Non-sectioned
    deliverables return a single-element list so the UI has one code path.
    """
    model = await LlmModelRegistry.ensure_binding_primary(OPENUI_TRANSLATE_BINDING)
    logger.info(
        "OpenUI section translate starting (binding=%s, model=%s)",
        OPENUI_TRANSLATE_BINDING,
        model,
    )
    sem = asyncio.Semaphore(_SECTION_TRANSLATE_CONCURRENCY)
    sections = _extract_sections(content)
    if sections is None:
        return [await _translate_one_with_retry(content, sem)]

    results = await asyncio.gather(
        *(_translate_one_with_retry(section, sem) for section in sections),
        return_exceptions=True,
    )
    return [r if isinstance(r, str) else "" for r in results]
