"""
Workflow resume logic.

Contains methods for resuming paused workflows:
- After HITL (Human-in-the-Loop) approval
- From a given state (e.g., continuing conversation)
"""

from typing import Dict, Any, Optional
from sqlalchemy import select, update
from datetime import datetime
import logging
import uuid

from langchain_core.messages import AIMessage

from .parser import WorkflowParser
from .builder import WorkflowGraphBuilder
from .state import (
    WorkflowState,
    add_messages_reducer,
    merge_node_outputs,
    serialize_state_for_storage,
    deserialize_state_from_storage
)
from domain.entities import Execution as ExecutionDomainEntity
from db.models import ExecutionEntity, ExecutionData

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


async def resume_workflow_after_hitl(
    executor_self,  # The WorkflowExecutor instance
    execution_id: int,
    approved_deliverable: Dict[str, Any],
    deliverable_id: str
):
    """
    Resume a paused workflow after HITL approval.
    
    Loads the paused state, updates it with the approved deliverable,
    and continues execution from the next node.
    
    Args:
        executor_self: The WorkflowExecutor instance
        execution_id: Execution ID to resume
        approved_deliverable: The approved (possibly edited) deliverable
        deliverable_id: ID of the deliverable that was approved
        
    Returns:
        WorkflowExecutionResult with continuation results
    """
    try:
        logger.info("Resuming workflow execution %d after HITL approval", execution_id)
        
        # Ensure RLS context is set for this session
        from db.pgsql import set_user_context
        if executor_self.user_id:
            await set_user_context(executor_self.db_session, executor_self.user_id)
            logger.debug("🔒 RLS: Ensured user context set to %s for execution %d", executor_self.user_id, execution_id)
        
        # Load execution record
        query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        result = await executor_self.db_session.execute(query)
        execution = result.scalar_one_or_none()
        
        if not execution:
            raise ValueError(f"Execution {execution_id} not found")
        
        # Convert DB model to domain entity for business logic
        execution_entity = ExecutionDomainEntity(
            id=execution.id,
            workflow_id=execution.workflowId,
            session_id=execution.sessionId,
            finished=execution.finished,
            mode=execution.mode,
            retry_of=execution.retryOf,
            retry_success_id=execution.retrySuccessId,
            started_at=execution.startedAt,
            stopped_at=execution.stoppedAt,
            wait_till=execution.waitTill,
            status=execution.status,
            deleted_at=execution.deletedAt,
            created_at=execution.createdAt,
            updated_at=execution.updatedAt
        )
        
        if not execution_entity.is_pending_review():
            raise ValueError(f"Execution {execution_id} is not in pending_review status (current: {execution.status})")
        
        # Load execution state
        data_query = select(ExecutionData).where(ExecutionData.executionId == execution_id)
        data_result = await executor_self.db_session.execute(data_query)
        execution_data = data_result.scalar_one_or_none()
        
        if not execution_data:
            raise ValueError(f"Execution data not found for execution {execution_id}")
        
        # Deserialize state
        state = deserialize_state_from_storage(execution_data.data)
        
        # Update state with approved deliverable
        state["metadata"]["status"] = "running"  # Resume execution
        state["interrupted"] = False  # Clear interrupted flag so nodes will execute
        
        # Add approved deliverable to state deliverables list
        if "deliverables" not in state:
            state["deliverables"] = []
        
        # Mark deliverable as approved and add to state BEFORE clearing pending_deliverable
        approved = {
            **approved_deliverable,
            "deliverable_id": deliverable_id,
            "status": "approved",
            "approved_at": datetime.utcnow().isoformat()
        }
        state["deliverables"].append(approved)
        logger.info("✅ Added approved deliverable to state.deliverables: %s", deliverable_id)
        
        # Now clear the pending deliverable
        state["pending_deliverable"] = None
        
        # Store workflowId/sessionId immediately to avoid RLS refresh issues later
        workflow_id = execution.workflowId
        hitl_session_id = execution.sessionId
        
        # Load workflow and rebuild graph
        workflow = await executor_self._load_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        workflow_json = await executor_self._build_workflow_json(workflow)
        parsed_workflow = WorkflowParser.parse(workflow_json)

        # Ensure direct-next HITL map is available on state (used to auto-approve deliverables)
        if "metadata" not in state:
            state["metadata"] = {}
        state["metadata"]["direct_next_is_hitl"] = _build_direct_next_is_hitl(parsed_workflow)
        state["metadata"]["direct_next_agent_startup"] = _build_direct_next_agent_startup(parsed_workflow)
        
        # Build graph
        builder = WorkflowGraphBuilder(parsed_workflow)
        graph = builder.build()
        compiled_graph = graph.compile()
        
        # Continue execution from current point
        logger.info("Continuing workflow execution from node: %s", state.get("current_node"))
        
        config = {"configurable": {"thread_id": str(execution_id)}}

        from app.llm.observability_context import (
            apply_workflow_observability_context,
            reset_llm_observability_context,
        )

        workflow_obs_tokens = apply_workflow_observability_context(state)
        
        try:
            # Accumulate state incrementally from each node event.
            accumulated_state = {**state}
            accumulated_state["messages"] = state.get("messages", []).copy() if isinstance(state.get("messages"), list) else []
            accumulated_state["node_outputs"] = state.get("node_outputs", {}).copy() if isinstance(state.get("node_outputs"), dict) else {}
            accumulated_state["deliverables"] = state.get("deliverables", []).copy() if isinstance(state.get("deliverables"), list) else []
            
            logger.debug("🔍 HITL RESUME: Starting accumulation with %d messages", len(accumulated_state["messages"]))
            
            saved_deliverable_ids: set = set()

            async for event in compiled_graph.astream(state, config):
                logger.debug("Workflow resume event: %s", list(event.keys()))

                for node_name, node_state in event.items():
                    if isinstance(node_state, dict):
                        for key, value in node_state.items():
                            if key == "messages" and isinstance(value, list):
                                accumulated_state["messages"] = add_messages_reducer(
                                    accumulated_state["messages"], 
                                    value
                                )
                                logger.debug(f"      ✅ HITL RESUME: Added {len(value)} message(s), total: {len(accumulated_state['messages'])}")
                            elif key == "node_outputs" and isinstance(value, dict):
                                accumulated_state["node_outputs"] = merge_node_outputs(
                                    accumulated_state["node_outputs"], 
                                    value
                                )
                            elif key == "deliverables" and isinstance(value, list):
                                accumulated_state["deliverables"] = value
                            else:
                                accumulated_state[key] = value

                # Flush intermediate state to DB after every node.
                try:
                    await executor_self._save_state_to_db(execution_id, accumulated_state)
                except Exception as save_err:
                    logger.warning("⚠️ Intermediate state save failed: %s", save_err)
                    try:
                        await executor_self._restore_rls_context()
                    except Exception:
                        pass

                # Persist new deliverables progressively.
                try:
                    saved_deliverable_ids = await executor_self._save_intermediate_deliverables(
                        execution_id, hitl_session_id,
                        accumulated_state.get("deliverables", []),
                        saved_deliverable_ids,
                    )
                except Exception as deliv_err:
                    logger.warning("⚠️ Intermediate deliverable save failed: %s", deliv_err)
                    try:
                        await executor_self._restore_rls_context()
                    except Exception:
                        pass

            final_state = accumulated_state
            logger.debug("🔍 RESUME: Final accumulated state has %d messages", len(final_state.get("messages", [])))
            
            # Determine execution status
            if final_state.get("error"):
                status = "failed"
                error = final_state.get("error")
                output_data = None
            elif final_state.get("pending_deliverable"):
                # Hit another HITL node
                status = "pending_review"
                error = None
                output_data = None
                logger.info("Workflow paused at another HITL node - pending deliverable found")
            else:
                status = "completed"
                error = None
                output_data = final_state.get("output_data", {})
                
                # BUGFIX: If output_data is empty but we have deliverables, collect them as output
                if not output_data and final_state.get("deliverables"):
                    logger.debug("🔧 FIX: No output_data found but deliverables exist - collecting as output")
                    deliverables = final_state.get("deliverables", [])
                    output_data = {
                        "deliverables": deliverables,
                        "final_deliverable": deliverables[-1] if deliverables else None,
                        "all_node_outputs": final_state.get("node_outputs", {})
                    }
                    logger.debug("🔧 FIX: Collected %d deliverables as output", len(deliverables))
            
            # Update execution record
            await executor_self._update_execution_record(
                execution_id=execution_id,
                status=status,
                state=final_state,
                error=error
            )
            
            logger.info(
                "Workflow execution %d resumed and completed with status: %s",
                execution_id,
                status
            )
            
            # Import here to avoid circular dependency
            from .executor import WorkflowExecutionResult
            
            return WorkflowExecutionResult(
                execution_id=execution_id,
                workflow_id=execution.workflowId,
                status=status,
                output_data=output_data,
                error=error,
                state=final_state
            )
            
        except Exception as e:
            logger.error("Error resuming workflow: %s", e, exc_info=True)

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
        logger.error("Failed to resume workflow execution %d: %s", execution_id, e)
        raise


async def resume_workflow_from_state(
    executor_self,  # The WorkflowExecutor instance
    execution_id: int,
    state: Dict[str, Any],
    variables: Optional[Dict[str, Any]] = None
):
    """
    Resume a workflow from a given state (e.g., after user sends a new message).
    
    This is used when a workflow is paused (e.g., at HITL) and the user sends
    a new message to continue. The state should already have the new message added.
    
    Args:
        executor_self: The WorkflowExecutor instance
        execution_id: Execution ID to resume
        state: Current workflow state (with new message already added)
        variables: Optional variables
        
    Returns:
        WorkflowExecutionResult with continuation results
    """
    try:
        logger.info("Resuming workflow execution %d from provided state", execution_id)
        
        # Ensure RLS context is set for this session
        from db.pgsql import set_user_context
        if executor_self.user_id:
            await set_user_context(executor_self.db_session, executor_self.user_id)
            logger.debug("🔒 RLS: Ensured user context set to %s for execution %d", executor_self.user_id, execution_id)
        
        # Load execution record to get workflow_id
        query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        result = await executor_self.db_session.execute(query)
        execution = result.scalar_one_or_none()
        
        if not execution:
            # Check if execution exists at all (bypass RLS check)
            from sqlalchemy import text
            check_query = text(f"SELECT COUNT(*) FROM execution_entity WHERE id = {execution_id}")
            check_result = await executor_self.db_session.execute(check_query)
            count = check_result.scalar()
            
            if count > 0:
                logger.error("Execution %d exists but is filtered by RLS - authentication/permission issue", execution_id)
                raise ValueError(f"Execution {execution_id} not accessible (RLS filtered - check user permissions)")
            else:
                logger.error("Execution %d does not exist in database", execution_id)
                raise ValueError(f"Execution {execution_id} not found")
        
        # Store workflowId/sessionId immediately to avoid RLS refresh issues later
        workflow_id = execution.workflowId
        resume_session_id = execution.sessionId
        
        # Load workflow and rebuild graph
        workflow = await executor_self._load_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        workflow_json = await executor_self._build_workflow_json(workflow)
        parsed_workflow = WorkflowParser.parse(workflow_json)

        # Ensure direct-next HITL map is available on state (used to auto-approve deliverables)
        if "metadata" not in state:
            state["metadata"] = {}
        state["metadata"]["direct_next_is_hitl"] = _build_direct_next_is_hitl(parsed_workflow)
        state["metadata"]["direct_next_agent_startup"] = _build_direct_next_agent_startup(parsed_workflow)
        
        # Build graph
        builder = WorkflowGraphBuilder(parsed_workflow)
        graph = builder.build()
        compiled_graph = graph.compile()
        
        # Update status to running BEFORE execution starts (direct update avoids RLS rowcount issues)
        await executor_self.db_session.execute(
            update(ExecutionEntity)
            .where(ExecutionEntity.id == execution_id)
            .values(status="running")
        )
        await executor_self.db_session.commit()
        await executor_self._restore_rls_context()
        logger.debug("Set execution %d status to 'running' before resuming", execution_id)
        
        # 🔧 FIX: Save state with user message to DB before resuming
        # This ensures the conversation history is immediately visible when querying the session
        await executor_self._save_state_to_db(execution_id, state)
        logger.debug("💾 Saved resumed state to DB (messages: %d)", len(state.get("messages", [])))
        
        # Continue execution from current state
        logger.info("Continuing workflow from current state (interrupted=%s)", state.get("interrupted"))
        
        config = {"configurable": {"thread_id": str(execution_id)}}

        from app.llm.observability_context import (
            apply_workflow_observability_context,
            reset_llm_observability_context,
        )

        if state.get("metadata") and execution_id:
            meta = state["metadata"]
            if not meta.get("execution_id"):
                meta["execution_id"] = execution_id
            if not meta.get("workflow_id"):
                meta["workflow_id"] = workflow_id
            if not meta.get("session_id") and resume_session_id:
                meta["session_id"] = resume_session_id

        workflow_obs_tokens = apply_workflow_observability_context(state)
        
        try:
            # Accumulate state incrementally from each node event.
            # After every node completes we save to DB so the frontend
            # can poll and display progressive updates.
            # Start from a full copy of the original state so that
            # intermediate saves don't lose fields like metadata/variables.
            accumulated_state = {**state}
            accumulated_state["messages"] = state.get("messages", []).copy() if isinstance(state.get("messages"), list) else []
            accumulated_state["node_outputs"] = state.get("node_outputs", {}).copy() if isinstance(state.get("node_outputs"), dict) else {}
            accumulated_state["deliverables"] = state.get("deliverables", []).copy() if isinstance(state.get("deliverables"), list) else []

            logger.debug("🔍 RESUME: Starting accumulation with %d messages", len(accumulated_state["messages"]))

            saved_deliverable_ids: set = set()

            async for event in compiled_graph.astream(state, config):
                logger.debug("Workflow resume event: %s", list(event.keys()))

                for node_name, node_state in event.items():
                    if isinstance(node_state, dict):
                        for key, value in node_state.items():
                            if key == "messages" and isinstance(value, list):
                                accumulated_state["messages"] = add_messages_reducer(
                                    accumulated_state["messages"],
                                    value
                                )
                                logger.debug(f"      ✅ RESUME: Added {len(value)} message(s), total: {len(accumulated_state['messages'])}")
                            elif key == "node_outputs" and isinstance(value, dict):
                                accumulated_state["node_outputs"] = merge_node_outputs(
                                    accumulated_state["node_outputs"],
                                    value
                                )
                            elif key == "deliverables" and isinstance(value, list):
                                accumulated_state["deliverables"] = value
                            else:
                                accumulated_state[key] = value

                # Flush intermediate state to DB after every node so the
                # frontend can pick up new messages via polling.
                try:
                    await executor_self._save_state_to_db(execution_id, accumulated_state)
                except Exception as save_err:
                    logger.warning("⚠️ Intermediate state save failed: %s", save_err)
                    try:
                        await executor_self._restore_rls_context()
                    except Exception:
                        pass

                # Also persist new deliverables to the deliverables table so
                # the frontend can display them progressively.
                try:
                    saved_deliverable_ids = await executor_self._save_intermediate_deliverables(
                        execution_id, resume_session_id,
                        accumulated_state.get("deliverables", []),
                        saved_deliverable_ids,
                    )
                except Exception as deliv_err:
                    logger.warning("⚠️ Intermediate deliverable save failed: %s", deliv_err)
                    try:
                        await executor_self._restore_rls_context()
                    except Exception:
                        pass

            final_state = accumulated_state
            logger.debug("🔍 RESUME: Final accumulated state has %d messages", len(final_state.get("messages", [])))
            
            # Determine execution status
            if final_state.get("error"):
                status = "failed"
                error = final_state.get("error")
                output_data = None
            elif final_state.get("pending_deliverable"):
                status = "pending_review"
                error = None
                output_data = None
                logger.info("Workflow paused at HITL node again - pending deliverable found")
            elif final_state.get("interrupted"):
                status = "paused"
                error = None
                output_data = None
            else:
                status = "completed"
                error = None
                output_data = final_state.get("output_data", {})
                
                # BUGFIX: If output_data is empty but we have deliverables, collect them as output
                if not output_data and final_state.get("deliverables"):
                    logger.debug("🔧 FIX: No output_data found but deliverables exist - collecting as output")
                    deliverables = final_state.get("deliverables", [])
                    output_data = {
                        "deliverables": deliverables,
                        "final_deliverable": deliverables[-1] if deliverables else None,
                        "all_node_outputs": final_state.get("node_outputs", {})
                    }
                    logger.debug("🔧 FIX: Collected %d deliverables as output", len(deliverables))
            
            # Update execution record (direct updates to avoid RLS rowcount issues)
            now = datetime.utcnow()
            await executor_self.db_session.execute(
                update(ExecutionEntity)
                .where(ExecutionEntity.id == execution_id)
                .values(
                    status=status,
                    stoppedAt=now,
                    finished=status in ["completed", "failed", "cancelled"]
                )
            )
            
            await executor_self.db_session.execute(
                update(ExecutionData)
                .where(ExecutionData.executionId == execution_id)
                .values(
                    data=serialize_state_for_storage(final_state)
                )
            )
            
            await executor_self.db_session.commit()
            await executor_self._restore_rls_context()
            
            logger.info(
                "Workflow execution %d resumed successfully - status: %s",
                execution_id,
                status
            )
            
            # Import here to avoid circular dependency
            from .executor import WorkflowExecutionResult
            
            return WorkflowExecutionResult(
                execution_id=execution_id,
                workflow_id=execution.workflowId,
                status=status,
                output_data=output_data,
                error=error,
                state=final_state
            )
            
        except Exception as e:
            logger.error("Error resuming workflow: %s", e, exc_info=True)

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
            
            # Update execution with error (direct updates to avoid RLS rowcount issues)
            now = datetime.utcnow()
            await executor_self.db_session.execute(
                update(ExecutionEntity)
                .where(ExecutionEntity.id == execution_id)
                .values(
                    status="failed",
                    stoppedAt=now,
                    finished=True
                )
            )

            # Persist the error message in state for chat history
            await executor_self.db_session.execute(
                update(ExecutionData)
                .where(ExecutionData.executionId == execution_id)
                .values(
                    data=serialize_state_for_storage(state)
                )
            )

            await executor_self.db_session.commit()
            await executor_self._restore_rls_context()
            
            raise
        finally:
            reset_llm_observability_context(workflow_obs_tokens)
            try:
                from app.utils.langfuse_config import flush_langfuse

                flush_langfuse()
            except Exception:
                pass
        
    except Exception as e:
        logger.error("Failed to resume workflow execution %d: %s", execution_id, e)
        raise

