"""
End-to-end example: query structured tables from a Knowledge Base.

Prerequisite: attach one or more Knowledge Bases to this Code Executor
node via the "Knowledge bases" multiselect in the node configuration.
Upload at least one structured (tabular) document to each KB.

This example shows the three common access patterns in order of
preference:

1.  ``knowledge_base.list_tables()`` -- discover what's available.
2.  ``knowledge_base.read_table(name, limit=...)`` -- DataFrame-first
    read of a single table (Pandas when available).
3.  ``knowledge_base.query(sql, kb_id=...)`` -- escape hatch for
    arbitrary SELECTs, including JOINs and aggregations.

All three are read-only; the host rejects anything that isn't a single
SELECT statement.
"""
from agent_studio import knowledge_base, output, KnowledgeBaseError


def main() -> None:
    try:
        tables = knowledge_base.list_tables()
    except KnowledgeBaseError as exc:
        output.data(
            {"error": str(exc)},
            title="Knowledge Base not configured",
        )
        return

    if not tables:
        output.data(
            {"message": "No structured tables are attached to the "
                        "configured KBs yet."},
            title="Knowledge Base is empty",
        )
        return

    # Pick the first available table for the demo.
    first = tables[0]
    table_name = first["table"]
    kb_id = first["kb_id"]

    df = knowledge_base.read_table(table_name, limit=100, kb_id=kb_id)

    # Pandas path -- describe shape + preview.
    try:
        preview = df.head(20).to_dict(orient="records")
        summary = {
            "kb_name": first["kb_name"],
            "table": table_name,
            "rows_fetched": len(df),
            "columns": list(df.columns),
            "preview": preview,
        }
    except AttributeError:
        # Fallback when pandas isn't installed: df is already list[dict].
        summary = {
            "kb_name": first["kb_name"],
            "table": table_name,
            "rows_fetched": len(df),
            "columns": list(df[0].keys()) if df else [],
            "preview": df[:20],
        }

    output.data(
        summary,
        title=f"Sample from {first['kb_name']} / {table_name}",
        visualization=[
            {"type": "header", "title": f"{first['kb_name']} / {table_name}"},
            {"type": "metric", "label": "Rows fetched",
             "value": summary["rows_fetched"]},
            {"type": "table", "rows": summary["preview"]},
        ],
    )


if __name__ == "__main__":
    main()
