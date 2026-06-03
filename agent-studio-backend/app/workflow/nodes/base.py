"""
Base node executor interface.

All node executors must inherit from BaseNode and implement the execute method.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
import time
import logging
import uuid

from ..state import WorkflowState, NodeOutput
from ..parser import NodeConfig
from langchain_core.messages import AIMessage
from app.llm.observability_context import (
    merge_llm_observability_context,
    reset_llm_observability_context,
)
from app.tracing import emit_trace_event, reset_trace_context, set_trace_context

logger = logging.getLogger(__name__)


class BaseNode(ABC):
    """
    Base class for all workflow node executors.
    
    Each node type (agent, tool, condition, etc.) implements this interface
    to execute its specific logic within the workflow.
    """
    
    def __init__(self, config: NodeConfig):
        """
        Initialize the node executor.
        
        Args:
            config: Node configuration from workflow definition
        """
        self.config = config
        self.node_id = config.id
        self.node_type = config.type
        self.node_config = config.config
        self.label = config.config.get("label", f"{config.type}_{config.id}")
        
        if config.type in ["agent", "chat"]:
            logger.debug("BaseNode.__init__ - Node: %s, Type: %s, model: %s/%s",
                         self.node_id, self.node_type,
                         self.node_config.get("modelProvider"),
                         self.node_config.get("modelName"))
    
    async def __call__(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute the node and return state updates.
        
        This wrapper handles timing and error handling.
        Returns ONLY the fields to update, allowing LangGraph reducers to work.
        
        Args:
            state: Current workflow state
            
        Returns:
            Dict of state updates (not full state)
        """
        # If an error already occurred, skip all downstream nodes
        if state.get("error"):
            logger.info(
                "⏭️  Skipping node %s (%s) - workflow already in error state",
                self.label,
                self.node_type
            )
            return {}

        # Check if workflow is interrupted (e.g., waiting for HITL approval,
        # an agent's startupMessage/waitForUserInput pause, or a
        # code-executor paused via ``output.ask()``).  Skip this node unless
        # its type is expected to run even during an interrupt.
        #
        # Always-run node types:
        #   - hitl / human-in-the-loop / human: must run to detect a
        #     pending deliverable or collect user input for this node.
        #   - start / chat: must run to process the user message that
        #     triggered the resume.
        #
        # Code-executor is a CONDITIONAL always-run: it must re-execute
        # ONLY when it is being resumed from its own ``output.ask()``
        # pause (identified by ``pending_user_input.node_id == self.node_id``
        # together with ``user_input_response`` being set).  Any other
        # interrupt (an upstream agent pausing, a human node pausing,
        # HITL awaiting approval, …) must still skip downstream code-
        # executors, otherwise they run out-of-order before the paused
        # node produces its deliverable.
        if state.get("interrupted"):
            always_run_types = (
                "hitl",
                "human-in-the-loop",
                "human",
                "start",
                "chat",
            )

            should_skip = True
            if self.node_type in always_run_types:
                should_skip = False
            elif self.node_type == "code-executor":
                pending = state.get("pending_user_input") or {}
                is_own_pause_resume = (
                    pending.get("node_id") == self.node_id
                    and state.get("user_input_response") is not None
                )
                if is_own_pause_resume:
                    should_skip = False

            if should_skip:
                logger.info(
                    "⏭️  Skipping node %s (%s) - workflow is interrupted",
                    self.label,
                    self.node_type,
                )
                return {}  # Return empty dict - no state changes
        
        # Check if this node has already executed (for resume after HITL)
        # Skip nodes that have already produced output
        # EXCEPTION: 
        #   - HITL nodes must always run to check for deliverables
        #   - start/chat nodes must run to process user input
        #   - Multi-turn agents (has_deliverable=false) must continue until they produce a deliverable
        node_outputs = state.get("node_outputs", {})
        if self.node_id in node_outputs and self.node_type not in ["hitl", "human-in-the-loop", "human", "start", "chat"]:
            # Check if this is a multi-turn agent waiting for user input
            node_output = node_outputs[self.node_id]
            output_data = node_output.get("output", {}) if isinstance(node_output, dict) else {}
            has_deliverable = output_data.get("has_deliverable", True)  # Default to True for non-agent nodes
            
            # If agent asked a question (has_deliverable=false), allow it to re-execute with user's response
            if has_deliverable is False:
                logger.info(
                    "🔄 Node %s (%s) is in multi-turn mode (no deliverable yet) - will re-execute to continue",
                    self.label,
                    self.node_type
                )
            # Code executor resuming after midway input (output.ask()) must re-execute
            elif self.node_type == "code-executor" and (state.get("pending_user_input") or {}).get("node_id") == self.node_id and state.get("user_input_response"):
                logger.info(
                    "🔄 Node %s (%s) resuming after midway input - will re-execute with user response",
                    self.label,
                    self.node_type
                )
            else:
                logger.info(
                    "⏭️  Skipping node %s (%s) - already executed in this workflow run",
                    self.label,
                    self.node_type
                )
                return {}  # Return empty dict - node already ran
        
        start_time = time.time()
        
        metadata = state.get("metadata") or {}
        node_span_id = f"node:{self.node_id}:{uuid.uuid4().hex[:10]}"
        trace_tokens = set_trace_context(
            execution_id=metadata.get("execution_id"),
            session_id=metadata.get("session_id"),
            node_id=self.node_id,
            node_label=self.label,
            node_type=self.node_type,
            span_id=node_span_id,
        )
        obs_tokens = merge_llm_observability_context(
            node_id=self.node_id,
            node_label=self.label,
            node_type=self.node_type,
        )

        try:
            await emit_trace_event(
                "node.started",
                status="running",
                payload={
                    "label": self.label,
                    "node_type": self.node_type,
                },
                span_id=node_span_id,
            )
            logger.info("Executing node: %s (%s)", self.label, self.node_type)
            
            # Execute the node-specific logic
            output = await self.execute(state)
            
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            logger.info(
                "Node %s completed in %.2fms",
                self.label,
                duration_ms
            )
            
            # Store node output for tracking (exclude non-serializable fields like messages)
            # Messages are merged via LangGraph reducers, not stored in node_outputs
            output_for_tracking = {k: v for k, v in (output or {}).items() if k != "messages"}
            
            node_output_record = NodeOutput(
                node_id=self.node_id,
                node_type=self.node_type,
                output=output_for_tracking,
                timestamp=datetime.utcnow().isoformat(),
                duration_ms=duration_ms,
                status="success",
                error=None
            )
            
            # Return state updates (let LangGraph merge with reducers)
            # DON'T manually merge node_outputs - let the reducer do it!
            updates = {
                "node_outputs": {
                    self.node_id: node_output_record
                }
            }
            
            # Merge output fields (like messages, deliverables, etc.)
            # LangGraph will use reducers to merge these properly
            if output:
                updates.update(output)

            await emit_trace_event(
                "node.completed",
                status="success",
                payload={
                    "label": self.label,
                    "node_type": self.node_type,
                    "output_fields": list(output_for_tracking.keys())
                    if isinstance(output_for_tracking, dict)
                    else [],
                },
                duration_ms=duration_ms,
                span_id=node_span_id,
            )
            
            return updates
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            error_msg = f"Error in node {self.label}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await emit_trace_event(
                "node.failed",
                status="error",
                payload={
                    "label": self.label,
                    "node_type": self.node_type,
                    "error": error_msg,
                },
                duration_ms=duration_ms,
                span_id=node_span_id,
            )
            error_message = AIMessage(
                content=f"Error: {error_msg}",
                additional_kwargs={
                    "message_id": str(uuid.uuid4()),
                    "agent_id": self.node_id,
                    "agent_label": self.label,
                    "agent_type": self.node_type,
                    "is_error": True
                }
            )
            
            # Return error state update
            return {
                "error": error_msg,
                "error_node": self.node_id,
                "should_continue": False,
                "interrupted": True,
                "messages": [error_message],
                "node_outputs": {
                    self.node_id: NodeOutput(
                        node_id=self.node_id,
                        node_type=self.node_type,
                        output=None,
                        timestamp=datetime.utcnow().isoformat(),
                        duration_ms=duration_ms,
                        status="error",
                        error=error_msg
                    )
                }
            }
        finally:
            reset_trace_context(trace_tokens)
            reset_llm_observability_context(obs_tokens)
    
    @abstractmethod
    async def execute(self, state: WorkflowState) -> Any:
        """
        Execute the node-specific logic.
        
        Subclasses must implement this method to perform their specific task.
        
        Args:
            state: Current workflow state
            
        Returns:
            Output data from this node (can be any type)
        """
        pass
    
    def get_input_from_state(
        self,
        state: WorkflowState,
        input_key: Optional[str] = None
    ) -> Any:
        """
        Get input data for this node from the workflow state.
        
        Can retrieve from:
        1. A specific previous node's output (if input_key is a node ID)
        2. The workflow input_data
        3. A workflow variable
        
        Args:
            state: Current workflow state
            input_key: Key to look up input (node ID, variable name, etc.)
            
        Returns:
            Input data for this node
        """
        if not input_key:
            # Return the entire input_data
            return state.get("input_data", {})
        
        # Try to get from a previous node's output
        if input_key in state.get("node_outputs", {}):
            return state["node_outputs"][input_key].get("output")
        
        # Try to get from variables
        if input_key in state.get("variables", {}):
            return state["variables"][input_key]
        
        # Try to get from input_data
        if input_key in state.get("input_data", {}):
            return state["input_data"][input_key]
        
        return None
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value for this node.
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            Configuration value
        """
        return self.node_config.get(key, default)
