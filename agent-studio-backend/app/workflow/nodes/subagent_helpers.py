"""
Helper functions for subagent execution.

Contains reusable logic for single subagent execution, tool management, and result processing.
"""

from typing import Dict, Any, List
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from ..tools.registry import get_tool_registry
import logging

logger = logging.getLogger(__name__)


def prepare_subagent_llm(
    llm,
    tools: List[str],
    subtask_id: str
) -> tuple:
    """
    Prepare LLM instances with and without forced tool choice.
    
    Args:
        llm: Base LLM instance
        tools: List of tool names
        subtask_id: ID of the subtask for logging
        
    Returns:
        Tuple of (llm_with_forced_tool, llm_with_optional_tools, agent_tools)
    """
    # Get tools
    tool_registry = get_tool_registry()
    agent_tools = tool_registry.get_tools_by_names(tools)
    
    logger.debug("Subagent %s has %d tools available: %s", subtask_id, len(agent_tools), [t.name for t in agent_tools])
    
    if agent_tools:
        # FORCE the LLM to use web_search tool on first call
        # This ensures research uses current data, not training data
        # For LangChain OpenAI, use string "web_search" not dict
        llm_with_forced_tool = llm.bind_tools(agent_tools, tool_choice="web_search")
        llm_with_optional_tools = llm.bind_tools(agent_tools)  # No forced choice
        logger.debug("Subagent %s tools bound to LLM (web_search FORCED on first call)", subtask_id)
    else:
        logger.warning("Subagent %s has NO tools available!", subtask_id)
        llm_with_forced_tool = llm
        llm_with_optional_tools = llm
    
    return llm_with_forced_tool, llm_with_optional_tools, agent_tools


def create_subagent_messages(subtask: Dict[str, Any]) -> List:
    """
    Create initial messages for subagent execution.
    
    Args:
        subtask: Subtask specification
        
    Returns:
        List of initial messages
    """
    return [
        SystemMessage(content=(
            f"You are a specialized research agent with access to web search tools. "
            f"Your task: {subtask['task']}. "
            f"Focus on: {subtask.get('focus', 'gathering comprehensive information')}. "
            f"\n\nIMPORTANT: You MUST use the web_search tool to find current, accurate information. "
            f"DO NOT rely on your training data. Always search the web first. "
            f"\n\nSEARCH QUERY TIPS:"
            f"\n- Use specific, descriptive terms (e.g., 'artificial intelligence agents software development' not 'key benefits AI')"
            f"\n- Include year when looking for recent info (e.g., '2024' or '2025')"
            f"\n- Avoid common words that could trigger unrelated results"
            f"\n- If first search fails, try different phrasing"
            f"\n- Use quotes for exact phrases if needed"
            f"\n\nAfter gathering information from web search, synthesize your findings based on the actual search results."
        )),
        HumanMessage(content=f"Research this using web search (formulate a good search query): {subtask['task']}")
    ]


async def _execute_single_tool(
    tool_call: Dict[str, Any],
    agent_tools: List,
    subtask_id: str
) -> ToolMessage:
    """
    Execute a single tool call and return the result message.
    
    Args:
        tool_call: Tool call specification
        agent_tools: Available tools
        subtask_id: ID of the subtask for logging
        
    Returns:
        ToolMessage with result or error
    """
    tool_name = tool_call.get('name')
    tool_args = tool_call.get('args', {})
    tool_id = tool_call.get('id', '')
    
    logger.debug("🛠️  Executing tool: %s (subagent: %s)", tool_name, subtask_id)
    logger.debug("   Args: %s", tool_args)
    
    # Find tool
    tool = next((t for t in agent_tools if t.name == tool_name), None)
    
    if not tool:
        logger.warning("⚠️  Subagent %s requested UNKNOWN tool: %s", subtask_id, tool_name)
        return ToolMessage(
            content=f"Error: Tool '{tool_name}' not found",
            tool_call_id=tool_id
        )
    
    try:
        tool_result = await tool.ainvoke(tool_args)
        result_preview = str(tool_result)[:300]
        logger.debug("✅ Tool %s SUCCESS! Result length: %d chars", tool_name, len(str(tool_result)))
        logger.debug("   Preview: %s...", result_preview)
        
        return ToolMessage(
            content=str(tool_result),
            tool_call_id=tool_id
        )
        
    except Exception as e:
        logger.error("❌ Tool %s FAILED: %s", tool_name, e)
        return ToolMessage(
            content=f"Error: {str(e)}",
            tool_call_id=tool_id
        )


async def execute_tool_calls(
    tool_calls: List[Dict[str, Any]],
    agent_tools: List,
    messages: List,
    subtask_id: str
) -> None:
    """
    Execute all tool calls IN PARALLEL and append results to messages.
    
    Performance optimization: Multiple tools execute simultaneously instead of sequentially.
    For example, if LLM requests google_search + kb_search + calculator:
    - Sequential (old): 2s + 1.5s + 0.1s = 3.6s
    - Parallel (new): max(2s, 1.5s, 0.1s) = 2s (45% faster!)
    
    Args:
        tool_calls: List of tool calls to execute
        agent_tools: Available tools
        messages: Message list to append results to
        subtask_id: ID of the subtask for logging
    """
    if not tool_calls:
        return
    
    logger.debug("🔨 Subagent %s executing %d tool calls IN PARALLEL", subtask_id, len(tool_calls))
    
    # Execute all tools in parallel using asyncio.gather
    tool_results = await asyncio.gather(*[
        _execute_single_tool(tool_call, agent_tools, subtask_id)
        for tool_call in tool_calls
    ], return_exceptions=True)
    
    # Append all results to messages (maintaining order)
    for i, result in enumerate(tool_results):
        if isinstance(result, Exception):
            logger.error("❌ Tool call %d failed with exception: %s", i, result)
            # Create error message for this tool
            tool_id = tool_calls[i].get('id', '')
            messages.append(ToolMessage(
                content=f"Error: {str(result)}",
                tool_call_id=tool_id
            ))
        else:
            messages.append(result)
    
    logger.debug("📨 All %d tool results appended. Total messages: %d", len(tool_calls), len(messages))
    logger.debug("🔄 Loop will CONTINUE to let LLM process these results...")


async def run_tool_execution_loop(
    llm_with_forced_tool,
    llm_with_optional_tools,
    messages: List,
    agent_tools: List,
    subtask_id: str,
    max_iterations: int = 5
) -> int:
    """
    Run the tool execution loop until completion or max iterations.
    
    Args:
        llm_with_forced_tool: LLM with forced tool choice
        llm_with_optional_tools: LLM with optional tools
        messages: Message list to process
        agent_tools: Available tools
        subtask_id: ID of the subtask for logging
        max_iterations: Maximum number of iterations
        
    Returns:
        Number of iterations executed
    """
    iteration = 0
    
    logger.info("Subagent %s starting tool execution loop (max %d iterations)", subtask_id, max_iterations)
    
    while iteration < max_iterations:
        iteration += 1
        logger.debug("=" * 80)
        logger.debug("🔄 Subagent %s ITERATION %d/%d", subtask_id, iteration, max_iterations)
        logger.debug("=" * 80)
        
        # Use forced tool choice ONLY on first iteration
        current_llm = llm_with_forced_tool if iteration == 1 else llm_with_optional_tools
        logger.debug("🤖 Using LLM with %s", "FORCED web_search" if iteration == 1 else "OPTIONAL tools")
        
        response = await current_llm.ainvoke(messages)
        logger.debug("📥 Subagent %s received response type: %s", subtask_id, type(response).__name__)
        
        # DEBUG: Print response content
        if hasattr(response, 'content'):
            logger.debug("📝 Response content: %s", response.content[:200] if response.content else "None")
        
        messages.append(response)
        logger.debug("📨 Messages in conversation: %d", len(messages))
        
        # Check if there are tool calls
        tool_calls = getattr(response, 'tool_calls', [])
        logger.debug("🔧 Tool calls requested: %d", len(tool_calls))
        
        if not tool_calls:
            # No tool calls - we have the final answer
            logger.info("✅ Subagent %s completed after %d iterations (no more tools needed)", subtask_id, iteration)
            logger.debug("📄 Final response content: %s", response.content[:300] if hasattr(response, 'content') else "No content")
            break
        
        # Execute tools
        await execute_tool_calls(tool_calls, agent_tools, messages, subtask_id)
        
        logger.debug("🔄 Iteration %d complete. Continuing loop to process tool results...", iteration)
    
    return iteration


def extract_final_response(messages: List, subtask_id: str, iteration: int) -> str:
    """
    Extract the final response from the message chain.
    
    Args:
        messages: Message list
        subtask_id: ID of the subtask for logging
        iteration: Number of iterations completed
        
    Returns:
        Final response content
    """
    logger.debug("=" * 80)
    logger.debug("🏁 Extracting final response from message chain")
    logger.debug("   Total messages: %d", len(messages))
    if messages:
        logger.debug("   Last message type: %s", type(messages[-1]).__name__)
        if hasattr(messages[-1], 'content'):
            logger.debug("   Last message content preview: %s...", str(messages[-1].content)[:200])
    
    final_response = messages[-1].content if messages and hasattr(messages[-1], 'content') else "No response"
    
    logger.debug("=" * 80)
    logger.info("✅ Subagent %s FINISHED", subtask_id)
    logger.debug("   Total iterations: %d", iteration)
    logger.debug("   Final response length: %d chars", len(str(final_response)))
    logger.debug("   Final response preview: %s...", str(final_response)[:300])
    logger.debug("=" * 80)
    
    return final_response

