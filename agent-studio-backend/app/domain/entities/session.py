"""
Session domain entity.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json


@dataclass
class Session:
    """Chat session domain entity."""
    
    id: str
    workflow_id: str
    name: Optional[str]
    description: Optional[str]
    status: str
    message_count: int
    session_variables: Optional[dict]
    session_metadata: Optional[dict]
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime]
    deleted_at: Optional[datetime]
    is_pinned: bool = False
    last_accessed_at: Optional[datetime] = None
    project_id: Optional[str] = None
    
    def is_active(self) -> bool:
        """Check if session is active."""
        return self.status == 'active' and self.deleted_at is None
    
    def can_receive_messages(self) -> bool:
        """Check if session can receive messages."""
        return self.is_active()
    
    def is_deleted(self) -> bool:
        """Check if session is deleted."""
        return self.deleted_at is not None
    
    def get_variables_dict(self) -> dict:
        """Get session variables as dict."""
        if not self.session_variables:
            return {}
        if isinstance(self.session_variables, str):
            return json.loads(self.session_variables)
        return self.session_variables
    
    def get_metadata_dict(self) -> dict:
        """Get session metadata as dict."""
        if not self.session_metadata:
            return {}
        if isinstance(self.session_metadata, str):
            return json.loads(self.session_metadata)
        return self.session_metadata
