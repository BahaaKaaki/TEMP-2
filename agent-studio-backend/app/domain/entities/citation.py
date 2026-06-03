"""
Citation entity for RAG knowledge base references.

Represents a citation/reference to a chunk from a knowledge base document,
including all metadata needed for UI display and document retrieval.
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class ChunkCitation:
    """
    Citation for a knowledge base chunk used in agent response.
    
    Contains all information needed to:
    - Display citation marker in text [N]
    - Show preview on hover
    - Display full details in modal
    - Download source document
    """
    
    # Citation identification
    citation_number: int
    chunk_id: str
    document_id: str
    kb_id: str
    
    # Document information
    document_name: str
    document_file_type: str
    
    # Chunk information
    chunk_index: int
    chunk_text: str
    chunk_size: int
    
    # Search relevance
    relevance_score: float  # 0.0 to 1.0
    distance: float  # L2 distance from query
    
    # Document metadata
    file_size_bytes: int
    mime_type: Optional[str]
    uploaded_at: datetime
    blob_name: str  # For download
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime to ISO string
        if isinstance(data.get('uploaded_at'), datetime):
            data['uploaded_at'] = data['uploaded_at'].isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChunkCitation':
        """Create from dictionary."""
        # Convert ISO string back to datetime if needed
        if isinstance(data.get('uploaded_at'), str):
            data['uploaded_at'] = datetime.fromisoformat(data['uploaded_at'])
        return cls(**data)


@dataclass
class CitationCollection:
    """
    Collection of citations for a single message.
    
    Manages sequential numbering and deduplication.
    """
    
    citations: list[ChunkCitation]
    
    def __init__(self):
        self.citations = []
        self._chunk_id_to_number = {}  # For deduplication
        self._next_number = 1
    
    def add_citation(
        self,
        chunk_id: str,
        document_id: str,
        kb_id: str,
        document_name: str,
        document_file_type: str,
        chunk_index: int,
        chunk_text: str,
        chunk_size: int,
        relevance_score: float,
        distance: float,
        file_size_bytes: int,
        mime_type: Optional[str],
        uploaded_at: datetime,
        blob_name: str
    ) -> int:
        """
        Add a citation and return its number.
        
        If the same chunk is cited multiple times, returns existing number.
        Otherwise assigns new sequential number.
        
        Returns:
            Citation number to use in text (e.g., 1 for [1])
        """
        # Check if this chunk already cited
        if chunk_id in self._chunk_id_to_number:
            return self._chunk_id_to_number[chunk_id]
        
        # Assign new number
        citation_number = self._next_number
        self._next_number += 1
        
        # Store mapping
        self._chunk_id_to_number[chunk_id] = citation_number
        
        # Create citation
        citation = ChunkCitation(
            citation_number=citation_number,
            chunk_id=chunk_id,
            document_id=document_id,
            kb_id=kb_id,
            document_name=document_name,
            document_file_type=document_file_type,
            chunk_index=chunk_index,
            chunk_text=chunk_text,
            chunk_size=chunk_size,
            relevance_score=relevance_score,
            distance=distance,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            uploaded_at=uploaded_at,
            blob_name=blob_name
        )
        
        self.citations.append(citation)
        return citation_number
    
    def to_dict_list(self) -> list[Dict[str, Any]]:
        """Convert all citations to list of dictionaries."""
        return [c.to_dict() for c in self.citations]
    
    def get_by_number(self, number: int) -> Optional[ChunkCitation]:
        """Get citation by its number."""
        for citation in self.citations:
            if citation.citation_number == number:
                return citation
        return None

