"""
Example: Read and re-display the previous node's deliverable.

Use this in a second Code Executor node that is connected downstream
from another Code Executor or Agent node.  It reads the upstream
deliverable data and re-displays it using the visualization layer.

Available inputs:
    inputs["deliverables"]   - list of approved upstream deliverables
    inputs["prev_output"]    - immediate predecessor node's output
    inputs["variables"]      - workflow variables
    inputs["workflow_input"] - original user input
"""
from agent_studio import output
import json
import builtins

_inputs = getattr(builtins, "_agent_studio_inputs", {}) or {}

deliverables = _inputs.get("deliverables", [])
prev = _inputs.get("prev_output")

if not deliverables and not prev:
    output.data(
        data={"error": "No upstream deliverables found"},
        title="No Input",
        visualization=[
            {"type": "card", "title": "No upstream data", "children": [
                {"type": "text", "value": "This node has no upstream deliverables. "
                 "Make sure it is connected downstream from another Code Executor or Agent node, "
                 "and that the upstream node has produced output."},
            ]},
        ],
    )
else:
    upstream_data = None
    source_label = "Unknown"

    if deliverables:
        d = deliverables[0]
        upstream_data = d.get("data", {})
        source_label = d.get("agent_label", "Upstream Node")
        print(f"Reading deliverable from: {source_label}")
    elif prev:
        upstream_data = prev.get("deliverable", {})
        source_label = prev.get("node_id", "Previous Node")
        print(f"Reading prev_output from: {source_label}")

    clean_data = {
        k: v for k, v in (upstream_data or {}).items()
        if not k.startswith("_")
    }

    keys = list(clean_data.keys())
    summary_items = []
    for k in keys[:10]:
        v = clean_data[k]
        if isinstance(v, (dict, list)):
            summary_items.append(f"{k}: ({type(v).__name__}, {len(v)} items)")
        else:
            summary_items.append(f"{k}: {v}")

    output.data(
        data=clean_data,
        title=f"Data from {source_label}",
        visualization=[
            {
                "type": "header",
                "title": f"Deliverable from {source_label}",
                "badges": {
                    "keys": str(len(keys)),
                    "source": source_label,
                },
            },
            {
                "type": "accordion",
                "sections": [
                    {
                        "title": f"Data Summary ({len(keys)} keys)",
                        "content": [
                            {"type": "list", "items": summary_items},
                        ],
                    },
                    {
                        "title": "Raw JSON",
                        "content": [
                            {"type": "code", "value": json.dumps(clean_data, indent=2, default=str), "language": "json"},
                        ],
                    },
                ],
            },
        ],
    )

    print(f"Re-displayed {len(keys)} keys from upstream deliverable.")
