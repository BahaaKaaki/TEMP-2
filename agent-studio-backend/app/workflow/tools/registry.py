"""
Tool registry for managing available tools.

The registry maintains a collection of tools that can be used by
agent and tool nodes in workflows.
"""

from typing import Dict, Optional, Any, List
from langchain_core.tools import BaseTool
import logging

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry for workflow tools.
    
    Manages a collection of LangChain tools that can be used in workflows.
    """
    
    def __init__(self):
        """Initialize the tool registry."""
        self._tools: Dict[str, BaseTool] = {}
    
    def register_tool(self, name: str, tool: BaseTool) -> None:
        """
        Register a tool.
        
        Args:
            name: Tool name/identifier
            tool: LangChain tool instance
        """
        self._tools[name] = tool
        logger.debug("Registered tool: %s", name)
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """
        Get a tool by name.
        
        Args:
            name: Tool name
            
        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(name)
    
    def list_tools(self) -> List[str]:
        """
        List all registered tool names.
        
        Returns:
            List of tool names
        """
        return list(self._tools.keys())
    
    def get_tools_by_names(self, names: List[str]) -> List[BaseTool]:
        """
        Get multiple tools by their names.
        
        Args:
            names: List of tool names
            
        Returns:
            List of tool instances (skipping any not found)
        """
        tools = []
        for name in names:
            tool = self.get_tool(name)
            if tool:
                tools.append(tool)
            else:
                logger.warning("Tool not found: %s", name)
        return tools


# Global tool registry instance
_global_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """
    Get the global tool registry instance.
    
    Returns:
        Global ToolRegistry instance
    """
    global _global_registry
    
    if _global_registry is None:
        _global_registry = ToolRegistry()
        _initialize_default_tools(_global_registry)
    
    return _global_registry


def _initialize_default_tools(registry: ToolRegistry) -> None:
    """
    Initialize the registry with default tools.
    
    Args:
        registry: ToolRegistry to initialize
    """
    # Import and register default tools
    try:
        # Use Google Custom Search - highest quality results
        from .google_search import GoogleSearchTool
        registry.register_tool("web_search", GoogleSearchTool())
        logger.debug("✅ Registered Google Custom Search (premium quality)")
    except Exception as e:
        logger.error("Failed to register Google search tool: %s", e)
    
    try:
        from .calculator import CalculatorTool
        registry.register_tool("calculator", CalculatorTool())
    except Exception as e:
        logger.warning("Failed to register calculator tool: %s", e)
    
    try:
        from .deep_research import DeepResearchTool
        registry.register_tool("deep_research", DeepResearchTool())
        logger.debug("✅ Registered Deep Research tool (o3-deep-research)")
    except Exception as e:
        logger.warning("Failed to register deep research tool: %s", e)
    
    try:
        from .simple_web_search import SimpleWebSearchTool
        registry.register_tool("simple_web_search", SimpleWebSearchTool())
        logger.debug("✅ Registered Simple Web Search tool (OpenAI web_search_preview)")
    except Exception as e:
        logger.warning("Failed to register simple web search tool: %s", e)

    logger.debug("Initialized tool registry with %d tools", len(registry.list_tools()))


