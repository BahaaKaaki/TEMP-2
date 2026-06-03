"""
Chat service for message handling business logic.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import uuid
from datetime import datetime
import logging
import json
import re

from .base import BaseService
from .file_scope_resolver import resolve_active_agent
from app.services.openui_prompt import system_prompt_available
from app.services.openui_translate_service import translate_deliverable_section_langs
from workflow.utils.file_scope import get_node_config_for_agent
from workflow.utils.file_context import build_agent_file_context
from db.pgsql import PrimarySessionLocal
from repositories import (
    SessionRepository,
    ExecutionRepository,
    DeliverableRepository,
    FileRepository,
    WorkflowRepository,
    CheckpointRepository,
)
from domain.entities import Session, Message
from core.exceptions import (
    SessionNotFoundException,
    SessionNotActiveException,
    WorkflowNotActiveException,
)
from workflow.executor import WorkflowExecutor
from langchain_core.messages import HumanMessage, AIMessage
from config.settings import settings

logger = logging.getLogger(__name__)

# Track background tasks to prevent garbage collection
_background_tasks: set = set()

# Deliverable ids with a translation in flight, so overlapping schedules
# (normal post-save + self-heal on read) never spawn duplicate LLM calls.
_inflight_pretranslate_ids: set[str] = set()


# Output types that don't render through OpenUI Lang -- skip pretranslation.
_OPENUI_RENDERED_OUTPUT_TYPES = {None, "", "sections"}

# Agent types whose deliverables are not rendered via OpenUI Lang.
_OPENUI_SKIP_AGENT_TYPES = {"code-executor", "powerpoint-generator"}

_ROOT_LANG_RE = re.compile(r"^root\s*=", re.MULTILINE)


def _deliverable_requires_openui(agent_type, output_type) -> bool:
    """Whether a deliverable renders through OpenUI Lang (mirrors the frontend)."""
    if agent_type in _OPENUI_SKIP_AGENT_TYPES:
        return False
    return output_type in _OPENUI_RENDERED_OUTPUT_TYPES


def openui_lang_array_is_ready(openui_lang) -> bool:
    """True when openui_lang is a JSON array with at least one renderable Lang.

    Matches the frontend's `hasRenderableOpenUI`: the column must hold a JSON
    array of per-section Lang strings and at least one entry must be a real
    `root = ...` program.
    """
    if not openui_lang or not isinstance(openui_lang, str):
        return False
    text = openui_lang.strip()
    if not text.startswith("["):
        return False
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(parsed, list) or not parsed:
        return False
    return any(
        isinstance(entry, str)
        and len(entry.strip()) >= 24
        and _ROOT_LANG_RE.search(entry)
        for entry in parsed
    )


def schedule_pretranslation_if_stale(deliverable) -> None:
    """Self-heal: (re)schedule OpenUI translation for a deliverable whose
    openui_lang is missing or not a renderable Lang array. The in-flight guard
    in `_schedule_pretranslation` makes overlapping polls a no-op.
    """
    try:
        agent_type = getattr(deliverable, "agent_type", None)
        data = (
            deliverable.get_deliverable_dict()
            if hasattr(deliverable, "get_deliverable_dict")
            else {}
        )
        output_type = data.get("_output_type") if isinstance(data, dict) else None
        if not _deliverable_requires_openui(agent_type, output_type):
            return
        if openui_lang_array_is_ready(getattr(deliverable, "openui_lang", None)):
            return
        payload = dict(data) if isinstance(data, dict) else {}
        payload.setdefault("_output_type", output_type)
        _schedule_pretranslation(deliverable.id, payload)
    except Exception as exc:
        logger.warning("Failed to schedule self-heal pretranslation: %s", exc)


async def _pretranslate_deliverable(deliverable_id: str, deliverable_data: dict) -> None:
    """Translate a deliverable's sections to OpenUI Lang and persist on its row.

    Runs as a fire-and-forget task post-save so chat reopens render instantly.
    Opens its own DB session so it survives the request that scheduled it.
    Persists a JSON array of per-section Lang strings on ``openuiLang``.
    """
    if not system_prompt_available():
        _inflight_pretranslate_ids.discard(deliverable_id)
        return
    try:
        langs = await translate_deliverable_section_langs(deliverable_data)
        if not any(isinstance(lang, str) and lang.strip() for lang in langs):
            # Nothing renderable; leave the row null so self-heal can retry.
            return
        async with PrimarySessionLocal() as db:
            await DeliverableRepository(db).save_openui_lang(
                deliverable_id, json.dumps(langs)
            )
    except Exception as exc:
        logger.warning(
            "OpenUI Lang pretranslation failed for %s: %s", deliverable_id, exc
        )
    finally:
        _inflight_pretranslate_ids.discard(deliverable_id)


def _schedule_pretranslation(saved_or_id, deliverable_data) -> None:
    """Fire-and-forget pretranslate the saved deliverable to OpenUI Lang.

    Accepts either a saved deliverable row (anything with an ``id`` attribute)
    or a string deliverable id. No-op for output types that don't render via
    OpenUI (widget, file, table, form) or when a translation is already in
    flight for the same deliverable.
    """
    try:
        if isinstance(saved_or_id, str):
            deliverable_id = saved_or_id
        else:
            deliverable_id = getattr(saved_or_id, "id", None)
        if not deliverable_id:
            return
        output_type = (
            deliverable_data.get("_output_type")
            if isinstance(deliverable_data, dict)
            else None
        )
        if output_type not in _OPENUI_RENDERED_OUTPUT_TYPES:
            return
        if deliverable_id in _inflight_pretranslate_ids:
            return
        _inflight_pretranslate_ids.add(deliverable_id)
        task = asyncio.create_task(
            _pretranslate_deliverable(deliverable_id, deliverable_data)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except Exception as exc:
        logger.warning("Failed to schedule OpenUI Lang pretranslation: %s", exc)


class ChatService(BaseService):
    """Service for chat message business logic."""
    
    def __init__(
        self,
        db: AsyncSession,
        session_repo: SessionRepository,
        execution_repo: ExecutionRepository,
        deliverable_repo: DeliverableRepository,
        file_repo: FileRepository,
        workflow_repo: WorkflowRepository,
        workflow_executor: WorkflowExecutor,
        checkpoint_repo: Optional["CheckpointRepository"] = None,
    ):
        super().__init__(db)
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.deliverable_repo = deliverable_repo
        self.file_repo = file_repo
        self.workflow_repo = workflow_repo
        self.workflow_executor = workflow_executor
        self.checkpoint_repo = checkpoint_repo

    async def _ensure_workflow_active_for_owner(
        self, workflow_id: str, user_id: Optional[str]
    ) -> None:
        """Activate an inactive workflow when the owner sends chat (mirrors session creation)."""
        if not user_id:
            return
        from db.models import WorkflowEntity
        from sqlalchemy import select

        result = await self.db.execute(
            select(WorkflowEntity).where(
                WorkflowEntity.id == workflow_id,
                WorkflowEntity.createdById == str(user_id),
                WorkflowEntity.isArchived == False,
            )
        )
        db_workflow = result.scalar_one_or_none()
        if db_workflow and not db_workflow.active:
            db_workflow.active = True
            logger.debug("Activated workflow %s for chat message", workflow_id)
    
    async def send_message(
        self,
        session_id: str,
        message: str,
        variables: Optional[dict] = None,
        user_id: Optional[str] = None,
        force_deliver: bool = False,
        question_message_id: Optional[str] = None,
        question_response: Optional[dict] = None,
    ) -> dict:
        """Send message to session and execute workflow.

        ``question_message_id`` and ``question_response`` are set when
        the user is submitting answers to a QuestionsCard. The backend
        stamps the matching agent AIMessage with ``answered_at`` and
        tags the new HumanMessage with the structured response so the
        history reflects the interaction.
        """
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundException(session_id)
        
        if not session.can_receive_messages():
            raise SessionNotActiveException(session_id)

        await self._ensure_workflow_active_for_owner(session.workflow_id, user_id)
        
        workflow = await self.workflow_repo.get_effective_by_id(
            session.workflow_id, user_id=user_id,
        )
        if not workflow:
            raise WorkflowNotActiveException(session.workflow_id)
        
        if not workflow.can_be_executed():
            raise WorkflowNotActiveException(session.workflow_id)
        
        existing_messages = await self._load_conversation_history(session_id)
        
        if not existing_messages:
            existing_messages = await self._inject_initial_message(workflow)
        
        enhanced_message = await self._enhance_message_with_files(
            session_id=session_id,
            message=message,
            workflow=workflow,
        )
        
        merged_vars = self._merge_variables(
            session.get_variables_dict(),
            variables or {}
        )
        
        should_resume, paused_execution, is_running = await self._check_resume_needed(session_id)
        
        # ── Guard: execution already in progress (e.g. deep research) ──
        if is_running:
            logger.warning(
                "Session %s: execution already running, returning 'running' status "
                "to prevent duplicate workflow launch",
                session_id,
            )
            return {
                "session_id": session_id,
                "message": (
                    "Workflow is still processing. "
                    "Please wait for the current step to complete."
                ),
                "role": "assistant",
                "timestamp": datetime.utcnow().isoformat(),
                "status": "running",
                "execution_id": paused_execution.id if paused_execution else None,
                "conversation_history": self._messages_to_history(
                    existing_messages
                ),
                "pending_deliverable": None,
            }
        
        # Generate message_id upfront so we can link it to the checkpoint
        user_message_id = str(uuid.uuid4())
        
        # Create checkpoint before processing (snapshot state BEFORE this message)
        await self._create_checkpoint_before_message(
            session_id=session_id,
            user_message_id=user_message_id,
            message_text=enhanced_message,
            display_text=message,
            user_id=user_id,
        )
        
        # ── Deep Research: launch in background, return immediately ──
        if not should_resume and self._has_deep_research(workflow):
            logger.info(
                "Session %s: deep research detected, launching background workflow",
                session_id,
            )
            return await self._handle_deep_research(
                session, enhanced_message, message,
                merged_vars, existing_messages, user_id,
            )
        
        if should_resume:
            result = await self._resume_workflow(
                paused_execution,
                enhanced_message,
                message,
                merged_vars,
                force_deliver=force_deliver,
                user_message_id=user_message_id,
                question_message_id=question_message_id,
                question_response=question_response,
            )
        else:
            result = await self._start_new_workflow(
                session,
                enhanced_message,
                message,
                merged_vars,
                existing_messages,
                force_deliver=force_deliver,
                user_message_id=user_message_id,
                question_message_id=question_message_id,
                question_response=question_response,
            )
        
        await self._save_deliverables(session_id, result, user_id)
        
        await self.session_repo.increment_message_count(session_id)
        await self.commit()
        
        response = self._format_response(session_id, result)
        
        logger.debug(
            "Session %s: sent message, status: %s",
            session_id,
            result.status
        )
        
        return response
    
    async def _load_conversation_history(self, session_id: str, max_recent_executions: int = 20) -> List:
        """
        Load and deduplicate conversation history with pagination.
        
        Loads only the most recent executions to prevent memory issues
        and slow queries in long-running conversations.
        
        Args:
            session_id: Session ID
            max_recent_executions: Maximum number of recent executions to load (default: 20)
                                    This prevents loading 1000+ executions in long conversations
        
        Returns:
            List of messages, pruned to recent history
        """
        # Load only recent executions (pagination at DB level)
        executions = await self.execution_repo.get_by_session_id(
            session_id, 
            order_by="desc",
            limit=max_recent_executions
        )
        
        # Reverse to maintain chronological order (oldest first)
        executions = list(reversed(executions))
        
        if not executions:
            logger.info("No executions found for session %s", session_id)
            return []
        
        # Batch load execution data to avoid N+1 queries
        execution_ids = [e.id for e in executions]
        states_dict = await self.execution_repo.get_execution_data_batch(execution_ids)
        
        messages = []
        seen_ids = set()
        has_initial_message = False
        
        for execution in executions:
            state = states_dict.get(execution.id)
            if not state:
                continue
            
            exec_messages = state.get("messages", [])
            for msg in exec_messages:
                if not msg.content or msg.content.strip() == "":
                    continue
                
                if hasattr(msg, "additional_kwargs") and msg.additional_kwargs.get("is_initial_message"):
                    if not has_initial_message:
                        has_initial_message = True
                        messages.append(msg)
                    continue
                
                msg_id = None
                if hasattr(msg, 'additional_kwargs') and isinstance(msg.additional_kwargs, dict):
                    msg_id = msg.additional_kwargs.get('message_id')
                
                if msg_id:
                    if msg_id not in seen_ids:
                        seen_ids.add(msg_id)
                        messages.append(msg)
                else:
                    msg_key = (msg.content[:settings.TEXT_PREVIEW_LENGTH], msg.__class__.__name__)
                    if msg_key not in seen_ids:
                        seen_ids.add(msg_key)
                        messages.append(msg)
        
        logger.debug(
            "Loaded %d messages from %d recent executions (limited to last %d)",
            len(messages),
            len(executions),
            max_recent_executions
        )
        
        return messages
    
    async def _inject_initial_message(self, workflow) -> List:
        """Inject session-open greeting from chat (legacy) or first downstream startup."""
        from app.workflow.utils.startup import resolve_session_open_content

        resolved = resolve_session_open_content(workflow)
        if not resolved:
            return []

        display_text = resolved["display_text"]
        llm_content = resolved["llm_content"]
        questions_payload = resolved.get("questions_payload")

        logger.debug(
            "Injecting session-open message: %s%s",
            (display_text or llm_content)[:50],
            " (+questions)" if questions_payload else "",
        )

        additional_kwargs: dict = {
            "message_id": str(uuid.uuid4()),
            "is_initial_message": True,
        }
        if resolved.get("agent_id"):
            additional_kwargs["agent_id"] = resolved["agent_id"]
            additional_kwargs["agent_label"] = resolved.get("agent_label")
            additional_kwargs["agent_type"] = resolved.get("agent_type")
        if questions_payload:
            additional_kwargs["questions"] = questions_payload
            additional_kwargs["display_content"] = display_text

        initial_ai_message = AIMessage(
            content=llm_content,
            additional_kwargs=additional_kwargs,
        )

        return [initial_ai_message]
    
    async def _enhance_message_with_files(
        self,
        session_id: str,
        message: str,
        workflow=None,
    ) -> str:
        """Glue this agent's own uploads into the user message.

        Files from other steps are injected into the system prompt during
        workflow execution (see ``build_agent_file_context``).
        """
        active_agent_id: Optional[str] = None
        node_config: dict = {}

        if workflow:
            try:
                active = await resolve_active_agent(
                    session_id=session_id,
                    workflow_id=workflow.id,
                    execution_repo=self.execution_repo,
                    workflow_repo=self.workflow_repo,
                )
                active_agent_id = active.agent_id
                if active_agent_id:
                    node_config = get_node_config_for_agent(workflow, active_agent_id)
            except Exception as e:
                logger.warning(
                    "file_scope: could not resolve active agent for session %s: %s",
                    session_id,
                    e,
                )

        if active_agent_id:
            file_block = await build_agent_file_context(
                session_id,
                active_agent_id,
                node_config,
                for_system=False,
                workflow=workflow,
                file_repo=self.file_repo,
            )
        else:
            files = await self.file_repo.get_parsed_files_by_session(session_id)
            logger.debug(
                "file_scope: active agent unresolved; legacy injecting %d files",
                len(files),
            )
            from workflow.utils.file_context import format_file_block
            file_block = format_file_block(
                files,
                header_title="UPLOADED DOCUMENTS - CONTEXT",
            )

        if not file_block:
            return message

        return (
            file_block
            + "\n\nUSER MESSAGE:\n"
            + message
        )
    
    def _merge_variables(self, session_vars: dict, request_vars: dict) -> dict:
        """Merge session and request variables."""
        return {**session_vars, **request_vars}
    
    async def _check_resume_needed(self, session_id: str) -> tuple[bool, Optional, bool]:
        """Check if execution should be resumed or is already running.

        Returns:
            (should_resume, execution, is_running)
        """
        latest_exec = await self.execution_repo.get_latest_by_session(session_id)
        
        if not latest_exec:
            return False, None, False
        
        if latest_exec.can_be_resumed():
            logger.info(
                "Found paused execution %d in '%s' status - will RESUME",
                latest_exec.id,
                latest_exec.status
            )
            return True, latest_exec, False
        
        if latest_exec.status == "running":
            logger.info(
                "Execution %d is already running - will reject duplicate message",
                latest_exec.id,
            )
            return False, latest_exec, True
        
        return False, None, False
    
    async def _create_checkpoint_before_message(
        self,
        session_id: str,
        user_message_id: str,
        message_text: str,
        display_text: str,
        user_id: Optional[str],
    ) -> None:
        """Create a checkpoint capturing state before this user message."""
        if not self.checkpoint_repo:
            return
        try:
            from .checkpoint_service import CheckpointService
            svc = CheckpointService(
                self.db,
                self.checkpoint_repo,
                self.session_repo,
                self.execution_repo,
                self.deliverable_repo,
            )
            await svc.create_checkpoint_before_message(
                session_id=session_id,
                user_message_id=user_message_id,
                user_message_text=message_text,
                user_message_display=display_text,
                user_id=user_id or "",
            )
        except Exception as e:
            logger.error("Failed to create checkpoint (non-fatal): %s", e, exc_info=True)

    async def _resume_workflow(
        self,
        execution,
        enhanced_message: str,
        display_message: str,
        variables: dict,
        force_deliver: bool = False,
        user_message_id: Optional[str] = None,
        question_message_id: Optional[str] = None,
        question_response: Optional[dict] = None,
    ) -> any:
        """Resume paused workflow."""
        logger.info("RESUMING execution %d", execution.id)
        
        state = await self.execution_repo.get_execution_data(execution.id)
        if not state:
            raise Exception("Cannot resume - state data not found")

        # Stamp the AIMessage that asked the questions as answered, and
        # tag the new HumanMessage with the structured answer payload so
        # downstream tooling can audit / restore the interaction.
        if question_message_id:
            self._stamp_question_answered(
                state.get("messages", []), question_message_id
            )

        new_user_extras: dict = {
            "message_id": user_message_id or str(uuid.uuid4()),
            "display_content": display_message,
        }
        if question_message_id:
            new_user_extras["is_question_response"] = True
            new_user_extras["question_message_id"] = question_message_id
        if question_response:
            new_user_extras["question_response"] = question_response

        new_user_message = HumanMessage(
            content=enhanced_message,
            additional_kwargs=new_user_extras,
        )
        state["messages"].append(new_user_message)
        
        state["interrupted"] = False
        state["pending_deliverable"] = None
        state["force_deliver"] = force_deliver
        
        await self.execution_repo.update_status(execution.id, "running")
        await self.commit()
        
        result = await self.workflow_executor.resume_workflow_from_state(
            execution_id=execution.id,
            state=state,
            variables=variables
        )
        
        return result
    
    async def _start_new_workflow(
        self,
        session,
        enhanced_message: str,
        display_message: str,
        variables: dict,
        existing_messages: List,
        force_deliver: bool = False,
        user_message_id: Optional[str] = None,
        question_message_id: Optional[str] = None,
        question_response: Optional[dict] = None,
    ) -> any:
        """Start new workflow execution."""
        logger.info("STARTING new execution for session %s", session.id)
        
        # Inject force_deliver into variables so it reaches the workflow state
        if force_deliver:
            variables = {**variables, "_force_deliver": True}

        # If this user message is answering a hand-configured initialQuestions
        # set on the chat node, the question AIMessage lives in
        # ``existing_messages`` (we just injected it above). Stamp it so the
        # answered_at flag is persisted into the new execution's state.
        if question_message_id:
            self._stamp_question_answered(existing_messages, question_message_id)

        result = await self.workflow_executor.execute_workflow(
            workflow_id=session.workflow_id,
            input_data={
                "message": enhanced_message,
                "display_message": display_message,
                "user_message_id": user_message_id,
                "question_message_id": question_message_id,
                "question_response": question_response,
            },
            initial_message=None,
            variables=variables,
            existing_messages=existing_messages,
            session_id=session.id
        )
        
        await self.execution_repo.update_session_id(result.execution_id, session.id)
        await self.commit()
        
        return result

    @staticmethod
    def _stamp_question_answered(messages: list, question_message_id: str) -> bool:
        """Stamp the AIMessage carrying a questions payload as answered.

        Walks the message list looking for an AIMessage whose
        ``additional_kwargs.message_id`` matches ``question_message_id``
        and that carries an unanswered ``questions`` payload, then sets
        ``answered_at`` on it.

        Returns True when a match was found and stamped.
        """
        if not question_message_id:
            return False
        for msg in messages:
            if msg.__class__.__name__ != "AIMessage":
                continue
            kwargs = getattr(msg, "additional_kwargs", None) or {}
            if (
                kwargs.get("message_id") == question_message_id
                and kwargs.get("questions")
                and not kwargs.get("answered_at")
            ):
                kwargs["answered_at"] = datetime.utcnow().isoformat()
                msg.additional_kwargs = kwargs
                return True
        return False
    
    async def _save_deliverables(
        self,
        session_id: str,
        result,
        user_id: Optional[str] = None
    ):
        """Save deliverables from execution result."""
        if not result.state:
            return
        
        deliverables = result.state.get("deliverables", [])
        for deliv_entry in deliverables:
            agent_id = deliv_entry.get("agent_id")

            status = deliv_entry.get("status", "pending")
            reviewed_by = user_id if status == "approved" else None
            reviewed_at = datetime.utcnow() if status == "approved" else None
            review_notes = deliv_entry.get("review_notes") or deliv_entry.get("reviewNotes")

            deliverable_data = deliv_entry.get("deliverable", {})
            citations = deliv_entry.get("citations", [])
            if citations and isinstance(deliverable_data, dict):
                deliverable_data["_citations"] = citations

            saved = await self.deliverable_repo.upsert_by_session_and_agent(
                session_id=session_id,
                execution_id=result.execution_id,
                agent_id=deliv_entry.get("agent_id"),
                agent_label=deliv_entry.get("agent_label"),
                agent_type=deliv_entry.get("agent_type"),
                deliverable_data=deliverable_data,
                iteration=1,
                schema=deliv_entry.get("schema"),
                created_by_id=user_id,
                status=status,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                review_notes=review_notes
            )
            _schedule_pretranslation(saved, deliverable_data)
            logger.debug(
                "Saved deliverable from %s (iteration %d)",
                deliv_entry.get("agent_label"),
                1
            )
        
        await self.commit()
    
    # ========================================================================
    # AUTO-START ON SESSION CREATION
    # ========================================================================

    @staticmethod
    def _should_auto_start_workflow(workflow) -> bool:
        """Return True when the workflow should run on session creation.

        Eligible when the first executable node after chat/start has no startup
        message or questionnaire (agents and code-executors). Code-executors
        with a runtime-input form still require the user to submit that form first.
        """
        try:
            from app.workflow.utils.startup import should_auto_start_on_session_open

            return should_auto_start_on_session_open(workflow)
        except Exception as e:
            logger.warning("Error checking auto-start eligibility: %s", e)
            return False

    async def auto_start_session_if_needed(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Kick off the workflow in the background when no startup greeting is needed.

        Returns ``True`` when a background run was launched, ``False``
        otherwise.  The caller doesn't need to await the run — the
        frontend's normal polling loop will pick up the execution state.
        """
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            return False

        workflow = await self.workflow_repo.get_effective_by_id(
            session.workflow_id, user_id=str(session.user_id) if session.user_id else None,
        )
        if not workflow:
            return False

        if not self._should_auto_start_workflow(workflow):
            return False

        logger.info(
            "Session %s: first executable has no startup pause — "
            "launching workflow without waiting for a chat message",
            session_id,
        )

        task = asyncio.create_task(
            _background_workflow_runner(
                session_id=session_id,
                workflow_id=session.workflow_id,
                enhanced_message="",
                display_message="",
                variables=session.get_variables_dict() or {},
                existing_messages=[],
                user_id=user_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return True

    # ========================================================================
    # DEEP RESEARCH BACKGROUND EXECUTION
    # ========================================================================

    @staticmethod
    def _has_deep_research(workflow) -> bool:
        """Check if any agent node in the workflow has enableDeepResearch."""
        try:
            nodes = workflow.get_nodes_list()
            for node in nodes:
                config = node.get("data", {}).get("config", {})
                if not config:
                    config = node.get("config", {})
                if config.get("enableDeepResearch"):
                    return True
        except Exception as e:
            logger.warning("Error checking deep research flag: %s", e)
        return False

    async def _handle_deep_research(
        self,
        session,
        enhanced_message: str,
        display_message: str,
        variables: dict,
        existing_messages: List,
        user_id: Optional[str],
    ) -> dict:
        """
        Launch workflow execution as a background asyncio task and return
        immediately with status='running' so the HTTP response finishes fast.

        The frontend will poll getChatSession() until the last message is
        from the assistant.
        """
        session_id = session.id
        workflow_id = session.workflow_id

        workflow = await self.workflow_repo.get_effective_by_id(
            workflow_id, user_id=user_id,
        )
        if not workflow:
            raise WorkflowNotActiveException(workflow_id)

        # Build a user HumanMessage so we can include it in the immediate response
        user_msg = HumanMessage(
            content=enhanced_message,
            additional_kwargs={
                "message_id": str(uuid.uuid4()),
                "display_content": display_message,
            },
        )

        workflow_json = await self.workflow_executor._build_workflow_json(workflow)
        execution_id = await self.workflow_executor._create_execution_record(
            workflow_id=workflow_id,
            workflow_data=workflow_json,
            user_id=user_id,
            session_id=session_id,
        )

        # ── Launch background task ──────────────────────────────────────
        task = asyncio.create_task(
            _background_workflow_runner(
                session_id=session_id,
                workflow_id=workflow_id,
                enhanced_message=enhanced_message,
                display_message=display_message,
                variables=variables,
                existing_messages=existing_messages,
                user_id=user_id,
                execution_id=execution_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        # ── Increment message count and commit ──────────────────────────
        await self.session_repo.increment_message_count(session_id)
        await self.commit()

        # ── Build conversation history for the immediate response ───────
        conversation_history = self._messages_to_history(
            list(existing_messages or []) + [user_msg]
        )

        logger.info(
            "Session %s: background workflow launched, returning running status",
            session_id,
        )

        return {
            "session_id": session_id,
            "message": (
                "Deep research is in progress. This may take several minutes — "
                "I will update this chat automatically when results are ready."
            ),
            "role": "assistant",
            "timestamp": datetime.utcnow().isoformat(),
            "status": "running",
            "execution_id": execution_id,
            "conversation_history": conversation_history,
            "pending_deliverable": None,
        }

    @staticmethod
    def _messages_to_history(messages: List) -> List[dict]:
        """Convert LangChain messages to the dict format used by the API."""
        history: List[dict] = []
        for msg in messages:
            role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
            message_id = (
                msg.additional_kwargs.get("message_id")
                if hasattr(msg, "additional_kwargs")
                else None
            )

            display_content = msg.content
            agent_id = None
            agent_label = None
            agent_type = None
            citations: list = []
            structured_queries: list = []
            questions = None
            answered_at = None
            edwin_url = None
            edwin_handoff_id = None
            message_format = None

            if hasattr(msg, "additional_kwargs") and isinstance(
                msg.additional_kwargs, dict
            ):
                # An explicitly stored display_content wins, even when it's
                # an empty string — that's how a question-only message
                # signals "render nothing above the QuestionsCard".
                if "display_content" in msg.additional_kwargs:
                    display_content = msg.additional_kwargs["display_content"] or ""
                agent_id = msg.additional_kwargs.get("agent_id")
                agent_label = msg.additional_kwargs.get("agent_label")
                agent_type = msg.additional_kwargs.get("agent_type")
                citations = msg.additional_kwargs.get("citations", [])
                structured_queries = msg.additional_kwargs.get("structured_queries", [])
                questions = msg.additional_kwargs.get("questions")
                answered_at = msg.additional_kwargs.get("answered_at")
                edwin_url = msg.additional_kwargs.get("edwin_url")
                edwin_handoff_id = msg.additional_kwargs.get("edwin_handoff_id")
                message_format = msg.additional_kwargs.get("format")

            # Strip file context from user messages
            if (
                msg.__class__.__name__ == "HumanMessage"
                and "UPLOADED DOCUMENTS" in msg.content
            ):
                parts = msg.content.split("USER MESSAGE:")
                if len(parts) > 1:
                    display_content = parts[-1].strip()

            entry: dict = {
                "message_id": message_id,
                "role": role,
                "content": display_content,
                "timestamp": datetime.utcnow().isoformat(),
                "agent_id": agent_id,
                "agent_label": agent_label,
                "agent_type": agent_type,
            }
            if citations:
                entry["citations"] = citations
            if structured_queries:
                entry["structured_queries"] = structured_queries
            if questions:
                entry["questions"] = questions
            if answered_at:
                entry["answered_at"] = answered_at
            if edwin_url:
                entry["edwin_url"] = edwin_url
            if edwin_handoff_id:
                entry["edwin_handoff_id"] = edwin_handoff_id
            if message_format:
                entry["format"] = message_format

            history.append(entry)
        return history

    def _format_response(self, session_id: str, result: any) -> dict:
        """Format chat response."""
        assistant_message = ""
        conversation_history = []
        pending_deliverable_info = None
        
        if result.state:
            messages = result.state.get("messages", [])
            
            for msg in messages:
                role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
                message_id = msg.additional_kwargs.get("message_id") if hasattr(msg, "additional_kwargs") else None
                
                display_content = msg.content
                agent_id = None
                agent_label = None
                agent_type = None
                
                citations = []
                structured_queries = []
                questions = None
                answered_at = None
                message_format = None
                if hasattr(msg, "additional_kwargs") and isinstance(msg.additional_kwargs, dict):
                    # An explicitly stored display_content wins, even when
                    # it's an empty string — that's how a question-only
                    # message signals "render nothing above the QuestionsCard".
                    if "display_content" in msg.additional_kwargs:
                        display_content = msg.additional_kwargs["display_content"] or ""

                    agent_id = msg.additional_kwargs.get("agent_id")
                    agent_label = msg.additional_kwargs.get("agent_label")
                    agent_type = msg.additional_kwargs.get("agent_type")
                    
                    citations = msg.additional_kwargs.get("citations", [])
                    structured_queries = msg.additional_kwargs.get("structured_queries", [])
                    questions = msg.additional_kwargs.get("questions")
                    answered_at = msg.additional_kwargs.get("answered_at")
                    message_format = msg.additional_kwargs.get("format")
                    
                    if role == "assistant":
                        logger.debug("Formatting assistant message - agent_id=%s, agent_label=%s, agent_type=%s, citations=%d, queries=%d", agent_id, agent_label, agent_type, len(citations), len(structured_queries))
                
                if msg.__class__.__name__ == "HumanMessage" and "UPLOADED DOCUMENTS" in msg.content:
                    parts = msg.content.split("USER MESSAGE:")
                    if len(parts) > 1:
                        display_content = parts[-1].strip()
                
                message_data = {
                    "message_id": message_id,
                    "role": role,
                    "content": display_content,
                    "timestamp": datetime.utcnow().isoformat(),
                    "agent_id": agent_id,
                    "agent_label": agent_label,
                    "agent_type": agent_type
                }
                
                if citations:
                    message_data["citations"] = citations
                    logger.debug("API Response: Adding %d citations to message %s", len(citations), message_id)
                if structured_queries:
                    message_data["structured_queries"] = structured_queries
                if questions:
                    message_data["questions"] = questions
                if answered_at:
                    message_data["answered_at"] = answered_at
                if message_format:
                    message_data["format"] = message_format
                
                conversation_history.append(message_data)
            
            for msg in reversed(messages):
                if msg.__class__.__name__ == "AIMessage":
                    assistant_message = msg.content
                    break
        
        if not assistant_message and result.output_data:
            if isinstance(result.output_data, dict):
                for key, value in result.output_data.items():
                    if isinstance(value, dict) and "response" in value:
                        assistant_message = value["response"]
                        break
                    elif isinstance(value, str):
                        assistant_message = value
                        break
        
        if not assistant_message:
            if result.status == "pending_review":
                assistant_message = "I have completed my analysis and produced a deliverable for your review."
            else:
                assistant_message = "I processed your message but couldn't generate a response."
        
        if result.status == "pending_review" and result.state:
            pending_deliverable = result.state.get("pending_deliverable")
            if pending_deliverable:
                pending_deliverable_info = {
                    "agent_id": pending_deliverable.get("agent_id"),
                    "agent_label": pending_deliverable.get("agent_label"),
                    "agent_type": pending_deliverable.get("agent_type"),
                    "deliverable": pending_deliverable.get("deliverable"),
                    "iteration": pending_deliverable.get("iteration", 1)
                }
        
        return {
            "session_id": session_id,
            "message": assistant_message,
            "role": "assistant",
            "timestamp": datetime.utcnow().isoformat(),
            "status": result.status,
            "execution_id": result.execution_id,
            "conversation_history": conversation_history,
            "pending_deliverable": pending_deliverable_info
        }


# ============================================================================
# MODULE-LEVEL BACKGROUND TASK
# ============================================================================

async def _background_workflow_runner(
    session_id: str,
    workflow_id: str,
    enhanced_message: str,
    display_message: str,
    variables: dict,
    existing_messages: list,
    user_id: Optional[str],
    execution_id: Optional[int] = None,
) -> None:
    """
    Run a workflow in the background with its own DB session.

    This is spawned as an ``asyncio.Task`` from
    ``ChatService._handle_deep_research`` so that the HTTP response
    can return immediately with ``status='running'``.

    The function creates a completely fresh DB session and all needed
    repositories / executor so it is independent of the request lifecycle.
    """
    from db.pgsql import PrimarySessionLocal, set_user_context

    logger.info("🔬 Background workflow started: session=%s workflow=%s", session_id, workflow_id)

    try:
        async with PrimarySessionLocal() as db:
            try:
                if user_id:
                    await set_user_context(db, user_id)

                executor = WorkflowExecutor(db, user_id=user_id)
                execution_repo = ExecutionRepository(db)
                deliverable_repo = DeliverableRepository(db)
                session_repo = SessionRepository(db)

                result = await executor.execute_workflow(
                    workflow_id=workflow_id,
                    input_data={
                        "message": enhanced_message,
                        "display_message": display_message,
                    },
                    initial_message=None,
                    variables=variables,
                    existing_messages=existing_messages,
                    session_id=session_id,
                    existing_execution_id=execution_id,
                )

                # Save deliverables (mirrors ChatService._save_deliverables)
                if result.state:
                    deliverables = result.state.get("deliverables", [])
                    for deliv_entry in deliverables:
                        status = deliv_entry.get("status", "pending")
                        reviewed_by = user_id if status == "approved" else None
                        reviewed_at = datetime.utcnow() if status == "approved" else None
                        review_notes = (
                            deliv_entry.get("review_notes")
                            or deliv_entry.get("reviewNotes")
                        )

                        deliverable_data = deliv_entry.get("deliverable", {})
                        citations = deliv_entry.get("citations", [])
                        if citations and isinstance(deliverable_data, dict):
                            deliverable_data["_citations"] = citations

                        saved = await deliverable_repo.upsert_by_session_and_agent(
                            session_id=session_id,
                            execution_id=result.execution_id,
                            agent_id=deliv_entry.get("agent_id"),
                            agent_label=deliv_entry.get("agent_label"),
                            agent_type=deliv_entry.get("agent_type"),
                            deliverable_data=deliverable_data,
                            iteration=1,
                            schema=deliv_entry.get("schema"),
                            created_by_id=user_id,
                            status=status,
                            reviewed_by=reviewed_by,
                            reviewed_at=reviewed_at,
                            review_notes=review_notes,
                        )
                        _schedule_pretranslation(saved, deliverable_data)

                await db.commit()

                logger.debug(
                    "🔬 Background workflow completed: session=%s status=%s execution=%d",
                    session_id,
                    result.status,
                    result.execution_id,
                )

            except Exception as e:
                logger.error(
                    "🔬 Background workflow error: session=%s error=%s",
                    session_id,
                    e,
                    exc_info=True,
                )
                await db.rollback()

    except Exception as outer:
        logger.error(
            "🔬 Background workflow DB session error: session=%s error=%s",
            session_id,
            outer,
            exc_info=True,
        )
