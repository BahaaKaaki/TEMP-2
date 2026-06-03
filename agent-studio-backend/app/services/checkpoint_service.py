"""
Checkpoint service for revert-to-state feature.

Manages creating state snapshots before each user message and
performing atomic reverts that restore messages, deliverables,
execution status, and all workflow state.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime
import json
import logging
import os

from .base import BaseService
from repositories import (
    CheckpointRepository,
    SessionRepository,
    ExecutionRepository,
    DeliverableRepository,
)
from domain.entities import Checkpoint
from core.exceptions import (
    SessionNotFoundException,
    CheckpointNotFoundException,
    RevertConflictException,
)
from workflow.state import (
    serialize_state_for_storage,
    deserialize_state_from_storage,
)
from db.models import ExecutionEntity

logger = logging.getLogger(__name__)

from config.keyvault import cfg
MAX_CHECKPOINTS_PER_SESSION = cfg.MAX_CHECKPOINTS_PER_SESSION


class CheckpointService(BaseService):
    """Service for checkpoint creation and revert logic."""

    def __init__(
        self,
        db: AsyncSession,
        checkpoint_repo: CheckpointRepository,
        session_repo: SessionRepository,
        execution_repo: ExecutionRepository,
        deliverable_repo: DeliverableRepository,
    ):
        super().__init__(db)
        self.checkpoint_repo = checkpoint_repo
        self.session_repo = session_repo
        self.execution_repo = execution_repo
        self.deliverable_repo = deliverable_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_checkpoints(self, session_id: str) -> List[Checkpoint]:
        """List all checkpoints for a session, ordered by step.
        
        Lazily backfills checkpoints for existing user messages that
        predate the checkpoint feature, so revert buttons appear on all
        user messages -- not just those sent after the feature shipped.
        """
        existing = await self.checkpoint_repo.list_by_session(session_id)
        existing_msg_ids = {cp.user_message_id for cp in existing}

        backfilled = await self._backfill_missing_checkpoints(
            session_id, existing_msg_ids
        )
        if backfilled:
            return await self.checkpoint_repo.list_by_session(session_id)
        return existing

    async def create_checkpoint_before_message(
        self,
        session_id: str,
        user_message_id: str,
        user_message_text: str,
        user_message_display: Optional[str],
        user_id: str,
    ) -> Checkpoint:
        """
        Snapshot the full session state right before a user message is processed.

        Captures:
        - The current execution state (messages, node_outputs, deliverables, flags)
        - All agent_deliverable table rows for this session
        - The session's messageCount
        """
        # 1. Determine current execution (if any)
        latest_exec = await self.execution_repo.get_latest_by_session(session_id)
        execution_id = latest_exec.id if latest_exec else None
        execution_status = latest_exec.status if latest_exec else None

        # 2. Get current workflow state
        workflow_state_json = "{}"
        if execution_id:
            state = await self.execution_repo.get_execution_data(execution_id)
            if state:
                workflow_state_json = serialize_state_for_storage(state)

        # 3. Snapshot all deliverable rows for this session
        deliverables = await self.deliverable_repo.get_by_session_id(session_id)
        deliverable_snapshots = json.dumps(
            [self.deliverable_repo.snapshot_deliverable(d) for d in deliverables],
            default=str,
        )

        # 4. Get session message count
        session = await self.session_repo.get_by_id(session_id)
        message_count = session.message_count if session else 0

        # 5. Get next step index
        step_index = await self.checkpoint_repo.get_next_step_index(session_id)

        # 6. Create checkpoint
        checkpoint = await self.checkpoint_repo.create_checkpoint(
            session_id=session_id,
            execution_id=execution_id,
            user_message_id=user_message_id,
            user_message_text=user_message_text,
            user_message_display=user_message_display,
            workflow_state=workflow_state_json,
            execution_status=execution_status,
            deliverable_snapshots=deliverable_snapshots,
            step_index=step_index,
            session_message_count=message_count,
            user_id=user_id,
        )

        # 7. Prune old checkpoints if limit exceeded
        await self._prune_checkpoints(session_id)

        logger.debug(
            "Checkpoint created: session=%s step=%d msg_id=%s",
            session_id, step_index, user_message_id,
        )
        return checkpoint

    async def revert_to_checkpoint(
        self, session_id: str, checkpoint_id: str, user_id: str
    ) -> dict:
        """
        Atomically revert the session to the state captured in a checkpoint.

        Restores:
        - execution_data.data (messages, node_outputs, deliverables in-state, flags)
        - execution_entity.status
        - agent_deliverable table rows
        - chat_session.messageCount

        Also soft-deletes later executions and removes later checkpoints.

        Returns a dict with restored conversation_history, prefill_message,
        deliverables, and status for the frontend.
        """
        checkpoint = await self.checkpoint_repo.get_by_id(checkpoint_id)
        if not checkpoint:
            raise CheckpointNotFoundException(checkpoint_id)

        if checkpoint.session_id != session_id:
            raise CheckpointNotFoundException(checkpoint_id)

        # GUARD: no running executions
        latest_exec = await self.execution_repo.get_latest_by_session(session_id)
        if latest_exec and latest_exec.status == "running":
            raise RevertConflictException(session_id)

        # === ATOMIC REVERT ===

        # 1. Restore execution state
        snapshots = json.loads(checkpoint.deliverable_snapshots)
        if checkpoint.execution_id:
            state = deserialize_state_from_storage(checkpoint.workflow_state)

            # Sync state.deliverables / node_outputs with the deliverable
            # snapshot so stale data doesn't leak back into the DB via
            # intermediate saves during the resumed execution.
            snapshot_agent_ids = {
                s.get("agent_id") for s in snapshots if s.get("agent_id")
            }
            state_deliv_ids = {
                d.get("agent_id")
                for d in state.get("deliverables", [])
                if d.get("agent_id")
            }
            removed_ids = state_deliv_ids - snapshot_agent_ids
            if removed_ids:
                state["deliverables"] = [
                    d for d in state.get("deliverables", [])
                    if d.get("agent_id") not in removed_ids
                ]
                for rid in removed_ids:
                    state.get("node_outputs", {}).pop(rid, None)

                # Clear pending_deliverable if it belongs to a removed agent
                # so the resume path doesn't incorrectly enter HITL mode.
                pd = state.get("pending_deliverable")
                if pd and pd.get("agent_id") in removed_ids:
                    state["pending_deliverable"] = None

                logger.debug(
                    "Stripped %d stale agent(s) from state: %s",
                    len(removed_ids), removed_ids,
                )

            await self.execution_repo.save_execution_data(
                checkpoint.execution_id, state
            )
            # Mark as "paused" so _check_resume_needed triggers the
            # standard resume path.  Nodes still present in node_outputs
            # are skipped; agents whose outputs were removed above will
            # re-execute with the new user message.
            await self.execution_repo.update_status(
                checkpoint.execution_id, "paused", finished=False
            )
            logger.debug(
                "Restored execution %d state and marked paused for resume",
                checkpoint.execution_id,
            )

        # 2. Soft-delete all executions started AFTER the checkpoint's execution
        await self._soft_delete_later_executions(session_id, checkpoint)

        # 3. Restore agent_deliverable table
        await self.deliverable_repo.delete_by_session(session_id)
        for snap in snapshots:
            # Parse datetime strings back to datetime objects
            for dt_field in ("reviewed_at", "created_at", "updated_at"):
                val = snap.get(dt_field)
                if isinstance(val, str):
                    try:
                        snap[dt_field] = datetime.fromisoformat(val)
                    except (ValueError, TypeError):
                        snap[dt_field] = None
            await self.deliverable_repo.insert_from_snapshot(snap, fallback_user_id=user_id)
        logger.debug(
            "Restored %d deliverable(s) from checkpoint", len(snapshots),
        )

        # 4. Restore session metadata
        await self.session_repo.update_message_count(
            session_id, checkpoint.session_message_count
        )

        # 5. Delete all checkpoints after this one
        deleted_count = await self.checkpoint_repo.delete_after_step(
            session_id, checkpoint.step_index
        )
        logger.debug(
            "Deleted %d checkpoint(s) after step %d",
            deleted_count, checkpoint.step_index,
        )

        await self.commit()

        # 6. Build response for frontend
        conversation_history = self._build_conversation_history(checkpoint)
        pending_deliverable = self._extract_pending_deliverable(checkpoint)

        logger.debug(
            "Revert complete: session=%s -> checkpoint step=%d",
            session_id, checkpoint.step_index,
        )

        return {
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "conversation_history": conversation_history,
            "prefill_message": checkpoint.user_message_display or checkpoint.user_message_text,
            "deliverables": snapshots,
            "pending_deliverable": pending_deliverable,
            "status": checkpoint.execution_status or "active",
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _backfill_missing_checkpoints(
        self, session_id: str, existing_msg_ids: set
    ) -> int:
        """Create checkpoints for user messages that don't have one yet.

        For each HumanMessage in the latest execution state whose
        message_id is not in *existing_msg_ids*, a checkpoint is
        synthesised with the messages list truncated to right before
        that HumanMessage (i.e. the state *before* it was sent).
        """
        latest_exec = await self.execution_repo.get_latest_by_session(session_id)
        if not latest_exec:
            return 0

        state = await self.execution_repo.get_execution_data(latest_exec.id)
        if not state:
            return 0

        messages = state.get("messages", [])
        if not messages:
            return 0

        human_msgs = []
        for i, msg in enumerate(messages):
            if msg.__class__.__name__ != "HumanMessage":
                continue
            additional = getattr(msg, "additional_kwargs", {}) or {}
            msg_id = additional.get("message_id")
            if not msg_id or msg_id in existing_msg_ids:
                continue
            human_msgs.append((i, msg, msg_id, additional))

        if not human_msgs:
            return 0

        all_deliverables = await self.deliverable_repo.get_by_session_id(session_id)
        deliverable_snaps = [
            self.deliverable_repo.snapshot_deliverable(d) for d in all_deliverables
        ]
        deliverable_by_agent = {}
        for snap in deliverable_snaps:
            aid = snap.get("agent_id")
            if aid:
                deliverable_by_agent[aid] = snap

        session = await self.session_repo.get_by_id(session_id)
        next_step = await self.checkpoint_repo.get_next_step_index(session_id)
        created = 0

        for idx, msg, msg_id, additional in human_msgs:
            truncated = {k: v for k, v in state.items() if k != "messages"}
            truncated["messages"] = list(messages[:idx])

            display = additional.get("display_content") or msg.content
            if "UPLOADED DOCUMENTS" in msg.content:
                parts = msg.content.split("USER MESSAGE:")
                if len(parts) > 1:
                    display = parts[-1].strip()

            user_count = sum(
                1 for m in messages[:idx]
                if m.__class__.__name__ == "HumanMessage"
            )

            agents_before = set()
            for m in messages[:idx]:
                a = getattr(m, "additional_kwargs", {}) or {}
                aid = a.get("agent_id")
                if aid:
                    agents_before.add(aid)

            # Truncate node_outputs and deliverables to match the point
            # in time when this message was sent; without this, reverting
            # to a backfilled checkpoint restores outputs from agents
            # that hadn't run yet at that point.
            if agents_before:
                if "node_outputs" in truncated:
                    truncated["node_outputs"] = {
                        k: v for k, v in truncated["node_outputs"].items()
                        if k in agents_before
                    }
                if "deliverables" in truncated:
                    truncated["deliverables"] = [
                        d for d in truncated["deliverables"]
                        if d.get("agent_id") in agents_before
                    ]
            else:
                truncated["node_outputs"] = {}
                truncated["deliverables"] = []

            per_msg_snaps = [
                deliverable_by_agent[aid]
                for aid in agents_before
                if aid in deliverable_by_agent
            ]
            per_msg_json = json.dumps(per_msg_snaps, default=str)

            await self.checkpoint_repo.create_checkpoint(
                session_id=session_id,
                execution_id=latest_exec.id,
                user_message_id=msg_id,
                user_message_text=msg.content,
                user_message_display=display,
                workflow_state=serialize_state_for_storage(truncated),
                execution_status=latest_exec.status,
                deliverable_snapshots=per_msg_json,
                step_index=next_step + created,
                session_message_count=user_count,
                user_id=session.user_id or "" if session else "",
            )
            created += 1

        if created:
            await self.commit()
            logger.debug(
                "Backfilled %d checkpoint(s) for session %s",
                created, session_id,
            )
        return created

    async def _soft_delete_later_executions(
        self, session_id: str, checkpoint: Checkpoint
    ) -> None:
        """Mark all executions after the checkpoint as 'reverted'.

        When checkpoint.execution_id is None (checkpoint taken before any
        execution existed), ALL executions are soft-deleted.
        """
        all_execs = await self.execution_repo.get_by_session_id(session_id, order_by="asc")
        for exc in all_execs:
            if checkpoint.execution_id is None or exc.id > checkpoint.execution_id:
                await self.db.execute(
                    update(ExecutionEntity)
                    .where(ExecutionEntity.id == exc.id)
                    .values(status="reverted", finished=True, stoppedAt=datetime.utcnow())
                )
                logger.debug("Soft-deleted execution %d (status=reverted)", exc.id)

        await self.db.flush()

    async def _prune_checkpoints(self, session_id: str) -> None:
        """Remove oldest checkpoints if session exceeds the limit."""
        count = await self.checkpoint_repo.count_by_session(session_id)
        if count > MAX_CHECKPOINTS_PER_SESSION:
            pruned = await self.checkpoint_repo.delete_oldest(
                session_id, MAX_CHECKPOINTS_PER_SESSION
            )
            if pruned:
                logger.debug(
                    "Pruned %d old checkpoint(s) for session %s", pruned, session_id
                )

    def _build_conversation_history(self, checkpoint: Checkpoint) -> list:
        """Build conversation history dicts from the checkpointed workflow state."""
        try:
            state = deserialize_state_from_storage(checkpoint.workflow_state)
        except Exception:
            return []

        messages = state.get("messages", [])
        history = []
        for msg in messages:
            if not msg.content or msg.content.strip() == "":
                continue

            role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
            additional = getattr(msg, "additional_kwargs", {}) or {}

            display_content = msg.content
            stored_display = additional.get("display_content")
            if stored_display:
                display_content = stored_display

            if role == "user" and "UPLOADED DOCUMENTS" in msg.content:
                parts = msg.content.split("USER MESSAGE:")
                if len(parts) > 1:
                    display_content = parts[-1].strip()

            entry = {
                "message_id": additional.get("message_id"),
                "role": role,
                "content": display_content,
                "timestamp": additional.get("timestamp", datetime.utcnow().isoformat()),
                "agent_id": additional.get("agent_id"),
                "agent_label": additional.get("agent_label"),
                "agent_type": additional.get("agent_type"),
            }
            citations = additional.get("citations", [])
            if citations:
                entry["citations"] = citations

            history.append(entry)

        return history

    def _extract_pending_deliverable(self, checkpoint: Checkpoint) -> Optional[dict]:
        """Extract pending_deliverable from the checkpointed state if present."""
        try:
            state = deserialize_state_from_storage(checkpoint.workflow_state)
        except Exception:
            return None

        pending = state.get("pending_deliverable")
        if not pending:
            return None

        return {
            "agent_id": pending.get("agent_id"),
            "agent_label": pending.get("agent_label"),
            "agent_type": pending.get("agent_type"),
            "deliverable": pending.get("deliverable"),
            "iteration": pending.get("iteration", 1),
        }
