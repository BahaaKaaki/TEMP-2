"""
Subagent node implementation.

Inspired by Anthropic's multi-agent research system.
Creates multiple parallel agents to explore different aspects simultaneously.
"""

from typing import Dict, Any, List, Optional
from .base import BaseNode
from ..state import WorkflowState
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from ..tools.registry import get_tool_registry
import logging
import asyncio
# from langfuse import observe  # DISABLED
from utils.langfuse_config import observe  # No-op decorator
from .subagent_helpers import (
    prepare_subagent_llm,
    create_subagent_messages,
    run_tool_execution_loop,
    extract_final_response
)

logger = logging.getLogger(__name__)


class SubagentNode(BaseNode):
    """
    Subagent node for parallel task execution.
    
    Creates multiple specialized agents that work simultaneously,
    each with their own context window and tools.
    
    Inspired by Anthropic's orchestrator-worker pattern.
    """
    
    async def execute(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute the subagent node.
        
        Creates multiple agents to explore different aspects in parallel.
        
        Args:
            state: Current workflow state
            
        Returns:
            Aggregated results from all subagents
        """
        # Get input data from state
        input_data = self.get_input_from_state(state)
        
        config = self.node_config or {}
        
        # Get configuration
        num_agents = config.get("num_agents", 3)
        parallel = config.get("parallel", True)
        task_decomposition = config.get("task_decomposition", "auto")
        tools = config.get("tools", [])
        model_provider = config.get("modelProvider", LLMConfig.DEFAULT_PROVIDER)
        model_name = config.get("modelName", LLMConfig.DEFAULT_MODEL)
        
        logger.debug("🔍 Subagent node using model: %s/%s", model_provider, model_name)
        
        logger.debug(
            "Subagent node executing with %d agents (parallel=%s)",
            num_agents,
            parallel
        )
        
        # Decompose task into subtasks
        subtasks = await self._decompose_task(
            input_data,
            num_agents,
            task_decomposition,
            state
        )
        
        logger.info("Decomposed into %d subtasks", len(subtasks))
        
        # Execute subagents
        if parallel:
            results = await self._execute_parallel(
                subtasks,
                tools,
                model_provider,
                model_name,
                state
            )
        else:
            results = await self._execute_sequential(
                subtasks,
                tools,
                model_provider,
                model_name,
                state
            )
        
        # Aggregate results
        aggregated = self._aggregate_results(results)
        
        return {
            "num_subagents": len(subtasks),
            "subtasks": [{"task": t["task"], "status": "completed"} for t in subtasks],
            "results": results,
            "aggregated": aggregated,
            "parallel": parallel
        }
    
    async def _decompose_task(
        self,
        input_data: Any,
        num_agents: int,
        method: str,
        state: WorkflowState
    ) -> List[Dict[str, Any]]:
        """
        Decompose the main task into subtasks.
        
        Args:
            input_data: Input data to decompose
            num_agents: Number of subtasks to create
            method: Decomposition method ('auto', 'manual', 'llm')
            state: Workflow state
            
        Returns:
            List of subtask specifications
        """
        if method == "manual" and isinstance(input_data, dict) and "subtasks" in input_data:
            # User provided manual subtasks
            return input_data["subtasks"]
        
        # Auto decomposition using LLM
        main_query = input_data
        if isinstance(input_data, dict):
            main_query = input_data.get("message") or input_data.get("query") or str(input_data)
        
        # Use LLM to decompose (simplified for now)
        # In production, this should call an LLM to intelligently split the task
        subtasks = []
        
        if "research" in str(main_query).lower():
            # Research-style decomposition
            aspects = [
                "historical context and background",
                "current state and recent developments",
                "technical details and mechanisms",
                "expert opinions and analysis",
                "future implications and predictions"
            ]
            
            for i in range(min(num_agents, len(aspects))):
                subtasks.append({
                    "id": f"subagent_{i+1}",
                    "task": f"Research {aspects[i]} of: {main_query}",
                    "focus": aspects[i]
                })
        else:
            # Generic decomposition
            for i in range(num_agents):
                subtasks.append({
                    "id": f"subagent_{i+1}",
                    "task": f"Aspect {i+1} of: {main_query}",
                    "focus": f"perspective_{i+1}"
                })
        
        return subtasks
    
    async def _execute_parallel(
        self,
        subtasks: List[Dict[str, Any]],
        tools: List[str],
        model_provider: str,
        model_name: str,
        state: WorkflowState
    ) -> List[Dict[str, Any]]:
        """
        Execute subagents in parallel.
        
        Args:
            subtasks: List of subtask specifications
            tools: Tools available to subagents
            model_provider: AI model provider
            model_name: AI model name
            state: Workflow state
            
        Returns:
            List of results from all subagents
        """
        # Create tasks for async execution
        tasks = [
            self._execute_single_agent(
                subtask,
                tools,
                model_provider,
                model_name,
                state
            )
            for subtask in subtasks
        ]
        
        # Execute all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Subagent %d failed: %s", i, result)
                processed_results.append({
                    "subagent_id": subtasks[i]["id"],
                    "status": "failed",
                    "error": str(result)
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def _execute_sequential(
        self,
        subtasks: List[Dict[str, Any]],
        tools: List[str],
        model_provider: str,
        model_name: str,
        state: WorkflowState
    ) -> List[Dict[str, Any]]:
        """
        Execute subagents sequentially.
        
        Args:
            subtasks: List of subtask specifications
            tools: Tools available to subagents
            model_provider: AI model provider
            model_name: AI model name
            state: Workflow state
            
        Returns:
            List of results from all subagents
        """
        results = []
        
        for subtask in subtasks:
            try:
                result = await self._execute_single_agent(
                    subtask,
                    tools,
                    model_provider,
                    model_name,
                    state
                )
                results.append(result)
            except Exception as e:
                logger.error("Subagent %s failed: %s", subtask["id"], e)
                results.append({
                    "subagent_id": subtask["id"],
                    "status": "failed",
                    "error": str(e)
                })
        
        return results
    
    @observe(name="subagent_execute_single")
    async def _execute_single_agent(
        self,
        subtask: Dict[str, Any],
        tools: List[str],
        model_provider: str,
        model_name: str,
        state: WorkflowState
    ) -> Dict[str, Any]:
        """
        Execute a single subagent.
        
        Delegates to helper functions for LLM preparation, tool execution, and result extraction.
        
        Args:
            subtask: Subtask specification
            tools: Available tools
            model_provider: AI model provider
            model_name: AI model name
            state: Workflow state
            
        Returns:
            Result from the subagent
        """
        logger.info("Executing subagent: %s", subtask["id"])
        
        # Get LLM
        llm = self._get_llm(model_provider, model_name)
        
        # Prepare LLM with tools
        llm_with_forced_tool, llm_with_optional_tools, agent_tools = prepare_subagent_llm(
            llm, tools, subtask["id"]
        )
        
        # Create initial messages
        messages = create_subagent_messages(subtask)
        
        # Execute tool loop
        iteration = await run_tool_execution_loop(
            llm_with_forced_tool,
            llm_with_optional_tools,
            messages,
            agent_tools,
            subtask["id"],
            max_iterations=5
        )
        
        # Extract final response
        final_response = extract_final_response(messages, subtask["id"], iteration)
        
        return {
            "subagent_id": subtask["id"],
            "task": subtask["task"],
            "status": "completed",
            "findings": final_response,
            "iterations": iteration,
            "tool_calls_made": iteration
        }
    
    def _get_llm(self, provider: str, model_name: str):
        """Get LLM instance using centralized client manager."""
        from app.config.llm_config import LLMClientManager
        
        return LLMClientManager.get_client(
            provider=provider,
            model=model_name,
            temperature=0.7,
            max_tokens=16000
        )
    
    def _aggregate_results(self, results: List[Dict[str, Any]]) -> str:
        """
        Aggregate results from all subagents.
        
        Args:
            results: List of subagent results
            
        Returns:
            Aggregated summary
        """
        aggregated = "# Aggregated Research Findings\n\n"
        
        for i, result in enumerate(results, 1):
            status = result.get("status", "unknown")
            
            if status == "completed":
                aggregated += f"## Finding {i}: {result.get('task', 'Unknown task')}\n"
                aggregated += f"{result.get('findings', 'No findings')}\n\n"
            else:
                aggregated += f"## Finding {i}: Failed\n"
                aggregated += f"Error: {result.get('error', 'Unknown error')}\n\n"
        
        return aggregated

