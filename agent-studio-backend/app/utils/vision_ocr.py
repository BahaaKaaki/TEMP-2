"""
Image OCR via vision-capable LLM.

When a user uploads an image (png/jpg/...), we can't use the regular
``unstructured`` parser the way we do for PDFs / DOCX, so this module
sends the image bytes (base64) to a vision-capable model through the
existing GenAI proxy and returns the transcribed text + a short visual
description.

The output is plain text and slots straight into ``chat_file.extracted_text``
so the rest of the file-context pipeline (local/global injection,
provenance labels, truncation) keeps working unchanged.

Defaults to ``vertex_ai.gemini-2.5-flash-lite`` (cheap + fast) via the
proxy. Override with the ``OCR_VISION_MODEL`` / ``OCR_VISION_PROVIDER``
settings.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional, Tuple

from langchain_core.messages import HumanMessage

from config.llm_config import LLMClientManager
from config.settings import settings

logger = logging.getLogger(__name__)


# Image extensions we route to the vision OCR pipeline. Kept as a single
# source of truth so the FileParser, the file route validators, and the
# frontend ``accept`` attribute stay in sync.
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp"})

# Common MIME mappings — used when the upload didn't carry a MIME type so
# the vision model still receives a valid ``data:image/...`` URL.
_EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


# Prompt is intentionally compact: we want the LLM to treat its job as
# transcription first, description second. ``Verbatim`` discourages the
# model from "summarizing" the visible text.
_OCR_PROMPT = (
    "You are an OCR + visual description assistant.\n\n"
    "Task:\n"
    "1. Transcribe ALL visible text from the image VERBATIM, preserving "
    "line breaks and reading order. Do not paraphrase.\n"
    "2. After the transcription, on a new line, write the literal token "
    "'---' and then a brief (<=3 sentences) description of any non-text "
    "visual content (charts, diagrams, screenshots, photos, etc.).\n\n"
    "If the image contains no readable text, output exactly the token "
    "'[NO TEXT DETECTED]' followed by the '---' separator and the visual "
    "description.\n\n"
    "Output plain text only. No code fences, no JSON, no preamble."
)


def is_image_extension(file_extension: str) -> bool:
    """True if ``file_extension`` (with or without the leading dot) is an image."""
    if not file_extension:
        return False
    return file_extension.lower().lstrip(".") in IMAGE_EXTENSIONS


def guess_image_mime(file_extension: str, fallback: Optional[str] = None) -> str:
    """Best-effort MIME type for the data URL the vision model expects."""
    ext = (file_extension or "").lower().lstrip(".")
    return _EXT_TO_MIME.get(ext, fallback or "image/png")


async def extract_text_from_image(
    file_bytes: bytes,
    file_name: str,
    mime_type: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Run vision OCR on ``file_bytes``.
    
    Returns ``(success, extracted_text, error_message)`` so the caller can
    persist the same way it does for ``unstructured`` parses.
    
    The function never raises — any failure short-circuits to
    ``(False, None, "<reason>")`` and the caller marks the row as
    ``parsing_status='failed'``.
    """
    if not settings.OCR_VISION_ENABLED:
        return False, None, "Image OCR disabled (OCR_VISION_ENABLED=false)"
    
    if not file_bytes:
        return False, None, "Empty image content"
    
    size = len(file_bytes)
    max_bytes = settings.OCR_VISION_MAX_BYTES
    if size > max_bytes:
        return (
            False,
            None,
            f"Image too large for OCR: {size} bytes (limit: {max_bytes})",
        )
    
    # Resolve MIME from explicit value -> filename suffix -> png fallback.
    ext = file_name.rsplit(".", 1)[-1] if file_name and "." in file_name else ""
    effective_mime = mime_type or guess_image_mime(ext)
    
    try:
        b64 = base64.b64encode(file_bytes).decode("ascii")
        data_url = f"data:{effective_mime};base64,{b64}"
    except Exception as e:
        return False, None, f"Failed to encode image as base64: {e}"
    
    try:
        client = LLMClientManager.get_client(
            provider=settings.OCR_VISION_PROVIDER,
            model=settings.OCR_VISION_MODEL,
            temperature=0,
            max_tokens=settings.OCR_VISION_MAX_OUTPUT_TOKENS,
            timeout=settings.OCR_VISION_TIMEOUT,
            binding_key="settings.ocr_vision",
            llm_role="ocr_vision",
        )
    except Exception as e:
        logger.error("vision_ocr: failed to build LLM client: %s", e, exc_info=True)
        return False, None, f"Vision client init failed: {e}"
    
    message = HumanMessage(
        content=[
            {"type": "text", "text": _OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )
    
    try:
        # ``ainvoke`` already runs async; the timeout wrapper is just a
        # belt-and-braces guard so a hung proxy can't stall the parser
        # background task indefinitely.
        result = await asyncio.wait_for(
            client.ainvoke([message]),
            timeout=settings.OCR_VISION_TIMEOUT + 15,
        )
    except asyncio.TimeoutError:
        return False, None, (
            f"Vision OCR timed out after {settings.OCR_VISION_TIMEOUT}s"
        )
    except Exception as e:
        logger.error(
            "vision_ocr: LLM call failed for %s (%d bytes, mime=%s): %s",
            file_name, size, effective_mime, e, exc_info=True,
        )
        return False, None, f"Vision OCR call failed: {e}"
    
    text = _coerce_text(getattr(result, "content", None))
    if not text:
        return False, None, "Vision model returned empty content"
    
    # Sanitize for PostgreSQL TEXT (matches FileParser.parse_file behaviour).
    text = text.replace("\x00", "")
    text = "".join(c for c in text if ord(c) >= 32 or c in "\n\r\t")
    
    logger.info(
        "✅ Vision OCR for %s: %d chars extracted (model=%s)",
        file_name, len(text), settings.OCR_VISION_MODEL,
    )
    return True, text, None


def _coerce_text(content) -> str:
    """Normalise LangChain-style ``content`` to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                # OpenAI-style content blocks: {"type":"text","text":"..."}
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts).strip()
    return str(content).strip()
