"""
Deliverable repository for data access.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update
from datetime import datetime
import uuid
import json

from .base import BaseRepository
from db.models import AgentDeliverable
from domain.entities import Deliverable


class DeliverableRepository(BaseRepository[AgentDeliverable, Deliverable]):
    """Repository for deliverable data access."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, AgentDeliverable)
    
    async def get_by_id(self, deliverable_id: str) -> Optional[Deliverable]:
        """Get deliverable by ID."""
        query = select(AgentDeliverable).where(
            AgentDeliverable.id == deliverable_id
        )
        result = await self.db.execute(query)
        db_deliv = result.scalar_one_or_none()
        
        if not db_deliv:
            return None
        
        return self._to_domain(db_deliv)
    
    async def get_by_session_id(self, session_id: str) -> List[Deliverable]:
        """Get all deliverables for a session."""
        query = select(AgentDeliverable).where(
            AgentDeliverable.sessionId == session_id
        ).order_by(AgentDeliverable.createdAt.asc())
        
        result = await self.db.execute(query)
        deliverables = result.scalars().all()
        
        return [self._to_domain(d) for d in deliverables]
    
    async def get_by_agent_and_iteration(
        self,
        session_id: str,
        agent_id: str,
        iteration: int
    ) -> Optional[Deliverable]:
        """Get deliverable by agent and iteration."""
        query = select(AgentDeliverable).where(
            and_(
                AgentDeliverable.sessionId == session_id,
                AgentDeliverable.agentId == agent_id,
                AgentDeliverable.iteration == iteration
            )
        )
        result = await self.db.execute(query)
        db_deliv = result.scalar_one_or_none()
        
        if not db_deliv:
            return None
        
        return self._to_domain(db_deliv)

    async def upsert_by_session_and_agent(
        self,
        session_id: str,
        execution_id: int,
        agent_id: str,
        agent_label: str,
        agent_type: str,
        deliverable_data: dict,
        iteration: int = 1,
        schema: Optional[str] = None,
        created_by_id: Optional[str] = None,
        status: str = "pending",
        reviewed_by: Optional[str] = None,
        reviewed_at: Optional[datetime] = None,
        review_notes: Optional[str] = None
    ) -> Deliverable:
        """Create or overwrite a deliverable for a session+agent."""
        query = select(AgentDeliverable).where(
            and_(
                AgentDeliverable.sessionId == session_id,
                AgentDeliverable.agentId == agent_id
            )
        ).order_by(AgentDeliverable.createdAt.desc())
        result = await self.db.execute(query)
        existing = result.scalars().all()

        if existing:
            keep = existing[0]

            # Remove any duplicate rows for this agent/session
            if len(existing) > 1:
                for extra in existing[1:]:
                    await self.db.delete(extra)

            keep.executionId = execution_id
            keep.agentLabel = agent_label
            keep.agentType = agent_type
            new_payload = json.dumps(deliverable_data)
            # Only invalidate cached derivations when the deliverable data
            # actually changed. Resumes (e.g. after approve) re-save unchanged
            # rows; blindly nulling these would wipe a ready OpenUI Lang and
            # force a needless re-translate -- which resurfaces the "Preparing
            # deliverable view" spinner on an already-rendered deliverable.
            if keep.deliverable != new_payload:
                keep.deliverable = new_payload
                keep.vizConfigs = None
                keep.openuiLang = None
            if schema is not None:
                keep.deliverableSchema = schema
            keep.status = status
            if status == "approved":
                keep.reviewedAt = reviewed_at or datetime.utcnow()
                keep.reviewedBy = reviewed_by
                if review_notes is not None:
                    keep.reviewNotes = review_notes
            elif status == "rejected":
                keep.reviewedAt = reviewed_at or datetime.utcnow()
                keep.reviewedBy = reviewed_by
                if review_notes is not None:
                    keep.reviewNotes = review_notes
            else:
                keep.reviewedAt = None
                keep.reviewedBy = None
                keep.reviewNotes = None
            keep.iteration = iteration
            keep.previousDeliverableId = None
            if created_by_id is not None:
                keep.createdById = created_by_id
            now = datetime.utcnow()
            keep.createdAt = now
            keep.updatedAt = now

            await self.db.flush()
            await self.db.refresh(keep)

            return self._to_domain(keep)

        return await self.create_deliverable(
            deliverable_id=str(uuid.uuid4()),
            session_id=session_id,
            execution_id=execution_id,
            agent_id=agent_id,
            agent_label=agent_label,
            agent_type=agent_type,
            deliverable_data=deliverable_data,
            iteration=iteration,
            schema=schema,
            created_by_id=created_by_id,
            status=status,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            review_notes=review_notes
        )
    
    async def create_deliverable(
        self,
        deliverable_id: str,
        session_id: str,
        execution_id: int,
        agent_id: str,
        agent_label: str,
        agent_type: str,
        deliverable_data: dict,
        iteration: int = 1,
        schema: Optional[str] = None,
        created_by_id: Optional[str] = None,
        status: str = "pending",
        reviewed_by: Optional[str] = None,
        reviewed_at: Optional[datetime] = None,
        review_notes: Optional[str] = None
    ) -> Deliverable:
        """Create new deliverable."""
        db_deliv = AgentDeliverable(
            id=deliverable_id,
            sessionId=session_id,
            executionId=execution_id,
            agentId=agent_id,
            agentLabel=agent_label,
            agentType=agent_type,
            deliverable=json.dumps(deliverable_data),
            deliverableSchema=schema,
            status=status,
            iteration=iteration,
            createdById=created_by_id,
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow()
        )
        
        if status == "approved":
            db_deliv.reviewedAt = reviewed_at or datetime.utcnow()
            db_deliv.reviewedBy = reviewed_by
            db_deliv.reviewNotes = review_notes
        elif status == "rejected":
            db_deliv.reviewedAt = reviewed_at or datetime.utcnow()
            db_deliv.reviewedBy = reviewed_by
            db_deliv.reviewNotes = review_notes
        
        await self.create(db_deliv)
        return self._to_domain(db_deliv)
    
    async def approve_deliverable(
        self,
        deliverable_id: str,
        reviewed_by: Optional[str] = None,
        review_notes: Optional[str] = None,
        edited_data: Optional[dict] = None
    ) -> Deliverable:
        """Approve deliverable."""
        query = select(AgentDeliverable).where(
            AgentDeliverable.id == deliverable_id
        )
        result = await self.db.execute(query)
        db_deliv = result.scalar_one()
        
        db_deliv.status = "approved"
        db_deliv.reviewedAt = datetime.utcnow()
        db_deliv.reviewedBy = reviewed_by
        db_deliv.reviewNotes = review_notes
        
        if edited_data:
            db_deliv.deliverable = json.dumps(edited_data)
            # Invalidate cached viz configs -- data changed, must regenerate
            db_deliv.vizConfigs = None
            # Invalidate cached OpenUI Lang -- data changed, must re-translate
            db_deliv.openuiLang = None
        
        db_deliv.updatedAt = datetime.utcnow()
        
        await self.db.flush()
        await self.db.refresh(db_deliv)
        
        return self._to_domain(db_deliv)
    
    async def reject_deliverable(
        self,
        deliverable_id: str,
        reviewed_by: Optional[str] = None,
        review_notes: Optional[str] = None
    ) -> Deliverable:
        """Reject deliverable."""
        query = select(AgentDeliverable).where(
            AgentDeliverable.id == deliverable_id
        )
        result = await self.db.execute(query)
        db_deliv = result.scalar_one()
        
        db_deliv.status = "rejected"
        db_deliv.reviewedAt = datetime.utcnow()
        db_deliv.reviewedBy = reviewed_by
        db_deliv.reviewNotes = review_notes or "Please revise your output."
        db_deliv.updatedAt = datetime.utcnow()
        
        await self.db.flush()
        await self.db.refresh(db_deliv)
        
        return self._to_domain(db_deliv)
    
    async def save_openui_lang(
        self,
        deliverable_id: str,
        lang: str
    ) -> None:
        """Persist pre-translated OpenUI Lang string to DB."""
        await self.db.execute(
            update(AgentDeliverable)
            .where(AgentDeliverable.id == deliverable_id)
            .values(openuiLang=lang, updatedAt=datetime.utcnow())
        )
        await self.db.commit()

    async def delete_by_session(self, session_id: str) -> int:
        """Delete all deliverables for a session. Used during revert."""
        from sqlalchemy import delete as sa_delete
        stmt = sa_delete(AgentDeliverable).where(
            AgentDeliverable.sessionId == session_id
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def insert_from_snapshot(self, snapshot: dict, fallback_user_id: str = "") -> None:
        """Insert a deliverable from a checkpoint snapshot dict."""
        deliverable_data = snapshot.get("deliverable_data")
        if isinstance(deliverable_data, dict):
            deliverable_data = json.dumps(deliverable_data)
        elif deliverable_data is None:
            deliverable_data = "{}"

        viz_configs_raw = snapshot.get("viz_configs")
        viz_configs_str = None
        if viz_configs_raw is not None:
            if isinstance(viz_configs_raw, dict):
                viz_configs_str = json.dumps(viz_configs_raw)
            elif isinstance(viz_configs_raw, str):
                viz_configs_str = viz_configs_raw

        created_by = snapshot.get("created_by_id") or fallback_user_id

        row = AgentDeliverable(
            id=snapshot["id"],
            sessionId=snapshot["session_id"],
            executionId=snapshot["execution_id"],
            agentId=snapshot["agent_id"],
            agentLabel=snapshot["agent_label"],
            agentType=snapshot["agent_type"],
            deliverable=deliverable_data,
            deliverableSchema=snapshot.get("deliverable_schema"),
            vizMetadata=snapshot.get("viz_metadata"),
            vizConfigs=viz_configs_str,
            openuiLang=snapshot.get("openui_lang"),
            status=snapshot.get("status", "pending"),
            reviewedAt=snapshot.get("reviewed_at"),
            reviewedBy=snapshot.get("reviewed_by"),
            reviewNotes=snapshot.get("review_notes"),
            createdById=created_by,
            iteration=snapshot.get("iteration", 1),
            previousDeliverableId=snapshot.get("previous_deliverable_id"),
            createdAt=snapshot.get("created_at", datetime.utcnow()),
            updatedAt=snapshot.get("updated_at", datetime.utcnow()),
        )
        self.db.add(row)
        await self.db.flush()

    def snapshot_deliverable(self, deliverable: Deliverable) -> dict:
        """Convert a domain Deliverable to a snapshot dict for checkpoint storage."""
        return {
            "id": deliverable.id,
            "session_id": deliverable.session_id,
            "execution_id": deliverable.execution_id,
            "agent_id": deliverable.agent_id,
            "agent_label": deliverable.agent_label,
            "agent_type": deliverable.agent_type,
            "deliverable_data": deliverable.deliverable_data,
            "deliverable_schema": deliverable.deliverable_schema,
            "viz_configs": deliverable.viz_configs,
            "openui_lang": deliverable.openui_lang,
            "status": deliverable.status,
            "iteration": deliverable.iteration,
            "reviewed_at": deliverable.reviewed_at.isoformat() if deliverable.reviewed_at else None,
            "reviewed_by": deliverable.reviewed_by,
            "review_notes": deliverable.review_notes,
            "created_by_id": deliverable.created_by_id,
            "previous_deliverable_id": deliverable.previous_deliverable_id,
            "created_at": deliverable.created_at.isoformat() if deliverable.created_at else None,
            "updated_at": deliverable.updated_at.isoformat() if deliverable.updated_at else None,
        }

    def _to_domain(self, db_deliv: AgentDeliverable) -> Deliverable:
        """Convert database model to domain entity."""
        deliverable_data = json.loads(db_deliv.deliverable) if db_deliv.deliverable else {}
        
        # Parse viz_configs if present
        viz_configs = None
        if hasattr(db_deliv, 'vizConfigs') and db_deliv.vizConfigs:
            try:
                viz_configs = json.loads(db_deliv.vizConfigs)
            except (json.JSONDecodeError, TypeError):
                viz_configs = None

        openui_lang = getattr(db_deliv, 'openuiLang', None) or None

        return Deliverable(
            id=db_deliv.id,
            session_id=db_deliv.sessionId,
            execution_id=db_deliv.executionId,
            agent_id=db_deliv.agentId,
            agent_label=db_deliv.agentLabel,
            agent_type=db_deliv.agentType,
            deliverable_data=deliverable_data,
            deliverable_schema=db_deliv.deliverableSchema,
            status=db_deliv.status,
            iteration=db_deliv.iteration,
            reviewed_at=db_deliv.reviewedAt,
            reviewed_by=db_deliv.reviewedBy,
            review_notes=db_deliv.reviewNotes,
            previous_deliverable_id=db_deliv.previousDeliverableId,
            created_at=db_deliv.createdAt,
            updated_at=db_deliv.updatedAt,
            viz_configs=viz_configs,
            created_by_id=db_deliv.createdById,
            openui_lang=openui_lang
        )

