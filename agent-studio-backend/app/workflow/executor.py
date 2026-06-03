"""
Workflow executor.

Executes workflows using LangGraph with state management and persistence.
Delegates to specialized modules for execution and resume operations.
"""

from typing import Dict, Any, Optional, AsyncIterator, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import json
import logging

from repositories.workflow_repository import get_effective_workflow_data
from .parser import WorkflowParser
from .builder import WorkflowGraphBuilder
from .state import (
    create_initial_state,
    WorkflowState,
    serialize_state_for_storage,
    deserialize_state_from_storage
)
from .validation import WorkflowValidator, format_validation_report
from db.models import WorkflowEntity, ExecutionEntity, ExecutionData
from domain.entities import Execution as ExecutionDomainEntity, Workflow

# Import the delegated modules
from .executor_execute import execute_workflow as _execute_workflow
from .executor_resume import (
    resume_workflow_after_hitl as _resume_workflow_after_hitl,
    resume_workflow_from_state as _resume_workflow_from_state
)

logger = logging.getLogger(__name__)


class WorkflowExecutionResult:
    """Result of a workflow execution."""
    
    def __init__(
        self,
        execution_id: int,
        workflow_id: str,
        status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        state: Optional[WorkflowState] = None
    ):
        self.execution_id = execution_id
        self.workflow_id = workflow_id
        self.status = status
        self.output_data = output_data
        self.error = error
        self.state = state


class WorkflowExecutor:
    """
    Executes workflows using LangGraph.
    
    Manages the full lifecycle of workflow execution including:
    - Loading workflow definitions
    - Building the execution graph
    - Running the workflow
    - Persisting execution state and results
    """
    
    def __init__(self, db_session: AsyncSession, user_id: Optional[str] = None):
        """
        Initialize the executor.
        
        Args:
            db_session: Database session for persistence
            user_id: ID of the user triggering executions
        """
        self.db_session = db_session
        self.user_id = user_id
    
    async def _restore_rls_context(self) -> None:
        """Re-set RLS context after a commit.
        
        db.commit() may release the underlying connection back to the pool.
        The next query may get a NEW connection that does NOT have
        app.current_user_id set, causing RLS to filter out all rows.
        """
        from db.pgsql import set_user_context
        from core.request_context import get_current_user_id, get_current_user_groups

        user_id = self.user_id or get_current_user_id()
        if not user_id:
            return

        group_ids = get_current_user_groups()
        await set_user_context(
            self.db_session,
            str(user_id),
            group_ids=group_ids,
        )
    
    async def execute_workflow(
        self,
        workflow_id: str,
        input_data: Dict[str, Any],
        initial_message: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        existing_messages: Optional[list] = None,
        session_id: Optional[str] = None,
        existing_execution_id: Optional[int] = None,
    ) -> WorkflowExecutionResult:
        """
        Execute a workflow.
        
        Delegates to executor_execute.execute_workflow for the actual execution logic.
        
        Args:
            workflow_id: ID of the workflow to execute
            input_data: Input data for the workflow
            initial_message: Optional initial message for chat workflows
            variables: Optional initial variables
            existing_messages: Optional existing conversation messages (for continuing conversations)
            session_id: Optional session ID to link execution to immediately
            
        Returns:
            WorkflowExecutionResult with execution details
        """
        return await _execute_workflow(
            self,
            workflow_id,
            input_data,
            initial_message,
            variables,
            existing_messages,
            session_id,
            existing_execution_id,
        )
    
    async def resume_workflow_after_hitl(
        self,
        execution_id: int,
        approved_deliverable: Dict[str, Any],
        deliverable_id: str
    ) -> WorkflowExecutionResult:
        """
        Resume a paused workflow after HITL approval.
        
        Delegates to executor_resume.resume_workflow_after_hitl for the actual logic.
        
        Args:
            execution_id: Execution ID to resume
            approved_deliverable: The approved (possibly edited) deliverable
            deliverable_id: ID of the deliverable that was approved
            
        Returns:
            WorkflowExecutionResult with continuation results
        """
        return await _resume_workflow_after_hitl(
            self,
            execution_id,
            approved_deliverable,
            deliverable_id
        )
    
    async def resume_workflow_from_state(
        self,
        execution_id: int,
        state: Dict[str, Any],
        variables: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecutionResult:
        """
        Resume a workflow from a given state (e.g., after user sends a new message).
        
        Delegates to executor_resume.resume_workflow_from_state for the actual logic.
        
        Args:
            execution_id: Execution ID to resume
            state: Current workflow state (with new message already added)
            variables: Optional variables
            
        Returns:
            WorkflowExecutionResult with continuation results
        """
        return await _resume_workflow_from_state(
            self,
            execution_id,
            state,
            variables
        )
    
    async def stream_workflow_execution(
        self,
        workflow_id: str,
        input_data: Dict[str, Any],
        initial_message: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute a workflow with streaming events.
        
        Args:
            workflow_id: ID of the workflow to execute
            input_data: Input data for the workflow
            initial_message: Optional initial message
            variables: Optional initial variables
            
        Yields:
            Execution events
        """
        # Load workflow
        workflow = await self._load_workflow(workflow_id)
        
        if not workflow:
            yield {
                "event_type": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "message": f"Workflow {workflow_id} not found"
            }
            return
        
        # Parse workflow
        workflow_json = await self._build_workflow_json(workflow)
        parsed_workflow = WorkflowParser.parse(workflow_json)
        
        # Create execution record
        execution_id = await self._create_execution_record(
            workflow_id=workflow_id,
            workflow_data=workflow_json,
            user_id=self.user_id
        )
        
        yield {
            "event_type": "execution_started",
            "timestamp": datetime.utcnow().isoformat(),
            "execution_id": execution_id,
            "workflow_id": workflow_id
        }
        
        from app.llm.observability_context import lookup_user_email

        user_id_str = str(self.user_id) if self.user_id else None
        user_email = await lookup_user_email(self.db_session, user_id_str)

        # Create initial state
        state = create_initial_state(
            workflow_id=workflow_id,
            workflow_name=workflow.name,
            input_data=input_data,
            execution_id=execution_id,
            initial_message=initial_message,
            user_id=user_id_str,
            user_email=user_email,
        )
        
        if variables:
            state["variables"] = variables
        
        # Build graph
        builder = WorkflowGraphBuilder(parsed_workflow)
        graph = builder.build()
        compiled_graph = graph.compile()
        
        # Execute with streaming
        config = {"configurable": {"thread_id": str(execution_id)}}
        
        try:
            async for event in compiled_graph.astream(state, config):
                # Emit event
                for node_id, node_state in event.items():
                    yield {
                        "event_type": "node_completed",
                        "timestamp": datetime.utcnow().isoformat(),
                        "node_id": node_id,
                        "data": {
                            "node_outputs": node_state.get("node_outputs", {}).get(node_id)
                        }
                    }
            
            # Get final state
            final_state = await compiled_graph.aget_state(config)
            
            # Update execution
            if final_state and final_state.values:
                state_data = final_state.values
                status = "completed" if not state_data.get("error") else "failed"
                
                await self._update_execution_record(
                    execution_id=execution_id,
                    status=status,
                    state=state_data,
                    error=state_data.get("error")
                )
                
                yield {
                    "event_type": "execution_completed",
                    "timestamp": datetime.utcnow().isoformat(),
                    "execution_id": execution_id,
                    "status": status,
                    "output_data": state_data.get("output_data")
                }
            
        except Exception as e:
            logger.error("Error in streaming execution: %s", e)
            
            await self._update_execution_record(
                execution_id=execution_id,
                status="failed",
                error=str(e)
            )
            
            yield {
                "event_type": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "message": str(e)
            }
    
    async def resume_execution(
        self,
        execution_id: int,
        user_input: Dict[str, Any]
    ) -> WorkflowExecutionResult:
        """
        Resume a paused workflow execution.
        
        Args:
            execution_id: ID of the paused execution
            user_input: User input to resume with
            
        Returns:
            WorkflowExecutionResult
        """
        # Load execution record
        query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        result = await self.db_session.execute(query)
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
        
        if not execution_entity.is_waiting():
            raise ValueError(f"Execution {execution_id} is not in waiting status (current: {execution.status})")
        
        # Load execution data
        data_query = select(ExecutionData).where(ExecutionData.executionId == execution_id)
        data_result = await self.db_session.execute(data_query)
        execution_data = data_result.scalar_one_or_none()
        
        if not execution_data:
            raise ValueError(f"Execution data not found for {execution_id}")
        
        # Deserialize state
        state = deserialize_state_from_storage(execution_data.data)
        
        # Add user input response
        state["user_input_response"] = user_input
        state["interrupted"] = False
        
        # Rebuild and continue execution
        # (Implementation would continue from checkpoint)
        # For now, raise not implemented
        raise NotImplementedError("Resume execution not yet implemented")
    
    async def cancel_execution(self, execution_id: int) -> bool:
        """
        Cancel a running execution.
        
        Args:
            execution_id: ID of the execution to cancel
            
        Returns:
            True if cancelled successfully
        """
        query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        result = await self.db_session.execute(query)
        execution = result.scalar_one_or_none()
        
        if not execution:
            return False
        
        # Update status
        execution.status = "cancelled"
        execution.stoppedAt = datetime.utcnow()
        
        await self.db_session.commit()
        await self._restore_rls_context()
        
        logger.info("Cancelled execution %d", execution_id)
        return True
    
    async def _load_workflow(self, workflow_id: str) -> Optional[WorkflowEntity]:
        """Load workflow from database."""
        query = select(WorkflowEntity).where(WorkflowEntity.id == workflow_id)
        result = await self.db_session.execute(query)
        return result.scalar_one_or_none()

    async def _build_workflow_json(
        self, workflow: Union[WorkflowEntity, Workflow]
    ) -> Dict[str, Any]:
        """Build workflow JSON using the effective (possibly snapshot) data.

        Accepts a DB ``WorkflowEntity`` (snapshot rules applied here) or a
        domain ``Workflow`` whose nodes/connections were already resolved
        (e.g. via ``WorkflowRepository.get_effective_by_id``).
        """
        if isinstance(workflow, Workflow):
            nodes_raw = workflow.nodes
            connections_raw = workflow.connections
        else:
            is_owner = self.user_id and str(self.user_id) == str(workflow.createdById)
            eff = await get_effective_workflow_data(
                workflow, self.db_session, is_owner=is_owner,
            )
            nodes_raw = eff.nodes
            connections_raw = eff.connections

        return {
            "workflow": {
                "nodes": json.loads(nodes_raw) if nodes_raw else [],
                "edges": json.loads(connections_raw) if connections_raw else [],
            },
            "version": "1.0",
        }
    
    async def _create_execution_record(
        self,
        workflow_id: str,
        workflow_data: Dict[str, Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> int:
        """Create execution record in database."""
        execution = ExecutionEntity(
            workflowId=workflow_id,
            sessionId=session_id,
            finished=False,
            mode="manual",
            startedAt=datetime.utcnow(),
            status="running",
            createdAt=datetime.utcnow(),
            triggeredById=user_id
        )
        
        self.db_session.add(execution)
        await self.db_session.flush()
        
        # Create execution data record
        execution_data = ExecutionData(
            executionId=execution.id,
            workflowData=json.dumps(workflow_data),
            data="{}"
        )
        
        self.db_session.add(execution_data)
        await self.db_session.commit()
        await self._restore_rls_context()
        
        return execution.id
    
    async def _save_state_to_db(
        self,
        execution_id: int,
        state: WorkflowState
    ) -> None:
        """Save workflow state to ExecutionData table.
        
        This is used to persist the state during execution so that conversation
        history is always available when querying the session.
        """
        data_query = select(ExecutionData).where(ExecutionData.executionId == execution_id)
        data_result = await self.db_session.execute(data_query)
        execution_data = data_result.scalar_one_or_none()
        
        if execution_data:
            try:
                execution_data.data = serialize_state_for_storage(state)
                await self.db_session.commit()
                await self._restore_rls_context()
            except Exception:
                await self.db_session.rollback()
                raise
        else:
            logger.warning(
                "⚠️ _save_state_to_db: ExecutionData not found for execution %d "
                "(possible RLS context loss) — state NOT saved",
                execution_id
            )

    async def _save_intermediate_deliverables(
        self,
        execution_id: int,
        session_id: str,
        deliverables: list,
        saved_deliverable_ids: set,
    ) -> set:
        """Persist new deliverables to the deliverables table during execution.

        This allows the frontend to display deliverables progressively
        via polling, rather than waiting for the full execution to complete.

        Tracks by ``deliverable_id`` so that a single agent (e.g. a code-
        executor that pauses and then completes) can emit multiple distinct
        deliverables across stream events.

        Returns updated set of deliverable_ids that have been saved.
        """
        if not session_id or not deliverables:
            return saved_deliverable_ids

        from repositories.deliverable_repository import DeliverableRepository

        repo = DeliverableRepository(self.db_session)
        any_saved = False
        pretranslate_targets = []

        for deliv_entry in deliverables:
            agent_id = deliv_entry.get("agent_id")
            if not agent_id:
                continue

            deliv_id = deliv_entry.get("deliverable_id") or agent_id
            if deliv_id in saved_deliverable_ids:
                continue

            status = deliv_entry.get("status", "pending")
            deliverable_data = deliv_entry.get("deliverable", {})
            citations = deliv_entry.get("citations", [])
            if citations and isinstance(deliverable_data, dict):
                deliverable_data["_citations"] = citations

            review_notes = (
                deliv_entry.get("review_notes")
                or deliv_entry.get("reviewNotes")
            )
            reviewed_by = self.user_id if status == "approved" else None
            reviewed_at = datetime.utcnow() if status == "approved" else None

            try:
                saved = await repo.upsert_by_session_and_agent(
                    session_id=session_id,
                    execution_id=execution_id,
                    agent_id=agent_id,
                    agent_label=deliv_entry.get("agent_label", "Agent"),
                    agent_type=deliv_entry.get("agent_type", "agent"),
                    deliverable_data=deliverable_data,
                    iteration=1,
                    schema=deliv_entry.get("schema"),
                    created_by_id=self.user_id,
                    status=status,
                    reviewed_by=reviewed_by,
                    reviewed_at=reviewed_at,
                    review_notes=review_notes,
                )
            except Exception:
                await self.db_session.rollback()
                raise

            saved_deliverable_ids.add(deliv_id)
            any_saved = True
            pretranslate_targets.append((saved.id, deliverable_data))
            logger.debug(
                "Saved intermediate deliverable for agent %s (%s) [deliv=%s]",
                agent_id, deliv_entry.get("agent_label"), deliv_id,
            )

        if any_saved:
            try:
                await self.db_session.commit()
                await self._restore_rls_context()
            except Exception:
                await self.db_session.rollback()
                raise

            from app.services.chat_service import _schedule_pretranslation

            for deliverable_id, deliverable_data in pretranslate_targets:
                _schedule_pretranslation(deliverable_id, deliverable_data)

        return saved_deliverable_ids
    
    async def _update_execution_record(
        self,
        execution_id: int,
        status: str,
        state: Optional[WorkflowState] = None,
        error: Optional[str] = None
    ) -> None:
        """Update execution record with final state."""
        await self._restore_rls_context()
        query = select(ExecutionEntity).where(ExecutionEntity.id == execution_id)
        result = await self.db_session.execute(query)
        execution = result.scalar_one_or_none()
        
        if not execution:
            logger.warning(
                "Execution %d not found on first attempt (likely RLS context loss) "
                "— restoring context and retrying",
                execution_id
            )
            await self._restore_rls_context()
            result = await self.db_session.execute(query)
            execution = result.scalar_one_or_none()
        
        if not execution:
            logger.error(
                "Cannot update execution %d to status '%s': not found "
                "even after RLS context restore — giving up",
                execution_id, status
            )
            return
        
        execution.status = status
        execution.stoppedAt = datetime.utcnow()
        execution.finished = status in ["completed", "failed", "cancelled"]
        
        # Update execution data if state provided
        if state:
            data_query = select(ExecutionData).where(ExecutionData.executionId == execution_id)
            data_result = await self.db_session.execute(data_query)
            execution_data = data_result.scalar_one_or_none()
            
            if execution_data:
                execution_data.data = serialize_state_for_storage(state)
        
        await self.db_session.commit()
        await self._restore_rls_context()

        # Prefix-delete ADLS artefacts (checkpoints + midway uploads) the
        # Code Executor node accumulated during this run.  Best-effort:
        # a failure here must never fail the terminal status transition.
        # We let the workflow fully terminate first so the terminal state
        # is already durable before we start tidying storage.
        if status in ("completed", "failed", "cancelled"):
            try:
                await self._cleanup_code_executor_artefacts(execution_id, state)
            except Exception as exc:
                logger.warning(
                    "Code executor artefact cleanup failed for execution %d: %s",
                    execution_id, exc,
                )

    async def _cleanup_code_executor_artefacts(
        self,
        execution_id: int,
        state: Optional[WorkflowState],
    ) -> None:
        """Delete ADLS blobs this workflow's Code Executor nodes produced.

        Two artefact classes live under the shared blob container:

        * Checkpoints — scoped by ``(user_id, execution_id, pause_index)``.
          We can prefix-delete them given only user + execution.
        * Midway uploads — keyed by ``upload_id`` (not by execution), so
          we need to enumerate them by walking the final
          ``pending_user_input.pause_file_map``.  Even on a completed
          workflow the map is still attached to the state because we
          don't scrub pending_user_input once a pause is consumed (we
          only null it out on the next node's transition).

        Both operations are best-effort; unreachable storage or missing
        blobs are downgraded to debug logs.
        """
        from .code_executor_storage import cleanup_run

        user_id = "anon"
        midway_blob_names = []
        if state is not None:
            meta = state.get("metadata") or {}
            user_id = str(meta.get("user_id") or "anon")
            pending = state.get("pending_user_input") or {}
            if isinstance(pending, dict):
                pause_file_map = pending.get("pause_file_map") or {}
                if isinstance(pause_file_map, dict):
                    for entry in pause_file_map.values():
                        if isinstance(entry, dict) and entry.get("blob_name"):
                            midway_blob_names.append(entry["blob_name"])

        await cleanup_run(
            user_id=user_id,
            execution_id=str(execution_id),
            midway_blob_names=midway_blob_names,
        )


