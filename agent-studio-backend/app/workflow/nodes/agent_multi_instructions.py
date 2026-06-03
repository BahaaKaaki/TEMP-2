"""
Multi-agent mode system instruction builder.

Builds comprehensive system prompts with:
- Previous deliverables context  
- Task/output schemas
- Rejection feedback
- KB access instructions
"""

import logging
from typing import Dict, List

from ..state import WorkflowState, get_previous_deliverables, format_deliverables_for_prompt, resolve_deliverable_sources
from ..utils.context import enrich_system_prompt
from ..utils.kb_config import resolve_kb_ids

logger = logging.getLogger(__name__)


def resolve_agent_instructions(config: Dict) -> str:
    """Canonical agent instructions for Tool Caller, KB researcher, classifiers, etc.

    ``systemInstructions`` is the source of truth. ``taskInstructions`` is kept
    only as a fallback for workflows saved before that field was retired.
    """
    if not config:
        return ""
    system = (config.get("systemInstructions") or "").strip()
    if system:
        return system
    legacy = (config.get("taskInstructions") or "").strip()
    if legacy:
        return legacy
    return (config.get("reasoningGuideline") or "").strip()


class MultiAgentInstructionBuilder:
    """Builds system instructions for multi-agent mode."""
    
    def __init__(self, node):
        """Initialize with parent node reference."""
        self.node = node
    
    def build(
        self,
        state: WorkflowState,
        has_rejection_feedback: bool = False,
        tool_caller_mode: bool = False,
        structured_schema: str = "",
    ) -> str:
        """
        Build comprehensive system instructions for multi-agent mode.
        
        Args:
            state: Current workflow state
            has_rejection_feedback: Whether agent is re-executing after rejection
            tool_caller_mode: If True, omit output schema and submit_deliverable
                instructions from the prompt.  The Main LLM should only
                reason/chat; deliverable production is handled separately.
            structured_schema: Pre-fetched semantic model text describing
                structured tables/columns available in the KB.
            
        Returns:
            Complete system instruction string
        """
        parts = []
        config = self.node.node_config or {}
        
        # Get previous deliverables based on deliverableSources config
        previous_deliverables = resolve_deliverable_sources(
            state, self.node.node_id, config
        )
        has_previous_deliverables = len(previous_deliverables) > 0
        
        # Add each instruction section
        if has_previous_deliverables:
            if tool_caller_mode:
                parts.append(self._get_critical_context_mandate())
            else:
                parts.append(self._get_critical_json_mandate())
        
        parts.append(self._get_role_instructions(config))
        
        if previous_deliverables:
            parts.append(self._get_deliverables_context(previous_deliverables))
        
        if has_rejection_feedback:
            parts.append(self._get_rejection_feedback(state))
        
        if config.get("inputSchema"):
            parts.append(self._get_input_schema(config))
        
        if not tool_caller_mode:
            if config.get("outputSchema"):
                parts.append(self._get_output_schema(config))
            parts.append(self._get_response_format())
        else:
            parts.append(self._get_tool_caller_mode_format())
        
        parts.append(self._get_reasoning_guidelines())
        
        kb_ids = resolve_kb_ids(self.node.get_config_value)
        if kb_ids:
            kb_section = self._get_kb_instructions(
                structured_schema,
                tool_caller_mode=tool_caller_mode,
                kb_count=len(kb_ids),
            )
            parts.append(kb_section)
            logger.debug(
                "📚 Added KB instructions for %d KB(s) (%s) (%d chars, structured_schema=%d chars)",
                len(kb_ids), kb_ids, len(kb_section), len(structured_schema),
            )

        enable_web_search = bool(config.get("enableWebSearch"))
        enable_deep_research = bool(config.get("enableDeepResearch"))
        has_kb = bool(kb_ids)
        if has_kb or enable_web_search or enable_deep_research:
            parts.append(self._get_citation_instructions(
                has_kb=has_kb,
                has_web=enable_web_search,
                has_deep_research=enable_deep_research,
                tool_caller_mode=tool_caller_mode,
            ))

        # Join and enrich
        full_instructions = "\n".join(parts)
        user_timezone = state.get("variables", {}).get("user_timezone")
        enriched_instructions = enrich_system_prompt(full_instructions, user_timezone)
        
        logger.debug("Built system instructions (%d chars) for %s", 
                    len(enriched_instructions), self.node.label)
        
        return enriched_instructions
    
    def _get_critical_json_mandate(self) -> str:
        """Critical mandate for downstream agents receiving prior context."""
        return """⚠️ CRITICAL: You are receiving processed information from a previous agent.
Use it as context, but do NOT just repeat it verbatim.

If you need more information, ask the user directly in your response.
Only call the submit_deliverable tool when you are ready with your own analysis.
---
"""

    def _get_critical_context_mandate(self) -> str:
        """Context mandate for tool-caller-mode (no mention of tools)."""
        return """⚠️ CRITICAL: You are receiving processed information from a previous agent.
Use it as context, but do NOT just repeat it verbatim.

If you need more information, ask the user directly in your response.
Focus on reasoning, analysis, and gathering information through conversation.
---
"""

    def _get_tool_caller_mode_format(self) -> str:
        """Response format for tool-caller-mode Main LLM (no tool/schema awareness)."""
        config = self.node.node_config or {}
        has_deep_research = config.get("enableDeepResearch", False)

        deep_research_guidance = ""
        if has_deep_research:
            deep_research_guidance = (
                "- You have access to deep research capabilities. When a user asks a "
                "substantive question, do NOT provide a full answer from general knowledge.\n"
                "- Instead, briefly acknowledge the request and state what you plan to "
                "research. Keep your initial response SHORT (2-3 sentences max).\n"
                "- A research step will be performed automatically — your role is to "
                "frame the research need, not to answer from memory.\n"
            )

        return f"""
# HOW TO RESPOND
- Respond in natural language only.
- Ask clarifying questions when you need more information.
- Analyze and reason about the task step by step.
- Do NOT produce structured JSON output in your response.
- Do NOT mention tools, schemas, or deliverables.
- Focus on gathering information, reasoning, and communicating with the user.
{deep_research_guidance}"""
    
    def _get_role_instructions(self, config: Dict) -> str:
        """Base role instructions."""
        base = resolve_agent_instructions(config) or "You are a helpful AI assistant."
        return f"# ROLE\n{base}\n"
    
    def _get_deliverables_context(self, previous_deliverables: List[Dict]) -> str:
        """Previous agents' deliverables context."""
        context = format_deliverables_for_prompt(previous_deliverables)
        return (f"# CONTEXT FROM PREVIOUS AGENTS\n{context}\n"
                "Build upon these outputs. Reference them when relevant.\n")
    
    def _get_rejection_feedback(self, state: WorkflowState) -> str:
        """Rejection feedback for re-execution."""
        messages = state.get("messages", [])
        rejection_messages = [
            msg.content for msg in messages 
            if hasattr(msg, "additional_kwargs") 
            and msg.additional_kwargs.get("is_rejection_feedback", False)
        ]
        
        if not rejection_messages:
            return ""
        
        parts = [
            "\n⚠️ CRITICAL - REVISION REQUIRED:\n",
            "Your previous deliverable was REJECTED. You MUST address this feedback:\n\n"
        ]
        
        for feedback in rejection_messages:
            parts.append(f"FEEDBACK: {feedback}\n")
        
        parts.append("\nYou MUST revise your analysis and call submit_deliverable with an improved deliverable.\n")
        parts.append("Do NOT just respond conversationally — you MUST call submit_deliverable with the complete data.\n")
        parts.append("Focus on addressing the specific issues mentioned in the feedback.\n\n")
        
        return "".join(parts)
    
    def _get_input_schema(self, config: Dict) -> str:
        """Input schema definition."""
        schema = config.get("inputSchema", "")
        return f"# EXPECTED INPUT FORMAT\n```json\n{schema}\n```\n"
    
    def _get_output_schema(self, config: Dict) -> str:
        """Output schema definition with tool-based delivery instructions."""
        schema = config.get("outputSchema", "")

        return f"""# REQUIRED OUTPUT SCHEMA
When calling the submit_deliverable tool, your data must match this JSON Schema:
```json
{schema}
```

IMPORTANT:
- This is a JSON SCHEMA definition. You must provide ACTUAL DATA that matches this schema.
- Do NOT return the schema itself — return data that conforms to the schema structure.
"""
    
    def _get_response_format(self) -> str:
        """Response format instructions using tool-based delivery."""
        return """
# HOW TO RESPOND
- Respond in natural language. Ask clarifying questions when you need more information.
- When your task is complete and you have gathered enough information, call the
  **submit_deliverable** tool with your structured output data.
- Do NOT try to embed JSON deliverables in your chat text — always use the tool.
- Keep asking questions until you are confident you can produce a complete deliverable.
"""
    
    def _get_reasoning_guidelines(self) -> str:
        """Reasoning guidelines."""
        return """
# REASONING GUIDELINES
- Think step-by-step
- Be thorough but efficient
- Ask clarifying questions when uncertain
- Build upon previous agents' work
- Provide clear explanations in your chat responses
"""
    
    def _get_kb_instructions(
        self,
        structured_schema: str = "",
        tool_caller_mode: bool = False,
        kb_count: int = 1,
    ) -> str:
        """Knowledge base usage instructions, optionally including structured data awareness.

        When *tool_caller_mode* is True the Main LLM has NO tools bound, so
        the instructions avoid phrases like "use the tool" or "you have access
        to a tool" which can cause some models (e.g. Gemini) to attempt a
        function call and return empty content.  Instead the instructions frame
        information retrieval as automatic system behaviour.

        ``kb_count`` controls singular vs. plural language so the LLM
        understands when more than one KB is available.
        """
        if tool_caller_mode:
            return self._get_kb_instructions_tool_caller_mode(
                structured_schema, kb_count=kb_count,
            )

        structured_section = ""
        if structured_schema and structured_schema.strip():
            structured_section = """
## Structured Data (CSV/Excel Tables)
You have access to a structured data query tool that can analyse uploaded CSV/Excel tables.
The tool autonomously selects the right tables, explores the data, and runs SQL queries.
You do NOT need to know table names or column names — just pass the user's data question.

When users ask questions about numbers, statistics, aggregations, filtering,
or any data analysis, you SHOULD use this tool. DO NOT say you don't have the data.

STRUCTURED DATA RESULT FORMATTING:
- When you receive query results as a markdown table, you MUST include the full table in your response.
- Add a brief summary or insight ABOVE the table (e.g. "Here are the results:" or a key finding).
- If appropriate, add analysis or observations BELOW the table.
- Do NOT rewrite the table as prose — always preserve it as a markdown table so the user can read it visually.
- Do NOT attempt your own calculations on the data — the query tool handles all computation.
"""

        kb_priority_rule = (
            "- For quantitative/data questions (numbers, KPIs, statistics, tables), "
            "use the structured data query tool FIRST. Only search the KB afterwards "
            "if the user explicitly asks for narrative context or if the query tool "
            "returned no results.\n"
            "- For qualitative questions (policies, reports, explanations), search "
            "the knowledge base FIRST before asking the user clarifying questions.\n"
            if structured_section else
            "- ALWAYS search the knowledge base FIRST before asking the user clarifying questions.\n"
            "  When the user describes what they need, search immediately with a relevant query.\n"
            "  Ask for refinements only AFTER reviewing the search results.\n"
        )

        if kb_count > 1:
            scope_line = (
                f"You have access to {kb_count} knowledge base search tools "
                "— one per configured KB. Each tool is named after its KB.\n"
            )
            multi_kb_rule = (
                "- When a question could be answered by more than one KB, call "
                "every relevant search tool (and any structured-data tool) for "
                "those KBs and merge the results before answering.\n"
            )
        else:
            scope_line = "You have access to a knowledge base search tool.\n"
            multi_kb_rule = ""

        return f"""
# KNOWLEDGE BASE ACCESS
{scope_line}IMPORTANT GUIDELINES:
{kb_priority_rule}{multi_kb_rule}- Use the knowledge base search tool(s) when users ask about: documents, reports, policies, procedures, data, or any domain-specific information.
{structured_section}
- If the KB search returns no relevant results, clearly inform the user.
- Do not make up or hallucinate information - if it's not in the KB, say so.
- You can search multiple times with different queries if needed.
"""

    def _get_kb_instructions_tool_caller_mode(
        self,
        structured_schema: str = "",
        kb_count: int = 1,
    ) -> str:
        """KB instructions for tool-caller-mode where the Main LLM has no tools.

        Avoids all "you have access to a tool" language.  Instead frames
        the KB as a knowledge source whose results will be provided
        automatically, so the LLM should focus on reasoning and
        conversing rather than attempting function calls.
        """
        structured_section = ""
        if structured_schema and structured_schema.strip():
            structured_section = """
## Structured Data (CSV/Excel Tables)
Uploaded CSV/Excel tables are available and can be queried automatically.
When the user asks about numbers, statistics, aggregations, filtering,
or any data analysis, the system will query the data for you.

STRUCTURED DATA RESULT FORMATTING:
- When you receive query results as a markdown table, you MUST include the full table in your response.
- Add a brief summary or insight ABOVE the table (e.g. "Here are the results:" or a key finding).
- If appropriate, add analysis or observations BELOW the table.
- Do NOT rewrite the table as prose — always preserve it as a markdown table so the user can read it visually.
- Do NOT attempt your own calculations on the data — the system handles all computation.
"""

        kb_priority_rule = (
            "- For quantitative/data questions (numbers, KPIs, statistics, tables), "
            "the system will query the structured data first.\n"
            "- For qualitative questions (policies, reports, explanations), "
            "the system will search the knowledge base.\n"
            if structured_section else
            "- The system will automatically search the knowledge base when needed.\n"
        )

        kb_label = (
            f"{kb_count} knowledge bases containing relevant documents and data are available."
            if kb_count > 1
            else "A knowledge base containing relevant documents and data is available."
        )

        return f"""
# KNOWLEDGE BASE
{kb_label}
The system will automatically search it and provide results when needed.
Your role is to reason about the user's request and present findings clearly.
{kb_priority_rule}
IMPORTANT GUIDELINES:
- Do NOT make up or hallucinate information — if it's not in the provided results, say so.
- Do NOT attempt to call any functions or tools. Just respond in natural language.
{structured_section}"""

    def _get_citation_instructions(
        self,
        has_kb: bool,
        has_web: bool,
        has_deep_research: bool,
        tool_caller_mode: bool = False,
    ) -> str:
        """Generic citation-preservation rules applied whenever any citation-
        emitting tool is available (KB search, web search, deep research).

        This used to live inside ``_get_kb_instructions`` and was therefore only
        injected when a knowledge base was configured.  Web-search-only agents
        never saw it, so LLMs routinely stripped ``[N]`` markers from the final
        response and the downstream citation pipeline discarded every citation.
        Keeping the rules in their own section lets us apply them uniformly.
        """
        sources: List[str] = []
        if has_kb:
            sources.append("the knowledge base search tool")
        if has_web:
            sources.append("the web search tool")
        if has_deep_research:
            sources.append("the deep research tool")

        source_list = ", ".join(sources) if sources else "research tools"

        return f"""
# CITATION REQUIREMENTS (CRITICAL)
Whenever you use information that came from {source_list}, you MUST preserve the
numbered citation markers ``[1]``, ``[2]``, ``[3]``, ... that appear in the tool
output. These markers are how the frontend renders clickable source badges.

Rules:
- Place each marker immediately after the claim it supports, e.g.
  "Brent crude rose 17% this week [2]."
- If a single claim is supported by multiple sources, include every marker:
  "Gold fell 3% for the week [1][2]."
- NEVER drop, renumber, or rewrite the markers. Keep them exactly as the tool
  returned them (``[1]``, ``[2]``, ... — no extra words inside the brackets).
- When producing structured DELIVERABLE data (via ``submit_deliverable``), do
  NOT include any ``[N]`` markers in field values. Deliverables must be clean.
- Do NOT invent new citation numbers — only use the ones the tool gave you.
"""

