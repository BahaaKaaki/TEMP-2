#!/usr/bin/env python3
"""Governance Document Graph Parser — Enhanced Multi-Document Edition

Multi-phase LLM pipeline that processes governance/procedure documents
(PDF + DOCX) into structured JSON — extracting process graph nodes, edges,
roles, and mapping every piece of text to a specific node with zero data loss.

Enhanced capabilities:
  - Multi-page BPMN extraction with hierarchical sub-graph stitching
  - DOCX support alongside PDF
  - Cross-document process linking across an entire governance corpus
  - Unified corpus output with inter-process edges

Usage:
    # Single document
    python governance_processor.py /path/to/document.pdf -o output.json

    # Batch corpus processing
    python governance_processor.py --batch /path/to/folder/ -o corpus_output.json
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from openai import AsyncOpenAI

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gov-parser")


# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

DEFAULT_PROXY_URL = "https://genai-sharedservice-emea.pwcinternal.com"
DEFAULT_SMART_MODEL = "bedrock.anthropic.claude-sonnet-4-6"
DEFAULT_FAST_MODEL = "bedrock.anthropic.claude-haiku-4-5"

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


@dataclass
class Config:
    proxy_url: str = DEFAULT_PROXY_URL
    api_key: str = ""
    smart_model: str = DEFAULT_SMART_MODEL
    fast_model: str = DEFAULT_FAST_MODEL
    dpi: int = 150
    max_retries: int = 2
    temperature: float = 0.0
    max_tokens: int = 16384


# ═══════════════════════════════════════════════════════════════
# Phase 1 — Document Ingestion  (PDF + DOCX)
# ═══════════════════════════════════════════════════════════════

@dataclass
class PageData:
    page_num: int
    text: str
    image_b64: str
    embedded_images: list[str] = field(default_factory=list)


def extract_pdf(pdf_path: str, dpi: int = 150) -> tuple[list[PageData], str]:
    """Extract per-page text and render each page to a base64 PNG image."""
    log.info("Phase 1 · Ingesting PDF — %s", pdf_path)
    doc = fitz.open(pdf_path)
    pages: list[PageData] = []
    text_parts: list[str] = []

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for idx, page in enumerate(doc):
        text = page.get_text()
        text_parts.append(f"--- PAGE {idx + 1} ---\n{text}")

        pixmap = page.get_pixmap(matrix=matrix)
        img_bytes = pixmap.tobytes("png")
        img_b64 = base64.b64encode(img_bytes).decode("ascii")

        pages.append(PageData(page_num=idx + 1, text=text, image_b64=img_b64))

    doc.close()
    full_text = "\n\n".join(text_parts)
    log.info("  ✓ %d pages extracted (%d characters)", len(pages), len(full_text))
    return pages, full_text


def extract_docx(docx_path: str) -> tuple[list[PageData], str]:
    """Extract text and embedded images from a DOCX file.

    DOCX files lack fixed page boundaries.  We split content into logical
    sections using heading styles, then attach embedded images to the
    section in which they appear.
    """
    log.info("Phase 1 · Ingesting DOCX — %s", docx_path)

    doc = DocxDocument(docx_path)

    # --- extract all images from the zip ---
    media_map: dict[str, str] = {}
    with zipfile.ZipFile(docx_path) as z:
        for name in z.namelist():
            low = name.lower()
            if name.startswith("word/media/") and any(
                low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp")
            ):
                raw = z.read(name)
                media_map[name] = base64.b64encode(raw).decode("ascii")

    # --- map rId → media path for the main document part ---
    rid_to_media: dict[str, str] = {}
    main_part = doc.part
    for rel in main_part.rels.values():
        if hasattr(rel, "target_ref") and str(rel.target_ref).startswith("media/"):
            full_path = f"word/{rel.target_ref}"
            if full_path in media_map:
                rid_to_media[rel.rId] = full_path

    # --- walk paragraphs, split on headings, attach inline images ---
    sections: list[dict] = []
    current: dict = {"text": "", "images": []}

    for para in doc.paragraphs:
        style = para.style.name if para.style else ""
        if style.startswith("Heading") and current["text"].strip():
            sections.append(current)
            current = {"text": "", "images": []}

        current["text"] += para.text + "\n"

        for run in para.runs:
            if not hasattr(run, "_element"):
                continue
            drawings = run._element.findall(
                ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing"
            ) + run._element.findall(
                ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict"
            )
            for _ in drawings:
                blips = run._element.findall(
                    ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
                )
                for blip in blips:
                    embed = blip.get(
                        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
                    )
                    if embed and embed in rid_to_media:
                        b64 = media_map.get(rid_to_media[embed], "")
                        if b64:
                            current["images"].append(b64)

    if current["text"].strip() or current["images"]:
        sections.append(current)

    # --- build PageData list ---
    pages: list[PageData] = []
    text_parts: list[str] = []
    for idx, sec in enumerate(sections):
        pnum = idx + 1
        text_parts.append(f"--- SECTION {pnum} ---\n{sec['text']}")
        pages.append(PageData(
            page_num=pnum,
            text=sec["text"],
            image_b64=sec["images"][0] if sec["images"] else "",
            embedded_images=sec["images"],
        ))

    full_text = "\n\n".join(text_parts)
    total_imgs = sum(len(s["images"]) for s in sections)
    log.info(
        "  ✓ %d sections, %d embedded images extracted (%d characters)",
        len(pages), total_imgs, len(full_text),
    )
    return pages, full_text


def extract_document(path: str, dpi: int = 150) -> tuple[list[PageData], str]:
    """Unified entry point — dispatches to PDF or DOCX extractor."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path, dpi)
    if ext in (".docx", ".doc"):
        if not HAS_DOCX:
            raise ImportError(
                "python-docx is required for DOCX files: pip install python-docx"
            )
        return extract_docx(path)
    raise ValueError(f"Unsupported file type: {ext}")


# ═══════════════════════════════════════════════════════════════
# LLM Helpers
# ═══════════════════════════════════════════════════════════════

def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


async def llm_call(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_content: list[dict[str, Any]] | str,
    config: Config,
    label: str = "",
) -> dict:
    """Make a single async LLM call and return parsed JSON."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    raw = ""
    for attempt in range(config.max_retries + 1):
        try:
            t0 = time.time()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            elapsed = time.time() - t0
            raw = response.choices[0].message.content or ""
            tokens = response.usage.total_tokens if response.usage else 0
            result = json.loads(_strip_json_fences(raw))
            log.info("  ✓ [%s] %.1fs · %d tokens", label, elapsed, tokens)
            return result

        except json.JSONDecodeError as exc:
            log.warning(
                "  ✗ [%s] JSON parse failed (attempt %d/%d): %s",
                label, attempt + 1, config.max_retries + 1, exc,
            )
            if attempt == config.max_retries:
                log.error("  Raw response:\n%s", raw[:500])
                raise

        except Exception as exc:
            log.warning(
                "  ✗ [%s] Call failed (attempt %d/%d): %s",
                label, attempt + 1, config.max_retries + 1, exc,
            )
            if attempt == config.max_retries:
                raise
            await asyncio.sleep(2 ** attempt)

    return {}


# ═══════════════════════════════════════════════════════════════
# Phase 2-pre — Page Classification + Graph Grouping
# ═══════════════════════════════════════════════════════════════

@dataclass
class GraphGroup:
    """A set of related BPMN pages within a document."""
    group_id: str
    group_type: str        # "overview" | "detail"
    section_ref: str       # e.g. "8.1", "overview"
    page_nums: list[int] = field(default_factory=list)
    parent_group_id: str | None = None
    description: str = ""


CLASSIFY_SYSTEM = """\
You are a document-structure analyst specialising in governance procedure PDFs.

You will receive the text extracted from every page of a PDF.  Your job is to:
1. Identify which pages contain a **process flowchart, swimlane diagram, or BPMN
   diagram** (not plain-text tables or numbered lists).
2. Determine whether the document has MULTIPLE related diagrams — for example:
   - An OVERVIEW / top-level process map showing high-level phases
   - One or more DETAIL diagrams showing the step-by-step flow within each phase

Flowchart pages typically exhibit:
• Fragmented, non-sentence text (shape/box labels such as role names,
  short action phrases, "YES", "NO").
• Lack of coherent paragraphs — the text extractor pulls labels out of
  graphical shapes so the output looks jumbled.
• Multiple role/actor names appearing as isolated fragments.
• Decision keywords scattered without sentence context.

Return **only** a JSON object:
{
  "graph_groups": [
    {
      "group_id":        "overview",
      "group_type":      "overview",
      "section_ref":     "overview",
      "page_nums":       [8],
      "parent_group_id": null,
      "description":     "High-level 5-phase process overview"
    },
    {
      "group_id":        "detail_8.1",
      "group_type":      "detail",
      "section_ref":     "8.1",
      "page_nums":       [9],
      "parent_group_id": "overview",
      "description":     "Detail flow for Identify & Log Problem"
    }
  ],
  "reasoning": "One-paragraph justification"
}

RULES
• If the document has only ONE diagram, return a single group with group_type = "overview".
• If a diagram spans multiple consecutive pages, put ALL page numbers in one group.
• Detail diagrams whose section is evident from nearby headings must include
  the section reference (e.g. "8.1", "8.3").
• Pages that contain ONLY text (procedures, tables, roles) are NOT graph pages —
  do not include them.
• If NO page contains a flowchart, return {"graph_groups": [], "reasoning": "…"}."""


async def classify_pages(
    client: AsyncOpenAI,
    pages: list[PageData],
    config: Config,
) -> list[GraphGroup]:
    """Identify graph pages and group them into related sub-graphs."""
    page_summaries = "\n\n".join(
        f"=== PAGE {p.page_num} ===\n{p.text[:1500]}" for p in pages
    )
    result = await llm_call(
        client, config.fast_model, CLASSIFY_SYSTEM,
        f"Classify each page:\n\n{page_summaries}",
        config, label="2pre·Classify",
    )

    groups: list[GraphGroup] = []
    for g in result.get("graph_groups", []):
        groups.append(GraphGroup(
            group_id=g.get("group_id", ""),
            group_type=g.get("group_type", "overview"),
            section_ref=g.get("section_ref", ""),
            page_nums=g.get("page_nums", []),
            parent_group_id=g.get("parent_group_id"),
            description=g.get("description", ""),
        ))

    if groups:
        summary = "; ".join(
            f"{g.group_id} ({g.group_type}) pp.{g.page_nums}" for g in groups
        )
        log.info("  Graph groups: %s", summary)
    else:
        log.warning("  No graph pages detected")

    return groups


# ═══════════════════════════════════════════════════════════════
# Phase 2A — Multi-Graph Extraction  (Sonnet + Vision)
# ═══════════════════════════════════════════════════════════════

GRAPH_SYSTEM = """\
You are a BPMN / process-flow analyst specialising in governance and ITIL procedure documents.

Analyse the supplied document pages (images + text) and extract the **complete** procedure
flowchart **including the visual layout** so it can be reproduced in another tool.

All positions use a **normalised coordinate system** where the top-left of the
flowchart bounding box is (0, 0) and the bottom-right is (1, 1).
Estimate positions by looking at the image carefully.

CONTEXT: This diagram is part of a larger document.  {group_context}

Return **only** a JSON object — no commentary — with this structure:

{{
  "nodes": [
    {{
      "id":          "{prefix}N<seq>",
      "label":       "Human-readable step name",
      "actor":       "Swimlane / role this step belongs to",
      "type":        "action | decision | start | end | subprocess",
      "shape":       "rectangle | diamond | rounded_rectangle | comment_box",
      "description": "What happens at this step",
      "position": {{
        "x":      0.15,
        "y":      0.05,
        "width":  0.12,
        "height": 0.04
      }},
      "external_ref": "Name of another process this node hands off to, or null"
    }}
  ],
  "edges": [
    {{
      "from_node":  "{prefix}N<x>",
      "to_node":    "{prefix}N<y>",
      "type":       "sequence | approval | rejection | conditional | escalation",
      "condition":  "YES / NO / Major Change / null",
      "label":      "Arrow label or null"
    }}
  ],
  "swimlanes": [
    {{
      "name":       "Lane display name",
      "actor_role": "Role that owns this lane",
      "order":      1,
      "bounds": {{
        "y_start": 0.0,
        "y_end":   0.10,
        "label_x": 0.0,
        "label_width": 0.06
      }}
    }}
  ]
}}

SHAPE GUIDE
• rectangle          — standard process step (action box)
• diamond            — decision gate (YES / NO paths)
• rounded_rectangle  — start / end / trigger steps (rounded corners)
• comment_box        — annotation / callout with bullet-point detail text

EXTERNAL REFERENCES
• If a node represents a hand-off to ANOTHER process (e.g. "Problem Management",
  "Change Enablement", "Incident Management"), set external_ref to the process name.
• End nodes that point to another process → type = "end", external_ref = process name.
• Start nodes that receive from another process → type = "start", external_ref = source.
• For normal internal nodes → external_ref = null.

POSITION RULES
• x, y = centre of the shape in normalised coords (0–1).
• width, height = size of the shape in normalised coords.
• For swimlanes: y_start / y_end mark the top and bottom of the horizontal band.
  label_x and label_width describe the left-side label column.
• "order" is the visual top-to-bottom index (1 = topmost lane).
• Estimate positions as accurately as possible from the image.

GENERAL RULES
• Capture EVERY node and EVERY edge visible in the diagram, including rejection/feedback loops.
• Use sequential IDs ({prefix}N1, {prefix}N2, …) following the natural process order.
• Decision diamonds → type = "decision", shape = "diamond".
• The first entry-point step → type = "start".
• Terminal sinks → type = "end".
• The "actor" field MUST match one of the swimlane names exactly.
• Missing a node or edge = an incomplete model — be thorough."""


async def extract_single_graph(
    client: AsyncOpenAI,
    pages: list[PageData],
    group: GraphGroup,
    full_text: str,
    config: Config,
) -> dict:
    """Extract a graph from a single GraphGroup's pages."""
    target_pages = [p for p in pages if p.page_num in group.page_nums]
    if not target_pages:
        target_pages = pages  # fallback

    # Prefix node IDs for detail sub-graphs to avoid collisions
    prefix = "" if group.group_type == "overview" else f"D{group.section_ref.replace('.', '_')}_"

    if group.group_type == "detail":
        ctx = (
            f"This is a DETAIL sub-graph for section {group.section_ref}. "
            f"It shows the step-by-step flow for: {group.description}. "
            "Mark start/end nodes that connect to the broader process."
        )
    else:
        ctx = (
            "This is the main process overview. If it contains high-level phase boxes "
            "that decompose into separate detail diagrams, set type='subprocess' for those nodes."
        )

    prompt = GRAPH_SYSTEM.format(prefix=prefix, group_context=ctx)

    page_label = ", ".join(str(p.page_num) for p in target_pages)
    log.info(
        "  Extracting graph [%s] from page(s) [%s]",
        group.group_id, page_label,
    )

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Below are {len(target_pages)} page image(s) from a governance "
                "procedure document.  Extract the process graph.\n\n"
                f"DOCUMENT TEXT (for context):\n{full_text[:8000]}"
            ),
        },
    ]

    for page in target_pages:
        images_to_send = []
        if page.image_b64:
            images_to_send.append(page.image_b64)
        images_to_send.extend(page.embedded_images)

        for img_b64 in images_to_send:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
            })

    return await llm_call(
        client, config.smart_model, prompt, content, config,
        label=f"2A·Graph[{group.group_id}]",
    )


async def extract_all_graphs(
    client: AsyncOpenAI,
    pages: list[PageData],
    groups: list[GraphGroup],
    full_text: str,
    config: Config,
) -> dict:
    """Extract all graph groups and combine into a hierarchical structure."""
    if not groups:
        log.info("  No graph groups — sending all pages as fallback")
        fallback = GraphGroup(
            group_id="overview", group_type="overview",
            section_ref="overview",
            page_nums=[p.page_num for p in pages],
        )
        graph = await extract_single_graph(
            client, pages, fallback, full_text, config,
        )
        return {"overview": graph, "sub_graphs": [], "overview_to_detail_links": []}

    overview_groups = [g for g in groups if g.group_type == "overview"]
    detail_groups = [g for g in groups if g.group_type == "detail"]

    # Extract overview (there should be exactly one)
    overview_graph: dict = {}
    if overview_groups:
        overview_graph = await extract_single_graph(
            client, pages, overview_groups[0], full_text, config,
        )
    elif not detail_groups:
        single = groups[0]
        overview_graph = await extract_single_graph(
            client, pages, single, full_text, config,
        )
        return {"overview": overview_graph, "sub_graphs": [], "overview_to_detail_links": []}

    # Extract detail sub-graphs concurrently
    sub_graphs: list[dict] = []
    if detail_groups:
        log.info("  Extracting %d detail sub-graph(s) concurrently", len(detail_groups))
        detail_results = await asyncio.gather(*(
            extract_single_graph(client, pages, g, full_text, config)
            for g in detail_groups
        ))
        for g, result in zip(detail_groups, detail_results):
            sub_graphs.append({
                "group_id": g.group_id,
                "section_ref": g.section_ref,
                "parent_group_id": g.parent_group_id,
                "description": g.description,
                **result,
            })

    # Stitch overview → detail links
    links = await stitch_subgraphs(
        client, overview_graph, sub_graphs, config,
    ) if overview_graph and sub_graphs else []

    return {
        "overview": overview_graph,
        "sub_graphs": sub_graphs,
        "overview_to_detail_links": links,
    }


# ═══════════════════════════════════════════════════════════════
# Phase 2A-post — Sub-Graph Stitching
# ═══════════════════════════════════════════════════════════════

STITCH_SYSTEM = """\
You are a process-graph integration specialist.

You receive:
  1. OVERVIEW — a high-level process graph with phase-level nodes.
  2. DETAIL_SUBGRAPHS — one or more detailed sub-graphs, each expanding
     a specific phase of the overview.

Your task: link them together.

For each detail sub-graph:
  1. Identify which overview node it expands (by matching section_ref,
     label similarity, or sequential position).
  2. Record the detail graph's start node(s) and end node(s).
  3. Identify any end nodes in one detail graph that feed into the
     start of the next detail graph (phase continuity).

Return **only** a JSON object:
{
  "links": [
    {
      "overview_node_id":    "N3",
      "overview_node_label": "Identify & Log Problem",
      "detail_group_id":     "detail_8.1",
      "detail_start_nodes":  ["D8_1_N1"],
      "detail_end_nodes":    ["D8_1_N5"],
      "section_ref":         "8.1"
    }
  ],
  "phase_continuity_edges": [
    {
      "from_detail_group":  "detail_8.1",
      "from_node_id":       "D8_1_N5",
      "to_detail_group":    "detail_8.2",
      "to_node_id":         "D8_2_N1",
      "label":              "Proceed to Categorize & Prioritize"
    }
  ]
}"""


async def stitch_subgraphs(
    client: AsyncOpenAI,
    overview: dict,
    sub_graphs: list[dict],
    config: Config,
) -> list[dict]:
    """Link overview nodes to their detail sub-graphs."""
    payload = json.dumps(
        {"overview": overview, "detail_subgraphs": sub_graphs},
        indent=2, ensure_ascii=False,
    )
    result = await llm_call(
        client, config.fast_model, STITCH_SYSTEM,
        f"Stitch these graphs together:\n\n{payload}",
        config, label="2A-post·Stitch",
    )
    links = result.get("links", [])
    continuity = result.get("phase_continuity_edges", [])
    log.info(
        "  ✓ %d overview-to-detail links, %d continuity edges",
        len(links), len(continuity),
    )
    return links + [{"_type": "continuity", **e} for e in continuity]


# ═══════════════════════════════════════════════════════════════
# Phase 2B — Document Content Extraction  (Haiku)
# ═══════════════════════════════════════════════════════════════

CONTENT_SYSTEM = """\
You are a governance-document analyst.

Extract **all** non-procedure content from the supplied document.  Return **only** a JSON object:

{
  "metadata": {
    "id":             "Document ID",
    "version":        "Version number",
    "title":          "Full title",
    "classification": "Classification level",
    "department":     "Issuing department"
  },
  "terms_and_definitions": [
    { "term": "…", "definition": "…" }
  ],
  "purpose": {
    "text":       "Introductory purpose paragraph(s) — VERBATIM",
    "objectives": ["Each numbered objective — VERBATIM"]
  },
  "scope": {
    "text":           "Full scope statement — VERBATIM",
    "change_sources": ["Each change-trigger type"]
  },
  "applicability": "Full applicability text — VERBATIM",
  "requirements": [
    { "standard": "Name + number", "description": "Relevance" }
  ],
  "roles": [
    {
      "id":               "snake_case_id",
      "name":             "Display Name",
      "description":      "Description paragraph — VERBATIM",
      "responsibilities": ["Each bullet — VERBATIM"]
    }
  ],
  "kpis": [
    {
      "name":        "KPI name",
      "description": "What it measures",
      "formula":     "Calculation formula",
      "target":      "Target value",
      "frequency":   "Frequency",
      "polarity":    "ascending | descending",
      "unit":        "Unit"
    }
  ],
  "records": [
    { "title": "…", "medium": "…", "location": "…" }
  ],
  "references": ["Each referenced document — include document IDs if visible"],
  "interface_table": [
    {
      "section":       "8.1",
      "direction":     "input | output",
      "name":          "The artefact name (e.g. Service Request, Registered and Classified Change)",
      "interface_ref": "The other process/phase (e.g. Incident Management Procedure, Phase 8.2)"
    }
  ]
}

RULES
• Extract COMPLETE text — never summarise or truncate.
• Every responsibility, objective and definition must appear VERBATIM.
• Include ALL roles even when names are similar.
• The interface_table is CRITICAL — extract every Input/Output row from every
  procedure sub-section.  These define how this process connects to other processes.
• Sub-bullets under a role → separate responsibility strings."""


async def extract_document_content(
    client: AsyncOpenAI, full_text: str, config: Config,
) -> dict:
    return await llm_call(
        client, config.fast_model, CONTENT_SYSTEM,
        f"Extract all structured content from this governance document:\n\n{full_text}",
        config, label="2B·Content",
    )


# ═══════════════════════════════════════════════════════════════
# Phase 2C — Procedure Section Extraction  (Haiku)
# ═══════════════════════════════════════════════════════════════

PROCEDURE_SYSTEM = """\
You are a procedure analyst specialising in ITIL governance processes.

Extract every detail from the procedure section (the part with numbered activity steps, \
input/output tables, RACI matrices, risk criteria and checklists).

Return **only** a JSON object:

{
  "sections": [
    {
      "section_id": "8.1",
      "title":      "Section title",
      "inputs":  [ { "name": "…", "interface_from": "Source procedure" } ],
      "outputs": [ { "name": "…", "interface_to":   "Destination procedure" } ],
      "activities": [
        { "id": "8.1.1.1", "text": "FULL VERBATIM text of the step — include every sub-point" }
      ],
      "raci_matrix": [
        {
          "activity":            "Activity label",
          "change_manager":      "R|A|C|I|AR|empty",
          "change_coordinator":  "R|A|C|I|AR|empty",
          "technical_reviewer":  "R|A|C|I|AR|empty",
          "business_owner":      "R|A|C|I|AR|empty",
          "security_team":       "R|A|C|I|AR|empty",
          "customer":            "R|A|C|I|AR|empty",
          "change_reviewer":     "R|A|C|I|AR|empty",
          "change_implementer":  "R|A|C|I|AR|empty",
          "change_tester":       "R|A|C|I|AR|empty",
          "gdoc":                "R|A|C|I|AR|empty"
        }
      ],
      "decision_criteria": {
        "risk_assessment": [
          { "criterion": "Question", "parameters": "H/M/L or values", "points": "Scoring" }
        ],
        "risk_levels": [
          { "range": "Point range", "level": "Low|Medium|High", "treatment": "Description" }
        ]
      },
      "change_types": [
        { "type": "Standard|Normal|Emergency|Expedited", "definition": "VERBATIM", "treatment": "VERBATIM" }
      ],
      "checklists": [
        {
          "name": "Checklist title",
          "items": [ { "item": "Question — VERBATIM", "action": "Required action — VERBATIM" } ]
        }
      ]
    }
  ]
}

RULES
• Capture ALL numbered activity steps with COMPLETE verbatim text.
• Include every row of every table (RACI, risk, checklists).
• Fields that do not apply to a section → use empty arrays / null.
• Never summarise — copy the source text exactly."""


async def extract_procedure_details(
    client: AsyncOpenAI, full_text: str, config: Config,
) -> dict:
    return await llm_call(
        client, config.fast_model, PROCEDURE_SYSTEM,
        f"Extract all procedure-section details from this document:\n\n{full_text}",
        config, label="2C·Procedure",
    )


# ═══════════════════════════════════════════════════════════════
# Phase 3 — Text-to-Node Linking  (Sonnet)
# ═══════════════════════════════════════════════════════════════

LINKING_SYSTEM = """\
You are a data-integration specialist.

You receive three artefacts extracted from the same governance document:
  1. GRAPH  – process flowchart nodes and edges (may include sub-graphs)
  2. CONTENT – non-procedure document content (metadata, roles, terms, KPIs …)
  3. PROCEDURES – detailed procedure-section data (activities, RACI, inputs/outputs …)

Your task: map **every** extracted data element to either
  • a specific graph node (by node_id), OR
  • "global_context" (applies to the whole process), OR
  • "role_definition" (defines an actor spanning multiple nodes).

Return **only** a JSON object:

{
  "node_content_mapping": [
    {
      "node_id":            "N1",
      "node_label":         "Label for reference",
      "procedure_sections": ["8.1"],
      "activity_ids":       ["8.1.1.1", "8.1.1.2"],
      "inputs":             ["Service Request"],
      "outputs":            ["Registered and Classified Change"],
      "raci": {
        "change_manager": "A",
        "change_coordinator": "R"
      },
      "change_types_applicable":      ["Standard", "Normal"],
      "checklists_applicable":        [],
      "decision_criteria_applicable": ["risk_assessment"]
    }
  ],
  "role_node_participation": [
    {
      "role_id":   "change_manager",
      "role_name": "Change Manager",
      "participations": [
        { "node_id": "N5", "raci_type": "A", "section": "8.1" }
      ]
    }
  ],
  "global_context_assignments": [
    { "category": "purpose | scope | applicability | requirements | terms | kpis | records | references | metadata",
      "reason":   "Brief justification" }
  ],
  "unmapped_text": [
    { "text_summary": "…", "source": "Where it came from", "reason": "Why it couldn't be mapped" }
  ]
}

RULES
• Every procedure activity must map to exactly one node.
• Every input / output must map to exactly one node.
• RACI entries → the node they describe.
• KPIs, terms, scope, purpose, applicability, requirements, records, references → global_context.
• Role definitions → role_definition, but also list which nodes they participate in.
• change_types from section 8.1 → the recording / classification node(s).
• checklists and decision_criteria → the node where they are applied.
• The unmapped_text array should ideally be EMPTY.
• Use the actor / swimlane from the graph to match roles to nodes.
• If the graph contains sub-graphs with prefixed IDs (D8_1_N1 etc.), map to those too."""


async def link_text_to_nodes(
    client: AsyncOpenAI,
    graph_data: dict,
    content: dict,
    procedures: dict,
    config: Config,
) -> dict:
    all_nodes = graph_data.get("overview", {}).get("nodes", [])
    for sg in graph_data.get("sub_graphs", []):
        all_nodes.extend(sg.get("nodes", []))
    all_edges = graph_data.get("overview", {}).get("edges", [])
    for sg in graph_data.get("sub_graphs", []):
        all_edges.extend(sg.get("edges", []))

    flat_graph = {"nodes": all_nodes, "edges": all_edges}
    payload = json.dumps(
        {"graph": flat_graph, "document_content": content, "procedure_sections": procedures},
        indent=2, ensure_ascii=False,
    )
    return await llm_call(
        client, config.smart_model, LINKING_SYSTEM,
        f"Map all extracted content to graph nodes. Data:\n\n{payload}",
        config, label="3·Linking",
    )


# ═══════════════════════════════════════════════════════════════
# Phase 4 — Assembly & Validation
# ═══════════════════════════════════════════════════════════════

def assemble_output(
    graph_data: dict,
    content: dict,
    procedures: dict,
    linking: dict,
    source_file: str,
    total_pages: int,
    processing_time: float,
    models_used: list[str],
) -> dict:
    """Build the final JSON, attach linked content to nodes, validate completeness."""

    node_map: dict[str, dict] = {}
    for mapping in linking.get("node_content_mapping", []):
        node_map[mapping.get("node_id", "")] = mapping

    role_parts: dict[str, list] = {}
    for rp in linking.get("role_node_participation", []):
        role_parts[rp.get("role_id", "")] = rp.get("participations", [])

    proc_by_id: dict[str, dict] = {}
    for sec in procedures.get("sections", []):
        proc_by_id[sec.get("section_id", "")] = sec

    def _enrich_nodes(nodes: list[dict]) -> list[dict]:
        enriched: list[dict] = []
        for node in nodes:
            nid = node.get("id", "")
            mapping = node_map.get(nid, {})
            section_ids = mapping.get("procedure_sections", [])

            activities: list[str] = []
            mapped_aids = set(mapping.get("activity_ids", []))
            for sid in section_ids:
                sec = proc_by_id.get(sid, {})
                for act in sec.get("activities", []):
                    if not mapped_aids or act.get("id") in mapped_aids:
                        activities.append(act.get("text", ""))

            decision_criteria = None
            change_types: list[dict] = []
            checklists: list[dict] = []
            for sid in section_ids:
                sec = proc_by_id.get(sid, {})
                if sec.get("decision_criteria"):
                    decision_criteria = sec["decision_criteria"]
                for ct in sec.get("change_types", []) or []:
                    change_types.append(ct)
                for cl in sec.get("checklists", []) or []:
                    checklists.append(cl)

            enriched.append({
                "id":                 nid,
                "label":              node.get("label", ""),
                "actor":              node.get("actor", ""),
                "type":               node.get("type", ""),
                "shape":              node.get("shape"),
                "description":        node.get("description", ""),
                "position":           node.get("position"),
                "external_ref":       node.get("external_ref"),
                "procedure_sections": section_ids,
                "content": {
                    "activities":        activities,
                    "inputs":            mapping.get("inputs", []),
                    "outputs":           mapping.get("outputs", []),
                    "raci":              mapping.get("raci", {}),
                    "change_types":      change_types or None,
                    "decision_criteria": decision_criteria,
                    "checklists":        checklists or None,
                },
            })
        return enriched

    # Enrich overview nodes
    overview = graph_data.get("overview", {})
    overview_nodes = _enrich_nodes(overview.get("nodes", []))

    # Enrich sub-graph nodes
    enriched_sub_graphs: list[dict] = []
    for sg in graph_data.get("sub_graphs", []):
        enriched_sub_graphs.append({
            "group_id":        sg.get("group_id", ""),
            "section_ref":     sg.get("section_ref", ""),
            "parent_group_id": sg.get("parent_group_id"),
            "description":     sg.get("description", ""),
            "nodes":           _enrich_nodes(sg.get("nodes", [])),
            "edges":           sg.get("edges", []),
            "swimlanes":       sg.get("swimlanes", []),
        })

    # Enrich roles
    enriched_roles: list[dict] = []
    for role in content.get("roles", []):
        rid = role.get("id", "")
        parts = role_parts.get(rid, [])
        enriched_roles.append({
            **role,
            "participates_in_nodes": list({p.get("node_id") for p in parts}),
            "node_participations":   parts,
        })

    output = {
        "document_metadata": content.get("metadata", {}),
        "global_context": {
            "purpose":               content.get("purpose", {}),
            "scope":                 content.get("scope", {}),
            "applicability":         content.get("applicability", ""),
            "requirements":          content.get("requirements", []),
            "terms_and_definitions": content.get("terms_and_definitions", []),
            "kpis":                  content.get("kpis", []),
            "records":               content.get("records", []),
            "references":            content.get("references", []),
            "interface_table":       content.get("interface_table", []),
        },
        "roles": enriched_roles,
        "process_graph": {
            "overview": {
                "nodes":     overview_nodes,
                "edges":     overview.get("edges", []),
                "swimlanes": overview.get("swimlanes", []),
            },
            "sub_graphs":              enriched_sub_graphs,
            "overview_to_detail_links": graph_data.get("overview_to_detail_links", []),
        },
        "unmapped_text":       linking.get("unmapped_text", []),
        "extraction_metadata": {
            "source_file":             source_file,
            "total_pages":             total_pages,
            "processing_time_seconds": round(processing_time, 2),
            "models_used":             models_used,
        },
    }

    # Validation summary
    all_nodes = overview_nodes
    for sg in enriched_sub_graphs:
        all_nodes = all_nodes + sg.get("nodes", [])
    n_nodes = len(all_nodes)
    n_with_acts = sum(1 for n in all_nodes if n["content"]["activities"])
    n_unmapped = len(output["unmapped_text"])
    total_acts = sum(len(s.get("activities", [])) for s in procedures.get("sections", []))
    mapped_acts = sum(len(n["content"]["activities"]) for n in all_nodes)

    log.info("  Validation:")
    log.info("    Nodes: %d total, %d with activities attached", n_nodes, n_with_acts)
    log.info("    Sub-graphs: %d", len(enriched_sub_graphs))
    log.info("    Activities: %d extracted, %d mapped to nodes", total_acts, mapped_acts)
    log.info("    Unmapped text blocks: %d", n_unmapped)

    return output


# ═══════════════════════════════════════════════════════════════
# Phase 5 — Cross-Document Linking  (NEW)
# ═══════════════════════════════════════════════════════════════

CROSS_DOC_SYSTEM = """\
You are a process integration specialist analysing an ITIL / ISO governance document corpus.

You receive summaries of MULTIPLE governance process documents, each containing:
  - document_id, title
  - process_start_nodes (entry points to the process)
  - process_end_nodes (terminal / hand-off nodes)
  - external_refs (nodes that name another process)
  - interface_table (explicit Input/Output + "Interface From/To" pairs)
  - references (other documents cited)

Your task: identify ALL cross-document process hand-offs — i.e. where the end or
output of one process triggers the start or input of another.

CRITICAL — the wording WILL differ between documents.  Use **semantic matching**:
  • "Problem Management" end node in Change doc → matches Problem Management document
  • "Change Enablement (If Required)" in Problem doc → matches Change Enablement doc
  • "Service Request Management Procedure" in references → matches GDL-PRC-024
  • Interface table entries like "Incident Management" → match the Incident doc

Return **only** a JSON object:

{
  "cross_document_edges": [
    {
      "id":              "XD<seq>",
      "from_document":   "GDL-PRC-016",
      "from_node_id":    "N17",
      "from_node_label": "Problem Management",
      "from_context":    "Failed changes escalated to Problem Management",
      "to_document":     "GDL-PRC-023",
      "to_node_id":      "N1",
      "to_node_label":   "Identify Problem",
      "to_context":      "Problem identified from failed change",
      "edge_type":       "process_handoff | escalation | feedback_loop | input_dependency",
      "confidence":      "high | medium | low",
      "evidence":        "One-sentence justification citing both documents"
    }
  ],
  "document_dependencies": [
    {
      "document_id":  "GDL-PRC-016",
      "title":        "Change Enablement Procedure",
      "depends_on":   ["GDL-PRC-023"],
      "depended_by":  ["GDL-PRC-023"],
      "reasoning":    "Brief explanation"
    }
  ],
  "shared_roles": [
    {
      "canonical_name":  "Change Manager",
      "appears_in":      ["GDL-PRC-016", "GDL-PRC-023"],
      "note":            "Same governance role across both processes"
    }
  ]
}

RULES
• Match by MEANING, not exact string — "Change Management" = "Change Enablement Procedure"
  = GDL-PRC-016.
• interface_table entries are the strongest signal — use them first.
• external_ref fields on nodes are the second strongest signal.
• references arrays provide supporting evidence.
• If a to_document exists but has no graph (e.g. a policy), still create the edge
  with to_node_id = null and to_node_label = "Process entry point".
• Only create edges where there is clear evidence of a hand-off.
• Confidence: high = explicit interface_table match; medium = external_ref + reference match;
  low = inferred from text similarity only."""


def _build_doc_summary(doc_output: dict) -> dict:
    """Condense a single-document output into a summary for cross-doc linking."""
    meta = doc_output.get("document_metadata", {})
    doc_id = meta.get("id", "unknown")
    title = meta.get("title", "")

    overview = doc_output.get("process_graph", {}).get("overview", {})
    overview_nodes = overview.get("nodes", [])

    sub_nodes: list[dict] = []
    for sg in doc_output.get("process_graph", {}).get("sub_graphs", []):
        sub_nodes.extend(sg.get("nodes", []))

    all_nodes = overview_nodes + sub_nodes

    start_nodes = [
        {"id": n["id"], "label": n.get("label", ""), "external_ref": n.get("external_ref")}
        for n in all_nodes if n.get("type") in ("start",)
    ]
    end_nodes = [
        {"id": n["id"], "label": n.get("label", ""), "external_ref": n.get("external_ref")}
        for n in all_nodes if n.get("type") in ("end",)
    ]
    external_refs = [
        {"id": n["id"], "label": n.get("label", ""), "external_ref": n.get("external_ref")}
        for n in all_nodes if n.get("external_ref")
    ]

    interface_table = doc_output.get("global_context", {}).get("interface_table", [])
    references = doc_output.get("global_context", {}).get("references", [])

    return {
        "document_id":      doc_id,
        "title":            title,
        "process_start_nodes": start_nodes,
        "process_end_nodes":   end_nodes,
        "external_refs":       external_refs,
        "interface_table":     interface_table,
        "references":          references,
    }


async def link_documents(
    client: AsyncOpenAI,
    doc_outputs: list[dict],
    config: Config,
) -> dict:
    """Phase 5: build cross-document edges from all processed documents."""
    log.info("Phase 5 · Cross-document linking (%d documents)", len(doc_outputs))

    summaries = [_build_doc_summary(d) for d in doc_outputs]
    payload = json.dumps(summaries, indent=2, ensure_ascii=False)

    return await llm_call(
        client, config.smart_model, CROSS_DOC_SYSTEM,
        f"Identify all cross-document process hand-offs:\n\n{payload}",
        config, label="5·CrossDoc",
    )


def build_corpus_output(
    doc_outputs: list[dict],
    cross_doc: dict,
    total_time: float,
    models_used: list[str],
) -> dict:
    """Assemble the unified corpus graph."""
    return {
        "corpus_metadata": {
            "total_documents":          len(doc_outputs),
            "documents_with_graphs":    sum(
                1 for d in doc_outputs
                if d.get("process_graph", {}).get("overview", {}).get("nodes")
            ),
            "processing_time_seconds":  round(total_time, 2),
            "models_used":              models_used,
        },
        "documents": doc_outputs,
        "cross_document_graph": {
            "edges":                 cross_doc.get("cross_document_edges", []),
            "document_dependencies": cross_doc.get("document_dependencies", []),
            "shared_roles":          cross_doc.get("shared_roles", []),
        },
    }


# ═══════════════════════════════════════════════════════════════
# Main Pipeline — Single Document
# ═══════════════════════════════════════════════════════════════

async def process_document(path: str, output_path: str | None, config: Config) -> dict:
    """Run the full four-phase extraction pipeline on one document."""
    t_start = time.time()

    # Phase 1
    pages, full_text = extract_document(path, config.dpi)

    # LLM client
    base_url = config.proxy_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"

    client = AsyncOpenAI(
        base_url=base_url,
        api_key=config.api_key,
        default_headers={"API-Key": config.api_key},
    )

    # Phase 2 wave 1: parallel Haiku calls
    log.info("Phase 2 · Wave 1 — parallel Haiku extraction (classify + content + procedure)")
    graph_groups, content, procedures = await asyncio.gather(
        classify_pages(client, pages, config),
        extract_document_content(client, full_text, config),
        extract_procedure_details(client, full_text, config),
    )

    # Phase 2 wave 2: graph extraction (Sonnet + vision)
    log.info("Phase 2 · Wave 2 — multi-graph extraction (Sonnet + vision)")
    graph_data = await extract_all_graphs(client, pages, graph_groups, full_text, config)

    # Phase 3: linking
    log.info("Phase 3 · Text-to-node linking")
    linking = await link_text_to_nodes(client, graph_data, content, procedures, config)

    # Phase 4: assembly
    log.info("Phase 4 · Assembly & validation")
    elapsed = time.time() - t_start
    models_used = sorted(set([config.smart_model, config.fast_model]))

    result = assemble_output(
        graph_data, content, procedures, linking,
        source_file=str(Path(path).name),
        total_pages=len(pages),
        processing_time=elapsed,
        models_used=models_used,
    )

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    total = time.time() - t_start
    log.info("Done · %s · %.1fs total", Path(path).name, total)
    return result


# ═══════════════════════════════════════════════════════════════
# Batch Pipeline — Multi-Document Corpus
# ═══════════════════════════════════════════════════════════════

async def process_corpus(
    folder: str, output_path: str, config: Config,
    concurrency: int = 2,
) -> dict:
    """Process all documents in a folder, then cross-link them."""
    t_start = time.time()
    folder_path = Path(folder)

    files = sorted(
        f for f in folder_path.iterdir()
        if f.suffix.lower() in SUPPORTED_EXTENSIONS and not f.name.startswith(".")
    )

    # De-duplicate: if both .pdf and .docx exist for the same document, prefer PDF
    # (better page rendering for vision).
    stem_map: dict[str, Path] = {}
    for f in files:
        stem = f.stem
        if stem not in stem_map:
            stem_map[stem] = f
        elif f.suffix.lower() == ".pdf":
            stem_map[stem] = f
    files = sorted(stem_map.values())

    log.info("=" * 60)
    log.info("CORPUS MODE — %d documents to process", len(files))
    log.info("=" * 60)

    # Process documents with limited concurrency
    semaphore = asyncio.Semaphore(concurrency)
    doc_outputs: list[dict] = []

    async def _process_one(path: Path) -> dict:
        async with semaphore:
            log.info("─" * 60)
            log.info("Processing: %s", path.name)
            try:
                return await process_document(str(path), None, config)
            except Exception as exc:
                log.error("FAILED: %s — %s", path.name, exc)
                return {
                    "document_metadata": {"id": path.stem, "title": path.name},
                    "error": str(exc),
                }

    results = await asyncio.gather(*(_process_one(f) for f in files))
    doc_outputs = list(results)

    successful = [d for d in doc_outputs if "error" not in d]
    log.info("─" * 60)
    log.info(
        "Extraction complete: %d/%d succeeded",
        len(successful), len(doc_outputs),
    )

    # Phase 5: cross-document linking
    base_url = config.proxy_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=config.api_key,
        default_headers={"API-Key": config.api_key},
    )

    cross_doc: dict = {}
    if len(successful) >= 2:
        cross_doc = await link_documents(client, successful, config)
    else:
        log.warning("  < 2 successful documents — skipping cross-document linking")

    # Build corpus output
    total_time = time.time() - t_start
    models_used = sorted(set([config.smart_model, config.fast_model]))
    corpus = build_corpus_output(doc_outputs, cross_doc, total_time, models_used)

    # Write
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(corpus, indent=2, ensure_ascii=False))

    n_edges = len(cross_doc.get("cross_document_edges", []))
    log.info("=" * 60)
    log.info(
        "CORPUS COMPLETE — %d documents, %d cross-doc edges, %.1fs total",
        len(doc_outputs), n_edges, total_time,
    )
    log.info("Output: %s", output_path)
    return corpus


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Governance Document Graph Parser — "
                    "LLM-powered procedure document analysis",
    )
    ap.add_argument(
        "input",
        help="Path to a PDF/DOCX document, or a folder when using --batch",
    )
    ap.add_argument(
        "-o", "--output", default=None,
        help="Output JSON path (default: <input>_parsed.json)",
    )
    ap.add_argument(
        "--batch", action="store_true",
        help="Batch mode: process all PDF/DOCX files in the input folder "
             "and produce a unified corpus output with cross-document links",
    )
    ap.add_argument("--smart-model", default=DEFAULT_SMART_MODEL)
    ap.add_argument("--fast-model",  default=DEFAULT_FAST_MODEL)
    ap.add_argument(
        "--api-key", default=None,
        help="GenAI proxy API key (or set GENAI_PROXY_API_KEY)",
    )
    ap.add_argument(
        "--proxy-url", default=None,
        help="GenAI proxy base URL (or set GENAI_PROXY_URL)",
    )
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument(
        "--concurrency", type=int, default=2,
        help="Max documents to process concurrently in batch mode",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = Config(
        smart_model=args.smart_model,
        fast_model=args.fast_model,
        dpi=args.dpi,
    )
    config.api_key = args.api_key or os.getenv("GENAI_PROXY_API_KEY", "")
    config.proxy_url = (
        args.proxy_url or os.getenv("GENAI_PROXY_URL", DEFAULT_PROXY_URL)
    )

    if not config.api_key:
        print(
            "ERROR: No API key. Set GENAI_PROXY_API_KEY or use --api-key.",
            file=sys.stderr,
        )
        sys.exit(1)

    input_path = Path(args.input)

    if args.batch:
        if not input_path.is_dir():
            print(f"ERROR: --batch requires a directory, got: {input_path}", file=sys.stderr)
            sys.exit(1)
        output_path = args.output or str(input_path / "corpus_output.json")
        asyncio.run(process_corpus(str(input_path), output_path, config, args.concurrency))
    else:
        if not input_path.exists():
            print(f"ERROR: File not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        output_path = args.output or str(input_path.with_suffix("")) + "_parsed.json"
        asyncio.run(process_document(str(input_path), output_path, config))


if __name__ == "__main__":
    main()
