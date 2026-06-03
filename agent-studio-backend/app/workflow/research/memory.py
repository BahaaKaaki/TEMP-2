"""
Research memory system using Redis for persistent storage.

Handles storage and retrieval of research plans, findings, and intermediate
results across multiple iterations. Survives context window limitations.
"""

import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ResearchMemory:
    """
    Persistent memory for research orchestration.
    
    Uses Redis to store:
    - Research plans (strategy for each iteration)
    - Subagent findings (results from each subagent)
    - Iteration history (track progress)
    - Source accumulation (all discovered sources)
    
    Data persists for 1 hour (sufficient for research session).
    """
    
    def __init__(
        self,
        execution_id: int,
        redis_client: Optional[Any] = None
    ):
        """
        Initialize research memory.
        
        Args:
            execution_id: Unique execution ID for this research session
            redis_client: Optional Redis client (will create if None)
        """
        self.execution_id = execution_id
        self.redis = redis_client
        self.ttl = 3600  # 1 hour TTL
        
        # Key prefixes for different data types
        self.key_plan = f"research:{execution_id}:plan"
        self.key_findings = f"research:{execution_id}:findings"
        self.key_sources = f"research:{execution_id}:sources"
        self.key_iterations = f"research:{execution_id}:iterations"
        
        logger.debug(
            "Initialized ResearchMemory for execution_id=%d",
            execution_id
        )
    
    async def _ensure_redis(self) -> Any:
        """
        Ensure Redis connection is available.
        
        Returns:
            Redis client
            
        Raises:
            RuntimeError: If Redis is not available
        """
        if self.redis is None:
            try:
                # Import here to avoid circular dependency
                from db.redis import get_redis, init_redis
                
                # Try to get existing Redis connection
                try:
                    self.redis = await get_redis()
                except RuntimeError:
                    # Redis not initialized yet, initialize it
                    logger.debug("Initializing Redis for research memory")
                    await init_redis()
                    self.redis = await get_redis()
                
            except Exception as e:
                logger.error("Failed to initialize Redis: %s", e)
                raise RuntimeError("Redis is required for research memory") from e
        
        return self.redis
    
    async def save_plan(self, plan: Dict[str, Any]) -> None:
        """
        Save research plan for current iteration.
        
        Args:
            plan: Research plan dictionary containing:
                - iteration: Current iteration number
                - strategy: Overall research strategy
                - focus_areas: List of areas to investigate
                - subagent_count: Planned number of subagents
        """
        try:
            redis = await self._ensure_redis()
            
            # Add timestamp
            plan["saved_at"] = datetime.utcnow().isoformat()
            
            # Debug: Log the exact Redis key being used
            logger.debug("💾 Saving plan to Redis:")
            logger.debug("   Key: %s", self.key_plan)
            logger.debug("   execution_id: %d", self.execution_id)
            logger.debug("   iteration: %d", plan.get("iteration", 0))
            
            # Save to Redis
            await redis.set(
                self.key_plan,
                json.dumps(plan),
                ex=self.ttl
            )
            
            logger.debug(
                "✅ Saved research plan for iteration %d (execution_id=%d) to key: %s",
                plan.get("iteration", 0),
                self.execution_id,
                self.key_plan
            )
            
        except Exception as e:
            logger.error("Failed to save research plan: %s", e)
            # Don't raise - memory failure shouldn't stop research
    
    async def retrieve_plan(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve the current research plan.
        
        Returns:
            Research plan dictionary or None if not found
        """
        try:
            redis = await self._ensure_redis()
            
            plan_json = await redis.get(self.key_plan)
            
            if plan_json:
                plan = json.loads(plan_json)
                logger.debug("Retrieved research plan: iteration %d", plan.get("iteration", 0))
                return plan
            
            logger.debug("No research plan found")
            return None
            
        except Exception as e:
            logger.error("Failed to retrieve research plan: %s", e)
            return None
    
    async def append_finding(self, finding: Dict[str, Any]) -> None:
        """
        Append a subagent finding to the collection.
        
        Args:
            finding: Finding dictionary containing:
                - subagent_id: Unique subagent identifier
                - iteration: Which iteration this is from
                - task: What the subagent was asked to research
                - findings: The research results
                - sources: List of source URLs
        """
        try:
            redis = await self._ensure_redis()
            
            # Add timestamp
            finding["recorded_at"] = datetime.utcnow().isoformat()
            
            # Get existing findings
            findings = await self.get_all_findings()
            
            # Append new finding
            findings.append(finding)
            
            # Save back to Redis
            await redis.set(
                self.key_findings,
                json.dumps(findings),
                ex=self.ttl
            )
            
            logger.debug(
                "Appended finding from %s (total findings: %d)",
                finding.get("subagent_id", "unknown"),
                len(findings)
            )
            
        except Exception as e:
            logger.error("Failed to append finding: %s", e)
    
    async def get_all_findings(self) -> List[Dict[str, Any]]:
        """
        Get all findings from all subagents.
        
        Returns:
            List of finding dictionaries
        """
        try:
            redis = await self._ensure_redis()
            
            findings_json = await redis.get(self.key_findings)
            
            if findings_json:
                findings = json.loads(findings_json)
                logger.debug("Retrieved %d findings", len(findings))
                return findings
            
            return []
            
        except Exception as e:
            logger.error("Failed to retrieve findings: %s", e)
            return []
    
    async def add_sources(self, sources: List[Dict[str, str]]) -> None:
        """
        Add sources to the accumulated source list.
        
        Args:
            sources: List of source dictionaries with 'url' and 'title'
        """
        try:
            redis = await self._ensure_redis()
            
            # Get existing sources
            existing = await self.get_all_sources()
            existing_urls = {s['url'] for s in existing}
            
            # Add new unique sources
            new_sources = [
                s for s in sources
                if s['url'] not in existing_urls
            ]
            
            if new_sources:
                all_sources = existing + new_sources
                
                await redis.set(
                    self.key_sources,
                    json.dumps(all_sources),
                    ex=self.ttl
                )
                
                logger.debug(
                    "Added %d new sources (total: %d)",
                    len(new_sources),
                    len(all_sources)
                )
            
        except Exception as e:
            logger.error("Failed to add sources: %s", e)
    
    async def get_all_sources(self) -> List[Dict[str, str]]:
        """
        Get all accumulated sources.
        
        Returns:
            List of source dictionaries
        """
        try:
            redis = await self._ensure_redis()
            
            sources_json = await redis.get(self.key_sources)
            
            if sources_json:
                sources = json.loads(sources_json)
                logger.debug("Retrieved %d sources", len(sources))
                return sources
            
            return []
            
        except Exception as e:
            logger.error("Failed to retrieve sources: %s", e)
            return []
    
    async def record_iteration(self, iteration_data: Dict[str, Any]) -> None:
        """
        Record metadata about a completed iteration.
        
        Args:
            iteration_data: Iteration metadata containing:
                - iteration_number: Which iteration
                - subagents_spawned: How many subagents were created
                - synthesis_length: Length of synthesis
                - is_complete: Whether research was deemed complete
        """
        try:
            redis = await self._ensure_redis()
            
            # Get existing iterations
            iterations_json = await redis.get(self.key_iterations)
            iterations = json.loads(iterations_json) if iterations_json else []
            
            # Add timestamp
            iteration_data["completed_at"] = datetime.utcnow().isoformat()
            
            # Append
            iterations.append(iteration_data)
            
            # Save
            await redis.set(
                self.key_iterations,
                json.dumps(iterations),
                ex=self.ttl
            )
            
            logger.debug(
                "Recorded iteration %d (complete=%s)",
                iteration_data.get("iteration_number", 0),
                iteration_data.get("is_complete", False)
            )
            
        except Exception as e:
            logger.error("Failed to record iteration: %s", e)
    
    async def get_iteration_history(self) -> List[Dict[str, Any]]:
        """
        Get history of all completed iterations.
        
        Returns:
            List of iteration metadata
        """
        try:
            redis = await self._ensure_redis()
            
            iterations_json = await redis.get(self.key_iterations)
            
            if iterations_json:
                iterations = json.loads(iterations_json)
                logger.debug("Retrieved %d iterations", len(iterations))
                return iterations
            
            return []
            
        except Exception as e:
            logger.error("Failed to retrieve iteration history: %s", e)
            return []
    
    async def clear(self) -> None:
        """
        Clear all research memory (cleanup after completion).
        """
        try:
            redis = await self._ensure_redis()
            
            keys = [
                self.key_plan,
                self.key_findings,
                self.key_sources,
                self.key_iterations
            ]
            
            for key in keys:
                await redis.delete(key)
            
            logger.info("Cleared research memory for execution_id=%d", self.execution_id)
            
        except Exception as e:
            logger.error("Failed to clear research memory: %s", e)
    
    async def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of current research state.
        
        Returns:
            Summary dictionary with counts and status
        """
        try:
            findings = await self.get_all_findings()
            sources = await self.get_all_sources()
            iterations = await self.get_iteration_history()
            plan = await self.retrieve_plan()
            
            return {
                "execution_id": self.execution_id,
                "current_iteration": plan.get("iteration", 0) if plan else 0,
                "total_findings": len(findings),
                "total_sources": len(sources),
                "iterations_completed": len(iterations),
                "has_plan": plan is not None
            }
            
        except Exception as e:
            logger.error("Failed to get summary: %s", e)
            return {"error": str(e)}

