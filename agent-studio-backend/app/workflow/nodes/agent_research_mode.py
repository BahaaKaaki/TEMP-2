"""
Deep research mode execution for agent node.

Implements Anthropic-style research orchestration with smart pre-check.
"""

from typing import Any, Dict
from langchain_core.messages import HumanMessage, AIMessage
import logging
import uuid
import time
import re

from config.llm_config import LLMClientManager, LLMConfig
from ..state import WorkflowState, get_previous_deliverables, format_deliverables_for_prompt, resolve_deliverable_sources
from ..research import ResearchOrchestrator
from .agent_standard_mode import StandardModeExecutor
from .agent_multi_instructions import resolve_agent_instructions

logger = logging.getLogger(__name__)


def _extract_text_content(content) -> str:
    """Normalise LLM response content that may be a list of blocks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts).strip()
    return str(content).strip()


class ResearchModeExecutor:
    """Executes agent in deep research mode."""
    
    def __init__(self, node):
        """Initialize with parent node reference."""
        self.node = node
    
    async def execute(self, state: WorkflowState) -> Dict[str, Any]:
        """
        Execute as Research Orchestrator (Anthropic pattern).
        
        Includes smart pre-check to skip research for simple queries.
        
        Args:
            state: Current workflow state
            
        Returns:
            Research result dictionary with final_report and metadata
        """
        try:
            # Extract research query
            query = self._extract_query_from_messages(state)
            
            # Get research configuration
            research_config = self._build_research_config()
            
            # Smart pre-check: Skip research for simple queries
            if not research_config.get("alwaysResearch", False):
                needs_research, reason = await self._should_use_deep_research(query)
                if not needs_research:
                    logger.debug("⚡ Skipping deep research (direct answer): %s", reason)
                    standard_executor = StandardModeExecutor(self.node)
                    return await standard_executor.execute(state)
            
            # Run deep research
            result = await self._run_research_orchestration(
                query, state, research_config
            )
            
            return result
            
        except Exception as e:
            logger.error("Deep research mode failed: %s", e, exc_info=True)
            logger.warning("Falling back to standard agent mode")
            standard_executor = StandardModeExecutor(self.node)
            return await standard_executor.execute(state)
    
    def _extract_query_from_messages(self, state: WorkflowState) -> str:
        """Extract research query from conversation messages."""
        messages = state.get("messages", [])
        query = ""
        
        # Find most recent HumanMessage
        for msg in reversed(messages):
            if msg.__class__.__name__ == "HumanMessage":
                # Try display_content first (clean query without file context)
                if hasattr(msg, "additional_kwargs") and isinstance(msg.additional_kwargs, dict):
                    display_content = msg.additional_kwargs.get("display_content")
                    if display_content and display_content.strip():
                        query = display_content
                        logger.debug("📝 Research query from display_content: %s", query[:100])
                        break
                
                # Fallback to full content
                query = msg.content
                # Skip system/startup messages
                if not query or "🤖" in query or query.startswith("{") or "UPLOADED DOCUMENTS" in query:
                    continue
                logger.debug("📝 Research query from message content: %s", query[:100])
                break
        
        # Final fallback
        if not query:
            logger.warning("⚠️ No valid user query found for research, using fallback")
            input_data = self.node.get_input_from_state(state)
            query = self._extract_query_string(input_data)
        
        return query
    
    def _extract_query_string(self, input_data: Any) -> str:
        """Extract query string from input data."""
        if isinstance(input_data, str):
            return input_data
        elif isinstance(input_data, dict):
            if "message" in input_data:
                return input_data["message"]
            elif "query" in input_data:
                return input_data["query"]
            # Fallback: stringify dict
            return str(input_data)
        return str(input_data)
    
    def _build_research_config(self) -> Dict[str, Any]:
        """Build research configuration from node config."""
        research_config = self.node.node_config.get("researchConfig", {}).copy()
        
        # Merge root-level research settings
        root_keys = [
            "maxIterations", "minSubagents", "maxSubagents",
            "addCitations", "researchDepth"
        ]
        for key in root_keys:
            if key in self.node.node_config:
                research_config[key] = self.node.node_config[key]
        
        return research_config
    
    async def _should_use_deep_research(self, query: str) -> tuple[bool, str]:
        """
        Check if query needs deep research or can be answered directly.
        
        Args:
            query: User's question
            
        Returns:
            Tuple of (needs_research: bool, reason: str)
        """
        # Get LLM
        provider = self.node.node_config.get("modelProvider", LLMConfig.DEFAULT_PROVIDER)
        model_name = self.node.node_config.get("modelName", LLMConfig.DEFAULT_MODEL)
        temperature = self.node.node_config.get("temperature", LLMConfig.DEFAULT_TEMPERATURE)
        max_tokens = self.node.node_config.get("maxTokens", LLMConfig.DEFAULT_MAX_TOKENS)
        
        llm = LLMClientManager.get_client(provider, model_name, temperature, max_tokens)
        
        prompt = f"""Analyze this query and decide if deep web research with multiple agents is needed.

Query: {query}

Consider:
1. Is this well-known information you can answer confidently? (capitals, basic facts, common knowledge)
2. Does it require CURRENT information from 2024-2025? (recent events, latest developments, breaking news)
3. Is it complex/nuanced requiring multiple sources and perspectives?
4. Does it ask for comparisons, analysis, or comprehensive research?

Examples that DON'T need research:
- "What is the capital of France?" → Well-known fact
- "Who wrote Romeo and Juliet?" → Historical fact
- "Explain photosynthesis" → Standard knowledge
- "What is 2+2?" → Basic math

Examples that DO need research:
- "What are the latest quantum computing developments in 2024?" → Current info needed
- "Compare the top 5 AI coding assistants" → Requires research & comparison
- "Analyze the economic impact of recent tariffs" → Current + complex
- "Research the history of the Roman Empire" → Comprehensive coverage

Respond EXACTLY in this format:
NEEDS_RESEARCH: yes/no
CONFIDENCE: 1-10 (how confident you are in answering without research)
REASON: One sentence explanation

Answer:"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = _extract_text_content(response.content)
            
            # Parse response
            needs_research = "NEEDS_RESEARCH: yes" in content.lower()
            
            # Extract confidence
            confidence_match = re.search(r'CONFIDENCE:\s*(\d+)', content)
            confidence = int(confidence_match.group(1)) if confidence_match else 5
            
            # Extract reason
            reason_match = re.search(r'REASON:\s*(.+)', content, re.IGNORECASE)
            reason = reason_match.group(1).strip() if reason_match else "Analysis completed"
            
            # High confidence (9-10) and doesn't need research -> skip
            if not needs_research and confidence >= 9:
                logger.debug("Skipping research - high confidence answer: %d/10", confidence)
                return (False, reason)
            
            logger.debug("Deep research needed - %s", reason)
            return (True, reason)
            
        except Exception as e:
            logger.error("Failed to check research need: %s", e)
            # Default to doing research if check fails
            return (True, "Pre-check failed, defaulting to research")
    
    async def _run_research_orchestration(
        self,
        query: str,
        state: WorkflowState,
        research_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run research orchestration and build result."""
        # Already imported at module level
        
        # Get previous deliverables context (respects deliverableSources config)
        config = self.node.node_config or {}
        previous_deliverables = resolve_deliverable_sources(state, self.node.node_id, config)
        if previous_deliverables:
            logger.debug("📥 Research agent receiving %d previous deliverable(s) for context",
                       len(previous_deliverables))
            deliverables_context = format_deliverables_for_prompt(previous_deliverables)
        else:
            deliverables_context = ""
            logger.debug("📥 Research agent has no previous deliverables (starting fresh)")
        
        # Get output schema and agent instructions
        output_schema = self.node.node_config.get("outputSchema", "")
        task_instructions = resolve_agent_instructions(self.node.node_config or {})
        
        logger.debug("📋 Research outputSchema configured: %s", "Yes" if output_schema else "No")
        logger.debug("📋 Research systemInstructions configured: %s", "Yes" if task_instructions else "No")
        
        # Get execution ID
        execution_id = state.get("metadata", {}).get("execution_id", 0)
        if not execution_id or execution_id == 0:
            execution_id = int(time.time() * 1000)
            logger.warning("⚠️ No execution_id in state, using generated ID: %d", execution_id)
        else:
            logger.debug("✅ Using execution_id from state: %d", execution_id)
        
        # Get tools (including KB tools)
        tool_names = self.node.get_config_value("tools", ["web_search"])
        tools = await self.node._get_tools(tool_names)
        
        # Create orchestrator
        orchestrator = ResearchOrchestrator(
            config=research_config,
            state=state,
            node_config=self.node.node_config,
            execution_id=execution_id,
            previous_context=deliverables_context,
            output_schema=output_schema,
            task_instructions=task_instructions,
            tools=tools
        )
        
        logger.info("🔬 Starting deep research for query: %s", query[:100])
        
        # Run research
        result = await orchestrator.run(query)
        
        # Extract findings
        final_report = result["final_report"]
        structured_output = result.get("structured_output", {})
        metadata = result.get("metadata", {})
        
        # Get chat message and deliverable
        chat_message = structured_output.get("chat", f"Research completed for: {query[:100]}")
        output_deliverable = structured_output.get("outputDeliverable", {"report": final_report})
        
        logger.debug("📊 Final report from orchestrator: %d chars", len(final_report))
        logger.debug("💬 Chat message: %s", chat_message[:200])
        logger.debug("📦 Output deliverable keys: %s",
                   list(output_deliverable.keys()) if isinstance(output_deliverable, dict) else "N/A")
        
        # Check for citations
        has_citations = "[1]" in final_report or "## Sources" in final_report
        logger.debug("🔍 Citations present in final_report: %s", has_citations)
        
        # Update state node_outputs
        state["node_outputs"][self.node.node_id] = {
            "output": output_deliverable,
            "response": chat_message,
            "final_report": final_report,
            "research_metadata": {
                "iterations": result["iterations"],
                "subagents_used": result["num_subagents"],
                "sources_count": result["sources_count"],
                "mode": "deep_research",
                "has_citations": has_citations
            }
        }
        
        # Create AI message for conversation
        new_message = AIMessage(content=chat_message, additional_kwargs={
            "message_id": str(uuid.uuid4()),
            "agent_id": self.node.node_id,
            "agent_label": self.node.label,
            "agent_type": self.node.node_type,
            "has_deliverable": True,
            "citations": []  # Research citations handled by orchestrator
        })
        
        logger.debug(
            "✅ Deep research complete: %d iterations, %d subagents, %d sources, citations=%s",
            result["iterations"], result["num_subagents"], 
            result["sources_count"], has_citations
        )
        
        metadata_map = state.get("metadata", {}) if isinstance(state, dict) else {}
        direct_next_is_hitl = True  # default to pending if mapping is missing
        direct_map = metadata_map.get("direct_next_is_hitl", {})
        if isinstance(direct_map, dict):
            direct_next_is_hitl = direct_map.get(self.node.node_id, True)
        status = "pending" if direct_next_is_hitl else "approved"

        # Create deliverable entry
        deliverable_entry = {
            "agent_id": self.node.node_id,
            "agent_label": self.node.label,
            "agent_type": self.node.node_type,
            "deliverable": output_deliverable,
            "full_report": final_report,
            "iteration": state.get("current_agent_iteration", 1),
            "status": status
        }
        
        # Add to state deliverables
        existing_deliverables = state.get("deliverables", []).copy()
        existing_deliverables.append(deliverable_entry)
        
        logger.info("✅ Added research deliverable to state.deliverables (now %d total)",
                   len(existing_deliverables))
        
        # Return result
        return {
            "chat": chat_message,
            "response": chat_message,
            "outputDeliverable": output_deliverable,
            "mode": "deep_research",
            "iterations": result["iterations"],
            "subagents_used": result["num_subagents"],
            "sources_count": result["sources_count"],
            "metadata": metadata,
            "has_deliverable": True,
            "deliverable": output_deliverable,
            "deliverables": existing_deliverables,
            "messages": [new_message]
        }

