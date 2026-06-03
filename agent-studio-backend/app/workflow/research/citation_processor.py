"""
Citation processor for adding citations to research findings.

Final step in Anthropic's research pipeline - adds proper citations and
source references to the synthesized research report.
"""

import logging
from typing import Dict, List, Any, Optional
from langchain_core.messages import HumanMessage
# from langfuse import observe  # DISABLED
from utils.langfuse_config import observe  # No-op decorator

from .utils import format_sources_list

logger = logging.getLogger(__name__)


class CitationProcessor:
    """
    Adds citations to research reports.
    
    Takes a synthesized research report and all findings with sources,
    then adds inline citations [1], [2], [3] and creates a Sources section.
    
    Follows academic citation standards.
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.3  # Lower for consistency
    ):
        """
        Initialize citation processor.
        
        Args:
            model_name: Model to use for citation processing
            temperature: Low temperature for consistent citations
        """
        from app.llm.registry import LlmModelRegistry
        self.model_name = model_name or LlmModelRegistry.get_primary("service.citation_processor")
        self.temperature = temperature
        
        logger.debug("Initialized CitationProcessor with model %s", self.model_name)
    
    @observe(name="citation_processor_add_citations")
    async def process(
        self,
        synthesis: str,
        all_findings: List[Dict[str, Any]]
    ) -> str:
        """
        Add citations to research synthesis.
        
        Args:
            synthesis: Synthesized research report (uncited)
            all_findings: List of all subagent findings with sources
            
        Returns:
            Research report with inline citations and Sources section
        """
        logger.info("📚 Processing citations for research report")
        logger.debug("📝 Input synthesis length: %d chars", len(synthesis))
        logger.debug("🔍 Number of findings to process: %d", len(all_findings))
        
        # Collect all unique sources
        all_sources = self._collect_all_sources(all_findings)
        
        if not all_sources:
            logger.warning("⚠️  No sources found, returning uncited synthesis")
            logger.warning("Debug - all_findings structure: %s", [list(f.keys()) for f in all_findings])
            return synthesis + "\n\n---\n\n*Note: No sources were available for citation.*"
        
        logger.debug("✅ Found %d unique sources for citation", len(all_sources))
        logger.debug("📎 Source URLs: %s", [s.get('url', 'NO_URL')[:50] for s in all_sources[:5]])
        
        # Build citation prompt
        prompt = self._build_citation_prompt(synthesis, all_sources)
        
        # Get LLM using centralized client manager
        from app.config.llm_config import LLMClientManager
        llm = LLMClientManager.get_client(
            provider="openai",
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=16000,
            binding_key="service.citation_processor",
            llm_role="citation_processor",
        )
        
        try:
            # Invoke citation agent
            logger.debug("Invoking citation agent")
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            cited_report = response.content
            
            logger.info("Successfully added citations to report")
            
            return cited_report
            
        except Exception as e:
            logger.error("Failed to process citations: %s", e)
            # Fallback: return original with sources appended
            return self._create_fallback_report(synthesis, all_sources)
    
    def _collect_all_sources(
        self,
        all_findings: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """
        Collect and deduplicate sources from all findings.
        
        Args:
            all_findings: List of finding dictionaries
            
        Returns:
            List of unique source dictionaries
        """
        seen_urls = set()
        unique_sources = []
        
        for finding in all_findings:
            sources = finding.get("sources", [])
            
            for source in sources:
                url = source.get("url", "")
                
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_sources.append(source)
        
        return unique_sources
    
    def _build_citation_prompt(
        self,
        synthesis: str,
        sources: List[Dict[str, str]]
    ) -> str:
        """
        Build prompt for citation agent.
        
        Args:
            synthesis: Research report to add citations to
            sources: Available sources
            
        Returns:
            Formatted prompt
        """
        formatted_sources = format_sources_list(sources)
        
        prompt = f"""You are a citation agent. Your task is to add proper citations to a research report.

RESEARCH REPORT (uncited):
{synthesis}

AVAILABLE SOURCES:
{formatted_sources}

INSTRUCTIONS:
1. Read the research report carefully
2. For each factual claim, statistic, or quoted information, add an inline citation [N]
3. Match claims to the most relevant source from the available sources
4. Multiple claims can cite the same source
5. Place citations immediately after the relevant statement, before punctuation
6. At the end, create a "## Sources" section listing all cited sources
7. Keep the original structure and content of the report intact
8. Only add citations - do not modify the content otherwise

EXAMPLE FORMAT:
Recent studies show that AI adoption increased by 45% in 2024 [1]. This trend is expected to continue [2].

## Sources

[1] AI Adoption Report 2024
    https://example.com/ai-report-2024

[2] Future of AI Analysis
    https://example.com/future-ai

Now, add proper citations to the research report above and output the complete cited report:"""
        
        return prompt
    
    def _create_fallback_report(
        self,
        synthesis: str,
        sources: List[Dict[str, str]]
    ) -> str:
        """
        Create fallback report if citation agent fails.
        
        Simply appends sources section to original synthesis.
        
        Args:
            synthesis: Original synthesis
            sources: List of sources
            
        Returns:
            Report with sources appended
        """
        logger.debug("Creating fallback report with sources appended")
        
        formatted_sources = format_sources_list(sources)
        
        fallback = f"""{synthesis}

---

## Sources

{formatted_sources}

*Note: Inline citations could not be added automatically. Please refer to the sources above.*"""
        
        return fallback
    
    async def validate_citations(
        self,
        cited_report: str,
        sources: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Validate that citations were added correctly.
        
        Args:
            cited_report: Report with citations
            sources: Available sources
            
        Returns:
            Validation results dictionary
        """
        import re
        
        # Extract citation numbers from report
        citation_pattern = r'\[(\d+)\]'
        cited_numbers = set(re.findall(citation_pattern, cited_report))
        
        # Check if Sources section exists
        has_sources_section = "## Sources" in cited_report or "## sources" in cited_report.lower()
        
        # Count citations
        citation_count = len(cited_numbers)
        
        # Validate citation range
        max_source_num = len(sources)
        invalid_citations = [
            int(n) for n in cited_numbers
            if int(n) < 1 or int(n) > max_source_num
        ]
        
        is_valid = (
            citation_count > 0 and
            has_sources_section and
            len(invalid_citations) == 0
        )
        
        validation = {
            "is_valid": is_valid,
            "citation_count": citation_count,
            "has_sources_section": has_sources_section,
            "invalid_citations": invalid_citations,
            "unique_sources_cited": len(cited_numbers)
        }
        
        logger.debug("Citation validation: %s", validation)
        
        return validation


