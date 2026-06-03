"""
Agent node executor.

Executes an LLM agent with optional tools and system prompts.

This is the main orchestrator that delegates to specialized executors:
- StandardModeExecutor: Regular LLM agent with tools
- MultiAgentModeExecutor: Structured deliverables workflow

When enableDeepResearch is true, the deep_research tool is automatically
injected into the agent's tool list so the LLM can invoke it on demand.
The deep_research tool always uses o3-deep-research internally.
"""

from typing import Any, List, Dict
# from langfuse import observe  # DISABLED
from utils.langfuse_config import observe  # No-op decorator
import json
import logging
import uuid
from datetime import datetime

from langchain_core.messages import AIMessage

from .base import BaseNode
from ..state import WorkflowState, get_previous_deliverables, resolve_deliverable_sources
from ..tools.registry import get_tool_registry
from ..utils.kb_config import resolve_kb_ids
from ..utils.schema_augmentation import inject_summary_field
from app.utils.kb_tool import create_kb_tool, create_kb_researcher_tool
from app.utils.structured_data_tool import create_structured_data_tool
from app.config.settings import settings

# Import mode executors
from .agent_standard_mode import StandardModeExecutor
from .agent_multi_mode import MultiAgentModeExecutor
from .agent_multi_instructions import resolve_agent_instructions

logger = logging.getLogger(__name__)


class AgentNode(BaseNode):
    """
    Universal agent node executor with multiple modes.
    
    Can execute as:
    1. Multi-Agent Mode: Structured deliverables, iterative conversations (auto-detected)
    2. Standard Mode: Regular LLM agent with tools (default)
    
    When enableDeepResearch is true the ``deep_research`` tool is injected
    automatically so the agent's LLM can decide when to use it.  The tool
    always calls o3-deep-research regardless of the agent's configured model.
    
    Mode detection:
    - Multi-Agent: Has outputSchema, systemInstructions, or previous deliverables in state
    - Standard: Default fallback
    
    All specialized agent types (researcher, business-analyst, opportunity-classifier)
    use this same class with different JSON configurations.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize agent node with mode executors."""
        super().__init__(*args, **kwargs)
        
        # Initialize mode executors (lazy initialization for circular dependency avoidance)
        self._standard_executor = None
        self._multi_executor = None
    
    @property
    def standard_executor(self):
        """Lazy-load standard mode executor."""
        if self._standard_executor is None:
            self._standard_executor = StandardModeExecutor(self)
        return self._standard_executor
    
    @property
    def multi_executor(self):
        """Lazy-load multi-agent mode executor."""
        if self._multi_executor is None:
            self._multi_executor = MultiAgentModeExecutor(self)
        return self._multi_executor
    
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the agent node in appropriate mode.
        
        Auto-detects mode based on config and state:
        1. Check for multi-agent mode (has deliverable structure)
        2. Fallback to standard mode
        
        If enableDeepResearch is set, the deep_research tool is injected
        before execution so the LLM can invoke it when needed.
        
        Args:
            state: Current workflow state
            
        Returns:
            Agent response (format varies by mode)
        """
        config = self.node_config or {}
        
        # Show startup message / questionnaire on first run and pause when
        # configured. Wait is inferred from non-empty startup content unless
        # legacy ``waitForUserInput`` is present on the saved node config.
        from app.workflow.utils.startup import (
            get_startup_message_text,
            get_startup_questions_payload,
            should_wait_for_startup,
        )

        wait_for_input = should_wait_for_startup(config)
        startup_message = get_startup_message_text(config)
        startup_questions_payload = get_startup_questions_payload(config)

        if wait_for_input:
            node_outputs = state.get("node_outputs", {})
            my_output = node_outputs.get(self.node_id)

            # Also check state messages — the deliverable_service may
            # have already injected the startup message on HITL approval
            # (and deleted node_outputs for this agent so it can re-run).
            startup_in_messages = any(
                getattr(m, "additional_kwargs", {}).get("agent_id") == self.node_id
                and (
                    getattr(m, "additional_kwargs", {}).get("is_startup_message")
                    or getattr(m, "additional_kwargs", {}).get("is_initial_message")
                )
                for m in state.get("messages", [])
            )

            already_shown = my_output is not None or startup_in_messages
            if not already_shown:
                logger.info(
                    "⏸️  Agent %s: startup pause — showing startup "
                    "message%s and pausing for user input",
                    self.label,
                    " with questions" if startup_questions_payload else "",
                )
                # ``display_content`` is rendered in the chat bubble
                # ABOVE the QuestionsCard.  It must NEVER include the
                # questions ``intro`` — the card renders that intro
                # inside itself, so duplicating it here would paint the
                # same text twice.  Only the separate startup message
                # belongs in display_content.
                display_text = startup_message or ""

                # ``llm_content`` (=AIMessage.content) is what the LLM
                # sees on resume — keep the full intro + rendered
                # questions there so the next turn has complete
                # conversational context.
                if startup_questions_payload:
                    from app.workflow.tools.ask_user_questions import (
                        render_questions_for_llm,
                    )
                    intro_text = (startup_questions_payload.get("intro") or "").strip()
                    rendered = render_questions_for_llm(startup_questions_payload, "")
                    llm_parts = [p for p in (display_text, intro_text, rendered) if p]
                    llm_content = "\n\n".join(llm_parts)
                else:
                    llm_content = display_text

                additional_kwargs = {
                    "message_id": str(uuid.uuid4()),
                    "agent_id": self.node_id,
                    "agent_label": self.label,
                    "agent_type": self.node_type,
                    "is_startup_message": True,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                if startup_questions_payload:
                    additional_kwargs["questions"] = startup_questions_payload
                    additional_kwargs["display_content"] = display_text
                msg = AIMessage(
                    content=llm_content,
                    additional_kwargs=additional_kwargs,
                )
                return {
                    "response": startup_message,
                    "agent_id": self.node_id,
                    "agent_label": self.label,
                    "agent_type": self.node_type,
                    "has_deliverable": False,
                    "interrupted": True,
                    "startup_shown": True,
                    "messages": [msg],
                }
        
        # Inject tools when flags are set
        enable_deep_research = config.get("enableDeepResearch", False)
        if enable_deep_research:
            self._ensure_deep_research_tool(config)

        enable_web_search = config.get("enableWebSearch", False)
        if enable_web_search:
            self._ensure_tool_in_list(config, "simple_web_search")

        # ask_user_questions tool — give the LLM the ability to pause and
        # ask the user a short questionnaire mid-conversation.  Auto-on
        # for chat agents, opt-in via enableUserQuestions for the rest.
        # Also turned on when waitForUserInput is set, since that node is
        # already meant to ask the user things.
        agent_mode_for_inject = config.get("agentMode", "regular")
        if (
            agent_mode_for_inject == "chat"
            or config.get("enableUserQuestions", False)
            or wait_for_input
        ):
            self._ensure_tool_in_list(config, "ask_user_questions")

        # Mode 1: Multi-Agent (has deliverable structure)
        has_output_schema = bool(config.get("outputSchema"))
        has_agent_instructions = bool(resolve_agent_instructions(config))
        has_previous_deliverables = len(resolve_deliverable_sources(state, self.node_id, config)) > 0
        
        if has_output_schema or has_agent_instructions or has_previous_deliverables:
            logger.info("🤖 Agent %s (%s) executing in MULTI-AGENT mode", 
                       self.label, self.node_type)
            result = await self._execute_multi_agent_mode(state)
        else:
            # Mode 2: Standard (default)
            logger.info("💬 Agent %s (%s) executing in STANDARD mode%s", 
                       self.label, self.node_type,
                       " (deep_research tool available)" if enable_deep_research else "")
            result = await self._execute_standard_mode(state)
        
        # Chat mode agents always stay alive -- keep the workflow paused
        # so the user can continue chatting indefinitely.
        agent_mode = config.get("agentMode", "regular")
        if agent_mode == "chat":
            result["interrupted"] = True
        
        return result
    
    # ============================================================================
    # DEEP RESEARCH TOOL INJECTION
    # ============================================================================
    
    def _ensure_deep_research_tool(self, config: dict) -> None:
        """
        Ensure deep_research is in the agent's tool list.
        
        Called when enableDeepResearch is true.  Mutates the config's tool
        list so that StandardModeExecutor will pick it up automatically.
        """
        tool_names = config.get("tools") or []
        if "deep_research" not in tool_names:
            tool_names.append("deep_research")
            config["tools"] = tool_names
            logger.debug(
                "🔬 Injected deep_research tool into agent %s (total tools: %s)",
                self.label, tool_names,
            )

    def _ensure_tool_in_list(self, config: dict, tool_name: str) -> None:
        """Ensure *tool_name* is present in the agent's tool list."""
        tool_names = config.get("tools") or []
        if tool_name not in tool_names:
            tool_names.append(tool_name)
            config["tools"] = tool_names
            logger.debug(
                "🔧 Injected %s tool into agent %s (total tools: %s)",
                tool_name, self.label, tool_names,
            )

    def _build_startup_questions_payload(self, config: dict) -> dict:
        """Read & validate the hand-configured startupQuestions payload.

        Returns ``None`` if not configured / invalid so the caller can
        fall back to the plain-text startup message path.
        """
        from app.workflow.tools.ask_user_questions import normalize_questions_payload

        raw = config.get("startupQuestions")
        if not raw:
            return None
        return normalize_questions_payload(raw)
    
    # ============================================================================
    # MODE EXECUTION DELEGATORS
    # ============================================================================
    
    @observe(name="agent_standard_mode")
    async def _execute_standard_mode(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute as standard agent.
        
        Delegates to StandardModeExecutor.
        """
        return await self.standard_executor.execute(state)
    
    @observe(name="agent_multi_agent_mode")
    async def _execute_multi_agent_mode(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute agent in multi-agent mode with deliverable output.
        
        Delegates to MultiAgentModeExecutor.
        """
        return await self.multi_executor.execute(state)
    
    # ============================================================================
    # SHARED UTILITY METHODS
    # ============================================================================
    
    async def _get_tools(self, tool_names: List[str]) -> List[Any]:
        """
        Get tool instances from the registry and add KB tools if configured.
        
        For ``deep_research`` when the agent has an ``outputSchema``, a
        per-agent instance is created with the schema so o3 can return
        structured data directly.
        """
        from app.workflow.tools.deep_research import DeepResearchTool

        registry = get_tool_registry()
        tools = []
        
        output_schema_str = self.get_config_value("outputSchema", "")
        parsed_schema = None
        if output_schema_str:
            try:
                raw = (
                    json.loads(output_schema_str)
                    if isinstance(output_schema_str, str)
                    else output_schema_str
                )
                # Round-trip to ensure a clean, JSON-serializable dict
                # (strips Pydantic ModelMetaclass refs that can sneak in)
                parsed_schema = json.loads(json.dumps(raw, default=str))
                parsed_schema = inject_summary_field(parsed_schema)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("⚠️ Could not parse outputSchema for deep_research schema injection: %s", e)

        for tool_name in tool_names:
            if tool_name == "deep_research" and parsed_schema:
                tool = DeepResearchTool(output_schema=parsed_schema)
                logger.debug("🔬 Created per-agent DeepResearchTool with output schema for %s", self.label)
            elif tool_name == "ask_user_questions":
                # Pause primitive — instantiated inline (not in the
                # global registry) so the standard executor's intercept
                # path can recognise it by name and bypass execution.
                from app.workflow.tools.ask_user_questions import AskUserQuestionsTool
                tool = AskUserQuestionsTool()
            else:
                tool = registry.get_tool(tool_name)

            if tool:
                if getattr(tool, "name", None) == "deep_research":
                    setattr(tool, "_is_deep_research_tool", True)
                tools.append(tool)
            else:
                logger.warning("Tool not found: %s", tool_name)
        
        # Add knowledge base tools — one search/researcher tool + one
        # structured-data tool per configured KB.  ``resolve_kb_ids``
        # handles the legacy single-id field for older workflows.
        kb_ids = resolve_kb_ids(self.get_config_value)
        if kb_ids:
            logger.debug("🔍 Resolved %d KB id(s) for %s: %s", len(kb_ids), self.label, kb_ids)
            embedding_model = self.get_config_value("embeddingModel", "azure_ada_002")
            search_method = self.get_config_value("searchMethod", "semantic")
            enable_reranking = self.get_config_value("enableReranking", False)
            reranker_model = self.get_config_value(
                "rerankerModel", "cross-encoder/ms-marco-MiniLM-L-6-v2"
            )
            use_researcher = settings.KB_RESEARCHER_ENABLED

            task_instructions_for_researcher = resolve_agent_instructions(
                self.node_config or {}
            )
            output_schema_raw = self.get_config_value("outputSchema", "")
            output_schema_for_researcher = ""
            if output_schema_raw:
                if isinstance(output_schema_raw, str):
                    output_schema_for_researcher = output_schema_raw
                else:
                    try:
                        output_schema_for_researcher = json.dumps(
                            output_schema_raw, indent=2, default=str
                        )
                    except (TypeError, ValueError):
                        output_schema_for_researcher = str(output_schema_raw)

            for kb_id in kb_ids:
                try:
                    if use_researcher:
                        kb_tool = await create_kb_researcher_tool(
                            kb_id=kb_id,
                            embedding_model=embedding_model,
                            search_method=search_method,
                            enable_reranking=enable_reranking,
                            reranker_model=reranker_model,
                            task_instructions=task_instructions_for_researcher,
                            output_schema=output_schema_for_researcher,
                        )
                    else:
                        kb_tool = await create_kb_tool(
                            kb_id=kb_id,
                            embedding_model=embedding_model,
                            search_method=search_method,
                            enable_reranking=enable_reranking,
                            reranker_model=reranker_model,
                        )

                    if kb_tool:
                        langchain_tool = kb_tool.as_langchain_tool()
                        setattr(langchain_tool, "_is_kb_tool", True)
                        setattr(langchain_tool, "_kb_id", kb_id)
                        tools.append(langchain_tool)
                        logger.debug(
                            "✅ Added KB tool '%s' for knowledge base: %s",
                            kb_tool.name, kb_id,
                        )
                    else:
                        logger.warning("⚠️ KB tool creation returned None for KB ID: %s", kb_id)

                    # Also add a per-KB structured data tool when the KB has tables
                    try:
                        sd_tool = await create_structured_data_tool(
                            kb_id=kb_id,
                            kb_name=kb_tool.kb_name if kb_tool else None,
                        )
                        if sd_tool:
                            sd_langchain = sd_tool.as_langchain_tool()
                            setattr(sd_langchain, "_is_structured_tool", True)
                            setattr(sd_langchain, "_kb_id", kb_id)
                            tools.append(sd_langchain)
                            logger.debug(
                                "✅ Added structured data tool '%s' for KB: %s",
                                sd_tool.name, kb_id,
                            )
                    except Exception as sd_err:
                        logger.debug("No structured data tool for KB %s: %s", kb_id, sd_err)

                except (ImportError, ValueError, RuntimeError) as e:
                    logger.error(
                        "❌ Failed to create KB tool for %s: %s",
                        kb_id, e, exc_info=True,
                    )
        else:
            logger.debug("ℹ️ No KB IDs configured for agent %s", self.label)
        
        # Auto-inject submit_deliverable for multi-agent nodes with an output schema.
        # Chat mode agents never get this tool -- the user controls deliverable
        # production exclusively via the "Deliver Now" button.
        agent_mode = self.get_config_value("agentMode", "regular")
        has_output_schema = bool(self.get_config_value("outputSchema"))
        has_submit_tool = any(
            getattr(t, "name", None) == "submit_deliverable" for t in tools
        )
        if has_output_schema and not has_submit_tool and agent_mode != "chat":
            from app.workflow.tools.submit_deliverable import SubmitDeliverableTool
            submit_tool = SubmitDeliverableTool(output_schema=parsed_schema)
            tools.append(submit_tool)
            logger.debug("✅ Injected submit_deliverable tool for agent %s", self.label)

        logger.debug("📋 Total tools available: %d", len(tools))
        return tools
    
    def _format_prompt(
        self,
        prompt: str,
        state: WorkflowState,
        input_data: Any
    ) -> str:
        """
        Format the prompt with variables from state and input.
        
        Supports variable substitution like: {{variable_name}}
        
        This is shared across all execution modes.
        """
        formatted = prompt
        
        # Replace input variable
        if isinstance(input_data, str):
            formatted = formatted.replace("{{input}}", input_data)
        elif isinstance(input_data, dict):
            for key, value in input_data.items():
                formatted = formatted.replace(f"{{{{{key}}}}}", str(value))
        
        # Replace state variables
        for key, value in state.get("variables", {}).items():
            formatted = formatted.replace(f"{{{{{key}}}}}", str(value))
        
        # Replace node outputs
        for node_id, output in state.get("node_outputs", {}).items():
            node_output_value = output.get("output")
            if node_output_value:
                formatted = formatted.replace(
                    f"{{{{node.{node_id}}}}}",
                    str(node_output_value)
                )
        
        return formatted
