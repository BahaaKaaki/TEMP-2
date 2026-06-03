"""
Multi-agent mode execution orchestrator.

Handles:
- Agent state tracking and iteration management
- Deliverable lifecycle (creation, rejection handling)
- Question loop protection
- Citation filtering
"""

from typing import Any, Dict, List
from langchain_core.messages import AIMessage
import logging
import uuid
from datetime import datetime
import json
import re

from app.utils.citation_injector import CitationInjector
from ..state import WorkflowState, get_previous_deliverables, resolve_deliverable_sources
from ..utils.kb_config import resolve_kb_ids
from .agent_multi_instructions import MultiAgentInstructionBuilder
from .agent_multi_loop import MultiAgentLoopExecutor

logger = logging.getLogger(__name__)


class MultiAgentModeExecutor:
    """Executes agent in multi-agent mode with structured deliverables."""
    
    def __init__(self, node):
        """Initialize with parent node reference."""
        self.node = node
        self.instruction_builder = MultiAgentInstructionBuilder(node)
        self.loop_executor = MultiAgentLoopExecutor(node)
    
    async def execute(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute agent in multi-agent mode with deliverable output.
        
        Features:
        - Builds comprehensive system instructions with context
        - Supports iterative agent conversations
        - Produces structured deliverables
        - Injects previous agent outputs
        
        Args:
            state: Current workflow state
            
        Returns:
            Dictionary with chat response and optional deliverable
        """
        try:
            logger.info("🤖 Multi-agent node %s starting execution", self.node.label)
            
            # Update agent tracking
            self._update_state_tracking(state)
            
            # Check if should skip (already approved)
            if self._should_skip_execution(state):
                logger.debug("⏭️  Agent %s already has approved deliverable and no rejection - SKIPPING", 
                           self.node.label)
                return {}
            
            # Manage iteration tracking
            self._manage_iteration_tracking(state)
            
            # Build system instructions — in tool_caller_mode the Main LLM
            # should NOT see the output schema or submit_deliverable instructions.
            has_rejection_feedback = self._has_rejection_feedback(state)
            config = self.node.node_config or {}
            has_output_schema = bool(config.get("outputSchema"))

            structured_schema = await self._fetch_structured_schema(config)

            system_instructions = self.instruction_builder.build(
                state,
                has_rejection_feedback,
                tool_caller_mode=has_output_schema,
                structured_schema=structured_schema,
            )
            
            # Log context for debugging
            self._log_execution_context(state, system_instructions)
            
            # Execute agent loop
            result = await self.loop_executor.execute(state, system_instructions)
            
            # Clear force_deliver so downstream agents don't inherit it
            if state.get("force_deliver"):
                state["force_deliver"] = False
            
            # Process result and build output
            return self._process_result(result, state)
            
        except Exception as e:
            logger.error("Multi-agent node %s failed: %s", self.node.label, e, exc_info=True)
            raise
    
    def _update_state_tracking(self, state: WorkflowState) -> None:
        """Update state with current agent tracking info."""
        state["current_agent_id"] = self.node.node_id
        
        if "metadata" not in state:
            state["metadata"] = {}
        state["metadata"]["current_agent_id"] = self.node.node_id
        state["metadata"]["current_agent_label"] = self.node.label

    async def _fetch_structured_schema(self, config: Dict) -> str:
        """Check whether ANY configured KB has structured tables.

        Returns a lightweight indicator string (not the full model) so
        the instruction builder knows to include structured-data guidance.
        The query tool handles schema details autonomously.

        With multi-KB support we short-circuit on the first KB that has
        tables — guidance is the same regardless of which KB they live in.
        """
        kb_ids = resolve_kb_ids(config)
        if not kb_ids:
            return ""
        try:
            from app.repositories.structured_data_repository import StructuredDataRepository
            from app.db.pgsql import get_write_db

            async for db_session in get_write_db():
                try:
                    repo = StructuredDataRepository(db_session)
                    for kb_id in kb_ids:
                        tables = await repo.get_tables_for_kb(kb_id)
                        if tables:
                            logger.debug(
                                "📊 KB %s has %d structured table(s)",
                                kb_id, len(tables),
                            )
                            return "structured_data_available"
                finally:
                    break
        except Exception as e:
            logger.debug("No structured data check for KBs %s: %s", kb_ids, e)
        return ""
    
    def _should_skip_execution(self, state: WorkflowState) -> bool:
        """Check if agent should skip execution (already approved)."""
        my_deliverables = [d for d in state.get("deliverables", []) 
                          if d.get("agent_id") == self.node.node_id]
        
        my_rejected = any(d.get("status") == "rejected" for d in my_deliverables)
        my_approved = any(d.get("status") == "approved" for d in my_deliverables)
        
        # Check for rejection feedback
        messages = state.get("messages", [])
        my_rejection_feedback = any(
            hasattr(msg, "additional_kwargs") and 
            msg.additional_kwargs.get("is_rejection_feedback", False) and
            msg.additional_kwargs.get("rejected_agent_id") == self.node.node_id
            for msg in messages
        )
        
        if my_rejection_feedback or my_rejected:
            logger.info("🔄 Agent %s detected rejection - WILL RE-EXECUTE", self.node.label)
            return False
        
        return my_approved and not my_rejected and not my_rejection_feedback
    
    def _manage_iteration_tracking(self, state: WorkflowState) -> None:
        """Manage agent iteration counter."""
        my_deliverables = [d for d in state.get("deliverables", []) 
                          if d.get("agent_id") == self.node.node_id]
        
        # Single deliverable per agent: always use iteration 1
        state["current_agent_iteration"] = 1
        if my_deliverables:
            logger.debug("Agent %s re-executing (iteration %d)", 
                       self.node.label, state["current_agent_iteration"])

    def _has_rejection_feedback(self, state: WorkflowState) -> bool:
        """Check if there's rejection feedback in messages."""
        messages = state.get("messages", [])
        return any(
            msg.additional_kwargs.get("is_rejection_feedback", False) 
            for msg in messages 
            if hasattr(msg, "additional_kwargs")
        )
    
    def _log_execution_context(self, state: WorkflowState, system_instructions: str) -> None:
        """Log execution context for debugging."""
        config = self.node.node_config or {}
        previous_deliverables = resolve_deliverable_sources(state, self.node.node_id, config)
        
        if previous_deliverables:
            logger.debug("📥 Agent %s receiving %d previous deliverable(s):", 
                       self.node.label, len(previous_deliverables))
            for idx, deliv in enumerate(previous_deliverables):
                logger.debug(
                    "   [%d] From %s (status: %s)",
                    idx,
                    deliv.get('agent_label'),
                    deliv.get('status'),
                )
                logger.debug("      Deliverable content: %s", 
                           json.dumps(deliv.get('deliverable', {}), indent=6))
        else:
            logger.debug("📥 Agent %s has NO previous deliverables (first agent in chain)", 
                       self.node.label)
        
        logger.debug("📋 System instructions for %s (first 500 chars):", self.node.label)
        logger.debug("   %s...", system_instructions[:500])
    
    def _process_result(
        self,
        result: Dict[str, Any],
        state: WorkflowState
    ) -> Dict[str, Any]:
        """Process agent loop result and build final output."""
        deliverable = result.get("deliverable")
        chat_response = result.get("chat", result.get("response", ""))
        citations = result.get("citations", [])
        questions_payload = result.get("questions")

        # Questions always pause the workflow and never produce a deliverable
        if questions_payload:
            has_meaningful_deliverable = False
        else:
            has_meaningful_deliverable = self._is_meaningful_deliverable(deliverable)

        # Build output
        output = {
            "response": chat_response,
            "agent_id": self.node.node_id,
            "agent_label": self.node.label,
            "agent_type": self.node.node_type,
            "has_deliverable": has_meaningful_deliverable,
            "iteration": state.get("current_agent_iteration", 1),
        }

        if has_meaningful_deliverable:
            output = self._add_deliverable_to_output(
                output, deliverable, state, citations
            )
        elif questions_payload:
            logger.info(
                "❓ Agent %s pausing with %d structured question(s)",
                self.node.label,
                len(questions_payload.get("questions") or []),
            )
            output["interrupted"] = True
        else:
            logger.info("💬 Agent %s asking for more information - pausing workflow", 
                       self.node.label)
            output["interrupted"] = True
        
        # Filter and inject citations for the chat message
        if citations:
            chat_response, chat_citations = self._process_citations(chat_response, citations)
        else:
            chat_citations = []
        
        # Create conversation message
        structured_queries = result.get("structured_queries", [])
        msg_kwargs = {
            "message_id": str(uuid.uuid4()),
            "agent_id": self.node.node_id,
            "agent_label": self.node.label,
            "agent_type": self.node.node_type,
            "citations": chat_citations,
        }
        if structured_queries:
            msg_kwargs["structured_queries"] = structured_queries
            logger.debug(
                "📊 Attaching %d structured query trace(s) to AI message",
                len(structured_queries),
            )

        if questions_payload:
            # Mirror the standard-mode pause path: ``content`` carries the
            # full rendered questions text so the LLM has complete context
            # on resume; ``display_content`` stays empty because the
            # QuestionsCard component renders the intro itself — we don't
            # want it duplicated above the card in the chat bubble.
            from app.workflow.tools.ask_user_questions import render_questions_for_llm
            intro_text = (questions_payload.get("intro") or "").strip()
            llm_visible_content = render_questions_for_llm(questions_payload, intro_text)
            msg_kwargs["questions"] = questions_payload
            msg_kwargs["display_content"] = ""
            msg_kwargs["timestamp"] = datetime.utcnow().isoformat()
            new_message = AIMessage(
                content=llm_visible_content,
                additional_kwargs=msg_kwargs,
            )
        else:
            new_message = AIMessage(content=chat_response, additional_kwargs=msg_kwargs)
        messages = [new_message]

        # If next agent has a startup message and there's no HITL next, pause for user input
        if has_meaningful_deliverable:
            metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
            direct_next_is_hitl = False
            direct_map = metadata.get("direct_next_is_hitl", {})
            if isinstance(direct_map, dict):
                direct_next_is_hitl = direct_map.get(self.node.node_id, False)

            startup_map = metadata.get("direct_next_agent_startup", {})
            startup_info = startup_map.get(self.node.node_id) if isinstance(startup_map, dict) else None

            if startup_info and not direct_next_is_hitl:
                startup_message = AIMessage(
                    content=startup_info.get("startup_message", ""),
                    additional_kwargs={
                        "message_id": str(uuid.uuid4()),
                        "agent_id": startup_info.get("agent_id"),
                        "agent_label": startup_info.get("agent_label"),
                        "agent_type": startup_info.get("agent_type"),
                        "is_startup_message": True,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                messages.append(startup_message)
                output["next_node"] = startup_info.get("agent_id")
                if startup_info.get("wait_for_input", False):
                    output["interrupted"] = True
        
        self._log_result(chat_response, state, has_meaningful_deliverable, deliverable)
        
        return {
            **output,
            "messages": messages
        }
    
    def _is_meaningful_deliverable(self, deliverable: Any) -> bool:
        """
        Check if a deliverable has meaningful content.
        
        A deliverable is considered meaningful if:
        - It exists (not None)
        - It's a non-empty dict/list
        - All string values are not empty (or just whitespace)
        - Nested structures recursively contain meaningful values
        
        Args:
            deliverable: The deliverable to check
            
        Returns:
            True if deliverable has meaningful content, False otherwise
        """
        if deliverable is None:
            return False
        
        if isinstance(deliverable, dict):
            # Empty dict is not meaningful
            if not deliverable:
                return False
            
            # Check if at least one value is meaningful
            for value in deliverable.values():
                if self._is_meaningful_value(value):
                    return True
            
            return False
        
        if isinstance(deliverable, list):
            # Empty list is not meaningful
            if not deliverable:
                return False
            
            # Check if at least one item is meaningful
            for item in deliverable:
                if self._is_meaningful_value(item):
                    return True
            
            return False
        
        # For other types, check if meaningful value
        return self._is_meaningful_value(deliverable)
    
    def _is_meaningful_value(self, value: Any) -> bool:
        """
        Check if a single value is meaningful (not empty/whitespace).
        
        Args:
            value: The value to check
            
        Returns:
            True if value is meaningful, False otherwise
        """
        if value is None:
            return False
        
        if isinstance(value, str):
            # Empty or whitespace-only strings are not meaningful
            return bool(value.strip())
        
        if isinstance(value, (dict, list)):
            # Recursively check nested structures
            return self._is_meaningful_deliverable(value)
        
        # Numbers, booleans, etc. are considered meaningful
        # (even if False or 0, they're explicit values)
        return True
    
    def _add_deliverable_to_output(
        self,
        output: Dict[str, Any],
        deliverable: Dict,
        state: WorkflowState,
        citations: List[Dict] = None,
    ) -> Dict[str, Any]:
        """Add deliverable to output and state, including any citations."""
        output["deliverable"] = deliverable
        logger.info("Agent %s produced deliverable - workflow can proceed", self.node.label)
        
        metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
        direct_next_is_hitl = True  # default to pending if mapping is missing
        direct_map = metadata.get("direct_next_is_hitl", {})
        if isinstance(direct_map, dict):
            direct_next_is_hitl = direct_map.get(self.node.node_id, True)
        status = "pending" if direct_next_is_hitl else "approved"

        # Create deliverable entry
        if citations:
            deliverable = self._inject_deliverable_citations(deliverable, citations)

        deliverable_entry = {
            "agent_id": self.node.node_id,
            "agent_label": self.node.label,
            "agent_type": self.node.node_type,
            "deliverable": deliverable,
            "schema": self.node.get_config_value("outputSchema", "") or None,
            "iteration": 1,
            "status": status,
            "citations": citations or [],
        }
        if citations:
            logger.info("Attached %d citations to deliverable entry", len(citations))
        
        # Add to state (replace any previous deliverable for this agent)
        existing_deliverables = state.get("deliverables", []).copy()
        replaced = False
        new_deliverables = []
        for existing in existing_deliverables:
            if existing.get("agent_id") == self.node.node_id:
                if not replaced:
                    new_deliverables.append(deliverable_entry)
                    replaced = True
                # Skip any duplicate entries for this agent
            else:
                new_deliverables.append(existing)
        
        if not replaced:
            new_deliverables.append(deliverable_entry)
        
        output["deliverables"] = new_deliverables
        
        logger.info(f"Added deliverable to state.deliverables (now {len(new_deliverables)} total)")
        
        return output

    def _inject_deliverable_citations(
        self,
        deliverable: Dict[str, Any],
        citations: List[Dict],
    ) -> Dict[str, Any]:
        """Inject [N] citation markers into deliverable text fields.

        Walks every string value inside ``sections[].content`` and appends
        the citation marker whose chunk_text has the best word-overlap with
        that string.  This makes citations visible in the deliverable review
        UI where ``parseCitations`` looks for ``[N]`` patterns.
        """
        sections = deliverable.get("sections")
        if not sections or not citations:
            return deliverable

        stopwords = frozenset({
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "was", "are", "were",
            "be", "been", "this", "that", "these", "those", "it", "its",
        })

        def _significant_words(text: str) -> set:
            return set(re.findall(r"\b\w+\b", text.lower())) - stopwords

        citation_word_sets = [
            (_significant_words(c.get("chunk_text", "")), c["citation_number"])
            for c in citations
        ]

        injected_total = 0

        def _annotate_bullet(bullet: str) -> str:
            nonlocal injected_total
            if not bullet or re.search(r"\[\d+\]", bullet):
                return bullet
            bwords = _significant_words(bullet)
            best_num, best_overlap = None, 0
            for cwords, cnum in citation_word_sets:
                overlap = len(bwords & cwords)
                if overlap > best_overlap and overlap >= 3:
                    best_overlap = overlap
                    best_num = cnum
            if best_num is not None:
                injected_total += 1
                return f"{bullet.rstrip('., ')} [{best_num}]"
            return bullet

        def _annotate_list(items):
            if not isinstance(items, list):
                return items
            return [_annotate_bullet(i) if isinstance(i, str) else i for i in items]

        for section in sections:
            content = section.get("content")
            if not isinstance(content, dict):
                continue
            for key in (
                "executive_summary",
                "relevant_experience",
                "prior_experience",
                "education_and_languages",
            ):
                if key in content:
                    content[key] = _annotate_list(content[key])

            for proj in content.get("projects") or []:
                if isinstance(proj, dict) and "bullets" in proj:
                    proj["bullets"] = _annotate_list(proj["bullets"])

        logger.debug(
            "Injected citation markers into %d deliverable fields", injected_total
        )
        return deliverable

    def _process_citations(
        self,
        chat_response: str,
        citations: List[Dict]
    ) -> tuple[str, List[Dict]]:
        """Filter and inject citations into response."""
        markers_found = re.findall(r'\[(\d+)\]', chat_response)
        
        if not markers_found:
            logger.warning("⚠️ Multi-agent: LLM did not preserve citation markers! Using citation injection.")
            chat_response = CitationInjector.inject_citations(
                chat_response, citations, min_overlap_words=5
            )
            markers_found = re.findall(r'\[(\d+)\]', chat_response)
            logger.debug("✅ Multi-agent: Citation injection complete, markers now: %s", markers_found)
        
        # Filter to only used citations
        if markers_found:
            used_numbers = set(int(m) for m in markers_found)
            filtered_citations = [c for c in citations 
                                 if c['citation_number'] in used_numbers]
            logger.debug("🔍 Multi-agent: Filtered citations: %d used out of %d total",
                       len(filtered_citations), len(citations))
            return chat_response, filtered_citations

        # Never-silent fallback: the LLM dropped every marker AND nothing could
        # be matched inline (typical for web citations, whose ``chunk_text`` is
        # empty). Rather than discarding the sources and showing a bare
        # response, append a compact ``Sources:`` footer with [N] markers so
        # the frontend can still render clickable badges for web citations.
        web_citations = [c for c in citations if c.get("type") == "web"]
        if web_citations:
            logger.warning(
                "⚠️ Multi-agent: no inline markers matched — appending Sources footer "
                "with %d web citation(s)",
                len(web_citations),
            )
            chat_response = CitationInjector.append_sources_footer(
                chat_response, web_citations,
            )
            return chat_response, web_citations

        logger.warning("⚠️ Multi-agent: No citation markers in response, discarding all citations")
        return chat_response, []
    
    def _log_result(
        self,
        chat_response: str,
        state: WorkflowState,
        has_meaningful_deliverable: bool,
        deliverable: Any
    ) -> None:
        """Log result for debugging."""
        logger.debug(f"🔍 DEBUG: Agent {self.node.label} adding AIMessage to state")
        logger.debug(f"   Chat response: {chat_response[:100]}")
        logger.debug(f"   Current state has {len(state.get('messages', []))} messages")
        logger.debug(f"   Has meaningful deliverable: {has_meaningful_deliverable}")
        logger.debug(f"   Raw deliverable: {deliverable}")
        logger.debug(f"   Will interrupt: {not has_meaningful_deliverable}")

