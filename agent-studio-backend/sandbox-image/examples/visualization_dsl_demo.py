"""
Example: Visualization DSL — declarative layout with composable primitives.

Paste this into a Code Executor node to see the DSL in action.
No frontend changes needed — the visualization parameter on output.data()
drives the entire UI.
"""
from agent_studio import output

sales_data = {
    "quarter": "Q1 2026",
    "total_revenue": 1_250_000,
    "growth_rate": 0.18,
    "top_product": "Enterprise Plan",
    "regions": [
        {"region": "EMEA", "revenue": 520_000, "deals": 34},
        {"region": "APAC", "revenue": 380_000, "deals": 27},
        {"region": "Americas", "revenue": 350_000, "deals": 41},
    ],
    "monthly": [
        {"month": "Jan", "revenue": 380_000, "target": 400_000},
        {"month": "Feb", "revenue": 410_000, "target": 400_000},
        {"month": "Mar", "revenue": 460_000, "target": 450_000},
    ],
}

output.data(
    data=sales_data,
    title="Q1 2026 Sales Report",
    visualization=[
        {
            "type": "header",
            "title": "Q1 2026 Sales Report",
            "subtitle": "Quarterly performance overview",
            "badges": {
                "quarter": "Q1 2026",
                "status": "Final",
                "growth": "+18%",
            },
        },
        {
            "type": "grid",
            "columns": 3,
            "children": [
                {"type": "metric", "value": "$1.25M", "label": "Total Revenue", "change": "+18%", "trend": "up"},
                {"type": "metric", "value": "102", "label": "Total Deals", "change": "+12", "trend": "up"},
                {"type": "metric", "value": "Enterprise Plan", "label": "Top Product"},
            ],
        },
        {"type": "divider"},
        {
            "type": "tabs",
            "tabs": [
                {
                    "label": "By Region",
                    "content": [
                        {
                            "type": "table",
                            "title": "Regional Breakdown",
                            "columns": ["region", "revenue", "deals"],
                            "rows": sales_data["regions"],
                        },
                    ],
                },
                {
                    "label": "Monthly Trend",
                    "content": [
                        {
                            "type": "chart",
                            "chartType": "bar",
                            "title": "Revenue vs Target",
                            "chartData": sales_data["monthly"],
                            "xLabel": "month",
                            "yLabel": "revenue",
                        },
                    ],
                },
                {
                    "label": "Summary",
                    "content": [
                        {
                            "type": "text",
                            "value": "Revenue grew **18% QoQ** driven by enterprise upgrades in EMEA. "
                                     "APAC showed strong deal velocity with 27 closed deals. "
                                     "Americas maintained steady pipeline growth.",
                            "format": "markdown",
                        },
                        {
                            "type": "list",
                            "title": "Key Highlights",
                            "items": [
                                "EMEA: Largest revenue contributor at $520K",
                                "All regions exceeded Q4 baseline",
                                "Enterprise Plan adoption up 23%",
                            ],
                        },
                    ],
                },
            ],
        },
    ],
)

print("Sales report generated with DSL visualization.")
