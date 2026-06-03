"""
Google Custom Search API tool - Highest quality results.

Get API key: https://developers.google.com/custom-search
Free: 100 searches/day, Paid: $5/1000 searches
"""

from typing import Optional, Type
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun
import logging
import os
from googleapiclient.discovery import build
from config.keyvault import cfg
logger = logging.getLogger(__name__)


class GoogleSearchInput(BaseModel):
    """Input schema for Google search tool."""
    query: str = Field(description="The search query")
    num_results: int = Field(default=10, description="Number of results to return (1-10)")


class GoogleSearchTool(BaseTool):
    """
    Google Custom Search API - Highest quality search results.
    
    Setup:
    1. Get API key: https://developers.google.com/custom-search/v1/overview
    2. Create custom search engine: https://programmablesearchengine.google.com/
    3. Set environment variables:
       - GOOGLE_API_KEY
       - GOOGLE_CSE_ID
    """
    
    name: str = "web_search"
    description: str = (
        "Search the web using Google Custom Search API. "
        "Returns the highest quality, most relevant search results. "
        "Use this when you need authoritative, accurate information from the web."
    )
    args_schema: Type[BaseModel] = GoogleSearchInput
    
    def _run(
        self,
        query: str,
        num_results: int = 10,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """
        Execute web search using Google Custom Search API.
        
        Args:
            query: Search query
            num_results: Number of results to return (1-10, default 10)
            run_manager: Callback manager
            
        Returns:
            Search results as formatted string
        """
        try:
            
            
            api_key = cfg.GOOGLE_API_KEY
            cse_id = cfg.GOOGLE_CSE_ID
            
            if not api_key or not cse_id:
                return (
                    "❌ Google Search credentials not found. "
                    "Please set GOOGLE_API_KEY and GOOGLE_CSE_ID environment variables. "
                    "Get credentials at: https://developers.google.com/custom-search"
                )
            
            logger.debug("🔍 Google Search: %s (num_results=%d)", query, num_results)
            
            # Build service
            service = build("customsearch", "v1", developerKey=api_key)
            
            # Perform search
            result = service.cse().list(
                q=query,
                cx=cse_id,
                num=min(num_results, 10)
            ).execute()
            
            if 'items' not in result:
                return f"No results found for '{query}'."
            
            # Format results
            formatted = f"🔍 Google Search results for '{query}':\n\n"
            
            for i, item in enumerate(result['items'], 1):
                title = item.get('title', 'No title')
                snippet = item.get('snippet', 'No description')
                link = item.get('link', 'No URL')
                
                formatted += f"{i}. {title}\n"
                formatted += f"   {snippet}\n"
                formatted += f"   URL: {link}\n\n"
            
            logger.debug("✅ Found %d results from Google", len(result['items']))
            return formatted
            
        except ImportError:
            error_msg = (
                "Google API client not installed. "
                "Install it with: pip install google-api-python-client"
            )
            logger.error(error_msg)
            return f"Error: {error_msg}"
            
        except Exception as e:
            logger.error("Google search error: %s", e)
            return f"Error performing search: {str(e)}"
    
    async def _arun(
        self,
        query: str,
        num_results: int = 10,
        run_manager: Optional[CallbackManagerForToolRun] = None
    ) -> str:
        """Async execution of Google search."""
        return self._run(query, num_results, run_manager)

