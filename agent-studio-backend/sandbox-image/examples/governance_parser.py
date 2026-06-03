"""Governance Document Graph Parser v2 — Code Executor version.

Multi-phase LLM pipeline that processes governance/procedure documents (PDF)
into structured JSON with:
  - Multi-page BPMN extraction with hierarchical sub-graph stitching
  - Cross-document process linking across an entire governance corpus
  - Unified corpus output with inter-process edges

Pipeline per document:
  1.  Upload PDF(s)
  2.  Phase 1  — Extract text via PyMuPDF
  3.  Phase 2-pre — Classify pages → graph groups (overview vs detail)
  4.  Phase 2A — Extract graph per group (Sonnet)
  5.  Phase 2A-post — Stitch sub-graphs to overview
  6.  Phase 2B — Content extraction with interface table (Haiku)
  7.  Phase 2C — Procedure details (Haiku)
  8.  Phase 3  — Text-to-node linking (Sonnet)
  9.  Phase 4  — Assembly & validation
Cross-document (if 2+ files):
  10. Phase 5  — Cross-document process linking (Sonnet)
  11. Build corpus output
  12. Visualize with collapsible per-document containers + cross-doc links

Recommended timeout: 900 seconds (many LLM calls, especially multi-doc).
"""

from agent_studio import output, llm
import json
import time
import io
import fitz
from concurrent.futures import ThreadPoolExecutor, as_completed


SMART_MODEL = "bedrock.anthropic.claude-sonnet-4-6"
FAST_MODEL = "bedrock.anthropic.claude-haiku-4-5"


# ═══════════════════════════════════════════════════════════════
# LLM helpers
# ═══════════════════════════════════════════════════════════════

def strip_json_fences(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def llm_json(prompt, model, system_prompt, retries=2, max_tokens=16384):
    for attempt in range(retries + 1):
        raw = llm.complete(
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
            timeout=180,
        )
        raw = strip_json_fences(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == retries:
                return {"_error": f"JSON parse failed after {retries + 1} attempts", "_raw": raw[:500]}
    return {}


# ═══════════════════════════════════════════════════════════════
# Phase 1 — PDF Ingestion
# ═══════════════════════════════════════════════════════════════

def extract_pdf(pdf_path):
    """Extract per-page text and return full text + page map."""
    doc = fitz.open(pdf_path)
    page_texts = {}
    text_parts = []
    for idx, page in enumerate(doc):
        text = page.get_text()
        page_num = idx + 1
        page_texts[page_num] = text
        text_parts.append(f"--- PAGE {page_num} ---\n{text}")
    total_pages = len(doc)
    doc.close()
    full_text = "\n\n".join(text_parts)
    return full_text, total_pages, page_texts


# ═══════════════════════════════════════════════════════════════
# Phase 2-pre — Page Classification & Graph Grouping
# ═══════════════════════════════════════════════════════════════

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


def classify_pages(page_texts):
    """Identify graph pages and group them into related sub-graphs."""
    page_summaries = "\n\n".join(
        f"=== PAGE {pnum} ===\n{text[:1500]}"
        for pnum, text in sorted(page_texts.items())
    )
    result = llm_json(
        prompt=f"Classify each page:\n\n{page_summaries}",
        model=FAST_MODEL,
        system_prompt=CLASSIFY_SYSTEM,
    )
    groups = []
    for g in result.get("graph_groups", []):
        groups.append({
            "group_id": g.get("group_id", ""),
            "group_type": g.get("group_type", "overview"),
            "section_ref": g.get("section_ref", ""),
            "page_nums": g.get("page_nums", []),
            "parent_group_id": g.get("parent_group_id"),
            "description": g.get("description", ""),
        })
    return groups


# ═══════════════════════════════════════════════════════════════
# Phase 2A — Multi-Graph Extraction (Sonnet, text-based)
# ═══════════════════════════════════════════════════════════════

GRAPH_SYSTEM_TEMPLATE = """\
You are a BPMN / process-flow analyst specialising in governance and ITIL procedure documents.

Analyse the supplied document text and extract the **complete** procedure
flowchart **including estimated visual layout** so it can be reproduced in another tool.

All positions use a **normalised coordinate system** where the top-left of the
flowchart bounding box is (0, 0) and the bottom-right is (1, 1).

CONTEXT: {group_context}

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
• Estimate positions from the document structure — actors that appear
  first in the procedure get lower y values, steps within a lane flow
  left-to-right then top-to-bottom.

GENERAL RULES
• Capture EVERY node and EVERY edge visible in the diagram, including rejection/feedback loops.
• Use sequential IDs ({prefix}N1, {prefix}N2, …) following the natural process order.
• Decision diamonds → type = "decision", shape = "diamond".
• The first entry-point step → type = "start".
• Terminal sinks → type = "end".
• The "actor" field MUST match one of the swimlane names exactly.
• Missing a node or edge = an incomplete model — be thorough."""


def extract_single_graph(full_text, page_texts, group):
    """Extract a graph from a single group's pages."""
    prefix = "" if group["group_type"] == "overview" else f"D{group['section_ref'].replace('.', '_')}_"

    if group["group_type"] == "detail":
        ctx = (
            f"This is a DETAIL sub-graph for section {group['section_ref']}. "
            f"It shows the step-by-step flow for: {group['description']}. "
            "Mark start/end nodes that connect to the broader process."
        )
    else:
        ctx = (
            "This is the main process overview. If it contains high-level phase boxes "
            "that decompose into separate detail diagrams, set type='subprocess' for those nodes."
        )

    system_prompt = GRAPH_SYSTEM_TEMPLATE.format(prefix=prefix, group_context=ctx)

    target_text = ""
    for pnum in sorted(group.get("page_nums", [])):
        if pnum in page_texts:
            target_text += f"\n--- PAGE {pnum} ---\n{page_texts[pnum]}\n"

    if not target_text.strip():
        target_text = full_text

    return llm_json(
        prompt=(
            f"Below is text from the relevant page(s) of a governance procedure document.\n"
            f"Extract the process graph for group '{group['group_id']}'.\n\n"
            f"TARGET PAGES:\n{target_text}\n\n"
            f"FULL DOCUMENT CONTEXT (for reference):\n{full_text[:8000]}"
        ),
        model=SMART_MODEL,
        system_prompt=system_prompt,
    )


def extract_all_graphs(full_text, page_texts, groups):
    """Extract all graph groups and combine into a hierarchical structure."""
    if not groups:
        fallback = {
            "group_id": "overview",
            "group_type": "overview",
            "section_ref": "overview",
            "page_nums": list(page_texts.keys()),
            "description": "Full document",
        }
        graph = extract_single_graph(full_text, page_texts, fallback)
        return {"overview": graph, "sub_graphs": [], "overview_to_detail_links": []}

    overview_groups = [g for g in groups if g["group_type"] == "overview"]
    detail_groups = [g for g in groups if g["group_type"] == "detail"]

    overview_graph = {}
    if overview_groups:
        print(f"    Extracting overview graph (pages {overview_groups[0].get('page_nums', [])})...")
        overview_graph = extract_single_graph(full_text, page_texts, overview_groups[0])
    elif not detail_groups:
        single = groups[0]
        overview_graph = extract_single_graph(full_text, page_texts, single)
        return {"overview": overview_graph, "sub_graphs": [], "overview_to_detail_links": []}

    sub_graphs = []
    if detail_groups:
        n_detail = len(detail_groups)
        print(f"    Extracting {n_detail} detail sub-graph(s) in parallel...")
        with ThreadPoolExecutor(max_workers=n_detail) as pool:
            future_to_group = {
                pool.submit(extract_single_graph, full_text, page_texts, g): g
                for g in detail_groups
            }
            for future in as_completed(future_to_group):
                g = future_to_group[future]
                result = future.result()
                sub_graphs.append({
                    "group_id": g["group_id"],
                    "section_ref": g["section_ref"],
                    "parent_group_id": g.get("parent_group_id"),
                    "description": g.get("description", ""),
                    **result,
                })
                print(f"    \u2713 Detail [{g['group_id']}] done")
        sub_graphs.sort(key=lambda sg: sg.get("section_ref", ""))

    links = []
    if overview_graph and sub_graphs:
        print("    Stitching sub-graphs to overview...")
        links = stitch_subgraphs(overview_graph, sub_graphs)

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


def stitch_subgraphs(overview, sub_graphs):
    payload = json.dumps(
        {"overview": overview, "detail_subgraphs": sub_graphs},
        indent=2, ensure_ascii=False,
    )
    result = llm_json(
        prompt=f"Stitch these graphs together:\n\n{payload}",
        model=FAST_MODEL,
        system_prompt=STITCH_SYSTEM,
    )
    links = result.get("links", [])
    continuity = result.get("phase_continuity_edges", [])
    return links + [{"_type": "continuity", **e} for e in continuity]


# ═══════════════════════════════════════════════════════════════
# Phase 2B — Document Content Extraction (Haiku)
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
      "name":          "The artefact name",
      "interface_ref": "The other process/phase"
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


def extract_document_content(full_text):
    return llm_json(
        prompt=f"Extract all structured content from this governance document:\n\n{full_text}",
        model=FAST_MODEL,
        system_prompt=CONTENT_SYSTEM,
    )


# ═══════════════════════════════════════════════════════════════
# Phase 2C — Procedure Section Extraction (Haiku)
# ═══════════════════════════════════════════════════════════════

PROCEDURE_SYSTEM = """\
You are a procedure analyst specialising in ITIL governance processes.

Extract every detail from the procedure section (numbered activity steps, \
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
        { "id": "8.1.1.1", "text": "FULL VERBATIM text of the step" }
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
• Fields that do not apply → use empty arrays / null.
• Never summarise — copy the source text exactly."""


def extract_procedure_details(full_text):
    return llm_json(
        prompt=f"Extract all procedure-section details from this document:\n\n{full_text}",
        model=FAST_MODEL,
        system_prompt=PROCEDURE_SYSTEM,
    )


# ═══════════════════════════════════════════════════════════════
# Phase 3 — Text-to-Node Linking (Sonnet)
# ═══════════════════════════════════════════════════════════════

LINKING_SYSTEM = """\
You are a data-integration specialist.

You receive three artefacts extracted from the same governance document:
  1. GRAPH  – process flowchart nodes and edges (may include sub-graphs)
  2. CONTENT – non-procedure document content (metadata, roles, terms, KPIs …)
  3. PROCEDURES – detailed procedure-section data (activities, RACI, inputs/outputs …)

Map **every** extracted data element to either
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
      "raci": { "change_manager": "A", "change_coordinator": "R" },
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


def link_text_to_nodes(graph_data, content, procedures):
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
    return llm_json(
        prompt=f"Map all extracted content to graph nodes. Data:\n\n{payload}",
        model=SMART_MODEL,
        system_prompt=LINKING_SYSTEM,
    )


# ═══════════════════════════════════════════════════════════════
# Phase 4 — Assembly & Validation
# ═══════════════════════════════════════════════════════════════

def assemble_output(graph_data, content, procedures, linking, source_file, total_pages):
    """Build the final JSON, attach linked content to nodes, validate completeness."""
    node_map = {}
    for m in linking.get("node_content_mapping", []):
        node_map[m.get("node_id", "")] = m

    role_parts = {}
    for rp in linking.get("role_node_participation", []):
        role_parts[rp.get("role_id", "")] = rp.get("participations", [])

    proc_by_id = {}
    for sec in procedures.get("sections", []):
        proc_by_id[sec.get("section_id", "")] = sec

    def _enrich_nodes(nodes):
        enriched = []
        for node in nodes:
            nid = node.get("id", "")
            mapping = node_map.get(nid, {})
            section_ids = mapping.get("procedure_sections", [])

            activities = []
            mapped_aids = set(mapping.get("activity_ids", []))
            for sid in section_ids:
                sec = proc_by_id.get(sid, {})
                for act in sec.get("activities", []):
                    if not mapped_aids or act.get("id") in mapped_aids:
                        activities.append(act.get("text", ""))

            decision_criteria = None
            change_types = []
            checklists = []
            for sid in section_ids:
                sec = proc_by_id.get(sid, {})
                if sec.get("decision_criteria"):
                    decision_criteria = sec["decision_criteria"]
                for ct in sec.get("change_types", []) or []:
                    change_types.append(ct)
                for cl in sec.get("checklists", []) or []:
                    checklists.append(cl)

            enriched.append({
                "id": nid,
                "label": node.get("label", ""),
                "actor": node.get("actor", ""),
                "type": node.get("type", ""),
                "shape": node.get("shape"),
                "description": node.get("description", ""),
                "position": node.get("position"),
                "external_ref": node.get("external_ref"),
                "procedure_sections": section_ids,
                "content": {
                    "activities": activities,
                    "inputs": mapping.get("inputs", []),
                    "outputs": mapping.get("outputs", []),
                    "raci": mapping.get("raci", {}),
                    "change_types": change_types or None,
                    "decision_criteria": decision_criteria,
                    "checklists": checklists or None,
                },
            })
        return enriched

    overview = graph_data.get("overview", {})
    overview_nodes = _enrich_nodes(overview.get("nodes", []))

    enriched_sub_graphs = []
    for sg in graph_data.get("sub_graphs", []):
        enriched_sub_graphs.append({
            "group_id": sg.get("group_id", ""),
            "section_ref": sg.get("section_ref", ""),
            "parent_group_id": sg.get("parent_group_id"),
            "description": sg.get("description", ""),
            "nodes": _enrich_nodes(sg.get("nodes", [])),
            "edges": sg.get("edges", []),
            "swimlanes": sg.get("swimlanes", []),
        })

    enriched_roles = []
    for role in content.get("roles", []):
        rid = role.get("id", "")
        parts = role_parts.get(rid, [])
        enriched_roles.append({
            **role,
            "participates_in_nodes": list({p.get("node_id") for p in parts}),
            "node_participations": parts,
        })

    result = {
        "document_metadata": content.get("metadata", {}),
        "global_context": {
            "purpose": content.get("purpose", {}),
            "scope": content.get("scope", {}),
            "applicability": content.get("applicability", ""),
            "requirements": content.get("requirements", []),
            "terms_and_definitions": content.get("terms_and_definitions", []),
            "kpis": content.get("kpis", []),
            "records": content.get("records", []),
            "references": content.get("references", []),
            "interface_table": content.get("interface_table", []),
        },
        "roles": enriched_roles,
        "process_graph": {
            "overview": {
                "nodes": overview_nodes,
                "edges": overview.get("edges", []),
                "swimlanes": overview.get("swimlanes", []),
            },
            "sub_graphs": enriched_sub_graphs,
            "overview_to_detail_links": graph_data.get("overview_to_detail_links", []),
        },
        "unmapped_text": linking.get("unmapped_text", []),
    }

    all_nodes = overview_nodes[:]
    for sg in enriched_sub_graphs:
        all_nodes.extend(sg.get("nodes", []))
    n_nodes = len(all_nodes)
    n_with_acts = sum(1 for n in all_nodes if n["content"]["activities"])
    total_acts = sum(len(s.get("activities", [])) for s in procedures.get("sections", []))
    mapped_acts = sum(len(n["content"]["activities"]) for n in all_nodes)
    n_unmapped = len(result["unmapped_text"])

    print(f"    Validation: {n_nodes} nodes, {n_with_acts} with activities")
    print(f"    Sub-graphs: {len(enriched_sub_graphs)}")
    print(f"    Activities: {total_acts} extracted, {mapped_acts} mapped")
    print(f"    Unmapped text blocks: {n_unmapped}")

    return result


# ═══════════════════════════════════════════════════════════════
# Phase 5 — Cross-Document Linking (Sonnet)
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
• Match by MEANING, not exact string.
• interface_table entries are the strongest signal — use them first.
• external_ref fields on nodes are the second strongest signal.
• references arrays provide supporting evidence.
• Only create edges where there is clear evidence of a hand-off.
• Confidence: high = explicit interface_table match; medium = external_ref + reference match;
  low = inferred from text similarity only."""


def _build_doc_summary(doc_output):
    meta = doc_output.get("document_metadata", {})
    overview = doc_output.get("process_graph", {}).get("overview", {})
    overview_nodes = overview.get("nodes", [])

    sub_nodes = []
    for sg in doc_output.get("process_graph", {}).get("sub_graphs", []):
        sub_nodes.extend(sg.get("nodes", []))

    all_nodes = overview_nodes + sub_nodes

    return {
        "document_id": meta.get("id", "unknown"),
        "title": meta.get("title", ""),
        "process_start_nodes": [
            {"id": n["id"], "label": n.get("label", ""), "external_ref": n.get("external_ref")}
            for n in all_nodes if n.get("type") == "start"
        ],
        "process_end_nodes": [
            {"id": n["id"], "label": n.get("label", ""), "external_ref": n.get("external_ref")}
            for n in all_nodes if n.get("type") == "end"
        ],
        "external_refs": [
            {"id": n["id"], "label": n.get("label", ""), "external_ref": n.get("external_ref")}
            for n in all_nodes if n.get("external_ref")
        ],
        "interface_table": doc_output.get("global_context", {}).get("interface_table", []),
        "references": doc_output.get("global_context", {}).get("references", []),
    }


def link_documents(doc_outputs):
    print("Phase 5 · Cross-document linking...")
    summaries = [_build_doc_summary(d) for d in doc_outputs]
    payload = json.dumps(summaries, indent=2, ensure_ascii=False)
    return llm_json(
        prompt=f"Identify all cross-document process hand-offs:\n\n{payload}",
        model=SMART_MODEL,
        system_prompt=CROSS_DOC_SYSTEM,
    )


def build_corpus_output(doc_outputs, cross_doc):
    return {
        "corpus_metadata": {
            "total_documents": len(doc_outputs),
            "documents_with_graphs": sum(
                1 for d in doc_outputs
                if d.get("process_graph", {}).get("overview", {}).get("nodes")
            ),
        },
        "documents": doc_outputs,
        "cross_document_graph": {
            "edges": cross_doc.get("cross_document_edges", []),
            "document_dependencies": cross_doc.get("document_dependencies", []),
            "shared_roles": cross_doc.get("shared_roles", []),
        },
    }


# ═══════════════════════════════════════════════════════════════
# Visualization — JS render scripts + DSL flowcharts
# ═══════════════════════════════════════════════════════════════

# __IDX__ is replaced at build time with the document array index.
DOC_SECTIONS_SCRIPT = r"""
var h = React.createElement;
var doc = data.documents[__IDX__];
if (!doc) return h('div', null, 'Document not found');

var meta = doc.document_metadata || {};
var ctx  = doc.global_context || {};
var roles = doc.roles || [];

/* ── helpers ──────────────────────────────────────────────── */
function badge(label, value) {
    if (!value) return null;
    return h('span', {
        className: 'inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 border border-gray-200'
    },
        h('span', { className: 'font-medium text-gray-500' }, label + ':'),
        ' ' + value
    );
}

function section(title, body, key, isOpen) {
    return h('details', { key: key, className: 'bg-white rounded-lg border border-gray-200 overflow-hidden group', open: isOpen !== false },
        h('summary', { className: 'px-4 py-3 bg-gray-50 hover:bg-gray-100 cursor-pointer flex items-center justify-between select-none' },
            h('span', { className: 'text-sm font-semibold text-gray-700' }, title),
            h('svg', { className: 'w-4 h-4 text-gray-400 transition-transform group-open:rotate-180', fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24' },
                h('path', { strokeLinecap: 'round', strokeLinejoin: 'round', strokeWidth: 2, d: 'M19 9l-7 7-7-7' })
            )
        ),
        h('div', { className: 'px-4 py-3' }, body)
    );
}

function text(t) {
    return h('p', { className: 'text-sm text-gray-700 leading-relaxed whitespace-pre-wrap' }, t);
}

function tbl(cols, rows) {
    return h('div', { className: 'overflow-x-auto max-h-96' },
        h('table', { className: 'w-full text-xs border-collapse' },
            h('thead', { className: 'bg-gray-50 sticky top-0' },
                h('tr', null, cols.map(function(c) {
                    return h('th', { key: c, className: 'px-3 py-2 text-left font-medium text-gray-600 border-b' }, c);
                }))
            ),
            h('tbody', null, rows.map(function(row, ri) {
                return h('tr', { key: ri, className: ri % 2 === 0 ? 'bg-white' : 'bg-gray-50/50' },
                    cols.map(function(c) {
                        var val = row[c];
                        return h('td', { key: c, className: 'px-3 py-1.5 text-gray-800 border-b border-gray-100' },
                            typeof val === 'object' ? JSON.stringify(val) : String(val || '')
                        );
                    })
                );
            }))
        )
    );
}

function bullets(items) {
    return h('ul', { className: 'list-disc list-inside space-y-1 text-sm text-gray-700' },
        items.map(function(item, i) {
            return h('li', { key: i }, typeof item === 'string' ? item : JSON.stringify(item));
        })
    );
}

/* ── build sections ──────────────────────────────────────── */
var secs = [];
var si = 0;

var purpose = ctx.purpose || {};
var pText = purpose.text || '';
var objectives = purpose.objectives || [];
if (pText || objectives.length) {
    var body = pText;
    if (objectives.length) body += '\n\nObjectives:\n' + objectives.map(function(o) { return '  \u2022 ' + o; }).join('\n');
    secs.push(section('Purpose', text(body), 's' + si++));
}

var scope = ctx.scope || {};
var sText = scope.text || '';
var sources = scope.change_sources || [];
if (sText || sources.length) {
    var body2 = sText;
    if (sources.length) body2 += '\n\nChange sources:\n' + sources.map(function(s) { return '  \u2022 ' + s; }).join('\n');
    secs.push(section('Scope', text(body2), 's' + si++));
}

if (ctx.applicability) {
    secs.push(section('Applicability', text(ctx.applicability), 's' + si++));
}

if (roles.length) {
    var roleRows = roles.map(function(r) {
        return {
            Name: r.name || '',
            Description: (r.description || '').substring(0, 250),
            Responsibilities: (r.responsibilities || []).join('; ').substring(0, 350)
        };
    });
    secs.push(section('Roles & Responsibilities (' + roles.length + ')',
        tbl(['Name', 'Description', 'Responsibilities'], roleRows), 's' + si++));
}

var reqs = ctx.requirements || [];
if (reqs.length) {
    var reqRows = reqs.map(function(r) { return { Standard: r.standard || '', Description: r.description || '' }; });
    secs.push(section('Requirements & Standards', tbl(['Standard', 'Description'], reqRows), 's' + si++));
}

var kpis = ctx.kpis || [];
if (kpis.length) {
    var kpiRows = kpis.map(function(k) {
        return { Name: k.name || '', Target: k.target || '', Frequency: k.frequency || '', Formula: k.formula || '' };
    });
    secs.push(section('KPIs', tbl(['Name', 'Target', 'Frequency', 'Formula'], kpiRows), 's' + si++));
}

var terms = ctx.terms_and_definitions || [];
if (terms.length) {
    var termRows = terms.map(function(t) { return { Term: t.term || '', Definition: t.definition || '' }; });
    secs.push(section('Terms & Definitions', tbl(['Term', 'Definition'], termRows), 's' + si++));
}

var records = ctx.records || [];
if (records.length) {
    var recRows = records.map(function(r) { return { Title: r.title || '', Medium: r.medium || '', Location: r.location || '' }; });
    secs.push(section('Records', tbl(['Title', 'Medium', 'Location'], recRows), 's' + si++));
}

var refs = ctx.references || [];
if (refs.length) {
    secs.push(section('References', bullets(refs), 's' + si++));
}

var interfaces = ctx.interface_table || [];
if (interfaces.length) {
    var ifRows = interfaces.map(function(it) {
        return { Section: it.section || '', Direction: it.direction || '', Name: it.name || '', Interface: it.interface_ref || '' };
    });
    secs.push(section('Interface Table (' + interfaces.length + ' entries)',
        tbl(['Section', 'Direction', 'Name', 'Interface'], ifRows), 's' + si++));
}

/* ── sub-graph links summary ─────────────────────────────── */
var graphData = doc.process_graph || {};
var ovLinks = graphData.overview_to_detail_links || [];
if (ovLinks.length) {
    var linkRows = ovLinks.map(function(lnk) {
        if (lnk._type === 'continuity') {
            return {
                Type: 'Phase Continuity',
                From: (lnk.from_detail_group || '') + ' \u2192 ' + (lnk.from_node_id || ''),
                To:   (lnk.to_detail_group || '') + ' \u2192 ' + (lnk.to_node_id || ''),
                Label: lnk.label || ''
            };
        }
        return {
            Type: 'Overview \u2192 Detail',
            From: (lnk.overview_node_id || '') + ' (' + (lnk.overview_node_label || '') + ')',
            To:   lnk.detail_group_id || '',
            Label: lnk.section_ref || ''
        };
    });
    secs.push(section('Sub-Graph Links (' + ovLinks.length + ')',
        tbl(['Type', 'From', 'To', 'Label'], linkRows), 's' + si++, false));
}

/* ── assemble ────────────────────────────────────────────── */
return h('div', { className: 'space-y-4' },
    h('div', { className: 'bg-white rounded-lg border border-gray-200 px-5 py-4' },
        h('h2', { className: 'text-lg font-bold text-gray-900' }, meta.title || 'Governance Document'),
        h('div', { className: 'flex flex-wrap gap-2 mt-2' },
            badge('ID', meta.id),
            badge('Version', meta.version),
            badge('Classification', meta.classification),
            badge('Department', meta.department)
        )
    ),
    h('div', { className: 'space-y-3' }, secs)
);
"""


CROSS_DOC_VIZ_SCRIPT = r"""
var h = React.createElement;
var crossDoc = data.cross_document_graph || {};
var edges = crossDoc.edges || [];
var deps = crossDoc.document_dependencies || [];
var sharedRoles = crossDoc.shared_roles || [];
var nDocs = (data.documents || []).length;

/* ── helpers ──────────────────────────────────────────────── */
function tbl(cols, rows) {
    if (!rows.length) return null;
    return h('div', { className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
        h('div', { className: 'overflow-x-auto max-h-96' },
            h('table', { className: 'w-full text-xs border-collapse' },
                h('thead', { className: 'bg-gray-50 sticky top-0' },
                    h('tr', null, cols.map(function(c) {
                        return h('th', { key: c, className: 'px-3 py-2 text-left font-medium text-gray-600 border-b' }, c);
                    }))
                ),
                h('tbody', null, rows.map(function(row, ri) {
                    return h('tr', { key: ri, className: ri % 2 === 0 ? 'bg-white' : 'bg-gray-50/50' },
                        cols.map(function(c) {
                            var val = row[c];
                            return h('td', { key: c, className: 'px-3 py-1.5 text-gray-800 border-b border-gray-100' },
                                typeof val === 'object' ? JSON.stringify(val) : String(val || '')
                            );
                        })
                    );
                }))
            )
        )
    );
}

function sectionTitle(t) {
    return h('div', { className: 'text-sm font-semibold text-gray-700 mb-2' }, t);
}

function confidenceBadge(level) {
    var colors = { high: 'bg-emerald-50 text-emerald-700 border-emerald-200',
                   medium: 'bg-amber-50 text-amber-700 border-amber-200',
                   low: 'bg-red-50 text-red-700 border-red-200' };
    var cls = colors[level] || colors.medium;
    return h('span', { className: 'text-xs px-1.5 py-0.5 rounded border ' + cls }, level);
}

/* ── build sections ──────────────────────────────────────── */
var parts = [];

parts.push(
    h('div', { key: 'hdr', className: 'bg-white rounded-lg border border-gray-200 px-5 py-4' },
        h('h2', { className: 'text-lg font-bold text-gray-900' }, 'Cross-Document Process Links'),
        h('p', { className: 'text-sm text-gray-500 mt-1' },
            edges.length + ' process hand-offs detected across ' + nDocs + ' documents'),
        h('div', { className: 'flex flex-wrap gap-2 mt-2' },
            h('span', { className: 'inline-flex items-center text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 border border-blue-200' },
                '\u2194 Hand-offs: ' + edges.length),
            h('span', { className: 'inline-flex items-center text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-600 border border-purple-200' },
                '\u263A Shared Roles: ' + sharedRoles.length),
            h('span', { className: 'inline-flex items-center text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 border border-gray-200' },
                '\u21C4 Dependencies: ' + deps.length)
        )
    )
);

if (edges.length) {
    var edgeRows = edges.map(function(e) {
        return {
            'From Doc': e.from_document || '',
            'From Node': e.from_node_label || '',
            'To Doc': e.to_document || '',
            'To Node': e.to_node_label || '',
            Type: (e.edge_type || '').replace(/_/g, ' '),
            Confidence: e.confidence || '',
            Evidence: e.evidence || ''
        };
    });
    parts.push(h('div', { key: 'edges' },
        sectionTitle('Process Hand-offs'),
        tbl(['From Doc', 'From Node', 'To Doc', 'To Node', 'Type', 'Confidence', 'Evidence'], edgeRows)
    ));
}

if (deps.length) {
    var depRows = deps.map(function(d) {
        return {
            Document: d.document_id || '',
            Title: d.title || '',
            'Depends On': (d.depends_on || []).join(', '),
            'Depended By': (d.depended_by || []).join(', '),
            Reasoning: d.reasoning || ''
        };
    });
    parts.push(h('div', { key: 'deps' },
        sectionTitle('Document Dependencies'),
        tbl(['Document', 'Title', 'Depends On', 'Depended By', 'Reasoning'], depRows)
    ));
}

if (sharedRoles.length) {
    var roleRows = sharedRoles.map(function(r) {
        return {
            Role: r.canonical_name || '',
            'Appears In': (r.appears_in || []).join(', '),
            Note: r.note || ''
        };
    });
    parts.push(h('div', { key: 'roles' },
        sectionTitle('Shared Roles Across Documents'),
        tbl(['Role', 'Appears In', 'Note'], roleRows)
    ));
}

if (!edges.length && !deps.length && !sharedRoles.length) {
    parts.push(
        h('p', { key: 'empty', className: 'text-sm text-gray-500 italic py-4' },
            'No cross-document links were detected between the processed documents.')
    );
}

return h('div', { className: 'space-y-4' }, parts);
"""


def _format_flowchart_spec(title, graph_data, height=600):
    """Build a DSL flowchart spec from graph data."""
    return {
        "type": "flowchart",
        "title": title,
        "height": height,
        "nodes": [
            {
                "id": n.get("id"),
                "label": n.get("label", ""),
                "type": n.get("type", "action"),
                "shape": n.get("shape"),
                "actor": n.get("actor", ""),
                "description": n.get("description", ""),
                "position": n.get("position"),
            }
            for n in graph_data.get("nodes", [])
        ],
        "edges": graph_data.get("edges", []),
        "swimlanes": graph_data.get("swimlanes", []),
    }


def _merge_document_graphs(doc):
    """Merge overview + sub-graphs into a single combined graph.

    Adds linking edges from overview_to_detail_links so the
    overview nodes connect to their detail sub-graph start nodes,
    and detail sub-graphs chain via phase-continuity edges.

    Positions are stripped (each sub-graph has its own 0-1 space)
    so the frontend falls back to dagre auto-layout for the
    unified view.
    """
    graph = doc.get("process_graph", {})
    overview = graph.get("overview", {})
    sub_graphs = graph.get("sub_graphs", [])
    links = graph.get("overview_to_detail_links", [])

    all_nodes = []
    all_edges = []

    for n in overview.get("nodes", []):
        all_nodes.append({
            "id": n.get("id"),
            "label": n.get("label", ""),
            "type": n.get("type", "action"),
            "shape": n.get("shape"),
            "actor": n.get("actor", ""),
            "description": n.get("description", ""),
        })
    all_edges.extend(overview.get("edges", []))

    for sg in sub_graphs:
        for n in sg.get("nodes", []):
            all_nodes.append({
                "id": n.get("id"),
                "label": n.get("label", ""),
                "type": n.get("type", "action"),
                "shape": n.get("shape"),
                "actor": n.get("actor", ""),
                "description": n.get("description", ""),
            })
        all_edges.extend(sg.get("edges", []))

    for lnk in links:
        if lnk.get("_type") == "continuity":
            all_edges.append({
                "from_node": lnk.get("from_node_id", ""),
                "to_node": lnk.get("to_node_id", ""),
                "type": "sequence",
                "label": lnk.get("label", ""),
            })
        else:
            ov_id = lnk.get("overview_node_id", "")
            for start_id in lnk.get("detail_start_nodes", []):
                all_edges.append({
                    "from_node": ov_id,
                    "to_node": start_id,
                    "type": "sequence",
                    "label": f"Detail: {lnk.get('section_ref', '')}",
                })
            for end_id in lnk.get("detail_end_nodes", []):
                all_edges.append({
                    "from_node": end_id,
                    "to_node": ov_id,
                    "type": "sequence",
                    "label": "Return to overview",
                })

    return {"nodes": all_nodes, "edges": all_edges, "swimlanes": []}


def _build_cross_doc_graph(corpus):
    """Build a unified graph spanning ALL documents with cross-doc edges.

    Node IDs are prefixed with ``<doc_id>__`` to avoid collisions.
    Actor labels are prefixed with ``[doc_id]`` to show provenance.
    Per-document internal linking edges are also included.
    """
    docs = corpus.get("documents", [])
    cross_doc = corpus.get("cross_document_graph", {})

    all_nodes = []
    all_edges = []
    doc_id_map = {}

    for doc in docs:
        if doc.get("error"):
            continue
        meta = doc.get("document_metadata", {})
        doc_id = meta.get("id", "unknown")
        doc_id_map[doc_id] = meta.get("title", doc_id)
        prefix = doc_id.replace("-", "_").replace(" ", "_") + "__"

        graph = doc.get("process_graph", {})

        def _add_nodes(nodes, prefix, doc_id):
            for n in nodes:
                all_nodes.append({
                    "id": prefix + n.get("id", ""),
                    "label": n.get("label", ""),
                    "type": n.get("type", "action"),
                    "shape": n.get("shape"),
                    "actor": f"[{doc_id}] {n.get('actor', '')}",
                    "description": n.get("description", ""),
                })

        def _add_edges(edges, prefix):
            for e in edges:
                all_edges.append({
                    "from_node": prefix + e.get("from_node", ""),
                    "to_node": prefix + e.get("to_node", ""),
                    "type": e.get("type", "sequence"),
                    "condition": e.get("condition"),
                    "label": e.get("label"),
                })

        overview = graph.get("overview", {})
        _add_nodes(overview.get("nodes", []), prefix, doc_id)
        _add_edges(overview.get("edges", []), prefix)

        for sg in graph.get("sub_graphs", []):
            _add_nodes(sg.get("nodes", []), prefix, doc_id)
            _add_edges(sg.get("edges", []), prefix)

        for lnk in graph.get("overview_to_detail_links", []):
            if lnk.get("_type") == "continuity":
                all_edges.append({
                    "from_node": prefix + lnk.get("from_node_id", ""),
                    "to_node": prefix + lnk.get("to_node_id", ""),
                    "type": "sequence",
                    "label": lnk.get("label"),
                })
            else:
                ov_id = lnk.get("overview_node_id", "")
                for sid in lnk.get("detail_start_nodes", []):
                    all_edges.append({
                        "from_node": prefix + ov_id,
                        "to_node": prefix + sid,
                        "type": "sequence",
                        "label": f"Detail: {lnk.get('section_ref', '')}",
                    })

    for edge in cross_doc.get("edges", []):
        from_prefix = edge.get("from_document", "").replace("-", "_").replace(" ", "_") + "__"
        to_prefix = edge.get("to_document", "").replace("-", "_").replace(" ", "_") + "__"
        from_node = edge.get("from_node_id", "")
        to_node = edge.get("to_node_id", "")
        if from_node and to_node:
            all_edges.append({
                "from_node": from_prefix + from_node,
                "to_node": to_prefix + to_node,
                "type": "escalation",
                "label": (edge.get("edge_type", "hand-off") or "hand-off").replace("_", " "),
            })

    return {"nodes": all_nodes, "edges": all_edges, "swimlanes": []}


def _build_doc_viz(doc, doc_index):
    """Build visualization spec list for a single document."""
    graph = doc.get("process_graph", {})

    specs = []

    specs.append({
        "type": "render",
        "script": DOC_SECTIONS_SCRIPT.replace("__IDX__", str(doc_index)),
    })

    combined = _merge_document_graphs(doc)
    if combined["nodes"]:
        n_total = len(combined["nodes"])
        e_total = len(combined["edges"])
        n_subs = len(graph.get("sub_graphs", []))
        title = f"Complete Process Flow ({n_total} nodes, {e_total} edges"
        if n_subs:
            title += f", {n_subs} sub-graphs linked"
        title += ")"
        specs.append(_format_flowchart_spec(title, combined, height=800))

    return specs


def build_visualization(corpus):
    """Build the complete visualization spec list from corpus output."""
    docs = corpus.get("documents", [])
    cross_doc = corpus.get("cross_document_graph", {})

    if len(docs) == 1:
        return _build_doc_viz(docs[0], 0)

    tabs = []
    for i, doc in enumerate(docs):
        meta = doc.get("document_metadata", {})
        title = meta.get("title", f"Document {i + 1}")
        doc_id = meta.get("id", "")
        label = f"{title} ({doc_id})" if doc_id else title
        if len(label) > 50:
            label = label[:47] + "..."
        tabs.append({
            "label": label,
            "content": _build_doc_viz(doc, i),
        })

    cross_content = [{"type": "render", "script": CROSS_DOC_VIZ_SCRIPT}]
    unified = _build_cross_doc_graph(corpus)
    if unified["nodes"]:
        cross_content.append(_format_flowchart_spec(
            f"Unified Process Graph ({len(unified['nodes'])} nodes, {len(unified['edges'])} edges)",
            unified,
            height=1000,
        ))
    tabs.append({
        "label": "Cross-Document Links",
        "content": cross_content,
    })

    corpus_meta = corpus.get("corpus_metadata", {})
    return [
        {
            "type": "header",
            "title": "Governance Document Corpus",
            "subtitle": f"{corpus_meta.get('total_documents', len(docs))} documents processed",
            "badges": {
                "With Graphs": str(corpus_meta.get("documents_with_graphs", 0)),
                "Cross-Doc Edges": str(len(cross_doc.get("edges", []))),
            },
        },
        {"type": "tabs", "tabs": tabs},
    ]


# ═══════════════════════════════════════════════════════════════
# Single-Document Pipeline
# ═══════════════════════════════════════════════════════════════

def process_single_document(pdf_path):
    """Run the full pipeline on one PDF and return the assembled result.

    Execution waves (maximises parallelism):
      Wave 1 (parallel): classify_pages + content + procedure  [3× Haiku]
      Wave 2 (parallel): overview + detail sub-graphs           [N× Sonnet]
                          + stitch                              [1× Haiku]
      Wave 3:            text-to-node linking                   [1× Sonnet]
    """
    filename = pdf_path.rsplit("/", 1)[-1] if "/" in pdf_path else pdf_path
    t0 = time.time()

    print(f"  Phase 1 · Extracting text...")
    full_text, total_pages, page_texts = extract_pdf(pdf_path)
    print(f"  \u2713 {total_pages} pages, {len(full_text)} characters")

    # ── Wave 1: three independent Haiku calls in parallel ─────
    print(f"  Wave 1 · Parallel: classify + content + procedure (3× Haiku)...")
    w1_start = time.time()
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_classify = pool.submit(classify_pages, page_texts)
        f_content = pool.submit(extract_document_content, full_text)
        f_procedure = pool.submit(extract_procedure_details, full_text)

    groups = f_classify.result()
    content = f_content.result()
    procedures = f_procedure.result()
    w1_elapsed = time.time() - w1_start

    if groups:
        summary = "; ".join(f"{g['group_id']}({g['group_type']}) pp.{g['page_nums']}" for g in groups)
        print(f"  \u2713 Wave 1 done ({w1_elapsed:.1f}s) — groups: {summary}")
    else:
        print(f"  \u2713 Wave 1 done ({w1_elapsed:.1f}s) — no graph pages, will try full-doc extraction")
    print(f"    Content: {len(content.get('roles', []))} roles, {len(content.get('kpis', []))} KPIs")
    print(f"    Procedure: {len(procedures.get('sections', []))} sections")

    # ── Wave 2: graph extraction (depends on classify) ────────
    print(f"  Wave 2 · Multi-graph extraction (Sonnet, parallel sub-graphs)...")
    w2_start = time.time()
    graph_data = extract_all_graphs(full_text, page_texts, groups)
    w2_elapsed = time.time() - w2_start
    ov_nodes = len(graph_data.get("overview", {}).get("nodes", []))
    n_subs = len(graph_data.get("sub_graphs", []))
    print(f"  \u2713 Wave 2 done ({w2_elapsed:.1f}s) — Overview: {ov_nodes} nodes, Sub-graphs: {n_subs}")

    # ── Wave 3: linking (depends on all above) ────────────────
    print(f"  Wave 3 · Text-to-node linking (Sonnet)...")
    w3_start = time.time()
    linking = link_text_to_nodes(graph_data, content, procedures)
    w3_elapsed = time.time() - w3_start
    n_mapped = len(linking.get("node_content_mapping", []))
    n_unmapped = len(linking.get("unmapped_text", []))
    print(f"  \u2713 Wave 3 done ({w3_elapsed:.1f}s) — {n_mapped} nodes mapped, {n_unmapped} unmapped")

    elapsed = time.time() - t0
    print(f"  Phase 4  · Assembling output ({elapsed:.1f}s total)")

    result = assemble_output(
        graph_data, content, procedures, linking,
        source_file=filename,
        total_pages=total_pages,
    )
    return result


# ═══════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════

uploaded = output.ask(
    "Upload one or more governance / procedure PDF documents to parse.\n"
    "Multiple files will be processed individually, then cross-linked.",
    type="file",
    accept=".pdf",
    multiple=True,
)
files_to_process = uploaded if isinstance(uploaded, list) else [uploaded]

print(f"Processing {len(files_to_process)} document(s)...\n")

def _process_and_save(pdf_path, index, total):
    """Process one document and save its JSON. Returns (index, result)."""
    filename = pdf_path.rsplit("/", 1)[-1] if "/" in pdf_path else pdf_path
    print(f"\u2501\u2501\u2501 Document {index + 1}/{total}: {filename} \u2501\u2501\u2501")
    try:
        result = process_single_document(pdf_path)
        safe_name = filename.replace(".pdf", "").replace(" ", "_")
        out_path = f"/outputs/{safe_name}_parsed.json"
        with io.open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"  \u2713 Saved \u2192 {out_path}\n")
        return index, result
    except Exception as exc:
        print(f"  \u2717 FAILED: {exc}\n")
        return index, {
            "document_metadata": {"id": filename, "title": filename},
            "error": str(exc),
        }

all_results = [None] * len(files_to_process)

if len(files_to_process) == 1:
    _, all_results[0] = _process_and_save(files_to_process[0], 0, 1)
else:
    n_docs = len(files_to_process)
    print(f"Processing {n_docs} documents in parallel...\n")
    with ThreadPoolExecutor(max_workers=n_docs) as pool:
        futures = {
            pool.submit(_process_and_save, path, i, n_docs): i
            for i, path in enumerate(files_to_process)
        }
        for future in as_completed(futures):
            idx, result = future.result()
            all_results[idx] = result

successful = [d for d in all_results if "error" not in d]

cross_doc = {}
if len(successful) >= 2:
    cross_doc = link_documents(successful)
    n_edges = len(cross_doc.get("cross_document_edges", []))
    print(f"\u2713 Cross-document linking: {n_edges} hand-offs detected\n")
elif len(files_to_process) >= 2:
    print("Skipping cross-document linking (need 2+ successful documents)\n")

corpus = build_corpus_output(all_results, cross_doc)

if len(all_results) > 1:
    corpus_path = "/outputs/corpus_output.json"
    with io.open(corpus_path, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)
    print(f"\u2713 Corpus output saved \u2192 {corpus_path}")

viz = build_visualization(corpus)

corpus_meta = corpus.get("corpus_metadata", {})
output.data(
    data=corpus,
    title=f"Governance Corpus ({corpus_meta.get('total_documents', 1)} documents)",
    visualization=viz,
)

print(f"\nDone \u2014 {len(all_results)} document(s) processed.")
