"""
LLM-based metadata inference for knowledge-base chunks.

Uses a lightweight grader LLM (same as the KB researcher decomposer) to
extract typed metadata fields from document text.  Global fields are
inferred once from the full document; local fields are inferred per chunk
in parallel.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.settings import settings
from app.domain.entities.knowledge_base import MetadataFieldDef, MetadataFieldScope

logger = logging.getLogger(__name__)

MAX_GLOBAL_TEXT_CHARS = 12_000
MAX_LOCAL_TEXT_CHARS = 4_000

# ---------------------------------------------------------------------------
# Internal LLM helper
# ---------------------------------------------------------------------------

METADATA_INFER_BINDING = "service.metadata_infer"


def _get_inference_llm():
    from app.config.llm_config import LLMClientManager
    return LLMClientManager.get_client_for_binding(
        METADATA_INFER_BINDING,
        temperature=0.0,
        max_tokens=1024,
    )


def _parse_json_response(content: str) -> dict:
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if match:
        content = match.group(1).strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    brace = content.find("{")
    if brace != -1:
        depth, start = 0, brace
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return {}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

INFER_SYSTEM = """\
You are a metadata extraction engine.  Given a text passage and a list of
fields to extract, return a single JSON object mapping each field name to
its extracted value.

Rules:
- If a value cannot be determined from the text, set it to null.
- For DATE fields return ISO-8601 format: YYYY-MM-DD.
- For NUMBER fields return a plain number (up to 2 decimal places).
- For BOOLEAN fields return true or false.
- For STRING fields return a short text value.
- Respond with ONLY a JSON object (no markdown fences, no extra text).
"""


def _build_fields_description(fields: List[MetadataFieldDef]) -> str:
    parts: list = []
    for f in fields:
        desc = f" — {f.description}" if f.description else ""
        parts.append(f"- {f.name} ({f.type.value}){desc}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Type validation / casting
# ---------------------------------------------------------------------------

def validate_and_cast(value: Any, field_type: str) -> Any:
    """Validate and cast a raw LLM value to the declared type.

    Returns the cast value, or ``None`` if the value is invalid.
    """
    if value is None:
        return None
    try:
        if field_type == "date":
            if isinstance(value, str):
                datetime.strptime(value, "%Y-%m-%d")
                return value
            return None
        if field_type == "number":
            return round(float(value), 2)
        if field_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        return str(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Core inference functions
# ---------------------------------------------------------------------------

async def _infer_fields(text_fragment: str, fields: List[MetadataFieldDef]) -> Dict[str, Any]:
    """Run a single LLM call to extract *fields* from *text_fragment*."""
    if not fields:
        return {}

    fields_desc = _build_fields_description(fields)
    user_prompt = (
        f"## Fields to extract\n{fields_desc}\n\n"
        f"## Text\n{text_fragment}"
    )

    llm = _get_inference_llm()
    try:
        response = await llm.ainvoke([
            SystemMessage(content=INFER_SYSTEM),
            HumanMessage(content=user_prompt),
        ])
        raw = _parse_json_response(response.content.strip())
    except Exception as exc:
        logger.warning("Metadata inference LLM call failed: %s", exc)
        raw = {}

    result: Dict[str, Any] = {}
    for f in fields:
        val = raw.get(f.name)
        result[f.name] = validate_and_cast(val, f.type.value)
    return result


async def infer_global_metadata(
    full_text: str,
    fields: List[MetadataFieldDef],
) -> Dict[str, Any]:
    """Infer global (document-level) metadata from the full document text."""
    global_fields = [f for f in fields if f.scope == MetadataFieldScope.GLOBAL]
    if not global_fields:
        return {}
    truncated = full_text[:MAX_GLOBAL_TEXT_CHARS]
    return await _infer_fields(truncated, global_fields)


async def infer_local_metadata(
    chunk_text: str,
    fields: List[MetadataFieldDef],
) -> Dict[str, Any]:
    """Infer local (chunk-level) metadata from a single chunk."""
    local_fields = [f for f in fields if f.scope == MetadataFieldScope.LOCAL]
    if not local_fields:
        return {}
    truncated = chunk_text[:MAX_LOCAL_TEXT_CHARS]
    return await _infer_fields(truncated, local_fields)


MAX_CONCURRENT_INFER = 200
INFER_TIMEOUT_SECONDS = 120


async def infer_all_metadata(
    full_text: str,
    chunks_text: List[str],
    metadata_fields: List[MetadataFieldDef],
) -> List[Dict[str, Any]]:
    """Orchestrate global + local metadata inference for all chunks.

    Local inference is throttled to MAX_CONCURRENT_INFER parallel LLM calls
    to avoid hitting provider rate limits on large documents.  The entire
    operation is wrapped in a timeout so a stuck LLM never blocks the
    upload indefinitely.
    """
    has_global = any(f.scope == MetadataFieldScope.GLOBAL for f in metadata_fields)
    has_local = any(f.scope == MetadataFieldScope.LOCAL for f in metadata_fields)

    async def _noop() -> dict:
        return {}

    try:
        global_result = await asyncio.wait_for(
            infer_global_metadata(full_text, metadata_fields) if has_global else _noop(),
            timeout=INFER_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Global metadata inference failed/timed out: %s", exc)
        global_result = {}

    if has_local:
        sem = asyncio.Semaphore(MAX_CONCURRENT_INFER)

        async def _throttled_local(chunk_text: str) -> Dict[str, Any]:
            async with sem:
                return await infer_local_metadata(chunk_text, metadata_fields)

        try:
            local_results = await asyncio.wait_for(
                asyncio.gather(*[_throttled_local(ct) for ct in chunks_text]),
                timeout=INFER_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "Local metadata inference failed/timed out for %d chunks: %s",
                len(chunks_text), exc,
            )
            local_results = [{} for _ in chunks_text]
    else:
        local_results = [{} for _ in chunks_text]

    merged: List[Dict[str, Any]] = []
    for idx in range(len(chunks_text)):
        chunk_meta = {**global_result}
        if idx < len(local_results):
            chunk_meta.update(local_results[idx])
        merged.append(chunk_meta)

    return merged
