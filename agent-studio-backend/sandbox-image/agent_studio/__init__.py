"""
agent_studio -- Python SDK available inside sandbox containers.

Provides typed output helpers so user code can emit structured results
(data, tables, charts, files, interactive widgets) that the Code Executor
node understands and the frontend can render.

Usage inside sandbox::

    from agent_studio import output, llm, uploads, knowledge_base

    output.data({"revenue": 1_000_000})
    output.data(
        data,
        visualization=[
            {"type": "header", "title": "Q1 Report"},
            {"type": "chart", "chart_type": "bar", "chart_data": [...]},
        ],
    )

    result = llm.complete("Summarize this data", model="gpt-4o-mini")

    for path in uploads.list():
        ...

    # Pull structured data from a configured Knowledge Base.
    df = knowledge_base.read_table("customers", limit=100)
    agg = knowledge_base.query(
        "SELECT region, COUNT(*) AS n FROM customers GROUP BY region",
        kb_id="<uuid>",
    )

Type hints for visualization specs are exposed for IDE autocomplete::

    from agent_studio import ChartSpec, GridSpec, MetricSpec
"""

from agent_studio._knowledge_base import KnowledgeBaseError, knowledge_base
from agent_studio._llm import llm
from agent_studio._output import output
from agent_studio._uploads import uploads
from agent_studio._viz_types import (
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

__all__ = [
    "output",
    "uploads",
    "llm",
    "knowledge_base",
    "KnowledgeBaseError",
    "AccordionSection",
    "AccordionSpec",
    "CardSpec",
    "ChartSpec",
    "CodeSpec",
    "DividerSpec",
    "FlowchartEdge",
    "FlowchartNode",
    "FlowchartSpec",
    "GridSpec",
    "HeaderSpec",
    "ListSpec",
    "MetricSpec",
    "PrimitiveSpec",
    "RenderSpec",
    "TableSpec",
    "TabSection",
    "TabsSpec",
    "TextSpec",
    "Visualization",
]
