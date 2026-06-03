"""
File domain entity.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class File:
    """Uploaded file domain entity."""
    
    id: str
    session_id: str
    message_id: Optional[str]
    file_name: str
    file_type: str
    file_path: Optional[str]  # DEPRECATED: Legacy local file path
    file_size: int
    mime_type: Optional[str]
    extracted_text: Optional[str]
    parsed_elements: Optional[str]
    parsing_status: str
    parsing_error: Optional[str]
    uploaded_by: Optional[str]
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    
    # Azure Blob Storage fields
    container_name: Optional[str] = None
    blob_name: Optional[str] = None
    blob_url: Optional[str] = None
    
    # Per-agent file scope (see ChatFile model for semantics).
    uploaded_at_agent_id: Optional[str] = None
    uploaded_at_agent_label: Optional[str] = None
    scope: str = "global"
    
    def is_parsed(self) -> bool:
        """Check if file is successfully parsed."""
        return self.parsing_status == "completed"
    
    def is_parsing_failed(self) -> bool:
        """Check if file parsing failed."""
        return self.parsing_status == "failed"
    
    def is_pending_parsing(self) -> bool:
        """Check if file is pending parsing."""
        return self.parsing_status == "pending"
    
    def is_deleted(self) -> bool:
        """Check if file is deleted."""
        return self.deleted_at is not None
    
    def get_size_kb(self) -> float:
        """Get file size in KB."""
        return self.file_size / 1024
    
    def get_size_mb(self) -> float:
        """Get file size in MB."""
        return self.file_size / (1024 * 1024)
    
    def has_extracted_text(self) -> bool:
        """Check if file has extracted text."""
        return self.extracted_text is not None and len(self.extracted_text) > 0
    
    def mark_as_completed(self, extracted_text: str) -> None:
        """Mark file parsing as completed."""
        self.parsing_status = "completed"
        self.extracted_text = extracted_text
    
    def mark_as_failed(self, error: str) -> None:
        """Mark file parsing as failed."""
        self.parsing_status = "failed"
        self.parsing_error = error

