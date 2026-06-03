"""
Code executor utility routes -- validation, file downloads, midway uploads.
"""
import asyncio
import json
import os
import uuid
from typing import Any, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import logging

from core.dependencies import get_current_user
from db.models import User

logger = logging.getLogger(__name__)

OUTPUT_FILES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "sandbox_output_files"
)

router = APIRouter(
    prefix="/api/code-executor",
    tags=["Code Executor"],
)


# ── Validation ──────────────────────────────────────────────────────────

class CodeValidationRequest(BaseModel):
    code: str = Field(..., description="Python source code to validate")
    allowed_imports: list[str] = Field(default_factory=list, description="Additional allowed imports")


class CodeValidationResponse(BaseModel):
    valid: bool
    violations: list[str] = Field(default_factory=list)


@router.post("/validate", response_model=CodeValidationResponse)
async def validate_code(body: CodeValidationRequest):
    """Validate Python code against the sandbox import allowlist."""
    from workflow.sandbox.code_validator import CodeValidator

    validator = CodeValidator(extra_allowed_imports=body.allowed_imports)
    result = validator.validate(body.code)
    return CodeValidationResponse(valid=result.valid, violations=result.violations)


@router.get("/sdk-reference")
async def get_sdk_reference():
    """Return the SDK reference markdown for the documentation panel."""
    content = await asyncio.to_thread(_load_sdk_reference)
    return {"content": content}


# ── Sandbox pool observability ────────────────────────────────────────────

@router.get("/sandbox-pool-status")
async def sandbox_pool_status(
    current_user: User = Depends(get_current_user),
):
    """Return a snapshot of the sandbox warm-pool state.

    Useful when a code executor run is slow to acquire or fails -- surfaces
    the pool's target/current size, this worker's active count, in-flight
    provisions, and the last few Azure/registry errors (helpful during
    ACR / DNS outages).

    The endpoint is read-only; it never mutates pool state.
    """
    from workflow.sandbox.sandbox_provider import get_sandbox_provider

    provider = get_sandbox_provider()
    try:
        snapshot = await provider.pool_status()
    except Exception as exc:  # defensive — never 500 on an observability call
        logger.warning("pool_status failed: %s", exc)
        snapshot = {
            "provider": type(provider).__name__,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return snapshot


# ── Knowledge Base tables (for the editor side panel + AI generator) ───

class _KbColumnInfo(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    nullable: bool = True


class _KbTableInfo(BaseModel):
    kb_id: str
    kb_name: str
    schema_name: str
    table: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    row_count: int = 0
    columns: list[_KbColumnInfo] = Field(default_factory=list)


class KbTablesListResponse(BaseModel):
    tables: list[_KbTableInfo]


@router.get("/kb-tables", response_model=KbTablesListResponse)
async def list_kb_tables_for_editor(
    kb_ids: str = "",
    current_user: User = Depends(get_current_user),
) -> KbTablesListResponse:
    """Return structured table metadata for every KB the user can access.

    Used by the Code Editor's tables panel and the AI code generator when
    it needs to splice schemas into the system prompt. The comma-separated
    ``kb_ids`` is a filter -- KBs that aren't in the caller's RLS-visible
    set are silently dropped.
    """
    from db.pgsql import get_write_db as _get_write_db
    from repositories.knowledge_base_repository import KnowledgeBaseRepository
    from repositories.structured_data_repository import StructuredDataRepository

    requested = [k.strip() for k in (kb_ids or "").split(",") if k.strip()]
    if not requested:
        return KbTablesListResponse(tables=[])

    async for db in _get_write_db():
        kb_repo = KnowledgeBaseRepository(db)
        structured_repo = StructuredDataRepository(db)
        out: list[_KbTableInfo] = []
        for kb_id in requested:
            kb = await kb_repo.get_by_id(kb_id)
            if kb is None:
                continue  # RLS hid it — skip silently
            try:
                tables = await structured_repo.get_tables_for_kb(kb_id)
            except Exception as exc:
                logger.warning("Failed to list tables for KB %s: %s", kb_id, exc)
                continue
            for t in tables:
                cols = [
                    _KbColumnInfo(
                        name=c.column_name,
                        type=(
                            c.data_type.value
                            if hasattr(c.data_type, "value")
                            else str(c.data_type)
                        ),
                        description=c.description or None,
                        nullable=bool(c.nullable),
                    )
                    for c in (t.columns or [])
                ]
                out.append(
                    _KbTableInfo(
                        kb_id=kb_id,
                        kb_name=kb.name or kb_id,
                        schema_name=t.schema_name,
                        table=t.table_name,
                        display_name=t.display_name or t.table_name,
                        description=t.description or None,
                        row_count=int(t.row_count or 0),
                        columns=cols,
                    )
                )
        return KbTablesListResponse(tables=out)


# ── Output file downloads ───────────────────────────────────────────────

MIME_OVERRIDES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".csv": "text/csv",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


@router.get("/files/{execution_id}/{node_id}/{filename}")
async def download_output_file(
    execution_id: str,
    node_id: str,
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Serve a file that was produced by a code executor run.

    Checks Azure Blob first (production); falls back to local filesystem (dev).
    When the file lives in blob storage, returns a redirect to a short-lived SAS URL.
    """
    safe_name = os.path.basename(filename)

    blob_path = f"sandbox-outputs/{execution_id}/{node_id}/{safe_name}"
    try:
        from core.dependencies import get_storage_connector
        connector = get_storage_connector()
        if connector is not None:
            from datetime import datetime, timedelta, timezone
            from azure.storage.blob import generate_blob_sas, BlobSasPermissions

            blob_client = connector._blob_service_client.get_blob_client(
                container=connector.container_name,
                blob=blob_path,
            )
            if blob_client.exists():
                sas_token = generate_blob_sas(
                    account_name=blob_client.account_name,
                    container_name=connector.container_name,
                    blob_name=blob_path,
                    account_key=connector._account_key if hasattr(connector, "_account_key") else None,
                    user_delegation_key=None,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.now(timezone.utc) + timedelta(minutes=15),
                )
                sas_url = f"{blob_client.url}?{sas_token}"
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url=sas_url, status_code=302)
    except Exception as exc:
        logger.debug("Blob lookup failed (falling back to local): %s", exc)

    filepath = os.path.normpath(
        os.path.join(OUTPUT_FILES_DIR, execution_id, node_id, safe_name)
    )
    if not filepath.startswith(os.path.normpath(OUTPUT_FILES_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    ext = os.path.splitext(safe_name)[1].lower()
    media_type = MIME_OVERRIDES.get(ext, "application/octet-stream")

    return FileResponse(
        filepath,
        media_type=media_type,
        filename=safe_name,
    )


# ── Midway file uploads (output.ask(type="file")) ───────────────────
#
# Uploads stream straight to Azure Blob Storage (ADLS) via the shared
# ``AzureStorageConnector``.  The response includes a ``blob_name``
# pointer that the FE echoes back on resume; the Code Executor then
# pulls the bytes from blob into the sandbox before re-running.  The
# backend pod's local filesystem is never touched, so pod restarts and
# multi-replica backends no longer lose uploads.


@router.post("/upload-midway")
async def upload_midway_file(
    file: UploadFile = File(...),
    deliverable_id: str = Form(""),
    current_user: User = Depends(get_current_user),
):
    """Accept a file uploaded in response to ``output.ask(type='file')``.

    The file is streamed into Azure Blob Storage under a per-user,
    per-upload path (see ``code_executor_storage.midway_blob_name``).
    We return the opaque ``blob_name`` to the FE, which echoes it back
    when the user submits their pause response; the Code Executor
    downloads the blob at resume time to inject into ``/workspace/uploads``.
    """
    from workflow import code_executor_storage as ce_storage

    upload_id = str(uuid.uuid4())
    safe_name = os.path.basename(file.filename or "upload")
    content = await file.read()

    blob_name = await ce_storage.upload_midway(
        user_id=str(current_user.id),
        upload_id=upload_id,
        filename=safe_name,
        data=content,
        content_type=file.content_type,
    )
    if not blob_name:
        raise HTTPException(
            status_code=503,
            detail=(
                "Midway file storage is unavailable.  The upload could not be "
                "persisted, so the Code Executor cannot resume from this pause. "
                "Retry shortly; if the problem persists, report the execution ID "
                "and the time of the failure."
            ),
        )

    logger.info(
        "Midway upload stored: %s (%d bytes) blob=%s deliverable=%s user=%s",
        safe_name, len(content), blob_name, deliverable_id, current_user.id,
    )

    return {
        "upload_id": upload_id,
        "filename": safe_name,
        "size": len(content),
        "blob_name": blob_name,
    }


# ── AI Code Generation ──────────────────────────────────────────────────

_SDK_REFERENCE: str | None = None
_SDK_REFERENCE_MTIME: float | None = None
_SDK_REFERENCE_PATH: str | None = None


def _load_sdk_reference() -> str:
    """Load SDK_REFERENCE.md, re-reading if the source file has changed.

    The reference feeds BOTH the Docs panel (via GET /sdk-reference) AND the
    AI code-generator's system prompt, so an edit to the markdown needs to
    take effect immediately in dev without a server restart.  We cache by
    file mtime and fall through to stale content only if the file vanishes.
    """
    global _SDK_REFERENCE, _SDK_REFERENCE_MTIME, _SDK_REFERENCE_PATH
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "SDK_REFERENCE.md"),
        os.path.join(os.path.dirname(__file__), "..", "..", "sandbox-image", "SDK_REFERENCE.md"),
    ]
    for ref_path in candidates:
        try:
            mtime = os.path.getmtime(ref_path)
        except OSError:
            continue
        # Hit -- reuse cached content when the file hasn't changed since the
        # last read.  This keeps the hot path cheap on every code-gen call.
        if (
            _SDK_REFERENCE is not None
            and _SDK_REFERENCE_PATH == ref_path
            and _SDK_REFERENCE_MTIME == mtime
        ):
            return _SDK_REFERENCE
        try:
            with open(ref_path) as f:
                _SDK_REFERENCE = f.read()
                _SDK_REFERENCE_MTIME = mtime
                _SDK_REFERENCE_PATH = ref_path
                return _SDK_REFERENCE
        except FileNotFoundError:
            continue
    if _SDK_REFERENCE is None:
        _SDK_REFERENCE = "(SDK reference not available)"
    return _SDK_REFERENCE


class ChatTurn(BaseModel):
    """A single entry in the multi-turn code-generator conversation history.

    The frontend stores the full session in ``localStorage`` and replays up to
    the last ~20 turns on each request so the LLM retains context across
    back-and-forth edits without us running a session store on the server.
    """
    role: Literal["user", "assistant"]
    content: str = Field(
        "",
        description=(
            "For user turns: the raw prompt text. For assistant turns: a "
            "short human-readable summary (or the clarify question). The full "
            "code body lives on `code` so we can selectively strip it from "
            "older turns to save tokens."
        ),
    )
    kind: Optional[Literal["code", "clarify"]] = Field(
        None,
        description="For assistant turns only — which envelope branch was returned.",
    )
    code: Optional[str] = Field(
        None,
        description="For assistant `kind=code` turns, the full generated Python.",
    )
    summary: Optional[str] = Field(
        None,
        description="For assistant turns, a one-line summary of the change.",
    )
    images: list[str] = Field(
        default_factory=list,
        description="Image attachments the user included on this turn (data URLs).",
    )


class CodeGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Natural language description of what the code should do")
    context: dict = Field(default_factory=dict, description="Optional context: input_mappings, allowed_imports, existing_code, input_schema")
    images: list[str] = Field(
        default_factory=list,
        description=(
            "Optional image attachments for multimodal code generation. Each entry "
            "must be a data URL of the form `data:image/<png|jpeg|webp|gif>;base64,<data>`. "
            "Used by the LLM as visual reference (e.g. a dashboard screenshot to replicate)."
        ),
    )
    chat_history: list[ChatTurn] = Field(
        default_factory=list,
        description=(
            "Prior turns in this code-generator conversation, oldest first. "
            "The server trims / serializes them into the LLM messages so the "
            "model can continue a multi-turn refinement."
        ),
    )
    knowledge_base_ids: Optional[list[str]] = Field(
        default=None,
        description=(
            "Knowledge Bases configured on this Code Executor node. When set, "
            "the server splices each KB's semantic model (tables, columns, "
            "sample rows) into the system prompt so the LLM writes accurate "
            "`knowledge_base.read_table()` / `knowledge_base.query()` calls."
        ),
    )


class CodeGenerationResponse(BaseModel):
    """Typed envelope returned by ``/generate-code``.

    ``kind`` discriminates between a code reply and a clarifying question. We
    keep both families in a single flat model (rather than a discriminated
    union) so the frontend and any legacy consumer can read whatever fields
    they care about without crashing on the other branch's defaults.
    """
    kind: Literal["code", "clarify"] = Field(
        "code",
        description="'code' = an applied-to-editor code reply; 'clarify' = amber question card.",
    )

    # kind="code" fields
    code: str = Field("", description="Generated Python code (empty when kind='clarify')")
    summary: str = Field("", description="One-line human summary of what changed")
    explanation: str = Field(
        "",
        description=(
            "Legacy alias of `summary` kept for older frontends; mirrors "
            "`summary` for kind='code' and `question` for kind='clarify'."
        ),
    )
    assumptions: list[str] = Field(default_factory=list)
    valid: bool = Field(True, description="Whether the code passes validation")
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Non-blocking quality issues flagged by the LLM judge. The code "
            "is still valid and runnable; warnings are surfaced so the user "
            "can decide whether to refine or accept as-is. Examples: "
            "'consider using output.table instead of building HTML' or "
            "'no error handling around the CSV read'."
        ),
    )
    judge_summary: str = Field(
        "",
        description=(
            "One-line overall assessment from the LLM judge, when it ran. "
            "Empty if judging was disabled or the judge call failed."
        ),
    )

    # kind="clarify" fields
    question: str = Field("", description="Clarifying question text (when kind='clarify')")
    options: list[str] = Field(
        default_factory=list,
        description="Optional quick-reply chips the user can tap to answer.",
    )


_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert Python code generator for the Agent Studio sandbox environment.

## Response envelope (CRITICAL — read this first)

Every reply MUST be a SINGLE JSON object.  No markdown fences, no prose
before or after the object.  Pick exactly one of the two ``kind`` values.

**kind = "code"** — you are producing or editing the Python for this node.
This is the default; prefer it whenever you can.

    {"kind": "code",
     "summary": "<one short line describing what changed, <=80 chars>",
     "code": "<complete Python file as a JSON string; escape newlines as \\n>",
     "assumptions": ["<optional: assumptions you made to fill gaps>"]}

**kind = "clarify"** — you genuinely cannot start without more info.  Use
this sparingly (see "When to clarify" below).

    {"kind": "clarify",
     "question": "<one focused question>",
     "options": ["<optional chip labels the user can tap as a reply>"]}

Rules for the envelope:
- Emit ONLY the JSON object.  No preamble, no ```json fences, no trailing
  prose.  The host ``json.loads``-es your reply directly.
- The ``code`` field must contain a COMPLETE Python file — not a diff, not a
  patch, not a snippet.  The client replaces the entire editor buffer with
  whatever you send.
- Keep ``summary`` short and action-oriented: "Add horizontal bar chart of
  regions", "Switch colour scheme to reds", "Fix KeyError on missing column".
- ``assumptions`` is optional but encouraged whenever you made a non-obvious
  choice (column names you guessed, a default threshold, etc.).

## When to clarify — soft gating (Cursor-style)

**Default to producing code.**  A ``kind="code"`` reply with a sensible
assumption is almost always better than stalling the user with a question.
They can refine on the next turn.

Ask a clarifying question ONLY when ALL three are true:
1. The intent is fundamentally ambiguous (e.g. "dedupe these rows" without
   saying what key).
2. You cannot write defensive code that covers the reasonable cases.
3. Guessing would likely waste a turn because the wrong guess produces a
   visibly wrong result (not just a harmless default).

Also clarify when the user explicitly asks for your opinion ("what chart
type would you use?", "should I group by A or B?").

Clarify questions MUST:
- Be ONE focused question.  No open-ended checklists.
- Provide ``options`` chips whenever the answer is a pick from a small set.
- Not be a substitute for defensive coding.  "What if the column is missing?"
  is NOT a clarify — you should emit ``if "col" in df: ...`` instead.

When in doubt: emit ``kind="code"`` with an ``assumptions`` list.

## Multi-turn context

The ``messages`` array you're given includes the full conversation for this
code-executor node so far, oldest first.  Previous assistant turns are shown
as their envelopes (``{"kind": ..., ...}``), and older code bodies may be
stripped to just a ``summary`` to save tokens.  Treat follow-up user turns
as *deltas* on the most recent code — "make it horizontal" means modify the
last ``code`` you produced, not start over.

## SDK Reference
{sdk_reference}

## Architecture — each node is isolated
- Each code executor runs in its own disposable sandbox container.
- There are NO pre-existing files in the sandbox. The `/workspace/uploads/` folder starts empty.
- The ONLY way a node receives files is if the user uploads them during execution
  using `output.ask(prompt="...", type="file")` (single file) or
  `output.ask(prompt="...", type="file", multiple=True)` (multiple files).
  The returned value is the sandbox path(s) to the uploaded file(s).
- After `output.ask()` returns a path, you read the file with pandas/openpyxl/fitz
  etc., NOT with `uploads.get()`.  `uploads.get()` is only for files injected by
  the workflow host at startup (rare).
- Upstream data from previous workflow steps arrives ONLY via `inputs["deliverables"]`
  — a list of dicts, each with `agent_label`, `agent_type`, and `data`.

## Sandbox enforcement — this is checked statically BEFORE your code runs

Any code that violates the rules below is rejected by a static AST validator
and will never execute.  Stay strictly inside this list.

### Allowed imports (exhaustive — nothing else is permitted)
{allowed_imports_list}

### Blocked imports (do NOT emit, even inside try/except)
{blocked_imports_list}

### Blocked built-ins / calls
{blocked_calls_list}

### Blocked attribute chains
{blocked_attr_chains_list}

### Blocked attribute access
Do not access dunders like `__subclasses__`, `__globals__`, `__builtins__`,
`__code__`, `__class__`, `__mro__`, `__bases__`, `__reduce__`, `__import__`,
`__loader__`, `__spec__`.

If you find yourself reaching for a blocked module (e.g. `traceback` is
allowed but `logging` is not, `pathlib` is blocked so use `os.path`-style
string handling with just the stdlib `string` module or the path returned by
`output.ask`), rewrite the logic with an allowed module.  Never attempt to
smuggle one in via `__import__`, `eval`, `exec`, base64-decoded strings, or
attribute tricks — every one of those patterns is detected and rejected.

## Forbidden patterns — instant rejection (READ THIS BEFORE WRITING CODE)

The static validator and the runtime guard reject these patterns regardless
of what the user asked for.  They are listed first because they are the
single biggest failure mode of LLM-generated code in this product.

### A. NEVER ship HTML/markup through the `data` payload

`output.data(data, ...)` has TWO arguments for a reason: `data` is a
clean, structured, JSON-serialisable payload that downstream nodes,
agents, and the AI consume programmatically.  `visualization` is the
human-facing rendering.  Putting markup in `data` poisons every consumer
that touches the deliverable.

Forbidden field names anywhere in `data` (instant rejection):
`html`, `html_base64`, `html_b64`, `html_content`, `html_string`,
`rendered_html`, `markup`, `dom_string`, `iframe`, `iframe_src`,
`script`, `script_html`, `raw_html`, `page_html`, `full_html`.

Forbidden content in any `data` string value: HTML markup
(`<!doctype`, `<html`, `<body`, `<script`, `<iframe`, `<style>`),
base64-encoded HTML/JS pages, full-document blobs > ~4 KB.

### B. NEVER build HTML in Python with f-strings

Patterns like
```python
table_html = f"<tr><td>{row['name']}</td></tr>"   # REJECTED
```
fail validation: the static parts of an f-string that contain HTML tags
are detected by the AST validator.  This is also the most common XSS
sink — interpolated values from CSVs / user inputs render as live HTML.
Use `output.table(rows)` or `{"type": "table", "rows": [...]}` and let
the frontend escape values for you.

### C. NEVER smuggle HTML into render scripts

The `{"type": "render", "script": "..."}` escape hatch is JavaScript
that returns a `React.createElement(...)` tree.  It is NOT an iframe
loader, NOT a DOM injector, NOT a code-eval surface.

Forbidden tokens inside any render `script` (statically detected):
`srcDoc`, `<iframe`, `.innerHTML`, `.outerHTML`, `dangerouslySetInnerHTML`,
`document.write`, `atob(`, `eval(`, `new Function(`, `Function(`.

The "build HTML in Python → base64-encode → atob in JS → load into
iframe.srcDoc" pattern is the loophole this rule exists to close.  It
is detected at three layers (Python AST, JS-token scan, runtime payload
check).  Do not reach for it.

### D. Worked anti-example vs. correct shape

```python
# ───── DO NOT DO THIS ─────
html = f"<table>...{row['user_input']}...</table>"     # rule B (HTML f-string)
b64 = base64.b64encode(html.encode()).decode()
output.data(
    {"html_base64": b64, "summary": {...}},            # rule A (forbidden field)
    visualization=[{
        "type": "render",
        "script": (
            "const html = atob(data.html_base64);"
            "return React.createElement('iframe',"
            "  {srcDoc: html, sandbox: 'allow-scripts'});"
        ),                                              # rule C (atob, srcDoc, iframe)
    }],
)

# ───── DO THIS INSTEAD ─────
output.data(
    {                                                   # clean, structured
        "matrix":  matrix_df.to_dict(orient="records"),
        "agg":     agg_sorted.to_dict(orient="records"),
        "summary": {"total": 42, "aligned": 30},
    },
    title="Tourism Diagnostic",
    visualization=[                                     # rendering hints
        {"type": "header", "title": "Tourism Diagnostic"},
        {"type": "grid", "columns": 4, "children": [
            {"type": "metric", "label": "Total",   "value": 42},
            {"type": "metric", "label": "Aligned", "value": 30, "trend": "up"},
            {"type": "metric", "label": "Gaps",    "value": 12, "trend": "down"},
            {"type": "metric", "label": "Critical","value":  3, "trend": "down"},
        ]},
        {"type": "table",
         "title":   "Capacity",
         "rows":    [...],
         "columns": ["offering", "capacity", "est_visits", "gap_ratio", "flag"]},
        {"type": "chart",
         "chart_type": "bar",
         "chart_data": [...],
         "x_label": "offering",
         "y_label": "gap_ratio"},
    ],
)
```

If the 13 DSL primitives genuinely can't express the layout, drop a
SINGLE `{"type": "render", "script": "..."}` spec whose JS body builds
the UI with `React.createElement` and `Recharts`.  The script receives
`data` (your clean payload), `React`, and `Recharts` as arguments.  No
iframes, no innerHTML, no atob.

## Rules
1. Emit ONLY imports from the allowed list above. Any other import will fail
   validation and your code will never run.
2. Access upstream data via `inputs["deliverables"][i]["data"]`.
3. You MUST call exactly one **non-pause** `output.*` method (e.g.
   `output.data(...)`, `output.table(...)`, `output.file(...)`) to emit the
   terminal result.  Mid-script pauses (`output.ask`, `output.selection`,
   `output.list`, `output.form`) are separate — you may call any number of
   them to collect user input, then emit the final result afterwards.
4. If the task requires a file, use `output.ask(type="file")` to request the upload
   BEFORE trying to read it. Always check the returned path is valid.
5. Use `llm.complete()` when the task requires AI/NLP processing.
6. Handle errors gracefully with try/except and informative `output.data()` error messages.
7. Use `print()` for debug logging (appears in execution logs).
8. Do NOT use `open()` for output — use the SDK `output.*` methods. You CAN use
   `open()` in read mode to read a file returned by `output.ask(type="file")`.
9. Write clean, well-structured Python. Add a brief top-level comment explaining intent.
10. Always start with `from agent_studio import output` (and `uploads`, `llm` if needed).
11. **Interactive input — ALWAYS CAPTURE THE RETURN VALUE (CRITICAL)**:
    `output.ask`, `output.selection`, `output.list`, and `output.form` all
    **pause the script** and **return** the user's answer.  You MUST assign
    the result to a variable and use it downstream.  Writing them as bare
    statements (e.g. `output.selection(...)` with no `x = ...`) leaves the
    answer unused and produces a broken script.  Examples::

        plan   = output.selection(prompt=..., options=[...])
        kept   = output.list(items, mode="eliminate")
        cfg    = output.form(prompt=..., fields=[...])
        name   = output.ask("Your name?")

    Multi-select detection: if the user's prompt asks for *multiple*,
    *several*, *a few*, *any of*, *all that apply*, *checkboxes*, or
    otherwise implies picking more than one option, you MUST use
    `output.selection(..., allow_multiple=True)` (fixed options) or
    `output.list(items, mode="pick_many")` (runtime-computed options).
    Default single-select is wrong in those cases. See the "Intent →
    primitive cheat-sheet" in the SDK Reference for the full mapping.
12. **JS-first / render-first mode (CRITICAL)**: if the user's prompt
    contains cues like *"write (it) in JS"*, *"in JavaScript"*, *"all in
    JS"*, *"use JS"*, *"JS render"*, *"custom render"*, *"use
    `render`"*, *"use `React.createElement`"*, *"use Recharts
    directly"*, *"no native primitives"*, *"don't use the DSL"*,
    *"manually render"*, *"hand-rolled UI"*, or anything equivalent,
    you MUST NOT use native DSL primitives for the visible UI.  That
    means: no `{"type": "metric"}`, no `{"type": "chart"}`, no
    `{"type": "table"}`, no `{"type": "header"}`, no `{"type":
    "accordion"}`, no `{"type": "divider"}`, etc.  Instead emit a
    SINGLE top-level `{"type": "render", "script": "..."}` whose JS
    body builds the ENTIRE UI (KPI tiles, headers, dividers, tables,
    charts, tabs, accordions -- everything) with `React.createElement`
    and Recharts.  The `payload` passed to `output.data(...)` stays
    clean and semantic because downstream nodes still consume it.
    The native DSL is the fallback for these prompts, not the default.
    See the "Intent → mode" section of the SDK Reference's `render`
    docs for the full cheat-sheet and a worked dashboard example.

## Brand styling — Strategy& visualisation tokens (MANDATORY)

Every visualisation that exposes colours or fonts MUST use the tokens
below.  Tailwind defaults (`#3B82F6` blue, `#22C55E` green, `#EF4444`
red, etc.) and ad-hoc hex codes are prohibited unless the user
explicitly asks for a different palette.  This is checked by the
post-generation reviewer; non-conforming code is sent back for a fix.

### Colour palette

```python
DATA_COLORS = [        # use IN ORDER for chart series; cycle if N > 8
    "#A32020", "#7A1818", "#EA9595", "#F4CACA",
    "#DB536A", "#BA2741", "#464646", "#7D7D7D",
]
TABLE_ACCENT  = "#82141E"  # table headers, header bars, badges, accents
SEMANTIC_BAD  = "#D64554"  # losses, gaps, alerts, "below threshold"
SEMANTIC_GOOD = "#1AAB40"  # gains, on-track, "above threshold"
FOREGROUND    = "#FFFFFF"  # text on dark backgrounds
BACKGROUND    = "#7F7F7F"  # only for explicit panel BG; do NOT
                           # override the page's own background
```

Rules:
- Sequential chart series (bar/line/area/pie segments) → assign
  `DATA_COLORS[0]`, `DATA_COLORS[1]`, … in order.  Never sample
  arbitrarily from the palette.
- Up/down, good/bad, gain/loss, healthy/critical, on-track/at-risk →
  `SEMANTIC_GOOD` and `SEMANTIC_BAD`.  Never `#22C55E` for green or
  `#EF4444` for red.
- Table headers, header bars, primary callouts → `TABLE_ACCENT`.
- Heatmap colour scales → interpolate within `DATA_COLORS` (the red
  ramp).  For 3-stop semantic scales (low/medium/high risk) use
  `SEMANTIC_BAD` → `#7D7D7D` (neutral grey) → `SEMANTIC_GOOD`.
- Single-colour highlight → `DATA_COLORS[0]` (`#A32020`).

### Typography

| Role        | font-family | font-size |
|-------------|-------------|-----------|
| label, body | Arial       | inherit   |
| callout     | Arial       | 26px      |
| title       | Arial       | 14px      |
| header      | Georgia     | 14px      |

In render scripts: set `style={fontFamily: 'Arial'}` on body, titles,
and metric callouts; set `style={fontFamily: 'Georgia'}` on `<h1>`/
`<h2>`/`<h3>` headers.  Do NOT import or `@import` additional web fonts
— the platform only ships Arial and Georgia for these tokens.

### No emojis — anywhere

User-visible strings produced by your code MUST NOT contain emoji.  No
✅, ❌, 📊, 📈, 📉, 💡, 🔥, 🎯, 🚦, ⚠, ℹ, 🟢, 🔴, 🟡, ⬆, ⬇, ⭐, 🏆, 🚀,
or any other emoji codepoint.  This applies to:
  - `output.data(title=...)` and every text value inside `visualization`
  - every `output.ask` / `output.selection` / `output.list` /
    `output.form` prompt and option label
  - every literal string inside a render `script`
  - log lines emitted via `print()` (these surface in the execution log)

Use plain text labels instead: `"PASS"` / `"FAIL"`, `"HIGH"` / `"LOW"`,
`"On-track"` / `"At-risk"`, `"Up"` / `"Down"`.  For decorative icons
use SVG line icons via `React.createElement('svg', ...)` inside render
scripts — never an emoji as a string.

### Worked example — branded Recharts bar chart

```python
output.data(
    {"q": ["Q1","Q2","Q3","Q4"], "rev": [120, 145, 138, 160]},
    title="Quarterly revenue",
    visualization=[{
        "type": "render",
        "script": (
            "const { BarChart, Bar, XAxis, YAxis, Tooltip, "
            "  ResponsiveContainer } = Recharts;"
            "const COLORS = ['#A32020','#7A1818','#EA9595','#F4CACA',"
            "  '#DB536A','#BA2741','#464646','#7D7D7D'];"
            "return React.createElement('div', "
            "  {style: {fontFamily: 'Arial'}},"
            "  React.createElement('h2', "
            "    {style: {fontFamily: 'Georgia', fontSize: 14, color: '#82141E'}},"
            "    'Quarterly revenue'),"
            "  React.createElement(ResponsiveContainer, "
            "    {width: '100%', height: 280},"
            "    React.createElement(BarChart, "
            "      {data: data.q.map((q,i)=>({q, rev: data.rev[i]}))},"
            "      React.createElement(XAxis, {dataKey:'q'}),"
            "      React.createElement(YAxis, null),"
            "      React.createElement(Tooltip, null),"
            "      React.createElement(Bar, {dataKey:'rev', fill: COLORS[0]})"
            "    )"
            "  )"
            ");"
        ),
    }],
)
```

### Exceptions — when not to apply the brand palette

- The user explicitly asks for a different palette ("colour-blind
  safe", "use traffic-light colours", "match competitor X's red").
- You are reproducing a chart from a screenshot the user attached.
- A semantic mapping needs more than two colours and the brand
  doesn't define those stops — derive a ramp from the brand
  semantics (`SEMANTIC_BAD` → grey → `SEMANTIC_GOOD`) rather than
  picking arbitrary hues.

In all other cases, the brand tokens are mandatory.

## How to choose an output method
- **Single-shape output** → use the shortcut: `output.table(rows)`,
  `output.chart(type=..., data=...)`, `output.flat_list(items)`, or
  `output.document(...)`.
- **Dashboard / composed output** (header + metrics + chart + table in one
  card) → use `output.data(payload, visualization=[...])` with DSL
  primitives (`header`, `grid`, `metric`, `chart`, `table`, `tabs`,
  `accordion`, `card`, `flowchart`, `list`, `text`, `divider`, `code`).
  Container primitives nest child specs.
- **User explicitly asked for JS / "all in JS" / custom render** → flip
  to render-first mode per Rule 12: emit ONE top-level `{"type":
  "render", "script": "..."}` that builds the whole UI via
  `React.createElement`.  Do not sprinkle native primitives alongside.
- **Nothing built-in fits** (but the user didn't ask for JS) → drop a
  `{"type": "render", "script": "..."}` spec with a tiny
  `React.createElement(...)` snippet that returns a React element.
  Use this sparingly -- only when the 13 primitives can't express the
  layout.
- **File deliverable** → `output.file(path)` or `output.files(*paths)`.
- **Need user input mid-script** → pause with one of:
  `output.ask(...)` (single question),
  `output.selection(...)` (pick one or many from fixed options),
  `output.list(...)` (filter / pick from runtime-computed options),
  `output.form(...)` (multi-field form).
  All four pause the script and return the user's answer (variables are
  checkpointed automatically).  ALWAYS capture the return value.
- Always keep `data` clean and semantic -- downstream nodes receive
  `data` but never see `visualization`.

{extra_context}

Reply with the JSON envelope described at the top of this prompt.  The Python
body goes inside ``code`` (with ``\\n`` escapes for newlines).  No markdown
fences, no prose outside the object.
"""


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


# ── Envelope parsing (kind="code" | "clarify") ─────────────────────────

def _extract_first_json_object(text: str) -> dict | None:
    """Return the first balanced ``{...}`` object parsed from ``text``.

    We scan for top-level braces while respecting string literals and
    backslash escapes so we don't get fooled by a ``{`` that sits inside a
    Python docstring embedded in the ``code`` field.  ``strict=False`` lets us
    tolerate literal newlines inside JSON strings, which Claude occasionally
    produces when it forgets to escape a multi-line code block.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate, strict=False)
                    except json.JSONDecodeError:
                        break
        # Couldn't close at this `{`; try the next one.
        start = text.find("{", start + 1)
    return None


def _parse_envelope(raw: str) -> dict:
    """Parse an LLM response into our typed ``{kind, ...}`` envelope.

    Preference order:

    1. A direct ``json.loads`` of the stripped text (the happy path).
    2. First balanced ``{...}`` object in the text (for stray prose).
    3. Fallback: treat the whole payload as raw Python and wrap it as
       ``{"kind": "code", "code": <raw>, "summary": "Generated code."}`` so
       legacy responses (from before this endpoint emitted JSON) still work.

    The fallback is deliberate.  Claude occasionally ignores the envelope
    instruction and returns bare code -- which is still a perfectly valid
    answer, just not the preferred format.  Treating it as ``kind="code"``
    keeps the UX intact and the validator running.
    """
    stripped = _strip_fences(raw.strip())

    try:
        parsed = json.loads(stripped, strict=False)
        if isinstance(parsed, dict) and parsed.get("kind") in {"code", "clarify"}:
            return parsed
    except json.JSONDecodeError:
        pass

    extracted = _extract_first_json_object(stripped)
    if isinstance(extracted, dict) and extracted.get("kind") in {"code", "clarify"}:
        return extracted

    logger.warning(
        "code-gen LLM response was not a typed envelope; treating as raw code. "
        "First 200 chars: %r",
        stripped[:200],
    )
    return {"kind": "code", "code": stripped, "summary": "Generated code."}


_MAX_HISTORY_TURNS = 20
# Keep full code on the two most-recent assistant turns; older turns retain
# only the summary to keep the prompt budget bounded.
_KEEP_CODE_ON_LAST_N_ASSISTANT_TURNS = 2


def _history_to_messages(history: list[ChatTurn]) -> list[dict]:
    """Render a trimmed chat-history slice into LLM messages.

    Oldest turns are dropped first, then the tail is walked so that only the
    last ``_KEEP_CODE_ON_LAST_N_ASSISTANT_TURNS`` assistant messages retain
    their full ``code`` body -- everything earlier is collapsed to just
    ``{kind, summary}`` to keep token usage bounded on long sessions.
    """
    if not history:
        return []

    trimmed = list(history)[-_MAX_HISTORY_TURNS:]

    assistant_positions = [i for i, t in enumerate(trimmed) if t.role == "assistant"]
    keep_code_on = set(assistant_positions[-_KEEP_CODE_ON_LAST_N_ASSISTANT_TURNS:])

    messages: list[dict] = []
    for i, turn in enumerate(trimmed):
        if turn.role == "user":
            content = _build_user_content(turn.content or "", turn.images or [])
            messages.append({"role": "user", "content": content})
            continue

        # Assistant turn — always serialize as a JSON envelope so the model
        # sees the exact contract it's expected to emit on its next turn.
        envelope: dict = {"kind": turn.kind or "code"}
        if envelope["kind"] == "clarify":
            envelope["question"] = turn.content or turn.summary or ""
        else:
            envelope["summary"] = turn.summary or turn.content or ""
            if turn.code and i in keep_code_on:
                envelope["code"] = turn.code
        messages.append({
            "role": "assistant",
            "content": json.dumps(envelope, ensure_ascii=False),
        })
    return messages


def _extract_text(response) -> str:
    """Return plain text from a langchain AIMessage, handling multi-part content."""
    content = getattr(response, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict):
                parts.append(p.get("text") or "")
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    return content or ""


def _get_finish_reason(response) -> str:
    """Normalize finish/stop reason across OpenAI-compat and Anthropic-native responses."""
    metadata = getattr(response, "response_metadata", None) or {}
    # OpenAI-compat proxies: `finish_reason` ∈ {"stop", "length", "content_filter"}
    # Anthropic-native: `stop_reason` ∈ {"end_turn", "max_tokens", "stop_sequence"}
    reason = metadata.get("finish_reason") or metadata.get("stop_reason") or ""
    return str(reason).lower()


def _is_length_truncated(response) -> bool:
    return _get_finish_reason(response) in {"length", "max_tokens"}


def _output_token_count(response) -> int | None:
    """Extract output/completion token count from a langchain AIMessage when available."""
    usage = getattr(response, "usage_metadata", None) or {}
    if usage.get("output_tokens"):
        return int(usage["output_tokens"])
    metadata = getattr(response, "response_metadata", None) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    val = token_usage.get("completion_tokens") or token_usage.get("output_tokens")
    return int(val) if val else None


async def _invoke_with_continuation(llm, messages, *, max_continuations: int = 4):
    """Invoke the LLM, stitching continuations together when the output cap is hit.

    Some deployments (notably the GenAI proxy fronting Bedrock Claude) enforce a
    per-response output-token cap that is LOWER than what we request via
    ``max_tokens`` -- e.g. the proxy silently caps each call at 4K or 8K even
    when we ask for 32K, because Claude on Bedrock only honors extended output
    when the ``anthropic-beta: output-128k`` header is set and the OpenAI-compat
    layer does not forward it.  The result is a mid-string cutoff that looks
    exactly like a "model gave up" but is really a hard cap.

    This helper detects that case by inspecting ``finish_reason`` /
    ``stop_reason`` on the response and, when the cap was hit, asks the model
    to continue from EXACTLY where it stopped (no preamble, no repetition, no
    fences).  Chunks are concatenated so the caller receives a single coherent
    Python file even if it took several round-trips to produce.

    Returns ``(full_text, final_finish_reason, chunk_count)``.
    """
    working_messages = list(messages)
    chunks: list[str] = []
    final_reason = ""
    for attempt in range(max_continuations + 1):
        response = await llm.ainvoke(working_messages)
        chunk_text = _extract_text(response)
        chunks.append(chunk_text)
        out_tokens = _output_token_count(response)
        final_reason = _get_finish_reason(response) or "<unknown>"
        logger.info(
            "code-gen LLM chunk %d: finish_reason=%s output_tokens=%s chars=%d",
            attempt + 1, final_reason, out_tokens, len(chunk_text),
        )
        if not _is_length_truncated(response):
            break
        if attempt == max_continuations:
            logger.warning(
                "code-gen hit output-token cap on final continuation (chunk %d); "
                "returning stitched-but-possibly-still-truncated text",
                attempt + 1,
            )
            break
        working_messages = list(messages) + [
            {"role": "assistant", "content": "".join(chunks)},
            {"role": "user", "content": (
                "Your previous response was cut off by the output token limit. "
                "Continue writing from EXACTLY the last character you produced. "
                "Do NOT repeat anything you already wrote, do NOT add preamble, "
                "do NOT wrap in markdown fences, and do NOT add explanations -- "
                "just emit the raw continuation of the Python file so that "
                "concatenating your outputs yields valid, complete Python."
            )},
        ]
    return "".join(chunks), final_reason, len(chunks)


# ── LLM-as-judge ────────────────────────────────────────────────────────
#
# A second-pass review of the generated code by a cheaper, faster model
# (Haiku).  The static AST validator catches structural violations
# (forbidden imports, blocked calls, HTML smuggling patterns visible in
# the source); the runtime payload guard in ``code_executor.py`` catches
# violations that only appear at execution time.  The judge fills the
# gap between those: it spots intent-level problems the AST can't see —
# bypassing DSL primitives for a clear dashboard ask, hand-rolling
# canvas charts when Recharts would do, swallowing exceptions without
# user-visible feedback, etc.  It does NOT re-do the static checks.
#
# The judge is best-effort: any infrastructure failure (LLM unreachable,
# malformed JSON) returns a clean pass so we never block code-gen on a
# transient issue.  The user-facing impact of a judge call:
#   - CRITICAL issues  → fed back to generator on the next iteration; if
#                        unresolved at the final iteration, they land in
#                        ``violations`` and ``valid=False``.
#   - HIGH / MEDIUM    → surfaced as ``warnings`` on the response; code
#                        is still returned as valid.

_JUDGE_ENABLED = True
_JUDGE_BINDING = "service.code_executor.judge"
_CODE_GEN_BINDING = "service.code_executor.generator"

_JUDGE_SYSTEM_PROMPT = """\
You are a strict but pragmatic code reviewer for the Agent Studio Code
Executor sandbox.  You are given the user's original request and the
Python code generated to fulfil it.  Your job is to flag concrete
contract violations and serious quality problems — NOT to nitpick
style or rewrite working code.

## Response envelope (CRITICAL — read first)

Reply with ONE JSON object.  No markdown fences, no prose before or
after.      Schema:

    {
      "verdict": "pass" | "fail",
      "issues": [
        {
          "severity": "critical" | "high" | "medium",
          "category": "data_field" | "html_construction" | "render_abuse" |
                      "dsl_bypass" | "error_handling" | "security" |
                      "brand_styling" | "emoji" | "other",
          "message":  "one sentence describing the problem",
          "suggestion": "one sentence concrete fix"
        }
      ],
      "summary": "one-line overall assessment"
    }

`verdict = "fail"` iff at least ONE issue has `severity="critical"`.
HIGH/MEDIUM-only issues → still `verdict="pass"` with the issues listed
as advisory feedback.

If the code is clean, return `{"verdict": "pass", "issues": [],
"summary": "Looks good."}`.

## What counts as CRITICAL (block the code)

1. **data_field** — `output.data(data, ...)` whose `data` argument
   contains:
   - Field names like `html`, `html_base64`, `script`, `iframe`,
     `markup`, `rendered_html`, `dom_string`, `page_html`, `full_html`.
   - String values containing HTML markup (`<!doctype`, `<html`,
     `<body`, `<script`, `<iframe`, `<style>`).
   - Base64-encoded HTML/JS pages (long base64 strings whose decode
     would be HTML).
   `data` is for downstream nodes; markup belongs in `visualization`.

2. **html_construction** — Python code that builds HTML with f-strings,
   `.format`, or string concatenation and ships it onward, especially
   when the interpolated values come from user inputs (CSVs, uploads).
   This is an XSS sink.  Flag any `f"<...>...{var}...</...>"` pattern.

3. **render_abuse** — `{"type": "render", "script": "..."}` whose
   script body contains: `srcDoc`, `<iframe`, `.innerHTML`, `.outerHTML`,
   `dangerouslySetInnerHTML`, `document.write`, `atob(`, `eval(`,
   `new Function(`.  The render escape hatch is for
   `React.createElement` + `Recharts`, not for iframe loading or
   DOM injection.

4. **security** — code that exfiltrates user data, opens files outside
   `/workspace/uploads/` or `/outputs/`, hardcodes secrets, or attempts
   to bypass the import allowlist via dynamic loading.

## What counts as HIGH (advisory; don't block)

5. **dsl_bypass** — the user asked for a dashboard / report / table /
   chart and the code hand-rolls it (vanilla JS DOM, raw `<canvas>`
   drawing primitives, custom HTML tables, manual CSS) instead of
   using `output.table`, `output.chart`, or the `header`/`grid`/
   `metric`/`chart`/`table` DSL primitives.  ONE flagged issue
   covering the whole pattern; don't enumerate every primitive.

6. **error_handling** — file reads (`pd.read_csv`, `pd.read_excel`,
   `open(...)`) or `inputs["deliverables"][i]["data"]["col"]` accesses
   with no try/except and no defensive checks.  A missing column or
   malformed file currently surfaces as an unhandled `KeyError` /
   parser error.

7. **brand_styling** — visualisations use colours or fonts outside
   the Strategy& brand tokens defined in the system prompt:
     - Strategy& palette: `#A32020`, `#7A1818`, `#EA9595`, `#F4CACA`,
       `#DB536A`, `#BA2741`, `#464646`, `#7D7D7D`, accent `#82141E`,
       semantic bad `#D64554`, semantic good `#1AAB40`.
     - Allowed fonts: Arial (body / title / callout) and Georgia
       (header).
   Tailwind defaults like `#3B82F6`, `#22C55E`, `#EF4444` and ad-hoc
   hexes are off-brand.  Flag ONCE per generation covering the whole
   pattern; don't enumerate every offending hex.  Skip this flag if
   the user explicitly asked for a different palette.

8. **emoji** — any user-visible string (`output.data(title=...)`,
   visualization text, ask prompts, render-script string literals,
   `print()` log lines) contains an emoji codepoint.  No exceptions
   — the brand requires plain text labels and SVG icons.

## What counts as MEDIUM (informational only)

9. Hand-rolled canvas charts when `Recharts` (passed as the `Recharts`
   argument to render scripts) would do the same in 5 lines.
10. N (≥4) sequential `output.ask(type="file")` calls when files share
    a shape — `multiple=True` would replace them with one pause.

## Hard rules for YOUR reply

- ONE JSON object. No fences. No commentary.
- At most 6 issues; pick the most important.  A code reviewer who
  flags every minor smell is a code reviewer that gets ignored.
- Each `message` is one sentence.  Each `suggestion` is one sentence.
- Do NOT repeat issues that the static validator would have caught
  (forbidden imports, blocked calls, dunder access) — those are
  handled upstream.  Focus on intent-level and contract-level issues.
- If the user's request is open-ended ("write a script to analyse X")
  and the code is reasonable, return `verdict="pass"` even if you
  would have written it differently.
"""


def _parse_judge_envelope(raw: str) -> dict:
    """Parse the judge LLM's response into a normalised dict.

    Accepts either a direct JSON object or a fenced one.  Returns a
    pass-by-default envelope on any parse error so a malformed judge
    response never blocks code-gen.
    """
    stripped = _strip_fences(raw.strip())
    parsed: Any = None
    try:
        parsed = json.loads(stripped, strict=False)
    except json.JSONDecodeError:
        parsed = _extract_first_json_object(stripped)
    if not isinstance(parsed, dict):
        return {"verdict": "pass", "issues": [], "summary": ""}

    verdict = str(parsed.get("verdict", "pass")).strip().lower()
    if verdict not in {"pass", "fail"}:
        verdict = "pass"

    issues: list[dict] = []
    for raw_issue in parsed.get("issues") or []:
        if not isinstance(raw_issue, dict):
            continue
        sev = str(raw_issue.get("severity", "medium")).strip().lower()
        if sev not in {"critical", "high", "medium"}:
            sev = "medium"
        issues.append({
            "severity": sev,
            "category": str(raw_issue.get("category", "other")).strip(),
            "message": str(raw_issue.get("message", "")).strip(),
            "suggestion": str(raw_issue.get("suggestion", "")).strip(),
        })

    # Derived: fail iff any critical issue is present, regardless of what
    # the model said in `verdict`.  Belt-and-braces because some models
    # forget to set verdict consistently with the issues list.
    if any(i["severity"] == "critical" for i in issues):
        verdict = "fail"

    summary = str(parsed.get("summary", "")).strip()
    return {"verdict": verdict, "issues": issues, "summary": summary}


async def _run_judge(user_prompt: str, code: str) -> dict:
    """Run the judge LLM on the generated code.

    Returns ``{"verdict": "pass"|"fail", "issues": [...], "summary": str}``.
    Any infrastructure failure (LLM unreachable, malformed reply) is
    swallowed and treated as a pass so the judge never blocks code-gen
    on transient issues — the static validator and runtime guard remain
    the hard gates.
    """
    if not _JUDGE_ENABLED:
        return {"verdict": "pass", "issues": [], "summary": ""}

    try:
        from config.llm_config import LLMClientManager
        judge_llm = LLMClientManager.get_client_for_binding(
            _JUDGE_BINDING,
            temperature=0.0,
            max_tokens=2048,
            llm_role="code_judge",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Judge: failed to acquire LLM client (%s); skipping", exc)
        return {"verdict": "pass", "issues": [], "summary": ""}

    judge_user = (
        "## User's request\n"
        f"{user_prompt or '(empty)'}\n\n"
        "## Generated code\n"
        "```python\n"
        f"{code}\n"
        "```\n\n"
        "Review against the rubric in your system prompt and return the JSON envelope."
    )
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": judge_user},
    ]
    try:
        response = await judge_llm.ainvoke(messages)
        raw = _extract_text(response)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Judge LLM call failed: %s; treating as pass", exc)
        return {"verdict": "pass", "issues": [], "summary": ""}

    envelope = _parse_judge_envelope(raw)
    logger.info(
        "Judge verdict=%s issues=%d (critical=%d, high=%d, medium=%d) summary=%r",
        envelope["verdict"],
        len(envelope["issues"]),
        sum(1 for i in envelope["issues"] if i["severity"] == "critical"),
        sum(1 for i in envelope["issues"] if i["severity"] == "high"),
        sum(1 for i in envelope["issues"] if i["severity"] == "medium"),
        envelope["summary"][:120],
    )
    return envelope


def _format_judge_critique(judge: dict, user_prompt: str) -> str:
    """Render the judge's issues into a correction message for the
    generator's next iteration."""
    issues = judge.get("issues") or []
    critical = [i for i in issues if i["severity"] == "critical"]
    others = [i for i in issues if i["severity"] != "critical"]
    bullets: list[str] = []
    for i in critical:
        bullets.append(
            f"- [CRITICAL/{i['category']}] {i['message']} "
            f"→ {i['suggestion']}"
        )
    for i in others:
        bullets.append(
            f"- [{i['severity'].upper()}/{i['category']}] {i['message']} "
            f"→ {i['suggestion']}"
        )
    issue_block = "\n".join(bullets) if bullets else "(no specific issues)"
    return (
        "A code reviewer flagged the following issues with your previous "
        "attempt:\n"
        f"{issue_block}\n\n"
        "Produce a corrected version that:\n"
        "1. Resolves every CRITICAL issue.  These are contract violations, "
        "not preferences.\n"
        "2. Addresses the HIGH issues unless doing so would conflict with "
        "the user's explicit request.\n"
        "3. Still implements the user's original request: "
        f"{user_prompt}\n"
        "4. Is wrapped in the same response envelope "
        "({\"kind\":\"code\",\"summary\":...,\"code\":...,\"assumptions\":[]}).\n"
        "Do not switch to kind=\"clarify\" — the user already committed to "
        "this request; emit fixed code."
    )


# ── Multimodal helpers ──────────────────────────────────────────────────

_MAX_IMAGES_PER_REQUEST = 6
_MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB per data URL (Claude accepts up to ~5MB binary)
_ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
# Data-URL prefix looks like: data:image/png;base64,iVBORw0KGgo...
_DATA_URL_PREFIX = "data:"


def _validate_images(images: list[str]) -> list[str]:
    """Validate image data URLs and return the filtered list.

    Raises HTTPException(422) on any violation with a user-facing message.
    Silently drops empty strings / None entries.
    """
    clean: list[str] = []
    for raw in images or []:
        if not isinstance(raw, str) or not raw:
            continue
        if not raw.startswith(_DATA_URL_PREFIX):
            raise HTTPException(
                status_code=422,
                detail="Each image must be a data URL (data:image/...;base64,...).",
            )
        # Parse `data:<mime>;base64,<payload>`
        try:
            header, _ = raw.split(",", 1)
            mime = header[len(_DATA_URL_PREFIX):].split(";", 1)[0].strip().lower()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Malformed image data URL.",
            ) from exc
        if mime not in _ALLOWED_IMAGE_MIME:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported image type '{mime}'. Allowed: "
                    f"{', '.join(sorted(_ALLOWED_IMAGE_MIME))}."
                ),
            )
        # Size is measured on the full data URL to keep it simple and conservative.
        if len(raw) > _MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Image exceeds {_MAX_IMAGE_BYTES // (1024 * 1024)} MB size limit."
                ),
            )
        clean.append(raw)
    if len(clean) > _MAX_IMAGES_PER_REQUEST:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Too many images ({len(clean)}). Maximum is "
                f"{_MAX_IMAGES_PER_REQUEST} per request."
            ),
        )
    return clean


def _build_user_content(text: str, images: list[str]):
    """Compose a user-message `content` payload.

    Without images we return a plain string so the request stays cheap and
    backward-compatible.  With images we return the OpenAI-compat multimodal
    list (`type: text` + `type: image_url`), which the GenAI proxy translates
    into Claude's native image content blocks.
    """
    if not images:
        return text
    parts: list[dict] = [{"type": "text", "text": text}]
    for data_url in images:
        parts.append({"type": "image_url", "image_url": {"url": data_url}})
    return parts


# ── Upstream deliverable context ────────────────────────────────────────
#
# The frontend already collects each upstream node's ``outputSchema``
# (when configured) and sends them as a JSON-stringified array under
# ``context.upstream_nodes`` -- shape:
#
#     [{"index": 0, "label": "...", "type": "agent",
#       "output_schema": "<JSON Schema string or null>"}, ...]
#
# Previously we just inlined that JSON string verbatim, which made the
# LLM read raw JSON Schema and guess at access patterns.  This block
# does two things instead:
#
#   1. Renders each schema as a readable indented tree showing field
#      names, types, and descriptions (the schemas are already
#      self-documenting; we just expose that structure).
#   2. Generates concrete Python access patterns for each top-level
#      and nested field, so the model copies them rather than
#      reconstructing the path through ``inputs["deliverables"][i]
#      ["data"][...]`` from scratch.
#
# Code Executor upstreams often have no ``outputSchema`` (shape comes
# from ``output.data(...)``) — they appear with a defensive note unless
# the workflow author supplied a schema. Parsed schemas also emit a
# full JSON attachment (up to ``_MAX_FULL_SCHEMA_JSON_CHARS``).

# Agent deliverable JSON Schemas are often deeply nested (e.g. sections[].
# content.delivery.mode).  Shallow limits caused the LLM to only see the
# outer shape and guess inner paths incorrectly.
_MAX_SCHEMA_RENDER_DEPTH = 14
_MAX_SCHEMA_ACCESS_DEPTH = 14
_MAX_SCHEMA_PROPS_PER_OBJECT = 2000    # wide one-level objects (many columns)
_MAX_ACCESS_PATTERNS_PER_NODE = 800
_MAX_FULL_SCHEMA_JSON_CHARS = 50_000  # verbatim JSON Schema per upstream node in prompt


def _coerce_schema(raw: Any) -> Any:
    """Best-effort: turn whatever the FE sent into a Python dict/list.

    ``output_schema`` can arrive as: a JSON Schema dict already parsed,
    a JSON-string of one, ``None``, or an unrelated string.  Returns
    None on anything we can't make sense of so the caller falls back
    to label/type only.
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def _unwrap_schema_data_layer(schema: Any) -> Any:
    """If the configured schema still wraps the payload in a ``data`` key but
    runtime paths already start at ``inputs["deliverables"][i]["data"]``,
    strip that redundant layer so trees and access paths match execution.

    Only unwraps when the top level is a JSON-Schema object whose sole
    property is ``data`` (typical copy-paste from APIs that nest the body).
    """
    if not isinstance(schema, dict):
        return schema
    props = schema.get("properties")
    if not isinstance(props, dict):
        return schema
    keys = list(props.keys())
    if len(keys) != 1 or keys[0] != "data":
        return schema
    inner = props.get("data")
    if not isinstance(inner, dict):
        return schema
    if inner.get("type") not in (None, "object", "array") and "properties" not in inner:
        return schema
    return inner


def _is_flat_type_dict(d: dict) -> bool:
    """Heuristic: a "flat" schema dialect like
    ``{"customer_name": "string", "amount": "number"}`` -- a dict with
    no JSON-Schema metadata keys whose values are all primitive type
    names.  Some legacy agents emit schemas this way.
    """
    if not d:
        return False
    if "type" in d or "properties" in d or "items" in d:
        return False
    primitives = {
        "string", "number", "integer", "boolean", "object", "array",
        "any", "null",
    }
    for v in d.values():
        if not isinstance(v, str) or v.lower() not in primitives:
            return False
    return True


def _render_schema_tree(
    schema: Any, *, indent: int = 0, depth: int = 0,
) -> list[str]:
    """Render a JSON Schema (or a plain dict-of-types) as readable lines.

    We accept both real JSON Schema (``{"type": "object", "properties":
    {...}}``) and the simpler flat-dict shape some upstream agents emit
    (``{"field_a": "string", "field_b": "integer"}``) so the helper
    works regardless of which dialect the user happened to configure.
    """
    if depth >= _MAX_SCHEMA_RENDER_DEPTH:
        return [" " * indent + "... (depth limit)"]
    if not isinstance(schema, dict):
        return [" " * indent + f"({type(schema).__name__})"]

    lines: list[str] = []
    s_type = schema.get("type")
    description = (schema.get("description") or "").strip()
    required_names = set(schema.get("required") or []) if isinstance(
        schema.get("required"), list,
    ) else set()

    if s_type == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        for name, prop in list(props.items())[:_MAX_SCHEMA_PROPS_PER_OBJECT]:
            t = _short_type(prop)
            desc = (prop.get("description") or "").strip() if isinstance(prop, dict) else ""
            head = " " * indent + f"- {name}: {t}"
            if name in required_names:
                head += "  (required)"
            if desc:
                head += f"  — {desc}"
            if isinstance(prop, dict):
                ev = prop.get("enum")
                if isinstance(ev, list) and ev:
                    if len(ev) <= 12:
                        head += f"  enum={ev!r}"
                    else:
                        head += f"  enum=[{len(ev)} values]"
            lines.append(head)
            if isinstance(prop, dict):
                child = _render_schema_tree(
                    prop, indent=indent + 4, depth=depth + 1,
                )
                lines.extend(child)
        if len(props) > _MAX_SCHEMA_PROPS_PER_OBJECT:
            lines.append(
                " " * indent + f"  ... ({len(props) - _MAX_SCHEMA_PROPS_PER_OBJECT} more fields elided)"
            )
    elif s_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            t = _short_type(items)
            head = " " * indent + f"items: {t}"
            if description:
                head += f"  — {description}"
            lines.append(head)
            sub = _render_schema_tree(items, indent=indent + 4, depth=depth + 1)
            lines.extend(sub)
    elif _is_flat_type_dict(schema):
        for name, type_name in list(schema.items())[:_MAX_SCHEMA_PROPS_PER_OBJECT]:
            lines.append(" " * indent + f"- {name}: {type_name}")
        if len(schema) > _MAX_SCHEMA_PROPS_PER_OBJECT:
            lines.append(
                " " * indent + f"  ... ({len(schema) - _MAX_SCHEMA_PROPS_PER_OBJECT} more fields elided)"
            )

    return lines


def _short_type(prop: Any) -> str:
    """Short type label for a JSON Schema property dict."""
    if not isinstance(prop, dict):
        if isinstance(prop, str):
            return prop  # already a type name (flat-dict dialect)
        return type(prop).__name__
    t = prop.get("type")
    if isinstance(t, list):
        return " | ".join(t)
    if t == "array":
        items = prop.get("items") or {}
        item_t = items.get("type") if isinstance(items, dict) else None
        return f"array<{item_t or 'any'}>"
    return str(t or "any")


def _collect_access_paths(
    schema: Any, *, base: str, depth: int = 0,
) -> list[tuple[str, str, str]]:
    """Walk a schema and yield ``(python_expr, type_label, description)``
    tuples that show how to reach each field from the base expression.

    For objects we recurse into properties; for arrays we emit a
    ``[0]`` access for the first item.  Recursion depth is capped at
    ``_MAX_SCHEMA_ACCESS_DEPTH`` so very deep schemas stay bounded while
    typical multi-section agent payloads are fully covered.
    """
    if depth > _MAX_SCHEMA_ACCESS_DEPTH or not isinstance(schema, dict):
        return []
    paths: list[tuple[str, str, str]] = []

    s_type = schema.get("type")
    if s_type == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        for name, prop in list(props.items())[:_MAX_SCHEMA_PROPS_PER_OBJECT]:
            child_expr = f'{base}["{name}"]'
            t = _short_type(prop)
            desc = (
                (prop.get("description") or "").strip()
                if isinstance(prop, dict)
                else ""
            )
            paths.append((child_expr, t, desc))
            if isinstance(prop, dict):
                paths.extend(
                    _collect_access_paths(
                        prop, base=child_expr, depth=depth + 1,
                    )
                )
    elif s_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            child_expr = f"{base}[0]"
            t = _short_type(items)
            desc = (items.get("description") or "").strip()
            paths.append((child_expr, t, desc))
            paths.extend(
                _collect_access_paths(
                    items, base=child_expr, depth=depth + 1,
                )
            )
    elif _is_flat_type_dict(schema):
        for name, type_name in list(schema.items())[:_MAX_SCHEMA_PROPS_PER_OBJECT]:
            paths.append((f'{base}["{name}"]', str(type_name), ""))

    return paths


def _format_access_block(
    paths: list[tuple[str, str, str]], *, max_paths: int,
) -> str:
    """Render the collected paths as an aligned Python comment block."""
    if not paths:
        return ""
    truncated = paths[:max_paths]
    expr_w = max(len(p[0]) for p in truncated)
    lines: list[str] = []
    for expr, type_label, desc in truncated:
        line = f"  {expr.ljust(expr_w)}  # {type_label}"
        if desc:
            line += f" — {desc}"
        lines.append(line)
    if len(paths) > max_paths:
        lines.append(f"  ... ({len(paths) - max_paths} more access paths)")
    return "\n".join(lines)


# Node types that never append to ``state["deliverables"]`` — same set as the
# Code Editor frontend filter so codegen indices match runtime.
_NON_DELIVERABLE_UPSTREAM_TYPES = frozenset(
    {
        "condition",
        "end",
        "chat",
        "webhook",
        "scheduled-start",
        "sticky-note",
        "start",
        "tool",
        "transform",
        "human",
    }
)


def _truncate_schema_json(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _format_full_schema_block(schema: Any) -> str:
    """Pretty-print the entire schema JSON for the code generator prompt."""
    try:
        dumped = json.dumps(schema, indent=2, default=str)
    except TypeError:
        return ""
    truncated, was_trunc = _truncate_schema_json(
        dumped, _MAX_FULL_SCHEMA_JSON_CHARS,
    )
    note = ""
    if was_trunc:
        note = (
            f"\n_(Schema JSON truncated at {_MAX_FULL_SCHEMA_JSON_CHARS} "
            "characters for prompt size.)_\n\n"
        )
    return (
        f"{note}**Full output schema (complete JSON; authoritative field list):**\n"
        f"```json\n{truncated}\n```"
    )


def _build_upstream_context_block(upstream_raw: Any) -> str:
    """Render the FE-supplied upstream summary as a structured block.

    Falls through to an empty string when nothing useful is available
    (no upstream nodes, or all are missing schemas) so the caller can
    skip emitting the section entirely.
    """
    nodes_list: list[dict]
    if isinstance(upstream_raw, list):
        nodes_list = [n for n in upstream_raw if isinstance(n, dict)]
    elif isinstance(upstream_raw, str) and upstream_raw.strip():
        try:
            parsed = json.loads(upstream_raw)
            nodes_list = [n for n in parsed if isinstance(n, dict)] if isinstance(
                parsed, list,
            ) else []
        except json.JSONDecodeError:
            return (
                "## Upstream nodes (their outputs are in `inputs[\"deliverables\"]`)\n"
                f"{upstream_raw}"
            )
    else:
        return ""

    nodes_list = [
        n
        for n in nodes_list
        if str(n.get("type") or "node") not in _NON_DELIVERABLE_UPSTREAM_TYPES
    ]

    if not nodes_list:
        return ""

    sections: list[str] = []
    sections.append(
        "## Upstream deliverables (`inputs[\"deliverables\"]`)\n\n"
        "Index ``i`` is **0-based** and follows **workflow execution order** "
        "(earlier upstream steps first — same order the host appends approved "
        "outputs before this node runs).  **Logic / initiator nodes** (If/Else, "
        "Chat, Webhook, etc.) never appear in this array — only nodes that emit "
        "structured deliverables are listed below.  Each element has "
        "``agent_label``, ``agent_type``, and ``data``; **read only "
        "``inputs[\"deliverables\"][i][\"data\"]`** for structured fields "
        "(the per-node sections below describe that payload).  Schemas may "
        "have been saved with an extra ``properties.data`` wrapper — when "
        "present it is flattened here so paths always match runtime."
    )

    for i, node in enumerate(nodes_list):
        # Positional index only — must match the ordered array the client sends
        # (execution order) and `inputs["deliverables"][i]` at runtime.
        idx = i
        label = str(node.get("label") or node.get("type") or f"Node {idx}")
        ntype = str(node.get("type") or "node")
        raw_schema = node.get("output_schema")
        schema = _unwrap_schema_data_layer(_coerce_schema(raw_schema))

        block: list[str] = [
            f"### `inputs[\"deliverables\"][{idx}][\"data\"]` — upstream "
            f"\"{label}\" (`agent_type={ntype!r}`)"
        ]

        if schema is None:
            raw_str = raw_schema if isinstance(raw_schema, str) else None
            if raw_str and raw_str.strip():
                clipped, was_trunc = _truncate_schema_json(
                    raw_str.strip(), _MAX_FULL_SCHEMA_JSON_CHARS,
                )
                block.append(
                    "**Output schema (raw text — could not parse as JSON; "
                    "treat as informal guidance):**"
                )
                block.append("```")
                block.append(clipped)
                if was_trunc:
                    block.append("… (truncated)")
                block.append("```")
                sections.append("\n".join(block))
                continue
            if ntype == "code-executor":
                block.append(
                    "_No declared output schema._  This node is a Code "
                    "Executor; its `data` shape is whatever its "
                    "`output.data(...)` call emits.  Treat the payload "
                    "defensively (use `.get()` and check key presence)."
                )
            else:
                block.append(
                    "_No declared output schema._  Treat the `data` "
                    "payload defensively (use `.get()` / check key "
                    "presence) since the upstream node's deliverable "
                    "shape isn't pinned."
                )
            sections.append("\n".join(block))
            continue

        # Schema preview (outline)
        tree_lines = _render_schema_tree(schema)
        if tree_lines:
            block.append("**Schema outline:**")
            block.append("```")
            block.extend(tree_lines)
            block.append("```")

        # Access patterns
        base_expr = f'inputs["deliverables"][{idx}]["data"]'
        paths = _collect_access_paths(schema, base=base_expr)
        if paths:
            access_text = _format_access_block(
                paths, max_paths=_MAX_ACCESS_PATTERNS_PER_NODE,
            )
            block.append("**Access patterns** (use these verbatim):")
            block.append("```python")
            # Always include the top-level handle so the model has the
            # idiom for binding the whole payload before drilling in.
            block.append(f"data_{idx} = {base_expr}")
            block.append(access_text)
            block.append("```")

        full_schema = _format_full_schema_block(schema)
        if full_schema:
            block.append(full_schema)

        sections.append("\n".join(block))

    return "\n\n".join(sections)


async def _build_kb_context_block(kb_ids: list[str]) -> str:
    """Return a markdown block describing the configured KBs' tables so the
    LLM can write accurate ``knowledge_base.read_table()`` /
    ``knowledge_base.query()`` calls.

    The block has three layers, cheapest first so the model can skim:

    1. A strong preamble that names the SDK entry point
       (``from agent_studio import knowledge_base``) and shows both the
       Pandas-first read and the raw-SQL escape hatch in-line.
    2. A per-KB **Available tables** quick-index: one line per table with
       its description — enough for the model to decide *whether* a KB
       read is even relevant to the user's prompt.
    3. The full semantic model (columns, types, descriptions, sample
       rows, relationships) generated by ``StructuredDataService`` for
       writing the actual query.

    KBs the caller can't access (RLS) are silently skipped; if no KB
    produces any metadata we return an empty string so the prompt stays
    unchanged.
    """
    filtered = [str(k) for k in (kb_ids or []) if k]
    if not filtered:
        return ""

    from db.pgsql import get_write_db as _get_write_db
    from repositories.knowledge_base_repository import KnowledgeBaseRepository
    from repositories.structured_data_repository import StructuredDataRepository
    from services.structured_data_service import StructuredDataService

    sections: list[str] = []
    try:
        async for db in _get_write_db():
            kb_repo = KnowledgeBaseRepository(db)
            structured_repo = StructuredDataRepository(db)
            # StructuredDataService requires the repo as a collaborator.
            # The previous call-site passed only `db` which raised a
            # TypeError — caught by the outer `except Exception` and
            # swallowed, meaning KB context silently never made it into
            # the system prompt.  Pass the repo explicitly so we actually
            # produce the tables/columns/descriptions block.
            service = StructuredDataService(db, structured_repo)
            for kb_id in filtered:
                try:
                    kb = await kb_repo.get_by_id(kb_id)
                except Exception as exc:
                    logger.warning("KB %s lookup failed: %s", kb_id, exc)
                    continue
                if kb is None:
                    continue
                try:
                    semantic = await service.get_semantic_model(kb_id)
                except Exception as exc:
                    logger.warning(
                        "semantic_model failed for KB %s: %s", kb_id, exc,
                    )
                    continue
                if not (semantic or "").strip():
                    continue

                # Build a quick-index of tables with their descriptions so
                # the model can decide whether to use the KB at all BEFORE
                # wading through column/sample-row detail.  We pull the
                # same StructuredDataRepository the semantic model uses
                # so descriptions stay in sync.
                table_index_lines: list[str] = []
                try:
                    tables = await service.structured_repo.get_tables_for_kb(
                        kb_id
                    )
                    for t in tables or []:
                        desc = (getattr(t, "description", "") or "").strip()
                        col_count = len(getattr(t, "columns", []) or [])
                        row_count = getattr(t, "row_count", None)
                        meta_bits: list[str] = [f"{col_count} col"]
                        if isinstance(row_count, int):
                            meta_bits.append(f"{row_count:,} rows")
                        meta_str = ", ".join(meta_bits)
                        if desc:
                            table_index_lines.append(
                                f"- `{t.table_name}` ({meta_str}) — {desc}"
                            )
                        else:
                            table_index_lines.append(
                                f"- `{t.table_name}` ({meta_str}) — _no description provided_"
                            )
                except Exception as exc:
                    logger.warning(
                        "table index build failed for KB %s: %s", kb_id, exc,
                    )

                kb_label = kb.name or kb_id
                block = [f"### KB `{kb_label}`  (kb_id=`{kb_id}`)"]
                if table_index_lines:
                    block.append("")
                    block.append("**Available tables** (read with `knowledge_base.read_table(\"<table>\")`):")
                    block.extend(table_index_lines)
                block.append("")
                block.append("**Full schema** (use exactly these PG column names in SELECT/WHERE):")
                block.append(semantic)
                sections.append("\n".join(block))
            break
    except Exception as exc:
        logger.warning("Failed to load KB context for code generator: %s", exc)
        return ""

    if not sections:
        return ""

    preamble = (
        "## Knowledge Base context — structured tables are available\n\n"
        "The user has attached one or more Knowledge Bases (KBs) to this "
        "Code Executor node. You have **first-class, read-only access** to "
        "their structured tables via the `agent_studio.knowledge_base` "
        "SDK client. This is the ONLY supported way to read KB data — "
        "do NOT try to use SQLAlchemy, psycopg, requests, or any other "
        "database driver.\n\n"
        "```python\n"
        "from agent_studio import knowledge_base\n"
        "\n"
        "# Option 1 (preferred): Pandas DataFrame of a single table\n"
        "df = knowledge_base.read_table(\"<table_name>\", limit=100)\n"
        "\n"
        "# Option 2: raw SELECT (aggregations, joins, custom projections)\n"
        "df = knowledge_base.query(\n"
        "    \"SELECT col_a, SUM(col_b) AS total FROM <table> GROUP BY col_a\",\n"
        "    kb_id=\"<uuid>\",\n"
        ")\n"
        "```\n\n"
        "**Rules for KB reads**:\n"
        "1. **Only use KBs when the user's prompt genuinely needs them.** "
        "Do not insert a `knowledge_base.read_table()` call just because a "
        "KB is attached — if the user is uploading a CSV, parsing inputs, "
        "or calling the LLM, leave the KB alone.\n"
        "2. The `table_name` and column names below are the exact "
        "PostgreSQL identifiers (lower snake_case). Use them verbatim in "
        "`SELECT` and `WHERE` clauses.\n"
        "3. `knowledge_base.query()` only accepts a **single SELECT** — no "
        "semicolons, comments, or DML/DDL. The host rejects anything else.\n"
        "4. Pass `kb_id=` only when the table name is ambiguous across "
        "multiple KBs; otherwise the SDK resolves it automatically.\n"
        "5. **Table descriptions** below explain what each table contains "
        "in plain English — read them first to pick the right table.\n\n"
    )
    return preamble + "\n\n".join(sections)


@router.post(
    "/generate-code",
    response_model=CodeGenerationResponse,
    dependencies=[Depends(get_current_user)],
)
async def generate_code(body: CodeGenerationRequest):
    """Generate Python code from a natural language prompt using the configured LLM."""
    from config.llm_config import LLMClientManager
    from workflow.sandbox.code_validator import (
        CodeValidator,
        DEFAULT_ALLOWED_IMPORTS,
        BLOCKED_IMPORTS,
        BLOCKED_CALLS,
        DANGEROUS_ATTR_CHAINS,
    )

    sdk_ref = await asyncio.to_thread(_load_sdk_reference)
    ctx = body.context
    images = _validate_images(body.images)
    if images:
        logger.info("code-gen: received %d image attachment(s)", len(images))

    # Combine the static allowlist with any per-node extras so the LLM sees
    # exactly what the validator will accept for THIS request.  The same
    # `extra_allowed_imports` will be passed to CodeValidator below.
    extra_imports = [
        imp for imp in (ctx.get("allowed_imports") or []) if isinstance(imp, str) and imp
    ]
    effective_allowed = sorted(set(DEFAULT_ALLOWED_IMPORTS) | set(extra_imports))

    allowed_imports_list = ", ".join(f"`{imp}`" for imp in effective_allowed)
    blocked_imports_list = ", ".join(f"`{imp}`" for imp in sorted(BLOCKED_IMPORTS))
    blocked_calls_list = ", ".join(f"`{name}()`" for name in sorted(BLOCKED_CALLS))
    blocked_attr_chains_list = ", ".join(
        f"`{root}.{method}()`" for root, method in sorted(DANGEROUS_ATTR_CHAINS)
    )

    extra_parts = []
    upstream_block = _build_upstream_context_block(ctx.get("upstream_nodes"))
    if upstream_block:
        extra_parts.append(upstream_block)
    if ctx.get("existing_code"):
        extra_parts.append(
            f"## Existing code (modify/extend this)\n```python\n{ctx['existing_code']}\n```"
        )
    if extra_imports:
        extra_parts.append(
            "## Per-node extra allowed imports (already included in the allowlist above)\n"
            + ", ".join(f"`{imp}`" for imp in sorted(extra_imports))
        )

    kb_context_block = await _build_kb_context_block(body.knowledge_base_ids or [])
    if kb_context_block:
        extra_parts.append(kb_context_block)

    # NOTE: use .replace() rather than .format(): the template contains
    # literal JSON examples like `{"type": "render", ...}` that str.format
    # would misinterpret as named placeholders (raising KeyError: '"type"').
    system_prompt = (
        _SYSTEM_PROMPT_TEMPLATE
        .replace("{sdk_reference}", sdk_ref)
        .replace("{allowed_imports_list}", allowed_imports_list)
        .replace("{blocked_imports_list}", blocked_imports_list)
        .replace("{blocked_calls_list}", blocked_calls_list)
        .replace("{blocked_attr_chains_list}", blocked_attr_chains_list)
        .replace(
            "{extra_context}",
            "\n\n".join(extra_parts) if extra_parts else "",
        )
    )

    # Dashboard-style generations routinely exceed the system-wide 4K default
    # (long JS render scripts inside `output.data` visualizations inflate token
    # counts quickly).  Claude Opus 4.6 supports large output windows on
    # Bedrock, but the OpenAI-compat GenAI proxy often enforces a lower
    # per-response cap (commonly 4K/8K) because it cannot pass the
    # `anthropic-beta: output-128k` header.  `_invoke_with_continuation` below
    # transparently stitches follow-up calls when we see `finish_reason=length`,
    # so even if each call is capped we still get a complete Python file.
    # Opus is used here (not Sonnet) because code generation is the single
    # most reasoning-heavy task in the product and benefits most from Opus.
    llm = LLMClientManager.get_client_for_binding(
        _CODE_GEN_BINDING,
        temperature=0.2,
        max_tokens=32000,
        llm_role="code_generator",
    )

    validator = CodeValidator(extra_allowed_imports=extra_imports)

    # ---- Multi-turn message assembly -------------------------------------
    # Every request re-sends the (trimmed) chat history so the model sees the
    # full refinement conversation — it picks up "make the chart horizontal"
    # as a delta on the previous turn rather than a standalone request.
    history_messages = _history_to_messages(body.chat_history)
    base_messages = [
        {"role": "system", "content": system_prompt},
        *history_messages,
        {"role": "user", "content": _build_user_content(body.prompt, images)},
    ]

    # ---- Self-healing generation loop ------------------------------------
    # Each iteration runs THREE gates in order:
    #
    #   1. Generate code (with token-cap stitching).
    #   2. Static AST validator (`code_validator.py`).  Catches structural
    #      contract violations: forbidden imports, blocked calls, HTML
    #      f-strings, render-script abuse, etc.
    #   3. LLM judge (Haiku).  Catches intent-level issues the AST can't
    #      see: bypass of the DSL, missing error handling, hand-rolled
    #      charts when Recharts would do, etc.  Only runs when (2) passes.
    #
    # If either gate flags a CRITICAL issue we feed the combined critique
    # back to the generator and try again, capped at MAX_ATTEMPTS.  HIGH
    # and MEDIUM judge issues become non-blocking ``warnings`` on the
    # response — the code is still returned valid; the user sees the
    # advisory feedback alongside it.
    #
    # Self-healing only runs for ``kind="code"`` — a clarify reply
    # short-circuits since there's no code to validate or judge.
    MAX_ATTEMPTS = 4
    generated_code = ""
    envelope_kind = "code"
    envelope_summary = ""
    envelope_assumptions: list[str] = []
    envelope_question = ""
    envelope_options: list[str] = []
    result = None  # type: ignore[assignment]
    judge_envelope: dict = {"verdict": "pass", "issues": [], "summary": ""}
    working_messages = list(base_messages)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # Attach images on every attempt so the model keeps the visual
            # reference even across self-healing retries.  `_build_user_content`
            # falls back to a plain string when no images are present.
            full_text, finish_reason, chunk_count = await _invoke_with_continuation(
                llm,
                working_messages,
            )
        except Exception as exc:
            # First call failing means the LLM is unreachable — surface 502.
            # Retry failures are best-effort: keep the previous attempt.
            if attempt == 1:
                logger.exception("LLM call failed for code generation")
                raise HTTPException(
                    status_code=502, detail=f"LLM service error: {exc}"
                ) from exc
            logger.warning(
                "LLM retry attempt %d failed (%s); returning previous attempt",
                attempt, exc,
            )
            break

        if chunk_count > 1:
            logger.info(
                "code-gen attempt %d stitched from %d chunks (final finish_reason=%s)",
                attempt, chunk_count, finish_reason,
            )

        envelope = _parse_envelope(full_text)
        envelope_kind = envelope.get("kind", "code")

        if envelope_kind == "clarify":
            envelope_question = str(envelope.get("question") or "").strip()
            opts = envelope.get("options") or []
            envelope_options = [str(o) for o in opts if isinstance(o, (str, int, float))]
            logger.info(
                "code-gen attempt %d returned a clarify envelope (%d option chip(s))",
                attempt, len(envelope_options),
            )
            generated_code = ""
            result = None
            break

        # kind == "code"
        raw_code = envelope.get("code") or ""
        generated_code = _strip_fences(str(raw_code).strip())
        envelope_summary = str(envelope.get("summary") or "").strip()
        assumptions_raw = envelope.get("assumptions") or []
        envelope_assumptions = [
            str(a) for a in assumptions_raw if isinstance(a, (str, int, float))
        ]

        # ── Gate 2: static validator ────────────────────────────────
        result = validator.validate(generated_code)
        if not result.valid:
            logger.info(
                "Code generation attempt %d invalid (%d violation(s)): %s",
                attempt,
                len(result.violations),
                "; ".join(result.violations)[:500],
            )
            if attempt == MAX_ATTEMPTS:
                break
            violation_list = "\n".join(f"- {v}" for v in result.violations)
            correction = (
                "Your previous attempt failed the static validator with these "
                "errors:\n"
                f"{violation_list}\n\n"
                "Produce a corrected version that:\n"
                "1. Fixes every violation listed above.\n"
                "2. Still implements the user's original request: "
                f"{body.prompt}\n"
                "3. Uses ONLY imports from the allowed list in the system prompt.\n"
                "4. Is wrapped in the same response envelope "
                "({\"kind\":\"code\",\"summary\":...,\"code\":...,\"assumptions\":[]}).\n"
                "Do not switch to kind=\"clarify\" -- the user already committed "
                "to this request; emit fixed code."
            )
            working_messages = [
                *base_messages,
                {"role": "assistant", "content": full_text},
                {"role": "user", "content": correction},
            ]
            continue

        # ── Gate 3: LLM judge ───────────────────────────────────────
        judge_envelope = await _run_judge(body.prompt, generated_code)
        if judge_envelope["verdict"] == "pass":
            logger.info(
                "Code generation valid + judge-pass after %d attempt(s)",
                attempt,
            )
            break

        # Judge failed — at least one CRITICAL issue.  Feed combined
        # critique back to the generator and try again.
        critical_n = sum(
            1 for i in judge_envelope["issues"]
            if i["severity"] == "critical"
        )
        logger.info(
            "Code generation attempt %d judge-fail (%d critical issue(s))",
            attempt, critical_n,
        )
        if attempt == MAX_ATTEMPTS:
            break
        working_messages = [
            *base_messages,
            {"role": "assistant", "content": full_text},
            {
                "role": "user",
                "content": _format_judge_critique(judge_envelope, body.prompt),
            },
        ]

    # ---- Build the response envelope -------------------------------------
    if envelope_kind == "clarify":
        return CodeGenerationResponse(
            kind="clarify",
            question=envelope_question,
            options=envelope_options,
            explanation=envelope_question,  # legacy mirror
            valid=True,
            violations=[],
        )

    # Safety net: if every retry raised, ensure we always have a result.
    if result is None:
        result = validator.validate(generated_code)

    explanation = envelope_summary
    if not explanation:
        for line in generated_code.split("\n"):
            if line.strip().startswith("#") and not line.strip().startswith("#!"):
                explanation = line.strip().lstrip("# ")
                break

    # Merge judge issues into the response.  CRITICAL issues that
    # survived the loop become hard violations (so the FE shows them as
    # blocking, the same as static violations).  HIGH/MEDIUM issues are
    # advisory ``warnings`` — code is returned and runnable, the user
    # decides whether to refine.
    judge_issues = judge_envelope.get("issues") or []
    judge_critical = [i for i in judge_issues if i["severity"] == "critical"]
    judge_warnings_src = [i for i in judge_issues if i["severity"] != "critical"]

    def _format_issue(issue: dict) -> str:
        msg = issue.get("message") or ""
        sug = issue.get("suggestion") or ""
        cat = issue.get("category") or "other"
        if sug:
            return f"[{cat}] {msg} → {sug}"
        return f"[{cat}] {msg}"

    final_violations = list(result.violations)
    final_valid = result.valid
    if judge_critical:
        final_violations.extend(_format_issue(i) for i in judge_critical)
        final_valid = False
    final_warnings = [_format_issue(i) for i in judge_warnings_src]

    return CodeGenerationResponse(
        kind="code",
        code=generated_code,
        summary=envelope_summary,
        explanation=explanation,
        assumptions=envelope_assumptions,
        valid=final_valid,
        violations=final_violations,
        warnings=final_warnings,
        judge_summary=str(judge_envelope.get("summary") or ""),
    )
