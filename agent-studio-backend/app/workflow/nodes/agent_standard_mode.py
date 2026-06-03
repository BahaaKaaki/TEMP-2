"""
Standard agent execution mode.

Handles regular LLM agent interactions with tool calling loop.
No research orchestration or structured deliverables.
"""

from typing import Any, List, Dict, Optional
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
import logging
import uuid
import re
import json
import asyncio

from config.llm_config import LLMClientManager, LLMConfig
from app.utils.citation_injector import CitationInjector
from app.tracing import trace_tool_call
from ..state import (
    WorkflowState,
    get_session_id_from_state,
    get_workflow_id_from_state,
    resolve_deliverable_sources,
)
from ..utils.context import enrich_system_prompt
from ..utils.kb_config import resolve_kb_ids
from ..utils.file_context import build_global_file_context
from ..utils.streaming import should_stream_chat_responses
from app.tracing.chat_stream import (
    clear_chat_stream_buffer,
    defer_chat_stream,
    flush_chat_stream_buffer,
    reset_defer_chat_stream,
)

logger = logging.getLogger(__name__)


class StandardModeExecutor:
    """Executes agent in standard mode with tool calling."""
    
    def __init__(self, node):
        """Initialize with parent node reference."""
        self.node = node
    
    async def execute(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute as standard agent (original implementation).
        
        Runs regular agent with tool loop, no research orchestration.
        
        Args:
            state: Current workflow state
            
        Returns:
            Agent response dictionary
        """
        # Get configuration
        config = self._get_config(state)
        
        # Get input data
        input_data = self._get_input_data(state, config['input_source'])
        
        # Initialize LLM
        metadata = state.get("metadata") or {}
        stream_chat = should_stream_chat_responses(
            node_config=config["node_config"],
            node_type=self.node.node_type,
            metadata=metadata,
        )
        llm = LLMClientManager.get_client(
            config['model_provider'],
            config['model_name'],
            config['temperature'],
            config['max_tokens'],
            streaming=stream_chat,
            stream_chat=stream_chat,
        )
        
        # Get and bind tools
        tools = await self.node._get_tools(config['tool_names'])
        llm_forced = None
        llm_optional = llm
        forced_tool_name = None
        if tools:
            logger.debug("🔧 Binding %d tool(s) to LLM: %s", 
                       len(tools), [getattr(t, 'name', 'unknown') for t in tools])
            llm_optional = llm.bind_tools(tools)
            forced_tool_name = self._get_forced_tool_name(tools)
            if forced_tool_name:
                llm_forced = llm.bind_tools(tools, tool_choice=forced_tool_name)
                logger.debug("🔒 Strict mode: forcing initial tool call to '%s'", forced_tool_name)
            llm = llm_optional
        
        # Prepare messages
        messages = await self._prepare_messages(state, config, input_data)
        
        # Execute LLM with tool loop
        result = await self._execute_tool_loop(
            llm, messages, tools, state, config, llm_optional, llm_forced, forced_tool_name
        )
        
        return result
    
    def _get_config(self, state: WorkflowState) -> Dict[str, Any]:
        """Extract configuration values."""
        node = self.node
        
        # Determine input source
        input_source = node.get_config_value("inputSource")
        if not input_source:
            node_outputs = state.get("node_outputs", {})
            if node_outputs:
                outputs_list = [(k, v) for k, v in node_outputs.items() 
                               if k != node.node_id]
                if outputs_list:
                    input_source = outputs_list[-1][0]
                    logger.debug("Agent %s using input from previous node: %s", 
                               node.node_id, input_source)
        
        return {
            'prompt': node.get_config_value("prompt", ""),
            'model_provider': node.get_config_value("modelProvider", LLMConfig.DEFAULT_PROVIDER),
            'model_name': node.get_config_value("modelName", LLMConfig.DEFAULT_MODEL),
            'temperature': node.get_config_value("temperature", LLMConfig.DEFAULT_TEMPERATURE),
            'max_tokens': node.get_config_value("maxTokens", LLMConfig.DEFAULT_MAX_TOKENS),
            'tool_names': node.get_config_value("tools", []),
            'input_source': input_source,
            'kb_ids': resolve_kb_ids(node.get_config_value),
            'node_config': node.node_config or {}
        }
    
    def _get_input_data(self, state: WorkflowState, input_source: str) -> Any:
        """Get and log input data."""
        input_data = self.node.get_input_from_state(state, input_source)
        
        logger.debug(
            "Agent input source: %s, input_data type: %s",
            input_source if input_source else "state.input_data",
            type(input_data).__name__
        )
        
        if isinstance(input_data, dict) and "message" in input_data:
            logger.debug("Agent input_data.message: %s", input_data["message"][:100])
        elif isinstance(input_data, str):
            logger.debug("Agent input_data (str): %s", input_data[:100])
        
        return input_data
    
    async def _prepare_messages(
        self,
        state: WorkflowState,
        config: Dict[str, Any],
        input_data: Any
    ) -> List:
        """Prepare message list for LLM."""
        messages = []
        
        # Add system message
        if config['prompt']:
            system_msg = await self._build_system_message(state, config, input_data)
            messages.append(SystemMessage(content=system_msg))
        
        # Add conversation history
        if state.get("messages"):
            messages.extend(state["messages"])
            logger.debug("Added %d messages from conversation history", 
                        len(state["messages"]))
        
        # Add current input
        self._add_input_message(messages, input_data)
        
        return messages
    
    async def _build_system_message(
        self,
        state: WorkflowState,
        config: Dict[str, Any],
        input_data: Any
    ) -> str:
        """Build enriched system prompt."""
        # Format prompt with variables
        formatted_prompt = self.node._format_prompt(
            config['prompt'], state, input_data
        )
        
        # Enrich with system context
        user_timezone = state.get("variables", {}).get("user_timezone")
        enriched_prompt = enrich_system_prompt(formatted_prompt, user_timezone)
        
        # Add previous deliverables context (respects deliverableSources config)
        deliverables = resolve_deliverable_sources(
            state, self.node.node_id, config.get('node_config', {})
        )
        if deliverables:
            enriched_prompt += self._format_deliverables_context(deliverables)
            logger.debug("✅ Added %d deliverable(s) to agent context", 
                       len(deliverables))
        
        # Add KB instructions whenever any knowledge base is wired up
        kb_ids = config.get('kb_ids') or []
        if kb_ids:
            enriched_prompt += self._get_kb_instructions(kb_ids)
            logger.debug(
                "📚 Added knowledge base usage instructions for %d KB(s): %s",
                len(kb_ids), kb_ids,
            )

        node_config = config.get('node_config') or {}
        has_web = bool(node_config.get('enableWebSearch'))
        has_dr = bool(node_config.get('enableDeepResearch'))
        has_kb = bool(kb_ids)
        if has_kb or has_web or has_dr:
            enriched_prompt += self._get_citation_instructions(
                has_kb=has_kb, has_web=has_web, has_deep_research=has_dr,
            )
        
        session_id = get_session_id_from_state(state)
        if session_id:
            global_block = await build_global_file_context(
                session_id,
                current_agent_id=self.node.node_id,
                node_config=node_config,
                workflow_id=get_workflow_id_from_state(state),
            )
            if global_block:
                enriched_prompt += global_block
                logger.debug(
                    "📁 Injected file context from previous steps for %s",
                    self.node.label,
                )

        return enriched_prompt
    
    def _format_deliverables_context(self, deliverables: List[Dict]) -> str:
        """Format deliverables for prompt context."""
        context = "\n\n=== APPROVED DELIVERABLES FROM PREVIOUS AGENTS ===\n"
        context += "Indices start at 0 (first item is 0, second is 1), same as in code.\n"
        for idx, deliv in enumerate(deliverables):
            context += f"\nDeliverable [{idx}] from {deliv.get('agent_label', 'Unknown Agent')}:\n"
            context += f"Status: {deliv.get('status', 'unknown')}\n"
            context += f"Content:\n{json.dumps(deliv.get('deliverable', {}), indent=2)}\n"
        return context
    
    def _get_kb_instructions(self, kb_ids: List[str]) -> str:
        """Get knowledge base usage instructions.

        When multiple KBs are configured each gets its own search tool
        (``search_<kb_name>``) plus an optional structured-data tool
        (``query_<kb_name>``).  The instructions remind the LLM that it
        can call any/all of them — not just one.
        """
        multi = len(kb_ids) > 1
        scope_line = (
            "You have access to multiple knowledge base search tools "
            "— one per configured KB.  Each tool is named after its KB.\n"
            if multi
            else "You have access to a knowledge base search tool.\n"
        )
        multi_search_rule = (
            "- When the question could be answered by more than one KB, "
            "call every relevant tool (in parallel if possible) and merge "
            "their results before answering.\n"
            if multi
            else "- You can search multiple times with different queries if needed.\n"
        )
        return (
            "\n\n=== KNOWLEDGE BASE ACCESS ===\n"
            f"{scope_line}"
            "\n"
            "WHEN TO SEARCH:\n"
            "- Search the knowledge base when the user's message requires specific information, "
            "facts, data, evidence, or domain-specific knowledge that you should not answer from memory alone.\n"
            "- Examples of when to search: questions about documents, reports, policies, procedures, "
            "prior work, case studies, or any factual claim that should be backed by sources.\n"
            "\n"
            "WHEN NOT TO SEARCH:\n"
            "- Do NOT search for greetings, small talk, clarifying questions, or general conversation "
            "that does not require domain-specific evidence.\n"
            "- Do NOT search if the user is simply confirming, thanking, or asking you to adjust "
            "formatting, tone, or structure of a previous answer.\n"
            "- Do NOT search if you are asking the user for more details or clarification.\n"
            "\n"
            "- If the KB search returns no relevant results, clearly inform the user.\n"
            "- Do not make up or hallucinate information - if it's not in the KB, say so.\n"
            f"{multi_search_rule}"
        )

    def _get_citation_instructions(
        self,
        has_kb: bool,
        has_web: bool,
        has_deep_research: bool,
    ) -> str:
        """Generic ``[N]``-marker preservation rules.

        Applied whenever any citation-emitting tool is configured (KB search,
        web search, deep research). Previously this was bundled into the KB
        instructions and therefore never reached agents that had only web
        search enabled — which caused the LLM to strip markers and the
        downstream pipeline to silently discard every citation.
        """
        sources = []
        if has_kb:
            sources.append("the knowledge base search tool")
        if has_web:
            sources.append("the web search tool")
        if has_deep_research:
            sources.append("the deep research tool")
        source_list = ", ".join(sources) if sources else "research tools"

        return (
            "\n\n=== CITATION REQUIREMENTS (CRITICAL) ===\n"
            f"Whenever you use information that came from {source_list}, you MUST "
            "preserve the numbered citation markers [1], [2], [3], ... that appear "
            "in the tool output. These markers are how the frontend renders "
            "clickable source badges.\n"
            "\n"
            "- Place each marker immediately after the claim it supports, e.g.\n"
            '  "Brent crude rose 17% this week [2]."\n'
            "- If a single claim is supported by multiple sources, include every marker:\n"
            '  "Gold fell 3% for the week [1][2]."\n'
            "- NEVER drop, renumber, or rewrite the markers — keep them exactly as the "
            "tool returned them.\n"
            "- Do NOT invent new citation numbers — only use the ones the tool gave you.\n"
        )
    
    def _add_input_message(self, messages: List, input_data: Any) -> None:
        """Add current input as human message."""
        if isinstance(input_data, str):
            messages.append(HumanMessage(content=input_data))
            logger.debug("Processing user message: %s", input_data[:100])
        elif isinstance(input_data, dict):
            if "aggregated" in input_data:
                # Subagent findings
                findings = f"Research findings from {input_data.get('num_subagents', 0)} subagents:\n\n{input_data['aggregated']}"
                messages.append(HumanMessage(content=findings))
                logger.debug("Agent processing subagent findings (%d chars)", 
                           len(input_data['aggregated']))
            elif "message" in input_data:
                messages.append(HumanMessage(content=input_data["message"]))
                logger.debug("Processing user message: %s", input_data["message"][:100])
            elif "matched_condition_id" in input_data.get("output", {}):
                # Skip routing logic
                logger.debug("Skipping condition node output (routing only)")
            elif input_data:
                # Generic dict
                messages.append(HumanMessage(content=json.dumps(input_data, indent=2)))
                logger.debug("Processing dict input: %s", str(input_data)[:100])
    
    async def _execute_tool_loop(
        self,
        llm: Any,
        messages: List,
        tools: List,
        state: WorkflowState,
        config: Dict[str, Any],
        llm_optional: Any = None,
        llm_forced: Any = None,
        forced_tool_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute LLM with tool calling loop."""
        max_iterations = LLMConfig.MAX_TOOL_ITERATIONS
        iteration = 0
        final_response = None
        accumulated_citations = []
        accumulated_queries: List[Dict] = []
        forced_tool_used = False
        llm_optional = llm_optional or llm
        from app.llm.registry import LlmModelRegistry
        from app.llm.invoke import ainvoke_with_fallback

        workflow_resolved = LlmModelRegistry.resolve_for_invoke(
            model_name=config.get("model_name"),
            provider=config.get("model_provider"),
        )

        while iteration < max_iterations:
            current_llm = llm_forced if forced_tool_name and not forced_tool_used and llm_forced else llm_optional
            defer_token = defer_chat_stream() if stream_chat else None
            try:
                response = await ainvoke_with_fallback(
                    current_llm,
                    messages,
                    resolved=workflow_resolved,
                )
                messages.append(response)

                tool_calls = getattr(response, 'tool_calls', [])

                ask_questions_call = next(
                    (tc for tc in tool_calls if tc.get("name") == "ask_user_questions"),
                    None,
                )
                if ask_questions_call:
                    if stream_chat:
                        clear_chat_stream_buffer()
                    return self._pause_for_user_questions(
                        ask_questions_call=ask_questions_call,
                        raw_response=response,
                        messages=messages,
                        state=state,
                        config=config,
                        iteration=iteration,
                        accumulated_citations=accumulated_citations,
                        accumulated_queries=accumulated_queries,
                    )

                if not tool_calls:
                    if forced_tool_name and not forced_tool_used:
                        logger.warning(
                            "⚠️ Strict mode: model did not call required tool '%s'. Requesting explicit tool call.",
                            forced_tool_name,
                        )
                        messages.append(HumanMessage(
                            content=(
                                f"You must call the '{forced_tool_name}' tool now before answering. "
                                "Do not provide a final response yet."
                            )
                        ))
                        if stream_chat:
                            clear_chat_stream_buffer()
                        iteration += 1
                        continue
                    if stream_chat:
                        await flush_chat_stream_buffer()
                    final_response = response
                    break

                if stream_chat:
                    clear_chat_stream_buffer()

                if forced_tool_name and any(tc.get("name") == forced_tool_name for tc in tool_calls):
                    forced_tool_used = True
                    logger.debug("✅ Strict mode: required tool '%s' was invoked", forced_tool_name)

                logger.info("Agent requested %d tool calls", len(tool_calls))
                await self._execute_tools(
                    tool_calls, tools, messages, accumulated_citations,
                    accumulated_queries,
                )
                iteration += 1
            finally:
                if defer_token is not None:
                    reset_defer_chat_stream(defer_token)
        
        if not final_response:
            final_response = response
        
        # Build result
        return self._build_result(
            final_response, messages, state, config, 
            accumulated_citations, iteration, accumulated_queries,
        )

    def _pause_for_user_questions(
        self,
        ask_questions_call: Dict[str, Any],
        raw_response: Any,
        messages: List,
        state: WorkflowState,
        config: Dict[str, Any],
        iteration: int,
        accumulated_citations: List[Dict],
        accumulated_queries: List[Dict],
    ) -> Dict[str, Any]:
        """Convert an ask_user_questions tool call into a workflow pause.

        Strips the tool-call AIMessage we just appended (the LLM's raw
        response with ``tool_calls=[ask_user_questions(...)]``) and
        replaces it with a clean AIMessage carrying the questions
        payload on ``additional_kwargs.questions``.  Returns
        ``interrupted=True`` so the workflow pauses for user input.
        """
        from app.workflow.tools.ask_user_questions import (
            AskUserQuestionsInput,
            normalize_questions_payload,
        )
        from langchain_core.messages import AIMessage

        raw_args = ask_questions_call.get("args") or {}

        # Validate via the same Pydantic schema used by bind_tools so we
        # never ship a malformed payload to the frontend.
        try:
            validated = AskUserQuestionsInput(**raw_args)
            payload: Dict[str, Any] = validated.model_dump(exclude_none=False)
        except Exception as e:
            logger.warning(
                "ask_user_questions: invalid args from LLM (%s); falling back to "
                "best-effort normalization. raw=%s",
                e,
                str(raw_args)[:300],
            )
            payload = normalize_questions_payload(raw_args)
            if not payload:
                # Couldn't salvage — return an error message so the LLM can
                # see what went wrong and try again.
                logger.error("ask_user_questions: unable to parse payload, refusing to pause")
                err = AIMessage(
                    content=(
                        "I tried to ask you some questions but my question payload "
                        "was malformed. Let me try again in plain text."
                    ),
                    additional_kwargs={
                        "message_id": str(uuid.uuid4()),
                        "agent_id": self.node.node_id,
                        "agent_label": self.node.label,
                        "agent_type": self.node.node_type,
                    },
                )
                # Replace the broken raw response with the error message
                if messages and messages[-1] is raw_response:
                    messages[-1] = err
                return self._build_result(
                    err, messages, state, config,
                    accumulated_citations, iteration + 1, accumulated_queries,
                )

        from app.workflow.tools.ask_user_questions import render_questions_for_llm

        intro_text = payload.get("intro") or ""

        # ``content`` is what the LLM will see on resume — render the
        # full questions text so the next turn has complete context of
        # what was asked. ``display_content`` is what the chat bubble
        # paints ABOVE the QuestionsCard.  Keep it empty here: the
        # card renders the intro itself, so duplicating it in the
        # bubble would draw the same text twice.
        llm_visible_content = render_questions_for_llm(payload, intro_text)

        clean_msg = AIMessage(
            content=llm_visible_content,
            additional_kwargs={
                "message_id": str(uuid.uuid4()),
                "agent_id": self.node.node_id,
                "agent_label": self.node.label,
                "agent_type": self.node.node_type,
                "questions": payload,
                "display_content": "",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        # Replace the raw response (which carries the tool_call) with our
        # clean message.  We don't want the tool_call to live in history
        # because it has no matching ToolMessage — and the next LLM turn
        # will see the user's answer as a normal HumanMessage anyway.
        if messages and messages[-1] is raw_response:
            messages[-1] = clean_msg
        else:
            messages.append(clean_msg)

        # Compute delta of NEW messages to return (same convention as
        # _build_result), then attach pause metadata.
        original_count = len(state.get("messages", []))
        new_messages = messages[original_count:]

        logger.info(
            "⏸️  Agent %s: paused via ask_user_questions (%d question(s))",
            self.node.label,
            len(payload.get("questions") or []),
        )

        return {
            "response": intro_text,
            "model": f"{config['model_provider']}/{config['model_name']}",
            "iterations": iteration + 1,
            "messages": new_messages,
            "interrupted": True,
            "questions_payload": payload,
        }

    @staticmethod
    def _get_forced_tool_name(tools: List[Any]) -> Optional[str]:
        """Choose which tool must be called first in strict mode.

        Only deep research is forced — it's a deliberate one-shot operation
        that should always run when configured.  KB search is left to the
        LLM's judgment so it can decide per-turn whether a search is needed.
        """
        for tool in tools:
            if getattr(tool, "_is_deep_research_tool", False) or getattr(tool, "name", "") == "deep_research":
                return getattr(tool, "name", None)
        return None
    
    async def _execute_single_tool(
        self,
        tool_call: Dict,
        tools: List
    ) -> tuple:
        """Execute a single tool and return result with metadata."""
        tool_name = tool_call.get('name')
        tool_args = tool_call.get('args', {})
        tool_id = tool_call.get('id', '')
        
        logger.debug("Executing tool: %s with args: %s", tool_name, tool_args)
        
        # Find tool
        tool = next((t for t in tools if t.name == tool_name), None)
        
        if not tool:
            logger.warning("Tool %s not found", tool_name)
            return (None, tool_name, tool_id, f"Error: Tool '{tool_name}' not found")
        
        async def _invoke():
            if hasattr(tool, 'coroutine'):
                return await tool.coroutine(**tool_args)
            elif hasattr(tool, 'func'):
                return await tool.func(**tool_args)
            elif hasattr(tool, '_arun'):
                return await tool._arun(**tool_args)
            return await tool.ainvoke(tool_args)

        try:
            tool_result = await trace_tool_call(
                tool_name,
                tool_args,
                _invoke,
                payload={"source": "standard_agent"},
            )
            return (tool_result, tool_name, tool_id, None)
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e)
            return (None, tool_name, tool_id, f"Error: {str(e)}")
    
    async def _execute_tools(
        self,
        tool_calls: List[Dict],
        tools: List,
        messages: List,
        accumulated_citations: List[Dict],
        accumulated_queries: Optional[List[Dict]] = None,
    ) -> None:
        """
        Execute tool calls IN PARALLEL and add results to messages.
        
        Performance optimization: Multiple tools run simultaneously.
        Example: google_search (2s) + kb_search (1.5s) + calculator (0.1s)
        - Sequential: 3.6s total
        - Parallel: 2s total (45% faster!)
        """
        if not tool_calls:
            return
        
        logger.debug("Executing %d tools IN PARALLEL", len(tool_calls))
        
        # Execute all tools in parallel
        results = await asyncio.gather(*[
            self._execute_single_tool(tool_call, tools)
            for tool_call in tool_calls
        ], return_exceptions=True)
        
        # Process all results
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Tool execution failed with exception: %s", result)
                tc_id = tool_calls[idx].get("id", "")
                messages.append(ToolMessage(
                    content=f"Error: Tool execution failed: {result}",
                    tool_call_id=tc_id
                ))
                continue
            
            tool_result, tool_name, tool_id, error = result
            
            if error:
                messages.append(ToolMessage(content=error, tool_call_id=tool_id))
            else:
                self._process_tool_result(
                    tool_result, tool_name, tool_id, 
                    messages, accumulated_citations,
                    accumulated_queries,
                )
    
    def _process_tool_result(
        self,
        tool_result: Any,
        tool_name: str,
        tool_id: str,
        messages: List,
        accumulated_citations: List[Dict],
        accumulated_queries: Optional[List[Dict]] = None,
    ) -> None:
        """Process tool result and handle citations."""
        from app.workflow.tools.deep_research import CitedText

        citations: List[Dict] = []
        result_text: str = ""

        is_structured_query = (
            isinstance(tool_result, dict)
            and "sql" in tool_result
            and tool_name.startswith("query_")
        )

        if is_structured_query:
            result_text = tool_result.get("text", str(tool_result))
            if accumulated_queries is not None:
                agent_queries = tool_result.get("queries_executed")
                if agent_queries:
                    for qe in agent_queries:
                        accumulated_queries.append({
                            "question": tool_result.get("question", ""),
                            "sql": qe.get("sql", ""),
                            "tables_used": qe.get("tables_used", []),
                            "row_count": qe.get("row_count", 0),
                            "results": qe.get("results", {"columns": [], "rows": []}),
                        })
                else:
                    accumulated_queries.append({
                        "question": tool_result.get("question", ""),
                        "sql": tool_result.get("sql", ""),
                        "tables_used": tool_result.get("tables_used", []),
                        "row_count": tool_result.get("row_count", 0),
                        "results": tool_result.get("results", {"columns": [], "rows": []}),
                    })
        elif isinstance(tool_result, dict) and 'citations' in tool_result:
            result_text = tool_result.get('text', '')
            citations = tool_result.get('citations', [])
        elif isinstance(tool_result, CitedText) and tool_result.citations:
            result_text = str(tool_result)
            citations = list(tool_result.citations)
        else:
            result_text = str(tool_result)

        if citations:
            for citation in citations:
                citation['citation_number'] = len(accumulated_citations) + 1
                accumulated_citations.append(citation)
            logger.debug("Tool %s returned %d citations (total now: %d)",
                       tool_name, len(citations), len(accumulated_citations))

        messages.append(ToolMessage(content=result_text, tool_call_id=tool_id))
        logger.debug("✅ Tool '%s' executed, result length: %d, citations: %d",
                    tool_name, len(result_text), len(citations))
    
    def _build_result(
        self,
        final_response: Any,
        messages: List,
        state: WorkflowState,
        config: Dict[str, Any],
        accumulated_citations: List[Dict],
        iteration: int,
        accumulated_queries: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Build final result dictionary."""
        # Get only new messages
        original_count = len(state.get("messages", []))
        new_messages = messages[original_count:]
        
        # Filter and process messages
        new_messages_filtered = self._filter_and_process_messages(
            new_messages, final_response, accumulated_citations,
            accumulated_queries or [],
        )
        
        logger.debug(
            "📤 Returning %d new messages (filtered from %d, original state had %d)",
            len(new_messages_filtered), len(new_messages), original_count
        )
        
        # Add agent metadata
        self._add_agent_metadata(new_messages_filtered)
        
        # Extract content
        output = final_response.content if hasattr(final_response, 'content') else str(final_response)
        logger.debug("Agent final response: %s", output[:200])
        
        return {
            "response": output,
            "model": f"{config['model_provider']}/{config['model_name']}",
            "iterations": iteration + 1,
            "messages": new_messages_filtered
        }
    
    def _filter_and_process_messages(
        self,
        messages: List,
        final_response: Any,
        accumulated_citations: List[Dict],
        accumulated_queries: Optional[List[Dict]] = None,
    ) -> List:
        """Filter empty messages and process citations."""
        filtered = []
        
        for msg in messages:
            if msg.__class__.__name__ not in ["HumanMessage", "AIMessage"]:
                continue
            
            if not msg.content or not msg.content.strip():
                logger.warning("🔍 Filtering out empty message: %s", msg.__class__.__name__)
                continue
            
            # Add citations and query traces to final AI message
            if (msg.__class__.__name__ == "AIMessage" and msg == final_response):
                if accumulated_citations:
                    self._add_citations_to_message(msg, accumulated_citations)
                if accumulated_queries:
                    if not hasattr(msg, 'additional_kwargs'):
                        msg.additional_kwargs = {}
                    msg.additional_kwargs['structured_queries'] = accumulated_queries
                    logger.debug(
                        "📊 Attached %d structured query trace(s) to final AI message",
                        len(accumulated_queries),
                    )
            
            filtered.append(msg)
        
        return filtered
    
    def _add_citations_to_message(
        self,
        msg: Any,
        accumulated_citations: List[Dict]
    ) -> None:
        """Add citations to AI message with filtering."""
        if not hasattr(msg, 'additional_kwargs'):
            msg.additional_kwargs = {}
        
        msg.additional_kwargs['citations'] = accumulated_citations
        logger.debug("📚 Added %d citations to final AI message", len(accumulated_citations))
        logger.debug("🔍 CITATION DEBUG - Response text: %s", msg.content[:200])
        
        # Find citation markers
        markers_found = re.findall(r'\[(\d+)\]', msg.content)
        logger.debug("🔍 CITATION DEBUG - Markers found: %s", markers_found)
        
        # Inject if missing
        if not markers_found and accumulated_citations:
            logger.warning("⚠️ LLM did not preserve citation markers! Using citation injection.")
            msg.content = CitationInjector.inject_citations(
                msg.content, accumulated_citations, min_overlap_words=5
            )
            markers_found = re.findall(r'\[(\d+)\]', msg.content)
            logger.debug("✅ Citation injection complete, markers now: %s", markers_found)
        
        # Filter to only used citations
        if markers_found and accumulated_citations:
            used_numbers = set(int(m) for m in markers_found)
            filtered = [c for c in accumulated_citations 
                       if c['citation_number'] in used_numbers]
            logger.debug("🔍 Filtered citations: %d used out of %d total",
                       len(filtered), len(accumulated_citations))
            msg.additional_kwargs['citations'] = filtered
            return

        # Never-silent fallback: LLM stripped every marker and nothing could
        # be matched inline (common for web citations, whose ``chunk_text`` is
        # empty).  Append a compact ``Sources:`` footer with [N] markers so
        # the frontend can still render clickable badges.
        if accumulated_citations:
            web_citations = [
                c for c in accumulated_citations if c.get("type") == "web"
            ]
            if web_citations:
                logger.warning(
                    "⚠️ No inline markers matched — appending Sources footer with "
                    "%d web citation(s)",
                    len(web_citations),
                )
                msg.content = CitationInjector.append_sources_footer(
                    msg.content, web_citations,
                )
                msg.additional_kwargs['citations'] = web_citations
            else:
                logger.warning(
                    "⚠️ LLM dropped all citation markers and injection failed — "
                    "discarding %d KB citation(s)",
                    len(accumulated_citations),
                )
                msg.additional_kwargs['citations'] = []
    
    def _add_agent_metadata(self, messages: List) -> None:
        """Add agent metadata to AI messages."""
        for msg in messages:
            if msg.__class__.__name__ == "AIMessage":
                if not hasattr(msg, 'additional_kwargs'):
                    msg.additional_kwargs = {}
                if 'agent_id' not in msg.additional_kwargs:
                    msg.additional_kwargs['agent_id'] = self.node.node_id
                    msg.additional_kwargs['agent_label'] = self.node.label
                    msg.additional_kwargs['agent_type'] = self.node.node_type
                    msg.additional_kwargs['message_id'] = str(uuid.uuid4())
