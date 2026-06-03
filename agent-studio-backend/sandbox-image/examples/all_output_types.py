"""
Code Executor — Output Examples
================================
Copy any block below into your Code Executor node to try it.
Each example shows one output type. Pick the one you need,
modify the data, and delete the rest.

Your code has access to:
  inputs["variable_name"]    — data you mapped from upstream nodes
  inputs["variables"]        — workflow-level variables
  inputs["workflow_input"]   — the original workflow input
  inputs["runtime"]          — user-submitted form values (if configured)
  inputs["deliverables"]     — list of approved upstream deliverables
  inputs["prev_output"]      — the immediate predecessor's output
  inputs["uploaded_files"]   — list of file paths in /workspace/uploads/
  inputs["pause_responses"]  — list of user answers (multi-pause replay)

SDK modules:
  from agent_studio import output   — emit structured outputs
  from agent_studio import uploads  — access pre-uploaded session files
  from agent_studio import llm      — call LLM directly from sandbox
"""

from agent_studio import output


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 1 — Structured Data (key-value JSON)                       ║
# ║  Use when: returning computed metrics, summaries, or any JSON blob ║
# ╚══════════════════════════════════════════════════════════════════════╝

output.data({
    "total_revenue": 1_250_000,
    "growth_rate": 0.18,
    "top_product": "Enterprise Plan",
    "summary": "Revenue grew 18% QoQ driven by enterprise upgrades."
})


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 1b — Data with Sections (titled groups)                    ║
# ║  Use when: grouping related metrics under headings                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

# output.data({
#     "Revenue": {"total": 1_250_000, "growth_rate": 0.18},
#     "Products": {"top_product": "Enterprise Plan", "units_sold": 340},
#     "Forecast": {"q4_target": 1_500_000, "confidence": "high"},
# }, title="Quarterly Report")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 2 — Table                                                  ║
# ║  Use when: returning rows of data (sortable in the UI)             ║
# ╚══════════════════════════════════════════════════════════════════════╝

# output.table(
#     [
#         {"Company": "Acme Corp", "Revenue": 500_000, "Growth": "12%"},
#         {"Company": "Globex Inc", "Revenue": 350_000, "Growth": "8%"},
#         {"Company": "Initech", "Revenue": 400_000, "Growth": "-3%"},
#     ],
#     title="Pipeline Summary",
# )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 3 — Chart / Visualization                                  ║
# ║  Use when: rendering a bar, line, area, or pie chart               ║
# ╚══════════════════════════════════════════════════════════════════════╝

# output.chart(
#     type="bar",
#     data={
#         "labels": ["Q1", "Q2", "Q3", "Q4"],
#         "values": [120, 180, 150, 210],
#     },
#     title="Quarterly Revenue ($K)",
#     x_label="Quarter",
#     y_label="Revenue",
# )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 4 — Single File Output                                     ║
# ║  Use when: generating a CSV, Excel, PDF, or any downloadable file  ║
# ║  The file appears as a download link in the deliverable card.       ║
# ╚══════════════════════════════════════════════════════════════════════╝

# import csv
#
# with open("/outputs/report.csv", "w", newline="") as f:
#     writer = csv.writer(f)
#     writer.writerow(["Company", "Revenue", "Growth"])
#     writer.writerow(["Acme Corp", 500000, "12%"])
#     writer.writerow(["Globex Inc", 350000, "8%"])
#
# output.file("/outputs/report.csv", display_name="Pipeline Report.csv")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 4b — Multiple File Outputs                                 ║
# ║  Use when: generating several files at once                        ║
# ╚══════════════════════════════════════════════════════════════════════╝

# import json
#
# with open("/outputs/data.json", "w") as f:
#     json.dump({"revenue": 1_250_000}, f)
# with open("/outputs/summary.txt", "w") as f:
#     f.write("Revenue grew 18% QoQ.")
#
# output.files(
#     "/outputs/data.json",
#     ("/outputs/summary.txt", "Executive Summary.txt"),
#     title="Analysis Outputs",
# )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 5 — List (eliminate / pick-one / pick-many)                ║
# ║  Pauses the script.  Returns the user's picks so you can use them. ║
# ╚══════════════════════════════════════════════════════════════════════╝

# kept = output.list(
#     [
#         "Acme Corp",
#         "Globex Industries",
#         "Initech Solutions",
#         "Umbrella LLC",
#         "Stark Enterprises",
#         "Wayne Holdings",
#     ],
#     title="Shortlisted Companies",
#     mode="eliminate",   # "eliminate" | "pick_one" | "pick_many"
# )
# # eliminate / pick_many → list of kept values
# # pick_one             → single value
# output.data({"kept": kept}, title="Final shortlist")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 6 — Selection Widget (pauses script, returns user's choice)║
# ║  Flip allow_multiple=True whenever the prompt implies >1 answer.   ║
# ╚══════════════════════════════════════════════════════════════════════╝

# scenario = output.selection(
#     prompt="Which growth scenario should we model?",
#     options=[
#         {"label": "Conservative (5%)", "value": "conservative"},
#         {"label": "Moderate (12%)",    "value": "moderate"},
#         {"label": "Aggressive (25%)",  "value": "aggressive"},
#     ],
#     allow_multiple=False,
# )
# # scenario == "moderate"   (scalar, because allow_multiple=False)
#
# # Multi-select example — capture the list:
# regions = output.selection(
#     prompt="Which regions should the dashboard include?",
#     options=[{"label": r, "value": r} for r in df["region"].unique()],
#     allow_multiple=True,
# )
# df = df[df["region"].isin(regions)]


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 7 — Form Widget (pauses script, returns dict of answers)   ║
# ╚══════════════════════════════════════════════════════════════════════╝

# cfg = output.form(
#     prompt="Configure the financial model parameters:",
#     fields=[
#         {"name": "discount_rate",       "type": "number", "label": "Discount Rate (%)", "default": 10},
#         {"name": "projection_years",    "type": "number", "label": "Projection Horizon (years)", "default": 5},
#         {"name": "method",              "type": "select", "label": "Valuation Method",
#          "options": ["DCF", "Comparables", "Precedent Transactions"], "default": "DCF"},
#         {"name": "include_sensitivity", "type": "checkbox", "label": "Include Sensitivity Analysis", "default": True},
#     ],
# )
# # cfg["method"], cfg["discount_rate"], ... — use them in the rest of the script.


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 8 — Midway Input (pause script, ask user, then continue)  ║
# ║  Use when: the script needs a decision partway through execution   ║
# ║  The script runs twice: first to ask, second with the answer.      ║
# ╚══════════════════════════════════════════════════════════════════════╝

# companies = ["Acme Corp", "Globex Inc", "Initech", "Umbrella LLC"]
#
# answer = output.ask(
#     "Which company should we focus the deep dive on?",
#     options=companies,
#     type="selection",
# )
#
# output.data({
#     "selected_company": answer,
#     "analysis": f"Deep dive analysis for {answer} goes here...",
# }, title="Company Analysis")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 9 — Ask User to Upload a File, Then Process It            ║
# ║  Use when: the script needs a file from the user to continue      ║
# ║  The script runs twice: first to ask, second with the file.       ║
# ╚══════════════════════════════════════════════════════════════════════╝

# filepath = output.ask(
#     "Please upload your data file (Excel or CSV)",
#     type="file",
#     accept=".xlsx,.csv",
# )
# # First run: shows file upload widget, script pauses
# # Second run: filepath = "/workspace/uploads/mydata.xlsx"
#
# import pandas as pd
# df = pd.read_excel(filepath) if filepath.endswith('.xlsx') else pd.read_csv(filepath)
# output.table(df.head(20).to_dict("records"), title=f"Preview: {filepath.split('/')[-1]}")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 10 — Read Pre-Uploaded Files (from chat session)          ║
# ║  Use when: processing files already uploaded via the chat UI       ║
# ╚══════════════════════════════════════════════════════════════════════╝

# from agent_studio import uploads
#
# file_list = uploads.list()
# if file_list:
#     import pandas as pd
#     df = pd.read_csv(file_list[0])
#     output.table(df.to_dict("records"), title="Uploaded Data")
# else:
#     output.data({"message": "No files were uploaded to this session."})


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 11 — Use Previous Step Output                              ║
# ║  Use when: processing data from the upstream node's deliverable    ║
# ╚══════════════════════════════════════════════════════════════════════╝

# prev = inputs.get("prev_output") or {}
# prev_data = prev.get("deliverable", {})
# deliverables = inputs.get("deliverables", [])
#
# output.data({
#     "previous_node": prev.get("node_id"),
#     "previous_data": prev_data,
#     "total_upstream_deliverables": len(deliverables),
# }, title="Upstream Context")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 12 — Direct LLM Call from Sandbox                          ║
# ║  Use when: you need AI analysis without a separate Agent node       ║
# ║  Requires the GenAI proxy to be configured on the backend.          ║
# ╚══════════════════════════════════════════════════════════════════════╝

# from agent_studio import llm
# import json
#
# result = llm.complete(
#     "Summarize the key financial metrics from this data: revenue=$1.2M, growth=18%",
#     model="gpt-4o-mini",
#     system_prompt="You are a financial analyst. Be concise.",
# )
# output.data({"summary": result}, title="AI Summary")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 13 — LLM with Structured JSON Output                       ║
# ║  Use when: you need the LLM to return a specific JSON schema        ║
# ╚══════════════════════════════════════════════════════════════════════╝

# from agent_studio import llm
# import json
#
# raw = llm.complete(
#     "Extract all person and company names from: 'John Smith from Acme Corp met with Jane Doe of Globex Inc.'",
#     model="gpt-4o-mini",
#     output_schema={
#         "type": "object",
#         "properties": {
#             "people": {"type": "array", "items": {"type": "string"}},
#             "companies": {"type": "array", "items": {"type": "string"}},
#         },
#         "required": ["people", "companies"],
#     },
# )
# entities = json.loads(raw)
# output.data(entities, title="Extracted Entities")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  OPTION 14 — Multi-Pause (ask multiple questions sequentially)      ║
# ║  The script re-runs from the top each time; previous answers replay ║
# ║  instantly from cache.                                               ║
# ╚══════════════════════════════════════════════════════════════════════╝

# name = output.ask("What is your name?", type="text")
# department = output.ask(
#     "Select your department",
#     type="selection",
#     options=["Engineering", "Finance", "Marketing", "Operations"],
# )
# rating = output.ask("Rate your experience (1-10)", type="number", default=7)
#
# output.data({
#     "name": name,
#     "department": department,
#     "rating": rating,
#     "message": f"Thanks {name} from {department}!",
# }, title="Survey Results")
