"""
Text-to-SQL tool for agents to query structured data (CSV/Excel) stored in per-KB PostgreSQL schemas.

Includes a table-selection step so the SQL generator only sees relevant
tables instead of the entire schema -- critical when a KB has many tables.
"""
import json
import logging
import re
from typing import Optional, Dict, Any, List, Tuple

try:
    from pydantic import BaseModel, Field
except ImportError:
    from pydantic.v1 import BaseModel, Field

from app.repositories.structured_data_repository import StructuredDataRepository
from app.db.pgsql import get_write_db
from app.config.settings import settings
from app.tracing import TraceSpan

logger = logging.getLogger(__name__)

ANALYST_BINDING = "tool.structured_data.analyst"
TABLE_SELECT_BINDING = "tool.structured_data.table_select"
TABLE_SELECT_THRESHOLD = 5
MAX_ANALYST_STEPS = 20
MAX_EXPLORE_VALUES = 100


class StructuredQueryInput(BaseModel):
    """Input schema for structured data query tool."""

    question: str = Field(..., description="The natural language question about the data")
    table_name: Optional[str] = Field(
        default=None,
        description="Specific table name to query. If provided, skips automatic table selection.",
    )
    context: Optional[str] = Field(
        default=None,
        description="Additional context (agent/user instructions) to improve table selection and SQL generation",
    )
    max_rows: Optional[int] = Field(
        default=2000,
        description="Maximum rows to return",
    )


def _extract_sql_from_response(content: str) -> Optional[str]:
    """Extract SQL from LLM response, handling markdown code fences."""
    if not content or not content.strip():
        return None
    content = content.strip()
    # Match ```sql ... ``` or ``` ... ```
    match = re.search(r"```(?:sql)?\s*\n?(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # No fence - assume entire content is SQL
    return content.strip()


def _validate_select_only(sql: str) -> bool:
    """Ensure the SQL is SELECT-only (no DML/DDL/admin commands)."""
    stripped = sql.strip()

    # Block semicolons (query stacking)
    if ";" in stripped:
        return False

    # Block SQL comments that could hide dangerous keywords
    if "--" in stripped or "/*" in stripped:
        return False

    upper = stripped.upper()
    if not upper.startswith("SELECT"):
        return False

    dangerous = [
        "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE",
        "COPY", "EXECUTE", "GRANT", "REVOKE", "SET", "RESET", "DO", "CALL",
        "PERFORM", "RAISE", "LISTEN", "NOTIFY", "VACUUM", "ANALYZE",
        "EXPLAIN", "LOCK", "COMMENT",
    ]
    for kw in dangerous:
        if re.search(rf"\b{kw}\b", upper):
            return False
    return True


MAX_RESULT_ROWS_IN_META = 2000


def _serialize_results(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert query results into a JSON-safe structure for the frontend.
    Returns ``{columns: [...], rows: [[...], ...]}``."""
    if not rows:
        return {"columns": [], "rows": []}
    columns = list(rows[0].keys())
    serialized = []
    for row in rows[:MAX_RESULT_ROWS_IN_META]:
        serialized.append([
            str(v) if v is not None else None
            for v in row.values()
        ])
    return {"columns": columns, "rows": serialized}


def _format_results_as_table(rows: List[Dict[str, Any]]) -> str:
    """Format list of dicts as a markdown table so the LLM can echo it verbatim."""
    if not rows:
        return "(No rows returned)"
    headers = list(rows[0].keys())
    header_line = "| " + " | ".join(str(h) for h in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
    data_lines = []
    for row in rows:
        cells = []
        for h in headers:
            val = row.get(h, "")
            s = str(val) if val is not None else "NULL"
            if len(s) > 60:
                s = s[:57] + "..."
            cells.append(s)
        data_lines.append("| " + " | ".join(cells) + " |")
    return "\n".join([header_line, sep_line] + data_lines)


class StructuredDataQueryTool:
    """
    Tool that enables agents to query structured tabular data (CSV/Excel) stored
    in per-KB PostgreSQL schemas via natural language questions.

    When the KB has more than TABLE_SELECT_THRESHOLD tables, a lightweight
    table-selection LLM call narrows the schema before SQL generation so the
    SQL model only sees the relevant tables.  Callers (or users) can bypass
    selection entirely by providing an explicit ``table_name``.
    """

    def __init__(
        self,
        kb_id: str,
        kb_name: str,
        schema_name: str,
        semantic_model: str,
    ):
        self.kb_id = kb_id
        self.kb_name = kb_name or kb_id
        self.schema_name = schema_name
        self.semantic_model = semantic_model

        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", self.kb_name.lower())
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        self.name = f"query_{sanitized}"[:128]

        # Pre-parse the semantic model into per-table sections (cached).
        self._table_sections, self._relationships_text = self._parse_table_sections()
        self._table_summary = self._build_table_summary()

        self.description = (
            f"Query structured tabular data (CSV/Excel) stored in the '{self.kb_name}' knowledge base. "
            "Use this tool when the user asks about numbers, statistics, trends, comparisons, "
            "or any data analysis question. The tool autonomously selects the right tables, "
            "explores the data, runs SQL queries, and returns complete results with units. "
            "You can optionally pass a table_name hint or additional context."
        )

    # ------------------------------------------------------------------
    # Schema parsing helpers (run once in __init__)
    # ------------------------------------------------------------------

    def _parse_table_sections(self) -> Tuple[Dict[str, str], str]:
        """Split the semantic model into ``{table_name: block}`` and a
        relationships block so we can reassemble a filtered schema later."""
        sections: Dict[str, str] = {}
        current_table: Optional[str] = None
        current_lines: List[str] = []
        rel_lines: List[str] = []
        in_relationships = False

        for line in self.semantic_model.split("\n"):
            if line.startswith("Table: "):
                if current_table:
                    sections[current_table] = "\n".join(current_lines)
                table_part = line[len("Table: "):]
                current_table = table_part.split(" - ")[0].strip()
                current_lines = [line]
                in_relationships = False
            elif line.startswith("Relationships"):
                if current_table:
                    sections[current_table] = "\n".join(current_lines)
                    current_table = None
                in_relationships = True
                rel_lines.append(line)
            elif in_relationships:
                rel_lines.append(line)
            elif current_table is not None:
                current_lines.append(line)

        if current_table:
            sections[current_table] = "\n".join(current_lines)

        return sections, "\n".join(rel_lines).strip()

    def _build_table_summary(self) -> str:
        """Concise one-line-per-table summary for the table selector prompt."""
        if not self._table_sections:
            return ""
        lines: List[str] = []
        for idx, (name, block) in enumerate(self._table_sections.items(), 1):
            first_line = block.split("\n")[0]
            desc = first_line.split(" - ", 1)[1].strip() if " - " in first_line else ""
            col_names: List[str] = []
            for bline in block.split("\n"):
                stripped = bline.strip()
                if stripped.startswith("- ") and "(" in stripped:
                    col_names.append(stripped[2:].split(" (")[0].strip())
            cols = ", ".join(col_names) if col_names else "no columns"
            lines.append(f"{idx}. {name} — {desc} (columns: {cols})")
        return "\n".join(lines)

    def _filter_relationships(self, selected_tables: List[str]) -> str:
        """Return only the relationship lines that reference selected tables."""
        if not self._relationships_text:
            return ""
        selected = set(selected_tables)
        kept: List[str] = ["Relationships (for JOINs):"]
        for line in self._relationships_text.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            if any(t in stripped for t in selected):
                kept.append(f"  {stripped}")
        return "\n".join(kept) if len(kept) > 1 else ""

    def _build_filtered_schema(self, selected_tables: List[str]) -> str:
        """Reassemble the semantic model with only the selected tables."""
        parts: List[str] = ["Database Schema for Knowledge Base:\n"]
        for name in selected_tables:
            block = self._table_sections.get(name)
            if block:
                parts.append(block)
                parts.append("")
        rels = self._filter_relationships(selected_tables)
        if rels:
            parts.append(rels)
        return "\n".join(parts).strip()

    # ------------------------------------------------------------------
    # Table selection
    # ------------------------------------------------------------------

    async def _select_relevant_tables(
        self, question: str, context: str = "",
    ) -> List[str]:
        """Use a fast LLM call to pick only the tables needed for *question*.

        Skipped when the number of tables is at or below TABLE_SELECT_THRESHOLD.
        """
        table_names = list(self._table_sections.keys())
        if len(table_names) <= TABLE_SELECT_THRESHOLD:
            return table_names

        context_block = f"\nAdditional context:\n{context[:3000]}\n" if context else ""

        prompt = (
            "You are a database expert. Given a natural language question and a "
            "list of available tables, select the table(s) needed to answer the "
            "question.\n\n"
            f"Available tables:\n{self._table_summary}\n"
            f"{context_block}\n"
            f"Question: {question}\n\n"
            "Rules:\n"
            "- Select ONLY the tables needed to answer the question.\n"
            "- If the question requires JOINs across tables, include all tables involved.\n"
            "- Return ONLY a JSON array of table names, e.g. [\"table1\", \"table2\"].\n"
            "- When in doubt, include a table rather than omit it.\n"
        )

        try:
            from langchain_core.messages import HumanMessage
            from app.config.llm_config import LLMClientManager
            from app.llm.registry import LlmModelRegistry

            llm = LLMClientManager.get_client(
                model=LlmModelRegistry.get_primary(TABLE_SELECT_BINDING),
                temperature=0.0,
                max_tokens=512,
                binding_key=TABLE_SELECT_BINDING,
                llm_role="table_select",
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)
            cleaned = (content or "").strip()
            fence = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
            if fence:
                cleaned = fence.group(1).strip()
            tables = json.loads(cleaned)
            if isinstance(tables, list):
                valid = [t for t in tables if t in self._table_sections]
                if valid:
                    logger.debug("📊 Table selector chose %d/%d tables: %s",
                                 len(valid), len(table_names), valid)
                    return valid
        except Exception as exc:
            logger.warning("Table selection failed (%s), using all tables", exc)

        return table_names

    def _resolve_tables(self, table_name: Optional[str]) -> Optional[List[str]]:
        """Resolve an explicit *table_name* to matching section keys.

        Returns ``None`` when no match is found (caller should fall back to
        automatic selection).
        """
        if not table_name:
            return None
        if table_name in self._table_sections:
            return [table_name]
        lower = table_name.lower()
        matches = [t for t in self._table_sections if lower in t.lower()]
        return matches if matches else None

    # ------------------------------------------------------------------
    # Core search — autonomous analyst agent
    # ------------------------------------------------------------------

    async def search(
        self,
        question: str,
        table_name: Optional[str] = None,
        context: Optional[str] = None,
        max_rows: int = 2000,
    ) -> Dict[str, Any]:
        """Answer a data question by running an autonomous analyst agent.

        The agent internally iterates: explore columns → understand data
        vocabulary → generate SQL → execute → query more tables if needed.
        """
        async with TraceSpan(
            "structured_data",
            label=f"Structured Data Analyst: {self.kb_name}",
            payload={
                "kb_id": self.kb_id,
                "kb_name": self.kb_name,
                "table_name": table_name,
                "question": question,
            },
        ) as span:
            try:
                explicit = self._resolve_tables(table_name)
                if explicit:
                    selected_tables = explicit
                    logger.debug("Explicit table(s): %s", selected_tables)
                else:
                    if table_name:
                        logger.debug("No exact match for '%s', falling back to auto-select", table_name)
                    selected_tables = await self._select_relevant_tables(question, context or "")
                    logger.debug("Auto-selected table(s): %s", selected_tables)

                filtered_schema = self._build_filtered_schema(selected_tables)
                span.add_payload(selected_tables=selected_tables)

                result = await self._run_analyst_agent(
                    question, context or "", selected_tables, filtered_schema, max_rows,
                )
                span.add_payload(
                    row_count=result.get("row_count", 0),
                    query_count=len(result.get("queries_executed") or []),
                )
                return result
            except Exception as e:
                logger.error("Structured data query error: %s", e, exc_info=True)
                span.add_payload(error=str(e))
                return {"text": f"Error: {str(e)}", "sql": "", "row_count": 0}

    # ------------------------------------------------------------------
    # Analyst agent internals
    # ------------------------------------------------------------------

    async def _run_analyst_agent(
        self,
        question: str,
        context: str,
        selected_tables: List[str],
        filtered_schema: str,
        max_rows: int,
    ) -> Dict[str, Any]:
        """Multi-step ReAct agent that explores and queries the database."""
        observations: List[str] = []
        queries_executed: List[Dict] = []
        tables_touched: set = set()
        explored_cache: Dict[str, str] = {}
        units: str = ""
        self._last_validated_units = ""
        validated_once = False
        for step in range(1, MAX_ANALYST_STEPS + 1):
            prompt = self._build_analyst_prompt(
                question, context, filtered_schema, selected_tables, observations,
            )
            action = await self._call_analyst_llm(prompt)
            if action is None:
                observations.append(f"Step {step}: [ERROR] Could not parse agent action, stopping.")
                break

            action_type = action.get("action", "")
            logger.debug("Analyst step %d: %s", step, action_type)

            if action_type == "explore":
                tbl = action.get("table", "")
                col = action.get("column", "")
                filt = action.get("filter", "")
                if tbl not in self._table_sections:
                    observations.append(f"Step {step}: [EXPLORE] {tbl}.{col} → table not found")
                    continue
                tables_touched.add(tbl)
                cache_key = f"{tbl}.{col}:{filt}"
                if cache_key in explored_cache:
                    observations.append(
                        f"Step {step}: [EXPLORE] {tbl}.{col} → ALREADY EXPLORED (same results as before). "
                        "Do NOT repeat. Try a different column, a different table, use a filter, or run a query."
                    )
                    continue
                vals = await self._execute_explore(tbl, col, filt)
                explored_cache[cache_key] = vals
                observations.append(f"Step {step}: [EXPLORE] {tbl}.{col}{f' (filter={filt})' if filt else ''} → {vals}")

            elif action_type == "query":
                sql = action.get("sql", "").strip()
                if not sql or not _validate_select_only(sql):
                    observations.append(f"Step {step}: [QUERY] rejected (invalid SQL)")
                    continue
                exec_result = await self._execute_sql(sql, max_rows)
                used = [t for t in selected_tables if t.lower() in sql.lower()]
                tables_touched.update(used or selected_tables)

                if exec_result["error"]:
                    observations.append(
                        f"Step {step}: [QUERY] {sql}\n→ ERROR: {exec_result['error']}"
                    )
                else:
                    n = exec_result["row_count"]
                    fmt = _format_results_as_table(exec_result["results"][:20])
                    observations.append(f"Step {step}: [QUERY] {sql}\n→ {n} rows:\n{fmt}")
                    queries_executed.append({
                        "sql": sql,
                        "row_count": n,
                        "tables_used": used or list(selected_tables),
                        "results": _serialize_results(exec_result["results"]),
                    })

            elif action_type == "done":
                units = action.get("units", "") or units
                observations.append(
                    f"Step {step}: [DONE] {action.get('summary', 'Analysis complete')}"
                )

                if not validated_once and step < MAX_ANALYST_STEPS:
                    feedback = await self._validate_results(
                        question, filtered_schema, queries_executed,
                    )
                    validated_once = True
                    units = self._last_validated_units or units
                    if feedback:
                        observations.append(
                            f"Step {step}: [VALIDATION FAILED] {feedback} — continue querying."
                        )
                        logger.info("Validation gap detected, resuming agent loop: %s", feedback)
                        continue
                break

        units = units or self._last_validated_units

        return self._compile_agent_results(
            question, observations, queries_executed,
            list(tables_touched or selected_tables), units,
        )

    def _build_analyst_prompt(
        self,
        question: str,
        context: str,
        schema: str,
        selected_tables: List[str],
        observations: List[str],
    ) -> str:
        """Build the ReAct prompt for the analyst agent."""
        obs_block = ""
        if observations:
            obs_block = "\n\n## Previous Steps\n" + "\n\n".join(observations)

        context_block = ""
        if context:
            context_block = f"\n\n## Supervisor Instructions\n{context[:3000]}"

        return f"""You are an autonomous data analyst agent. Your job is to FULLY answer a data question by exploring and querying a PostgreSQL database. Work step by step.

## Database Schema
{schema}
{context_block}

## User Question
{question}

## Available Actions
Return ONLY a single JSON object choosing ONE action:

1. Explore a column to see its distinct values (do this FIRST for key columns like country, metric, service, region):
   {{"action": "explore", "table": "table_name", "column": "column_name"}}
   To SEARCH within a column (useful when many values exist), add a filter:
   {{"action": "explore", "table": "table_name", "column": "column_name", "filter": "search_term"}}

2. Execute a SQL query to retrieve data:
   {{"action": "query", "sql": "SELECT ..."}}

3. Signal that you have enough data:
   {{"action": "done", "summary": "Brief description of data collected", "units": "unit of the numeric values, e.g. USD millions"}}

## Rules

### Data Exploration
- ALWAYS explore key categorical columns BEFORE writing queries so you know the exact values (e.g. is it 'Saudi Arabia' or 'KSA'?)
- Use explored values EXACTLY as they appear — case-sensitive, exact spelling
- If a column has many values and you can't find the one you need, use the "filter" parameter: {{"action": "explore", "table": "...", "column": "country", "filter": "saudi"}}
- NEVER explore the same table+column combination twice — you will get the same result. If the value wasn't there, use filter or try a different approach
- If you've explored a table's key columns and the data you need isn't there, that table likely doesn't have it. Move on — issue a "done" with whatever you found rather than retrying

### Units (CRITICAL)
- The column descriptions in the schema above contain unit information (e.g. "Revenue in USD millions", "Subscribers in thousands", "Price per MB in USD")
- You MUST read these descriptions and identify the unit for every numeric column you query
- Include the unit in your "done" summary and in column aliases (e.g. SELECT revenue AS revenue_usd_millions)

### Computation (CRITICAL)
- If the user asks for a derived metric — percentage difference, growth rate, ratio, year-over-year change, average, comparison — you MUST compute it directly in SQL
- NEVER return raw values and expect someone else to calculate. Examples:
  - Percentage difference: (a - b) / NULLIF(b, 0) * 100 AS pct_difference
  - Growth rate: (new - old) / NULLIF(old, 0) * 100 AS growth_rate_pct
  - Ratio: a / NULLIF(b, 0) AS ratio
- Include both the raw values AND the computed metric in the same query

### Business Logic (CRITICAL)
- Read the schema column descriptions carefully to understand what each metric MEANS
- Check if metrics are SUBSETS of each other before presenting or summing them.
  Example: "Communications Market" is often a subset of "ICT Market" — presenting them as separate additive items is WRONG.
  Read the column descriptions to determine relationships.
- NEVER sum metrics that overlap or have a parent-child relationship
- When unsure, present metrics individually with clear labels rather than computing misleading totals

### Completeness Check (before choosing "done")
- Re-read the user question and verify against your collected results:
  (a) ALL requested data points are present
  (b) ALL requested calculations/transformations are computed in the SQL results
  (c) Units are identified from the schema descriptions
  (d) No double-counting or misleading aggregations
- If ANYTHING is missing or wrong, issue another query instead of saying done

### Schema (CRITICAL)
- Tables are already in the search path. NEVER prefix table names with a schema (e.g. do NOT write public."table" or any_schema."table")
- Use bare table names exactly as shown in the Database Schema section (e.g. FROM "table_name")
- If you need to discover or list tables, query information_schema with table_schema = '{self.schema_name}' — NEVER filter on 'public'

### General
- If the question spans multiple tables (e.g. mobile + fixed revenue), query EACH table
- If a query returns an error, read the error and fix the SQL
- If a query returns 0 rows, explore the relevant columns to find correct filter values
- Column names are lowercase identifiers — use them unquoted
- Maximum {MAX_ANALYST_STEPS} total steps — be efficient
- Return ONLY the JSON action, nothing else
{obs_block}

## Your Next Action"""

    async def _call_analyst_llm(self, prompt: str) -> Optional[Dict]:
        """Call the analyst LLM and parse the JSON action."""
        try:
            from langchain_core.messages import HumanMessage
            from app.config.llm_config import LLMClientManager
            from app.llm.registry import LlmModelRegistry

            llm = LLMClientManager.get_client(
                model=LlmModelRegistry.get_primary(ANALYST_BINDING),
                temperature=0.0,
                max_tokens=1024,
                binding_key=ANALYST_BINDING,
                llm_role="data_analyst",
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = (response.content if hasattr(response, "content") else str(response)).strip()

            fence = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
            if fence:
                content = fence.group(1).strip()

            # Extract the first JSON object from the response
            brace_start = content.find("{")
            if brace_start == -1:
                return None
            depth, end = 0, brace_start
            for i in range(brace_start, len(content)):
                if content[i] == "{":
                    depth += 1
                elif content[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            return json.loads(content[brace_start:end])
        except Exception as exc:
            logger.warning("Analyst LLM call failed: %s", exc)
            return None

    async def _execute_explore(self, table: str, column: str, filter_term: str = "") -> str:
        """Run SELECT DISTINCT on a column and return a summary of values.

        When *filter_term* is provided, results are filtered with ILIKE so the
        agent can search for specific values (e.g. 'saudi') without needing to
        page through all distinct values.
        """
        safe_col = re.sub(r"[^a-z0-9_]", "", column.lower())
        if filter_term:
            safe_filter = filter_term.replace("'", "''")
            sql = (
                f'SELECT DISTINCT {safe_col} FROM "{table}" '
                f"WHERE CAST({safe_col} AS TEXT) ILIKE '%{safe_filter}%' "
                f"ORDER BY {safe_col} LIMIT {MAX_EXPLORE_VALUES}"
            )
        else:
            sql = f'SELECT DISTINCT {safe_col} FROM "{table}" ORDER BY {safe_col} LIMIT {MAX_EXPLORE_VALUES}'
        result = await self._execute_sql(sql, MAX_EXPLORE_VALUES)
        if result["error"]:
            return f"Error: {result['error']}"
        vals = [str(list(r.values())[0]) for r in result["results"] if list(r.values())[0] is not None]
        n = len(vals)
        preview = ", ".join(vals[:30])
        if n > 30:
            preview += f", ... ({n} total)"
        return f"{n} distinct values: {preview}"

    async def _execute_sql(self, sql: str, max_rows: int) -> Dict[str, Any]:
        """Execute SQL and return results or error info."""
        try:
            async for db_session in get_write_db():
                repo = StructuredDataRepository(db_session)
                results = await repo.execute_query(
                    self.schema_name, sql, timeout_seconds=30, max_rows=max_rows,
                )
                return {"results": results, "row_count": len(results), "error": None}
        except Exception as e:
            return {"results": [], "row_count": 0, "error": str(e)}

    async def _validate_results(
        self,
        question: str,
        schema: str,
        queries_executed: List[Dict],
    ) -> Optional[str]:
        """Check whether collected results fully satisfy the question.

        Returns ``None`` if everything looks good, or a feedback string
        describing what is missing so the agent loop can continue.
        """
        if not queries_executed:
            return "No queries have been executed yet. You need to query the data."

        results_summary_parts: List[str] = []
        for idx, qe in enumerate(queries_executed, 1):
            cols = qe["results"].get("columns", [])
            rows = qe["results"].get("rows", [])
            n = qe["row_count"]
            data_preview = ""
            if rows:
                preview_rows = rows[:15]
                data_preview = f"\n  Data (first {len(preview_rows)} rows):\n"
                for r in preview_rows:
                    data_preview += f"    {r}\n"
            results_summary_parts.append(
                f"Query {idx}: {qe['sql']}\n  → {n} rows, columns: {cols}{data_preview}"
            )
        results_summary = "\n".join(results_summary_parts)

        prompt = f"""You are a QA reviewer for a data analyst agent. Given the user question, the database schema, and the queries + results already executed, determine if the results are CORRECT and COMPLETE.

## User Question
{question}

## Database Schema (read column descriptions for units)
{schema[:6000]}

## Queries Executed & Results
{results_summary}

## Check these criteria (ALL must pass)

### 1. BUSINESS LOGIC & SEMANTIC CORRECTNESS
- Look at the actual result data above. Do the numbers make sense given the column descriptions?
- Are any metrics SUBSETS of each other? For example, "Communications Market" is typically a subset of "ICT Market" — they should NOT be summed together for a "total". Check the schema descriptions carefully.
- Is there any double-counting risk? If two columns represent overlapping or hierarchical metrics, flag it.
- Do the aggregations (SUM, AVG, etc.) make semantic sense for the type of metric?

### 2. UNITS
- Are the units of numeric columns identifiable from the schema descriptions? If so, what are they?
- Are different metrics being compared using consistent units?

### 3. CALCULATIONS
- Did the user ask for any derived metric (percentage difference, growth rate, ratio, comparison)? If yes, was it computed directly in the SQL?

### 4. COMPLETENESS
- Does the data cover everything the user asked for (all countries, years, metrics mentioned)?

## Response format
Return ONLY a JSON object:
- If everything is satisfied: {{"pass": true, "units": "the units from schema descriptions, e.g. USD billions"}}
- If something is wrong: {{"pass": false, "feedback": "Specific description of the issue — e.g. double-counting, missing calculation, wrong interpretation. Tell the agent exactly what to fix.", "units": "units if identifiable, otherwise empty string"}}"""

        try:
            from langchain_core.messages import HumanMessage
            from app.config.llm_config import LLMClientManager
            from app.llm.registry import LlmModelRegistry

            llm = LLMClientManager.get_client(
                model=LlmModelRegistry.get_primary(ANALYST_BINDING),
                temperature=0.0,
                max_tokens=512,
                binding_key=ANALYST_BINDING,
                llm_role="data_analyst",
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = (response.content if hasattr(response, "content") else str(response)).strip()

            fence = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
            if fence:
                content = fence.group(1).strip()

            brace_start = content.find("{")
            if brace_start == -1:
                return None
            depth, end = 0, brace_start
            for i in range(brace_start, len(content)):
                if content[i] == "{":
                    depth += 1
                elif content[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            result = json.loads(content[brace_start:end])
            self._last_validated_units = result.get("units", "")

            if result.get("pass"):
                return None
            return result.get("feedback", "Validation failed — re-check the question.")
        except Exception as exc:
            logger.warning("Validation LLM call failed: %s", exc)
            return None

    @staticmethod
    def _compile_agent_results(
        question: str,
        observations: List[str],
        queries_executed: List[Dict],
        tables_used: List[str],
        units: str = "",
    ) -> Dict[str, Any]:
        """Combine results from all agent queries into the tool return value."""
        if not queries_executed:
            return {
                "text": "(No data retrieved)\n\nAgent log:\n" + "\n".join(observations),
                "sql": "",
                "row_count": 0,
                "tables_used": tables_used,
                "results": {"columns": [], "rows": []},
                "queries_executed": [],
                "units": units,
            }

        text_parts: List[str] = []
        total_rows = 0
        for qe in queries_executed:
            r = qe["results"]
            total_rows += qe["row_count"]
            if r["columns"] and r["rows"]:
                header = "| " + " | ".join(r["columns"]) + " |"
                sep = "| " + " | ".join("---" for _ in r["columns"]) + " |"
                rows = [
                    "| " + " | ".join(str(v) if v is not None else "NULL" for v in row) + " |"
                    for row in r["rows"]
                ]
                text_parts.append(f"{header}\n{sep}\n" + "\n".join(rows))

        tables_note = f"(queried table(s): {', '.join(tables_used)})"
        units_note = f"\n(units: {units})" if units else ""
        combined_text = (
            ("\n\n".join(text_parts) + "\n" + tables_note + units_note)
            if text_parts
            else tables_note + units_note
        )

        first_results = queries_executed[0]["results"] if queries_executed else {"columns": [], "rows": []}
        last_sql = queries_executed[-1]["sql"] if queries_executed else ""

        return {
            "text": combined_text,
            "sql": last_sql,
            "row_count": total_rows,
            "tables_used": tables_used,
            "results": first_results,
            "queries_executed": queries_executed,
            "units": units,
        }

    def as_langchain_tool(self):
        try:
            from langchain_core.tools import StructuredTool
        except ImportError:
            from langchain.tools import StructuredTool

        return StructuredTool.from_function(
            name=self.name,
            description=self.description,
            func=self.search,
            coroutine=self.search,
            args_schema=StructuredQueryInput,
            return_direct=False,
        )

    def as_openai_function(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The natural language question about the data",
                    },
                    "table_name": {
                        "type": "string",
                        "description": "Specific table name to query (optional, skips auto-selection)",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context to improve table selection",
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Maximum rows to return",
                        "default": 100,
                    },
                },
                "required": ["question"],
            },
        }


async def create_structured_data_tool(
    kb_id: str,
    kb_name: str = None,
) -> Optional[StructuredDataQueryTool]:
    """
    Factory function to create the structured data query tool.

    Args:
        kb_id: Knowledge base ID
        kb_name: Optional display name for the KB

    Returns:
        StructuredDataQueryTool instance or None if no structured tables exist
    """
    if not kb_id:
        return None

    from app.services.structured_data_service import StructuredDataService

    result_tool = None
    try:
        async for db_session in get_write_db():
            try:
                structured_repo = StructuredDataRepository(db_session)
                service = StructuredDataService(db_session, structured_repo)
                semantic_model = await service.get_semantic_model(kb_id)
                if not semantic_model or not semantic_model.strip():
                    logger.debug("No structured tables for KB %s; skipping tool", kb_id)
                    return None

                schema_name = f"kb_data_{kb_id[:8]}"
                display_name = kb_name or kb_id
                result_tool = StructuredDataQueryTool(
                    kb_id=kb_id,
                    kb_name=display_name,
                    schema_name=schema_name,
                    semantic_model=semantic_model,
                )
                logger.info("Created structured data tool: %s for KB %s", result_tool.name, kb_id)
            finally:
                break
    except Exception as e:
        logger.error("Error creating structured data tool: %s", e, exc_info=True)
        return None

    return result_tool
