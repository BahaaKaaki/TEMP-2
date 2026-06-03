"""
Helper functions for research subagent execution.

Contains reusable logic for initializing subagent messages,
executing tool loops, and extracting results.
"""

from typing import Dict, Any, List
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
import logging

logger = logging.getLogger(__name__)


def initialize_subagent_messages(
    task_spec: Dict[str, Any],
    tools: List[Any],
    system_message_builder
) -> List:
    """
    Initialize messages for subagent execution.
    
    Args:
        task_spec: Task specification containing id, task, focus, context
        tools: List of available tools
        system_message_builder: Function to build system message
        
    Returns:
        List of initial messages
    """
    subagent_id = task_spec.get("id", "unknown")
    task = task_spec.get("task", "")
    focus = task_spec.get("focus", "")
    context = task_spec.get("context", "")
    
    # Build system message
    system_content = system_message_builder(task, focus, context)
    
    # Add KB instructions if knowledge base tool is available
    kb_tool = next((t for t in tools if hasattr(t, 'name') and 'search_' in t.name.lower()), None)
    if kb_tool:
        system_content += """

## KNOWLEDGE BASE ACCESS
You have access to a knowledge base search tool. IMPORTANT:
- ALWAYS search the knowledge base FIRST before using web search
- Knowledge bases contain domain-specific, curated information that is more reliable than web search
- Use the knowledge base search tool when your task involves specific documents, reports, policies, or domain knowledge

CITATION REQUIREMENTS (CRITICAL):
- The KB tool returns text with citation markers like [1], [2], [3] at the end of each piece of information
- When you use KB information, you MUST include ALL the citation markers [N] in your response
- Example: If tool returns 'Funding by NSFC [1]', you write: 'The work was funded by NSFC [1]'
- NEVER remove the [N] markers - they are essential for source attribution
- Include markers immediately after the information they cite

- If KB search returns no results, then use web search as a fallback
- You can search the KB multiple times with different queries for comprehensive coverage
"""
        logger.debug("Added KB instructions to subagent %s system prompt", subagent_id)
    
    # Initialize messages
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=task)
    ]


async def execute_subagent_tool_loop(
    subagent_id: str,
    messages: List,
    tools: List[Any],
    llm_getter,
    llm_with_forced_tool_getter,
    tool_executor,
    max_iterations: int = 10
) -> tuple:
    """
    Execute the tool loop for subagent execution.
    
    Args:
        subagent_id: Unique subagent identifier
        messages: List of messages
        tools: Available tools
        llm_getter: Function to get LLM with tools
        llm_with_forced_tool_getter: Function to get LLM with forced tool
        tool_executor: Function to execute a tool
        max_iterations: Maximum iterations
        
    Returns:
        Tuple of (iteration_count, tool_calls_count)
    """
    iteration = 0
    tool_calls_count = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # Force tool use on first iteration (Anthropic pattern)
        if iteration == 1:
            llm = llm_with_forced_tool_getter(tools)
            logger.debug("Subagent %s iteration 1: forcing tool use", subagent_id)
        else:
            llm = llm_getter(bind_tools=tools)
        
        try:
            # Invoke LLM
            response = await llm.ainvoke(messages)
            messages.append(response)
            
            # Check for tool calls
            tool_calls = getattr(response, 'tool_calls', [])
            
            if not tool_calls:
                # No more tool calls - final answer
                logger.debug(
                    "Subagent %s completed after %d iterations",
                    subagent_id,
                    iteration
                )
                break
            
            # Execute tools
            logger.debug(
                "Subagent %s executing %d tool calls",
                subagent_id,
                len(tool_calls)
            )
            
            for tool_call in tool_calls:
                tool_name = tool_call.get('name', 'unknown')
                tool_args = tool_call.get('args', {})
                tool_id = tool_call.get('id', '')
                
                # Find and execute the tool
                tool_result = await tool_executor(
                    tool_name,
                    tool_args,
                    tools
                )
                
                # Add tool result to messages
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id
                ))
                
                tool_calls_count += 1
            
        except Exception as e:
            logger.error(
                "Subagent %s error in iteration %d: %s",
                subagent_id,
                iteration,
                e
            )
            # Continue with partial results
            break
    
    return iteration, tool_calls_count


def extract_subagent_result(
    task_spec: Dict[str, Any],
    messages: List,
    iteration: int,
    tool_calls_count: int,
    sources_extractor
) -> Dict[str, Any]:
    """
    Extract final result from subagent execution.
    
    Args:
        task_spec: Task specification
        messages: List of messages
        iteration: Number of iterations completed
        tool_calls_count: Total tool calls made
        sources_extractor: Function to extract sources from messages
        
    Returns:
        Result dictionary
    """
    subagent_id = task_spec.get("id", "unknown")
    task = task_spec.get("task", "")
    
    # Extract findings from final message
    findings = messages[-1].content if messages else ""
    
    # Extract sources from tool messages
    sources = sources_extractor(messages)
    
    logger.info(
        "Subagent %s complete: %d iterations, %d tool calls, %d sources",
        subagent_id,
        iteration,
        tool_calls_count,
        len(sources)
    )
    
    return {
        "subagent_id": subagent_id,
        "task": task,
        "findings": findings,
        "sources": sources,
        "iterations": iteration,
        "tool_calls_count": tool_calls_count
    }

