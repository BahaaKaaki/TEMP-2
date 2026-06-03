"""
Smart text truncation with semantic boundaries.

Prevents context loss by truncating at natural boundaries (sentences, paragraphs)
instead of arbitrary character positions.
"""
import re
from typing import Optional


def truncate_at_sentence(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate text at the last complete sentence before max_length.
    
    Args:
        text: Text to truncate
        max_length: Maximum character length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text ending at a sentence boundary
        
    Examples:
        >>> truncate_at_sentence("Hello world. This is a test. More text.", 25)
        'Hello world. This is a test....'
    """
    if len(text) <= max_length:
        return text
    
    # Find last sentence boundary before max_length
    # Look for: period, exclamation, question mark followed by space or newline
    truncated = text[:max_length]
    
    # Find the last sentence-ending punctuation
    sentence_endings = [m.end() for m in re.finditer(r'[.!?]\s+', truncated)]
    
    if sentence_endings:
        # Truncate at the last sentence boundary
        last_sentence_end = sentence_endings[-1]
        return text[:last_sentence_end].rstrip() + suffix
    
    # If no sentence boundary found, look for paragraph or line break
    last_newline = truncated.rfind('\n\n')
    if last_newline > max_length * 0.5:  # Only use if it's not too far back
        return text[:last_newline].rstrip() + suffix
    
    last_single_newline = truncated.rfind('\n')
    if last_single_newline > max_length * 0.7:
        return text[:last_single_newline].rstrip() + suffix
    
    # Fallback: truncate at last space to avoid splitting words
    last_space = truncated.rfind(' ')
    if last_space > max_length * 0.8:
        return text[:last_space].rstrip() + suffix
    
    # Last resort: hard truncate (but at least don't split multi-byte chars)
    return truncated.rstrip() + suffix


def truncate_with_context(
    text: str,
    max_length: int,
    context_query: Optional[str] = None,
    suffix: str = "..."
) -> str:
    """
    Truncate text while preserving relevant context based on a query.
    
    If a context_query is provided, tries to keep text around matching sections.
    Otherwise falls back to semantic truncation from the start.
    
    Args:
        text: Text to truncate
        max_length: Maximum character length
        context_query: Optional query to find relevant sections
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text with preserved context
    """
    if len(text) <= max_length:
        return text
    
    if not context_query:
        return truncate_at_sentence(text, max_length, suffix)
    
    # Find query terms in text (case-insensitive)
    query_terms = context_query.lower().split()
    text_lower = text.lower()
    
    # Find first occurrence of any query term
    first_match_pos = len(text)
    for term in query_terms:
        pos = text_lower.find(term)
        if pos != -1 and pos < first_match_pos:
            first_match_pos = pos
    
    if first_match_pos == len(text):
        # No match found, truncate from start
        return truncate_at_sentence(text, max_length, suffix)
    
    # Try to center the match within max_length
    start_pos = max(0, first_match_pos - max_length // 3)
    end_pos = min(len(text), start_pos + max_length)
    
    # Adjust to sentence boundaries
    if start_pos > 0:
        # Find sentence start after start_pos
        sentence_start = text.rfind('. ', 0, start_pos)
        if sentence_start != -1:
            start_pos = sentence_start + 2
        prefix = "..." if start_pos > 0 else ""
    else:
        prefix = ""
    
    # Extract segment
    segment = text[start_pos:end_pos]
    
    # Truncate segment at sentence boundary
    truncated_segment = truncate_at_sentence(segment, len(segment), "")
    
    return prefix + truncated_segment + suffix


def smart_truncate_for_llm(
    text: str,
    max_length: int,
    keep_start: bool = True,
    keep_end: bool = False
) -> str:
    """
    Smart truncation optimized for LLM context windows.
    
    Preserves important sections (start/end) and uses semantic boundaries.
    
    Args:
        text: Text to truncate
        max_length: Maximum character length
        keep_start: Whether to preserve the beginning
        keep_end: Whether to preserve the ending
        
    Returns:
        Truncated text with key sections preserved
    """
    if len(text) <= max_length:
        return text
    
    if keep_start and keep_end:
        # Keep both start and end, show truncation in middle
        start_len = int(max_length * 0.45)
        end_len = int(max_length * 0.45)
        
        start_text = truncate_at_sentence(text[:start_len * 2], start_len, "")
        end_text = text[-end_len * 2:]
        
        # Find sentence start in end text
        end_sentence_start = end_text.find('. ')
        if end_sentence_start != -1:
            end_text = end_text[end_sentence_start + 2:]
        
        truncated_chars = len(text) - len(start_text) - len(end_text)
        middle_marker = f"\n\n[...{truncated_chars:,} characters omitted...]\n\n"
        
        return start_text + middle_marker + end_text
    
    elif keep_start:
        return truncate_at_sentence(text, max_length, "\n\n[...truncated...]")
    
    elif keep_end:
        # Keep the end section
        start_pos = max(0, len(text) - max_length)
        end_section = text[start_pos:]
        
        # Find sentence start
        sentence_start = end_section.find('. ')
        if sentence_start != -1:
            end_section = end_section[sentence_start + 2:]
        
        truncated_chars = len(text) - len(end_section)
        return f"[...{truncated_chars:,} characters omitted...]\n\n" + end_section
    
    else:
        # Default: keep start
        return truncate_at_sentence(text, max_length, "\n\n[...truncated...]")

