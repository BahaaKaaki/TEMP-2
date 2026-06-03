"""
Deliverable service for HITL business logic.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import logging
from datetime import datetime

from .base import BaseService
from repositories import (
    DeliverableRepository,
    ExecutionRepository,
    WorkflowRepository,
    SessionRepository
)
from domain.entities import Deliverable
from workflow.executor import WorkflowExecutor
from core.exceptions import (
    DeliverableNotFoundException,
    DeliverableNotPendingException,
)

try:
    from langchain_core.messages import AIMessage, HumanMessage
except ImportError:
    from langchain.schema import AIMessage, HumanMessage

logger = logging.getLogger(__name__)


class DeliverableService(BaseService):
    """Service for deliverable (HITL) business logic."""
    
    def __init__(
        self,
        db: AsyncSession,
        deliverable_repo: DeliverableRepository,
        execution_repo: ExecutionRepository,
        workflow_repo: WorkflowRepository,
        session_repo: SessionRepository,
        workflow_executor: WorkflowExecutor
    ):
        super().__init__(db)
        self.deliverable_repo = deliverable_repo
        self.execution_repo = execution_repo
        self.workflow_repo = workflow_repo
        self.session_repo = session_repo
        self.workflow_executor = workflow_executor
    
    async def list_session_deliverables(
        self,
        session_id: str
    ) -> List[Deliverable]:
        """List all deliverables for a session.

        Self-heals OpenUI rendering: any deliverable that needs OpenUI Lang but
        whose `openui_lang` is missing or not a renderable array is re-scheduled
        for translation (the in-flight guard prevents duplicate LLM calls).
        """
        deliverables = await self.deliverable_repo.get_by_session_id(session_id)
        try:
            from .chat_service import schedule_pretranslation_if_stale

            for deliverable in deliverables:
                schedule_pretranslation_if_stale(deliverable)
        except Exception as exc:
            logger.warning("OpenUI self-heal scheduling failed: %s", exc)
        return deliverables
    
    async def get_deliverable(
        self,
        deliverable_id: str
    ) -> Deliverable:
        """Get deliverable by ID."""
        deliverable = await self.deliverable_repo.get_by_id(deliverable_id)
        if not deliverable:
            raise DeliverableNotFoundException(deliverable_id)
        return deliverable
    
    async def approve_deliverable(
        self,
        deliverable_id: str,
        reviewed_by: Optional[str] = None,
        review_notes: Optional[str] = None,
        edited_deliverable: Optional[dict] = None
    ) -> dict:
        """Approve deliverable and resume workflow."""
        deliverable = await self.get_deliverable(deliverable_id)
        
        if not deliverable.can_be_reviewed():
            raise DeliverableNotPendingException(deliverable_id, deliverable.status)
        
        final_data = edited_deliverable if edited_deliverable else deliverable.get_deliverable_dict()
        
        updated_deliverable = await self.deliverable_repo.approve_deliverable(
            deliverable_id,
            reviewed_by,
            review_notes,
            edited_deliverable
        )
        
        await self._update_state_deliverable_status(
            updated_deliverable,
            "approved",
            final_data
        )
        
        await self.commit()
        
        logger.debug("Deliverable %s approved", deliverable_id)
        
        startup_message_full = await self._inject_startup_message(updated_deliverable)
        
        # Build next_agent dict with available information
        next_agent_info = None
        if startup_message_full:
            metadata = startup_message_full.get("metadata", {})
            next_agent_info = {
                "agent_label": metadata.get("agent_label"),
                "agent_id": metadata.get("agent_id"),
                "agent_type": metadata.get("agent_type")
            }

        # Auto-resume when the next agent does not require user input.
        # If wait_for_input is True the workflow stays paused for the user
        # to send a message.  Otherwise, continue immediately (same pattern
        # as reject_deliverable).
        should_wait = (
            startup_message_full
            and startup_message_full.get("metadata", {}).get("wait_for_input", False)
        )

        resumed_result = None
        if not should_wait:
            try:
                state = await self.execution_repo.get_execution_data(
                    updated_deliverable.execution_id
                )
                if state:
                    state["interrupted"] = False
                    state["pending_deliverable"] = None
                    if "metadata" in state:
                        state["metadata"]["status"] = "running"

                    session = await self.session_repo.get_by_id(
                        updated_deliverable.session_id
                    )
                    variables = session.get_variables_dict() if session else None

                    resumed_result = await self.workflow_executor.resume_workflow_from_state(
                        execution_id=updated_deliverable.execution_id,
                        state=state,
                        variables=variables,
                    )

                    pretranslate_targets = await self._save_deliverables(
                        updated_deliverable.session_id,
                        resumed_result,
                        user_id=reviewed_by or self.workflow_executor.user_id,
                    )

                    await self.commit()
                    self._schedule_openui_pretranslation(
                        pretranslate_targets,
                        user_id=reviewed_by or self.workflow_executor.user_id,
                    )
            except Exception as e:
                logger.error(
                    "Failed to auto-resume workflow after approval: %s",
                    e, exc_info=True,
                )
        
        return {
            "deliverable_id": deliverable_id,
            "status": "approved",
            "workflow_resumed": startup_message_full is not None or resumed_result is not None,
            "next_agent": next_agent_info,
            "startup_message": startup_message_full.get("content") if startup_message_full else None,
            "startup_message_full": startup_message_full,
            "message": "Deliverable approved successfully" + 
                      (" - next agent is ready" if startup_message_full else "")
        }
    
    async def respond_to_widget(
        self,
        deliverable_id: str,
        user_response: dict,
        reviewed_by: Optional[str] = None,
    ) -> dict:
        """Accept a user's response to an interactive widget and resume workflow.

        Stores the response inside the deliverable, marks it approved, then
        resumes the workflow so downstream nodes can read ``user_response``.
        """
        deliverable = await self.get_deliverable(deliverable_id)

        if not deliverable.can_be_reviewed():
            raise DeliverableNotPendingException(deliverable_id, deliverable.status)

        # Persist widget response and approve in one step
        updated_deliverable = await self.deliverable_repo.approve_deliverable(
            deliverable_id,
            reviewed_by,
            review_notes=None,
            edited_data=None,
        )

        # Store the user_response alongside the deliverable state
        await self._update_state_deliverable_status(
            updated_deliverable,
            "approved",
            deliverable.get_deliverable_dict(),
            user_response=user_response,
        )

        await self.commit()

        logger.info("Widget response stored for deliverable %s", deliverable_id)

        # Resume workflow (with duplicate-resume guard)
        resumed = False
        try:
            state = await self.execution_repo.get_execution_data(
                updated_deliverable.execution_id
            )
            if state:
                exec_status = state.get("metadata", {}).get("status")
                if exec_status == "running":
                    logger.warning(
                        "Execution %s already running — skipping duplicate "
                        "resume for deliverable %s",
                        updated_deliverable.execution_id, deliverable_id,
                    )
                else:
                    state["interrupted"] = False
                    state["pending_deliverable"] = None
                    if "metadata" in state:
                        state["metadata"]["status"] = "running"

                    state["user_input_response"] = user_response

                    session = await self.session_repo.get_by_id(
                        updated_deliverable.session_id
                    )
                    variables = session.get_variables_dict() if session else None

                    await self.workflow_executor.resume_workflow_from_state(
                        execution_id=updated_deliverable.execution_id,
                        state=state,
                        variables=variables,
                    )
                    resumed = True
                    await self.commit()
        except Exception as e:
            logger.error("Failed to resume workflow after widget response: %s", e, exc_info=True)

        # Build a post-resume snapshot so the /respond HTTP caller can
        # update its UI synchronously for chained output.ask() sequences.
        # By this point resume_workflow_from_state has already awaited
        # the sandbox round-trip; if the script issued another
        # output.ask() the next ask deliverable is persisted to the DB
        # (same session row, updated deliverable JSON with a new
        # pause_index).  Returning it in the response removes the need
        # for the frontend to poll or GET /deliverables again and fixes
        # the race where consecutive asks didn't appear until refresh.
        snapshot = await self._build_post_resume_snapshot(
            session_id=updated_deliverable.session_id,
        )

        return {
            "deliverable_id": deliverable_id,
            "status": "approved",
            "workflow_resumed": resumed,
            "next_agent": None,
            "startup_message": None,
            "startup_message_full": None,
            "message": "Widget response accepted" + (" - workflow resumed" if resumed else ""),
            **snapshot,
        }

    async def _build_post_resume_snapshot(
        self,
        session_id: str,
    ) -> dict:
        """Gather the data the UI needs right after a widget response resume.

        Returns a dict with keys:
          - ``updated_deliverables``: all deliverables for the session
            as ``DeliverableResponse`` Pydantic models (identical shape
            to ``GET /sessions/{id}/deliverables``).  Pydantic handles
            datetime → ISO-string serialization automatically.
          - ``execution_status``: authoritative execution status
            (``running`` / ``paused`` / ``completed`` / ...).
          - ``execution_id``: the active execution id, if any.
        """
        # Local import to avoid circular: schemas does not import services.
        from schemas import DeliverableResponse

        updated_deliverables: list = []
        execution_status: Optional[str] = None
        execution_id: Optional[int] = None

        try:
            deliverables = await self.deliverable_repo.get_by_session_id(session_id)
            for d in deliverables:
                dd = d.get_deliverable_dict()
                updated_deliverables.append(
                    DeliverableResponse(
                        id=d.id,
                        sessionId=d.session_id,
                        executionId=d.execution_id,
                        agentId=d.agent_id,
                        agentLabel=d.agent_label,
                        agentType=d.agent_type,
                        deliverable=dd if isinstance(dd, dict) else {},
                        deliverableSchema=getattr(d, "deliverable_schema", None),
                        status=d.status,
                        iteration=d.iteration,
                        reviewedAt=d.reviewed_at,
                        reviewedBy=d.reviewed_by,
                        reviewNotes=d.review_notes,
                        previousDeliverableId=d.previous_deliverable_id,
                        createdAt=d.created_at,
                        updatedAt=d.updated_at,
                        outputType=dd.get("_output_type") if isinstance(dd, dict) else None,
                        interactive=bool(dd.get("_interactive")) if isinstance(dd, dict) else False,
                        userResponse=dd.get("_user_response") if isinstance(dd, dict) else None,
                        openuiLang=getattr(d, "openui_lang", None),
                    )
                )
        except Exception as e:
            logger.warning(
                "Failed to load deliverables snapshot for session %s: %s",
                session_id, e, exc_info=True,
            )

        try:
            latest = await self.execution_repo.get_latest_by_session(session_id)
            if latest:
                execution_status = latest.status
                execution_id = latest.id
        except Exception as e:
            logger.warning(
                "Failed to load execution snapshot for session %s: %s",
                session_id, e, exc_info=True,
            )

        return {
            "updated_deliverables": updated_deliverables,
            "execution_status": execution_status,
            "execution_id": execution_id,
        }

    async def reject_deliverable(
        self,
        deliverable_id: str,
        reviewed_by: Optional[str] = None,
        review_notes: Optional[str] = None
    ) -> dict:
        """Reject deliverable with feedback."""
        deliverable = await self.get_deliverable(deliverable_id)
        
        if not deliverable.can_be_reviewed():
            raise DeliverableNotPendingException(deliverable_id, deliverable.status)
        
        updated_deliverable = await self.deliverable_repo.reject_deliverable(
            deliverable_id,
            reviewed_by,
            review_notes
        )
        
        await self._update_state_deliverable_status(
            updated_deliverable,
            "rejected",
            None
        )
        
        await self._add_rejection_feedback(updated_deliverable)
        
        await self._clear_rejected_node_outputs(updated_deliverable)
        
        await self.commit()

        logger.debug("Deliverable %s rejected", deliverable_id)

        # Build next_agent dict - for rejection, it's the same agent that will retry
        next_agent_info = {
            "agent_label": updated_deliverable.agent_label,
            "agent_id": updated_deliverable.agent_id,
            "agent_type": updated_deliverable.agent_type
        }

        # Resume workflow immediately with rejection feedback (no extra user message required)
        resumed_result = None
        try:
            state = await self.execution_repo.get_execution_data(updated_deliverable.execution_id)
            if state:
                # Ensure resume flags are cleared
                state["interrupted"] = False
                state["pending_deliverable"] = None
                if "metadata" in state:
                    state["metadata"]["status"] = "running"

                session = await self.session_repo.get_by_id(updated_deliverable.session_id)
                variables = session.get_variables_dict() if session else None

                resumed_result = await self.workflow_executor.resume_workflow_from_state(
                    execution_id=updated_deliverable.execution_id,
                    state=state,
                    variables=variables
                )

                pretranslate_targets = await self._save_deliverables(
                    updated_deliverable.session_id,
                    resumed_result,
                    user_id=reviewed_by or self.workflow_executor.user_id
                )

                await self.commit()
                self._schedule_openui_pretranslation(
                    pretranslate_targets,
                    user_id=reviewed_by or self.workflow_executor.user_id,
                )
        except Exception as e:
            # Don't fail the rejection if auto-resume fails; allow manual continuation
            logger.error("Failed to auto-resume workflow after rejection: %s", e, exc_info=True)

        return {
            "deliverable_id": deliverable_id,
            "status": "rejected",
            "workflow_resumed": resumed_result is not None,
            "next_agent": next_agent_info,
            "startup_message": None,
            "startup_message_full": None,
            "message": "Deliverable rejected. The agent will revise based on your feedback." +
                      ("" if resumed_result is not None else " Send another message to continue if needed.")
        }

    async def _save_deliverables(
        self,
        session_id: str,
        result,
        user_id: Optional[str] = None
    ) -> list[tuple[str, dict]]:
        """Persist any new deliverables created during resume."""
        if not result or not result.state:
            return []

        deliverables = result.state.get("deliverables", [])
        pretranslate_targets = []
        for deliv_entry in deliverables:
            agent_id = deliv_entry.get("agent_id")
            
            status = deliv_entry.get("status", "pending")
            reviewed_by = user_id if status == "approved" else None
            reviewed_at = datetime.utcnow() if status == "approved" else None
            review_notes = deliv_entry.get("review_notes") or deliv_entry.get("reviewNotes")

            saved = await self.deliverable_repo.upsert_by_session_and_agent(
                session_id=session_id,
                execution_id=result.execution_id,
                agent_id=deliv_entry.get("agent_id"),
                agent_label=deliv_entry.get("agent_label"),
                agent_type=deliv_entry.get("agent_type"),
                deliverable_data=deliv_entry.get("deliverable", {}),
                iteration=1,
                schema=deliv_entry.get("schema"),
                created_by_id=user_id,
                status=status,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                review_notes=review_notes
            )
            pretranslate_targets.append((saved.id, deliv_entry.get("deliverable", {})))
            logger.debug(
                "Saved deliverable from %s (iteration %d)",
                deliv_entry.get("agent_label"),
                1
            )

        return pretranslate_targets

    @staticmethod
    def _schedule_openui_pretranslation(
        pretranslate_targets: list[tuple[str, dict]],
        *,
        user_id: Optional[str],
    ) -> None:
        del user_id  # unused; pretranslation opens its own session
        from app.services.chat_service import _schedule_pretranslation

        for deliverable_id, deliverable_data in pretranslate_targets:
            _schedule_pretranslation(deliverable_id, deliverable_data)
    
    async def _update_state_deliverable_status(
        self,
        deliverable: Deliverable,
        status: str,
        final_data: Optional[dict],
        user_response: Optional[dict] = None,
    ) -> None:
        """Update deliverable status in workflow state."""
        state = await self.execution_repo.get_execution_data(deliverable.execution_id)
        if not state:
            return
        
        deliverables_list = state.get("deliverables", [])
        matched = None
        for deliv in deliverables_list:
            if deliv.get("agent_id") == deliverable.agent_id:
                if deliv.get("iteration") == deliverable.iteration:
                    matched = deliv
                    break
                if matched is None:
                    matched = deliv
        
        if matched:
            matched["status"] = status
            if final_data:
                matched["deliverable"] = final_data
            if user_response is not None:
                matched["user_response"] = user_response
            logger.debug(
                "Updated deliverable status to '%s' in state for %s",
                status,
                deliverable.agent_label
            )
        
        state["deliverables"] = deliverables_list
        await self.execution_repo.save_execution_data(deliverable.execution_id, state)
    
    async def _add_rejection_feedback(self, deliverable: Deliverable) -> None:
        """Add rejection feedback message to state."""
        state = await self.execution_repo.get_execution_data(deliverable.execution_id)
        if not state:
            return
        
        rejection_message = HumanMessage(
            content=f"[Feedback on {deliverable.agent_label}'s deliverable]: {deliverable.review_notes}",
            additional_kwargs={
                "message_id": str(uuid.uuid4()),
                "is_rejection_feedback": True,
                "rejected_agent_id": deliverable.agent_id
            }
        )
        state["messages"].append(rejection_message)
        
        state["interrupted"] = False
        state["pending_deliverable"] = None
        
        await self.execution_repo.save_execution_data(deliverable.execution_id, state)
    
    async def _clear_rejected_node_outputs(self, deliverable: Deliverable) -> None:
        """Clear node outputs for rejected agent and its HITL."""
        state = await self.execution_repo.get_execution_data(deliverable.execution_id)
        if not state:
            return
        
        node_outputs = state.get("node_outputs", {})
        rejected_agent_id = deliverable.agent_id
        
        if rejected_agent_id in node_outputs:
            del node_outputs[rejected_agent_id]
            logger.debug("Cleared node_output for rejected agent: %s", rejected_agent_id)
        
        hitl_nodes_to_clear = []
        for node_id, output in list(node_outputs.items()):
            if output.get("node_type") in ["human-in-the-loop", "hitl"]:
                hitl_output = output.get("output", {})
                hitl_pending = hitl_output.get("pending_deliverable", {}) or hitl_output.get("deliverable_info", {})
                
                if hitl_pending.get("agent_id") == rejected_agent_id:
                    hitl_nodes_to_clear.append(node_id)
        
        for node_id in hitl_nodes_to_clear:
            del node_outputs[node_id]
            logger.debug("Cleared HITL node_output: %s", node_id)
        
        state["node_outputs"] = node_outputs
        await self.execution_repo.save_execution_data(deliverable.execution_id, state)
    
    async def _inject_startup_message(self, deliverable: Deliverable) -> Optional[dict]:
        """Inject startup message from next agent after approval."""
        try:
            session = await self.session_repo.get_by_id(deliverable.session_id)
            if not session:
                return None
            
            workflow = await self.workflow_repo.get_effective_by_id(
                session.workflow_id, user_id=session.user_id,
            )
            if not workflow:
                return None
            
            nodes = workflow.get_nodes_list()
            edges = workflow.get_edges_list()
            
            hitl_node_id = None
            for edge in edges:
                if edge.get("source") == deliverable.agent_id:
                    target_node_id = edge.get("target")
                    target_node = next((n for n in nodes if n.get("id") == target_node_id), None)
                    if target_node and target_node.get("type") == "human-in-the-loop":
                        hitl_node_id = target_node_id
                        break
            
            if not hitl_node_id:
                return None
            
            next_node = None
            for edge in edges:
                if edge.get("source") == hitl_node_id:
                    next_node_id = edge.get("target")
                    next_node = next((n for n in nodes if n.get("id") == next_node_id), None)
                    break
            
            processor_types = ["agent", "researcher", "business-analyst", "opportunity-classifier", "financial-modeler", "code-executor"]
            
            if not next_node or next_node.get("type") not in processor_types:
                return None
            
            node_config = next_node.get("config", {})
            agent_label = node_config.get("label", "Agent")

            from app.workflow.utils.startup import (
                build_startup_display_and_llm_content,
                get_startup_message_text,
                has_startup_content,
                should_wait_for_startup,
            )

            if not has_startup_content(node_config):
                return None

            wait_for_input = should_wait_for_startup(node_config)
            startup_message = get_startup_message_text(node_config)
            display_text, llm_content, questions_payload = build_startup_display_and_llm_content(
                node_config
            )
            
            state = await self.execution_repo.get_execution_data(deliverable.execution_id)

            additional_kwargs = {
                "message_id": str(uuid.uuid4()),
                "agent_id": next_node.get("id"),
                "agent_label": agent_label,
                "agent_type": next_node.get("type"),
                "is_startup_message": True,
                "timestamp": datetime.utcnow().isoformat(),
            }
            if questions_payload:
                additional_kwargs["questions"] = questions_payload
                additional_kwargs["display_content"] = display_text

            startup_ai_message = AIMessage(
                content=llm_content,
                additional_kwargs=additional_kwargs,
            )
            
            if "messages" not in state:
                state["messages"] = []
            state["messages"].append(startup_ai_message)
            
            state["pending_deliverable"] = None
            
            node_outputs = state.get("node_outputs", {})
            if next_node.get("id") in node_outputs:
                del node_outputs[next_node.get("id")]
                state["node_outputs"] = node_outputs
            
            state["next_node"] = next_node.get("id")

            if wait_for_input:
                state["interrupted"] = True
                await self.execution_repo.update_status(deliverable.execution_id, "paused")
            else:
                state["interrupted"] = False
                if "metadata" in state:
                    state["metadata"]["status"] = "running"

            await self.execution_repo.save_execution_data(deliverable.execution_id, state)
            await self.commit()
            
            logger.debug(
                "Startup message injected from %s (wait_for_input=%s)",
                agent_label, wait_for_input,
            )
            
            return {
                "role": "assistant",
                "content": f"🤖 {agent_label}: {startup_message}",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "agent_id": next_node.get("id"),
                    "agent_label": agent_label,
                    "is_startup_message": True,
                    "wait_for_input": wait_for_input,
                }
            }
        
        except Exception as e:
            logger.error("Failed to inject startup message: %s", e, exc_info=True)
            return None

