# Agent Studio (vector410)

Full-stack AI agent platform with a visual workflow designer and execution engine.

## Architecture

- **Frontend**: React 19, Vite 7, Tailwind CSS 4, XY Flow (React Flow)
- **Backend**: FastAPI (Python), LangGraph/LangChain execution engine
- **Data**: PostgreSQL 18 (pgvector/VectorChord), Redis 7, Azure Blob Storage (Azurite for local dev)
- **Auth**: JWT with optional Azure Entra ID

## Quick Start

```bash
# 1. Copy and configure environment
cp example.env .env
# Edit .env with your API keys (at minimum OPENAI_API_KEY)

# 2. Start all services
docker-compose up --build

# 3. Access the app
# Frontend: http://localhost:81
# Backend API: http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Services


| Service    | Port  | Description                          |
| ---------- | ----- | ------------------------------------ |
| Frontend   | 81    | React SPA (served via Nginx)         |
| Backend    | 8000  | FastAPI application                  |
| PostgreSQL | 5432  | Primary database with vector support |
| Redis      | 6379  | Caching and rate limiting            |
| Azurite    | 10000 | Azure Blob Storage emulator          |


## Features

- Visual workflow designer with drag-and-drop node canvas
- Multi-agent orchestration via LangGraph
- Knowledge Bases with RAG (semantic, BM25, hybrid search) and delimiter-based chunking
- Human-in-the-Loop (HITL) review nodes
- Deep Research mode (multi-agent research orchestration)
- Chat interface with file upload and streaming responses
- Generative UI (OpenUI Lang) for structured deliverables -- JSON from `submit_deliverable` is translated at display time (LLM + component library) and rendered as charts, tables, slides, and cards. Agent chat uses markdown. See [docs/openui-integration.md](docs/openui-integration.md).
- Deliverable export menu (in the expanded deliverable view) -- exports are built from the structured deliverable JSON, not the live OpenUI render:
  - **Create Presentation in Edwin** -- on-demand handoff that sends the deliverable to Edwin and opens it in a new tab (same mechanism as the `powerpoint-generator` workflow node)
  - **Fill PowerPoint Template** -- upload any PPTX with `{{ }}` placeholders; the system auto-detects fields, generates a matching output schema, and fills the template from structured deliverable data at export time
  - **Generate AI PowerPoint** -- LLM generates a storyline then builds each slide with layout selection (available when no template is configured)
  - **Export as PDF / Word / HTML** -- branded, portable documents generated from the deliverable content
- Workflow marketplace for sharing and importing workflows

## Knowledge Base Chunking Methods


| Method     | Description                                                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Fixed Size | Fixed character-count chunks with configurable overlap                                                                                           |
| Recursive  | Hierarchical splitting using ordered separators (recommended for general text)                                                                   |
| Sentence   | Sentence-boundary splitting                                                                                                                      |
| Paragraph  | Double-newline splitting                                                                                                                         |
| Delimiter  | Splits on an exact delimiter string -- each segment becomes one chunk. Useful when records are separated by a known marker (e.g. `===CV_END===`) |


## PPTX Template Engine

Upload any `.pptx` template with placeholder syntax and the platform automatically handles the rest:


| Syntax                        | Purpose                                                                 | Example                                 |
| ----------------------------- | ----------------------------------------------------------------------- | --------------------------------------- |
| `{{ field }}`                 | Text substitution                                                       | `{{ client_name }}`                     |
| `{{* field }}`                | Bullet list (one paragraph per item)                                    | `{{* key_findings }}`                   |
| `{{+ field }}`                | Repeat-group scalar field (paired with `{{* }}` in the same array item) | `{{+ projects_left.title }}`            |
| `{{# loop }}` / `{{/ loop }}` | Slide duplication per array item                                        | `{{# projects }}` ... `{{/ projects }}` |
| `{{@ array | count }}`        | Variant marker -- keep this slide only when the array has *count* items | `{{@ people | 4 }}`                     |


**Workflow**:

1. In the workflow builder, configure an agent node and upload a `.pptx` template in the **PPTX Template** section.
2. The system extracts all placeholders and generates a matching JSON output schema automatically.
3. At runtime, the agent produces structured JSON matching that schema.
4. After HITL review, click **Fill PowerPoint Template** to download the filled `.pptx`.

Notes:

- For repeat groups, keep `{{+ ... }}` (title) and `{{* ... }}` (bullets) in consecutive paragraphs inside the same text box.
- Generated schema marks repeat arrays as required with at least one item, and each item requires both `title` and `bullets`.
- Text replacement preserves the template's existing run/paragraph styling; set desired color in the placeholder's text style inside PowerPoint.
- Export fills exactly what the deliverable JSON contains. If a repeat array has one item, one title+bullet block is rendered; if it has N items, N blocks are rendered.
- Use agent workflow instructions to guide extraction strategy (for example, encouraging broader project coverage); the template engine itself is schema-driven.
- Template metadata and blob access are owner-scoped (user isolation via RLS + per-request ownership checks in template routes/services).
- **Variant slides**: place `{{@ array | count }}` on each variant slide. At fill time the engine counts `len(data[array])`, keeps only the matching variant, and removes the rest. Variant slides can reference array items by index (e.g. `{{ people.0.name }}`). The schema auto-generates `minItems`/`maxItems` from the available variant range. If no exact match exists, the nearest lower-or-equal variant is selected. Shapes that contain only variant markers (e.g. colored boxes used as visual labels) are removed entirely from the output.
- **Slide assembly** uses a "build from scratch" pattern: the template is parsed to compute a slide plan, then a fresh presentation is assembled by copying only the required slides via `pptx-slide-copier`. This avoids python-pptx's known slide-cloning/removal corruption issues.

Endpoints: `POST /api/templates/upload`, `GET /api/templates/{id}`, `POST /api/templates/{id}/fill`, `DELETE /api/templates/{id}`.

**Documentation:**

- [Template Authoring Guide](agent-studio-backend/docs/pptx-template-authoring-guide.md) -- placeholder syntax, template patterns, common mistakes, and LLM instruction templates
- [Template Engine Technical Flow](agent-studio-backend/docs/template-engine-technical-flow.md) -- full code-level trace from upload through execution to export

## Project Structure

```
vector410/
  agent-studio-backend/     # FastAPI backend
    app/
      config/               # Settings and configuration
      connectors/           # Azure Storage, external connectors
      core/                 # Dependencies, request context
      db/                   # Database models, migrations, connection
      domain/entities/      # Domain models (KnowledgeBase, ChunkingConfig)
      repositories/         # Data access layer
      routers/              # API route handlers
      services/             # Business logic (incl. PowerPoint builder/schema)
        template_engine/    # PPTX template placeholder extraction, schema gen, filling
      workflow/             # LangGraph workflow engine
        nodes/              # Workflow node implementations
        tools/              # LangChain tools (web_search, calculator, etc.)
      utils/                # Security, helpers, chunking utilities
    docs/                   # Technical documentation (template authoring guide, engine flow)
  agent-studio-frontend/    # React frontend
    src/
      api/                  # API client
      components/           # UI components (builder, chat, workspace)
      context/              # React contexts (auth, workflow, theme)
      data/                 # Node palette config, static data
  docker-compose.yaml       # Multi-service Docker setup
  example.env               # Environment variable template
```

## Environment Variables

See `example.env` for the full list. Key variables:

- `OPENAI_API_KEY` -- Required for LLM operations
- `POSTGRES_*` -- Database connection settings
- `REDIS_*` -- Redis connection settings
- `AZURE_STORAGE_CONNECTION_STRING` -- Blob storage (defaults to Azurite)
- `JWT_SECRET_KEY` -- JWT signing key
- `VITE_API_BASE_URL` -- Frontend API base URL
## Generative UI (OpenUI Lang)

Structured deliverables stay **JSON** for HITL and export. After a deliverable
is saved, the backend pretranslates each `sections[]` item to its own OpenUI
Lang in parallel (LLM + `system.txt` from `generatePrompt()`) and persists a
JSON array of per-section Lang strings on `agent_deliverable.openuiLang`. The
frontend builds a deterministic tab bar from `sections[]` (one tab per section)
and renders each Lang via `OpenUIMessage` / `Renderer` with no runtime LLM call;
the inline card and the expanded modal use the same component. If a row's
`openuiLang` is missing or invalid, `list_session_deliverables` self-heals by
re-scheduling translation on the next fetch. A required `summary` field is
injected into every agent's output schema so a plain-prose summary is always
available above the rendered card. Agent chat uses markdown, not OpenUI Lang.

```bash
# Regenerate component-spec.json + system.txt (also runs on npm run dev / build)
cd agent-studio-frontend && npm run generate:openui
```

OpenUI Lang translation model: `service.openui_translate` in `agent-studio-backend/config/llm_models_inventory.yaml` (overridable via the admin LLM catalog).

See [docs/openui-integration.md](docs/openui-integration.md) for architecture and sandbox.

Dev widget gallery: http://localhost:5180/?test=openui&gallery=1 (`npm run openui:sandbox:gallery`).
- `EDWIN_API_URL` -- Edwin backend API base for the PowerPoint Generator node (`POST /api/handoffs`)

