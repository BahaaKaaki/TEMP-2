"""
Human node executor.

Pauses workflow execution and waits for human input.
"""

from typing import Any
import logging

from .base import BaseNode
from ..state import WorkflowState

logger = logging.getLogger(__name__)


class HumanNode(BaseNode):
    """
    Human node executor.
    
    Pauses workflow execution and waits for human input.
    The workflow must be resumed with the user's input.
    """
    
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the human node.
        
        Args:
            state: Current workflow state
            
        Returns:
            User input (if provided) or pause indication
        """
        # Check if we have user input response
        if state.get("user_input_response"):
            # User has provided input, return it
            user_input = state["user_input_response"]
            state["user_input_response"] = None  # Clear it
            state["pending_user_input"] = None
            
            logger.info("Received user input: %s", user_input)
            return user_input
        
        # No user input yet, pause the workflow
        prompt = self.get_config_value("prompt", "Please provide input")
        input_schema = self.get_config_value("inputSchema", {})
        
        # Set pending user input
        state["pending_user_input"] = {
            "node_id": self.node_id,
            "prompt": prompt,
            "schema": input_schema
        }
        
        # Mark as interrupted
        state["interrupted"] = True
        state["metadata"]["status"] = "paused"
        
        logger.info("Workflow paused for human input at node: %s", self.label)
        
        return {
            "status": "waiting_for_input",
            "prompt": prompt
        }


