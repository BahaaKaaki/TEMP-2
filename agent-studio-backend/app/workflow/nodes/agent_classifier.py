"""
Tool Caller / Action Router for multi-agent workflows.

A lightweight LLM (GPT-5.4 mini) that runs at the start of each agent iteration to
decide what should happen next (before the Main LLM when chat is needed):
- CHAT:               return the agent's text to the user
- SEARCH_KB:          execute a KB search with a specific query
- DEEP_RESEARCH:      execute deep research with a specific query
- SUBMIT_DELIVERABLE: trigger the Main LLM to produce its structured output

The Tool Caller only sees summarized/truncated context (~5K chars) so it
always has a small, reliable context window for tool-calling decisions.

Also retains the legacy ``classify_readiness`` helper for backward compat.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from config.llm_config import LLMClientManager
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


def _extract_text_content(content) -> str:
    """Normalise LLM response content that may be a list of blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts).strip()
    return str(content).strip()


TOOL_CALLER_BINDING = "tool.tool_caller"
TOOL_CALLER_PROVIDER = "openai"
TOOL_CALLER_TEMPERATURE = 0.0
TOOL_CALLER_MAX_TOKENS = 1024


def get_tool_caller_model() -> str:
    """Resolved tool-caller model from the unified LLM catalog."""
    from app.llm.registry import LlmModelRegistry
    return LlmModelRegistry.get_primary(TOOL_CALLER_BINDING)


def __getattr__(name: str):
    """Backward compatibility for removed module-level model constants."""
    if name == "TOOL_CALLER_MODEL":
        return get_tool_caller_model()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# ---------------------------------------------------------------------------
# Tool Caller / Action Router
# ---------------------------------------------------------------------------

def _build_router_system_prompt(available_tools: List[str]) -> str:
    """Build the system prompt dynamically based on available tools.

    Only presents actions whose backing tools actually exist so the LLM
    never picks an unavailable action like ``deep_research``.
    """
    has_deep_research = "deep_research" in (available_tools or [])
    has_web_search = "simple_web_search" in (available_tools or [])
    has_ask_questions = "ask_user_questions" in (available_tools or [])

    action_num = 1
    actions = []

    actions.append(
        f"{action_num}. The agent is chatting / asking questions / needs more user input:\n"
        f'   {{"action": "chat"}}'
    )
    action_num += 1

    if has_ask_questions:
        actions.append(
            f"{action_num}. The agent should ask the user a STRUCTURED multi-question "
            f"form (rendered inline in chat as a card with picker options + an "
            f"optional free-form 'Other' input). Use this when the agent's "
            f"natural intent is to ask 2 or more short questions in a row, "
            f"especially when each can be answered by picking from a few sensible "
            f"defaults (e.g. industry, country, scope, preferences):\n"
            f'   {{"action": "ask_user_questions"}}'
        )
        action_num += 1

    actions.append(
        f"{action_num}. The agent should search the knowledge base for information:\n"
        f'   {{"action": "search_kb", "query": "the specific search query"}}\n'
        f"   If the agent or user mentions a SPECIFIC FILE NAME (e.g. \"reasons3.txt\",\n"
        f"   \"report.pdf\"), you MUST include document_name to restrict the search:\n"
        f'   {{"action": "search_kb", "query": "...", "document_name": "reasons3.txt"}}\n'
        f"   If metadata filters are available you may optionally add:\n"
        f'   {{"action": "search_kb", "query": "...", "metadata_filters": [{{"field": "name", "operator": "eq|neq|gt|gte|lt|lte|like", "value": "..."}}]}}'
    )
    action_num += 1

    actions.append(
        f"{action_num}. The agent should query structured tabular data (CSV/Excel tables):\n"
        f'   {{"action": "query_structured_data", "question": "the natural language question about the data"}}\n'
        f"   If the user or agent mentions a SPECIFIC TABLE NAME, include it:\n"
        f'   {{"action": "query_structured_data", "question": "...", "table_name": "the_table_name"}}\n'
        f"   Use this when the question is about specific data points, aggregations, or filtering from uploaded CSV/Excel tables."
    )
    action_num += 1

    if has_deep_research:
        actions.append(
            f"{action_num}. The agent should perform deep research on a topic:\n"
            f'   {{"action": "deep_research", "query": "the specific research query"}}'
        )
        action_num += 1

    if has_web_search:
        actions.append(
            f"{action_num}. The agent should search the web for current information:\n"
            f'   {{"action": "simple_web_search", "query": "the specific search query"}}\n'
            f"   Use this for quick factual lookups, recent events, or up-to-date\n"
            f"   information not available in the knowledge base."
        )
        action_num += 1

    actions.append(
        f"{action_num}. The agent has gathered enough information and should produce its\n"
        f"   structured deliverable now:\n"
        f'   {{"action": "submit_deliverable", "reason": "brief reason"}}'
    )

    actions_block = "\n\n".join(actions)

    deep_research_tool_rule = (
        '- Choose "deep_research" when the agent needs in-depth external research.\n'
        '  IMPORTANT: If deep_research is available and has NOT been used yet,\n'
        '  it should almost always be the first action for user questions.\n'
        if has_deep_research else ""
    )
    web_search_tool_rule = (
        '- Choose "simple_web_search" for quick factual lookups, recent events,\n'
        "  or when the agent needs current information from the open web.\n"
        "  Prefer this over deep_research for straightforward questions.\n"
        if has_web_search else ""
    )
    deep_research_after_tool = (
        " or deep_research" if has_deep_research else ""
    )

    ask_questions_priority_rule = ""
    if has_ask_questions:
        ask_questions_priority_rule = (
            "ABSOLUTE TOP PRIORITY — Structured questionnaire over plain-text "
            "questions (this rule OVERRIDES every \"choose chat\" rule below):\n"
            "- Both `ask_user_questions` and `chat` pause the workflow and wait\n"
            "  for the user's reply. The choice between them is NOT about whether\n"
            "  to pause — it's about HOW the user answers. If the agent's most\n"
            "  recent message is asking the user for input, you MUST choose\n"
            '  "ask_user_questions" whenever the rule below applies.\n'
            "- TRIGGER: If the agent's most recent AI message asks the user for\n"
            "  TWO OR MORE distinct pieces of input (numbered list, bullet list,\n"
            "  or comma-separated request like \"please provide A, B, C, and D\"),\n"
            "  AND the user has NOT yet provided that input,\n"
            '  → you MUST choose {"action": "ask_user_questions"}. Never "chat".\n'
            "- This applies even when the answers are FREE-FORM TEXT (e.g. names,\n"
            "  descriptions, project asks). The tool supports type='text' for\n"
            "  open-ended answers and allow_other=true for picker fallbacks. Do\n"
            "  not skip the tool just because the answers aren't multiple-choice.\n"
            "- The rationale \"the agent should wait for the user's reply\" does\n"
            "  NOT justify choosing chat when this trigger fires —\n"
            "  ask_user_questions also waits for the reply.\n"
            "- EXCEPTIONS where chat is still correct:\n"
            "  * The agent's last message asks ONE single follow-up only (e.g.\n"
            "    \"can you elaborate?\", \"what year?\").\n"
            "  * The agent is presenting tool results, summarizing, or confirming\n"
            "    — not gathering new input.\n"
            "  * The user has just submitted a question response and the agent\n"
            "    is acknowledging it.\n"
            "- DO NOT use ask_user_questions to confirm, summarize, or wrap up\n"
            "  (use chat or submit_deliverable for those).\n\n"
        )

    deep_research_priority_rule = ""
    if has_deep_research:
        deep_research_priority_rule = (
            "HIGH PRIORITY — Proactive deep research (when deep_research tool is available):\n"
            '- If the conversation contains NO "[Tool result from ...]" messages AND\n'
            "  the user is asking a substantive question that requires research,\n"
            '  you MUST choose "deep_research" with a comprehensive query derived\n'
            "  from the user's request.\n"
            "- Deep research should be your FIRST action for any open-ended or\n"
            "  knowledge-intensive question when no research has been done yet.\n"
            '- Do NOT choose "chat" when the agent answered from general knowledge\n'
            "  but deep_research has not been used yet. Route to deep_research\n"
            "  so the agent can provide well-researched, cited information.\n"
            "- This takes priority over search_kb for broad research questions.\n\n"
        )

    return (
        "You are an action router for a multi-agent workflow system.\n\n"
        "Given an agent's task description, required output schema, available tools,\n"
        "and the recent conversation, decide what the agent should do NEXT.\n\n"
        "Respond with ONLY a JSON object (no markdown, no extra text). Pick exactly\n"
        "one action:\n\n"
        f"{actions_block}\n\n"
        "DECISION GUIDELINES (in priority order):\n\n"
        f"{ask_questions_priority_rule}"
        "HIGHEST PRIORITY — User explicitly confirms or requests output:\n"
        "- If the user's latest message indicates they are satisfied and want the\n"
        '  deliverable (e.g. "provide the output", "looks good proceed", "that\'s\n'
        '  what I need", "go ahead", "submit", "finalize"), choose\n'
        '  "submit_deliverable" IMMEDIATELY. Do NOT search again or chat further.\n'
        "- ALSO treat soft confirmations as approval when the agent has already\n"
        "  presented data and the user responds positively. Examples of soft\n"
        '  confirmations: "this is good", "no this is good", "looks good",\n'
        '  "perfect", "great", "yes", "ok proceed", "that works", "correct",\n'
        '  "no changes needed". If the agent already showed the user gathered data\n'
        "  and the user's reply expresses satisfaction (even without explicitly\n"
        '  saying "submit"), choose "submit_deliverable".\n\n'
        "HIGH PRIORITY — Proactive KB search (no tool results in conversation yet):\n"
        '- If the conversation contains NO "[Tool result from ...]" messages AND\n'
        "  the user has provided ANY concrete input (a company name, industry,\n"
        "  topic, person, keyword, or question), choose \"search_kb\" with a\n"
        "  relevant query derived from the user's input.\n"
        '- Do NOT choose "chat" just because the agent responded with a clarifying\n'
        "  question or produced an empty response. If you can form ANY reasonable\n"
        "  search query from the user's input, always search first.\n"
        "- Even if the agent's workflow says to collect more context first, prefer\n"
        "  searching the KB proactively. The agent can refine after seeing results.\n"
        '- When in doubt between "chat" and "search_kb" and no search has been\n'
        '  done yet, ALWAYS prefer "search_kb", unless you need more info to perform a search\n\n'
        f"{deep_research_priority_rule}"
        "NORMAL PRIORITY — Deciding after tool results (no user confirmation yet):\n"
        '- NEVER choose "submit_deliverable" immediately after a tool execution\n'
        f"  (search_kb{deep_research_after_tool}) if the user has NOT yet reviewed the results.\n"
        '- If the most recent message is a tool result (e.g. "[Tool result from ...]"),\n'
        '  ALWAYS choose "chat" so the agent can present findings to the user.\n'
        "- If query_structured_data has ALREADY been executed and returned data,\n"
        '  choose "chat" to present the results. Do NOT follow up with search_kb\n'
        "  unless the instuctions requires or user asks for narrative/qualitative context.\n"
        "  The data results are sufficient — present them first.\n\n"
        "STANDARD RULES:\n"
        '- Choose "submit_deliverable" when the agent has enough data AND the user\n'
        "  has seen the results and confirmed (or not objected after reviewing).\n"
        '- Choose "query_structured_data" when the user asks about numbers,\n'
        "  statistics, totals, averages, filtering, ranking, counts, dates, KPIs,\n"
        "  or any quantitative question that can be answered from tabular data\n"
        "  (CSV/Excel tables). This translates the question into an SQL query.\n"
        "  This should be your FIRST choice for any data/numbers question.\n"
        '- Choose "search_kb" when the agent needs information from unstructured\n'
        "  documents (PDFs, Word docs, text files). This performs semantic/keyword\n"
        "  search across document chunks. Use for qualitative questions, finding\n"
        "  specific paragraphs, policy lookups, or any text-based retrieval.\n"
        "- If the knowledge base has BOTH structured tables AND unstructured\n"
        "  documents, decide based on the nature of the question:\n"
        "  * Quantitative / analytical / data questions → query_structured_data FIRST\n"
        "  * Qualitative / textual / evidence questions → search_kb\n"
        "  * Do NOT call search_kb before query_structured_data for data questions.\n"
        f"{deep_research_tool_rule}"
        f"{web_search_tool_rule}"
        '- Choose "chat" when:\n'
        "  * The agent is providing intermediate analysis or a single short\n"
        "    follow-up question.\n"
        + (
            "  * (Note: when the agent is asking for 2+ pieces of input, the\n"
            "    ABSOLUTE TOP PRIORITY rule above forces ask_user_questions —\n"
            "    do not pick chat in that case.)\n"
            if has_ask_questions else
            "  * The agent is asking the user questions.\n"
        )
        +
        "  * The agent just received tool results and should present them for review.\n"
        "  * The user has not yet confirmed the retrieved data is what they need.\n"
        "- If the agent's last response is empty or unclear, prefer \"chat\" so\n"
        "  the user can guide the agent.\n"
        '- When in doubt between "submit_deliverable" and "chat", AND the user\n'
        "  has NOT explicitly asked for the output, prefer \"chat\".\n"
    )


async def route_next_action(
    task_instructions: str,
    output_schema_summary: str,
    available_tools: List[str],
    recent_messages: List[str],
    provider: str = TOOL_CALLER_PROVIDER,
    model: Optional[str] = None,
    metadata_schema_desc: str = "",
    structured_data_desc: str = "",
) -> Dict[str, Any]:
    """Decide the next action for the agent.

    Args:
        task_instructions: The agent's systemInstructions (truncated).
        output_schema_summary: Stringified output schema or summary.
        available_tools: Names of tools available to this agent.
        recent_messages: Summarized recent messages (~5K chars max).
        provider: LLM provider for the router call.
        model: Model name for the router call.
        metadata_schema_desc: Human-readable description of available KB
            metadata fields so the router can include metadata_filters.
        structured_data_desc: Semantic model of structured tables available
            for querying. When present, data questions should be routed to
            query_structured_data.
    """
    conversation_text = "\n---\n".join(recent_messages[-10:])
    tools_text = ", ".join(available_tools) if available_tools else "none"

    metadata_section = ""
    if metadata_schema_desc and metadata_schema_desc.strip():
        metadata_section = (
            f"## KB Metadata Filters\n"
            f"When choosing search_kb you may optionally include metadata_filters.\n"
            f"{metadata_schema_desc.strip()}\n\n"
        )

    structured_section = ""
    if structured_data_desc and structured_data_desc.strip():
        has_search_kb = any(t.startswith("search_") or t.startswith("research_") for t in (available_tools or []))
        routing_note = (
            "The KB also has unstructured documents searchable via search_kb. "
            "Use query_structured_data for quantitative/analytical questions and "
            "search_kb for qualitative/text-based questions."
            if has_search_kb else
            "Use query_structured_data for any data-related questions."
        )
        structured_section = (
            f"## Structured Data Available\n"
            f"The agent HAS structured tabular data loaded and ready to query. "
            f"The query tool autonomously selects the right tables and runs SQL.\n"
            f"When the user asks about numbers, statistics, revenue, dates, "
            f"filtering, ranking, totals, KPIs, or any data analysis, you MUST choose "
            f"query_structured_data — do NOT choose chat or search_kb.\n"
            f"PRIORITY RULE: If the user mentions 'tables', 'KPI', 'data', 'numbers', "
            f"'from tables', or any quantitative request, query_structured_data "
            f"MUST be the FIRST action — do NOT search_kb first.\n"
            f"POST-QUERY RULE: Once query_structured_data has returned results, "
            f"choose 'chat' to present the data. Do NOT automatically follow up "
            f"with search_kb — the structured data results are self-contained.\n"
            f"{routing_note}\n\n"
        )

    doc_name_section = ""
    has_kb_tool = any(
        t.startswith("search_") or t.startswith("research_")
        for t in (available_tools or [])
    )
    if has_kb_tool:
        doc_name_section = (
            "## Document Filtering\n"
            "When choosing search_kb, if the conversation mentions a specific "
            "file name (e.g. 'reasons3.txt', 'report.pdf'), you MUST include "
            '"document_name" in your action to restrict the search to that file.\n\n'
        )

    user_prompt = (
        f"## Agent Instructions\n{task_instructions}\n\n"
        f"## Required Output Schema\n{output_schema_summary}\n\n"
        f"## Available Tools\n{tools_text}\n\n"
        f"{metadata_section}"
        f"{doc_name_section}"
        f"{structured_section}"
        f"## Recent Conversation\n{conversation_text}\n\n"
        "What should the agent do next?"
    )

    logger.debug(
        "🔀 Tool Caller INPUT | tools: [%s] | msgs: %d | task_preview: %s | schema_preview: %s",
        tools_text,
        len(recent_messages),
        task_instructions[:120].replace("\n", " "),
        output_schema_summary[:120].replace("\n", " "),
    )
    logger.debug(
        "🔀 Tool Caller FULL PROMPT (%d chars):\n%s",
        len(user_prompt), user_prompt,
    )

    try:
        llm = LLMClientManager.get_client_for_binding(
            TOOL_CALLER_BINDING,
            temperature=TOOL_CALLER_TEMPERATURE,
            max_tokens=TOOL_CALLER_MAX_TOKENS,
            streaming=True,
            stream_chat=False,
            llm_role="tool_decider",
        )

        system_prompt = _build_router_system_prompt(available_tools)
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        content = _extract_text_content(response.content)
        parsed = _parse_router_response(content, available_tools)
        logger.debug(
            "🔀 Tool Caller DECISION: %s | raw: %s",
            json.dumps(parsed), content[:300],
        )
        return parsed

    except Exception as e:
        logger.warning(
            "Tool Caller failed (%s), defaulting to chat: %s",
            type(e).__name__, e,
        )
        return {"action": "chat", "reason": f"Router error — defaulting to chat ({e})"}


def _strip_markdown_json(content: str) -> str:
    """Remove markdown code fences (```json ... ```) that some models add."""
    import re
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content


def _parse_router_response(
    content: str,
    available_tools: List[str],
) -> Dict[str, Any]:
    """Extract action dict from the router's raw response."""
    cleaned = _strip_markdown_json(content)
    try:
        data = json.loads(cleaned)
        action = data.get("action", "chat")

        # Normalize tool-name actions to standard action types.
        # The Tool Caller sometimes uses the actual tool name
        # (e.g. "research_whys") instead of the canonical action.
        if action.startswith("search_") or action.startswith("research_"):
            if action not in ("search_kb",):
                logger.debug(
                    "🔀 Normalizing tool-name action '%s' → 'search_kb'", action,
                )
                data["action"] = "search_kb"
                action = "search_kb"
        elif action.startswith("query_") and action != "query_structured_data":
            logger.debug(
                "🔀 Normalizing tool-name action '%s' → 'query_structured_data'", action,
            )
            data["action"] = "query_structured_data"
            if "query" in data and "question" not in data:
                data["question"] = data.pop("query")
            action = "query_structured_data"

        if action == "search_kb" and "search_kb" not in _tool_capabilities(available_tools):
            logger.warning("Router chose search_kb but no KB tool available — falling back to chat")
            return {"action": "chat", "reason": "No KB tool available"}

        if action == "deep_research" and "deep_research" not in available_tools:
            if "search_kb" in _tool_capabilities(available_tools):
                logger.debug(
                    "🔀 Router chose deep_research but tool not available — "
                    "falling back to search_kb (KB tool exists)"
                )
                data["action"] = "search_kb"
                return data
            logger.warning("Router chose deep_research but tool not available — falling back to chat")
            return {"action": "chat", "reason": "deep_research not available"}

        if action == "simple_web_search" and "simple_web_search" not in available_tools:
            logger.warning("Router chose simple_web_search but tool not available — falling back to chat")
            return {"action": "chat", "reason": "simple_web_search not available"}

        if action == "ask_user_questions" and "ask_user_questions" not in available_tools:
            logger.warning("Router chose ask_user_questions but tool not available — falling back to chat")
            return {"action": "chat", "reason": "ask_user_questions not available"}

        return data

    except json.JSONDecodeError:
        pass

    content_lower = content.lower()
    if "submit_deliverable" in content_lower:
        return {"action": "submit_deliverable", "reason": "parsed from text"}
    if "search_kb" in content_lower or "knowledge" in content_lower:
        return {"action": "chat", "reason": "could not parse query"}
    return {"action": "chat", "reason": "unparseable response"}


def _tool_capabilities(available_tools: List[str]) -> List[str]:
    """Map tool names to capability tags.

    KB tools have dynamic names (``search_<kb_name>`` or
    ``research_<kb_name>``), so we detect them by prefix and report
    ``search_kb`` as a capability.  Registry tools like
    ``simple_web_search`` pass through as-is.
    """
    caps = []
    for t in available_tools:
        if t.startswith("search_") or t.startswith("research_"):
            caps.append("search_kb")
        elif t.startswith("query_"):
            caps.append("query_structured_data")
        else:
            caps.append(t)
    return caps


# ---------------------------------------------------------------------------
# Legacy readiness classifier (kept for backward compatibility)
# ---------------------------------------------------------------------------

CLASSIFIER_MODEL_PROVIDER = TOOL_CALLER_PROVIDER

CLASSIFIER_TEMPERATURE = 0.0
CLASSIFIER_MAX_TOKENS = 256

CLASSIFIER_SYSTEM_PROMPT = """\
You are a readiness classifier for a multi-agent workflow system.

Given an agent's task description, required output schema, and the recent
conversation history, determine whether the agent has gathered enough
information to produce a COMPLETE and HIGH-QUALITY deliverable.

Respond with ONLY a JSON object (no markdown, no extra text):
{"ready": true, "reason": "one sentence explanation"}
or
{"ready": false, "reason": "what is still missing"}

Be strict: the agent should have concrete data/answers for ALL major
sections of the output schema, not just partial information.
"""


async def classify_readiness(
    task_instructions: str,
    output_schema_summary: str,
    recent_messages: List[str],
    provider: str = CLASSIFIER_MODEL_PROVIDER,
    model: Optional[str] = None,
) -> Tuple[bool, str]:
    """Determine whether the agent is ready to deliver."""
    conversation_text = "\n---\n".join(recent_messages[-10:])

    user_prompt = (
        f"## Agent Instructions\n{task_instructions}\n\n"
        f"## Required Output Schema\n{output_schema_summary}\n\n"
        f"## Recent Conversation\n{conversation_text}\n\n"
        "Is the agent ready to produce a complete deliverable?"
    )

    try:
        llm = LLMClientManager.get_client_for_binding(
            TOOL_CALLER_BINDING,
            temperature=CLASSIFIER_TEMPERATURE,
            max_tokens=CLASSIFIER_MAX_TOKENS,
            llm_role="readiness_classifier",
        )

        response = await llm.ainvoke([
            SystemMessage(content=CLASSIFIER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])

        content = _extract_text_content(response.content)
        parsed = _parse_classifier_response(content)
        logger.debug(
            "Classifier decision: ready=%s, reason=%s",
            parsed[0], parsed[1],
        )
        return parsed

    except Exception as e:
        logger.warning(
            "Classifier call failed (%s), defaulting to ready=True: %s",
            type(e).__name__, e,
        )
        return True, f"Classifier error — defaulting to ready ({e})"


def _parse_classifier_response(content: str) -> Tuple[bool, str]:
    """Extract (ready, reason) from the classifier's raw response."""
    try:
        data = json.loads(content)
        return bool(data.get("ready", True)), data.get("reason", "")
    except json.JSONDecodeError:
        pass

    content_lower = content.lower()
    if "not_ready" in content_lower or '"ready": false' in content_lower:
        return False, content
    return True, content
