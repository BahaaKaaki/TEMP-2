# `agent_studio` SDK Reference

Python SDK available inside every Code Executor sandbox.

```python
from agent_studio import output, uploads, llm, knowledge_base
```

---

## Mental model

Your script runs once per execution.  To produce a deliverable, call **one**
of the `output.*` methods.  The **last** call wins -- if you call
`output.data()` then `output.chart()`, the chart replaces the data.

There are three families of emitters:

| Family                     | Examples                                                    | Waits for user? |
|----------------------------|-------------------------------------------------------------|-----------------|
| Data & visualization       | `output.data`, `output.table`, `output.chart`               | No              |
| File deliverables          | `output.file`, `output.files`                               | No              |
| Interactive / pause        | `output.ask`, `output.selection`, `output.list`, `output.form` | Yes             |

The four interactive methods all pause the script **mid-execution** and
**return** the user's answer.  Internally they share the same indexed
multi-pause replay mechanism: after the user answers, the script
re-runs from the top, but previously-answered pauses return their
cached answers instantly, and a variable checkpoint skips re-executing
expensive work between pauses.

**Always capture the return value.**  `selection`, `list`, and `form`
are not terminal "show a widget and stop" helpers -- they give you the
user's choice back so you can act on it:

```python
kept = output.selection(prompt="Regions?",
                        options=[...], allow_multiple=True)
df = df[df["region"].isin(kept)]        # use `kept` downstream
```

---

## 1. Data & visualization

### `output.data(data, *, title="Result", visualization=None)`

The **canonical emission method**.  Every other visualization helper
below is a thin wrapper around this.

- `data` -- any JSON-serialisable value.  This is the clean payload that
  downstream nodes, the agent, and the AI receive.  Keep it focused and
  semantic; don't mix in rendering hints.
- `title` -- human-readable title shown on the output card.
- `visualization` -- optional list of **DSL component specs** that tell
  the frontend *how* to render the payload.  See the DSL section below
  for every primitive.  Can be a single spec dict (wrapped to a list
  internally) or a list of specs rendered top-to-bottom.

```python
# Plain data (frontend uses a generic key-value card)
output.data({"revenue": 1_000_000, "growth": 0.23})

# Composed dashboard (header + metric row + chart)
output.data(
    {"revenue": 1_000_000, "growth": 0.23},
    title="Q1 Snapshot",
    visualization=[
        {"type": "header", "title": "Q1 Snapshot",
         "badges": {"status": "final"}},
        {"type": "grid", "columns": 3, "children": [
            {"type": "metric", "label": "Revenue", "value": "$1.0M",
             "change": "+23%", "trend": "up"},
            {"type": "metric", "label": "MRR", "value": "$83k"},
            {"type": "metric", "label": "Churn", "value": "3%"},
        ]},
        {"type": "chart", "chart_type": "bar",
         "chart_data": [{"q": "Q1", "rev": 1_000_000}]},
    ],
)
```

**Design rule:** `data` is for the machine, `visualization` is for the
human.  Downstream nodes never see `visualization`.

### `output.table(data, *, title="Table", columns=None)`

Shortcut for a single `{type: "table"}` spec.  Accepts either shape:

- dict-of-lists: `{"Name": ["A", "B"], "Score": [1, 2]}`
- list-of-dicts: `[{"Name": "A", "Score": 1}, ...]`

```python
output.table(
    [{"name": "Alice", "score": 92}, {"name": "Bob", "score": 87}],
    title="Top performers",
)
```

### `output.chart(*, type="bar", data, title="Chart", x_label, y_label)`

Shortcut for a single `{type: "chart"}` spec.  Supported chart types:
`bar`, `line`, `area`, `pie`.  (For anything more exotic — scatter,
radar, stacked/grouped bars, donuts, dual-axis, etc. — use a
`{"type": "render", "script": "..."}` spec instead; see §5.)

```python
output.chart(
    type="line",
    data=[{"day": d, "visits": v}
          for d, v in zip(["Mon", "Tue", "Wed"], [100, 150, 140])],
    x_label="day", y_label="visits",
    title="Weekly traffic",
)
```

### `output.flat_list(items, *, title="Items", ordered=False)`

Static bullet/numbered list (non-interactive).  For an interactive
picker/filter use `output.list()` below.

```python
output.flat_list(
    ["Increase pricing", "Hire two engineers", "Launch in EU"],
    title="Q2 priorities",
)
```

### `output.document(*, title, metadata, sections, graph)`

Structured document composed of header + accordion + optional flowchart.
For custom layouts reach for `output.data()` with DSL primitives.

Each section dict has `title` and a `type`:
- `type="text"`, `content=str`
- `type="table"`, `columns=[...]`, `rows=[...]`
- `type="list"`, `items=[...]`

```python
output.document(
    title="Q1 Report",
    metadata={"version": "1.0", "status": "final"},
    sections=[
        {"title": "Summary", "type": "text", "content": "Revenue up 23%..."},
        {"title": "By region", "type": "table",
         "columns": ["region", "revenue"],
         "rows": [{"region": "EU", "revenue": 400_000},
                  {"region": "US", "revenue": 600_000}]},
    ],
    graph={
        "nodes": [{"id": "a", "label": "Plan"},
                  {"id": "b", "label": "Execute"}],
        "edges": [{"source": "a", "target": "b"}],
    },
)
```

---

## 2. The Visualization DSL

The `visualization` argument on `output.data()` accepts a list of
**component specs**.  Each spec is a dict with a `type` key and
type-specific fields.  Specs compose -- containers (`accordion`, `tabs`,
`grid`, `card`) hold nested child specs.

All 13 primitives + the `render` escape hatch:

### Leaf primitives

#### `header`
Page or section header with title, subtitle, and metadata badges.
```python
{"type": "header", "title": "Q1 Report", "subtitle": "Finance",
 "badges": {"version": "1.0", "status": "final"}}
```

#### `text`
Paragraph of plain text or lightweight markdown.  When
`format="markdown"` a subset is supported: `**bold**`, `*italic*`,
`` `code` ``, newlines.
```python
{"type": "text", "value": "Summary of **Q1** results.", "format": "markdown"}
```

#### `table`
Sortable table with sticky header.  Click a column header to sort.
```python
{"type": "table", "title": "Sales",
 "columns": ["region", "revenue"],
 "rows": [{"region": "EU", "revenue": 1200},
          {"region": "US", "revenue": 3400}]}
```

#### `list`
Static bullet (`ordered=False`) or numbered (`ordered=True`) list.
Items can be plain strings or `{"label": ...}` dicts.
```python
{"type": "list", "title": "Key findings",
 "items": ["Revenue up 12%", "Costs down 3%"],
 "ordered": False}
```

#### `chart`
Chart powered by Recharts.  Supported `chart_type` values: `bar`,
`line`, `area`, `pie`.  `chart_data` is a list of data points;
`x_label` / `y_label` name the keys inside each point.  For chart
styles outside this list (scatter, radar, stacked/grouped bar, donut,
dual-axis, …) emit a `{"type": "render", "script": ...}` spec instead.
```python
{"type": "chart", "title": "Revenue by quarter",
 "chart_type": "bar",
 "chart_data": [{"quarter": "Q1", "revenue": 100},
                {"quarter": "Q2", "revenue": 150}],
 "x_label": "quarter", "y_label": "revenue"}
```

#### `flowchart`
Interactive process flowchart.  Nodes need `id` and `label`; edges need
`source` and `target` referencing node ids.  Optional `swimlanes` groups
nodes into horizontal bands.
```python
{"type": "flowchart", "title": "Approval flow",
 "nodes": [{"id": "a", "label": "Submit"},
           {"id": "b", "label": "Review"},
           {"id": "c", "label": "Approve"}],
 "edges": [{"source": "a", "target": "b"},
           {"source": "b", "target": "c"}]}
```

#### `metric`
Single big-number metric with optional trend indicator (`trend` is
`up` | `down` | `neutral`).
```python
{"type": "metric", "label": "Revenue", "value": "$1.2M",
 "change": "+12%", "trend": "up"}
```

#### `divider`
Horizontal rule for visual separation.
```python
{"type": "divider"}
```

#### `code`
Syntax-highlighted code block.
```python
{"type": "code", "title": "Query", "language": "sql",
 "value": "SELECT * FROM users WHERE id = 1"}
```

### Container primitives

Containers hold nested specs.  Nesting is unbounded -- a `card` can hold
an `accordion` which holds a `tabs` etc.

#### `accordion`
Collapsible sections.  Each section's `content` is a list of specs.
```python
{"type": "accordion", "sections": [
    {"title": "Details", "content": [
        {"type": "text", "value": "..."},
        {"type": "table", "columns": [...], "rows": [...]},
    ]},
    {"title": "Raw data", "content": [
        {"type": "code", "language": "json", "value": "..."},
    ]},
]}
```

#### `tabs`
Tab strip; each tab's `content` is a list of specs.
```python
{"type": "tabs", "tabs": [
    {"label": "Summary", "content": [
        {"type": "metric", "label": "Revenue", "value": "$1M"},
    ]},
    {"label": "Details", "content": [
        {"type": "table", "columns": [...], "rows": [...]},
    ]},
]}
```

#### `grid`
Equal-width grid.  `columns` is the column count; each entry in
`children` is a spec (or list of specs) placed in one cell.
```python
{"type": "grid", "columns": 3, "children": [
    {"type": "metric", "label": "Revenue", "value": "$1M"},
    {"type": "metric", "label": "Users", "value": "12k"},
    {"type": "metric", "label": "Churn", "value": "3%"},
]}
```

#### `card`
Bordered card wrapping nested specs.  Use to visually group related
primitives.
```python
{"type": "card", "title": "Summary", "children": [
    {"type": "text", "value": "Revenue is up."},
    {"type": "chart", "chart_type": "line", "chart_data": [...]},
]}
```

### Custom JS (`render` spec)

`render` is the escape hatch that lets you build **any** UI directly in
JavaScript.  It has two distinct operating modes.

#### Intent → mode cheat-sheet

| User's intent / phrasing                                                          | Mode                                          |
| --------------------------------------------------------------------------------- | --------------------------------------------- |
| No custom-UI cue — just "make a dashboard", "show the results", etc.              | **Primitive-first** (default)                 |
| Needs something outside the 13 primitives (stacked bars, donut, brush, drill-down) | **Primitive + one `render` spec** for that pane |
| "Write in JS / JavaScript", "all in JS", "use `render`", "use React.createElement", "use Recharts directly", "no native primitives", "don't use the DSL", "manually render", "hand-rolled UI", "custom component" | **All-JS mode** — one top-level `render`      |

**All-JS mode** (third row) means: emit exactly **one** `{"type":
"render", "script": "..."}` whose `script` builds the entire UI
(headers, KPI tiles, dividers, tables, tabs, accordions, charts --
everything) via `React.createElement`.  Do **not** also ship native
`metric` / `header` / `chart` / `table` specs alongside -- that
defeats the point of the request.  The `payload` passed to
`output.data(...)` stays clean and semantic so downstream nodes still
work.

#### Runtime contract

`script` is evaluated as a JS function body with three arguments:

- `data` -- the full payload passed to `output.data`.
- `React` -- the React module.  Use `React.useState`, `React.useMemo`
  etc. for state.  To use hooks, define a component function inside
  the script and `return React.createElement(MyComponent)`.
- `Recharts` -- the Recharts library.  Destructure what you need:
  `const { BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, Cell, LineChart, Line, PieChart, Pie,
  AreaChart, Area, ReferenceLine, LabelList } = Recharts;`

Hard rules:

- **Must `return` a React element.**
- **JSX is NOT available** -- always use
  `React.createElement(tag, props, ...children)`.
- Tailwind classes are available via `className`.
- Errors are caught and displayed inline so a bad spec won't break the
  rest of the output.

#### Example — small pane (primitive + one `render`)

```python
{"type": "render", "script": """
    return React.createElement(
        'div',
        {className: 'p-4 bg-blue-50 rounded-lg'},
        React.createElement('h3', {className: 'font-bold'},
            'Revenue: $' + data.revenue),
        React.createElement('p', null,
            'Growth: ' + (data.growth * 100).toFixed(1) + '%')
    );
"""}
```

#### Example — all-JS dashboard (fire when the user asks for JS)

One top-level `render` that builds header + KPI tiles + a stacked bar
chart + a table, all in JavaScript.  No other primitives in the
`visualization` list.

```python
payload = {
    "title": "Revenue Dashboard",
    "subtitle": "2017 – 2019",
    "kpis": [
        {"label": "Total revenue", "value": "$4.2M", "trend": "up",   "change": "+12%"},
        {"label": "Latest year",   "value": "$1.6M", "trend": "up",   "change": "+8%"},
        {"label": "Regions",       "value": "4",     "trend": "flat", "change": ""},
    ],
    "stacked": [
        {"Year": "2017", "AMER": 800000, "EMEA": 500000, "APAC": 200000},
        {"Year": "2018", "AMER": 900000, "EMEA": 600000, "APAC": 300000},
        {"Year": "2019", "AMER": 950000, "EMEA": 650000, "APAC": 350000},
    ],
    "regions": ["AMER", "EMEA", "APAC"],
    "colors":  ["#10B981", "#3B82F6", "#F59E0B"],
    "rows": [
        {"Region": "AMER", "Country": "US",  "Revenue": 1_800_000},
        {"Region": "EMEA", "Country": "DE",  "Revenue":   900_000},
        {"Region": "APAC", "Country": "JP",  "Revenue":   550_000},
    ],
}

output.data(
    payload,
    title="Revenue Dashboard",
    visualization=[{"type": "render", "script": r"""
        const { BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
                ResponsiveContainer } = Recharts;

        const fmt = (v) => Math.abs(v) >= 1e6
            ? '$' + (v/1e6).toFixed(2) + 'M'
            : Math.abs(v) >= 1e3 ? '$' + (v/1e3).toFixed(1) + 'K'
            : '$' + v.toFixed(0);

        const Header = React.createElement('div', {className: 'mb-4'},
            React.createElement('h1',
                {className: 'text-2xl font-bold text-gray-900'}, data.title),
            React.createElement('p',
                {className: 'text-sm text-gray-500'}, data.subtitle),
        );

        const Kpis = React.createElement('div',
            {className: 'grid grid-cols-3 gap-3 mb-4'},
            ...data.kpis.map((k, i) => React.createElement('div',
                {key: i, className: 'bg-white border rounded-lg p-3'},
                React.createElement('div',
                    {className: 'text-xs uppercase text-gray-500'}, k.label),
                React.createElement('div',
                    {className: 'text-xl font-bold text-gray-900'}, k.value),
                k.change && React.createElement('div',
                    {className: k.trend === 'up' ? 'text-green-600 text-xs'
                                : k.trend === 'down' ? 'text-red-600 text-xs'
                                : 'text-gray-400 text-xs'}, k.change),
            )),
        );

        const Chart = React.createElement('div',
            {className: 'bg-white border rounded-lg p-3 mb-4'},
            React.createElement('h3',
                {className: 'text-sm font-semibold text-gray-700 mb-2'},
                'Revenue by year & region'),
            React.createElement(ResponsiveContainer, {width: '100%', height: 300},
                React.createElement(BarChart, {data: data.stacked},
                    React.createElement(XAxis, {dataKey: 'Year'}),
                    React.createElement(YAxis, {tickFormatter: fmt}),
                    React.createElement(Tooltip, {formatter: fmt}),
                    React.createElement(Legend, null),
                    ...data.regions.map((r, i) =>
                        React.createElement(Bar, {
                            key: r, dataKey: r, stackId: 'a',
                            fill: data.colors[i % data.colors.length],
                        })
                    ),
                )
            ),
        );

        const Table = React.createElement('div',
            {className: 'bg-white border rounded-lg overflow-hidden'},
            React.createElement('table',
                {className: 'w-full text-sm'},
                React.createElement('thead', {className: 'bg-gray-50'},
                    React.createElement('tr', null,
                        ...['Region', 'Country', 'Revenue'].map(h =>
                            React.createElement('th',
                                {key: h, className: 'text-left px-3 py-2 font-semibold text-gray-700'},
                                h)),
                    )),
                React.createElement('tbody', null,
                    ...data.rows.map((row, i) =>
                        React.createElement('tr',
                            {key: i, className: i % 2 ? 'bg-gray-50' : ''},
                            React.createElement('td', {className: 'px-3 py-2'}, row.Region),
                            React.createElement('td', {className: 'px-3 py-2'}, row.Country),
                            React.createElement('td', {className: 'px-3 py-2 text-right'}, fmt(row.Revenue)),
                        )
                    )),
            ),
        );

        return React.createElement('div',
            {className: 'w-full'}, Header, Kpis, Chart, Table);
    """}],
)
```

Notes for all-JS mode:

- Keep the `payload` dict clean and semantic (KPIs as numbers with
  labels, not pre-formatted HTML).  Format inside the JS.
- One top-level `render` is the target.  Do not also ship `metric` /
  `chart` / `header` / `table` specs in the same `visualization` list
  -- mixing them contradicts the "write in JS" instruction.
- If you need multiple scrollable sections, build them as `div`s
  inside the single `render` (see the three composed chunks above).

### Optional: TypedDict autocomplete

If you want IDE autocomplete for specs, import the typed aliases:

```python
from agent_studio import output, ChartSpec, GridSpec, MetricSpec

metric: MetricSpec = {
    "type": "metric", "label": "Revenue", "value": "$1.2M",
    "change": "+12%", "trend": "up",
}
output.data(data, visualization=[metric])
```

Full list: `HeaderSpec`, `TextSpec`, `TableSpec`, `ListSpec`,
`ChartSpec`, `FlowchartSpec`, `MetricSpec`, `DividerSpec`, `CodeSpec`,
`AccordionSpec`, `TabsSpec`, `GridSpec`, `CardSpec`, `RenderSpec`,
`PrimitiveSpec`, `Visualization`.  Plain dicts also work fine.

---

## 3. File deliverables

### `output.file(path, *, display_name=None)`

Register a single output file.  The path must be under `/outputs/`; the
host extracts the file and makes it downloadable.

```python
with open("/outputs/report.xlsx", "wb") as f:
    f.write(workbook_bytes)
output.file("/outputs/report.xlsx", display_name="Q1 Report.xlsx")
```

### `output.files(*paths, title="Output Files")`

Register multiple files in one deliverable.  Each entry is a path string
or a `(path, display_name)` tuple.

```python
output.files(
    "/outputs/summary.pdf",
    ("/outputs/raw.csv", "Raw data (CSV)"),
    title="Deliverables",
)
```

---

## 4. Interactive outputs (pause the script & return the user's answer)

These pause the script **mid-execution** (via `sys.exit(42)` under the
hood), wait for the user to answer in the UI, then resume and **return
the answer as the call's value**.  Always assign the result to a
variable.

**Important:** read the intent-mapping table below carefully -- picking
the wrong primitive (or forgetting `allow_multiple=True` when the user
wants multi-select) is the single most common code-generation mistake.

### Intent → primitive cheat-sheet

| User's intent / phrasing                                                        | Use this                                      | Returns             |
| ------------------------------------------------------------------------------- | --------------------------------------------- | ------------------- |
| "Pick one of these options" (radio)                                             | `output.selection(..., allow_multiple=False)` | `str` (the value)   |
| "Pick **multiple**, **several**, **a few**, **any of**, **checkboxes**"         | `output.selection(..., allow_multiple=True)`  | `list[str]`         |
| "Filter / trim down this list I just computed"                                  | `output.list(items, mode="eliminate")`        | `list` (kept items) |
| "Pick one from this dynamic list"                                               | `output.list(items, mode="pick_one")`         | single item         |
| "Pick many from this dynamic list"                                              | `output.list(items, mode="pick_many")`        | `list` (chosen)     |
| Several answers of different types on one screen (incl. a boolean toggle)       | `output.form(fields=[...])`                   | `dict[name → value]`|
| Yes / no                                                                        | `output.ask(type="confirm")`                  | `bool`              |
| Single text / number / file                                                     | `output.ask(type="text\|number\|file")`       | `str` / `int` / `path` |
| Single pick from a short, fixed list (one-shot)                                 | `output.ask(type="selection", options=[...])` | `str`               |

Rule of thumb: any phrase like "multiple", "more than one", "several",
"a few of", "checkboxes", "all that apply" → **`allow_multiple=True`**
on `selection()` or **`mode="pick_many"`** on `list()`.  Never infer
single-select in that case.

---

### `output.selection(*, prompt, options, allow_multiple=False)`

Fixed, pre-defined options.  Renders as **radio buttons** by default;
flip `allow_multiple=True` to render as **checkboxes** and return a
list of the chosen values.

`options` accepts either a list of `{"label": str, "value": Any}` dicts
(recommended -- label is shown to the user, value is what your code
receives) or a plain list of strings (label == value).

```python
# Single-select (radio)
plan = output.selection(
    prompt="Pick a plan",
    options=[
        {"label": "Starter", "value": "s"},
        {"label": "Pro",     "value": "p"},
    ],
)
# plan == "p"   (scalar)

# Multi-select (checkboxes) -- use this whenever the user asks to pick
# multiple, several, a few, "any of", or "all that apply".
regions = output.selection(
    prompt="Which regions should the dashboard include?",
    options=[
        {"label": "North America", "value": "na"},
        {"label": "Europe",        "value": "eu"},
        {"label": "Asia",          "value": "asia"},
        {"label": "LATAM",         "value": "latam"},
    ],
    allow_multiple=True,   # <- turns the UI into checkboxes
)
# regions == ["eu", "asia"]   (always a list when allow_multiple=True,
#                              even if the user picks only one)
```

### `output.list(items, *, title="Items", mode="eliminate")`

Interactive list for filtering / picking from values your **code just
computed** (e.g. the unique countries in an uploaded CSV, candidates
from a search, etc.).  Use this instead of `selection()` when the
options aren't known until runtime.

Modes:

- `"eliminate"` (default): all items start checked; user unchecks the
  ones to drop.  Returns the items the user **kept**.
- `"pick_one"`: user picks a single item.  Returns that single item.
- `"pick_many"`: user picks one or more items (checkboxes).  Returns a
  list of the picked items.

```python
countries = df["Country"].unique().tolist()

# "Let the user uncheck countries they want excluded"
keep = output.list(countries, title="Countries to include",
                   mode="eliminate")
df = df[df["Country"].isin(keep)]

# "Let the user pick several from a dynamic list" (checkboxes)
chosen = output.list(candidates, title="Shortlist", mode="pick_many")
```

### `output.form(*, prompt, fields)`

Multi-field form -- use when you need several answers on one screen,
or when any of the answers is a **boolean toggle** (`type="checkbox"`
gives you a single true/false per field, separate from the
multi-select pattern above).

Field shape: `{"name": str, "type": "text|number|select|checkbox",
"label": str, "default": Any, "options": [...], "required": bool}`.

Returns a dict mapping each field's `name` to its value.

```python
cfg = output.form(
    prompt="Dashboard configuration",
    fields=[
        {"name": "title",       "type": "text",
         "label": "Dashboard title", "required": True},
        {"name": "year",        "type": "select",
         "label": "Focus year", "options": ["2017","2018","2019"],
         "default": "2019"},
        # Boolean toggle — rendered as a single checkbox:
        {"name": "include_yoy", "type": "checkbox",
         "label": "Include YoY growth chart", "default": True},
        {"name": "include_pie", "type": "checkbox",
         "label": "Include region share pie", "default": True},
        {"name": "top_n",       "type": "number",
         "label": "How many top countries?", "default": 10},
    ],
)
# cfg == {"title": "...", "year": "2019", "include_yoy": True,
#         "include_pie": False, "top_n": 10}
if cfg["include_yoy"]:
    ...
```

> NOTE: a `"checkbox"` field in `form()` is a **single boolean toggle**.
> If you need the user to tick multiple items from a list, do NOT add
> N checkbox fields in a form -- use `output.selection(allow_multiple=True)`
> or `output.list(mode="pick_many")` instead.

---

## 5. Midway input: `output.ask()` (single-question)

```python
result = output.ask(
    prompt,
    *,
    options=None,
    type="text",      # "text" | "number" | "selection" | "confirm" | "file"
    default=None,
    accept=None,      # file accept filter, e.g. ".xlsx,.csv"
    multiple=False,   # type="file" → list of paths;
                      # type="selection" → checkboxes, returns list
    checkpoint=True,  # save variables before pausing (default on)
)
```

Lightweight single-question prompt.  For multi-option selection, a
filterable list, or a multi-field form reach for
`output.selection`/`list`/`form` in the previous section -- they share
the exact same pause-and-resume machinery described below.

**How midway pauses work (same for `ask`, `selection`, `list`, `form`):**

1. The SDK saves a **checkpoint** of user variables (via `cloudpickle`).
2. The sandbox exits with code 42; the host records the pause.
3. When the user answers, the script re-runs from the top.
4. The checkpoint is restored into globals so no code before the pause
   runs again.
5. The pause call at the same index returns the cached answer instantly.

You can call as many pauses as you want in a single script.  Each call
has its own pause index and cache.

```python
name = output.ask("What is your name?")
xlsx_path = output.ask("Upload your sales export",
                        type="file", accept=".xlsx")
df = pandas.read_excel(xlsx_path)

if output.ask("Include forecasts?", type="confirm"):
    df = add_forecasts(df)

# Multiple choice, single pick:
mode = output.ask("Analysis mode?", type="selection",
                  options=["monthly", "quarterly", "yearly"])

# Multiple choice, multi-pick (equivalent to output.selection(..., allow_multiple=True)):
cols = output.ask("Which columns to include?", type="selection",
                  options=df.columns.tolist(), multiple=True)

output.data({"rows": len(df), "cols": cols})
```

**When to disable `checkpoint=False`:** only if you have unpicklable
state (e.g. open file handles, live DB connections).  Everything else
should keep the default -- it's essentially free and avoids re-running
expensive work.

---

## 6. `uploads` -- access user-uploaded files

```python
uploads.list()        # -> list[str]  paths in /workspace/uploads/
uploads.get(name)     # -> str        full path (raises FileNotFoundError)
uploads.exists(name)  # -> bool
```

Files supplied by the user before the run (or via `output.ask(type="file")`)
land in `/workspace/uploads/`.

---

## 7. `llm` -- call LLMs from inside the sandbox

```python
result = llm.complete(
    prompt,
    *,
    model="bedrock.anthropic.claude-haiku-4-5",
    system_prompt=None,
    output_schema=None,   # JSON Schema dict for structured output
    temperature=None,
    max_tokens=4096,
    timeout=120,
)
```

Returns the assistant message as a string.  When `output_schema` is
provided the model is forced to emit valid JSON conforming to the schema;
the string returned is the JSON, ready for `json.loads`.

---

## 8. `knowledge_base` -- query structured data from a Knowledge Base

When the Code Executor node is configured with one or more
**knowledgeBaseIds**, every structured table attached to those KBs is
available to your script as a pandas DataFrame.  Each run gets an
opaque, per-run **session id** (no cryptographic material) that the
host uses to look up the authenticated user and the KB allowlist.  The
session is scoped to this single run -- it is revoked the moment the
run finishes, at which point any leaked copy is useless.

```python
from agent_studio import knowledge_base

# 1. Discover what's available (one HTTP call on first use, then cached).
for t in knowledge_base.list_tables():
    print(t["kb_name"], t["table"], [c["name"] for c in t["columns"]])

# 2. Read a whole table (DataFrame when pandas is installed).
customers = knowledge_base.read_table("customers", limit=500)

# 3. Read with a WHERE clause.
paid = knowledge_base.read_table(
    "orders",
    where="status = 'paid' AND created_at > '2025-01-01'",
    limit=1000,
)

# 4. Run an arbitrary SELECT (requires kb_id).
top = knowledge_base.query(
    "SELECT region, COUNT(*) AS n FROM customers GROUP BY region ORDER BY n DESC",
    kb_id="<kb-uuid>",
    max_rows=50,
)
```

### Method reference

- `knowledge_base.list_tables(kb_id=None, *, refresh=False)` -- returns a
  list of dicts describing every visible table:
  `{kb_id, kb_name, schema_name, table, display_name, description,
    row_count, columns: [{name, type, description, nullable}]}`.
  Fetched from the host on first call and cached in process memory; pass
  `refresh=True` to re-query.

- `knowledge_base.describe(table, kb_id=None)` -- convenience accessor
  that returns the dict for a single table.  Raises if `table` is
  ambiguous across multiple KBs without `kb_id`.

- `knowledge_base.read_table(table, *, limit=100, where=None, kb_id=None)`
  -- returns a pandas DataFrame (or list of dicts) of rows.  The
  `kb_id` argument is only required when the same table name exists in
  multiple configured KBs.

- `knowledge_base.query(sql, *, kb_id, max_rows=1000)` -- runs one
  SELECT against the named KB's schema.  The SQL is validated
  server-side -- no semicolons, comments, or DDL/DML.  Returns a
  DataFrame or list of dicts.

- `knowledge_base.query_df(...)` -- alias for `query()`.

### Guarantees

- **Read-only.**  The server rejects anything that isn't a single
  SELECT statement.
- **Row-level security.**  Every request runs under the authenticated
  user's RLS context; you only see KBs you created or that were shared
  to you.
- **Opaque session, not a token.**  The sandbox never holds a signed
  token or any crypto material.  The session id is a random lookup key
  that's revoked the moment the run ends.
- **No files.**  Nothing KB-related is written to `/workspace`.  The
  session id is passed via an env var that the SDK `pop`s and scrubs
  at import time -- `os.environ` reveals nothing afterwards.
- **Hard caps.**  `max_rows` is clamped at 10 000; query timeout is 30s.

### No KBs configured?

If the node's `knowledgeBaseIds` is empty, every method raises
`agent_studio.KnowledgeBaseError` with a message telling the user to
configure a KB on the node.

---

## 9. Runtime environment

### Injected variables

- `inputs` -- dict of resolved input values from upstream nodes.
- Files from `uploads.list()` / `uploads.get(name)` in
  `/workspace/uploads/`.

### Allowed imports

`json`, `csv`, `math`, `statistics`, `datetime`, `collections`,
`itertools`, `re`, `typing`, `dataclasses`, `enum`, `functools`,
`operator`, `string`, `textwrap`, `uuid`, `hashlib`, `base64`, `copy`,
`decimal`, `fractions`, `random`, `time`, `calendar`, `pprint`, `io`,
`struct`, `html`, `xml`, `concurrent`, `pandas`, `numpy`, `matplotlib`,
`scipy`, `sklearn`, `openpyxl`, `xlsxwriter`, `pptx`, `fitz` (PyMuPDF),
`cloudpickle`, `agent_studio`.

### Blocked

`os`, `sys`, `subprocess`, `shutil`, `socket`, `http`, `urllib`,
`requests`, `pathlib`, `importlib`, `ctypes`, `pickle` (use
`cloudpickle`), `threading`, `asyncio`, `eval`, `exec`, `open`,
`__import__`.

### File system contract

- `/workspace/uploads/` -- read-only, contains user-supplied files.
- `/outputs/` -- writable, anything you put here can be registered via
  `output.file()` / `output.files()`.

---

## Recipes

### Minimal

```python
output.data({"greeting": "hello, world"})
```

### Table from pandas

```python
import pandas as pd
df = pd.read_excel(uploads.get("sales.xlsx"))
output.table(df.to_dict(orient="records"), title="Sales")
```

### Dashboard

```python
output.data(
    summary,
    title="Sales Dashboard",
    visualization=[
        {"type": "header", "title": "Sales Dashboard",
         "subtitle": f"Through {summary['end_date']}"},
        {"type": "grid", "columns": 4, "children": [
            {"type": "metric", "label": "Revenue",
             "value": f"${summary['revenue']:,.0f}",
             "change": f"{summary['growth']:+.0%}",
             "trend": "up" if summary["growth"] > 0 else "down"},
            {"type": "metric", "label": "Orders",
             "value": summary["orders"]},
            {"type": "metric", "label": "AOV",
             "value": f"${summary['aov']:.2f}"},
            {"type": "metric", "label": "Refund rate",
             "value": f"{summary['refund_rate']:.1%}"},
        ]},
        {"type": "tabs", "tabs": [
            {"label": "By region", "content": [
                {"type": "chart", "chart_type": "bar",
                 "chart_data": summary["by_region"],
                 "x_label": "region", "y_label": "revenue"},
            ]},
            {"label": "By product", "content": [
                {"type": "table",
                 "columns": ["product", "revenue", "units"],
                 "rows": summary["by_product"]},
            ]},
        ]},
    ],
)
```

### Pause for a file, then process

```python
xlsx_path = output.ask("Upload your sales export",
                       type="file", accept=".xlsx")
import pandas as pd
df = pd.read_excel(xlsx_path)
output.table(df.head(20).to_dict(orient="records"), title="Preview")
```

### Custom visualization with `render`

```python
output.data(
    {"score": 87, "threshold": 75},
    visualization=[{"type": "render", "script": """
        const passing = data.score >= data.threshold;
        return React.createElement('div',
            {className: 'p-6 rounded-xl ' + (passing ? 'bg-emerald-50' : 'bg-red-50')},
            React.createElement('div',
                {className: 'text-4xl font-bold ' + (passing ? 'text-emerald-700' : 'text-red-700')},
                data.score),
            React.createElement('div',
                {className: 'text-sm text-gray-600 mt-1'},
                'Threshold: ' + data.threshold)
        );
    """}],
)
```
