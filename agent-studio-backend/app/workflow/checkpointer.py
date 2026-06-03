"""
Checkpoint storage for workflow state persistence.

Enables workflow state persistence and resume functionality.
Note: This is a simplified implementation that doesn't use LangGraph's checkpoint API
which has changed in recent versions.
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class InMemoryCheckpointSaver:
    """
    Simplified in-memory checkpoint saver.
    
    Stores workflow state snapshots for potential resume functionality.
    This is a simplified version that works with LangGraph without
    depending on the checkpoint API which varies by version.
    """
    
    def __init__(self):
        """Initialize the checkpoint saver."""
        self.checkpoints: Dict[str, Any] = {}
        self.metadata: Dict[str, Dict[str, Any]] = {}
    
    def save(self, thread_id: str, state: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Save a state checkpoint.
        
        Args:
            thread_id: Thread/conversation identifier
            state: Workflow state to save
            metadata: Optional metadata
        """
        self.checkpoints[thread_id] = state
        if metadata:
            self.metadata[thread_id] = metadata
        logger.debug("Saved checkpoint for thread: %s", thread_id)
    
    def load(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a state checkpoint.
        
        Args:
            thread_id: Thread/conversation identifier
            
        Returns:
            Saved state if found, None otherwise
        """
        return self.checkpoints.get(thread_id)
    
    def get_metadata(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get checkpoint metadata.
        
        Args:
            thread_id: Thread/conversation identifier
            
        Returns:
            Metadata if found, None otherwise
        """
        return self.metadata.get(thread_id)
    
    def list_checkpoints(self) -> Dict[str, Any]:
        """
        List all checkpoints.
        
        Returns:
            Dictionary of thread_id -> checkpoint
        """
        return self.checkpoints.copy()
    
    def clear(self, thread_id: Optional[str] = None) -> None:
        """
        Clear checkpoints.
        
        Args:
            thread_id: Specific thread to clear, or None to clear all
        """
        if thread_id:
            self.checkpoints.pop(thread_id, None)
            self.metadata.pop(thread_id, None)
            logger.debug("Cleared checkpoint for thread: %s", thread_id)
        else:
            self.checkpoints.clear()
            self.metadata.clear()
            logger.debug("Cleared all checkpoints")
