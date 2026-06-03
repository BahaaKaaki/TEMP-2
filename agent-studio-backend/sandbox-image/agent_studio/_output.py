"""
Output helpers for the agent_studio sandbox SDK.

Every public method serialises a structured result to ``/outputs/_result.json``.
The CodeExecutorNode reads that file after execution and converts it into
a typed deliverable.  Only the **last** call wins -- if user code calls
``output.data()`` then ``output.chart()``, the chart replaces the data.

## The one rule to remember

Call exactly **one** of the emission methods before your script ends.
Everything else is a helper around this.

## Two flavours of output

1. **Canonical**: ``output.data(payload, visualization=[...])``
   A JSON payload + a list of DSL component specs that tell the frontend
   how to render the payload.  Composable -- drop in a header, a metric
   row, a chart and a table in one output.  See ``_viz_types.py`` for the
   spec schema.  Reach for the ``render`` spec (a tiny JS snippet) when
   the primitives can't express what you want.

2. **Shortcuts** for common single-component cases.  These are thin
   wrappers around ``data()`` + a pre-filled DSL spec:

   - ``output.table(rows)``   → single ``{type: "table"}`` spec
   - ``output.chart(...)``    → single ``{type: "chart"}`` spec
   - ``output.flat_list(items)`` → single ``{type: "list"}`` spec
   - ``output.document(...)`` → composed of ``header`` + ``accordion`` +
     optional ``flowchart``

All of them produce identical JSON on the wire, so downstream nodes
always see the same envelope regardless of which helper you used.

## Not visualizations -- interactive pauses and file deliverables

These **pause** the script (``sys.exit(42)``) and **return the user's
answer** on resume:

- ``output.ask(...)``       -- single-question pause (text / number /
                               selection / confirm / file)
- ``output.selection(...)`` -- pick one or many from fixed options;
                               returns a scalar or ``list``
- ``output.list(...)``      -- filterable list with ``eliminate`` /
                               ``pick_one`` / ``pick_many`` modes
- ``output.form(...)``      -- multi-field form; returns ``dict``

These register downloadable files (no pause, no return value):

- ``output.file(path)`` / ``output.files(*paths)``

## Midway pause (all four pause methods)

All four interactive methods share the same **indexed multi-pause
replay** mechanism.  On every script re-run the host injects
``inputs["pause_responses"]``.  If the answer for this pause index is
already cached the method returns it instantly; otherwise the SDK
writes the question to ``/outputs/_pause.json``, saves a checkpoint of
user variables (so resume skips re-running expensive work), and exits
with code 42 so the host can surface the widget to the user.
"""

from __future__ import annotations

import inspect
import json
import sys
from typing import Any

from agent_studio._viz_types import (  # re-exported for convenience
    AccordionSection,
    AccordionSpec,
    CardSpec,
    ChartSpec,
    CodeSpec,
    DividerSpec,
    FlowchartEdge,
    FlowchartNode,
    FlowchartSpec,
    GridSpec,
    HeaderSpec,
    ListSpec,
    MetricSpec,
    PrimitiveSpec,
    RenderSpec,
    TableSpec,
    TabSection,
    TabsSpec,
    TextSpec,
    Visualization,
)

_OUTPUT_PATH = "/outputs/_result.json"
_PAUSE_PATH = "/outputs/_pause.json"

_pause_counter: int = 0


class _Output:
    """Singleton that writes the SDK result file.  Accessed as ``output``."""

    # ==================================================================
    # Canonical emission -- data + optional visualization DSL
    # ==================================================================

    def data(
        self,
        data: dict[str, Any] | list | Any,
        *,
        title: str = "Result",
        visualization: Visualization | None = None,
    ) -> None:
        """Emit a JSON payload and optionally a visualization spec.

        This is the one method every other non-interactive emitter calls
        under the hood.

        Args:
            data: Any JSON-serialisable value.  This is the **clean**
                output that downstream nodes and agents receive -- no
                frontend concerns leak into it.
            title: Human-readable title for the output card.
            visualization: Optional rendering instructions for the
                frontend.  A single spec dict or a list of specs rendered
                top-to-bottom.  Each spec has a ``type`` key and
                type-specific fields -- see ``agent_studio._viz_types``
                for the full schema with examples.

                Built-in leaf primitives:
                    header, text, table, list (display-only), chart,
                    flowchart, metric, divider, code

                Container primitives (nest child specs):
                    accordion, tabs, grid, card

                Escape hatch:
                    ``{"type": "render", "script": "<JS function body>"}``
                    -- receives ``data`` and ``React`` and must return a
                    React element via ``React.createElement``.

                When omitted the frontend falls back to a generic
                key-value renderer over ``data``.  Visualization is
                **never** passed to downstream nodes.

        Examples::

            # Plain data, no custom rendering
            output.data({"revenue": 1_000_000, "growth": 0.23})

            # Composed dashboard
            output.data(
                {"revenue": 1_000_000, "growth": 0.23},
                title="Q1 Snapshot",
                visualization=[
                    {"type": "header", "title": "Q1 Snapshot",
                     "badges": {"status": "final"}},
                    {"type": "grid", "columns": 3, "children": [
                        {"type": "metric", "label": "Revenue",
                         "value": "$1.0M", "change": "+23%", "trend": "up"},
                        {"type": "metric", "label": "MRR", "value": "$83k"},
                        {"type": "metric", "label": "Churn", "value": "3%"},
                    ]},
                    {"type": "chart", "chart_type": "bar",
                     "chart_data": [{"q": "Q1", "rev": 1000}]},
                ],
            )
        """
        result: dict[str, Any] = {
            "type": "data",
            "data": data,
            "metadata": {"title": title},
            "interactive": False,
        }
        if visualization is not None:
            if isinstance(visualization, dict):
                visualization = [visualization]
            result["visualization"] = list(visualization)
        self._write(result)

    # ==================================================================
    # Shortcuts -- each is one line of sugar over data()
    # ==================================================================

    def table(
        self,
        data: dict[str, list] | list[dict],
        *,
        title: str = "Table",
        columns: list[str] | None = None,
    ) -> None:
        """Emit tabular data as a single-table visualization.

        Accepts either shape -- both are normalised to a rows-and-columns
        DSL ``table`` primitive:

        - dict-of-lists: ``{"Name": ["A", "B"], "Score": [1, 2]}``
        - list-of-dicts: ``[{"Name": "A", "Score": 1}, ...]``

        Example::

            output.table([{"name": "Alice", "score": 92},
                          {"name": "Bob", "score": 87}],
                         title="Top performers")
        """
        rows, cols = _normalise_table(data, columns)
        spec: TableSpec = {
            "type": "table",
            "title": title,
            "columns": cols,
            "rows": rows,
        }
        self.data(data, title=title, visualization=[spec])

    def chart(
        self,
        *,
        type: str = "bar",
        data: list[dict[str, Any]] | dict[str, Any] | None = None,
        title: str = "Chart",
        x_label: str | None = None,
        y_label: str | None = None,
    ) -> None:
        """Emit a Recharts-compatible chart.

        ``type`` must be one of ``bar``, ``line``, ``area``, ``pie``.
        For anything outside this set (scatter, radar, stacked/grouped
        bar, donut, dual-axis, …) use ``output.data(..., visualization=
        [{"type": "render", "script": ...}])`` with a small JS snippet
        that builds the chart directly against Recharts.

        ``data`` is a list of data-point dicts; ``x_label`` / ``y_label``
        name the keys inside each point that supply the axes.

        Example::

            output.chart(
                type="line",
                data=[{"day": d, "visits": v}
                      for d, v in zip(["Mon", "Tue", "Wed"], [100, 150, 140])],
                x_label="day", y_label="visits",
                title="Weekly traffic",
            )
        """
        spec: ChartSpec = {
            "type": "chart",
            "title": title,
            "chart_type": type,
            "chart_data": data or [],
        }
        if x_label:
            spec["x_label"] = x_label
        if y_label:
            spec["y_label"] = y_label
        self.data(data or [], title=title, visualization=[spec])

    def flat_list(
        self,
        items: list[str | dict[str, Any]],
        *,
        title: str = "Items",
        ordered: bool = False,
    ) -> None:
        """Emit a static (non-interactive) bullet or numbered list.

        For an interactive list (filter / pick), use ``output.list()``.

        Example::

            output.flat_list(["Increase pricing", "Hire two engineers",
                              "Launch in EU"], title="Q2 priorities")
        """
        normalised = [
            item if isinstance(item, str) else item.get("label", str(item))
            for item in items
        ]
        spec: ListSpec = {
            "type": "list",
            "title": title,
            "items": normalised,
            "ordered": ordered,
        }
        self.data({"items": normalised}, title=title, visualization=[spec])

    def document(
        self,
        *,
        title: str = "Document",
        metadata: dict[str, Any] | None = None,
        sections: list[dict[str, Any]] | None = None,
        graph: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured document: title + sections + optional flowchart.

        This is a convenience wrapper that composes DSL primitives:
        ``header`` (title + metadata badges) + ``accordion`` (sections) +
        optional ``flowchart`` (graph).  For custom layouts reach for
        ``output.data()`` directly.

        Each section dict has ``title`` and a ``type``:

        - ``type="text"``, ``content=str``
        - ``type="table"``, ``columns=[...]``, ``rows=[...]``
        - ``type="list"``, ``items=[...]``

        Example::

            output.document(
                title="Q1 Report",
                metadata={"version": "1.0", "status": "final"},
                sections=[
                    {"title": "Summary", "type": "text", "content": "..."},
                    {"title": "Results", "type": "table",
                     "columns": ["region", "revenue"], "rows": [...]},
                ],
                graph={"nodes": [...], "edges": [...]},
            )
        """
        visualization: list[PrimitiveSpec] = []

        header: HeaderSpec = {"type": "header", "title": title}
        if metadata:
            header["badges"] = metadata
        visualization.append(header)

        if sections:
            accordion_sections: list[AccordionSection] = []
            for sec in sections:
                sec_type = sec.get("type", "text")
                sec_title = sec.get("title", "")
                content: list[PrimitiveSpec] = []
                if sec_type == "text":
                    content.append({
                        "type": "text",
                        "value": sec.get("content", ""),
                    })
                elif sec_type == "table":
                    content.append({
                        "type": "table",
                        "columns": sec.get("columns", []),
                        "rows": sec.get("rows", []),
                    })
                elif sec_type == "list":
                    content.append({
                        "type": "list",
                        "items": sec.get("items", []),
                    })
                accordion_sections.append({
                    "title": sec_title, "content": content,
                })
            visualization.append({
                "type": "accordion",
                "sections": accordion_sections,
            })

        if graph and graph.get("nodes"):
            flowchart: FlowchartSpec = {
                "type": "flowchart",
                "title": "Process Flow",
                "nodes": graph.get("nodes", []),
                "edges": graph.get("edges", []),
            }
            if graph.get("swimlanes"):
                flowchart["swimlanes"] = graph["swimlanes"]
            visualization.append(flowchart)

        payload = {
            "title": title,
            "metadata": metadata or {},
            "sections": sections or [],
            "graph": graph,
        }
        self.data(payload, title=title, visualization=visualization)

    # ==================================================================
    # File outputs -- register downloads, not visualizations
    # ==================================================================

    def file(self, path: str, *, display_name: str | None = None) -> None:
        """Register a single output file (must be under /outputs/).

        The host extracts the file, persists it, and makes it downloadable
        from the deliverable card.

        Example::

            with open("/outputs/report.xlsx", "wb") as f:
                f.write(workbook_bytes)
            output.file("/outputs/report.xlsx", display_name="Q1 Report.xlsx")
        """
        import os
        import shutil
        dest = "/outputs/" + os.path.basename(path)
        if os.path.abspath(path) != os.path.abspath(dest):
            shutil.copy2(path, dest)
        self._write({
            "type": "file",
            "data": {
                "path": dest,
                "display_name": display_name or os.path.basename(path),
            },
            "metadata": {},
            "interactive": False,
        })

    def files(self, *paths: str | tuple[str, str], title: str = "Output Files") -> None:
        """Register multiple output files at once.

        Each entry is either a path string or a ``(path, display_name)``
        tuple.  All files are copied into ``/outputs/`` for extraction.

        Example::

            output.files(
                "/outputs/summary.pdf",
                ("/outputs/raw.csv", "Raw data (CSV)"),
                title="Deliverables",
            )
        """
        import os
        import shutil
        entries: list[dict[str, str]] = []
        for p in paths:
            if isinstance(p, (list, tuple)):
                src, name = p[0], p[1]
            else:
                src, name = p, os.path.basename(p)
            dest = "/outputs/" + os.path.basename(src)
            if os.path.abspath(src) != os.path.abspath(dest):
                shutil.copy2(src, dest)
            entries.append({"path": dest, "display_name": name})

        self._write({
            "type": "files",
            "data": {"files": entries},
            "metadata": {"title": title},
            "interactive": False,
        })

    # ==================================================================
    # Interactive widgets -- pause for user action when node.interactive=True
    # ==================================================================

    # ==================================================================
    # Interactive pauses -- block for user input, return the user's answer
    # ==================================================================
    #
    # ``ask``, ``selection``, ``list`` and ``form`` all share the same
    # "exit 42 → host → resume" replay contract implemented by
    # :func:`_pause_and_return` below.  Each public method is a thin
    # wrapper that (a) normalises its arguments into a pause payload and
    # (b) delegates to the helper, which either returns a cached answer
    # or pauses the sandbox.
    #
    # Design note: historically ``selection``/``list``/``form`` were
    # terminal "interactive deliverables" -- they just wrote
    # ``/outputs/_result.json`` and returned ``None``.  That meant any
    # subsequent ``output.*`` call silently overwrote them, and the
    # documented return types were aspirational.  Routing them through
    # the same pause mechanism as ``ask`` makes the widgets actually
    # show up, preserves their answers across resume, and unifies the
    # four methods into a single mental model.

    def ask(
        self,
        prompt: str,
        *,
        options: list[str | dict[str, Any]] | None = None,
        type: str = "text",
        default: Any = None,
        accept: str | None = None,
        multiple: bool = False,
        checkpoint: bool = True,
    ) -> Any:
        """Pause execution and ask the user a single question.

        Args:
            prompt: The question to display.
            options: For ``type="selection"`` -- list of choices.
            type: ``"text"`` | ``"number"`` | ``"selection"`` |
                  ``"confirm"`` | ``"file"``.
            default: Default value pre-filled in the UI.
            accept: For ``type="file"`` -- comma-separated file
                    extensions (e.g. ``".xlsx,.csv"``).
            multiple: For ``type="file"`` -- allow uploading multiple
                      files.  When ``True`` the return value is a
                      **list** of sandbox paths.
            checkpoint: If True (default), save a checkpoint of user
                        variables before pausing so the script resumes
                        without re-executing expensive work.  Disable
                        if you have unpicklable state.

        Returns:
            The user's answer.  For ``type="file"`` this is the sandbox
            path (``/workspace/uploads/<filename>``), or a list of paths
            when ``multiple=True``.

        Example::

            name = output.ask("What is your name?")
            xlsx_path = output.ask("Upload your sales export",
                                    type="file", accept=".xlsx")
            df = pandas.read_excel(xlsx_path)
        """
        normalised_options = None
        if options:
            normalised_options = []
            for opt in options:
                if isinstance(opt, str):
                    normalised_options.append({"label": opt, "value": opt})
                elif isinstance(opt, dict):
                    normalised_options.append(opt)

        payload_data: dict[str, Any] = {
            "prompt": prompt,
            "options": normalised_options,
            "default": default,
        }
        if type == "file":
            if accept:
                payload_data["accept"] = accept
            if multiple:
                payload_data["multiple"] = True
        elif type == "selection" and multiple:
            # Lets callers also reach multi-select via `ask(type="selection",
            # multiple=True, options=[...])` rather than having to switch to
            # `output.selection(allow_multiple=True)`.
            payload_data["multiple"] = True
            payload_data["allow_multiple"] = True

        return _pause_and_return(
            payload_data,
            pause_type=type,
            checkpoint=checkpoint,
            caller_frame=inspect.currentframe().f_back,
        )

    def selection(
        self,
        *,
        prompt: str,
        options: list[str | dict[str, Any]],
        allow_multiple: bool = False,
        checkpoint: bool = True,
    ) -> Any:
        """Pause execution and ask the user to pick from fixed options.

        Renders as **radio buttons** by default, or as **checkboxes** when
        ``allow_multiple=True``.

        Args:
            prompt: Question shown above the options.
            options: Either ``list[str]`` (label == value) or
                     ``list[{"label": str, "value": Any}]``.
            allow_multiple: If True, user may pick more than one option.
            checkpoint: Save a resume checkpoint before pausing. See
                        :meth:`ask` for details.

        Returns:
            Scalar ``value`` of the chosen option when
            ``allow_multiple=False``; ``list`` of chosen values when
            ``allow_multiple=True``.

        Example::

            plan = output.selection(
                prompt="Pick a plan",
                options=[
                    {"label": "Starter", "value": "s"},
                    {"label": "Pro",     "value": "p"},
                ],
            )

            regions = output.selection(
                prompt="Which regions to include?",
                options=[{"label": r, "value": r} for r in regions],
                allow_multiple=True,
            )
        """
        normalised_options: list[dict[str, Any]] = []
        for opt in options or []:
            if isinstance(opt, str):
                normalised_options.append({"label": opt, "value": opt})
            elif isinstance(opt, dict):
                normalised_options.append(opt)

        return _pause_and_return(
            {
                "prompt": prompt,
                "options": normalised_options,
                "multiple": allow_multiple,
                # Kept for frontend back-compat with the standalone
                # SelectionWidget which reads `allow_multiple`.
                "allow_multiple": allow_multiple,
            },
            pause_type="selection",
            checkpoint=checkpoint,
            caller_frame=inspect.currentframe().f_back,
        )

    def list(
        self,
        items: list[str | dict[str, Any]],
        *,
        title: str = "Items",
        mode: str = "eliminate",
        checkpoint: bool = True,
    ) -> Any:
        """Pause execution and show a filterable list the user can trim / pick.

        Distinct from the display-only ``list`` DSL primitive inside
        ``output.data(visualization=...)`` -- this one is interactive
        and blocks until the user submits.

        Args:
            items: Plain strings or ``{"label": ..., "value": ...}`` dicts.
            title: Heading shown above the list.
            mode: ``"eliminate"`` (default) -- every item starts checked,
                  user unchecks to drop; ``"pick_one"`` -- single pick;
                  ``"pick_many"`` -- multi pick from empty state.
            checkpoint: Save a resume checkpoint before pausing.

        Returns:
            - ``mode="eliminate"``: ``list`` of the values the user kept.
            - ``mode="pick_one"``: the single chosen ``value``.
            - ``mode="pick_many"``: ``list`` of the values the user picked.

        Example::

            kept = output.list(candidates, title="Shortlist",
                               mode="eliminate")
            chosen = output.list(regions, title="Pick regions",
                                 mode="pick_many")
        """
        normalised: list[dict[str, Any]] = []
        for item in items or []:
            if isinstance(item, str):
                normalised.append({"label": item, "value": item})
            elif isinstance(item, dict):
                normalised.append({
                    "label": item.get("label", str(item.get("value", ""))),
                    "value": item.get("value", item.get("label", "")),
                })
            else:
                normalised.append({"label": str(item), "value": item})

        return _pause_and_return(
            {
                "prompt": title,
                "title": title,
                "items": normalised,
                "mode": mode,
            },
            pause_type="list",
            checkpoint=checkpoint,
            caller_frame=inspect.currentframe().f_back,
        )

    def form(
        self,
        *,
        prompt: str,
        fields: list[dict[str, Any]],
        checkpoint: bool = True,
    ) -> dict[str, Any]:
        """Pause execution and show a multi-field form.

        Args:
            prompt: Heading shown above the form.
            fields: Each field dict is
                    ``{"name": str,
                       "type": "text"|"number"|"select"|"checkbox",
                       "label": str, "default": Any,
                       "options": [...],  # for `select`
                       "required": bool}``.
            checkpoint: Save a resume checkpoint before pausing.

        Returns:
            ``dict[name -> value]`` -- one entry per field.

        Example::

            answers = output.form(prompt="Confirm details", fields=[
                {"name": "email", "type": "text", "required": True},
                {"name": "plan",  "type": "select",
                 "options": ["starter", "pro"], "default": "pro"},
                {"name": "newsletter", "type": "checkbox", "default": False},
            ])
            send_invite(answers["email"], answers["plan"])
        """
        return _pause_and_return(
            {
                "prompt": prompt,
                "fields": fields or [],
            },
            pause_type="form",
            checkpoint=checkpoint,
            caller_frame=inspect.currentframe().f_back,
        )

    # ==================================================================
    # Internal
    # ==================================================================

    @staticmethod
    def _write(payload: dict[str, Any]) -> None:
        with open(_OUTPUT_PATH, "w") as f:
            json.dump(payload, f, default=str)


# ─── Shared pause mechanism (used by ask/selection/list/form) ───────────

def _pause_and_return(
    payload_data: dict[str, Any],
    *,
    pause_type: str,
    checkpoint: bool = True,
    caller_frame: Any | None = None,
) -> Any:
    """Indexed multi-pause replay.

    On re-run, dequeues the cached answer for the current pause index
    from ``inputs["pause_responses"]`` and returns it.  On first run,
    snapshots the caller's locals (if requested), writes the pause
    payload to ``/outputs/_pause.json``, and exits with code 42 so the
    host can surface the widget to the user.

    ``caller_frame`` must be the user-code frame (typically
    ``inspect.currentframe().f_back`` captured by the public method).
    Passing it explicitly -- rather than computing ``f_back.f_back``
    inside this helper -- keeps the stack-walking correct regardless
    of how many SDK wrappers sit between user code and this function.
    """
    global _pause_counter

    import builtins
    _inputs = getattr(builtins, "_agent_studio_inputs", {}) or {}

    # ── Cached replay: answer already available from a previous pause ──
    responses = _inputs.get("pause_responses") or []
    if _pause_counter < len(responses):
        cached = responses[_pause_counter]
        _pause_counter += 1
        if isinstance(cached, dict):
            return cached.get("value", cached)
        return cached

    # Legacy single-response back-compat (pre-multi-pause hosts)
    legacy = _inputs.get("pause_response")
    if legacy is not None and _pause_counter == 0:
        _pause_counter += 1
        if isinstance(legacy, dict):
            return legacy.get("value", legacy)
        return legacy

    # ── First encounter for this pause index: checkpoint and exit 42 ──
    has_checkpoint = False
    if checkpoint:
        try:
            from agent_studio._checkpoint import save_checkpoint
            if caller_frame is None:
                # Fallback: user-code frame is the caller of this helper's
                # caller (user → public method → _pause_and_return).
                caller_frame = inspect.currentframe().f_back.f_back
            has_checkpoint = save_checkpoint(caller_frame)
        except Exception:
            pass

    payload = {
        **payload_data,
        "type": pause_type,
        "pause_index": _pause_counter,
        "has_checkpoint": has_checkpoint,
    }

    with open(_PAUSE_PATH, "w") as f:
        json.dump(payload, f, default=str)

    sys.exit(42)


# ─── Helpers ──────────────────────────────────────────────────────────

def _normalise_table(
    data: Any,
    columns: list[str] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Coerce dict-of-lists or list-of-dicts into (rows, columns)."""
    if isinstance(data, dict):
        cols = columns or list(data.keys())
        length = max((len(data.get(c) or []) for c in cols), default=0)
        rows = []
        for i in range(length):
            rows.append({c: (data.get(c) or [None] * length)[i] for c in cols})
        return rows, cols
    if isinstance(data, list) and data:
        cols = columns or list(data[0].keys()) if isinstance(data[0], dict) else (columns or [])
        return list(data), cols
    return [], columns or []


output = _Output()
