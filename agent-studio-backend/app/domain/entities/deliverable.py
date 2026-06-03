"""
Deliverable domain entity.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json


@dataclass
class Deliverable:
    """Agent deliverable domain entity."""
    
    id: str
    session_id: str
    execution_id: int
    agent_id: str
    agent_label: str
    agent_type: str
    deliverable_data: dict
    deliverable_schema: Optional[str]
    status: str
    iteration: int
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]
    review_notes: Optional[str]
    previous_deliverable_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    viz_configs: Optional[dict] = None
    created_by_id: Optional[str] = None
    openui_lang: Optional[str] = None
    
    def is_pending(self) -> bool:
        """Check if deliverable is pending review."""
        return self.status == "pending"
    
    def is_approved(self) -> bool:
        """Check if deliverable is approved."""
        return self.status == "approved"
    
    def is_rejected(self) -> bool:
        """Check if deliverable is rejected."""
        return self.status == "rejected"
    
    def can_be_reviewed(self) -> bool:
        """Check if deliverable can be reviewed."""
        return self.is_pending()
    
    def approve(self, reviewed_by: Optional[str] = None, notes: Optional[str] = None):
        """Approve the deliverable."""
        self.status = "approved"
        self.reviewed_at = datetime.utcnow()
        self.reviewed_by = reviewed_by
        self.review_notes = notes
    
    def reject(self, reviewed_by: Optional[str] = None, notes: Optional[str] = None):
        """Reject the deliverable."""
        self.status = "rejected"
        self.reviewed_at = datetime.utcnow()
        self.reviewed_by = reviewed_by
        self.review_notes = notes or "Please revise your output."
    
    def get_deliverable_dict(self) -> dict:
        """Get deliverable data as dict."""
        if self.deliverable_data is None:
            return {}
        if isinstance(self.deliverable_data, str):
            try:
                return json.loads(self.deliverable_data)
            except (json.JSONDecodeError, ValueError):
                return {}
        if isinstance(self.deliverable_data, dict):
            return self.deliverable_data
        return {}
    
    def mark_as_approved(self, reviewed_by: Optional[str] = None, notes: Optional[str] = None) -> None:
        """Mark deliverable as approved (updates status only, call approve() for full approval)."""
        self.status = "approved"
        self.reviewed_at = datetime.utcnow()
        if reviewed_by:
            self.reviewed_by = reviewed_by
        if notes:
            self.review_notes = notes
    
    def mark_as_rejected(self, reviewed_by: Optional[str] = None, notes: Optional[str] = None) -> None:
        """Mark deliverable as rejected (updates status only, call reject() for full rejection)."""
        self.status = "rejected"
        self.reviewed_at = datetime.utcnow()
        if reviewed_by:
            self.reviewed_by = reviewed_by
        if notes:
            self.review_notes = notes or "Please revise your output."

