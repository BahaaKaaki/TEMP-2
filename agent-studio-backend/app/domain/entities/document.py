"""
Document domain entity for RAG capabilities.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class DocumentStatus(str, Enum):
    """Document processing status."""
    PENDING = "pending"
    PENDING_SCHEMA_REVIEW = "schema_review"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentType(str, Enum):
    """Document type enumeration."""
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    CSV = "csv"
    JSON = "json"
    XML = "xml"
    HTML = "html"
    MARKDOWN = "md"
    IMAGE = "image"
    OTHER = "other"


@dataclass
class Document:
    """Document domain entity for RAG storage."""
    
    id: str
    kb_id: str
    session_id: str
    blob_name: str
    file_name: str
    file_type: DocumentType
    file_size: int
    mime_type: Optional[str]
    status: DocumentStatus
    container_name: str
    blob_url: Optional[str]
    metadata: Optional[Dict[str, Any]]
    extracted_text: Optional[str]
    chunk_count: Optional[int]
    embedding_status: Optional[str]
    processing_error: Optional[str]
    uploaded_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    
    def is_processed(self) -> bool:
        """Check if document is successfully processed."""
        return self.status == DocumentStatus.COMPLETED
    
    def is_processing(self) -> bool:
        """Check if document is being processed."""
        return self.status == DocumentStatus.PROCESSING
    
    def is_failed(self) -> bool:
        """Check if document processing failed."""
        return self.status == DocumentStatus.FAILED
    
    def is_pending(self) -> bool:
        """Check if document is pending processing."""
        return self.status == DocumentStatus.PENDING
    
    def is_deleted(self) -> bool:
        """Check if document is soft-deleted."""
        return self.deleted_at is not None
    
    def get_size_kb(self) -> float:
        """Get file size in KB."""
        return self.file_size / 1024
    
    def get_size_mb(self) -> float:
        """Get file size in MB."""
        return self.file_size / (1024 * 1024)
    
    def has_extracted_text(self) -> bool:
        """Check if document has extracted text."""
        return self.extracted_text is not None and len(self.extracted_text) > 0
    
    def is_embedded(self) -> bool:
        """Check if document has been embedded."""
        return self.embedding_status == "completed"
    
    def mark_as_processing(self) -> None:
        """Mark document as being processed."""
        self.status = DocumentStatus.PROCESSING
        self.updated_at = datetime.utcnow()
    
    def mark_as_completed(self, extracted_text: Optional[str] = None, chunk_count: Optional[int] = None) -> None:
        """Mark document processing as completed."""
        self.status = DocumentStatus.COMPLETED
        if extracted_text:
            self.extracted_text = extracted_text
        if chunk_count is not None:
            self.chunk_count = chunk_count
        self.updated_at = datetime.utcnow()
    
    def mark_as_failed(self, error: str) -> None:
        """Mark document processing as failed."""
        self.status = DocumentStatus.FAILED
        self.processing_error = error
        self.updated_at = datetime.utcnow()
    
    def update_embedding_status(self, status: str) -> None:
        """Update embedding status."""
        self.embedding_status = status
        self.updated_at = datetime.utcnow()

