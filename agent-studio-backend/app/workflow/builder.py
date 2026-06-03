"""
Workflow graph builder.

Builds a LangGraph StateGraph from a parsed workflow definition.
"""

from typing import Dict, Any, Callable, List
from langgraph.graph import StateGraph, END
import logging

from .state import WorkflowState
from .parser import ParsedWorkflow, NodeConfig, EdgeConfig
from .nodes import NODE_REGISTRY

logger = logging.getLogger(__name__)


class WorkflowGraphBuilder:
    """
    Builds a LangGraph from a parsed workflow.
    
    Converts the node and edge definitions into an executable StateGraph.
    """
    
    def __init__(self, parsed_workflow: ParsedWorkflow):
        """
        Initialize the builder.
        
        Args:
            parsed_workflow: Parsed workflow definition
        """
        self.parsed_workflow = parsed_workflow
        self.node_executors: Dict[str, Callable] = {}
    
    def build(self) -> StateGraph:
        """
        Build the LangGraph StateGraph.
        
        Returns:
            Compiled StateGraph ready for execution
        """
        logger.info("Building workflow graph with %d nodes", len(self.parsed_workflow.nodes))
        
        # Create the state graph
        graph = StateGraph(WorkflowState)
        
        # Add all nodes
        for node_config in self.parsed_workflow.nodes:
            self._add_node_to_graph(graph, node_config)
        
        # Add edges
        for edge_config in self.parsed_workflow.edges:
            self._add_edge_to_graph(graph, edge_config)
        
        # Add conditional routing for condition nodes
        self._add_condition_node_routing(graph)
        
        # Set entry point (verify it's an executable node)
        if self.parsed_workflow.start_node:
            if self.parsed_workflow.start_node in self.node_executors:
                graph.set_entry_point(self.parsed_workflow.start_node)
                logger.debug("Set entry point: %s", self.parsed_workflow.start_node)
            else:
                logger.error("Start node %s is not in the executable graph", self.parsed_workflow.start_node)
                raise ValueError(f"Start node '{self.parsed_workflow.start_node}' was not added to the graph")
        
        # Add finish edges for end nodes (only if the node was actually added to the graph)
        for end_node_id in self.parsed_workflow.end_nodes:
            if end_node_id in self.node_executors:
                graph.add_edge(end_node_id, END)
                logger.debug("Added finish edge from: %s", end_node_id)
            else:
                logger.warning("Skipping finish edge for node %s: not in executable graph", end_node_id)
        
        logger.info("Graph building complete")
        return graph
    
    def _add_node_to_graph(self, graph: StateGraph, node_config: NodeConfig) -> None:
        """
        Add a node to the graph.
        
        Args:
            graph: StateGraph to add to
            node_config: Node configuration
        """
        node_type = node_config.type
        node_id = node_config.id
        
        # Get the executor class for this node type
        executor_class = NODE_REGISTRY.get(node_type)
        
        if not executor_class:
            logger.warning("Unknown node type '%s' for node %s, skipping", node_type, node_id)
            return
        
        # Create executor instance
        try:
            executor = executor_class(node_config)
            self.node_executors[node_id] = executor
            
            # Add to graph
            graph.add_node(node_id, executor)
            logger.debug("Added node: %s (type: %s)", node_id, node_type)
            
        except Exception as e:
            logger.error("Failed to create executor for node %s: %s", node_id, e)
            raise
    
    def _add_edge_to_graph(self, graph: StateGraph, edge_config: EdgeConfig) -> None:
        """
        Add an edge to the graph.
        
        For condition nodes, edges are handled specially - we collect all outgoing
        edges and add them as conditional edges in bulk.
        
        Args:
            graph: StateGraph to add to
            edge_config: Edge configuration
        """
        source = edge_config.source
        target = edge_config.target
        condition = edge_config.condition
        
        # Check if nodes exist
        if source not in self.node_executors:
            logger.warning("Source node %s not found for edge", source)
            return
        
        if target not in self.node_executors and target != END:
            logger.warning("Target node %s not found for edge", target)
            return
        
        # Check if source is a condition node
        source_executor = self.node_executors.get(source)
        is_condition_node = (hasattr(source_executor, 'config') and 
                            source_executor.config.type == "condition")
        
        if is_condition_node:
            # Skip individual edge addition for condition nodes
            # They will be handled in bulk by _add_condition_node_routing
            logger.debug("Skipping edge for condition node %s (will add routing)", source)
            return
        
        if condition:
            # Conditional edge (non-condition node with condition)
            self._add_conditional_edge(graph, source, target, condition)
        else:
            # Regular edge
            graph.add_edge(source, target)
            logger.debug("Added edge: %s -> %s", source, target)
    
    def _add_condition_node_routing(self, graph: StateGraph) -> None:
        """
        Add conditional routing for all condition nodes.
        
        Condition nodes route to different targets based on which condition matches.
        The routing is determined by matching condition IDs in edges to conditions
        in the node configuration.
        
        Args:
            graph: StateGraph to add routing to
        """
        # Find all condition nodes
        condition_nodes = [
            (node_id, executor) 
            for node_id, executor in self.node_executors.items()
            if hasattr(executor, 'config') and executor.config.type == "condition"
        ]
        
        for node_id, executor in condition_nodes:
            # Get all outgoing edges from this condition node
            outgoing_edges = [
                edge for edge in self.parsed_workflow.edges 
                if edge.source == node_id
            ]
            
            if not outgoing_edges:
                logger.warning("Condition node %s has no outgoing edges", node_id)
                continue
            
            # Get conditions from node config
            conditions = executor.config.config.get("conditions", [])
            
            # Build mapping from condition ID to target node
            condition_to_target = {}
            for edge in outgoing_edges:
                # Get conditionId from edge (frontend stores it here)
                condition_id = edge.conditionId
                
                # Fallback: try metadata
                if not condition_id and edge.metadata:
                    condition_id = edge.metadata.get("condition_id")
                
                # Fallback: try to extract from edge id (format: source-target-conditionId)
                if not condition_id and '-' in edge.id:
                    parts = edge.id.split('-')
                    if len(parts) >= 3:
                        potential_condition_id = '-'.join(parts[2:])
                        # Verify this is a valid condition ID
                        if any(c.get('id') == potential_condition_id for c in conditions):
                            condition_id = potential_condition_id
                
                if condition_id:
                    condition_to_target[condition_id] = edge.target
                    logger.debug("Mapped condition %s to target %s", condition_id, edge.target)
                else:
                    # Fallback: match by order (first edge = first condition, etc.)
                    edge_index = outgoing_edges.index(edge)
                    if edge_index < len(conditions):
                        condition_id = conditions[edge_index].get('id')
                        condition_to_target[condition_id] = edge.target
                        logger.warning("Edge from %s to %s has no conditionId, matched by order to condition %s", 
                                     node_id, edge.target, condition_id)
            
            # Create routing function for this specific condition node
            def create_router(cond_to_target: Dict[str, str], default_target: str):
                def route_condition(state: WorkflowState) -> str:
                    """Route based on matched condition."""
                    # Debug: Log state structure
                    logger.debug("🔍 ROUTER DEBUG for node %s", node_id)
                    logger.debug("   State keys: %s", list(state.keys()))
                    logger.debug("   node_outputs keys: %s", list(state.get("node_outputs", {}).keys()))
                    
                    # Get the condition node's output
                    condition_output = state.get("node_outputs", {}).get(node_id, {})
                    logger.debug("   Condition NodeOutput: %s", condition_output)
                    
                    # The condition node returns { "output": { "matched_condition_id": ... } }
                    # which gets wrapped in NodeOutput.output, creating a double-nested structure
                    # So we need: state["node_outputs"][node_id]["output"]["output"]["matched_condition_id"]
                    node_output_data = condition_output.get("output", {})
                    logger.debug("   Node output data: %s", node_output_data)
                    
                    # Try double-nested first (condition node returns with "output" key)
                    matched = node_output_data.get("output", {}).get("matched_condition_id")
                    
                    # Fallback to single-nested (if condition node changes to return at top level)
                    if not matched:
                        matched = node_output_data.get("matched_condition_id")
                    
                    logger.debug("   Extracted matched_condition_id: %s", matched)
                    logger.debug("   Available targets: %s", cond_to_target)
                    
                    if matched and matched in cond_to_target:
                        target = cond_to_target[matched]
                        logger.debug("✅ Routing from %s to %s (matched: %s)", node_id, target, matched)
                        return target
                    
                    # Default fallback
                    logger.warning("⚠️ No matching condition for %s, using default: %s", node_id, default_target)
                    logger.warning("   Reason: matched=%s, in_targets=%s", matched, matched in cond_to_target if matched else False)
                    return default_target
                
                return route_condition
            
            # Determine default target (last edge or first edge)
            default_target = outgoing_edges[-1].target if outgoing_edges else END
            
            # Build route map for LangGraph
            route_map = {target: target for target in condition_to_target.values()}
            if default_target not in route_map:
                route_map[default_target] = default_target
            
            # Add conditional edges
            router = create_router(condition_to_target, default_target)
            graph.add_conditional_edges(
                node_id,
                router,
                route_map
            )
            logger.debug("Added conditional routing for %s with %d branches", 
                       node_id, len(condition_to_target))
    
    def _add_conditional_edge(
        self,
        graph: StateGraph,
        source: str,
        target: str,
        condition: str
    ) -> None:
        """
        Add a conditional edge to the graph.
        
        For non-condition nodes that have conditions on their edges.
        
        Args:
            graph: StateGraph to add to
            source: Source node ID
            target: Target node ID (or mapping)
            condition: Condition specification
        """
        # Regular conditional logic (not implemented yet)
        graph.add_edge(source, target)
        logger.warning("Conditional edge on non-condition node, using regular edge")
    
    def get_node_executor(self, node_id: str) -> Any:
        """
        Get the executor instance for a node.
        
        Args:
            node_id: Node ID
            
        Returns:
            Node executor instance
        """
        return self.node_executors.get(node_id)


