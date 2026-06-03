"""
Workflow execution logic.

Contains the main workflow execution method that handles:
- Loading and validating workflows
- Building execution graphs
- Running workflows with state management
- Handling execution results and errors
"""

from typing import Dict, Any, Optional
from datetime import datetime
import logging
import uuid

from langchain_core.messages import AIMessage

from .parser import WorkflowParser
from .builder import WorkflowGraphBuilder
from .state import (
    create_initial_state,
    WorkflowState,
    add_messages_reducer,
    merge_node_outputs
)
from .validation import WorkflowValidator, format_validation_report

logger = logging.getLogger(__name__)


def _build_direct_next_is_hitl(parsed_workflow) -> Dict[str, bool]:
    """Build map of node_id -> whether its direct next node is a HITL."""
    node_type_by_id = {n.id: n.type for n in parsed_workflow.nodes}
    hitl_types = {"human-in-the-loop", "hitl", "human"}
    direct_next_is_hitl: Dict[str, bool] = {}

    for node in parsed_workflow.nodes:
        outgoing = parsed_workflow.get_outgoing_edges(node.id)
        direct_next_is_hitl[node.id] = any(
            node_type_by_id.get(edge.target) in hitl_types for edge in outgoing
        )

    return direct_next_is_hitl


def _build_direct_next_agent_startup(parsed_workflow) -> Dict[str, Dict[str, Any]]:
    """Build map of node_id -> next agent startup info (direct edge only).

    Always includes agents that have a ``startupMessage`` so the message
    is displayed in the chat.  The ``wait_for_input`` flag is carried
    through so the consumer can decide whether to also pause the workflow.
    """
    from app.workflow.utils.startup import (
        get_startup_message_text,
        has_startup_content,
        should_wait_for_startup,
    )

    node_by_id = {n.id: n for n in parsed_workflow.nodes}
    direct_next_startup: Dict[str, Dict[str, Any]] = {}

    for node in parsed_workflow.nodes:
        outgoing = parsed_workflow.get_outgoing_edges(node.id)
        for edge in outgoing:
            target = node_by_id.get(edge.target)
            if not target:
                continue
            target_config = target.config or {}

            if has_startup_content(target_config):
                direct_next_startup[node.id] = {
                    "agent_id": target.id,
                    "agent_label": target_config.get("label", "Agent"),
                    "agent_type": target.type,
                    "startup_message": get_startup_message_text(target_config),
                    "wait_for_input": should_wait_for_startup(target_config),
                }
                break

    return direct_next_startup


async def execute_workflow(
    executor_self,  # The WorkflowExecutor instance
    workflow_id: str,
    input_data: Dict[str, Any],
    initial_message: Optional[str] = None,
    variables: Optional[Dict[str, Any]] = None,
    existing_messages: Optional[list] = None,
    session_id: Optional[str] = None,
    existing_execution_id: Optional[int] = None,
):
    """
    Execute a workflow.
    
    Args:
        executor_self: The WorkflowExecutor instance
        workflow_id: ID of the workflow to execute
        input_data: Input data for the workflow
        initial_message: Optional initial message for chat workflows
        variables: Optional initial variables
        existing_messages: Optional existing conversation messages (for continuing conversations)
        session_id: Optional session ID to link execution to immediately at creation
        
    Returns:
        WorkflowExecutionResult with execution details
    """
    try:
        # Load workflow from database
        workflow = await executor_self._load_workflow(workflow_id)
        
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        if not workflow.active:
            is_owner = (
                executor_self.user_id
                and str(executor_self.user_id) == str(workflow.createdById)
                and not workflow.isArchived
            )
            if is_owner:
                workflow.active = True
                await executor_self.db_session.commit()
                logger.debug("Activated workflow %s for execution", workflow_id)
            else:
                raise ValueError(f"Workflow {workflow_id} is not active")
        
        # Parse workflow
        workflow_json = await executor_self._build_workflow_json(workflow)
        
        # 🛡️ VALIDATION: Validate and auto-fix common issues
        workflow_json, validation_issues = WorkflowValidator.validate_and_fix(
            workflow_json, 
            auto_fix=True
        )
        
        # Log validation results
        if validation_issues:
            validation_report = format_validation_report(validation_issues)
            logger.warning("Workflow validation found issues:\n%s", validation_report)
            
            # Check for blocking errors
            errors = [i for i in validation_issues if i.get("severity") == "error"]
            if errors:
                error_msg = f"Workflow has {len(errors)} critical error(s). " + validation_report
                raise ValueError(error_msg)
        else:
            logger.info("Workflow validation passed")
        
        parsed_workflow = WorkflowParser.parse(workflow_json)
        
        # Create execution record (or reuse one pre-created for background launches)
        if existing_execution_id is not None:
            execution_id = existing_execution_id
        else:
            execution_id = await executor_self._create_execution_record(
                workflow_id=workflow_id,
                workflow_data=workflow_json,
                user_id=executor_self.user_id,
                session_id=session_id,
            )
        
        from app.llm.observability_context import lookup_user_email

        user_id_str = str(executor_self.user_id) if executor_self.user_id else None
        user_email = await lookup_user_email(executor_self.db_session, user_id_str)

        # Create initial state
        state = create_initial_state(
            workflow_id=workflow_id,
            workflow_name=workflow.name,
            input_data=input_data,
            execution_id=execution_id,
            initial_message=initial_message,
            user_id=user_id_str,
            user_email=user_email,
            session_id=session_id,
        )

        # Store direct-next HITL map for nodes (used to auto-approve deliverables)
        if "metadata" not in state:
            state["metadata"] = {}
        state["metadata"]["direct_next_is_hitl"] = _build_direct_next_is_hitl(parsed_workflow)
        state["metadata"]["direct_next_agent_startup"] = _build_direct_next_agent_startup(parsed_workflow)
        if session_id:
            state["metadata"]["session_id"] = session_id
        
        # DEBUG: Log the initial state's input_data
        if isinstance(input_data, dict) and "message" in input_data:
            logger.debug(
                "Created new state with input_data.message: %s",
                input_data["message"][:100]
            )
        
        # Add existing messages for conversation continuity
        if existing_messages:
            logger.debug(
                "Adding %d existing messages to state for conversation continuity",
                len(existing_messages)
            )
            # Prepend existing messages BEFORE any new messages from initial_state
            new_messages = state.get("messages", [])
            state["messages"] = existing_messages + new_messages
            
            # IMPORTANT: Clear node_outputs from previous executions
            # Otherwise the agent will try to use the old output as input!
            state["node_outputs"] = {}
            
            logger.debug(
                "State now has %d total messages (%d existing + %d new)",
                len(state["messages"]),
                len(existing_messages),
                len(new_messages)
            )
            logger.debug("Cleared node_outputs to force agent to use new input_data")
        
        # Set initial variables
        if variables:
            # Extract force_deliver flag injected by ChatService
            if variables.pop("_force_deliver", False):
                state["force_deliver"] = True
            state["variables"] = variables
        
        # 🔧 FIX: Save initial state to DB before workflow execution starts
        # This makes the conversation history (including user message) immediately visible
        # when querying the session, even while workflow is still running.
        #
        # Include the user's HumanMessage from input_data so that polling sees
        # [... existing, HumanMessage] instead of just [...existing AIMessage].
        # Without this, the last message is "assistant" (the greeting) and the
        # frontend's polling thinks the workflow is idle and stops immediately.
        save_state = dict(state)
        save_state["messages"] = list(state.get("messages", []))
        if isinstance(input_data, dict) and input_data.get("message"):
            from langchain_core.messages import HumanMessage as _HM
            save_state["messages"].append(
                _HM(
                    content=input_data["message"],
                    additional_kwargs={
                        "message_id": input_data.get("user_message_id") or str(uuid.uuid4()),
                        "display_content": input_data.get("display_message", input_data["message"]),
                    },
                )
            )
        await executor_self._save_state_to_db(execution_id, save_state)
        logger.info("Saved initial state to DB")
        
        # Build and compile graph
        builder = WorkflowGraphBuilder(parsed_workflow)
        graph = builder.build()
        
        # Compile graph (checkpointing handled separately for now)
        compiled_graph = graph.compile()
        
        # Execute workflow
        logger.info("Executing workflow %s (execution %d)", workflow_id, execution_id)

        from app.llm.observability_context import (
            apply_workflow_observability_context,
            reset_llm_observability_context,
        )

        workflow_obs_tokens = apply_workflow_observability_context(state)
        
        config = {"configurable": {"thread_id": str(execution_id)}}
        final_state = None
        
        try:
            # Run the graph
            logger.debug("🔍 DEBUG: Starting LangGraph execution with state.messages = %d", len(state.get("messages", [])))
            logger.debug("🔍 DEBUG: State.input_data = %s", state.get("input_data"))
            logger.debug("🔍 DEBUG: Initial state type: %s", type(state))
            
            event_count = 0

            # Accumulate state incrementally from each node event.
            # After every node completes we save to DB so the frontend
            # can poll and display progressive updates.
            # Start from a full copy of the original state so that
            # intermediate saves don't lose fields like metadata/variables.
            accumulated_state = {**state}
            accumulated_state["messages"] = state.get("messages", []).copy() if isinstance(state.get("messages"), list) else []
            accumulated_state["node_outputs"] = state.get("node_outputs", {}).copy() if isinstance(state.get("node_outputs"), dict) else {}

            logger.debug("🔍 Starting accumulation with %d messages from initial state", len(accumulated_state["messages"]))

            saved_deliverable_ids: set = set()

            async for event in compiled_graph.astream(state, config):
                event_count += 1
                logger.debug("Workflow event %d: %s", event_count, list(event.keys()))

                for node_name, node_state in event.items():
                    if isinstance(node_state, dict):
                        for key, value in node_state.items():
                            if key == "messages" and isinstance(value, list):
                                accumulated_state["messages"] = add_messages_reducer(
                                    accumulated_state["messages"],
                                    value
                                )
                                logger.debug(f"      ✅ Added {len(value)} message(s) from {node_name}, total now: {len(accumulated_state['messages'])}")
                            elif key == "node_outputs" and isinstance(value, dict):
                                accumulated_state["node_outputs"] = merge_node_outputs(
                                    accumulated_state["node_outputs"],
                                    value
                                )
                            else:
                                accumulated_state[key] = value

                # Flush intermediate state to DB after every node so the
                # frontend can pick up new messages via polling.
                try:
                    await executor_self._save_state_to_db(execution_id, accumulated_state)
                except Exception as save_err:
                    logger.warning("⚠️ Intermediate state save failed: %s", save_err)
                    try:
                        await executor_self.db_session.rollback()
                        await executor_self._restore_rls_context()
                    except Exception:
                        pass

                # Also persist new deliverables to the deliverables table so
                # the frontend can display them progressively.
                try:
                    saved_deliverable_ids = await executor_self._save_intermediate_deliverables(
                        execution_id, session_id,
                        accumulated_state.get("deliverables", []),
                        saved_deliverable_ids,
                    )
                except Exception as deliv_err:
                    logger.warning("⚠️ Intermediate deliverable save failed: %s", deliv_err)
                    try:
                        await executor_self.db_session.rollback()
                        await executor_self._restore_rls_context()
                    except Exception:
                        pass

            final_state = accumulated_state
            logger.debug("🔍 Final accumulated state has %d messages, %d node_outputs",
                       len(final_state.get("messages", [])),
                       len(final_state.get("node_outputs", {})))
            
            # Log all messages
            for idx, msg in enumerate(final_state.get("messages", [])):
                logger.debug(f"   📨 Final message {idx}: {msg.__class__.__name__ if hasattr(msg, '__class__') else type(msg)} - {getattr(msg, 'content', 'NO CONTENT')[:50]}")
            
            # Determine execution status
            if final_state.get("error"):
                status = "failed"
                error = final_state.get("error")
                output_data = None
            elif final_state.get("pending_deliverable"):
                # HITL node set pending_deliverable - pause for human review
                status = "pending_review"
                error = None
                output_data = None
                logger.info("Workflow paused at HITL node - pending deliverable found")
            elif final_state.get("interrupted"):
                status = "paused"
                error = None
                output_data = None
            else:
                status = "completed"
                error = None
                output_data = final_state.get("output_data", {})
                
                # BUGFIX: If output_data is empty but we have deliverables, collect them as output
                # This handles workflows that end at a HITL node without explicit END node
                if not output_data and final_state.get("deliverables"):
                    logger.info("No output_data found but deliverables exist - collecting as output")
                    deliverables = final_state.get("deliverables", [])
                    output_data = {
                        "deliverables": deliverables,
                        "final_deliverable": deliverables[-1] if deliverables else None,
                        "all_node_outputs": final_state.get("node_outputs", {})
                    }
                    logger.info("Collected %d deliverables as output", len(deliverables))
            
            # Update execution record
            await executor_self._update_execution_record(
                execution_id=execution_id,
                status=status,
                state=final_state,
                error=error
            )
            
            logger.info(
                "Workflow execution %d completed with status: %s",
                execution_id,
                status
            )
            
            # Import here to avoid circular dependency
            from .executor import WorkflowExecutionResult
            
            return WorkflowExecutionResult(
                execution_id=execution_id,
                workflow_id=workflow_id,
                status=status,
                output_data=output_data,
                error=error,
                state=final_state
            )
            
        except Exception as e:
            logger.error("Error executing workflow: %s", e, exc_info=True)

            # Surface workflow-level errors in chat history
            if isinstance(state, dict):
                state.setdefault("messages", [])
                state["messages"].append(AIMessage(
                    content=f"Error: {str(e)}",
                    additional_kwargs={
                        "message_id": str(uuid.uuid4()),
                        "agent_id": "workflow",
                        "agent_label": "workflow_executor",
                        "agent_type": "system",
                        "is_error": True
                    }
                ))
            
            # Update execution with error
            await executor_self._update_execution_record(
                execution_id=execution_id,
                status="failed",
                state=state,
                error=str(e)
            )
            
            raise
        finally:
            reset_llm_observability_context(workflow_obs_tokens)
            try:
                from app.utils.langfuse_config import flush_langfuse

                flush_langfuse()
            except Exception:
                pass
        
    except Exception as e:
        logger.error("Failed to execute workflow %s: %s", workflow_id, e)
        raise

