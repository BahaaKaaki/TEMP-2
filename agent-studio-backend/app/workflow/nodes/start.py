"""
Start node executor.

The start node is the entry point of a workflow. It initializes the state
and passes input data to the next node.
"""

from typing import Any
from .base import BaseNode
from ..state import WorkflowState


class StartNode(BaseNode):
    """
    Start node executor.
    
    This node marks the beginning of a workflow and prepares the initial state.
    """
    
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the start node.
        
        Adds the user's message from input_data to the state messages.
        On resume the node re-runs (base.py exempts start/chat from the
        "already executed" skip) but the initial message is already in
        state — new user messages are added directly by chat_service.
        """
        # If this node already ran, the initial message is in state.
        # New user messages are injected by chat_service, not here.
        node_outputs = state.get("node_outputs", {})
        if self.node_id in node_outputs:
            return {}

        input_data = state.get("input_data", {})
        user_message_text = input_data.get("message", "")
        display_message_text = input_data.get("display_message")
        user_message_id_in = input_data.get("user_message_id")
        question_message_id = input_data.get("question_message_id")
        question_response = input_data.get("question_response")

        if user_message_text:
            from langchain_core.messages import HumanMessage
            import uuid

            extras: dict = {
                "message_id": user_message_id_in or str(uuid.uuid4()),
                "display_content": display_message_text if display_message_text else None,
            }
            if question_message_id:
                extras["is_question_response"] = True
                extras["question_message_id"] = question_message_id
            if question_response:
                extras["question_response"] = question_response

            user_message = HumanMessage(
                content=user_message_text,
                additional_kwargs=extras,
            )

            return {
                "messages": [user_message]
            }

        return {}

