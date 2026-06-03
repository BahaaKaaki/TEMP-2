"""
Subagent executor for individual research tasks.

Each subagent is a full-fledged agent with its own context window and tool loop.
Follows Anthropic's pattern of forcing tool use on first iteration.
"""

import logging
from typing import Dict, List, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
# from langfuse import observe  # DISABLED
from utils.langfuse_config import observe  # No-op decorator

from .utils import extract_sources_from_messages
from config.llm_config import LLMClientManager, LLMConfig
from .subagent_execution_helpers import (
    initialize_subagent_messages,
    execute_subagent_tool_loop,
    extract_subagent_result
)
from utils.text_truncation import smart_truncate_for_llm
from config.settings import settings

logger = logging.getLogger(__name__)


class SubagentExecutor:
    """
    Executes a single research subagent.
    
    Key features:
    - Full agent with tool loop (max 10 iterations)
    - Forced tool use on iteration 1 (Anthropic pattern)
    - Independent context window
    - Extracts sources from tool results
    """
    
    def __init__(
        self,
        model_provider: str = None,
        model_name: str = None,
        temperature: float = None,
        max_tokens: Optional[int] = None
    ):
        """
        Initialize subagent executor.
        
        Args:
            model_provider: LLM provider ('openai' or 'anthropic')
            model_name: Model name
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
        """
        # Use centralized defaults
        self.model_provider = model_provider or LLMConfig.DEFAULT_PROVIDER
        self.model_name = model_name or LLMConfig.DEFAULT_MODEL
        self.temperature = temperature if temperature is not None else LLMConfig.DEFAULT_TEMPERATURE
        self.max_tokens = max_tokens or LLMConfig.DEFAULT_MAX_TOKENS
        
        logger.debug(
            "Initialized SubagentExecutor with %s/%s",
            model_provider,
            model_name
        )
    
    def _get_llm(self, bind_tools: Optional[List[Any]] = None) -> Any:
        """
        Get LLM instance using centralized client manager.
        
        Args:
            bind_tools: Optional list of tools to bind
            
        Returns:
            LLM instance
        """
        llm = LLMClientManager.get_client(
            provider=self.model_provider,
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        
        # Bind tools if provided
        if bind_tools:
            llm = llm.bind_tools(bind_tools)
        
        return llm
    
    @observe(name="subagent_executor_execute")
    async def execute(
        self,
        task_spec: Dict[str, Any],
        tools: List[Any],
        max_iterations: int = 10
    ) -> Dict[str, Any]:
        """
        Execute a single subagent research task.
        
        Delegates to helper functions for message initialization, tool execution loop, and result extraction.
        
        Args:
            task_spec: Task specification containing:
                - id: Unique subagent identifier
                - task: Research task description
                - focus: Focus area (optional)
                - context: Additional context (optional)
            tools: List of LangChain tools to use
            max_iterations: Maximum tool loop iterations
            
        Returns:
            Result dictionary containing:
                - subagent_id: Unique identifier
                - task: Original task
                - findings: Research findings (text)
                - sources: List of source dictionaries
                - iterations: Number of iterations completed
                - tool_calls_count: Total tool calls made
        """
        subagent_id = task_spec.get("id", "unknown")
        task = task_spec.get("task", "")
        
        logger.info(
            "Starting subagent %s: %s",
            subagent_id,
            task[:100]
        )
        
        # Initialize messages
        messages = initialize_subagent_messages(task_spec, tools, self._build_system_message)
        
        # Execute tool loop
        iteration, tool_calls_count = await execute_subagent_tool_loop(
            subagent_id,
            messages,
            tools,
            self._get_llm,
            self._get_llm_with_forced_tool,
            self._execute_tool,
            max_iterations
        )
        
        # Extract and return result
        return extract_subagent_result(
            task_spec,
            messages,
            iteration,
            tool_calls_count,
            extract_sources_from_messages
        )
    
    def _build_system_message(
        self,
        task: str,
        focus: str,
        context: str
    ) -> str:
        """
        Build system message for subagent.
        
        Subagents receive minimal instructions - just their specific task.
        The orchestrator handles all context-aware planning.
        (Following Anthropic/Gemini pattern)
        
        Args:
            task: Main research task (specific query from orchestrator)
            focus: Focus area (optional)
            context: Not used - subagents should not be overwhelmed with context
            
        Returns:
            System message content
        """
        message_parts = [
            "You are a research subagent. Execute the given research task thoroughly.",
            "",
            "Guidelines:",
            "1. Use web search to find authoritative, recent information",
            "2. Make 2-3 searches with different angles/keywords for comprehensive coverage",
            "3. Include source URLs in your findings",
            "4. Focus on factual, verifiable information",
            "5. Be comprehensive but concise",
            "6. Note any conflicting information you find",
            "",
        ]
        
        if focus:
            message_parts.extend([
                f"Focus area: {focus}",
                ""
            ])
        
        message_parts.append(f"Your research task: {task}")
        
        return "\n".join(message_parts)
    
    def _get_llm_with_forced_tool(self, tools: List[Any]) -> Any:
        """
        Get LLM with forced tool use (for first iteration).
        
        Uses tool_choice parameter to force the agent to call a tool.
        
        Args:
            tools: Available tools
            
        Returns:
            LLM with forced tool configuration
        """
        # Prefer web_search tool if available
        preferred_tool = None
        for tool in tools:
            if hasattr(tool, 'name') and 'search' in tool.name.lower():
                preferred_tool = tool.name
                break
        
        # If no search tool, use first available
        if not preferred_tool and tools:
            preferred_tool = tools[0].name if hasattr(tools[0], 'name') else None
        
        llm = self._get_llm(bind_tools=tools)
        
        # Force tool use
        if preferred_tool:
            try:
                # OpenAI format
                llm = llm.bind(tool_choice={"type": "function", "function": {"name": preferred_tool}})
            except Exception:
                # Fallback: force any tool
                try:
                    llm = llm.bind(tool_choice="required")
                except Exception as e:
                    logger.warning("Could not force tool use: %s", e)
        
        return llm
    
    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tools: List[Any]
    ) -> str:
        """
        Execute a tool by name.
        
        Args:
            tool_name: Name of tool to execute
            tool_args: Arguments for the tool
            tools: List of available tools
            
        Returns:
            Tool result as string
        """
        # Find the tool
        tool = None
        for t in tools:
            if hasattr(t, 'name') and t.name == tool_name:
                tool = t
                break
        
        if not tool:
            logger.warning("Tool not found: %s", tool_name)
            return f"Error: Tool '{tool_name}' not available"
        
        try:
            # Execute tool
            logger.debug("Executing tool %s with args: %s", tool_name, tool_args)
            result = await tool.ainvoke(tool_args)
            
            # Truncate very long results using semantic boundaries
            if isinstance(result, str) and len(result) > settings.TOOL_RESULT_MAX_LENGTH:
                logger.debug("Truncating long tool result (%d chars)", len(result))
                result = smart_truncate_for_llm(
                    result,
                    max_length=settings.TOOL_RESULT_MAX_LENGTH,
                    keep_start=True,
                    keep_end=False
                )
            
            return str(result)
            
        except Exception as e:
            logger.error("Tool %s execution failed: %s", tool_name, e)
            return f"Error executing {tool_name}: {str(e)}"

