"""
Workflow parser for converting JSON workflow definitions to executable components.

Parses the workflow JSON structure (nodes and edges) and validates the workflow
before execution.
"""

from typing import Dict, List, Optional, Any, Set
from pydantic import BaseModel, Field, validator
import json
import logging

logger = logging.getLogger(__name__)

NON_EXECUTABLE_NODE_TYPES = {"sticky-note"}


class NodeConfig(BaseModel):
    """Configuration for a single workflow node."""
    id: str
    type: str
    position: Optional[Dict[str, float]] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class EdgeConfig(BaseModel):
    """Configuration for a workflow edge (connection)."""
    id: str
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    condition: Optional[str] = None  # For conditional edges
    conditionId: Optional[str] = None  # For condition node routing (which condition this edge represents)
    metadata: Optional[Dict[str, Any]] = None  # Additional metadata


class ParsedWorkflow(BaseModel):
    """Parsed and validated workflow structure."""
    version: str = "1.0"
    nodes: List[NodeConfig]
    edges: List[EdgeConfig]
    start_node: Optional[str] = None
    end_nodes: List[str] = Field(default_factory=list)
    
    @validator('nodes')
    def validate_nodes(cls, nodes):
        """Validate that there is at least one node."""
        if not nodes:
            raise ValueError("Workflow must have at least one node")
        return nodes
    
    def get_node_by_id(self, node_id: str) -> Optional[NodeConfig]:
        """Get a node by its ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None
    
    def get_outgoing_edges(self, node_id: str) -> List[EdgeConfig]:
        """Get all edges originating from a node."""
        return [edge for edge in self.edges if edge.source == node_id]
    
    def get_incoming_edges(self, node_id: str) -> List[EdgeConfig]:
        """Get all edges pointing to a node."""
        return [edge for edge in self.edges if edge.target == node_id]


class WorkflowParser:
    """
    Parser for workflow JSON definitions.
    
    Converts the frontend workflow JSON structure into a validated
    ParsedWorkflow object ready for execution.
    """
    
    @staticmethod
    def parse(workflow_json: Dict[str, Any]) -> ParsedWorkflow:
        """
        Parse a workflow JSON definition.
        
        Args:
            workflow_json: Raw workflow JSON from database
            
        Returns:
            ParsedWorkflow object
            
        Raises:
            ValueError: If workflow structure is invalid
        """
        try:
            # Handle both direct workflow object and wrapped format
            if "workflow" in workflow_json:
                workflow_data = workflow_json["workflow"]
            else:
                workflow_data = workflow_json
            
            # Parse nodes
            nodes = []
            for node_data in workflow_data.get("nodes", []):
                # Log what we're receiving
                if node_data.get("type") in ["agent", "chat"]:
                    logger.debug("🔍 PARSER - Received node: id=%s, type=%s", 
                               node_data.get("id"), node_data.get("type"))
                    config_keys = list(node_data.get("config", {}).keys())
                    logger.debug("PARSER - node_data.config keys: %s", config_keys)
                
                # Transform 'data' field to 'config' if needed
                if "data" in node_data and "config" not in node_data:
                    node_dict = node_data.copy()
                    node_dict["config"] = node_data["data"].get("config", {})
                    nodes.append(NodeConfig(**node_dict))
                else:
                    nodes.append(NodeConfig(**node_data))
            
            # Filter out non-executable nodes (e.g. sticky notes)
            non_exec_ids = {n.id for n in nodes if n.type in NON_EXECUTABLE_NODE_TYPES}
            if non_exec_ids:
                logger.info(
                    "Filtering %d non-executable node(s) from workflow: %s",
                    len(non_exec_ids),
                    non_exec_ids,
                )
            nodes = [n for n in nodes if n.id not in non_exec_ids]

            # Parse edges, dropping any that reference filtered nodes
            edges = []
            for edge_data in workflow_data.get("edges", []):
                edge = EdgeConfig(**edge_data)
                if edge.source in non_exec_ids or edge.target in non_exec_ids:
                    logger.debug(
                        "Dropping edge %s (%s -> %s): references non-executable node",
                        edge.id, edge.source, edge.target,
                    )
                    continue
                edges.append(edge)
            
            # Create parsed workflow
            parsed = ParsedWorkflow(
                version=workflow_json.get("version", "1.0"),
                nodes=nodes,
                edges=edges
            )
            
            # Validate and find start/end nodes
            WorkflowParser._validate_and_enrich(parsed)
            
            logger.debug(
                "Parsed workflow with %d nodes and %d edges",
                len(parsed.nodes),
                len(parsed.edges)
            )
            
            return parsed
            
        except Exception as e:
            logger.error("Failed to parse workflow: %s", e)
            raise ValueError(f"Invalid workflow structure: {str(e)}") from e
    
    @staticmethod
    def parse_from_string(workflow_str: str) -> ParsedWorkflow:
        """
        Parse a workflow from a JSON string.
        
        Args:
            workflow_str: JSON string representation of workflow
            
        Returns:
            ParsedWorkflow object
        """
        workflow_json = json.loads(workflow_str)
        return WorkflowParser.parse(workflow_json)
    
    @staticmethod
    def _validate_and_enrich(parsed: ParsedWorkflow) -> None:
        """
        Validate workflow structure and enrich with metadata.
        
        Args:
            parsed: ParsedWorkflow to validate
            
        Raises:
            ValueError: If validation fails
        """
        # Check for duplicate node IDs
        node_ids = [node.id for node in parsed.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Duplicate node IDs found in workflow")
        
        # Validate edge references
        for edge in parsed.edges:
            if edge.source not in node_ids:
                raise ValueError(f"Edge references non-existent source node: {edge.source}")
            if edge.target not in node_ids:
                raise ValueError(f"Edge references non-existent target node: {edge.target}")
        
        # Find start nodes (nodes with type "start" or no incoming edges)
        start_nodes = []
        for node in parsed.nodes:
            if node.type == "start":
                start_nodes.append(node.id)
            elif not parsed.get_incoming_edges(node.id):
                # Node with no incoming edges could be a start node
                if node.type != "end":  # Don't count end nodes
                    start_nodes.append(node.id)
        
        if not start_nodes:
            raise ValueError("Workflow must have at least one start node")
        
        if len(start_nodes) > 1:
            logger.warning("Multiple start nodes found, using first: %s", start_nodes[0])
        
        parsed.start_node = start_nodes[0]
        
        # Find end nodes (nodes with type "end" or no outgoing edges)
        end_nodes = []
        for node in parsed.nodes:
            if node.type == "end":
                end_nodes.append(node.id)
            elif not parsed.get_outgoing_edges(node.id):
                # Node with no outgoing edges could be an end node
                if node.type != "start":  # Don't count start nodes
                    end_nodes.append(node.id)
        
        parsed.end_nodes = end_nodes
        
        # Check for cycles (optional - some workflows may need cycles)
        if WorkflowParser._has_cycle(parsed):
            logger.warning("Workflow contains cycles - ensure proper termination conditions")
        
        # Validate that all nodes have valid types
        valid_node_types = {
            "start", "end", "agent", "tool", "condition",
            "transform", "human", "webhook", "api",
            "chat", "hitl", "human-in-the-loop", "subagent",
            "code-executor", "opportunity-classifier",
            "researcher", "business-analyst", "financial-modeler",
        }
        
        for node in parsed.nodes:
            if node.type not in valid_node_types:
                logger.warning("Unknown node type: %s (node %s)", node.type, node.id)
    
    @staticmethod
    def _has_cycle(parsed: ParsedWorkflow) -> bool:
        """
        Check if workflow has cycles using DFS.
        
        Args:
            parsed: ParsedWorkflow to check
            
        Returns:
            True if cycle detected, False otherwise
        """
        visited = set()
        rec_stack = set()
        
        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            
            for edge in parsed.get_outgoing_edges(node_id):
                target = edge.target
                if target not in visited:
                    if dfs(target):
                        return True
                elif target in rec_stack:
                    return True
            
            rec_stack.remove(node_id)
            return False
        
        for node in parsed.nodes:
            if node.id not in visited:
                if dfs(node.id):
                    return True
        
        return False
    
    @staticmethod
    def get_execution_order(parsed: ParsedWorkflow) -> List[str]:
        """
        Get a topological sort of nodes (execution order).
        
        This is a best-effort ordering for linear workflows.
        For workflows with branching/conditions, execution order is dynamic.
        
        Args:
            parsed: ParsedWorkflow
            
        Returns:
            List of node IDs in execution order
        """
        in_degree = {node.id: 0 for node in parsed.nodes}
        
        # Calculate in-degree for each node
        for edge in parsed.edges:
            in_degree[edge.target] += 1
        
        # Queue nodes with no dependencies
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        execution_order = []
        
        while queue:
            node_id = queue.pop(0)
            execution_order.append(node_id)
            
            # Reduce in-degree for dependent nodes
            for edge in parsed.get_outgoing_edges(node_id):
                in_degree[edge.target] -= 1
                if in_degree[edge.target] == 0:
                    queue.append(edge.target)
        
        return execution_order


