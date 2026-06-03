"""
Type definitions for the visualization DSL used by ``output.data(visualization=[...])``.

The DSL is a list of component specs.  Each spec is a dict with a ``type``
field plus type-specific options.  Container specs (``accordion``,
``tabs``, ``grid``, ``card``) nest child specs recursively.

All TypedDicts below use ``total=False`` so every field is optional --
this matches the runtime frontend which tolerates missing fields.  The
only strictly required key is ``type``.

Usage::

    from agent_studio import output, HeaderSpec, ChartSpec, GridSpec

    spec: ChartSpec = {
        "type": "chart",
        "chart_type": "bar",
        "chart_data": [{"quarter": "Q1", "revenue": 100}],
    }
    output.data(data, visualization=[spec])

Most users won't bother importing the types -- plain dicts work fine.
They exist for IDE autocomplete, static type checking, and as machine-
readable docs for the LLM code generator.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict, Union


# ─── Leaf primitives ──────────────────────────────────────────────────

class HeaderSpec(TypedDict, total=False):
    """Page/section header with title, subtitle, and metadata badges.

    Example::

        {"type": "header", "title": "Q1 Report", "subtitle": "Finance",
         "badges": {"version": "1.0", "status": "final"}}
    """
    type: Literal["header"]
    title: str
    subtitle: str
    badges: dict[str, Any]


class TextSpec(TypedDict, total=False):
    """Paragraph of plain text or lightweight markdown.

    Supports a subset of markdown when ``format="markdown"``:
    ``**bold**``, ``*italic*``, ``` `code` ``` and newlines.

    Example::

        {"type": "text", "value": "Hello **world**", "format": "markdown"}
    """
    type: Literal["text"]
    value: str
    content: str  # alias for value (legacy)
    format: Literal["plain", "markdown"]


class TableSpec(TypedDict, total=False):
    """Sortable table rendered with sticky header.

    Required: ``columns`` (list of column keys), ``rows`` (list of dicts).

    Example::

        {"type": "table", "title": "Sales",
         "columns": ["region", "revenue"],
         "rows": [{"region": "EU", "revenue": 1200},
                  {"region": "US", "revenue": 3400}]}
    """
    type: Literal["table"]
    title: str
    columns: list[str]
    rows: list[dict[str, Any]]


class ListSpec(TypedDict, total=False):
    """Static bullet or numbered list (non-interactive).

    Items can be plain strings or dicts with a ``label`` key.

    Example::

        {"type": "list", "title": "Key findings",
         "items": ["Revenue up 12%", "Costs down 3%"],
         "ordered": False}
    """
    type: Literal["list"]
    title: str
    items: list[Union[str, dict[str, Any]]]
    ordered: bool  # True → <ol>, False → <ul>


class ChartSpec(TypedDict, total=False):
    """Chart powered by Recharts.

    ``chart_type`` supports: ``bar``, ``line``, ``area``, ``pie``.  For
    anything outside this set (scatter, radar, stacked/grouped bar,
    donut, dual-axis, …) emit a ``RenderSpec`` with a small JS snippet
    that builds the chart directly against Recharts.

    ``chart_data`` is a list of dicts; each dict is one data point.
    ``x_label`` / ``y_label`` name the axis keys inside each data point.

    Example::

        {"type": "chart", "title": "Revenue by quarter",
         "chart_type": "bar",
         "chart_data": [{"quarter": "Q1", "revenue": 100},
                        {"quarter": "Q2", "revenue": 150}],
         "x_label": "quarter", "y_label": "revenue"}
    """
    type: Literal["chart"]
    title: str
    chart_type: Literal["bar", "line", "area", "pie"]
    chart_data: list[dict[str, Any]]
    x_label: str
    y_label: str


class FlowchartNode(TypedDict, total=False):
    id: str
    label: str
    swimlane: str
    shape: Literal["box", "diamond", "ellipse", "parallelogram"]


class FlowchartEdge(TypedDict, total=False):
    source: str
    target: str
    label: str


class FlowchartSpec(TypedDict, total=False):
    """Interactive process flowchart.

    Nodes require ``id`` and ``label``.  Edges require ``source`` and
    ``target`` (referencing node ids).  ``swimlanes`` optionally groups
    nodes into horizontal bands.

    Example::

        {"type": "flowchart", "title": "Approval flow",
         "nodes": [{"id": "a", "label": "Submit"},
                   {"id": "b", "label": "Review"},
                   {"id": "c", "label": "Approve"}],
         "edges": [{"source": "a", "target": "b"},
                   {"source": "b", "target": "c"}]}
    """
    type: Literal["flowchart"]
    title: str
    nodes: list[FlowchartNode]
    edges: list[FlowchartEdge]
    swimlanes: list[str]
    height: int


class MetricSpec(TypedDict, total=False):
    """Single big-number metric with optional trend indicator.

    Example::

        {"type": "metric", "label": "Revenue", "value": "$1.2M",
         "change": "+12%", "trend": "up"}
    """
    type: Literal["metric"]
    label: str
    value: Union[str, int, float]
    change: str
    trend: Literal["up", "down", "neutral"]


class DividerSpec(TypedDict, total=False):
    """Horizontal rule for visual separation.

    Example::

        {"type": "divider"}
    """
    type: Literal["divider"]


class CodeSpec(TypedDict, total=False):
    """Syntax-highlighted code block.

    Example::

        {"type": "code", "title": "Query", "language": "sql",
         "value": "SELECT * FROM users WHERE id = 1"}
    """
    type: Literal["code"]
    title: str
    language: str
    value: str


# ─── Container primitives ─────────────────────────────────────────────

# Forward-declared; PrimitiveSpec defined below.

class AccordionSection(TypedDict, total=False):
    title: str
    content: list["PrimitiveSpec"]


class AccordionSpec(TypedDict, total=False):
    """Collapsible sections.  Each section's content is a nested list of specs.

    Example::

        {"type": "accordion", "sections": [
            {"title": "Details", "content": [{"type": "text", "value": "..."}]},
            {"title": "Raw data", "content": [{"type": "table", ...}]},
        ]}
    """
    type: Literal["accordion"]
    sections: list[AccordionSection]


class TabSection(TypedDict, total=False):
    label: str
    content: list["PrimitiveSpec"]


class TabsSpec(TypedDict, total=False):
    """Tab strip; each tab's content is a nested list of specs.

    Example::

        {"type": "tabs", "tabs": [
            {"label": "Summary", "content": [{"type": "metric", ...}]},
            {"label": "Details", "content": [{"type": "table", ...}]},
        ]}
    """
    type: Literal["tabs"]
    tabs: list[TabSection]


class GridSpec(TypedDict, total=False):
    """Equal-width grid.  Each cell holds a nested spec or list of specs.

    Example::

        {"type": "grid", "columns": 3, "children": [
            {"type": "metric", "label": "Revenue", "value": "$1M"},
            {"type": "metric", "label": "Users", "value": "12k"},
            {"type": "metric", "label": "Churn", "value": "3%"},
        ]}
    """
    type: Literal["grid"]
    columns: int
    children: list[Union["PrimitiveSpec", list["PrimitiveSpec"]]]


class CardSpec(TypedDict, total=False):
    """Bordered card wrapping nested specs.

    Example::

        {"type": "card", "title": "Summary", "children": [
            {"type": "text", "value": "Revenue is up."},
            {"type": "chart", "chart_type": "line", "chart_data": [...]},
        ]}
    """
    type: Literal["card"]
    title: str
    children: list["PrimitiveSpec"]


# ─── Custom JavaScript escape hatch ───────────────────────────────────

class RenderSpec(TypedDict, total=False):
    """Escape hatch for rendering a custom React element from inline JS.

    The ``script`` is executed as a function body with three arguments:

    - ``data``: the deliverable payload (everything passed to
      ``output.data``).
    - ``React``: the React module.  Use ``React.useState``,
      ``React.useMemo``, etc. for state.  To use hooks, define a
      component inside the script and ``return React.createElement(MyCmp)``.
    - ``Recharts``: the Recharts library.  Useful components:
      ``BarChart``, ``LineChart``, ``AreaChart``, ``PieChart``, ``Bar``,
      ``Line``, ``Area``, ``Pie``, ``XAxis``, ``YAxis``, ``CartesianGrid``,
      ``Tooltip``, ``Legend``, ``ResponsiveContainer``, ``Cell``.

    Must ``return`` a React element.  JSX is not available -- use
    ``React.createElement(tag, props, ...children)``.  Errors are caught
    and displayed inline so a bad script won't break the rest of the
    output.

    Reach for this when you need interactivity (filters driving charts,
    drill-downs) or layouts the primitives can't express.

    Example::

        {"type": "render", "script": '''
            return React.createElement('div',
                {className: 'p-4 bg-blue-50 rounded-lg'},
                React.createElement('h3', {className: 'font-bold'},
                    'Revenue: $' + data.revenue),
                React.createElement('p', null,
                    'Growth: ' + (data.growth * 100).toFixed(1) + '%')
            );
        '''}
    """
    type: Literal["render"]
    script: str


# ─── Union of all spec types ──────────────────────────────────────────

PrimitiveSpec = Union[
    HeaderSpec, TextSpec, TableSpec, ListSpec,
    ChartSpec, FlowchartSpec, MetricSpec, DividerSpec, CodeSpec,
    AccordionSpec, TabsSpec, GridSpec, CardSpec,
    RenderSpec,
]
"""Any valid DSL primitive spec.  Pass a list of these to
``output.data(visualization=[...])``."""


Visualization = Union[PrimitiveSpec, list[PrimitiveSpec]]
"""The ``visualization`` argument.  Can be a single spec (wrapped to a
list internally) or a list rendered top-to-bottom."""


__all__ = [
    "HeaderSpec", "TextSpec", "TableSpec", "ListSpec",
    "ChartSpec", "FlowchartSpec", "FlowchartNode", "FlowchartEdge",
    "MetricSpec", "DividerSpec", "CodeSpec",
    "AccordionSpec", "AccordionSection",
    "TabsSpec", "TabSection",
    "GridSpec", "CardSpec",
    "RenderSpec",
    "PrimitiveSpec", "Visualization",
]
