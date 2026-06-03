"""
Multi-agent mode tool calling loop with deliverable detection.

Handles:
- LLM initialization with structured output
- Tool execution loop with submit_deliverable + classifier gate
- Citation accumulation
- Deliverable extraction
"""

from typing import Any, Dict, List, Optional, Tuple
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
import logging
import json
import re
import asyncio

from config.llm_config import LLMClientManager, LLMConfig
from app.tracing import TraceSpan, trace_tool_call
from ..state import (
    WorkflowState,
    get_session_id_from_state,
    get_workflow_id_from_state,
    resolve_deliverable_sources,
    format_deliverables_for_prompt,
)
from ..utils.file_context import build_global_file_context
from ..utils.schema_augmentation import inject_summary_field
from ..utils.streaming import (
    classify_chat_stream_release,
    should_stream_chat_responses,
)
from app.tracing.chat_stream import (
    clear_chat_stream_buffer,
    defer_chat_stream,
    flush_chat_stream_buffer,
    reset_defer_chat_stream,
)
from .agent_classifier import (
    classify_readiness,
    route_next_action,
    TOOL_CALLER_BINDING,
    TOOL_CALLER_PROVIDER,
    TOOL_CALLER_TEMPERATURE,
    TOOL_CALLER_MAX_TOKENS,
)
from .agent_multi_instructions import resolve_agent_instructions

logger = logging.getLogger(__name__)

def _deliverable_completion_message(deliverable_data: Any) -> str:
    """User-visible chat text from the deliverable summary field."""
    if isinstance(deliverable_data, dict):
        summary = deliverable_data.get("summary")
        if isinstance(summary, str):
            trimmed = summary.strip()
            if trimmed:
                return trimmed
    return "Deliverable ready."

# Tool Caller context — agent instructions (systemInstructions) are passed
# separately from the Main LLM system prompt to avoid duplicating deliverable blocks.
MAX_SUMMARY_CHARS = 24000
# Chat/reasoning turns should stay concise; 64k encouraged long reasoning chains.
CHAT_TURN_MAX_TOKENS = 8192
# Lightweight auxiliary calls (query planner, ask_user_questions).
FAST_AUX_MAX_TOKENS = 4096


def _extract_text_content(content) -> str:
    """Safely extract text from an LLM response content field.

    Some providers (e.g. litellm proxies) return ``content`` as a list of
    content-block dicts instead of a plain string.  This helper normalises
    both representations to a single stripped string.
    """
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


class MultiAgentLoopExecutor:
    """Executes agent loop with deliverable detection."""
    
    def __init__(self, node):
        """Initialize with parent node reference."""
        self.node = node
    
    async def execute(
        self,
        state: WorkflowState,
        system_instructions: str
    ) -> Dict[str, Any]:
        """Execute the agent using Tool Caller-first + Main LLM architecture.

        Flow:
        1. Tool Caller (Haiku, summarized context) decides the next action.
        2. Tool actions run immediately (KB / structured data / web / DR).
        3. Main LLM runs only when a user-facing chat reply is needed.
        4. submit_deliverable invokes structured output without a prior chat turn.
        """
        config = self.node.node_config or {}
        force_deliver = state.get("force_deliver", False)

        llm = self._init_llm(config)

        tool_names_cfg = config.get("tools", [])
        tools = await self.node._get_tools(tool_names_cfg)
        output_schema_str = config.get("outputSchema", "")
        task_instructions = resolve_agent_instructions(config)
        has_submit_tool = any(
            getattr(t, "name", None) == "submit_deliverable" for t in tools
        )
        tool_name_list = [getattr(t, "name", "unknown") for t in tools]

        messages = await self._prepare_messages(state, system_instructions)
        accumulated_citations: List[Dict] = []
        accumulated_queries: List[Dict] = []

        self._inject_deep_research_context(tools, messages, state, config)

        # Use the Tool Caller architecture when submit_deliverable is
        # available, OR when in chat mode (chat mode skips the tool but
        # still needs the Tool Caller loop for routing instead of the
        # legacy path which would force structured output).
        agent_mode = config.get("agentMode", "regular")
        if has_submit_tool or agent_mode == "chat":
            return await self._execute_with_tool_caller(
                llm, tools, messages, config, force_deliver,
                output_schema_str, task_instructions,
                tool_name_list, accumulated_citations,
                accumulated_queries,
                metadata=state.get("metadata"),
            )

        # -----------------------------------------------------------------
        # LEGACY PATHS (agents without submit_deliverable)
        # -----------------------------------------------------------------
        return await self._execute_legacy(
            llm, tools, messages, output_schema_str, accumulated_citations,
        )

    # ------------------------------------------------------------------
    # Deep research context injection
    # ------------------------------------------------------------------

    def _inject_deep_research_context(
        self,
        tools: List,
        messages: List,
        state: WorkflowState,
        config: Dict[str, Any],
    ) -> None:
        """Set deliverable and chat context on any DeepResearchTool instance.

        Resolves only the deliverables this agent is allowed to see
        (``deliverableSources`` config) and builds a chat summary from
        the agent's filtered messages.  Both are set as fields on the
        tool so ``_build_research_query`` can use them internally.
        """
        dr_tool = next(
            (t for t in tools if getattr(t, "name", "") == "deep_research"),
            None,
        )
        if dr_tool is None:
            return

        deliverables = resolve_deliverable_sources(
            state, self.node.node_id, config,
        )
        if deliverables:
            dr_tool.deliverable_context = format_deliverables_for_prompt(
                deliverables,
            )
            logger.debug(
                "📎 Injected %d deliverable(s) into DeepResearchTool for %s",
                len(deliverables), self.node.label,
            )

        instructions_parts: List[str] = []
        agent_instr = resolve_agent_instructions(config)
        if agent_instr:
            instructions_parts.append(agent_instr)
        if instructions_parts:
            dr_tool.agent_instructions = "\n\n".join(instructions_parts)
            logger.debug(
                "📎 Injected agent instructions (%d chars) into DeepResearchTool for %s",
                len(dr_tool.agent_instructions), self.node.label,
            )

        chat_parts: List[str] = []
        for msg in messages[1:]:
            if not isinstance(msg, HumanMessage):
                continue
            content = getattr(msg, "content", "") or ""
            if not content:
                continue
            kwargs = getattr(msg, "additional_kwargs", None) or {}
            if kwargs.get("is_startup_message"):
                continue
            if content.startswith("[Tool result") or content.startswith("[System]"):
                continue
            snippet = content[:2000]
            chat_parts.append(f"[user] {snippet}")
            if sum(len(p) for p in chat_parts) > 8000:
                break

        if chat_parts:
            dr_tool.agent_chat_summary = "\n---\n".join(chat_parts)
            logger.debug(
                "📎 Injected chat summary (%d user msgs, %d chars) into DeepResearchTool for %s",
                len(chat_parts),
                len(dr_tool.agent_chat_summary),
                self.node.label,
            )

    # ------------------------------------------------------------------
    # NEW: Main LLM + Tool Caller architecture
    # ------------------------------------------------------------------

    def _init_chat_llm(
        self,
        config: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Initialize a token-capped LLM for chat/reasoning turns.

        Uses a low max_tokens so the Main LLM produces concise reasoning
        instead of dumping the entire deliverable into the chat.
        """
        provider = config.get("modelProvider", LLMConfig.DEFAULT_PROVIDER)
        model_name = config.get("modelName", LLMConfig.DEFAULT_MODEL)
        temperature = config.get("temperature", LLMConfig.DEFAULT_TEMPERATURE)
        stream_chat = should_stream_chat_responses(
            node_config=config,
            node_type=self.node.node_type,
            metadata=metadata,
        )
        chat_llm = LLMClientManager.get_client(
            provider,
            model_name,
            temperature,
            CHAT_TURN_MAX_TOKENS,
            streaming=True,
            stream_chat=stream_chat,
            llm_role="main_llm",
        )
        logger.debug(
            "🔧 Initialized CHAT LLM: %s/%s (max_tokens=%d, stream_chat=%s)",
            provider, model_name, CHAT_TURN_MAX_TOKENS, stream_chat,
        )
        return chat_llm

    async def _invoke_chat_turn(
        self,
        chat_llm: Any,
        messages: List,
        config: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        *,
        iteration: int = 0,
    ) -> str:
        """Run the Main LLM for a user-facing chat reply (streaming when enabled)."""
        logger.debug(
            "📝 Main LLM invoked for %s (iteration %d, %d messages)",
            self.node.label, iteration, len(messages),
        )
        stream_to_ui = should_stream_chat_responses(
            node_config=config,
            node_type=self.node.node_type,
            metadata=metadata,
        )
        defer_token = defer_chat_stream() if stream_to_ui else None
        try:
            response = await chat_llm.ainvoke(messages)
            chat_content = (
                _extract_text_content(response.content)
                if hasattr(response, "content") and response.content
                else ""
            )
            messages.append(response)
            logger.debug(
                "📝 Main LLM response for %s (iteration %d): %d chars",
                self.node.label, iteration, len(chat_content),
            )
            if stream_to_ui:
                await flush_chat_stream_buffer()
            return chat_content
        finally:
            if defer_token is not None:
                reset_defer_chat_stream(defer_token)

    def _init_fast_aux_llm(self) -> Any:
        """Fast model for routing-adjacent tasks (questions, query planning)."""
        return LLMClientManager.get_client_for_binding(
            TOOL_CALLER_BINDING,
            temperature=TOOL_CALLER_TEMPERATURE,
            max_tokens=FAST_AUX_MAX_TOKENS,
            streaming=False,
            stream_chat=False,
            llm_role="tool_decider",
        )

    def _init_deliverable_llm(self, config: Dict[str, Any]) -> Any:
        """LLM for structured deliverable synthesis (may differ from chat model)."""
        d_provider = config.get("deliverableModelProvider")
        d_model = config.get("deliverableModelName")
        if d_provider and d_model:
            temperature = config.get("temperature", LLMConfig.DEFAULT_TEMPERATURE)
            max_tokens = config.get("maxTokens") or LLMConfig.DEFAULT_MAX_TOKENS
            if (max_tokens or 0) < 64000:
                max_tokens = 64000
            llm = LLMClientManager.get_client(
                d_provider, d_model, temperature, max_tokens,
                llm_role="deliverable_llm",
            )
            logger.debug(
                "🔧 Deliverable LLM: %s/%s (max_tokens=%d)",
                d_provider, d_model, max_tokens,
            )
            return llm
        return self._init_llm(config)

    @staticmethod
    def _should_auto_one_shot(tools: List, config: Dict[str, Any]) -> bool:
        """KB-only agents with a deliverable schema: skip the Tool Caller loop."""
        if config.get("agentMode", "regular") != "regular":
            return False
        if config.get("autoKbOneShot") is False:
            return False
        if not config.get("outputSchema"):
            return False

        names = [getattr(t, "name", "") for t in tools if getattr(t, "name", "")]
        if not names:
            return False
        if "ask_user_questions" in names:
            return False
        if any(n in ("deep_research", "simple_web_search") for n in names):
            return False
        if any(n.startswith("query_") for n in names):
            return False

        has_kb = any(
            n.startswith("search_") or n.startswith("research_") for n in names
        )
        if not has_kb:
            return False

        non_kb = [
            n for n in names
            if not n.startswith(("search_", "research_"))
            and n != "submit_deliverable"
        ]
        return len(non_kb) == 0

    @staticmethod
    def _is_kb_only_agent(tools: List) -> bool:
        """True when the only data tools are KB search/research."""
        names = [getattr(t, "name", "") for t in tools if getattr(t, "name", "")]
        has_kb = any(
            n.startswith("search_") or n.startswith("research_") for n in names
        )
        if not has_kb:
            return False
        return not any(
            n.startswith("query_")
            or n in ("deep_research", "simple_web_search", "ask_user_questions")
            for n in names
        )

    async def _generate_questions_payload(
        self,
        chat_llm: Any,
        messages: List,
        chat_content: str,
        task_instructions: str,
        *,
        suppress_chat_stream: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Force the Main LLM to emit a structured ``ask_user_questions`` payload.

        Re-invokes the chat LLM with the tool bound and forced, then validates
        the returned args against the same Pydantic schema used everywhere
        else.  Returns the validated payload as a plain dict, or ``None`` if
        the LLM didn't produce a usable tool call.
        """
        from app.workflow.tools.ask_user_questions import (
            AskUserQuestionsInput,
            AskUserQuestionsTool,
            normalize_questions_payload,
        )

        tool = AskUserQuestionsTool()

        nudge_lines = [
            "You MUST call the ask_user_questions tool now.",
            "Do not respond with plain text — emit a tool_call.",
            "",
            "Build a short structured questionnaire (1–10 questions). Include",
            "only questions you actually need answered to make progress.",
            "",
            "For each question:",
            "- Use type='single_choice' (or 'multi_choice' if several apply)",
            "  whenever the user can pick from known options — list 2–8 options",
            "  in the options array. Never use type='text' for pick-one questions.",
            "- Do NOT include catch-all options ('Other', 'Something else',",
            "  'Or something else?', 'I don't know', 'None of the above') —",
            "  the UI adds 'I don't know' plus a free-text row on every MCQ.",
            "- Use type='text' ONLY for genuinely open-ended answers (names,",
            "  long descriptions) with no reasonable preset list.",
            "- Mark required=true only for questions you truly need.",
        ]
        if (chat_content or "").strip():
            nudge_lines.extend([
                "",
                "Your previous draft of these questions in plain text was:",
                f"\"\"\"{chat_content.strip()[:1200]}\"\"\"",
                "Reuse that intent — don't ask different questions.",
            ])
        nudge = HumanMessage(content="\n".join(nudge_lines))

        # ``bind_tools`` doesn't validate ``tool_choice`` — providers do that
        # at invocation time. Try formats in order and only stop on a
        # successful call. OpenAI/litellm spec first since most providers
        # are reached via litellm proxies.
        tool_choice_attempts: List[Any] = [
            {"type": "function", "function": {"name": tool.name}},
            {"type": "tool", "name": tool.name},
            tool.name,
            "required",
            "any",
            None,
        ]

        response = None
        last_error: Optional[Exception] = None
        defer_token = defer_chat_stream() if suppress_chat_stream else None
        try:
            for tc in tool_choice_attempts:
                try:
                    bound = (
                        chat_llm.bind_tools([tool])
                        if tc is None
                        else chat_llm.bind_tools([tool], tool_choice=tc)
                    )
                except Exception as e:
                    last_error = e
                    logger.debug(
                        "ask_user_questions: bind_tools(tool_choice=%r) failed: %s",
                        tc, str(e)[:200],
                    )
                    continue
                try:
                    response = await bound.ainvoke(messages + [nudge])
                    logger.debug(
                        "ask_user_questions: invocation succeeded with tool_choice=%r",
                        tc,
                    )
                    break
                except Exception as e:
                    last_error = e
                    logger.debug(
                        "ask_user_questions: ainvoke(tool_choice=%r) failed: %s",
                        tc, str(e)[:300],
                    )
                    response = None
                    continue
        finally:
            if defer_token is not None:
                clear_chat_stream_buffer()
                reset_defer_chat_stream(defer_token)

        if response is None:
            logger.warning(
                "ask_user_questions: all tool_choice formats failed; last error: %s",
                last_error,
            )
            return None

        tool_calls = getattr(response, "tool_calls", None) or []
        call = next(
            (tc for tc in tool_calls if (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)) == tool.name),
            None,
        )
        if not call:
            logger.warning(
                "ask_user_questions: LLM did not emit a tool_call (%d total calls); "
                "falling back to chat. Response preview: %s",
                len(tool_calls),
                _extract_text_content(getattr(response, "content", ""))[:200],
            )
            return None

        raw_args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {}) or {}
        try:
            validated = AskUserQuestionsInput(**raw_args)
            return validated.model_dump(exclude_none=False)
        except Exception as e:
            logger.warning(
                "ask_user_questions: strict validation failed (%s); "
                "attempting lenient normalization. raw=%s",
                e, str(raw_args)[:300],
            )
            payload = normalize_questions_payload(raw_args)
            if payload:
                return payload
            logger.error(
                "ask_user_questions: could not salvage payload from LLM args"
            )
            return None

    async def _execute_with_tool_caller(
        self,
        llm: Any,
        tools: List,
        messages: List,
        config: Dict[str, Any],
        force_deliver: bool,
        output_schema_str: str,
        task_instructions: str,
        tool_name_list: List[str],
        accumulated_citations: List[Dict],
        accumulated_queries: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Core loop: Tool Caller routes first; Main LLM only for chat replies."""
        if accumulated_queries is None:
            accumulated_queries = []
        max_iterations = config.get("maxToolIterations", 5)

        chat_llm = self._init_chat_llm(config, metadata)

        logger.debug(
            "🔀 Tool Caller mode for %s | tools: %s | force_deliver: %s",
            self.node.label, tool_name_list, force_deliver,
        )

        agent_mode = config.get("agentMode", "regular")
        if self._should_auto_one_shot(tools, config):
            logger.info(
                "⚡ Auto one-shot for KB-only agent %s (skipping Tool Caller loop)",
                self.node.label,
            )
            agent_mode = "one_shot"

        if agent_mode == "one_shot":
            logger.info(
                "🎯 One Shot mode for %s: producing deliverable",
                self.node.label,
            )

            has_kb = any(
                getattr(t, "name", "").startswith(("search_", "research_"))
                for t in tools
            )
            has_sd = any(
                getattr(t, "name", "").startswith("query_") for t in tools
            )
            has_dr = any(
                getattr(t, "name", "") == "deep_research" for t in tools
            )
            has_ws = any(
                getattr(t, "name", "") == "simple_web_search" for t in tools
            )

            dr_deliverable = None
            if has_kb or has_sd or has_dr or has_ws:
                query = await self._generate_tool_query(
                    self._init_fast_aux_llm(), messages, task_instructions,
                )
                dr_deliverable = await self._execute_all_tools_parallel(
                    query, tools, messages, task_instructions,
                    accumulated_citations, accumulated_queries,
                    has_kb, has_sd, has_dr, has_ws,
                )

            if dr_deliverable is not None:
                logger.info(
                    "📦 One-shot: using DR pre-built deliverable for %s "
                    "(%d citations)",
                    self.node.label, len(accumulated_citations),
                )
                return {
                    "chat": "Deep research complete. Here is the structured deliverable.",
                    "deliverable": dr_deliverable,
                    "response": "Deep research complete. Here is the structured deliverable.",
                    "citations": accumulated_citations,
                    "structured_queries": accumulated_queries,
                }

            deliverable_llm = self._init_deliverable_llm(config)
            result = await self._produce_deliverable(
                deliverable_llm, tools, messages, accumulated_citations,
            )
            result["structured_queries"] = accumulated_queries
            return result

        if force_deliver:
            logger.info("🔒 force_deliver: skipping to deliverable production")
            deliverable_llm = self._init_deliverable_llm(config)
            result = await self._produce_deliverable(
                deliverable_llm, tools, messages, accumulated_citations,
            )
            result["structured_queries"] = accumulated_queries
            return result

        if self._user_requests_deliverable(messages):
            logger.debug(
                "🔒 User explicitly requested deliverable for %s — "
                "skipping Tool Caller and producing output",
                self.node.label,
            )
            deliverable_llm = self._init_deliverable_llm(config)
            result = await self._produce_deliverable(
                deliverable_llm, tools, messages, accumulated_citations,
            )
            result["structured_queries"] = accumulated_queries
            return result

        has_researcher = any(
            getattr(t, "name", "").startswith("research_") for t in tools
        )
        max_kb_searches = 2 if has_researcher else max_iterations
        kb_search_count = 0
        if has_researcher:
            logger.debug(
                "🔬 Agentic researcher detected — KB searches capped at %d per run",
                max_kb_searches,
            )

        parallel_kb = config.get("parallelKBSearch", False)
        has_kb_tool = any(
            getattr(t, "name", "").startswith(("search_", "research_"))
            for t in tools
        )
        has_sd_tool = any(
            getattr(t, "name", "").startswith("query_") for t in tools
        )
        use_parallel = parallel_kb and has_kb_tool and has_sd_tool
        if use_parallel:
            logger.debug(
                "⚡ Parallel KB search enabled for %s — "
                "search_kb and query_structured_data will fire concurrently",
                self.node.label,
            )

        kb_metadata_desc = ""
        for t in tools:
            schema = getattr(t, "metadata_schema", None)
            if not schema and hasattr(t, "func"):
                inner = getattr(t.func, "__self__", None) or getattr(t, "_run", None)
                if inner:
                    schema = getattr(inner, "metadata_schema", None)
            if schema:
                kb_metadata_desc = getattr(t, "_build_metadata_desc", lambda: "")()
                if not kb_metadata_desc:
                    desc_fn = getattr(
                        getattr(t, "func", None), "__self__", None
                    )
                    if desc_fn and hasattr(desc_fn, "_build_metadata_desc"):
                        kb_metadata_desc = desc_fn._build_metadata_desc()
                break

        structured_data_desc = self._extract_structured_data_desc(tools)

        stream_to_ui = should_stream_chat_responses(
            node_config=config,
            node_type=self.node.node_type,
            metadata=metadata,
        )

        for iteration in range(1, max_iterations + 1):
            logger.debug(
                "🔁 Iteration %d/%d for %s",
                iteration, max_iterations, self.node.label,
            )

            # Phase 1: Tool Caller decides next action (before Main LLM)
            summarized = self._summarize_messages(messages)
            logger.debug(
                "🔀 Tool Caller first for %s: %d summarized msgs, %d total chars",
                self.node.label, len(summarized),
                sum(len(s) for s in summarized),
            )
            async with TraceSpan(
                "tool_decider",
                label="Tool Caller",
                payload={
                    "available_tools": tool_name_list,
                    "iteration": iteration,
                    "recent_message_count": len(summarized),
                },
            ) as decider_span:
                action = await route_next_action(
                    task_instructions=task_instructions,
                    output_schema_summary=output_schema_str,
                    available_tools=tool_name_list,
                    recent_messages=summarized,
                    metadata_schema_desc=kb_metadata_desc,
                    structured_data_desc=structured_data_desc,
                )
                decider_span.add_payload(action=action)
            action_type = action.get("action", "chat")
            logger.debug(
                "🔀 Tool Caller → %s for %s (iteration %d) | full action: %s",
                action_type, self.node.label, iteration, json.dumps(action),
            )

            # Proactive KB: first turn with user input should search, not stall on chat
            if (
                action_type == "chat"
                and iteration == 1
                and has_kb_tool
                and kb_search_count < max_kb_searches
            ):
                last_user = ""
                for msg in reversed(messages):
                    if isinstance(msg, HumanMessage):
                        last_user = _extract_text_content(msg.content)
                        if last_user and not last_user.startswith("[Tool result"):
                            break
                        last_user = ""
                if last_user:
                    logger.info(
                        "🔄 Overriding Tool Caller 'chat' → 'search_kb' for %s "
                        "(first turn with user input, no prior search: %s)",
                        self.node.label, last_user[:100],
                    )
                    action_type = "search_kb"
                    action = {"action": "search_kb", "query": last_user}

            if stream_to_ui:
                release = classify_chat_stream_release(
                    action_type,
                    agent_mode=agent_mode,
                )
                if release == "clear":
                    clear_chat_stream_buffer()

            # --- ASK_USER_QUESTIONS: questionnaire without a prior Main LLM turn ---
            if action_type == "ask_user_questions":
                async with TraceSpan(
                    "ask_questions",
                    label="Ask Questions",
                    payload={"iteration": iteration},
                ) as ask_span:
                    questions_payload = await self._generate_questions_payload(
                        self._init_fast_aux_llm(),
                        messages,
                        "",
                        task_instructions,
                        suppress_chat_stream=True,
                    )
                    ask_span.add_payload(
                        question_count=len((questions_payload or {}).get("questions") or [])
                    )
                if questions_payload:
                    intro_text = (questions_payload.get("intro") or "").strip()
                    return {
                        "chat": intro_text,
                        "questions": questions_payload,
                        "deliverable": None,
                        "response": intro_text,
                        "citations": accumulated_citations,
                        "structured_queries": accumulated_queries,
                    }
                logger.warning(
                    "ask_user_questions: payload generation failed for %s — "
                    "falling back to Main LLM chat",
                    self.node.label,
                )
                action_type = "chat"

            # --- SUBMIT_DELIVERABLE: produce structured output ---
            if action_type == "submit_deliverable":
                agent_mode = config.get("agentMode", "regular")
                if agent_mode == "chat":
                    logger.debug(
                        "🔒 Chat mode: blocking Tool Caller submit_deliverable "
                        "for %s — only user can force deliver",
                        self.node.label,
                    )
                    final_content = await self._invoke_chat_turn(
                        chat_llm, messages, config, metadata, iteration=iteration,
                    )
                    if not final_content:
                        final_content = (
                            "I've reviewed the available information. "
                            "Could you provide more details so I can proceed?"
                        )
                    return {
                        "chat": final_content,
                        "deliverable": None,
                        "response": final_content,
                        "citations": accumulated_citations,
                        "structured_queries": accumulated_queries,
                    }
                deliverable_llm = self._init_deliverable_llm(config)
                result = await self._produce_deliverable(
                    deliverable_llm, tools, messages, accumulated_citations,
                )
                result["structured_queries"] = accumulated_queries
                return result

            # --- PARALLEL: fire both KB search + structured data concurrently ---
            if use_parallel and action_type in ("search_kb", "query_structured_data"):
                query = action.get("query") or action.get("question", "")
                if not query:
                    logger.warning(
                        "Tool Caller returned %s with empty query in parallel mode",
                        action_type,
                    )
                    continue

                if kb_search_count >= max_kb_searches:
                    logger.debug(
                        "⚡ Parallel mode but KB search cap reached (%d/%d) — "
                        "falling through to serial query_structured_data",
                        kb_search_count, max_kb_searches,
                    )
                else:
                    kb_coro = self._execute_routed_tool(
                        "search_kb", query, tools,
                        metadata_filters=action.get("metadata_filters"),
                        document_name=action.get("document_name"),
                    )
                    sd_coro = self._execute_routed_tool(
                        "query_structured_data", query, tools,
                        table_name=action.get("table_name"),
                        context=task_instructions,
                    )

                    (kb_text, kb_cites, _, _), (sd_text, _, _, query_meta) = (
                        await asyncio.gather(kb_coro, sd_coro)
                    )

                    for c in kb_cites:
                        c["citation_number"] = len(accumulated_citations) + 1
                        accumulated_citations.append(c)

                    if query_meta:
                        if isinstance(query_meta, list):
                            accumulated_queries.extend(query_meta)
                        else:
                            accumulated_queries.append(query_meta)

                    combined = (
                        f"[Tool result from search_kb]:\n{kb_text}\n\n"
                        f"[Tool result from query_structured_data]:\n{sd_text}"
                    )
                    messages.append(HumanMessage(content=combined))

                    kb_search_count += 1
                    logger.debug(
                        "⚡ Parallel search completed for %s | KB search %d/%d",
                        self.node.label, kb_search_count, max_kb_searches,
                    )
                    continue

            # --- QUERY_STRUCTURED_DATA: execute structured query tool ---
            if action_type == "query_structured_data":
                question = action.get("question", "")
                if not question:
                    logger.warning("Tool Caller returned query_structured_data with empty question")
                    continue
                tool_result, citations, _, query_meta = await self._execute_routed_tool(
                    action_type, question, tools,
                    table_name=action.get("table_name"),
                    context=task_instructions,
                )
                if query_meta:
                    if isinstance(query_meta, list):
                        accumulated_queries.extend(query_meta)
                    else:
                        accumulated_queries.append(query_meta)
                for c in citations:
                    c["citation_number"] = len(accumulated_citations) + 1
                    accumulated_citations.append(c)
                messages.append(HumanMessage(
                    content=f"[Tool result from query_structured_data]:\n{tool_result}"
                ))
                continue

            # --- SIMPLE_WEB_SEARCH: execute web search tool ---
            if action_type == "simple_web_search":
                query = action.get("query", "")
                if not query:
                    logger.warning("Tool Caller returned simple_web_search with empty query")
                    continue
                tool_result, citations, _, _ = await self._execute_routed_tool(
                    action_type, query, tools,
                )
                for c in citations:
                    c["citation_number"] = len(accumulated_citations) + 1
                    accumulated_citations.append(c)
                messages.append(HumanMessage(
                    content=f"[Tool result from simple_web_search]:\n{tool_result}"
                ))
                continue

            # --- SEARCH_KB / DEEP_RESEARCH: execute tool ---
            if action_type in ("search_kb", "deep_research"):
                query = action.get("query", "")
                if not query:
                    logger.warning("Tool Caller returned %s with empty query", action_type)
                    continue

                if action_type == "search_kb" and kb_search_count >= max_kb_searches:
                    logger.debug(
                        "🔒 KB search cap reached (%d/%d) for %s — "
                        "skipping additional search_kb, continuing loop",
                        kb_search_count, max_kb_searches, self.node.label,
                    )
                    messages.append(HumanMessage(
                        content=(
                            "[System]: Knowledge base research is complete. "
                            "No further KB searches are available. Use the "
                            "research findings already collected to proceed."
                        )
                    ))
                    continue

                meta_filters = action.get("metadata_filters")
                doc_name = action.get("document_name")
                tool_result, citations, tool_deliverable, _ = await self._execute_routed_tool(
                    action_type, query, tools,
                    metadata_filters=meta_filters,
                    document_name=doc_name,
                )

                citation_offset = len(accumulated_citations)
                for c in citations:
                    c["citation_number"] = len(accumulated_citations) + 1
                    accumulated_citations.append(c)

                if tool_deliverable is not None:
                    if citation_offset > 0:
                        tool_deliverable = self._renumber_deliverable_markers(
                            tool_deliverable, citation_offset
                        )
                    logger.debug(
                        "📦 Deep research produced structured deliverable for %s — "
                        "bypassing Tool Caller and returning directly",
                        self.node.label,
                    )
                    return {
                        "chat": "Deep research complete. Here is the structured deliverable.",
                        "deliverable": tool_deliverable,
                        "response": "Deep research complete. Here is the structured deliverable.",
                        "citations": accumulated_citations,
                        "structured_queries": accumulated_queries,
                    }

                if action_type == "search_kb":
                    kb_search_count += 1
                    logger.debug(
                        "🔍 KB search %d/%d completed for %s",
                        kb_search_count, max_kb_searches, self.node.label,
                    )

                messages.append(HumanMessage(
                    content=f"[Tool result from {action_type}]:\n{tool_result}"
                ))

                if (
                    action_type == "search_kb"
                    and self._is_kb_only_agent(tools)
                    and self.node.get_config_value("outputSchema", "")
                ):
                    logger.info(
                        "⚡ KB-only agent %s: producing deliverable after research pass",
                        self.node.label,
                    )
                    deliverable_llm = self._init_deliverable_llm(config)
                    result = await self._produce_deliverable(
                        deliverable_llm, tools, messages, accumulated_citations,
                    )
                    result["structured_queries"] = accumulated_queries
                    return result

                continue

            # --- CHAT: Main LLM produces the user-facing reply ---
            if action_type == "chat":
                final_content = await self._invoke_chat_turn(
                    chat_llm, messages, config, metadata, iteration=iteration,
                )
                if not final_content:
                    final_content = (
                        "I've reviewed the available information. "
                        "Could you provide more details so I can proceed?"
                    )
                return {
                    "chat": final_content,
                    "deliverable": None,
                    "response": final_content,
                    "citations": accumulated_citations,
                    "structured_queries": accumulated_queries,
                }

        # Exhausted iterations without a resolution — return last chat
        logger.warning(
            "⚠️ Exhausted %d iterations for %s without deliverable",
            max_iterations, self.node.label,
        )
        last_content = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                last_content = _extract_text_content(msg.content)
                break
        return {
            "chat": last_content or "I need more information to proceed.",
            "deliverable": None,
            "response": last_content or "I need more information to proceed.",
            "citations": accumulated_citations,
            "structured_queries": accumulated_queries,
        }

    async def _produce_deliverable(
        self,
        llm: Any,
        tools: List,
        messages: List,
        accumulated_citations: List[Dict],
    ) -> Dict[str, Any]:
        """Produce a structured deliverable using JSON-mode structured output.

        The user schema is resolved (refs inlined) and passed directly — no
        ``chat``/``outputDeliverable`` wrapper — so the LLM response IS the
        deliverable.
        """
        output_schema_str = self.node.get_config_value("outputSchema", "")
        if not output_schema_str:
            logger.error("❌ No outputSchema configured for %s", self.node.label)
            return {
                "chat": "Unable to produce deliverable — no output schema configured.",
                "deliverable": None,
                "response": "Unable to produce deliverable — no output schema configured.",
                "citations": accumulated_citations,
            }

        user_schema = (
            json.loads(output_schema_str)
            if isinstance(output_schema_str, str)
            else output_schema_str
        )
        resolved_schema = self._resolve_schema_refs(user_schema)
        resolved_schema = self._fix_array_schemas(resolved_schema)
        resolved_schema = inject_summary_field(resolved_schema)
        if "title" not in resolved_schema:
            resolved_schema["title"] = "Deliverable"
        resolved_schema["title"] = re.sub(
            r"[^a-zA-Z0-9_-]", "_", resolved_schema["title"]
        )

        logger.debug(
            "📦 Producing deliverable for %s | schema top-level keys: %s",
            self.node.label,
            list(resolved_schema.get("properties", {}).keys()),
        )
        schema_text = json.dumps(resolved_schema, indent=2)

        citation_instruction = ""
        if accumulated_citations:
            citation_instruction = (
                "\n\nCITATION RULES (MANDATORY):\n"
                "The research results above contain numbered citation markers "
                "like [1], [2], etc. You MUST preserve these markers in your "
                "output. Include them inline in every text field where the "
                "source information is used. Do NOT remove, renumber, or "
                "rephrase citation markers. They link to the sources list "
                "returned alongside this deliverable.\n"
            )

        messages.append(HumanMessage(content=(
            "Now produce your FINAL structured deliverable.\n"
            "Use ALL context available to you (system instructions, previous "
            "agent deliverables, conversation history, and any research "
            "results). Even if information is incomplete, populate every "
            "field with the best content you can.\n\n"
            f"{citation_instruction}"
            "You MUST respond with a JSON object matching this EXACT schema:\n"
            f"```json\n{schema_text}\n```"
        )))

        model_name = getattr(llm, "model_name", "") or getattr(llm, "model", "") or ""
        is_gemini = "gemini" in model_name.lower() or "vertex_ai" in model_name.lower()
        method = "json_mode" if is_gemini else "function_calling"

        structured_llm = llm.with_structured_output(
            schema=resolved_schema, method=method, include_raw=True,
        )
        response = await structured_llm.ainvoke(messages)
        response = self._unwrap_structured_response(response)

        deliverable = None
        if isinstance(response, dict) and response:
            deliverable = response
        elif hasattr(response, "content"):
            try:
                parsed = (
                    json.loads(response.content)
                    if isinstance(response.content, str)
                    else response.content
                )
                if isinstance(parsed, dict) and parsed:
                    deliverable = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        if deliverable:
            logger.debug(
                "✅ Deliverable produced with keys %s for %s",
                list(deliverable.keys()), self.node.label,
            )
            completion = _deliverable_completion_message(deliverable)
            return {
                "chat": completion,
                "deliverable": deliverable,
                "response": completion,
                "citations": accumulated_citations,
            }

        logger.error(
            "❌ Structured output produced no deliverable for %s | raw type: %s",
            self.node.label, type(response),
        )
        return {
            "chat": "Unable to produce deliverable at this time.",
            "deliverable": None,
            "response": "Unable to produce deliverable at this time.",
            "citations": accumulated_citations,
        }

    # ------------------------------------------------------------------
    # One-shot parallel tool helpers
    # ------------------------------------------------------------------

    async def _generate_tool_query(
        self,
        planner_llm: Any,
        messages: List,
        task_instructions: str,
    ) -> str:
        """Generate a focused search query from the conversation context.

        Uses a single lightweight LLM call (Haiku by default) so one-shot mode
        can feed a concise query to every data-gathering tool without a Tool
        Caller. Falls back to the last user message if the call fails.
        """
        last_user_msg = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and msg.content:
                last_user_msg = _extract_text_content(msg.content)
                break

        prompt = (
            "You are a query planner. Given the task instructions and "
            "conversation below, produce a SINGLE concise search query "
            "(1-2 sentences) that captures the key information need.\n\n"
            f"Task instructions:\n{task_instructions}\n\n"
            f"Latest user message:\n{last_user_msg}\n\n"
            "Respond with ONLY the search query, nothing else."
        )

        try:
            response = await planner_llm.ainvoke(
                [HumanMessage(content=prompt)]
            )
            query = _extract_text_content(response.content) if response.content else ""
            if query:
                logger.debug(
                    "🔎 One-shot query planner produced: %s", query[:200],
                )
                return query
        except Exception as exc:
            logger.warning(
                "⚠️ One-shot query planner failed for %s: %s — "
                "falling back to last user message",
                self.node.label, exc,
            )

        return last_user_msg or task_instructions[:500]

    async def _execute_all_tools_parallel(
        self,
        query: str,
        tools: List,
        messages: List,
        task_instructions: str,
        accumulated_citations: List[Dict],
        accumulated_queries: List[Dict],
        has_kb: bool,
        has_sd: bool,
        has_dr: bool,
        has_ws: bool = False,
    ) -> Optional[Dict]:
        """Fire all available data-gathering tools in parallel.

        Results are appended to *messages* in-place so that the subsequent
        ``_produce_deliverable`` call has the enriched context.

        Returns the deep-research pre-built deliverable when available so
        the caller can use it directly instead of re-generating.
        """
        coros = []
        labels = []

        if has_kb:
            coros.append(self._execute_routed_tool("search_kb", query, tools))
            labels.append("search_kb")

        if has_sd:
            coros.append(
                self._execute_routed_tool(
                    "query_structured_data", query, tools,
                    context=task_instructions,
                )
            )
            labels.append("query_structured_data")

        if has_dr:
            coros.append(self._execute_routed_tool("deep_research", query, tools))
            labels.append("deep_research")

        if has_ws:
            coros.append(self._execute_routed_tool("simple_web_search", query, tools))
            labels.append("simple_web_search")

        if not coros:
            return None

        logger.info(
            "⚡ One-shot parallel tool execution for %s — firing: %s",
            self.node.label, labels,
        )

        results = await asyncio.gather(*coros, return_exceptions=True)

        combined_parts: List[str] = []
        dr_deliverable: Optional[Dict] = None

        for label, result in zip(labels, results):
            if isinstance(result, Exception):
                logger.warning(
                    "⚠️ One-shot tool %s failed for %s: %s",
                    label, self.node.label, result,
                )
                continue

            text, citations, deliverable, query_meta = result

            if deliverable is not None and label == "deep_research":
                dr_deliverable = deliverable
                logger.debug(
                    "📦 One-shot: captured DR deliverable with %d keys for %s",
                    len(deliverable), self.node.label,
                )

            for c in citations:
                c["citation_number"] = len(accumulated_citations) + 1
                accumulated_citations.append(c)

            if query_meta:
                if isinstance(query_meta, list):
                    accumulated_queries.extend(query_meta)
                else:
                    accumulated_queries.append(query_meta)

            if text:
                combined_parts.append(f"[Tool result from {label}]:\n{text}")

        if combined_parts:
            messages.append(HumanMessage(content="\n\n".join(combined_parts)))
            logger.debug(
                "📎 Appended %d tool results to messages for %s",
                len(combined_parts), self.node.label,
            )

        return dr_deliverable

    async def _execute_routed_tool(
        self,
        action_type: str,
        query: str,
        tools: List,
        metadata_filters: Optional[list] = None,
        document_name: Optional[str] = None,
        table_name: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Tuple[str, List[Dict], Optional[Dict], Optional[Any]]:
        """Execute a tool chosen by the Tool Caller.

        Returns ``(text, citations, deliverable, query_metadata)``.

        For ``search_kb`` and ``query_structured_data`` we fan out across
        every matching tool (multi-KB support) and merge the results.
        Citation markers are renumbered into a single 1..N sequence so
        the merged text is internally consistent.
        """
        citations: List[Dict] = []

        if action_type == "simple_web_search":
            ws_tool = next(
                (t for t in tools if getattr(t, "name", "") == "simple_web_search"),
                None,
            )
            if not ws_tool:
                return "Simple web search tool not available.", citations, None, None
            logger.debug("🌐 Executing simple web search: %s", query[:100])
            result = await self._invoke_tool(ws_tool, {"query": query})
            if isinstance(result, dict):
                text = result.get("text", str(result))
                citations = result.get("citations", [])
            else:
                text = str(result)
            return text, citations, None, None

        if action_type == "search_kb":
            kb_tools = [
                t for t in tools
                if getattr(t, "name", "").startswith("search_")
                or getattr(t, "name", "").startswith("research_")
            ]
            if not kb_tools:
                return "No knowledge base tool available.", citations, None, None
            return await self._fanout_kb_search(
                kb_tools, query, document_name, metadata_filters,
            )

        if action_type == "deep_research":
            dr_tool = next(
                (t for t in tools if getattr(t, "name", "") == "deep_research"),
                None,
            )
            if not dr_tool:
                return "Deep research tool not available.", citations, None, None

            logger.debug("🔬 Executing deep research: %s", query[:300])
            result = await self._invoke_tool(dr_tool, {"query": query})

            from app.workflow.tools.deep_research import CitedText
            deliverable = None
            if isinstance(result, CitedText):
                text = str(result)
                citations = list(result.citations) if result.citations else []
                if result.deliverable:
                    deliverable = result.deliverable
                    logger.debug(
                        "📦 Deep research returned pre-built deliverable with %d keys",
                        len(deliverable),
                    )
            elif isinstance(result, dict):
                text = result.get("text", str(result))
                citations = result.get("citations", [])
            else:
                text = str(result)
            return text, citations, deliverable, None

        if action_type == "query_structured_data":
            sd_tools = [
                t for t in tools if getattr(t, "name", "").startswith("query_")
            ]
            if not sd_tools:
                return "No structured data query tool available.", citations, None, None
            return await self._fanout_structured_query(
                sd_tools, query, table_name, context,
            )

        return f"Unknown action type: {action_type}", citations, None, None

    # ------------------------------------------------------------------
    # Multi-KB fan-out helpers
    # ------------------------------------------------------------------

    async def _fanout_kb_search(
        self,
        kb_tools: List,
        query: str,
        document_name: Optional[str],
        metadata_filters: Optional[list],
    ) -> Tuple[str, List[Dict], Optional[Dict], Optional[Any]]:
        """Run every KB search/research tool in parallel and merge results.

        With a single KB this collapses to the original direct-invocation
        path.  With multiple KBs we invoke them concurrently and merge
        their text + citations into a single response, renumbering the
        ``[N]`` markers so the merged stream is internally consistent.
        """
        tool_args: Dict[str, Any] = {"query": query}
        if document_name:
            tool_args["document_name"] = document_name
        if metadata_filters:
            tool_args["metadata_filters"] = metadata_filters

        if len(kb_tools) == 1:
            tool = kb_tools[0]
            logger.debug(
                "🔍 Executing KB search on %s: %s | document_name=%s | filters=%d",
                getattr(tool, "name", "unknown"),
                query[:100],
                document_name or "all",
                len(metadata_filters) if metadata_filters else 0,
            )
            result = await self._invoke_tool(tool, tool_args)
            text, citations = self._unpack_kb_result(result)
            return text, citations, None, None

        logger.debug(
            "🔍 Fanning out KB search to %d tools (%s) for query: %s",
            len(kb_tools),
            [getattr(t, "name", "?") for t in kb_tools],
            query[:100],
        )
        coros = [self._invoke_tool(tool, tool_args) for tool in kb_tools]
        results = await asyncio.gather(*coros, return_exceptions=True)

        merged_parts: List[str] = []
        merged_citations: List[Dict] = []
        offset = 0
        for tool, result in zip(kb_tools, results):
            tool_name = getattr(tool, "name", "kb_tool")
            if isinstance(result, Exception):
                logger.warning("⚠️ KB tool %s failed: %s", tool_name, result)
                merged_parts.append(f"### {tool_name}: error — {result}")
                continue
            text, cites = self._unpack_kb_result(result)
            text, cites = self._shift_citations(text, cites, offset)
            offset += len(cites)
            merged_citations.extend(cites)
            if text and text.strip():
                merged_parts.append(f"### Results from {tool_name}\n{text}")

        merged_text = "\n\n".join(merged_parts) if merged_parts else (
            "No results returned from any of the configured knowledge bases."
        )
        return merged_text, merged_citations, None, None

    async def _fanout_structured_query(
        self,
        sd_tools: List,
        query: str,
        table_name: Optional[str],
        context: Optional[str],
    ) -> Tuple[str, List[Dict], Optional[Dict], Optional[Any]]:
        """Run every structured-data tool in parallel and merge results."""
        tool_args: Dict[str, Any] = {"question": query}
        if table_name:
            tool_args["table_name"] = table_name
        if context:
            tool_args["context"] = context

        if len(sd_tools) == 1:
            tool = sd_tools[0]
            logger.debug(
                "📊 Executing structured data query on %s: %s | table_name=%s",
                getattr(tool, "name", "unknown"),
                query[:100], table_name or "auto",
            )
            result = await self._invoke_tool(tool, tool_args)
            return self._unpack_structured_result(result, query)

        logger.debug(
            "📊 Fanning out structured-data query to %d tools (%s) for: %s",
            len(sd_tools),
            [getattr(t, "name", "?") for t in sd_tools],
            query[:100],
        )
        coros = [self._invoke_tool(tool, tool_args) for tool in sd_tools]
        results = await asyncio.gather(*coros, return_exceptions=True)

        merged_parts: List[str] = []
        merged_meta: List[Dict] = []
        for tool, result in zip(sd_tools, results):
            tool_name = getattr(tool, "name", "query_tool")
            if isinstance(result, Exception):
                logger.warning("⚠️ Structured-data tool %s failed: %s", tool_name, result)
                merged_parts.append(f"### {tool_name}: error — {result}")
                continue
            text, _, _, query_meta = self._unpack_structured_result(result, query)
            if text and text.strip():
                merged_parts.append(f"### Results from {tool_name}\n{text}")
            if query_meta:
                if isinstance(query_meta, list):
                    merged_meta.extend(query_meta)
                else:
                    merged_meta.append(query_meta)

        merged_text = "\n\n".join(merged_parts) if merged_parts else (
            "No results returned from any of the configured structured-data tables."
        )
        return merged_text, [], None, (merged_meta or None)

    @staticmethod
    def _unpack_kb_result(result: Any) -> Tuple[str, List[Dict]]:
        """Normalise KB tool output to ``(text, citations)``."""
        if isinstance(result, dict):
            text = result.get("text", str(result))
            citations = result.get("citations", []) or []
        else:
            text = str(result)
            citations = []
        return text, citations

    @staticmethod
    def _unpack_structured_result(
        result: Any, query: str,
    ) -> Tuple[str, List[Dict], Optional[Dict], Optional[Any]]:
        """Normalise structured-data tool output to the routed-tool tuple."""
        if isinstance(result, dict):
            text = result.get("text", str(result))
            agent_queries = result.get("queries_executed")
            if agent_queries:
                query_meta: Any = [
                    {
                        "question": query,
                        "sql": qe.get("sql", ""),
                        "tables_used": qe.get("tables_used", []),
                        "row_count": qe.get("row_count", 0),
                        "results": qe.get("results", {"columns": [], "rows": []}),
                    }
                    for qe in agent_queries
                ]
            else:
                query_meta = {
                    "question": query,
                    "sql": result.get("sql", ""),
                    "tables_used": result.get("tables_used", []),
                    "row_count": result.get("row_count", 0),
                    "results": result.get("results", {"columns": [], "rows": []}),
                }
        else:
            text = str(result)
            query_meta = None
        return text, [], None, query_meta

    @staticmethod
    def _shift_citations(
        text: str,
        citations: List[Dict],
        offset: int,
    ) -> Tuple[str, List[Dict]]:
        """Renumber ``[N]`` markers and ``citation_number`` fields by *offset*.

        Used when merging results from multiple KB tools so the combined
        text remains a single, monotonically-increasing 1..N citation
        stream that the caller can rebase against ``accumulated_citations``.
        """
        if offset <= 0 or not citations:
            return text, citations

        shifted_text = re.sub(
            r"\[(\d+)\]",
            lambda m: f"[{int(m.group(1)) + offset}]",
            text or "",
        )
        for c in citations:
            num = c.get("citation_number")
            if isinstance(num, int):
                c["citation_number"] = num + offset
        return shifted_text, citations

    @staticmethod
    def _renumber_deliverable_markers(data: Any, offset: int) -> Any:
        """Shift ``[N]`` citation markers in all string values by *offset*.

        Deep research embeds ``[1]``, ``[2]``, … in the deliverable JSON.
        When prior citations already occupy those numbers we need to shift
        the markers so they match the renumbered ``citation_number`` values.
        """
        if offset == 0:
            return data
        if isinstance(data, str):
            return re.sub(
                r'\[(\d+)\]',
                lambda m: f'[{int(m.group(1)) + offset}]',
                data,
            )
        if isinstance(data, dict):
            return {k: MultiAgentLoopExecutor._renumber_deliverable_markers(v, offset) for k, v in data.items()}
        if isinstance(data, list):
            return [MultiAgentLoopExecutor._renumber_deliverable_markers(item, offset) for item in data]
        return data

    @staticmethod
    def _extract_structured_data_desc(tools: List) -> str:
        """Return a short indicator if a structured data query tool is present.

        The query tool is autonomous and handles table selection internally,
        so we no longer expose the full semantic model to the Tool Caller.
        """
        for t in tools:
            if getattr(t, "name", "").startswith("query_"):
                return "structured_data_available"
        return ""

    @staticmethod
    def _summarize_messages(messages: List, max_chars: int = MAX_SUMMARY_CHARS) -> List[str]:
        """Build recent conversation context for the Tool Caller.

        Omits the system prompt — ``route_next_action`` already receives
        ``systemInstructions`` (via resolve_agent_instructions) and
        ``output_schema_summary`` separately.
        """
        if not messages:
            return []

        summaries: List[str] = []
        budget = max_chars

        reverse_msgs: List[str] = []
        for msg in reversed(messages[1:]):
            content = getattr(msg, "content", "") or ""
            if not content:
                continue
            role = type(msg).__name__.replace("Message", "").lower()
            entry = f"[{role}] {content}"
            if len(entry) > budget:
                if budget > 100:
                    reverse_msgs.append(entry[:budget])
                break
            reverse_msgs.append(entry)
            budget -= len(entry)

        summaries.extend(reversed(reverse_msgs))
        return summaries

    @staticmethod
    def _user_requests_deliverable(messages: List) -> bool:
        """Detect if the user explicitly asks to produce the deliverable.

        Triggers when BOTH conditions are met:
        1. Any recent HumanMessage contains a clear confirmation/output request.
        2. The agent has prior data to base the deliverable on — either an
           explicit ``[Tool result from ...]`` message OR a substantial AI
           response (>5 000 chars) indicating the agent already processed
           tool data in a previous turn (tool results are local to the loop
           and may not persist across multi-turn re-executions).
        """
        SUBSTANTIAL_AI_THRESHOLD = 5000

        confirmation_signals = [
            "provide the output", "provide output", "produce the output",
            "produce output", "generate the output", "generate output",
            "create the output", "submit the output", "submit output",
            "go ahead", "proceed", "finalize", "that's what i need",
            "thats what i need", "that is what i need",
            "its what i", "it's what i", "what i am looking for",
            "what i'm looking for", "looks good", "look good",
            "i am satisfied", "i'm satisfied", "yes proceed",
            "yes go ahead", "yes provide", "yes submit", "yes generate",
            "provide the deliverable", "produce the deliverable",
        ]

        has_confirmation = False
        has_data = False
        for msg in reversed(messages):
            content = getattr(msg, "content", "") or ""
            if not content:
                continue
            if isinstance(msg, HumanMessage):
                if not content.startswith("[System]") and not has_confirmation:
                    text = content.lower().strip()
                    if any(signal in text for signal in confirmation_signals):
                        has_confirmation = True
            if content.startswith("[Tool result from "):
                has_data = True
            if isinstance(msg, AIMessage) and len(content) >= SUBSTANTIAL_AI_THRESHOLD:
                has_data = True

        return has_confirmation and has_data

    # ------------------------------------------------------------------
    # LEGACY: agents without submit_deliverable
    # ------------------------------------------------------------------

    async def _execute_legacy(
        self,
        llm: Any,
        tools: List,
        messages: List,
        output_schema_str: str,
        accumulated_citations: List[Dict],
    ) -> Dict[str, Any]:
        """Legacy execution paths for agents without submit_deliverable."""

        if tools and output_schema_str:
            logger.debug(
                "🔧 Legacy two-phase mode: %d tool(s) + structured output for %s",
                len(tools), self.node.label,
            )
            forced_tool_name = self._get_forced_tool_name(tools)
            tool_llm = llm.bind_tools(tools)
            forced_tool_llm = (
                llm.bind_tools(tools, tool_choice=forced_tool_name)
                if forced_tool_name else None
            )
            if forced_tool_name:
                logger.debug("🔒 Strict mode: forcing initial tool call to '%s'", forced_tool_name)
            response, accumulated_citations, tool_deliverable, _ = (
                await self._execute_tool_loop(
                    tool_llm, messages, tools,
                    llm_optional=tool_llm,
                    llm_forced=forced_tool_llm,
                    forced_tool_name=forced_tool_name,
                )
            )
            if tool_deliverable is not None:
                return {
                    "chat": "Research complete. Here is the structured deliverable.",
                    "deliverable": tool_deliverable,
                    "response": "Research complete. Here is the structured deliverable.",
                    "citations": accumulated_citations,
                }
            if (
                messages
                and isinstance(messages[-1], AIMessage)
                and not getattr(messages[-1], "tool_calls", [])
            ):
                messages.pop()
            structured_llm = self._apply_structured_output(llm, output_schema_str, include_raw=True)
            logger.info("🔄 Phase 2: Re-invoking LLM with structured output")
            response = await structured_llm.ainvoke(messages)
            response = self._unwrap_structured_response(response)
            return self._build_result(response, accumulated_citations, output_schema_str)

        if output_schema_str and not tools:
            logger.debug("ℹ️ Structured output only (no tools) for %s", self.node.label)
            structured_llm = self._apply_structured_output(
                llm, output_schema_str, include_raw=True
            )
            response = await structured_llm.ainvoke(messages)
            response = self._unwrap_structured_response(response)
            return self._build_result(response, [], output_schema_str)

        if tools:
            logger.debug(
                "🔧 Binding %d tool(s) to multi-agent LLM: %s",
                len(tools),
                [getattr(t, "name", "unknown") for t in tools],
            )
            forced_tool_name = self._get_forced_tool_name(tools)
            llm_optional = llm.bind_tools(tools)
            llm_forced = (
                llm.bind_tools(tools, tool_choice=forced_tool_name)
                if forced_tool_name else None
            )
            if forced_tool_name:
                logger.debug("🔒 Strict mode: forcing initial tool call to '%s'", forced_tool_name)
            llm = llm_optional
        else:
            logger.debug("ℹ️ No tools to bind for multi-agent %s", self.node.label)
            forced_tool_name = None
            llm_optional = llm
            llm_forced = None

        response, accumulated_citations, tool_deliverable, _ = (
            await self._execute_tool_loop(
                llm, messages, tools,
                llm_optional=llm_optional,
                llm_forced=llm_forced,
                forced_tool_name=forced_tool_name,
            )
        )
        if tool_deliverable is not None:
            logger.info("⚡ Tool returned structured deliverable, using directly")
            return {
                "chat": "Research complete. Here is the structured deliverable.",
                "deliverable": tool_deliverable,
                "response": "Research complete. Here is the structured deliverable.",
                "citations": accumulated_citations,
            }

        return self._build_result(response, accumulated_citations, output_schema_str)
    
    def _init_llm(self, config: Dict[str, Any]) -> Any:
        """Initialize LLM with configuration."""
        provider = config.get("modelProvider", LLMConfig.DEFAULT_PROVIDER)
        model_name = config.get("modelName", LLMConfig.DEFAULT_MODEL)
        temperature = config.get("temperature", LLMConfig.DEFAULT_TEMPERATURE)
        max_tokens = config.get("maxTokens") or LLMConfig.DEFAULT_MAX_TOKENS
        
        # Structured output (multi-section deliverables) needs more tokens than
        # the default 4096 — reasoning models use ~2k for thinking, leaving too
        # little room for the JSON payload. Enforce a minimum of 32768 when a
        # deliverable schema is configured.
        output_schema_str = config.get("outputSchema", "")
        if output_schema_str and (max_tokens or 0) < 64000:
            logger.debug("📈 Bumping max_tokens from %d to 32768 for structured output", max_tokens)
            max_tokens = 64000
        
        llm = LLMClientManager.get_client(provider, model_name, temperature, max_tokens)
        logger.debug("🔧 Initialized LLM: %s/%s (max_tokens=%d)", provider, model_name, max_tokens)
        return llm
    
    def _apply_structured_output(self, llm: Any, output_schema_str: str, include_raw: bool = False) -> Any:
        """Apply structured output if schema is provided."""
        try:
            # Parse schema
            user_schema = (json.loads(output_schema_str) 
                          if isinstance(output_schema_str, str) else output_schema_str)
            
            user_schema = self._resolve_schema_refs(user_schema)
            user_schema = self._fix_array_schemas(user_schema)
            user_schema = inject_summary_field(user_schema)

            # Create wrapper schema with top-level title and description (required by LangChain)
            user_schema_title = user_schema.get("title", "DeliverableOutput")
            wrapper_schema = {
                "title": "AgentResponse",
                "description": "Agent response with chat message and optional structured deliverable output",
                "type": "object",
                "properties": {
                    "chat": {
                        "type": "string",
                        "description": "Natural language explanation of your work or questions you want to ask"
                    },
                    "outputDeliverable": user_schema
                },
                "required": ["chat"],  # Only chat is required, outputDeliverable is optional
                "additionalProperties": False
            }
            
            # Detect model type to choose the right structured output method
            # Gemini/Vertex AI models don't support function_calling via LiteLLM proxy properly
            model_name = getattr(llm, 'model_name', '') or getattr(llm, 'model', '') or ''
            is_gemini = 'gemini' in model_name.lower() or 'vertex_ai' in model_name.lower()
            
            if is_gemini:
                # Use json_mode for Gemini - function_calling returns None via proxy
                llm = llm.with_structured_output(
                    schema=wrapper_schema,
                    method="json_mode",
                    include_raw=include_raw
                )
                logger.debug("✅ Enabled structured output with JSON schema (json_mode for Gemini, include_raw=%s)", include_raw)
            else:
                # Use function_calling for OpenAI and other models
                llm = llm.with_structured_output(
                    schema=wrapper_schema,
                    method="function_calling",
                    include_raw=include_raw
                )
                logger.debug("✅ Enabled structured output with JSON schema (function_calling, include_raw=%s)", include_raw)
            
            logger.debug("Wrapper schema: %s", json.dumps(wrapper_schema, indent=2))
            return llm
            
        except Exception as e:
            logger.warning("⚠️ Failed to parse outputSchema for structured output: %s. "
                         "Falling back to prompt-based approach.", e)
            return llm
    
    def _resolve_schema_refs(self, schema: dict) -> dict:
        """Inline all ``$ref`` / ``definitions`` and flatten ``oneOf`` so the
        schema is self-contained and compatible with Gemini's json_mode."""
        if not isinstance(schema, dict):
            return schema

        definitions = schema.get("definitions", {})

        def _resolve(node):
            if not isinstance(node, dict):
                return node

            if "$ref" in node:
                ref_path = node["$ref"]
                if ref_path.startswith("#/definitions/"):
                    def_name = ref_path.split("/")[-1]
                    if def_name in definitions:
                        return _resolve(definitions[def_name])
                return node

            resolved: dict = {}
            for key, value in node.items():
                if key == "definitions":
                    continue
                if key == "oneOf":
                    items = [_resolve(item) for item in value]
                    all_props: dict = {}
                    all_required: set = set()
                    for item in items:
                        if isinstance(item, dict):
                            for p, v in item.get("properties", {}).items():
                                if p not in all_props:
                                    all_props[p] = v
                            all_required.update(item.get("required", []))
                    if all_props:
                        resolved["type"] = "object"
                        resolved["properties"] = all_props
                    continue
                if isinstance(value, dict):
                    resolved[key] = _resolve(value)
                elif isinstance(value, list):
                    resolved[key] = [
                        _resolve(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    resolved[key] = value
            return resolved

        return _resolve(schema)

    @staticmethod
    def _deep_copy_property(prop: Dict[str, Any]) -> Dict[str, Any]:
        """Deep-copy a JSON-schema property so mutations don't leak back."""
        return json.loads(json.dumps(prop, default=str))

    @staticmethod
    def _merge_property(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Merge *source* property schema into *target* in place.

        Handles the fields that commonly differ across tuple-style items:
        - ``enum``: values are unioned so the LLM can produce any variant.
        - ``description``: descriptions are concatenated (separated by
          `` | ``) so the LLM sees guidance for every section.
        - ``const``: converted to an ``enum`` and merged.

        All other keys are left as-is (first-come-wins is fine for
        ``type``, ``format``, etc.).
        """
        # --- enum ---
        src_enum = source.get("enum") or ([source["const"]] if "const" in source else None)
        tgt_enum = target.get("enum") or ([target["const"]] if "const" in target else None)
        if src_enum and tgt_enum:
            merged = list(tgt_enum)
            for v in src_enum:
                if v not in merged:
                    merged.append(v)
            target["enum"] = merged
            target.pop("const", None)
        elif src_enum and not tgt_enum:
            target["enum"] = list(src_enum)
            target.pop("const", None)

        # --- description ---
        src_desc = source.get("description", "")
        tgt_desc = target.get("description", "")
        if src_desc and tgt_desc and src_desc != tgt_desc:
            target["description"] = f"{tgt_desc} | {src_desc}"
        elif src_desc and not tgt_desc:
            target["description"] = src_desc

    def _fix_array_schemas(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively fix array schemas that are missing 'items' property
        or have tuple-style 'items' (list) which LiteLLM/Vertex AI cannot handle.
        OpenAI's function calling requires all arrays to specify items as an object.
        """
        if not isinstance(schema, dict):
            return schema
        
        # Make a copy to avoid mutating the original
        fixed_schema = schema.copy()
        
        # If this is an array type without items, add a default items schema
        if fixed_schema.get("type") == "array" and "items" not in fixed_schema:
            logger.warning("⚠️ Array schema missing 'items' property. Adding default: {\"type\": \"object\"}")
            fixed_schema["items"] = {"type": "object"}
        
        # Fix tuple-style items: "items": [schema1, schema2, ...] -> "items": { merged }
        # LiteLLM/Vertex AI cannot handle list-style items in function calling schemas
        if "items" in fixed_schema and isinstance(fixed_schema["items"], list):
            items_list = fixed_schema["items"]
            if len(items_list) == 1:
                # Single item - just unwrap it
                fixed_schema["items"] = self._fix_array_schemas(items_list[0])
            elif len(items_list) > 1:
                merged_properties: Dict[str, Any] = {}
                merged_required: set = set()
                for item_schema in items_list:
                    if not isinstance(item_schema, dict):
                        continue
                    for key, val in item_schema.get("properties", {}).items():
                        if key not in merged_properties:
                            merged_properties[key] = self._deep_copy_property(val)
                        else:
                            self._merge_property(merged_properties[key], val)
                    for req in item_schema.get("required", []):
                        merged_required.add(req)

                if merged_properties:
                    fixed_schema["items"] = self._fix_array_schemas({
                        "type": "object",
                        "properties": merged_properties,
                        "required": list(merged_required)
                    })
                else:
                    fixed_schema["items"] = {"type": "object"}
                logger.debug("🔧 Converted tuple-style items (%d schemas) to single merged schema", len(items_list))
            else:
                fixed_schema["items"] = {"type": "object"}
        
        # Recursively fix nested schemas
        if "properties" in fixed_schema:
            fixed_schema["properties"] = {
                key: self._fix_array_schemas(value)
                for key, value in fixed_schema["properties"].items()
            }
        
        if "items" in fixed_schema and isinstance(fixed_schema["items"], dict):
            fixed_schema["items"] = self._fix_array_schemas(fixed_schema["items"])
        
        if "additionalProperties" in fixed_schema and isinstance(fixed_schema["additionalProperties"], dict):
            fixed_schema["additionalProperties"] = self._fix_array_schemas(fixed_schema["additionalProperties"])
        
        return fixed_schema
    
    async def _prepare_messages(
        self,
        state: WorkflowState,
        system_instructions: str
    ) -> List:
        """Prepare message list for LLM.

        Only includes messages from the **current** agent's conversation.
        Previous agents' deliverables are already injected into the system
        instructions, so their raw chat history is excluded to prevent the
        Tool Caller from misinterpreting old user confirmations.
        
        Uploaded files from other steps are injected into the system prompt
        (with provenance labels) so they survive message-history pruning.
        """
        session_id = get_session_id_from_state(state)
        node_config = self.node.node_config or {}
        if session_id:
            global_block = await build_global_file_context(
                session_id,
                current_agent_id=self.node.node_id,
                node_config=node_config,
                workflow_id=get_workflow_id_from_state(state),
            )
            if global_block:
                system_instructions = system_instructions + global_block
                logger.debug(
                    "📁 Injected file context from previous steps for %s",
                    self.node.label,
                )
        
        messages = [SystemMessage(content=system_instructions)]

        if state.get("messages"):
            filtered = self._filter_current_agent_messages(state["messages"])
            messages.extend(filtered)
            logger.debug(
                "📨 Messages for %s: %d of %d from state (filtered out %d from prior agents)",
                self.node.label,
                len(filtered),
                len(state["messages"]),
                len(state["messages"]) - len(filtered),
            )

        # Add current input only when deliverableSources is "all" or
        # unset (legacy).  Any explicit selection ("none" or a list)
        # means the builder is controlling context, so the raw workflow
        # input_data should not be injected -- deliverables are the
        # sole context channel in that case.
        config = self.node.node_config or {}
        sources = config.get("deliverableSources")
        inject_input = sources is None or sources == "" or sources == "all" or sources is True
        if inject_input:
            input_data = self.node.get_input_from_state(state)
            if input_data:
                if isinstance(input_data, str):
                    messages.append(HumanMessage(content=input_data))
                elif isinstance(input_data, dict) and "message" in input_data:
                    messages.append(HumanMessage(content=input_data["message"]))
        
        return messages

    def _filter_current_agent_messages(self, messages: List) -> List:
        """Keep only messages belonging to the current agent's conversation.

        Messages are chronological.  We find the last AIMessage from a
        *different* agent (ignoring startup messages tagged for this agent)
        and take everything after it.  This gives us:
        - This agent's startup message (if any)
        - User messages directed at this agent
        - This agent's own AI responses and tool results
        """
        current_id = self.node.node_id

        boundary = -1
        for i, msg in enumerate(messages):
            kwargs = getattr(msg, "additional_kwargs", None) or {}
            agent_id = kwargs.get("agent_id")
            if not agent_id:
                continue
            if agent_id != current_id and not kwargs.get("is_startup_message"):
                boundary = i

        if boundary >= 0:
            return list(messages[boundary + 1:])

        return list(messages)
    
    async def _execute_tool_loop(
        self,
        llm: Any,
        messages: List,
        tools: List,
        llm_optional: Any = None,
        llm_forced: Any = None,
        forced_tool_name: Optional[str] = None,
    ) -> Tuple[Any, List[Dict], Optional[Dict], bool]:
        """Execute LLM with tool calling loop.

        Returns ``(response, accumulated_citations, tool_deliverable,
        from_submit_tool)`` where *from_submit_tool* distinguishes
        deliverables produced by ``submit_deliverable`` (needs classifier)
        from those produced by deep research (already validated).
        """
        logger.debug("Invoking LLM for multi-agent node %s", self.node.label)
        
        config = self.node.node_config or {}
        max_iterations = config.get("maxToolIterations", 5)
        iteration = 0
        accumulated_citations: List[Dict] = []
        tool_deliverable: Optional[Dict] = None
        from_submit_tool = False
        response = None
        forced_tool_used = False
        llm_optional = llm_optional or llm
        
        while iteration < max_iterations:
            iteration += 1
            logger.debug("Multi-agent iteration %d/%d", iteration, max_iterations)
            
            current_llm = llm_forced if forced_tool_name and not forced_tool_used and llm_forced else llm_optional
            response = await current_llm.ainvoke(messages)
            messages.append(response)

            # Check for tool calls
            tool_calls = getattr(response, 'tool_calls', [])
            if not tool_calls:
                if forced_tool_name and not forced_tool_used:
                    logger.warning(
                        "⚠️ Strict mode: model did not call required tool '%s'. Requesting explicit tool call.",
                        forced_tool_name,
                    )
                    messages.append(HumanMessage(
                        content=(
                            f"You must call the '{forced_tool_name}' tool now before providing a final response."
                        )
                    ))
                    continue
                break
            
            if forced_tool_name and any(tc.get("name") == forced_tool_name for tc in tool_calls):
                forced_tool_used = True
                logger.debug("✅ Strict mode: required tool '%s' was invoked", forced_tool_name)

            # Cap parallel tool calls to avoid context explosion
            max_parallel = config.get("maxParallelToolCalls", 4)
            if len(tool_calls) > max_parallel:
                logger.warning(
                    "⚠️ Agent %s requested %d tool calls, capping to %d",
                    self.node.label, len(tool_calls), max_parallel,
                )
                skipped = tool_calls[max_parallel:]
                tool_calls = tool_calls[:max_parallel]
                for skipped_tc in skipped:
                    messages.append(ToolMessage(
                        content=(
                            "Skipped: too many parallel tool calls. "
                            "Process current results first, then search again."
                        ),
                        tool_call_id=skipped_tc.get("id", ""),
                    ))

            logger.info("🔧 Agent %s calling %d tool(s)", self.node.label, len(tool_calls))
            td, is_submit = await self._execute_tools(tool_calls, tools, messages, accumulated_citations)
            if td is not None:
                tool_deliverable = td
                from_submit_tool = is_submit
                if from_submit_tool:
                    logger.info("🛑 submit_deliverable produced deliverable, exiting tool loop")
                    break
        
        return response, accumulated_citations, tool_deliverable, from_submit_tool

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

    async def _classifier_gate(
        self,
        deliverable: Dict[str, Any],
        config: Dict[str, Any],
        messages: List,
        accumulated_citations: List[Dict],
        chat_msg: str,
    ) -> Optional[Dict[str, Any]]:
        """Run the fast readiness classifier on a submit_deliverable result.

        Returns the deliverable unchanged if the classifier says READY,
        or ``None`` if NOT_READY (and appends a rejection message to
        *messages* so the agent can continue).
        """
        task_instructions = resolve_agent_instructions(config)
        output_schema_str = config.get("outputSchema", "")

        recent = []
        for msg in messages[-10:]:
            content = getattr(msg, "content", "")
            if content:
                recent.append(content)

        is_ready, reason = await classify_readiness(
            task_instructions=task_instructions,
            output_schema_summary=output_schema_str,
            recent_messages=recent,
        )

        if is_ready:
            logger.info("✅ Classifier approved deliverable for %s", self.node.label)
            return deliverable

        logger.info(
            "🚫 Classifier rejected deliverable for %s: %s",
            self.node.label, reason,
        )
        messages.append(HumanMessage(
            content=(
                f"Your deliverable was not accepted because: {reason}. "
                "Please gather the missing information and call "
                "submit_deliverable again when ready."
            )
        ))
        return None
    
    async def _execute_single_tool(
        self,
        tool_call: Dict,
        tools: List
    ) -> tuple:
        """Execute a single tool and return result with metadata."""
        tool_name = tool_call.get('name', 'unknown')
        tool_args = tool_call.get('args', {})
        tool_id = tool_call.get('id', '')
        
        logger.debug("🔧 Executing tool: %s with args: %s", 
                   tool_name, str(tool_args)[:100])
        
        # Find tool
        tool = next((t for t in tools if getattr(t, 'name', None) == tool_name), None)
        
        if not tool:
            return (None, tool_name, tool_id, f"Tool '{tool_name}' not found")
        
        tool_result = await self._invoke_tool(tool, tool_args)
        return (tool_result, tool_name, tool_id, None)
    
    async def _execute_tools(
        self,
        tool_calls: List[Dict],
        tools: List,
        messages: List,
        accumulated_citations: List[Dict]
    ) -> Tuple[Optional[Dict], bool]:
        """Execute tool calls IN PARALLEL and add results to messages.

        Returns ``(deliverable_or_none, from_submit_tool)``.
        """
        if not tool_calls:
            return None, False
        
        logger.debug("🔧 Executing %d tools IN PARALLEL", len(tool_calls))
        
        results = await asyncio.gather(*[
            self._execute_single_tool(tool_call, tools)
            for tool_call in tool_calls
        ], return_exceptions=True)
        
        tool_deliverable: Optional[Dict] = None
        from_submit_tool = False

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
                td, is_submit = self._process_tool_result(
                    tool_result, tool_name, tool_id, 
                    messages, accumulated_citations
                )
                if td is not None:
                    tool_deliverable = td
                    from_submit_tool = is_submit

        return tool_deliverable, from_submit_tool
    
    async def _invoke_tool(self, tool: Any, tool_args: Dict) -> Any:
        """Invoke a single tool, bypassing ainvoke to preserve structured returns."""
        tool_name = getattr(tool, "name", "unknown_tool")

        async def _invoke() -> Any:
            if hasattr(tool, 'coroutine'):
                return await tool.coroutine(**tool_args)
            elif hasattr(tool, 'func'):
                return await tool.func(**tool_args)
            elif hasattr(tool, '_arun'):
                return await tool._arun(**tool_args)
            return await tool.ainvoke(tool_args)

        try:
            return await trace_tool_call(
                tool_name,
                tool_args,
                _invoke,
                payload={"source": "multi_agent"},
            )
        except Exception as e:
            logger.error("Tool execution error: %s", e, exc_info=True)
            return f"Error executing tool: {str(e)}"
    
    def _process_tool_result(
        self,
        tool_result: Any,
        tool_name: str,
        tool_id: str,
        messages: List,
        accumulated_citations: List[Dict]
    ) -> Tuple[Optional[Dict], bool]:
        """Process tool result and handle citations.

        Returns ``(deliverable_or_none, from_submit_tool)`` where
        *from_submit_tool* is True when the deliverable came from the
        ``submit_deliverable`` tool (needs classifier gate) vs deep
        research (already validated, skip classifier).
        """
        from app.workflow.tools.deep_research import CitedText
        from app.workflow.tools.submit_deliverable import DeliverableSubmission

        citations: List[Dict] = []
        result_text: str = ""
        tool_deliverable: Optional[Dict] = None
        from_submit_tool = False

        if isinstance(tool_result, DeliverableSubmission):
            if tool_result.valid:
                tool_deliverable = tool_result.data
                from_submit_tool = True
                logger.debug(
                    "📦 submit_deliverable accepted with %d keys",
                    len(tool_deliverable),
                )
            result_text = str(tool_result)
        elif isinstance(tool_result, dict) and 'citations' in tool_result:
            result_text = tool_result.get('text', '')
            citations = tool_result.get('citations', [])
        elif isinstance(tool_result, CitedText):
            result_text = str(tool_result)
            citations = list(tool_result.citations) if tool_result.citations else []
            if tool_result.deliverable:
                tool_deliverable = tool_result.deliverable
                logger.debug("📦 Tool '%s' returned pre-built deliverable with %d keys",
                           tool_name, len(tool_deliverable))
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

        return tool_deliverable, from_submit_tool
    
    def _unwrap_structured_response(self, response: Any) -> Any:
        """
        Unwrap an include_raw=True structured output response.
        
        When include_raw=True, LangChain returns {"raw": AIMessage, "parsed": dict|None,
        "parsing_error": str|None}.  If the parser succeeded, return the parsed dict.
        If it returned None (common with Gemini json_mode via proxy), fall back to
        manually extracting JSON from the raw AIMessage content so the deliverable
        isn't silently lost.
        """
        if not isinstance(response, dict) or "raw" not in response:
            return response
        
        parsed = response.get("parsed")
        raw = response.get("raw")
        parsing_error = response.get("parsing_error")
        
        if parsed is not None:
            logger.debug("✅ Structured output parsed successfully, keys: %s", 
                       list(parsed.keys()) if isinstance(parsed, dict) else type(parsed))
            return parsed
        
        logger.warning("⚠️ Structured output parsing returned None — attempting manual extraction from raw response")
        if parsing_error:
            logger.warning("   Parsing error: %s", parsing_error)
        
        raw_content = getattr(raw, 'content', '') if raw else ''
        if not raw_content:
            logger.warning("   Raw response has no content")
            return None
        
        logger.debug("   Raw content length: %d, preview: %s", len(raw_content), raw_content[:500])
        
        # Try direct JSON parse
        try:
            manual = json.loads(raw_content)
            if isinstance(manual, dict):
                logger.debug("✅ Manual JSON extraction succeeded, keys: %s", list(manual.keys()))
                return manual
        except json.JSONDecodeError:
            pass
        
        # Gemini sometimes wraps JSON in markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', raw_content, re.DOTALL)
        if json_match:
            try:
                manual = json.loads(json_match.group(1))
                if isinstance(manual, dict):
                    logger.debug("✅ Extracted JSON from code block in raw response, keys: %s", list(manual.keys()))
                    return manual
            except json.JSONDecodeError:
                pass
        
        logger.warning("⚠️ All structured output extraction attempts failed")
        return None
    
    def _build_result(
        self,
        response: Any,
        accumulated_citations: List[Dict],
        output_schema_str: str
    ) -> Dict[str, Any]:
        """Build result dictionary from response."""
        # Extract deliverable
        if output_schema_str and isinstance(response, dict):
            # Structured output mode
            deliverable = response
            logger.debug("✅ Got structured output directly from LLM (dict)")
            logger.debug(f"   Structured response keys: {list(deliverable.keys())}")
            logger.debug(f"   Full structured response: {json.dumps(deliverable, indent=2, default=str)}")
        elif hasattr(response, 'content'):
            # Text mode - extract from content
            content = _extract_text_content(response.content)
            deliverable = self._extract_deliverable_from_response(content)
            logger.debug(f"🔍 Extracted deliverable from text: {deliverable is not None}")
            if deliverable:
                logger.debug(f"   Deliverable keys: {list(deliverable.keys())}")
        else:
            deliverable = None
            logger.warning("⚠️ Unexpected response type: %s", type(response))
        
        # Check if agent provided a deliverable (outputDeliverable field present and not None/empty)
        if deliverable and "outputDeliverable" in deliverable:
            output_data = deliverable.get("outputDeliverable")
            
            # Check if outputDeliverable has actual content (not None, not empty dict)
            has_content = output_data is not None and (
                not isinstance(output_data, dict) or len(output_data) > 0
            )
            
            if has_content:
                # Agent provided structured deliverable with content
                chat_msg = _deliverable_completion_message(output_data)

                logger.info(f"✅ Agent {self.node.label} produced deliverable")
                logger.debug(f"   Chat: {chat_msg[:100]}")
                logger.debug(f"   Deliverable data: {json.dumps(output_data, indent=2, default=str)}")
                
                if accumulated_citations:
                    logger.info(f"📚 Adding {len(accumulated_citations)} citations to deliverable response")
                
                return {
                    "chat": chat_msg,
                    "deliverable": output_data,
                    "response": chat_msg,
                    "citations": accumulated_citations if accumulated_citations else []
                }
        
        # Handle unwrapped deliverable: LLM returned the deliverable data directly
        # (e.g. json_mode with Gemini may return {'sections': [...]} without the wrapper)
        if deliverable and "outputDeliverable" not in deliverable and "chat" not in deliverable:
            # Check if it looks like a deliverable (has 'sections' or other expected schema keys)
            if "sections" in deliverable or (isinstance(deliverable, dict) and deliverable):
                logger.debug(f"⚠️  Agent {self.node.label} returned unwrapped deliverable (no chat/outputDeliverable wrapper)")
                logger.debug(f"   Keys: {list(deliverable.keys())}")
                
                output_data = deliverable
                chat_msg = _deliverable_completion_message(output_data)

                if accumulated_citations:
                    logger.info(f"📚 Adding {len(accumulated_citations)} citations to deliverable response")
                
                return {
                    "chat": chat_msg,
                    "deliverable": output_data,
                    "response": chat_msg,
                    "citations": accumulated_citations if accumulated_citations else []
                }
        
        # Agent is asking for more info or provided response without deliverable
        if deliverable and "chat" in deliverable:
            # Structured output without deliverable
            content = deliverable.get("chat", "")
            logger.info(f"ℹ️  Agent {self.node.label} responding without deliverable (asking questions or clarifying)")
            logger.debug(f"   Content preview: {content[:200]}")
        else:
            # Text mode response
            content = _extract_text_content(response.content) if hasattr(response, 'content') else str(response)
            logger.info(f"ℹ️  Agent {self.node.label} did not produce deliverable, content length: {len(content)}")
            logger.debug(f"   Content preview: {content[:200]}")
        
        if accumulated_citations:
            logger.info(f"📚 Adding {len(accumulated_citations)} citations to intermediate response")
        
        return {
            "chat": content,
            "deliverable": None,
            "response": content,
            "citations": accumulated_citations if accumulated_citations else []
        }
    
    def _extract_deliverable_from_response(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Extract structured deliverable from agent response.
        
        Looks for JSON blocks with 'chat' and 'outputDeliverable' fields.
        """
        # Try parsing entire response as JSON
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and ("outputDeliverable" in parsed or "output" in parsed):
                return parsed
            if isinstance(parsed, dict) and "chat" not in parsed:
                return {"chat": "Here is the deliverable.", "outputDeliverable": parsed}
        except json.JSONDecodeError:
            pass
        
        # Try extracting from markdown code blocks
        json_blocks = re.findall(r'```json\s*\n(.*?)\n```', content, re.DOTALL)
        for block in json_blocks:
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict) and ("outputDeliverable" in parsed or "output" in parsed):
                    return parsed
            except json.JSONDecodeError:
                continue
        
        # Try extracting embedded JSON
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.findall(json_pattern, content, re.DOTALL)
        for match in matches:
            try:
                parsed = json.loads(match)
                if isinstance(parsed, dict) and ("outputDeliverable" in parsed or "output" in parsed):
                    logger.info("✅ Extracted deliverable from embedded JSON in text")
                    return parsed
            except json.JSONDecodeError:
                continue
        
        return None
