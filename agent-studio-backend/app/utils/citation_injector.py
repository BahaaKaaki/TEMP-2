"""
Citation injection utility.

Forcefully injects citation markers [N] into LLM responses based on 
which knowledge base chunks or web sources were actually used.
"""

import logging
import re
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class CitationInjector:
    """
    Intelligently inject citation markers into LLM responses.

    Strategy:
    1. Find sentences in the LLM response that match a citation's content
       (KB chunk text, or for web citations the title + hostname).
    2. Inject ``[N]`` markers at the end of those sentences.
    3. Callers decide what to do if nothing matched — see
       ``append_sources_footer`` for the never-silent fallback used when
       web citations are in play.
    """
    
    @staticmethod
    def inject_citations(
        response_text: str,
        citations: List[Dict[str, Any]],
        min_overlap_words: int = 5
    ) -> str:
        """
        Inject citation markers into response text.
        
        Args:
            response_text: The LLM's response text (without citations)
            citations: List of citation objects with chunk_text
            min_overlap_words: Minimum word overlap to consider a match
            
        Returns:
            Response text with [N] markers injected
        """
        if not citations:
            return response_text
        
        logger.debug("🔧 Injecting %d citations into response", len(citations))
        
        # Strategy 1: Try to match sentences with chunks
        injected_text = CitationInjector._inject_inline(
            response_text, 
            citations, 
            min_overlap_words
        )
        
        # Check if any citations were injected
        markers_found = re.findall(r'\[(\d+)\]', injected_text)
        injected_count = len(set(markers_found))
        
        logger.debug("✅ Injected %d/%d citations inline", injected_count, len(citations))
        
        # Strategy 2: If no citations were injected, try to append at end (but let caller decide to filter)
        if injected_count == 0:
            logger.debug("⚠️ No inline matches found, will let caller decide to append or filter")
            # Don't auto-append - the agent node will filter out unused citations
            # injected_text = CitationInjector._append_citations(injected_text, citations)
        # Strategy 3: If some citations were injected, that's good - don't append the rest
        elif injected_count < len(citations):
            logger.debug("ℹ️ Only %d/%d citations matched inline (unused will be filtered out)", injected_count, len(citations))
            # Don't append unused citations - they'll be filtered out by the agent node
        
        return injected_text
    
    @staticmethod
    def _inject_inline(
        response_text: str,
        citations: List[Dict[str, Any]],
        min_overlap_words: int
    ) -> str:
        """
        Inject citations inline by matching sentences with citation content.

        KB citations match against ``chunk_text``. Web citations (empty
        ``chunk_text``) match against their title plus the URL hostname, with
        a lower word threshold because titles are short.
        """
        # Split response into sentences
        sentences = CitationInjector._split_into_sentences(response_text)
        
        # Track which citations have been used
        used_citations = set()
        
        # Process each sentence
        injected_sentences = []
        for sentence in sentences:
            sentence_modified = False
            
            # Try to match this sentence with each citation's searchable blob
            for citation in citations:
                citation_num = citation['citation_number']
                
                # Skip if already used
                if citation_num in used_citations:
                    continue

                search_blob, threshold = CitationInjector._searchable_text(
                    citation, min_overlap_words,
                )

                if CitationInjector._has_overlap(sentence, search_blob, threshold):
                    sentence_clean = sentence.rstrip('.,!?;: ')
                    sentence = f"{sentence_clean} [{citation_num}]."
                    used_citations.add(citation_num)
                    sentence_modified = True
                    logger.debug("Matched citation [%d] to sentence: %s...", citation_num, sentence[:60])
                    break  # Only one citation per sentence
            
            injected_sentences.append(sentence)
        
        return ' '.join(injected_sentences)

    @staticmethod
    def _searchable_text(
        citation: Dict[str, Any],
        default_threshold: int,
    ) -> Tuple[str, int]:
        """Pick the best text blob to match against for this citation.

        For KB citations we fall back on ``chunk_text`` with the default
        threshold.  For web citations the chunk is always empty, so we use
        ``title`` plus the URL hostname (minus its TLD) and loosen the
        threshold to 2 words because titles are short and the hostname is a
        single token.
        """
        chunk_text = (citation.get("chunk_text") or "").strip()
        if chunk_text:
            return chunk_text, default_threshold

        parts: List[str] = []
        title = (citation.get("title") or "").strip()
        if title:
            parts.append(title)

        url = (citation.get("url") or "").strip()
        if url:
            try:
                host = urlparse(url).hostname or ""
            except Exception:
                host = ""
            host = host.removeprefix("www.")
            # Strip the TLD so "apnews.com" matches the word "apnews".
            host_root = host.split(".")[0] if host else ""
            if host_root:
                parts.append(host_root)

        blob = " ".join(parts)
        # Titles are short (often < 10 significant words); require fewer matches.
        return blob, 2 if blob else default_threshold
    
    @staticmethod
    def _append_citations(response_text: str, citations: List[Dict[str, Any]]) -> str:
        """
        Append all citations at the end of response as clickable markers.
        """
        citation_line = "\n\n**Sources:** "
        citation_line += " ".join([f"[{c['citation_number']}]" for c in citations])
        citation_line += "\n\n*(Hover over or click any [N] to see source details)*"
        
        return response_text + citation_line

    @staticmethod
    def append_sources_footer(
        response_text: str,
        citations: List[Dict[str, Any]],
    ) -> str:
        """Append a compact ``**Sources:**`` footer with ``[N]`` markers.

        Used as the never-silent fallback when a sentence-level inline match
        was not possible (typically for web citations whose ``chunk_text`` is
        empty) and the LLM also stripped all markers from its prose.  Ensures
        the frontend can still render clickable source badges instead of
        silently dropping every citation.
        """
        if not citations:
            return response_text

        markers = " ".join(f"[{c['citation_number']}]" for c in citations)
        footer = f"\n\n**Sources:** {markers}"
        return response_text.rstrip() + footer
    
    @staticmethod
    def _split_into_sentences(text: str) -> List[str]:
        """
        Split text into sentences (simple implementation).
        """
        # Simple sentence splitting (can be improved with NLP libraries)
        # Split on . ! ? followed by space or newline
        sentences = re.split(r'([.!?]+[\s\n]+)', text)
        
        # Recombine sentences with their punctuation
        result = []
        for i in range(0, len(sentences) - 1, 2):
            sentence = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else '')
            if sentence.strip():
                result.append(sentence.strip())
        
        # Add last sentence if not paired
        if len(sentences) % 2 == 1 and sentences[-1].strip():
            result.append(sentences[-1].strip())
        
        return result
    
    @staticmethod
    def _has_overlap(sentence: str, chunk_text: str, min_words: int) -> bool:
        """
        Check if sentence has significant word overlap with chunk text.
        """
        # Normalize text
        sentence_lower = sentence.lower()
        chunk_lower = chunk_text.lower()
        
        # Extract significant words (ignore common stopwords)
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                     'of', 'with', 'by', 'from', 'is', 'was', 'are', 'were', 'be', 'been',
                     'this', 'that', 'these', 'those', 'it', 'its'}
        
        sentence_words = set(re.findall(r'\b\w+\b', sentence_lower)) - stopwords
        chunk_words = set(re.findall(r'\b\w+\b', chunk_lower)) - stopwords
        
        # Count overlapping words
        overlap = sentence_words & chunk_words
        
        return len(overlap) >= min_words
    
    @staticmethod
    def has_citation_markers(text: str) -> bool:
        """Check if text already contains citation markers."""
        return bool(re.search(r'\[\d+\]', text))

