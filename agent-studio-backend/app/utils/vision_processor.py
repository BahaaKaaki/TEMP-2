"""
Vision-based document processing for knowledge base uploads.

Renders each page/slide of a PDF, PPTX, or DOCX to an image, then sends
it to a vision-capable LLM (e.g. Gemini Flash) with a user prompt and
optional output schema.  Pages are processed in parallel.  Each page's
LLM output becomes a chunk in the RAG pipeline.
"""

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

VISION_BINDING = "service.vision.default"
DEFAULT_MAX_CONCURRENT = 20
DPI_RENDER = 200


@dataclass
class VisionPageResult:
    """Result of processing a single page with a vision LLM."""
    page_number: int
    text: str
    structured_data: Optional[Dict[str, Any]] = None
    # The rendered PNG of this page, retained so the caller can persist it as a
    # source snapshot for citation display. Not all callers need it.
    image_png: Optional[bytes] = None


# ---------------------------------------------------------------------------
# Page rendering helpers
# ---------------------------------------------------------------------------

def _render_pdf_pages(file_path: str, dpi: int = DPI_RENDER) -> List[bytes]:
    """Render every page of a PDF to PNG bytes using PyMuPDF."""
    import fitz  # PyMuPDF

    doc = fitz.open(file_path)
    images: List[bytes] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def _find_libreoffice_binary() -> str:
    """Locate the LibreOffice binary across Linux, macOS, and Windows."""
    import shutil

    candidates = [
        "libreoffice",
        "soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate

    raise FileNotFoundError(
        "LibreOffice is required for PPTX/DOCX vision processing but was not found. "
        "Install it: macOS → 'brew install --cask libreoffice', "
        "Linux → 'apt-get install libreoffice', "
        "or download from https://www.libreoffice.org"
    )


def _convert_to_pdf_via_libreoffice(file_path: str) -> str:
    """Convert PPTX/DOCX to PDF using LibreOffice headless.

    Returns the path to the generated PDF (inside a temp directory).
    Caller is responsible for cleaning up the temp directory.
    """
    lo_bin = _find_libreoffice_binary()
    tmp_dir = tempfile.mkdtemp(prefix="vision_lo_")
    cmd = [
        lo_bin,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", tmp_dir,
        file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"LibreOffice conversion failed: {stderr}")

    stem = Path(file_path).stem
    pdf_path = os.path.join(tmp_dir, f"{stem}.pdf")
    if not os.path.exists(pdf_path):
        files_in_dir = os.listdir(tmp_dir)
        raise RuntimeError(
            f"LibreOffice did not produce expected PDF. "
            f"Files in output dir: {files_in_dir}"
        )
    return pdf_path


def render_pages_to_images(file_path: str, dpi: int = DPI_RENDER) -> List[bytes]:
    """Render a document's pages to a list of PNG byte arrays.

    Supports PDF (direct), PPTX, and DOCX (via LibreOffice conversion).
    """
    ext = Path(file_path).suffix.lower().lstrip(".")
    if ext == "pdf":
        return _render_pdf_pages(file_path, dpi=dpi)

    if ext in ("pptx", "docx", "doc"):
        pdf_path = _convert_to_pdf_via_libreoffice(file_path)
        try:
            return _render_pdf_pages(pdf_path, dpi=dpi)
        finally:
            tmp_dir = os.path.dirname(pdf_path)
            for f in os.listdir(tmp_dir):
                os.remove(os.path.join(tmp_dir, f))
            os.rmdir(tmp_dir)

    raise ValueError(f"Unsupported file type for vision processing: .{ext}")


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _get_vision_llm(model: Optional[str] = None):
    """Create a vision-capable LLM client via the GenAI proxy."""
    from app.config.llm_config import LLMClientManager
    from app.llm.registry import LlmModelRegistry
    resolved = model or LlmModelRegistry.get_primary(VISION_BINDING)
    return LLMClientManager.get_client(
        provider="google",
        model=resolved,
        temperature=0.1,
        max_tokens=32768,
        timeout=180,
        binding_key=VISION_BINDING,
        llm_role="vision",
    )


def _image_to_data_url(image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _parse_json_block(text: str) -> Optional[dict]:
    """Try to extract a JSON object from an LLM response."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):
            return {"fields": obj}
    except json.JSONDecodeError:
        pass
    brace = text.find("{")
    if brace != -1:
        depth = 0
        for i in range(brace, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


_SKIP_SENTINEL = "SKIP"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PAGE_SYSTEM_PROMPT = """\
You are a document analysis engine.  You receive an image of a single \
page or slide from a document and a user goal describing what \
information to extract.

Rules:
- If the page contains NO information relevant to the user's goal, \
respond with exactly the word SKIP (nothing else).
- Be thorough – capture ALL details including every name, label, \
hierarchy level, department, sub-unit, and relationship visible on \
the page.  Do NOT summarize or abbreviate; list every item you see.
- Preserve the structural relationships you see (parent/child, \
groupings, levels, etc.).
- When a schema is provided, you MUST return valid JSON.  Never \
return plain text when a schema is given.
"""

_PAGE_PROMPT_NO_SCHEMA = """\
User goal: {prompt}

Analyze the attached page image.  Provide a thorough, well-structured \
text description of ALL relevant content.  List every name, label, \
department, sub-unit, and data point visible on the page.  Do NOT \
use generic phrases like "various sub-units" — enumerate them all.

Preserve any hierarchies, tables, groupings, and relationships.

If there is no relevant information, respond with SKIP."""

_PAGE_PROMPT_WITH_SCHEMA = """\
User goal: {prompt}

Output schema (JSON field definitions):
{schema}

Analyze the attached page image and return a single valid JSON object.

CRITICAL RULES:
1. You MUST return valid, complete JSON — no markdown fences, no \
trailing text, no truncation.
2. The "summary" field must be a detailed 3-6 sentence description \
that names specific entities, departments, and relationships found \
on this page.  Do NOT write generic summaries like "This slide \
presents an organizational structure."  Instead, include the actual \
names and hierarchy you extracted.
3. Populate ALL schema fields from the page content.  Set fields to \
null only if they truly do not apply to this page.
4. For array fields (like divisions), list EVERY item visible on the \
page — do not abbreviate or summarize.
5. If there is no relevant information at all, respond with SKIP \
(just the word, nothing else).

Return ONLY the JSON object."""


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


async def process_page(
    image: bytes,
    page_num: int,
    prompt: str,
    model: str,
    schema: Optional[List[Dict[str, Any]]] = None,
) -> Optional[VisionPageResult]:
    """Process a single page image with the vision LLM.

    Returns None if the LLM signals SKIP (page has no relevant content).
    """
    if schema:
        user_text = _PAGE_PROMPT_WITH_SCHEMA.format(
            prompt=prompt, schema=json.dumps(schema, indent=2)
        )
    else:
        user_text = _PAGE_PROMPT_NO_SCHEMA.format(prompt=prompt)

    content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": _image_to_data_url(image)}},
    ]

    llm = _get_vision_llm(model)
    response = await llm.ainvoke([
        SystemMessage(content=_PAGE_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ])
    raw = response.content if hasattr(response, "content") else str(response)
    raw = raw.strip()

    if raw.upper() == _SKIP_SENTINEL:
        logger.debug("Page %d: SKIP (no relevant content)", page_num)
        return None

    structured_data = None
    text = raw

    if schema:
        parsed = _parse_json_block(raw)
        if parsed:
            structured_data = parsed
            text = parsed.pop("summary", raw)
        else:
            logger.warning(
                "Page %d: schema was provided but LLM did not return valid JSON. "
                "Using raw text as chunk.",
                page_num,
            )

    return VisionPageResult(
        page_number=page_num,
        text=text,
        structured_data=structured_data,
        image_png=image,
    )


async def process_document(
    file_path: str,
    prompt: str,
    model: Optional[str] = None,
    output_schema: Optional[List[Dict[str, Any]]] = None,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
) -> List[VisionPageResult]:
    """Full vision-processing pipeline for a document.

    1. Render pages to images (in thread pool).
    2. Process all pages in parallel with a concurrency limit.
    3. Return results (pages that were SKIP'd are excluded).
    """
    logger.info(
        "Vision processing: file=%s, model=%s, "
        "has_output_schema=%s, max_concurrent=%d",
        Path(file_path).name, model,
        output_schema is not None, max_concurrent,
    )

    images = await asyncio.to_thread(render_pages_to_images, file_path)
    logger.info("Rendered %d page images from %s", len(images), Path(file_path).name)

    if not images:
        logger.warning("No pages rendered from %s", file_path)
        return []

    effective_schema = output_schema

    # Process pages in parallel
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _process_with_limit(img: bytes, page_num: int):
        async with semaphore:
            try:
                return await process_page(img, page_num, prompt, model, effective_schema)
            except Exception as e:
                logger.error("Vision processing failed for page %d: %s", page_num, e, exc_info=True)
                return None

    tasks = [
        _process_with_limit(img, page_num)
        for page_num, img in enumerate(images, start=1)
    ]
    results = await asyncio.gather(*tasks)

    # Filter out None results (skipped or failed pages)
    valid_results = [r for r in results if r is not None]

    logger.info(
        "Vision processing complete: %d/%d pages produced chunks",
        len(valid_results), len(images),
    )
    return valid_results
