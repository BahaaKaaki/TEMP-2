# OpenUI Lang — Deep Dive & Translation/Prompt Research

> Research artifact for `feat/openui-investigation`. Goal: understand OpenUI Lang
> thoroughly, document how we translate deliverable JSON → OpenUI Lang today, and
> identify concrete prompt/pipeline enhancements.
>
> Sources: official docs (thesys `thesysdev/openui`, openui.com), our generated
> `system.txt`, and a worked example (`temp1.md` source JSON → `temp2.md` output).
> See **§9 Sources**.

---

## 1. What OpenUI Lang is

OpenUI Lang is a **compact, line-oriented language designed for LLMs to emit UI**,
as a more token-efficient, predictable, and stream-friendly alternative to JSON
UI trees. The project bills it as "The Open Standard for Generative UI" and
reports it is up to **~67% more token-efficient than JSON** for the same UI.

Core idea: a **library** (components defined with Zod schemas + React renderers)
is the *contract* between the app and the model. The library defines exactly which
components the LLM may use and how each renders. The model writes a short program;
a `<Renderer>` parses it and produces React elements.

Key properties:
- **Line-oriented**: one `identifier = Expression` assignment per line → trivial to
  parse and to render *progressively* during streaming.
- **Positional arguments**: component args map to props **by Zod schema key order**,
  not by name. There is **no `name: value` colon syntax** — using it silently breaks.
- **Forward references / hoisting**: an identifier may be used before it is defined;
  references resolve after the full program is parsed.
- **Streaming-first**: output is re-parsed on every chunk, so writing `root` first
  yields a top-down reveal (shell → components → leaf data).

---

## 2. The language (full mental model)

### 2.1 Statement kinds
```text
# Component statement
header = CardHeader("Title", "Subtitle")

# Reactive state declaration (interactive apps only)
$showEdit = false

# Data read (tool-backed apps only)
data = Query("tool_name", {arg: $variable}, {rows: []}, refreshIntervalSeconds?)

# Data write (runs only when triggered by @Run)
result = Mutation("tool_name", {arg: $variable})

# Root entry point — ALWAYS required
root = Stack([header, content])
```
> In **our** static deliverable renderer, only **component statements** + `root`
> are used. Reactive state, `Query`/`Mutation`, bindings, and actions are
> deliberately disabled (see §3).

### 2.2 Expressions & data types
- Literals: strings (`"..."`, double-quoted, backslash-escaped), numbers, booleans
  (`true`/`false`), `null`, arrays (`[...]`), objects (`{...}`), and component calls
  `TypeName(arg1, arg2, ...)`.
- **Member access & array "pluck"** (v0.5):
  ```text
  tbl = Table([Col("Title", data.rows.title)])   // plucks `title` from each row
  kpi = TextContent("" + data.total)              // single field access
  ```
- **Ternary / conditional rendering**:
  ```text
  $showEdit ? editForm : null
  status == "error" ? Callout("error", "Failed", errorMsg) : null
  ```

### 2.3 Built-in `@` helper functions (v0.5)
Inline data transforms — aggregation, filtering, sorting, iteration:
```text
@Count(a)  @Sum(a)  @Avg(a)  @Min(a)  @Max(a)  @Round(x)
open   = @Filter(rows, "status", "==", "open")
sorted = @Sort(rows, "created", "desc")
tags   = @Each(rows, "t", Tag(t.priority, null, "sm"))
```
> We disable tool-backed data, so these are mostly irrelevant to us **except**
> `@Each`/`@Filter`/`@Count` could be used for styled table cells — but our JSON is
> already materialized, so we generally don't need them.

### 2.4 Reference & rendering rules (critical)
- `root` must be defined and is the only entry point.
- **Every variable except `root` must be referenced by at least one other variable**,
  transitively reachable from `root`. **Unreferenced variables are silently dropped
  and do not render** — this is *silent data loss*, not an error.
- Optional args may be omitted from the end.

### 2.5 The Renderer & error handling
`<Renderer response library isStreaming onError ... />` (`@openuidev/react-lang`).
- `onError(errors)` returns **structured parser/query errors** and is explicitly
  intended for **automated correction loops**. (We do not use this server-side yet —
  see §7.)

---

## 3. How *our* system uses OpenUI Lang

### 3.1 Build-time: library → component spec → system prompt
```
src/openui/library.jsx                     (base @openuidev/react-ui lib
  → createLibrary(...)                       + custom TreeView/Slide/QueryTrace
                                             + citation-aware overrides)
  → `openui generate --json-schema`        → src/openui/generated/component-spec.json
  → scripts/generate-openui-prompt.mjs     → generatePrompt({...spec, preamble,
       (@openuidev/lang-core)                 additionalRules, examples,
                                              toolCalls:false, bindings:false,
                                              editMode:false, inlineMode:false})
  → writes system.txt to BOTH:
       src/openui/generated/system.txt
       agent-studio-backend/app/services/openui_prompts/system.txt
```
- `generate-openui-prompt.mjs:71-82` **strips a contradictory lang-core rule**
  ("generate realistic/plausible data") because we must only render facts from the
  source JSON, and **fails the build** if the wording changes — a nice guardrail.
- `prompt-options.mjs` supplies the `preamble` (lines 2-5), 29 `additionalRules`
  (6-34), and 8 `examples` (36-112).

### 3.2 Run-time: per-section JSON → Lang (backend, fire-and-forget)
`agent-studio-backend/app/services/openui_translate_service.py`:
- System message = `build_system_prompt()` (the generated `system.txt`) **+**
  `_TASK_PROMPT` (lines 39-51). Human message = `"Structured JSON to render:\n" +
  <section JSON>`.
- `_strip_externally_rendered_fields` removes the top-level `summary` (lines 122-130)
  because the chat UI renders the deliverable summary *outside* the OpenUI block.
- **Per-section** translation: `translate_deliverable_section_langs` (198-220) splits
  on `content.sections[]` and translates each section **independently and in parallel**
  (semaphore = 5, line 34), one retry per section (174-195), failures stored as `""`.
- Validation is a single regex: output must contain `^root\s*=` (`_ROOT_RE`,
  lines 31, 160-161). **No real parse/lint.**
- Model/params: `gpt-5.5` → temperature **1.0**, `reasoning.effort=low`,
  `verbosity=low` (77-106); other models → temperature **0.2**. Output cap
  `OPENUI_TRANSLATE_MAX_TOKENS` default **8192** (84-94).
- Result (a JSON array of per-section Lang strings) is persisted to
  `agent_deliverable.openuiLang`; the frontend reads the column directly.

### 3.3 The component library available to the model
From `system.txt`:
- **Layout**: `Stack`, `Tabs`/`TabItem`, `Accordion`/`AccordionItem`, `Steps`/`StepsItem`,
  `Carousel`, `Separator`, `Modal`.
- **Content**: `Card`, `CardHeader`, `TextContent`, `MarkDownRenderer`, `Callout`,
  `TextCallout`, `Image`/`ImageBlock`/`ImageGallery`, `CodeBlock`.
- **Tables**: `Table`, `Col`.
- **Charts**: `BarChart`, `LineChart`, `AreaChart`, `RadarChart`, `HorizontalBarChart`,
  `Series`; `PieChart`, `RadialChart`, `SingleStackedBarChart`, `Slice`; `ScatterChart`,
  `ScatterSeries`, `Point`.
- **Forms/Buttons** (disabled by policy): `Form`, `FormControl`, `Input`, `TextArea`,
  `Select`, `DatePicker`, `Slider`, `CheckBoxGroup`, `RadioGroup`, `SwitchGroup`,
  `Button`, `Buttons`.
- **Data display**: `TagBlock`, `Tag`.
- **Agent Studio Text**: `Heading`, `Text`, `Bullets`, `Code`, `Link`.
- **Agent Studio Data**: `QueryTrace`.
- **Agent Studio Domain**: `Slide`, `TreeView`.

---

## 4. How JSON→Lang translation looks today (worked example)

Source `temp1.md` is a multi-section "comparable-company benchmark" deliverable
(sections: Microsoft, AWS, NTT, Orange, Telefónica, Summary), each section's
`content` carrying the same shape: `sector, geography, span_of_control, strategy,
restructuring_impact, insights[], slide_nums[], summary, recommendations[], org_tree`.

Output `temp2.md` contains **six independent programs** (one `root = Stack(...)` per
section). The canonical intended rendering per section is roughly:
- snapshot `Card`(`CardHeader(section_title, subtitle)`, `TextContent(description)`)
- a Field/Value facts `Table`
- `insights[]` → `MarkDownRenderer` bullet list in a `Card`
- `org_tree` → `TreeView`

**What's good:** citation markers (`[6]`, `[16]`, …) are preserved inline; empty
fields (`summary:""`, `recommendations:[]`) are correctly omitted; org trees render
losslessly as `TreeView`; data is largely complete.

**The recurring example pattern** (the one you pasted) is the standard "card per
string-array" shape — each block is `Card([CardHeader(...), MarkDownRenderer("- …\n- …", "clear")])`:
```text
…Header = CardHeader("Growth priorities")
prioritiesList = MarkDownRenderer("- Gemini/AI integration…\n- GCP enterprise share\n- YouTube monetization", "clear")
valueChainCard = Card([valueChainHeader, valueChainList], "card")
…
```
This is consistent with our "canonical string arrays" rule — but note (a) the leading
variable was truncated in the paste (`er = …`), and (b) it shows how quickly a section
becomes a long stack of near-identical cards.

---

## 5. Findings — what works and what doesn't

### ✅ Working well
- Faithful fact/citation preservation and lossless org-tree rendering.
- Sensible empty-field omission.
- Robust *infra*: parallel per-section translate, retry, self-heal, persisted cache.

### ⚠️ Problem 1 (biggest): cross-section inconsistency
Because each section is translated by an **independent LLM call with no sibling
context**, the *same field type is rendered differently across sibling sections* —
exactly the failure the prompt's "consistency" rule (`system.txt:284`,
`prompt-options.mjs:16`) tries to prevent. Concrete evidence in `temp2.md`:

| Field | Microsoft | NTT | Orange | Telefónica | Summary |
|---|---|---|---|---|---|
| `slide_nums` | facts-table cell `"6, 32"` (L8-9) | **dedicated Card + Table** (L47-50) | — | — | **`TagBlock`** (L115) |
| `strategy` / `restructuring_impact` | in facts `Table` | **`TextCallout`** (L42-43) | facts `Table` | **separate `strategyCard` table** (L86-90) | callout |
| `insights[]` | `Card` + `MarkDownRenderer` | `Card` | **`Accordion`** (L64) | `Card` | `Accordion` |

So slide numbers alone are rendered **three different ways**, and NTT's
`TextCallout` for `strategy` **directly violates** our own rule (`system.txt:291`:
"Do not use TextCallout for … strategy … restructuring_impact"). Visually, sibling
tabs look noticeably different.

### ⚠️ Problem 2: internal prompt contradictions
- **`slide_nums` is doubly specified**: rule "canonical facts table" lists `slide_nums`
  among facts-table fields (`system.txt:286`) *and* "canonical tags" says render slide
  numbers as `TagBlock` (`system.txt:287`). The model can't be consistent because the
  prompt isn't.
- Two confusingly-similar callout components with **different variant enums**:
  `Callout` variants `info|warning|error|success|neutral` (L44) vs `TextCallout`
  variants `neutral|info|warning|success|danger` (L45) — note `error` vs `danger`.

### ⚠️ Problem 3: prompt bloat + dead/contradictory sections
Even though `generatePrompt` is called with `toolCalls:false, bindings:false,
editMode:false, inlineMode:false`, `system.txt` **still documents** Forms/Inputs,
`Modal`, `$binding<...>` props, and `@Set`/`@Filter`/`@Sort`/`@Count` + `Query`
examples (e.g. L30, L52, L58-63, L91-162) — because those components/props remain in
the registered library. Then the task prompt + rule `system.txt:301` says "do not use
Forms, Inputs, … bindings, Query, @Set …". The model is shown rich capabilities and
then told not to use them: wasted input tokens **and** an avoidable contradiction
surface.

### ⚠️ Problem 4: weak output validation
We only check for a `root =` line (`_ROOT_RE`). A response that is **truncated**
(hitting the 8192-token cap on a big section) or that **references an undefined
variable** (→ silent drop / partial render) still passes this check. There is **no
real parse**, so malformed-but-`root`-prefixed output is persisted and only fails at
render time (frontend falls back to raw JSON).

### ⚠️ Problem 5: we pay input tokens for empty/redundant JSON
We strip only the **top-level** `summary` (`_strip_externally_rendered_fields`). The
section payloads still include `summary:""`, `recommendations:[]`, and other empty
fields. We send them (input-token cost) and rely on the model to omit them.

### ⚠️ Problem 6: text-component overlap
There are two overlapping text stacks: base `TextContent`/`MarkDownRenderer` vs
Agent Studio `Heading`/`Text`/`Bullets`. The prompt doesn't declare a single
canonical choice, inviting per-section drift. (Today's output uses `TextContent` +
`MarkDownRenderer`; nothing stops a section from using `Bullets`.)

### ⚠️ Problem 7 (minor): model/temperature works against consistency
`gpt-5.5` is forced to **temperature 1.0** (reasoning-model API constraint). Higher
temperature → more structural variation between sibling sections. For a deterministic
*rendering* task, this trades consistency for nothing we need.

---

## 6. "How we want to translate JSON → OpenUI" (target principles)
1. **Deterministic by default, LLM for the long tail.** Our deliverable `content`
   has a *known, stable schema*. Known fields (`sector`, `geography`,
   `span_of_control`, `strategy`, `restructuring_impact`, `insights`, `slide_nums`,
   `org_tree`, `pros/cons/risks`, …) should map to **one fixed component each**,
   ideally produced by code, with the LLM handling only free-form/unknown content.
2. **One field → one component, always.** Eliminate "render it three ways."
3. **Lossless.** Preserve every fact, row, citation marker; never summarize/placeholder.
4. **Validated.** Generated Lang must *parse* and have all references reachable before
   it is persisted.
5. **Lean prompt.** Only show the model components it is allowed to use.

---

## 7. Recommended enhancements (prioritized)

### P0 — Consistency
1. **Resolve prompt contradictions** (fast win): pick ONE rendering for `slide_nums`
   (recommend `TagBlock`), remove it from the facts-table rule (`system.txt:286` /
   `prompt-options.mjs:18`), and make the tag rule imperative ("ALWAYS … NEVER …").
   Do the same for `strategy`/`restructuring_impact` (always facts `Table`, never
   `TextCallout`) and `insights` (always `Card`+`MarkDownRenderer`, never `Accordion`).
2. **Add a field→component mapping block** to `prompt-options.additionalRules`: an
   explicit table the model can follow deterministically for the standard section schema.
3. **Add 1–2 "golden" canonical examples** that render the full standard section schema
   exactly as prescribed (so the model has a concrete consistent target).
4. **Lower variance**: prefer a non-reasoning model at temp `0.2` for translation, or
   keep `gpt-5.5` but accept that temp is pinned; evaluate which is more *consistent*.

### P1 — Determinism (bigger, highest payoff)
5. **Schema-driven deterministic pre-render.** Build a Python renderer that emits Lang
   for known fields directly (no LLM), guaranteeing identical components across sections
   and zero data loss. Reserve the LLM for unknown/free-form blocks only. This makes
   Problem 1 and most of Problem 2 disappear by construction and cuts cost/latency.
   *(Validate with the existing `temp1.md` → expected-Lang as a golden test.)*

### P1 — Validation / repair
6. **Real parse + repair loop.** Validate generated Lang with `@openuidev/lang-core`
   (a small Node validator/sidecar, or reuse the parser) instead of the `root =` regex;
   on parser errors, **re-prompt once with the structured errors** (the `onError`
   contract the lib is designed for). Catch truncation and undefined-reference drops
   *before* persisting.
7. **Detect truncation** explicitly (finish_reason / token cap) and either raise
   `OPENUI_TRANSLATE_MAX_TOKENS` for large sections or chunk them.

### P2 — Prompt hygiene / cost
8. **Prune the library used for the prompt** so disabled components (Forms/Inputs/Modal/
   bindings/Query) aren't documented at all — smaller prompt, no contradiction surface.
   (Either register a render-only library variant for spec generation, or post-process
   `system.txt` to strip those sections, asserting on wording like the existing
   plausible-data strip.)
9. **Pre-strip empty fields from the section payload** server-side (extend
   `_strip_externally_rendered_fields` to drop `null`/`""`/`[]`/`{}`), reducing input
   tokens and removing placeholder temptation.
10. **Pick one canonical text stack** (`TextContent`/`MarkDownRenderer`) and either tell
    the model to prefer it or drop the overlapping `Heading`/`Text`/`Bullets`.

---

## 8. Open questions to confirm next
- Is the **frontend `onError`** wired to anything today, or do render failures only
  fall back to raw JSON? (Confirms value of a server-side repair loop.)
- Do we have a **golden/eval set** for translation (input JSON → expected Lang)? If
  not, building one from `temp1.md` should precede any prompt change.
- Which model is actually bound to `service.openui_translate` in
  `config/llm_models_inventory.yaml` in each environment?

---

## 9. Follow-up Q&A

### 9.1 Do we actually want reactive state off?
"Reactive state" is **two features** with different verdicts:

- **(a) Tool-backed** — `Query`/`Mutation`/`@Run`, server bindings (hits a backend at
  render time). **Keep OFF.** Deliverables are pretranslated + cached on `openuiLang`
  with no render-time tool provider, and the **standalone HTML export has no backend**,
  so these would break offline. Also conflicts with the lossless/deterministic/"JSON is
  source of truth" guarantee.
- **(b) Client-only** — `$variables` + ternary + `@Filter`/`@Sort`/`@Each`/`@Count` over
  *already-materialized* data, plus `Tabs`/`Accordion`/`Modal` (no `$var` needed). Needs
  **no backend**, so it survives in the persisted render *and* the HTML export. Would
  unlock search/sort/filter on large tables and expand/collapse detail. We are **already
  partly here**: `Tabs`/`Accordion` are in use and exports are already interactive
  (tooltips, pagination, tree pan/zoom).

**Recommendation:** (a) no; (b) *not yet, but it's a deliberate product option, not a
technical block.* Client-only interactivity adds non-determinism to model output, which
worsens **Problem 1 (cross-section inconsistency)**. Fix consistency + add real output
validation first, then selectively enable `$var`/`@Filter`/`@Sort` for specific
high-value cases (large tables) behind strict canonical rules.

### 9.2 How is layout controlled — components or prompt?
**Both, across three layers:**

| Layer | Controls | Lives in |
|---|---|---|
| **Components** | The layout *vocabulary* + appearance | `library.jsx` + `@openuidev/react-ui` (React/CSS) |
| **Prompt + emitted program** | The *composition* — container choice, order, nesting, prop values | `system.txt` rules/examples + model output |
| **Frontend wrapper** | The *outer* shell — summary, per-section **tab bar**, citations | `DeliverableOpenUIView.jsx` (React, not Lang) |

- Components define the system: `Stack(children, direction, gap, align, justify, wrap)`
  is the flex primitive (`direction: row|column`, `gap: none…2xl`); grids = `Stack`
  `direction:"row"` + `wrap:true`; `Card` accepts the same flex params. Actual
  appearance (spacing scale, elevation, dark theme, tree pan/zoom) is baked into the
  React components and is **not** expressible in Lang.
- The prompt/program controls *which* layout is chosen and the prop values (positional,
  e.g. `Stack([...], "column", "l")` — never `direction:"row"`).
- The section **tab bar is deterministic React, outside Lang** — hence the rule
  "don't create tabs for sibling sections."

**Upshot:** layout-*consistency* issues are a **prompt-layer** problem (model
under-constrained on which layout to pick), fixable via prescriptive rules + golden
examples (§7 P0) without touching components.

## 10. Sources
- OpenUI — Introduction: https://www.openui.com/docs/openui-lang
- OpenUI Lang — Overview: https://www.openui.com/docs/openui-lang/overview
- OpenUI Lang — Specification v0.5 (latest): https://www.openui.com/docs/openui-lang/specification-v05
- OpenUI Lang — How it works / Architecture: https://www.openui.com/docs/openui-lang/how-it-works
- OpenUI Lang — Benchmarks (token efficiency vs JSON): https://www.openui.com/docs/openui-lang/benchmarks
- OpenUI — Quick Start: https://www.openui.com/docs/openui-lang/quickstart
- GitHub — thesysdev/openui: https://github.com/thesysdev/openui
- Internal: `system.txt`, `prompt-options.mjs`, `openui_prompt.py`,
  `generate-openui-prompt.mjs`, `openui_translate_service.py`; example `temp1.md`/`temp2.md`.
