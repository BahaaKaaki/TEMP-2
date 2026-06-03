# OpenUI Component Audit — "do these make sense for deliverables?"

> Every component registered in `library.jsx` / emitted in `system.txt`, judged for
> **static analytical consulting deliverables** (benchmarks, org structures, financial
> analysis). Verdicts drive the prompt engineering in `prompt-options.mjs`.
>
> Legend: **CORE** (use constantly) · **USE-WHEN** (only if the data clearly fits) ·
> **AVOID** (a better option almost always exists) · **NEVER** (interactive; off by policy).

## Layout
| Component | Verdict | Rationale |
|---|---|---|
| `Stack` | **CORE** | The backbone. `root = Stack([...], "column", "l")`. |
| `Card` | **CORE** | Primary grouping container; full-width, elevation variants. |
| `Tabs` / `TabItem` | **USE-WHEN** | Alternative views of the *same* data inside one section (chart vs table). NOT for sibling sections — the frontend tab bar handles those. |
| `Accordion` / `AccordionItem` | **USE-WHEN** | Reserve for pros/cons/risks and optional dense detail. Not for primary insights (hides them behind a click). |
| `Steps` / `StepsItem` | **USE-WHEN** | Genuinely ordered processes, transitions, roadmaps. |
| `Carousel` | **AVOID** | Horizontal scroll hides content and prints/exports poorly. |
| `Separator` | **AVOID** | Cards already separate content; low value. |
| `Modal` | **NEVER** | Interactive (`open` binding). |

## Content
| Component | Verdict | Rationale |
|---|---|---|
| `CardHeader` | **CORE** | Titles/subtitles for cards. |
| `TextContent` | **CORE** | Prose + headings (via `size`). Citation-aware override. |
| `MarkDownRenderer` | **CORE** | Bulleted/rich lists. **Citation-aware** — use for any cited list. |
| `TextCallout` | **USE-WHEN** | A single section summary/takeaway only. |
| `Callout` | **NEVER** | Has a `visible` binding (interactive auto-dismiss). Use `TextCallout`. |
| `CodeBlock` | **USE-WHEN** | Code, commands, structured payloads. |
| `Image` / `ImageBlock` / `ImageGallery` | **USE-WHEN** | Only when the JSON carries image URLs (rare for us). |

## Tables
| Component | Verdict | Rationale |
|---|---|---|
| `Table` / `Col` | **CORE** | Facts tables, row data, comparisons. Citation-aware overrides. The lossless default for arrays of objects. |

## Charts
| Component | Verdict | Rationale |
|---|---|---|
| `HorizontalBarChart` | **USE-WHEN** | Best for ranked lists / long category labels (e.g. peer comparisons). |
| `BarChart` | **USE-WHEN** | Category comparisons across one+ numeric series. |
| `LineChart` / `AreaChart` | **USE-WHEN** | Time/ordered numeric series (Area for cumulative/volume). |
| `RadarChart` | **USE-WHEN** | Multi-attribute comparison of entities — genuinely useful for benchmark scoring. |
| `PieChart` / `SingleStackedBarChart` | **USE-WHEN** | Part-to-whole numeric breakdowns. |
| `RadialChart` | **AVOID** | Decorative; `PieChart` is clearer. |
| `ScatterChart` (+ `ScatterSeries`, `Point`) | **USE-WHEN** | Correlation/distribution (two numeric dims). Rare here. |
| `Series` / `Slice` | helpers | Required by the chart calls above. |
| **All charts** | rule | **Additive — never replace the complete Table when row-level data exists.** |

## Data display
| Component | Verdict | Rationale |
|---|---|---|
| `TagBlock` | **CORE** | Short label arrays — slide numbers, categories, tickers. |
| `Tag` | **USE-WHEN** | A single colored status badge (e.g. risk level), often in a `Col` cell. |

## Agent Studio additions
| Component | Verdict | Rationale |
|---|---|---|
| `TreeView` | **CORE** | Org charts / any parent-child hierarchy (`org_tree`). High value. |
| `QueryTrace` | **USE-WHEN** | Only when the JSON contains query/tool provenance to show. |
| `Slide` | **AVOID (by default)** | Overlaps with Card+TextContent+MarkDownRenderer; mixing Slide and Card across sections breaks consistency. Reserve for explicitly slide-shaped output. |
| `Heading` | **AVOID** | Duplicates `TextContent("…","large-heavy")` / `CardHeader`, **and is not citation-aware** (drops `[n]`). |
| `Bullets` | **AVOID** | Duplicates `MarkDownRenderer` bullet list **and is not citation-aware** (drops `[n]`). |
| `Code` | **AVOID** | Use `CodeBlock`. |
| `Link` | **USE-WHEN** | No base inline-link equivalent; allow only for a genuine clickable URL. |

## Gaps (compose now; build later)
- **KPI / stat tile** — no dedicated component. Compose: `Card([TextContent(label,"small"), TextContent(value,"large-heavy")], "sunk")` in a `Stack` row+wrap. *(A real `Stat` component is a good follow-up.)*
- **Metric with delta/trend**, **two-column comparison** — compose with `Stack`/`Table` for now.

## Code smells found in `library.jsx` (recommended follow-ups — need a full frontend rebuild)
1. **`TextContent` registered twice** — `CitationAwareTextContent` (citation overrides) *and* the plain `primitives` `TextContent` (in `agentStudioComponents`, library.jsx:56-65). One silently wins; if the plain one wins, `TextContent` loses inline-citation rendering. **Fix:** drop `TextContent` from `agentStudioComponents`.
2. **`Heading`/`Bullets`/`Code`/`Link` are not citation-aware** — they bypass the citation overrides, so `[n]` markers render as dead text. **Fix:** either make them citation-aware or remove them from the library; until then the prompt forbids them for cited content.
3. **Disabled-component bloat** — `Form`/`Input`/`Modal`/`Buttons`/binding docs still ship in `system.txt` (~70+ lines) because they remain registered even with `toolCalls/bindings:false`. **Fix:** register a render-only library subset for spec generation. Until then the prompt's NEVER list overrides them.

## Net "best way to display a deliverable"
A consistent vertical **`Stack` of full-width `Card`s**: snapshot card → facts `Table` (with `Tag`/`TagBlock` accents) → cited insights via `MarkDownRenderer` → `TreeView` for hierarchies → charts **only** for genuinely numeric comparisons (additive to the table) → optional KPI stat tiles for headline numbers. Reserve `Tabs`/`Accordion`/`Steps`/`TextCallout` for the specific shapes above, and never reach for interactive components. The biggest *ceiling-raiser* remains a whole-deliverable overview pass (cross-section comparison) — out of scope while we keep per-section translation.
