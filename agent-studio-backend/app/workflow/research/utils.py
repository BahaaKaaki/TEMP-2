"""
Utility functions for research module.
"""

import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract URLs from text.
    
    Args:
        text: Text to extract URLs from
        
    Returns:
        List of unique URLs found
    """
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
    urls = re.findall(url_pattern, text)
    return list(set(urls))


def extract_sources_from_messages(messages: List[Any]) -> List[Dict[str, str]]:
    """
    Extract source URLs from LangChain messages.
    
    Args:
        messages: List of LangChain messages (including ToolMessages)
        
    Returns:
        List of source dictionaries with url and title
    """
    from langchain_core.messages import ToolMessage
    
    sources = []
    seen_urls = set()
    
    for message in messages:
        if isinstance(message, ToolMessage):
            # Extract URLs from tool results
            content = str(message.content)
            urls = extract_urls_from_text(content)
            
            for url in urls:
                if url not in seen_urls:
                    seen_urls.add(url)
                    
                    # Try to extract title from context
                    title = extract_title_near_url(content, url)
                    
                    sources.append({
                        "url": url,
                        "title": title or urlparse(url).netloc
                    })
    
    return sources


def extract_title_near_url(text: str, url: str) -> Optional[str]:
    """
    Extract title that appears near a URL in text.
    
    Args:
        text: Text containing the URL
        url: URL to find title for
        
    Returns:
        Title if found, None otherwise
    """
    # Find the URL position
    url_pos = text.find(url)
    if url_pos == -1:
        return None
    
    # Look backwards for a line that looks like a title
    # Typically format is: "N. Title\n   Description\n   URL: ..."
    before_url = text[:url_pos]
    lines = before_url.split('\n')
    
    # Check last few lines before URL
    for line in reversed(lines[-5:]):
        line = line.strip()
        # Skip empty lines and lines that are just URLs
        if not line or line.startswith('http'):
            continue
        # Skip lines that look like descriptions (too long)
        if len(line) > 100:
            continue
        # This looks like a title
        if len(line) > 10:
            # Remove leading numbers like "1. "
            title = re.sub(r'^\d+\.\s*', '', line)
            return title
    
    return None


def format_sources_list(sources: List[Dict[str, str]]) -> str:
    """
    Format sources list for display or prompts.
    
    Args:
        sources: List of source dictionaries
        
    Returns:
        Formatted string with numbered sources
    """
    if not sources:
        return "No sources available."
    
    formatted = []
    for i, source in enumerate(sources, 1):
        formatted.append(f"[{i}] {source['title']}\n    {source['url']}")
    
    return "\n\n".join(formatted)


def truncate_text(text: str, max_length: int = 1000, suffix: str = "...") -> str:
    """
    Truncate text to maximum length.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def estimate_tokens(text: str) -> int:
    """
    Rough estimate of tokens in text.
    
    Uses simple heuristic: ~4 characters per token for English text.
    
    Args:
        text: Text to estimate
        
    Returns:
        Estimated token count
    """
    return len(text) // 4


def create_research_summary(
    query: str,
    num_subagents: int,
    iterations: int,
    sources_count: int
) -> Dict[str, Any]:
    """
    Create metadata summary for research execution.
    
    Args:
        query: Original research query
        num_subagents: Total subagents used
        iterations: Number of iterations
        sources_count: Number of unique sources found
        
    Returns:
        Metadata dictionary
    """
    return {
        "query": query,
        "total_subagents": num_subagents,
        "iterations_completed": iterations,
        "unique_sources": sources_count,
        "research_type": "deep" if num_subagents >= 5 else "standard"
    }

