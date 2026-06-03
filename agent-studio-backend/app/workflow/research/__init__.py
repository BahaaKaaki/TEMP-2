"""
Research module for Anthropic-style deep research mode.

This module implements an iterative, multi-agent research system inspired by
Anthropic's research orchestrator pattern. Key components:

- ResearchOrchestrator: Main control loop with iterative refinement
- SubagentExecutor: Executes individual research subagents with tool loops
- ResearchMemory: Persistent memory system using Redis
- CitationProcessor: Adds citations and source references to findings

Usage:
    from workflow.research import ResearchOrchestrator
    
    orchestrator = ResearchOrchestrator(config, state, execution_id)
    result = await orchestrator.run(query)
"""

from .orchestrator import ResearchOrchestrator
from .memory import ResearchMemory
from .subagent_executor import SubagentExecutor
from .citation_processor import CitationProcessor

__all__ = [
    "ResearchOrchestrator",
    "ResearchMemory",
    "SubagentExecutor",
    "CitationProcessor",
]


