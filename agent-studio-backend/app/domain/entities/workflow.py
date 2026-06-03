"""
Workflow domain entity.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json


@dataclass
class Workflow:
    """Workflow domain entity."""
    
    id: str
    name: str
    active: bool
    nodes: Optional[str]
    connections: Optional[str]
    settings: Optional[str]
    static_data: Optional[str]
    pin_data: Optional[str]
    version_id: Optional[str]
    trigger_count: Optional[int]
    meta: Optional[str]
    parent_folder_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_archived: bool
    
    def is_active(self) -> bool:
        """Check if workflow is active."""
        return self.active and not self.is_archived
    
    def can_be_executed(self) -> bool:
        """Check if workflow can be executed."""
        return self.is_active()
    
    def get_nodes_list(self) -> list:
        """Get nodes as list."""
        if not self.nodes:
            return []
        nodes_data = json.loads(self.nodes)
        if isinstance(nodes_data, list):
            return nodes_data
        return nodes_data.get("nodes", [])
    
    def get_edges_list(self) -> list:
        """Get edges/connections as list."""
        if not self.connections:
            return []
        edges_data = json.loads(self.connections)
        if isinstance(edges_data, list):
            return edges_data
        return edges_data.get("edges", [])
    
    def find_node_by_type(self, node_type: str) -> Optional[dict]:
        """Find first node of given type."""
        nodes = self.get_nodes_list()
        for node in nodes:
            if node.get("type") == node_type:
                return node
        return None
    
    def get_start_node(self) -> Optional[dict]:
        """Get the start/chat node."""
        return self.find_node_by_type("chat") or self.find_node_by_type("start")

