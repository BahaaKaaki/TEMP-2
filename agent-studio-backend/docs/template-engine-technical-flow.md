# Template Engine -- Technical Flow

This document traces the full lifecycle of a PPTX template: from upload in the workflow builder, through AI-driven workflow execution, to the final "Fill PowerPoint Template" download. Every file, function, and API endpoint is referenced.

---

## Table of Contents

1. [Phase 1: Template Upload (Design Time)](#phase-1-template-upload-design-time)
2. [Phase 2: Workflow Execution (Chat Time)](#phase-2-workflow-execution-chat-time)
3. [Phase 3: Fill PowerPoint Template](#phase-3-fill-powerpoint-template)
4. [Module Reference](#module-reference)

---

## Phase 1: Template Upload (Design Time)

This phase happens when a user opens the workflow builder, selects an agent node, and uploads a `.pptx` template file.

### 1.1 Frontend: File Selection

**File:** `agent-studio-frontend/src/components/builder/NodeConfigPanel.jsx`

The agent node config panel renders a hidden file input (`accept=".pptx"`). When the user selects a file, the `onChange` handler fires:

1. Guards that the workflow has been saved (needs `workflow.id`).
2. Calls `uploadTemplate(workflowId, selectedNodeId, file)` from `@/api/template-client`.
3. On success, writes three config values to the node:
   - `templateId` -- UUID of the stored template
   - `templateName` -- display name
   - `outputSchema` -- JSON Schema string derived from the template's placeholders

### 1.2 Frontend: API Client

**File:** `agent-studio-frontend/src/api/template-client.js`

```
uploadTemplate(workflowId, agentNodeId, file, templateName?)
```

Sends a `POST` to `/api/templates/upload` with a `FormData` body containing:
- `file` -- the raw `.pptx` binary
- `workflow_id` -- the parent workflow UUID
- `agent_node_id` -- the node this template belongs to
- `template_name` -- optional display name

Returns JSON: `{ id, name, fileName, placeholders, generatedSchema }`.

### 1.3 Backend: Router

**File:** `agent-studio-backend/app/routers/template_routes.py`

```
POST /api/templates/upload
```

- Validates the file extension is `.pptx`.
- Reads the file bytes via `await file.read()`.
- Delegates to `TemplateService.upload_template(...)`.
- Returns the service result as JSON.

### 1.4 Backend: TemplateService.upload_template

**File:** `agent-studio-backend/app/services/template_service.py`

This is the orchestration method. It runs 7 steps in sequence:

| Step | What Happens | Module Called |
|------|-------------|--------------|
| 1. Sanitize | Strips think-cell add-in shapes and prunes orphaned OPC relationships from the PPTX ZIP. This prevents "needs repair" errors when slides are later cloned. | `template_sanitizer.sanitize_template(file_bytes)` |
| 2. Blob upload | Uploads the sanitized bytes to Azure Blob Storage under a deterministic path: `templates/{workflow_id}/{agent_node_id}/{uuid}.pptx`. | `self.storage.upload_blob(blob_name, data=file_bytes, ...)` |
| 3. Temp file | Writes the sanitized bytes to a `NamedTemporaryFile` so python-pptx can open it (python-pptx requires a file path). | `tempfile.NamedTemporaryFile(suffix=".pptx")` |
| 4. Parse placeholders | Scans every text frame across all slides for `{{ }}`, `{{* }}`, and `{{# }}`/`{{/ }}` markers. Returns a list of `Placeholder` dataclass instances. | `placeholder_parser.extract_placeholders(tmp_path)` |
| 5. Generate schema | Converts the placeholder list into a JSON Schema. Loop placeholders become `array` of `object`; bullet placeholders become `array` of `string`; text placeholders become `string`. Descriptions from `{{ field | hint }}` syntax become `description` fields. | `schema_generator.generate_schema(placeholders, title=...)` |
| 6. Upsert DB row | Checks for an existing template for this workflow+node pair. If found, deletes the old blob and DB row. Then inserts a new `WorkflowTemplate` row with the template metadata, serialized placeholders, and generated schema. | `TemplateRepository.create(...)` |
| 7. Return | Returns `{ id, name, fileName, placeholders, generatedSchema }` to the router. | -- |

### 1.5 Backend: Sanitizer Detail

**File:** `agent-studio-backend/app/services/template_engine/template_sanitizer.py`

`sanitize_template(raw: bytes) -> bytes` does two things:

1. **Strip add-in shapes:** Opens the PPTX with python-pptx, iterates all shapes on all slides, and removes any whose name or XML contains "think-cell" / "thinkcell" markers. These are invisible data shapes injected by the think-cell PowerPoint add-in that break slide cloning.

2. **Prune orphaned relationships:** Re-opens the PPTX as a ZIP file. For each slide XML, collects all `rId` references actually used in the shape tree. Then inspects the slide's `.rels` file and removes any relationship whose `rId` is not used and whose type is `oleObject`, `package`, `tags`, `tag`, or `vmlDrawing`. Also removes the corresponding embedded parts from the ZIP and cleans `[Content_Types].xml`.

### 1.6 Backend: Placeholder Parser Detail

**File:** `agent-studio-backend/app/services/template_engine/placeholder_parser.py`

`extract_placeholders(pptx_path) -> List[Placeholder]` works as follows:

1. Opens the PPTX with python-pptx.
2. For each slide, iterates all text frames (shapes, table cells, grouped shapes) via `_iter_text_frames`.
3. For each text frame, calls `merge_multiline_placeholders(tf)` to collapse any placeholders whose description spans multiple PowerPoint paragraphs.
4. For each paragraph, uses `paragraph_text(para)` (from `run_merger.py`) to concatenate text across split XML runs.
5. Applies the regex `_RE_PLACEHOLDER` to find all `{{ }}` tokens.
6. Classifies each match by prefix: `#` = LOOP_START, `/` = LOOP_END, `*` = BULLET_ARRAY, none = TEXT.
7. Deduplicates by `(raw_text, slide_index)`.
8. Extracts the optional `| description` hint.
9. After all slides are scanned, calls `_assign_loop_contexts` to tag each non-loop placeholder with the name of its enclosing loop (based on slide index ranges).

### 1.7 Backend: Schema Generator Detail

**File:** `agent-studio-backend/app/services/template_engine/schema_generator.py`

`generate_schema(placeholders, title) -> Dict` builds a JSON Schema:

1. Detects loops via `detect_loops(placeholders)`.
2. For each loop, creates an `array` property whose `items` is an `object` with properties for each field inside the loop. The `item.` prefix is stripped from field paths. Bullet-array fields get `{ "type": "array", "items": { "type": "string" } }`; text fields get `{ "type": "string" }`.
3. For non-loop placeholders, adds top-level properties using the same type mapping. Dotted paths (e.g. `person1.full_name`) create nested `object` nodes automatically via `_set_nested`.
4. Top-level keys are always required; `additionalProperties: false` is set on all objects.
5. If a placeholder has a `| description` hint, it is added as a `description` field on the property **and** that field is marked as required inside its parent object. Fields without hints are optional, which prevents the LLM from hallucinating data for unused slots.
6. `_finalize_objects` walks the schema tree after construction, adding `additionalProperties: false` and `required` lists to every nested object node.

### 1.8 Frontend: Saving the Workflow

**File:** `agent-studio-frontend/src/components/builder/BuilderView.jsx`

When the user saves the workflow (manually or auto-save), `handleSave` serializes all canvas nodes (including their `config` objects which now contain `templateId`, `templateName`, and `outputSchema`) into `JSON.stringify(nodesArray)`. This is sent to `PUT /api/workflows/{workflowId}`.

**File:** `agent-studio-backend/app/routers/workflow_entity.py`

The backend stores `nodes` and `connections` as JSON strings in the `workflow_entity` table. The `outputSchema`, `templateId`, and `templateName` live inside each node's `config` object within that JSON.

---

## Phase 2: Workflow Execution (Chat Time)

This phase happens when a user opens a chat session linked to the workflow and sends a message.

### 2.1 Frontend: Sending a Message

**File:** `agent-studio-frontend/src/components/chat/ChatView.jsx`

`handleSendMessage` calls `sendMessageToSession(sessionId, message)`.

**File:** `agent-studio-frontend/src/api/client.js`

```
sendMessageToSession(sessionId, message, options?)
```

Sends `POST /api/chat/sessions/{sessionId}/messages` with `{ message, ...options }`.

### 2.2 Backend: Chat Service

**File:** `agent-studio-backend/app/services/chat_service.py`

`send_message(session_id, message, user_id, ...)`:

1. Loads the session and its linked workflow.
2. Loads conversation history from the DB.
3. Calls `_start_new_workflow(session, message, ...)` or `_resume_workflow(session, message, ...)`.
4. `_start_new_workflow` delegates to `workflow_executor.execute_workflow(workflow_id=session.workflow_id, input_data={...})`.

### 2.3 Backend: Workflow Executor

**File:** `agent-studio-backend/app/workflow/executor.py`

`execute_workflow(workflow_id, input_data, ...)`:

1. `_load_workflow(workflow_id)` -- loads the `WorkflowEntity` from the DB.
2. `_build_workflow_json(workflow)` -- parses `workflow.nodes` and `workflow.connections` from JSON strings into `{ "workflow": { "nodes": [...], "edges": [...] }, "version": "1.0" }`.

**File:** `agent-studio-backend/app/workflow/executor_execute.py`

3. `WorkflowParser.parse(workflow_json)` -- iterates node objects, extracts `config` from `node_data["config"]` or `node_data["data"]["config"]`. The `outputSchema` and `templateId` are inside this config.
4. `WorkflowGraphBuilder(parsed_workflow).build()` -- registers each node with its executor class from `NODE_REGISTRY`. Each agent node executor receives a `NodeConfig` that carries the full `config` dict.

### 2.4 Backend: Schema Injection into the LLM

The `outputSchema` reaches the LLM through two channels:

#### Channel A: System Prompt

**File:** `agent-studio-backend/app/workflow/nodes/agent_multi_instructions.py`

`MultiAgentInstructionBuilder.build()` checks `config.get("outputSchema")`. If present and the agent is **not** in tool-caller mode, it appends a `# REQUIRED OUTPUT SCHEMA` section to the system prompt via `_get_output_schema(config)`:

````
# REQUIRED OUTPUT SCHEMA
When calling the submit_deliverable tool, your data must match this JSON Schema:
```json
{schema}
```

IMPORTANT:
- This is a JSON SCHEMA definition. You must provide ACTUAL DATA that matches this schema.
- Do NOT return the schema itself -- return data that conforms to the schema structure.
````

#### Channel B: Tool Description

**File:** `agent-studio-backend/app/workflow/nodes/agent.py`

`_get_tools` parses `outputSchema` from config. If present, it injects a `SubmitDeliverableTool(output_schema=parsed_schema)` into the agent's tool list.

**File:** `agent-studio-backend/app/workflow/tools/submit_deliverable.py`

`SubmitDeliverableTool.__init__(output_schema=...)` appends the full JSON Schema to its tool `description`, so the LLM sees the schema both in the system prompt and in the tool's own description.

#### Channel C: Tool-Caller Mode (Structured Output)

**File:** `agent-studio-backend/app/workflow/nodes/agent_multi_loop.py`

When `outputSchema` is set and the agent has tool-calling capabilities, the executor enters tool-caller mode. After the main LLM conversation concludes, `_produce_deliverable` sends the schema to the LLM separately and uses structured output to produce the deliverable. The `route_next_action` function (from `agent_classifier.py`) decides when to trigger `submit_deliverable` based on conversation context.

### 2.5 Backend: Deliverable Validation and Storage

When the agent calls `submit_deliverable`:

**File:** `agent-studio-backend/app/workflow/tools/submit_deliverable.py`

`_run(deliverable)`:
1. Validates `deliverable` is a non-empty dict.
2. If a schema was provided, calls `_validate_against_schema(deliverable)` which uses `jsonschema.validate(instance=data, schema=self.deliverable_schema)`.
3. Returns a `DeliverableSubmission` object with `valid=True` and `data=deliverable` on success, or `valid=False` and `errors=[...]` on validation failure.

**File:** `agent-studio-backend/app/workflow/nodes/agent_multi_loop.py`

`_process_tool_result` checks if the tool result is a `DeliverableSubmission` with `valid=True` and extracts `tool_deliverable = tool_result.data`.

**File:** `agent-studio-backend/app/workflow/nodes/agent_multi_mode.py`

`_add_deliverable_to_output` wraps the deliverable into a structured entry and adds it to `output["deliverables"]` in the workflow state.

**File:** `agent-studio-backend/app/services/chat_service.py`

`_save_deliverables` reads `result.state.get("deliverables", [])` and for each entry calls `deliverable_repo.upsert_by_session_and_agent(...)`.

**File:** `agent-studio-backend/app/repositories/deliverable_repository.py`

`upsert_by_session_and_agent` creates or updates an `AgentDeliverable` row in the `agent_deliverable` table, storing `deliverable=json.dumps(deliverable_data)` and `deliverableSchema=schema`.

### 2.6 Frontend: Receiving the Deliverable

**File:** `agent-studio-frontend/src/components/chat/ChatView.jsx`

After `sendMessageToSession` returns, the frontend calls `getSessionDeliverables(sessionId)` which GETs `/api/chat/sessions/{sessionId}/deliverables`. The deliverables are stored in React state and rendered via `DeliverableReview` components.

---

## Phase 3: Fill PowerPoint Template

This phase happens when the user clicks "Fill PowerPoint Template" in the deliverable review panel.

### 3.1 Frontend: templateId Resolution

**File:** `agent-studio-frontend/src/components/chat/ChatView.jsx`

When rendering `DeliverableReview`, the `templateId` prop is resolved via an inline function:

1. Gets the current deliverable step: `outputSteps[activeStepTab]`.
2. Extracts `agentId` from the step.
3. Calls `parseWorkflowGraph()` to get the workflow's node list.
4. Finds the node matching `agentId`.
5. Returns `node?.config?.templateId || null`.

This connects the deliverable back to the specific agent node that produced it, and from there to the template that was uploaded for that node.

### 3.2 Frontend: Export Handler

**File:** `agent-studio-frontend/src/components/chat/DeliverableReview.jsx`

`handleExportWithTemplate`:

1. Guards: `if (!templateId || !deliverable?.deliverable) return`.
2. Sets loading state: `setIsExportingTemplate(true)`.
3. Calls `fillTemplate(templateId, deliverable.deliverable)` from `@/api/template-client`.
4. Creates a temporary `<a>` element with `href = URL.createObjectURL(blob)` and `download = "{AgentLabel}.pptx"`.
5. Programmatically clicks the link to trigger the browser download.
6. Cleans up: removes the element and revokes the object URL.

### 3.3 Frontend: API Client

**File:** `agent-studio-frontend/src/api/template-client.js`

```
fillTemplate(templateId, data)
```

Sends `POST /api/templates/{templateId}/fill` with `{ data }` as JSON. Returns the response as a `Blob` (binary PPTX).

### 3.4 Backend: Fill Route

**File:** `agent-studio-backend/app/routers/template_routes.py`

```
POST /api/templates/{template_id}/fill
```

Request body: `{ "data": { ... } }` (the deliverable's structured data).

1. Loads the template metadata via `svc.get_template(template_id)`.
2. Calls `svc.fill(template_id, body.data)`.
3. Returns a `StreamingResponse` with the PPTX bytes, content type `application/vnd.openxmlformats-officedocument.presentationml.presentation`, and a `Content-Disposition: attachment` header.

### 3.5 Backend: TemplateService.fill

**File:** `agent-studio-backend/app/services/template_service.py`

`fill(template_id, data) -> Optional[bytes]`:

1. Loads the template row from DB: `self.repo.get_by_id(template_id)`.
2. Downloads the sanitized PPTX blob: `self.storage.download_blob(row.blobName)`.
3. Writes blob bytes to a temp file (python-pptx needs a file path).
4. Calls `fill_template(tmp_path, data)` from the template engine.
5. Deletes the temp file.
6. Returns the filled PPTX bytes.

### 3.6 Backend: template_filler.fill_template

**File:** `agent-studio-backend/app/services/template_engine/template_filler.py`

`fill_template(template_path, data) -> bytes` uses a "build from scratch" pattern:

1. **Parse:** Opens the template as a read-only source (`src = Presentation(template_path)`). Extracts placeholders, detects variant groups and loops.
2. **Plan:** `_build_slide_plan(src, placeholders, variant_groups, loops, data)` computes an ordered list of `(source_slide_index, data_dict)` tuples describing every slide in the final output:
   - Discards variant slides that do not match the data array length (keeps the best-matching variant).
   - Removes loop marker slides (`{{# }}` / `{{/ }}`).
   - Expands loop body slides once per array item, each with a scoped `{"item": current_element, ...top_level_data}` dict.
   - Passes non-variant, non-loop slides through unchanged.
3. **Assemble:** Opens the template a second time as the destination (`dst = Presentation(template_path)`) to preserve themes and layouts. Removes all slides from `dst` via `_remove_all_slides`. Then copies each planned slide from `src` into `dst` using `pptx-slide-copier`'s `SlideCopier.copy_slide`.
4. **Fill:** Iterates the assembled slides in order. For each slide: strips variant markers (if a shape contains *only* variant markers and whitespace, the entire shape is removed so styled containers like colored boxes don't leak into the output), removes loop markers, then calls `_fill_slide(slide, slide_data)`.
5. **Save:** Writes to a `BytesIO` buffer in a single save operation and returns the bytes.

### 3.7 Backend: _fill_slide Detail

**File:** `agent-studio-backend/app/services/template_engine/template_filler.py`

`_fill_slide(slide, data)`:

1. For each text frame on the slide (shapes, tables, groups):
   - Calls `merge_multiline_placeholders(tf)` to collapse any `{{ }}` tokens split across paragraphs.
   - For each paragraph:
     - Gets full text via `paragraph_text(para)`.
     - Checks for bullet-array match (`{{* path }}`). If found, resolves the data via `_resolve(data, path)` and calls `_fill_bullets(para, array_data)` which replaces the single placeholder paragraph with one paragraph per list item, cloning the original's formatting.
     - Otherwise, iterates all `{{ path }}` matches. For each, resolves the value via `_resolve(data, path)` and calls `replace_all_in_paragraph(para, match, str(value))`.

### 3.8 Backend: Slide Copier (pptx-slide-copier)

Slide assembly uses the third-party `pptx-slide-copier` library instead of hand-written clone/remove logic. `SlideCopier.copy_slide(src, src_index, dst)` copies a slide from a read-only source presentation into a writable destination, handling relationships, images, and layouts reliably without the OPC partname collision issues that plague python-pptx's internal cloning.

### 3.9 Backend: Multi-Paragraph Merge Detail

**File:** `agent-studio-backend/app/services/template_engine/run_merger.py`

`merge_multiline_placeholders(text_frame) -> int`:

PowerPoint stores line-breaks inside a text box as separate `<a:p>` XML elements. When a placeholder description contains line-breaks, the opening `{{` and closing `}}` end up in different paragraphs.

The function:
1. Iterates paragraphs sequentially.
2. For each paragraph, counts `{{` and `}}` occurrences.
3. If `open_count > close_count` (unclosed placeholder), scans forward through subsequent paragraphs until the cumulative `}}` count balances.
4. Concatenates the continuation paragraphs' text into the anchor paragraph's last XML run.
5. Removes the now-empty continuation `<a:p>` elements from the `<a:txBody>`.
6. Re-fetches the paragraph list and continues.

This runs before any regex matching in both the parser and the filler, making the engine resilient to descriptions of any length.

---

## Module Reference

| Module | File | Public API | Purpose |
|--------|------|-----------|---------|
| **template_sanitizer** | `app/services/template_engine/template_sanitizer.py` | `sanitize_template(raw: bytes) -> bytes` | Strip add-in shapes and prune orphaned OPC parts |
| **run_merger** | `app/services/template_engine/run_merger.py` | `paragraph_text`, `replace_in_paragraph`, `replace_all_in_paragraph`, `merge_multiline_placeholders` | Handle split XML runs and cross-paragraph placeholders |
| **placeholder_parser** | `app/services/template_engine/placeholder_parser.py` | `extract_placeholders`, `detect_loops`, `summarise`, `Placeholder`, `PlaceholderKind` | Scan PPTX for all placeholder tokens |
| **schema_generator** | `app/services/template_engine/schema_generator.py` | `generate_schema`, `schema_to_json` | Convert placeholders to JSON Schema |
| **template_filler** | `app/services/template_engine/template_filler.py` | `fill_template`, `fill_template_to_file` | Plan slide assembly, copy slides via pptx-slide-copier, fill placeholders, produce final PPTX |
| **TemplateService** | `app/services/template_service.py` | `upload_template`, `fill`, `get_template`, `delete_template` | Orchestration layer (blob storage + DB + engine) |
| **TemplateRepository** | `app/repositories/template_repository.py` | `create`, `get_by_id`, `list_by_workflow`, `delete` | DB persistence for template metadata |

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/templates/upload` | Upload and analyze a PPTX template |
| GET | `/api/templates/{id}` | Get template metadata |
| GET | `/api/templates/{id}/schema` | Get the generated JSON Schema |
| GET | `/api/templates/workflow/{id}` | List templates for a workflow |
| POST | `/api/templates/{id}/fill` | Fill template with data, return PPTX |
| DELETE | `/api/templates/{id}` | Delete template (blob + DB) |

### Frontend Components

| Component | File | Role |
|-----------|------|------|
| **OutputSchemaBuilder** | `agent-studio-frontend/src/components/builder/OutputSchemaBuilder.jsx` | Template upload UI in "Generate Schema" modal |
| **DeliverableReview** | `agent-studio-frontend/src/components/chat/DeliverableReview.jsx` | "Fill PowerPoint Template" button in deliverable review |
| **template-client** | `agent-studio-frontend/src/api/template-client.js` | API client for all template endpoints |
