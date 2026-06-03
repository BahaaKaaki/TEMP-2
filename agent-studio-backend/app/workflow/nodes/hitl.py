"""
Human-in-the-Loop (HITL) Node.

Pauses workflow execution to wait for human review and approval of agent deliverables.
Supports both human review and AI judge modes (for future implementation).
"""

from typing import Any, Dict, Optional
import logging
from datetime import datetime

from .base import BaseNode
from ..state import WorkflowState

logger = logging.getLogger(__name__)


class HITLNode(BaseNode):
    """
    Human-in-the-Loop review node.
    
    Functionality:
    1. Detects deliverable from previous agent
    2. Pauses workflow execution
    3. Signals that human review is required
    4. Stores deliverable info for frontend display
    
    Modes:
    - review_and_edit: Human can approve, reject, or edit deliverable
    - ai_judge: AI evaluates deliverable (future feature)
    
    The actual workflow resumption happens in the API layer after human action.
    """
    
    async def execute(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute HITL review checkpoint.
        
        Checks for deliverable from previous agent and pauses execution if found.
        
        Args:
            state: Current workflow state
            
        Returns:
            HITL status and deliverable info
        """
        try:
            logger.info("🔁 HITL node %s checking for deliverable", self.label)
            
            # Get configuration
            mode = self.get_config_value("mode", "review_and_edit")
            require_approval = self.get_config_value("requireApproval", True)
            allow_editing = self.get_config_value("allowEditing", True)
            instructions = self.get_config_value("instructions", "Please review and approve the content before continuing.")
            
            # Find the previous agent's deliverable
            previous_deliverable = self._find_previous_deliverable(state)
            
            if not previous_deliverable:
                logger.warning("⚠️  HITL node %s found no deliverable to review", self.label)
                result = {
                    "status": "no_review_needed",
                    "skipped": True
                }
                logger.debug("🔍 DEBUG HITL returning: %s", list(result.keys()))
                logger.debug("🔍 DEBUG HITL does NOT include 'messages' in return - should preserve existing messages")
                return result
            
            # Check if this deliverable has already been approved (for resume after approval)
            # IMPORTANT: Check BOTH state AND database to handle cases where state might be stale
            deliverables = state.get("deliverables", [])
            previous_agent_id = previous_deliverable.get("agent_id")
            
            logger.debug("🔍 HITL %s checking if deliverable from %s (agent_id: %s) is approved",
                       self.label, previous_deliverable.get("agent_label"), previous_agent_id)
            logger.debug("🔍 state.deliverables has %d deliverables", len(deliverables))
            for i, d in enumerate(deliverables):
                logger.debug("   Deliverable %d: agent_id=%s, status=%s, label=%s", 
                           i, d.get("agent_id"), d.get("status"), d.get("agent_label"))
            
            # Strategy 1: Check state.deliverables
            for approved_deliv in deliverables:
                if (approved_deliv.get("agent_id") == previous_agent_id and 
                    approved_deliv.get("status") == "approved"):
                    logger.info(
                        "✅ HITL node %s found ALREADY APPROVED deliverable from %s in state - skipping review",
                        self.label,
                        previous_deliverable.get("agent_label")
                    )
                    return {
                        "status": "already_approved",
                        "message": "Deliverable already approved. Continuing workflow.",
                        "skipped": True
                    }
            
            # Strategy 2: Check database as fallback (state might be stale during resume)
            # Import here to avoid circular dependency
            try:
                from app.db.models import AgentDeliverable
                from sqlalchemy.future import select
                from app.db.pgsql import PrimarySessionLocal
                import asyncio
                
                # Get execution_id from state metadata
                execution_id = state.get("metadata", {}).get("execution_id")
                
                if execution_id:
                    # Query database for approved deliverables in this execution
                    logger.debug("🔍 Checking database for approved deliverables (execution_id: %d)", execution_id)
                    
                    # Check if deliverable is approved in database
                    async with PrimarySessionLocal() as session:
                        stmt = select(AgentDeliverable).where(
                            AgentDeliverable.executionId == execution_id,
                            AgentDeliverable.agentId == previous_agent_id,
                            AgentDeliverable.status == "approved"
                        )
                        result = await session.execute(stmt)
                        db_deliverable = result.scalar_one_or_none()
                        
                        if db_deliverable:
                            logger.info("✅ HITL node %s found APPROVED deliverable in database - skipping review", self.label)
                            return {
                                "status": "already_approved",
                                "message": "Deliverable already approved in database. Continuing workflow.",
                                "skipped": True
                            }
            except Exception as e:
                logger.warning("Failed to check database for approval status: %s", e)
            
            logger.info(
                "⏸️  HITL node %s pausing workflow - deliverable from %s requires review",
                self.label,
                previous_deliverable.get("agent_label", "unknown")
            )
            
            # Return state updates (don't mutate state directly - LangGraph needs return values)
            return {
                "metadata": {
                    **state.get("metadata", {}),
                    "status": "pending_review"
                },
                "pending_deliverable": previous_deliverable,
                "interrupted": True,
                "status": "pending_review",
                "mode": mode,
                "require_approval": require_approval,
                "allow_editing": allow_editing,
                "instructions": instructions,
                "deliverable_info": {
                    "agent_id": previous_deliverable.get("agent_id"),
                    "agent_label": previous_deliverable.get("agent_label"),
                    "agent_type": previous_deliverable.get("agent_type"),
                    "deliverable": previous_deliverable.get("deliverable"),
                    "iteration": previous_deliverable.get("iteration", 1)
                },
                "paused_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error("HITL node %s failed: %s", self.label, e, exc_info=True)
            # Don't block workflow on HITL failure
            return {
                "status": "error",
                "error": str(e),
                "message": "HITL node failed, continuing workflow"
            }
    
    def _find_previous_deliverable(self, state: WorkflowState) -> Optional[Dict[str, Any]]:
        """
        Find the deliverable from the agent node that directly precedes this HITL node.
        
        First checks state.deliverables, then falls back to checking node_outputs.
        
        Args:
            state: Current workflow state
            
        Returns:
            Deliverable info dict or None if not found
        """
        # Strategy 1: Check node_outputs to find which agent precedes this HITL
        # Then find that agent's deliverable in state.deliverables
        node_outputs = state.get("node_outputs", {})
        
        # Find the node that executed right before this HITL
        # (the one that should have created a deliverable for us to review)
        preceding_agent_id = None
        
        for node_id, node_output in reversed(list(node_outputs.items())):
            # Skip self
            if node_id == self.node_id:
                continue
            
            # Check if this node has a deliverable (either structure)
            has_deliv = node_output.get("has_deliverable") or node_output.get("output", {}).get("has_deliverable")
            
            if has_deliv:
                preceding_agent_id = node_id
                logger.debug("Found preceding agent with deliverable: %s", node_id)
                break
        
        # Strategy 1A: If we found the preceding agent, look for its deliverable in state.deliverables
        # This is more reliable as it persists across workflow resumes and includes approval status
        if preceding_agent_id:
            deliverables = state.get("deliverables", [])
            for deliverable in reversed(deliverables):
                if deliverable.get("agent_id") == preceding_agent_id:
                    logger.debug("Found deliverable from %s in state.deliverables (status: %s)", 
                                deliverable.get("agent_label"), deliverable.get("status"))
                    return deliverable
        
        # Strategy 2: Check node_outputs for deliverables (fallback)
        node_outputs = state.get("node_outputs", {})
        
        # Iterate through node outputs in reverse order (most recent first)
        for node_id, node_output in reversed(list(node_outputs.items())):
            # Skip self
            if node_id == self.node_id:
                continue
            
            # Try both structures: direct and nested
            # Check direct structure first
            if node_output.get("has_deliverable"):
                logger.debug("Found deliverable from node %s (direct)", node_id)
                return {
                    "agent_id": node_output.get("agent_id"),
                    "agent_label": node_output.get("agent_label"),
                    "agent_type": node_output.get("agent_type"),
                    "deliverable": node_output.get("deliverable"),
                    "iteration": node_output.get("iteration", 1),
                    "status": node_output.get("status", "pending")
                }
            
            # Check nested "output" structure
            output_data = node_output.get("output", {})
            if output_data.get("has_deliverable"):
                logger.debug("Found deliverable from node %s (nested)", node_id)
                return {
                    "agent_id": output_data.get("agent_id"),
                    "agent_label": output_data.get("agent_label"),
                    "agent_type": output_data.get("agent_type"),
                    "deliverable": output_data.get("deliverable"),
                    "iteration": output_data.get("iteration", 1),
                    "status": output_data.get("status", "pending")
                }
        
        logger.debug("No deliverable found in state.deliverables or node_outputs")
        return None
    
    def should_skip_review(self, state: WorkflowState) -> bool:
        """
        Determine if review can be skipped.
        
        Can be used for auto-approval logic in future (e.g., AI judge mode).
        
        Args:
            state: Current workflow state
            
        Returns:
            True if review can be skipped
        """
        mode = self.get_config_value("mode", "review_and_edit")
        
        # Currently, only human review is supported
        # AI judge mode would be implemented here in future
        if mode == "ai_judge":
            logger.debug("AI judge mode not yet implemented, requiring human review")
            return False
        
        # Human review always required
        return False

