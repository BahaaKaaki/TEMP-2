"""Deliverable Reader — reads upstream deliverables and re-displays them.

Use this in a downstream Code Executor node to inspect, summarize, or
relay the output of any upstream agent or code executor.

Configure the node's "Upstream Deliverables Access" to select which
nodes this script should read from, or set it to "all" to see everything.
"""

from agent_studio import output
import json

deliverables = inputs.get("deliverables", [])

if not deliverables:
    output.data({"message": "No upstream deliverables found."}, title="No Data")
    raise SystemExit(0)

print(f"Found {len(deliverables)} upstream deliverable(s).\n")

sections = []
all_data = {}

for i, d in enumerate(deliverables):
    source = d.get("agent_label") or d.get("agent_type") or f"Source {i + 1}"
    data = d.get("data", {})

    if isinstance(data, dict):
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
    else:
        clean = data

    all_data[source] = clean

    summary_lines = []
    if isinstance(clean, dict):
        for key in list(clean.keys())[:8]:
            val = clean[key]
            if isinstance(val, list):
                summary_lines.append(f"- **{key}**: {len(val)} items")
            elif isinstance(val, dict):
                summary_lines.append(f"- **{key}**: {len(val)} keys")
            else:
                text = str(val)
                if len(text) > 120:
                    text = text[:120] + "..."
                summary_lines.append(f"- **{key}**: {text}")
    elif isinstance(clean, list):
        summary_lines.append(f"{len(clean)} items")
    else:
        summary_lines.append(str(clean)[:200])

    sections.append({
        "title": f"From: {source}",
        "content": "\n".join(summary_lines) if summary_lines else "(empty)",
    })

    print(f"  [{i + 1}] {source}: {len(json.dumps(clean, default=str))} chars")

out_path = "/outputs/upstream_deliverables.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False, default=str)
print(f"\nFull data saved to {out_path}")

output.data(
    all_data,
    title="Upstream Deliverables",
    visualization=[
        {
            "type": "sections",
            "sections": sections,
        }
    ],
)
