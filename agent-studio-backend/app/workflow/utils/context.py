"""
System context utilities for enriching LLM prompts.

Provides dynamic, server-side context like current date/time, timezone info,
and other system information to make LLM responses more accurate and time-aware.
"""

from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def build_system_context(
    user_timezone: Optional[str] = None,
    include_extended_info: bool = False
) -> str:
    """
    Build system context for LLM prompts.
    
    This provides the LLM with current date/time information so it can:
    - Give accurate time-aware responses
    - Reference current events correctly
    - Understand temporal context
    
    Args:
        user_timezone: Optional user timezone (e.g., "America/New_York")
        include_extended_info: Include additional context (day of year, etc.)
        
    Returns:
        Formatted context string ready to inject into system prompts
        
    Example:
        >>> context = build_system_context("America/New_York")
        >>> print(context)
        ## Current System Information
        
        **Date & Time:**
        - Current Date: Monday, October 20, 2025
        - Current UTC Time: 12:30:45 UTC
        - User Local Time: 08:30:45 EDT
        ...
    """
    now = datetime.now(timezone.utc)
    
    # Build base context
    context_lines = [
        "## Current System Information",
        "",
        "**Date & Time:**",
        f"- Current Date: {now.strftime('%A, %B %d, %Y')}",
        f"- Current UTC Time: {now.strftime('%H:%M:%S UTC')}",
        f"- Day of Week: {now.strftime('%A')}",
        f"- Month: {now.strftime('%B')}",
        f"- Year: {now.year}",
    ]
    
    # Add user's local time if timezone provided
    if user_timezone:
        try:
            import pytz
            user_tz = pytz.timezone(user_timezone)
            local_time = now.astimezone(user_tz)
            context_lines.append(
                f"- User Local Time: {local_time.strftime('%I:%M:%S %p %Z')} ({user_timezone})"
            )
            logger.debug(f"Added user timezone context: {user_timezone}")
        except Exception as e:
            logger.warning(f"Failed to parse user timezone '{user_timezone}': {e}")
    
    # Add extended info if requested
    if include_extended_info:
        context_lines.extend([
            f"- Day of Year: {now.timetuple().tm_yday}",
            f"- Week of Year: {now.isocalendar()[1]}",
            f"- Quarter: Q{(now.month-1)//3 + 1}",
        ])
    
    context_lines.extend([
        "",
        "**Important:** Use this date/time information to provide accurate, time-aware responses.",
        "When users ask about \"today\", \"this year\", \"current events\", etc., refer to this context.",
    ])
    
    return "\n".join(context_lines)


def enrich_system_prompt(
    base_prompt: str,
    user_timezone: Optional[str] = None,
    include_extended_info: bool = False
) -> str:
    """
    Enrich a system prompt with current date/time context.
    
    Takes any existing system prompt and adds temporal context to it.
    
    Args:
        base_prompt: Original system prompt (e.g., "You are a helpful assistant.")
        user_timezone: Optional user timezone
        include_extended_info: Include extended temporal info
        
    Returns:
        Enriched prompt with system context appended
        
    Example:
        >>> original = "You are a helpful research assistant."
        >>> enriched = enrich_system_prompt(original, "America/New_York")
        >>> # Now contains both original prompt + date/time context
    """
    if not base_prompt or not base_prompt.strip():
        base_prompt = "You are a helpful AI assistant."
    
    context = build_system_context(user_timezone, include_extended_info)
    
    # Combine original prompt with context
    enriched = f"""{base_prompt.strip()}

{context}"""
    
    logger.debug(f"Enriched system prompt with context (timezone: {user_timezone or 'UTC'})")
    
    return enriched


def get_current_date_simple() -> str:
    """
    Get simple date string for quick injection.
    
    Returns:
        Date string like "Monday, October 20, 2025"
    """
    now = datetime.now(timezone.utc)
    return now.strftime('%A, %B %d, %Y')


def get_current_datetime_iso() -> str:
    """
    Get ISO 8601 formatted datetime string.
    
    Returns:
        ISO datetime string like "2025-10-20T12:30:45Z"
    """
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%SZ')


# Convenience function for quick access
def add_date_to_prompt(prompt: str) -> str:
    """
    Quick helper to add just the current date to a prompt.
    
    Args:
        prompt: Original prompt
        
    Returns:
        Prompt with date prepended
    """
    date = get_current_date_simple()
    return f"Today is {date}.\n\n{prompt}"

