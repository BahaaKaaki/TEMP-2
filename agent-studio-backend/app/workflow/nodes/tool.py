"""
Tool node executor.

Executes a specific tool (API call, web search, etc.).
"""

from typing import Any
import logging

from .base import BaseNode
from ..state import WorkflowState
from ..tools.registry import get_tool_registry
from app.tracing import trace_tool_call

logger = logging.getLogger(__name__)


class ToolNode(BaseNode):
    """
    Tool node executor.
    
    Executes a specific tool with input from the workflow state.
    """
    
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the tool node.
        
        Args:
            state: Current workflow state
            
        Returns:
            Tool execution result
        """
        # Get tool configuration
        tool_name = self.get_config_value("toolName")
        tool_params = self.get_config_value("parameters", {})
        
        if not tool_name:
            raise ValueError(f"Tool node {self.node_id} missing toolName configuration")
        
        # Get input data
        input_source = self.get_config_value("inputSource")
        input_data = self.get_input_from_state(state, input_source)
        
        # Merge input data with configured parameters
        if isinstance(input_data, dict):
            params = {**tool_params, **input_data}
        else:
            params = tool_params.copy()
            params["input"] = input_data
        
        # Get the tool from registry
        registry = get_tool_registry()
        tool = registry.get_tool(tool_name)
        
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        
        # Execute the tool
        try:
            logger.info("Executing tool: %s with params: %s", tool_name, params)
            result = await trace_tool_call(
                tool_name,
                params,
                lambda: tool.ainvoke(params),
                payload={"source": "tool_node"},
            )
            
            return {
                "tool": tool_name,
                "result": result,
                "params": params
            }
            
        except Exception as e:
            logger.error("Error executing tool %s: %s", tool_name, e)
            raise

