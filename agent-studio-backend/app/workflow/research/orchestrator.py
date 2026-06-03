"""
Research orchestrator implementing Anthropic's multi-agent research pattern.

Main control loop that:
1. Analyzes query and creates research plan
2. Dynamically spawns subagents (1-20 based on complexity)
3. Executes subagents in parallel
4. Synthesizes findings
5. Evaluates completeness and iterates if needed
6. Adds citations to final report
"""

import logging
import asyncio
from typing import Dict, List, Any
from langchain_core.messages import HumanMessage
# from langfuse import observe  # DISABLED
from utils.langfuse_config import observe  # No-op decorator

from .memory import ResearchMemory
from .subagent_executor import SubagentExecutor
from .citation_processor import CitationProcessor
from .utils import create_research_summary
from ..state import WorkflowState
from ..tools.registry import get_tool_registry

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


class ResearchOrchestrator:
    """
    Orchestrates deep research following Anthropic's pattern.
    
    Acts as the "lead agent" that:
    - Thinks and plans research strategy
    - Decides how many subagents needed (dynamic)
    - Spawns and manages subagents
    - Synthesizes findings iteratively
    - Evaluates completeness
    - Adds citations
    
    Implements the full iterative research loop with memory persistence.
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        state: WorkflowState,
        node_config: Dict[str, Any],
        execution_id: int,
        previous_context: str = "",
        output_schema: str = "",
        task_instructions: str = "",
        tools: List[Any] = None
    ):
        """
        Initialize research orchestrator.
        
        Args:
            config: Research configuration from node
            state: Workflow state
            node_config: Full node configuration
            execution_id: Execution ID for memory
            previous_context: Formatted deliverables from previous agents
            output_schema: Expected output format/schema for the research
            task_instructions: Specific task instructions for the research
            tools: Optional list of tool instances (if None, loads from registry)
        """
        self.config = config
        self.state = state
        self.node_config = node_config
        self.execution_id = execution_id
        
        # Context from previous agents and expected output format
        self.previous_context = previous_context
        self.output_schema = output_schema
        self.task_instructions = task_instructions
        
        # Extract configuration
        self.max_iterations = config.get("maxIterations", 1)
        self.min_subagents = config.get("minSubagents", 1)
        self.max_subagents = config.get("maxSubagents", 10)
        self.enable_citations = config.get("enableCitations", True)
        
        # LLM configuration - use centralized config
        from config.llm_config import LLMConfig
        self.model_provider = node_config.get("modelProvider", LLMConfig.DEFAULT_PROVIDER)
        self.model_name = node_config.get("modelName", LLMConfig.DEFAULT_MODEL)
        self.temperature = node_config.get("temperature", LLMConfig.DEFAULT_TEMPERATURE)
        
        # Initialize components
        self.memory = ResearchMemory(execution_id)
        self.subagent_executor = SubagentExecutor(
            model_provider=self.model_provider,
            model_name=self.model_name,
            temperature=self.temperature
        )
        self.citation_processor = CitationProcessor(model_name=self.model_name)
        
        # Get tools (use provided tools or load from registry)
        if tools is not None:
            self.tools = tools
            logger.debug("Using %d tool(s) provided to orchestrator", len(tools))
        else:
            tool_names = node_config.get("tools", ["web_search"])
            tool_registry = get_tool_registry()
            self.tools = tool_registry.get_tools_by_names(tool_names)
            logger.debug("Loaded %d tool(s) from registry", len(self.tools))
        
        logger.debug(
            "Initialized ResearchOrchestrator (execution_id=%d, max_iterations=%d, subagents=%d-%d)",
            execution_id,
            self.max_iterations,
            self.min_subagents,
            self.max_subagents
        )
        logger.debug("📥 Previous context provided: %s chars", len(previous_context))
        logger.debug("📋 Output schema provided: %s", "Yes" if output_schema else "No")
        logger.debug("📋 Task instructions provided: %s", "Yes" if task_instructions else "No")
    
    async def run(self, query: str) -> Dict[str, Any]:
        """
        Run the full research orchestration loop.
        
        Args:
            query: Research query from user
            
        Returns:
            Result dictionary containing:
                - final_report: Comprehensive research report with citations
                - iterations: Number of iterations completed
                - num_subagents: Total subagents used
                - sources_count: Number of unique sources
                - metadata: Additional metadata
        """
        logger.info("Starting research orchestration for query: %s", query[:100])
        
        iteration = 0
        all_subagent_results = []
        synthesis = ""
        
        try:
            while iteration < self.max_iterations:
                iteration += 1
                logger.debug("=" * 60)
                logger.debug("ITERATION %d / %d", iteration, self.max_iterations)
                logger.debug("=" * 60)
                
                # STEP 1: Create research plan
                plan = await self.create_research_plan(query, iteration, synthesis)
                await self.memory.save_plan(plan)
                
                # STEP 2: Decide subagents needed
                subagent_specs = await self.decide_subagents(plan, query, iteration)
                
                if not subagent_specs:
                    logger.warning("No subagents generated, stopping iteration")
                    break
                
                # STEP 3: Execute subagents in parallel
                logger.debug("Executing %d subagents in parallel", len(subagent_specs))
                results = await self.execute_subagents_parallel(subagent_specs)
                
                # Store results
                all_subagent_results.extend(results)
                
                # Save findings to memory
                for result in results:
                    await self.memory.append_finding(result)
                    
                    # Add sources to memory
                    if result.get("sources"):
                        await self.memory.add_sources(result["sources"])
                
                # STEP 4: Synthesize findings
                synthesis = await self.synthesize_findings(
                    results,
                    query,
                    iteration,
                    all_subagent_results
                )
                
                logger.debug("Synthesis length: %d chars", len(synthesis))
                
                # STEP 5: Evaluate completeness
                is_complete = await self.evaluate_completeness(synthesis, query, iteration)
                
                # Record iteration
                await self.memory.record_iteration({
                    "iteration_number": iteration,
                    "subagents_spawned": len(subagent_specs),
                    "synthesis_length": len(synthesis),
                    "is_complete": is_complete
                })
                
                if is_complete:
                    logger.info("Research deemed complete after %d iterations", iteration)
                    break
                
                logger.debug("Research incomplete, continuing to iteration %d", iteration + 1)
            
            # STEP 6: Add citations (if enabled)
            if self.enable_citations and all_subagent_results:
                logger.debug("🔖 Adding citations to final report (enableCitations=%s)", self.enable_citations)
                logger.debug("📊 Synthesis before citations: %d chars", len(synthesis))
                final_report = await self.citation_processor.process(
                    synthesis,
                    all_subagent_results
                )
                logger.debug("📊 Final report after citations: %d chars", len(final_report))
                logger.debug("📄 Final report preview (first 500 chars):\n%s", final_report[:500])
                logger.debug("📄 Final report ending (last 500 chars):\n%s", final_report[-500:])
            else:
                logger.warning("⚠️  Citations DISABLED or no subagent results (enableCitations=%s, results=%d)", 
                             self.enable_citations, len(all_subagent_results))
                final_report = synthesis
            
            # Get all sources
            all_sources = await self.memory.get_all_sources()
            
            # STEP 7: Format as structured deliverable (chat + outputDeliverable)
            structured_output = await self._format_as_deliverable(
                final_report,
                query,
                all_sources
            )
            
            # Create result
            result = {
                "final_report": final_report,
                "structured_output": structured_output,  # {"chat": "...", "outputDeliverable": {...}}
                "iterations": iteration,
                "num_subagents": len(all_subagent_results),
                "sources_count": len(all_sources),
                "metadata": create_research_summary(
                    query,
                    len(all_subagent_results),
                    iteration,
                    len(all_sources)
                )
            }
            
            logger.info(
                "Research complete: %d iterations, %d subagents, %d sources",
                iteration,
                len(all_subagent_results),
                len(all_sources)
            )
            
            return result
            
        except Exception as e:
            logger.error("Research orchestration failed: %s", e, exc_info=True)
            
            # Return partial results if available
            if synthesis:
                return {
                    "final_report": synthesis,
                    "iterations": iteration,
                    "num_subagents": len(all_subagent_results),
                    "sources_count": 0,
                    "error": str(e),
                    "metadata": {"error": True}
                }
            
            raise
    
    @observe(name="research_create_plan")
    async def create_research_plan(
        self,
        query: str,
        iteration: int,
        previous_synthesis: str = ""
    ) -> Dict[str, Any]:
        """
        Create research plan for current iteration.
        
        Uses LLM to analyze query and create strategy.
        Includes context from previous agents and expected output format.
        
        Args:
            query: Original research query
            iteration: Current iteration number
            previous_synthesis: Synthesis from previous iteration (if any)
            
        Returns:
            Research plan dictionary
        """
        logger.debug("Creating research plan for iteration %d", iteration)
        
        llm = self._get_llm()
        
        # Build context sections
        context_section = ""
        if self.previous_context:
            context_section = f"""
## CONTEXT FROM PREVIOUS WORKFLOW STEPS
The following information has been provided from earlier steps in the workflow.
USE THIS AS YOUR FOUNDATION - do NOT research topics already covered here:

{self.previous_context}
---
"""
        
        task_section = ""
        if self.task_instructions:
            task_section = f"""
## YOUR SPECIFIC TASK
{self.task_instructions}
---
"""
        
        output_section = ""
        if self.output_schema:
            output_section = f"""
## EXPECTED OUTPUT FORMAT
Your research must ultimately produce output that matches this schema:
```json
{self.output_schema}
```
Plan your research to gather information for ALL required fields.
---
"""
        
        if iteration == 1:
            # First iteration - create initial plan with full context
            prompt = f"""You are a research planner. Create a research strategy with SPECIFIC search topics.

{context_section}
{task_section}
{output_section}

## USER'S REQUEST
{query}

## YOUR TASK
Create a research plan with:

1. **RESEARCH TOPICS** (3-8 specific topics to search)
   - Each topic should be specific enough to become a search query
   - Focus on topics NOT already covered in the context above
   - Topics should help fill the target output format

2. **SEARCH STRATEGY**
   - What specific keywords/phrases to search
   - What types of sources to prioritize (news, academic, industry reports)
   
3. **COMPLEXITY**: simple / medium / complex

4. **RECOMMENDED SUBAGENTS**: {self.min_subagents}-{self.max_subagents}

IMPORTANT:
- If previous context exists, DO NOT research those topics again
- Be SPECIFIC - "AI agent frameworks comparison 2024" not "AI information"
- Each topic should directly contribute to answering the user's query

Output your research plan:"""
        else:
            # Subsequent iterations - identify gaps and create specific search queries
            prompt = f"""You are a research planner. Iteration {iteration - 1} is complete. Identify gaps and plan additional searches.

{context_section}
{task_section}
{output_section}

## ORIGINAL USER REQUEST
{query}

## CURRENT RESEARCH (from previous iteration)
{previous_synthesis[:3000]}

## YOUR TASK
Analyze what's MISSING and create SPECIFIC search topics:

1. **GAPS IDENTIFIED**
   - What questions remain unanswered?
   - What fields in the target output format are still empty?

2. **ADDITIONAL SEARCH TOPICS** (be specific!)
   - List 2-5 specific search queries to fill the gaps
   - Each should be directly searchable (not vague)

3. **RECOMMENDED SUBAGENTS**: {self.min_subagents}-{self.max_subagents}

If research is COMPLETE and all required information is gathered, say "RESEARCH COMPLETE".

Output your gap analysis:"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            plan = {
                "iteration": iteration,
                "query": query,
                "strategy": response.content,
                "timestamp": "now"
            }
            
            logger.debug("Created research plan: %s", response.content[:200])
            
            return plan
            
        except Exception as e:
            logger.error("Failed to create research plan: %s", e)
            # Return minimal plan
            return {
                "iteration": iteration,
                "query": query,
                "strategy": "Continue research with available information",
                "error": str(e)
            }
    
    @observe(name="research_decide_subagents")
    async def decide_subagents(
        self,
        plan: Dict[str, Any],
        query: str,
        iteration: int
    ) -> List[Dict[str, Any]]:
        """
        Decide how many subagents to create and what they should research.
        
        Dynamically determines based on query complexity.
        Includes context from previous agents to avoid duplicate research.
        
        Args:
            plan: Research plan from create_research_plan
            query: Original query
            iteration: Current iteration
            
        Returns:
            List of subagent specifications
        """
        logger.debug("Deciding subagents for iteration %d", iteration)
        
        llm = self._get_llm()
        
        # Build context sections
        context_section = ""
        if self.previous_context:
            context_section = f"""
## ALREADY AVAILABLE CONTEXT (DO NOT RESEARCH THESE TOPICS)
{self.previous_context[:2000]}
---
"""
        
        output_section = ""
        if self.output_schema:
            output_section = f"""
## TARGET OUTPUT FORMAT
Research should gather data for this schema:
```json
{self.output_schema}
```
Assign subagent tasks that will fill in each required field.
---
"""
        
        task_section = ""
        if self.task_instructions:
            task_section = f"""
## SPECIFIC TASK REQUIREMENTS
{self.task_instructions}
---
"""
        
        prompt = f"""You are a research coordinator. Create specific search queries for parallel research subagents.

{context_section}
{task_section}
{output_section}

## USER'S RESEARCH QUERY
{query}

## RESEARCH PLAN
{plan.get('strategy', '')}

## YOUR TASK
Create between {self.min_subagents} and {self.max_subagents} SPECIFIC SEARCH QUERIES for subagents.

IMPORTANT - Each task must be a SPECIFIC, ACTIONABLE search query that:
1. Can be directly used as a web search query
2. Is focused on ONE specific aspect
3. Avoids generic terms - use specific keywords
4. Does NOT duplicate topics already covered in context above
5. Helps gather data for the target output format

BAD examples (too vague):
- "Research AI benefits"
- "Find information about technology"

GOOD examples (specific, searchable):
- "GPT-4 vs Claude 3 performance benchmarks 2024"
- "Enterprise AI agent deployment best practices"
- "LangChain vs AutoGen framework comparison"

Output format (one per line):
TASK 1: [Specific search query]
TASK 2: [Specific search query]
etc.

Output your search queries:"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            # Parse response into task specs
            tasks = self._parse_subagent_tasks(response.content, iteration)
            
            # Ensure within bounds
            if len(tasks) < self.min_subagents:
                logger.warning(
                    "Only %d tasks generated, minimum is %d",
                    len(tasks),
                    self.min_subagents
                )
            elif len(tasks) > self.max_subagents:
                logger.warning(
                    "Too many tasks (%d), limiting to %d",
                    len(tasks),
                    self.max_subagents
                )
                tasks = tasks[:self.max_subagents]
            
            logger.debug("Generated %d subagent tasks", len(tasks))
            
            return tasks
            
        except Exception as e:
            logger.error("Failed to decide subagents: %s", e)
            # Fallback: create default tasks
            return self._create_default_subagent_tasks(query, iteration)
    
    def _parse_subagent_tasks(
        self,
        response_text: str,
        iteration: int
    ) -> List[Dict[str, Any]]:
        """
        Parse LLM response into subagent task specifications.
        
        Subagents receive ONLY their specific task - no full context.
        The orchestrator keeps context for planning and synthesis.
        (Following Anthropic/Gemini pattern)
        
        Args:
            response_text: LLM response
            iteration: Current iteration
            
        Returns:
            List of task specifications (minimal, focused tasks)
        """
        import re
        
        tasks = []
        
        # Find lines that look like "TASK N: description"
        pattern = r'TASK\s+\d+:\s*(.+)'
        matches = re.findall(pattern, response_text, re.IGNORECASE)
        
        # Subagents get ONLY their specific task - no context overload
        # The orchestrator already used context to create these focused tasks
        for i, task_description in enumerate(matches, 1):
            tasks.append({
                "id": f"subagent_{iteration}_{i}",
                "task": task_description.strip(),
                "focus": "",
                "iteration": iteration
                # NO context passed - subagents just execute their specific query
            })
        
        return tasks
    
    def _create_default_subagent_tasks(
        self,
        query: str,
        iteration: int
    ) -> List[Dict[str, Any]]:
        """
        Create default subagent tasks as fallback.
        
        Subagents receive ONLY their specific task - minimal, focused queries.
        (Following Anthropic/Gemini pattern)
        
        Args:
            query: Research query
            iteration: Current iteration
            
        Returns:
            List of default tasks (minimal, no context overload)
        """
        logger.debug("Creating default subagent tasks")
        
        # Create generic research aspects
        aspects = [
            "Research background and context",
            "Research current state and recent developments",
            "Research expert opinions and analysis",
        ]
        
        # Subagents get ONLY their specific task - no context
        tasks = []
        for i, aspect in enumerate(aspects[:self.min_subagents], 1):
            tasks.append({
                "id": f"subagent_{iteration}_{i}",
                "task": f"{aspect} for: {query}",
                "focus": aspect,
                "iteration": iteration
                # NO context - subagents just execute their specific query
            })
        
        return tasks
    
    async def execute_subagents_parallel(
        self,
        subagent_specs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute multiple subagents in parallel.
        
        Args:
            subagent_specs: List of subagent task specifications
            
        Returns:
            List of results from all subagents
        """
        logger.info("Executing %d subagents in parallel", len(subagent_specs))
        
        # Create tasks for parallel execution
        tasks = [
            self.subagent_executor.execute(spec, self.tools, max_iterations=10)
            for spec in subagent_specs
        ]
        
        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and log them
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Subagent %s failed: %s",
                    subagent_specs[i].get("id", "unknown"),
                    result
                )
            else:
                valid_results.append(result)
        
        logger.debug(
            "Parallel execution complete: %d/%d successful",
            len(valid_results),
            len(subagent_specs)
        )
        
        return valid_results
    
    @observe(name="research_synthesize_findings")
    async def synthesize_findings(
        self,
        current_results: List[Dict[str, Any]],
        query: str,
        iteration: int,
        all_results: List[Dict[str, Any]]
    ) -> str:
        """
        Synthesize findings from subagents.
        
        Includes context from previous agents and expected output format.
        
        Args:
            current_results: Results from current iteration
            query: Original query
            iteration: Current iteration number
            all_results: All results from all iterations
            
        Returns:
            Synthesized research report
        """
        logger.debug(
            "Synthesizing findings from %d current + %d total subagents",
            len(current_results),
            len(all_results)
        )
        
        llm = self._get_llm()
        
        # Build findings text
        findings_text = self._format_findings_for_synthesis(current_results)
        
        # Build context sections
        context_section = ""
        if self.previous_context:
            context_section = f"""
## CONTEXT FROM PREVIOUS WORKFLOW STEPS
Incorporate this existing context into your synthesis:
{self.previous_context[:2000]}
---
"""
        
        output_section = ""
        if self.output_schema:
            output_section = f"""
## TARGET OUTPUT FORMAT
Structure your synthesis to provide information for this schema:
```json
{self.output_schema}
```
Ensure your report addresses ALL fields in this schema.
---
"""
        
        task_section = ""
        if self.task_instructions:
            task_section = f"""
## SPECIFIC REQUIREMENTS
{self.task_instructions}
---
"""
        
        # Check if this is multi-iteration
        if iteration > 1 and len(all_results) > len(current_results):
            previous_findings = self._format_findings_for_synthesis(
                [r for r in all_results if r not in current_results]
            )
            
            prompt = f"""You are a research synthesizer. Combine and synthesize research findings into a comprehensive report.

{context_section}
{task_section}
{output_section}

## ORIGINAL QUERY
{query}

## ITERATION {iteration} FINDINGS
{findings_text}

## PREVIOUS ITERATIONS FINDINGS
{previous_findings[:3000]}

## YOUR TASK
Create a comprehensive, well-structured research report that:
1. Integrates all findings coherently (including context from previous workflow steps)
2. Highlights key insights and patterns
3. Addresses the original query thoroughly
4. Uses clear sections and organization
5. Maintains factual accuracy
6. Provides information for ALL fields in the target output format

Output the synthesized research report:"""
        else:
            prompt = f"""You are a research synthesizer. Combine research findings into a comprehensive report.

{context_section}
{task_section}
{output_section}

## RESEARCH QUERY
{query}

## FINDINGS FROM {len(current_results)} RESEARCH SUBAGENTS
{findings_text}

## YOUR TASK
Create a comprehensive, well-structured research report that:
1. Integrates all findings coherently (including any context from previous workflow steps)
2. Highlights key insights
3. Addresses the query thoroughly
4. Uses clear sections
5. Maintains factual accuracy
6. Provides information for ALL fields in the target output format (if specified)

Output the synthesized research report:"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            synthesis = response.content
            
            logger.info("Synthesis complete: %d characters", len(synthesis))
            
            return synthesis
            
        except Exception as e:
            logger.error("Failed to synthesize findings: %s", e)
            # Fallback: concatenate findings
            return self._create_fallback_synthesis(current_results, query)
    
    def _format_findings_for_synthesis(
        self,
        results: List[Dict[str, Any]]
    ) -> str:
        """
        Format subagent results for synthesis prompt.
        
        Args:
            results: List of subagent results
            
        Returns:
            Formatted findings text
        """
        formatted = []
        
        for i, result in enumerate(results, 1):
            formatted.append(f"--- Subagent {i}: {result.get('task', 'Unknown')} ---")
            formatted.append(result.get("findings", "No findings")[:2000])
            formatted.append("")
        
        return "\n".join(formatted)
    
    def _create_fallback_synthesis(
        self,
        results: List[Dict[str, Any]],
        query: str
    ) -> str:
        """
        Create simple fallback synthesis if LLM fails.
        
        Args:
            results: Subagent results
            query: Original query
            
        Returns:
            Simple concatenated synthesis
        """
        logger.debug("Creating fallback synthesis")
        
        parts = [f"# Research Report: {query}", ""]
        
        for i, result in enumerate(results, 1):
            parts.append(f"## Finding {i}: {result.get('task', 'Research')}")
            parts.append(result.get("findings", "No findings available"))
            parts.append("")
        
        return "\n".join(parts)
    
    @observe(name="research_evaluate_completeness")
    async def evaluate_completeness(
        self,
        synthesis: str,
        query: str,
        iteration: int
    ) -> bool:
        """
        Evaluate if research is complete.
        
        Args:
            synthesis: Current synthesis
            query: Original query
            iteration: Current iteration
            
        Returns:
            True if research is complete, False if more iteration needed
        """
        logger.debug("Evaluating research completeness (iteration %d)", iteration)
        
        # Always stop at max iterations
        if iteration >= self.max_iterations:
            logger.info("Max iterations reached, marking complete")
            return True
        
        # If synthesis is very short, continue
        if len(synthesis) < 500:
            logger.debug("Synthesis too short (%d chars), continuing", len(synthesis))
            return False
        
        llm = self._get_llm()
        
        prompt = f"""You are a research evaluator. Assess if this research adequately answers the query.

Query: {query}

Current Research Report:
{synthesis[:3000]}

Questions:
1. Does this report comprehensively address the query?
2. Are there significant gaps or missing information?
3. Would additional research significantly improve the answer?

Output ONLY one word:
- "COMPLETE" if research is comprehensive
- "CONTINUE" if more research would help

Your assessment:"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            decision = _extract_text_content(response.content).upper()
            
            is_complete = "COMPLETE" in decision
            
            logger.debug("Evaluation decision: %s (complete=%s)", decision, is_complete)
            
            return is_complete
            
        except Exception as e:
            logger.error("Failed to evaluate completeness: %s", e)
            # Default: continue if not max iterations
            return iteration >= self.max_iterations
    
    def _get_llm(self) -> Any:
        """
        Get LLM instance for orchestrator using centralized client manager.
        
        Returns:
            LLM instance
        """
        from app.config.llm_config import LLMClientManager
        return LLMClientManager.get_client(
            provider=self.model_provider,
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=64000
        )
    
    @observe(name="research_format_deliverable")
    async def _format_as_deliverable(
        self,
        final_report: str,
        query: str,
        sources: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Format research output as structured deliverable (chat + outputDeliverable).
        
        Similar to multi-agent mode output format.
        
        Args:
            final_report: The synthesized research report
            query: Original research query
            sources: List of sources used
            
        Returns:
            Dictionary with 'chat' and 'outputDeliverable' keys
        """
        logger.info("Formatting research output as structured deliverable")
        
        llm = self._get_llm()
        
        # Build the prompt based on whether outputSchema is provided
        if self.output_schema:
            prompt = f"""You are formatting research findings into a structured deliverable.

## RESEARCH QUERY
{query}

## RESEARCH FINDINGS
{final_report[:8000]}

## REQUIRED OUTPUT FORMAT
You must output JSON with this EXACT structure:
```json
{{
  "chat": "A brief summary message explaining what was researched and key findings (2-3 sentences)",
  "outputDeliverable": {self.output_schema}
}}
```

IMPORTANT:
- The "chat" field should be a brief, conversational summary
- The "outputDeliverable" field MUST match the schema exactly
- Extract relevant information from the research to fill each field
- If information for a field wasn't found, use null or empty string
- Include source URLs where relevant

Output ONLY valid JSON, no other text:"""
        else:
            # Default schema if none provided
            prompt = f"""You are formatting research findings into a structured deliverable.

## RESEARCH QUERY
{query}

## RESEARCH FINDINGS
{final_report[:8000]}

## REQUIRED OUTPUT FORMAT
Output JSON with this structure:
```json
{{
  "chat": "A brief summary message explaining what was researched and key findings (2-3 sentences)",
  "outputDeliverable": {{
    "summary": "Executive summary of research findings",
    "key_findings": ["finding 1", "finding 2", ...],
    "details": "Detailed research report",
    "sources": ["url1", "url2", ...]
  }}
}}
```

Output ONLY valid JSON, no other text:"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = _extract_text_content(response.content)
            
            # Try to parse as JSON
            import json
            
            # Remove markdown code blocks if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            
            parsed = json.loads(content)
            
            # Validate structure
            if "chat" in parsed and "outputDeliverable" in parsed:
                logger.info("✅ Successfully formatted as structured deliverable")
                return parsed
            else:
                # Wrap in expected format
                logger.warning("Response missing expected fields, wrapping")
                return {
                    "chat": "Research completed. See deliverable for details.",
                    "outputDeliverable": parsed
                }
                
        except json.JSONDecodeError as e:
            logger.error("Failed to parse deliverable JSON: %s", e)
            # Fallback: return report as-is in expected format
            return {
                "chat": f"Research completed for: {query[:100]}",
                "outputDeliverable": {
                    "summary": final_report[:500],
                    "details": final_report,
                    "sources": [s.get("url", "") for s in sources[:10] if s.get("url")]
                }
            }
        except Exception as e:
            logger.error("Failed to format as deliverable: %s", e)
            return {
                "chat": f"Research completed for: {query[:100]}",
                "outputDeliverable": {
                    "report": final_report,
                    "error": str(e)
                }
            }

