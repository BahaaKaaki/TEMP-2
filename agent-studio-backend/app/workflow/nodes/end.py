"""
End node executor.

The end node marks the completion of a workflow and prepares the final output.
"""

from typing import Any, Dict
from .base import BaseNode
from ..state import WorkflowState


class EndNode(BaseNode):
    """
    End node executor.
    
    This node marks the end of a workflow and compiles the final output.
    """
    
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the end node.
        
        Compiles the final output from the workflow execution.
        
        Args:
            state: Current workflow state
            
        Returns:
            Final workflow output
        """
        # Collect outputs from specified nodes or all nodes
        output_nodes = self.get_config_value("outputNodes", [])
        
        if output_nodes:
            # Return outputs from specific nodes
            output_data = {}
            for node_id in output_nodes:
                if node_id in state.get("node_outputs", {}):
                    output_data[node_id] = state["node_outputs"][node_id].get("output")
        else:
            # Return all node outputs
            output_data = {
                node_id: output.get("output")
                for node_id, output in state.get("node_outputs", {}).items()
            }
        
        # Set the final output in state
        state["output_data"] = output_data
        state["metadata"]["status"] = "completed"
        state["should_continue"] = False
        
        return output_data


