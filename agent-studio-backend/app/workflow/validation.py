"""
Workflow validation utilities.

Validates workflow configurations before execution to catch common issues
that non-technical users might create.
"""

from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class WorkflowValidationError(Exception):
    """Raised when workflow validation fails."""
    
    def __init__(self, message: str, suggestions: List[str] = None):
        self.message = message
        self.suggestions = suggestions or []
        super().__init__(message)


class WorkflowValidator:
    """
    Validates workflow configurations for common issues.
    
    Helps non-technical users avoid configuration pitfalls.
    """
    
    @staticmethod
    def validate_multi_agent_workflow(workflow_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Validate multi-agent workflow configuration.
        
        Args:
            workflow_json: Parsed workflow JSON
            
        Returns:
            List of validation warnings/errors
        """
        issues = []
        
        nodes = workflow_json.get("workflow", {}).get("nodes", [])
        edges = workflow_json.get("workflow", {}).get("edges", [])
        
        # Check each agent node
        for node in nodes:
            node_type = node.get("type", "")
            node_id = node.get("id", "")
            node_label = node.get("data", {}).get("config", {}).get("label", node_id)
            
            if node_type in ["agent", "researcher", "business-analyst", "opportunity-classifier"]:
                config = node.get("data", {}).get("config", {})
                
                # Issue #1: Multi-agent node without output schema
                has_output_schema = bool(config.get("outputSchema"))
                has_downstream_hitl = WorkflowValidator._has_downstream_hitl(node_id, nodes, edges)
                
                if has_downstream_hitl and not has_output_schema:
                    issues.append({
                        "severity": "warning",
                        "node_id": node_id,
                        "node_label": node_label,
                        "issue": "Agent has HITL review but no outputSchema defined",
                        "impact": "Agent may ask questions indefinitely without producing reviewable deliverable",
                        "suggestion": "Add an outputSchema to define what structured output the agent should produce",
                        "auto_fix": None
                    })
                
                # Issue #2: Agent instructions that prevent deliverable production
                system_instructions = config.get("systemInstructions", "")
                blocking_phrases = [
                    "do not provide",
                    "should not provide",
                    "don't provide the output until",
                    "only provide when",
                    "wait until"
                ]
                
                for phrase in blocking_phrases:
                    if phrase.lower() in system_instructions.lower():
                        issues.append({
                            "severity": "warning",
                            "node_id": node_id,
                            "node_label": node_label,
                            "issue": f"System instructions contain blocking phrase: '{phrase}'",
                            "impact": "Agent may refuse to produce deliverable even when it should",
                            "suggestion": "Rephrase instructions to guide rather than block. Example: 'Gather information by asking questions, then produce deliverable' instead of 'Don't provide output until...'",
                            "auto_fix": None
                        })
                        break
                
        
        # Check for agents without any downstream nodes
        for node in nodes:
            node_type = node.get("type", "")
            node_id = node.get("id", "")
            
            if node_type in ["agent", "researcher"]:
                has_outgoing = any(e.get("source") == node_id for e in edges)
                if not has_outgoing:
                    # Check if this agent is part of a conditional branch
                    # If it's a target of a conditional edge, it's okay to have no outgoing connections
                    is_conditional_target = any(
                        e.get("target") == node_id and e.get("conditionId") is not None 
                        for e in edges
                    )
                    
                    # Only error if it's not part of a conditional workflow
                    if not is_conditional_target:
                        node_label = node.get("data", {}).get("config", {}).get("label", node_id)
                        issues.append({
                            "severity": "warning",  # Changed from "error" to "warning"
                            "node_id": node_id,
                            "node_label": node_label,
                            "issue": "Agent node has no outgoing connections",
                            "impact": "Agent output will end the workflow at this node",
                            "suggestion": "Consider connecting this agent to an END node, HITL node, or another agent to continue the workflow",
                            "auto_fix": None
                        })
        
        return issues
    
    @staticmethod
    def _has_downstream_hitl(node_id: str, nodes: List[Dict], edges: List[Dict]) -> bool:
        """Check if node has a HITL node downstream."""
        # Find immediate downstream nodes
        downstream_ids = [e.get("target") for e in edges if e.get("source") == node_id]
        
        for downstream_id in downstream_ids:
            # Find the node
            downstream_node = next((n for n in nodes if n.get("id") == downstream_id), None)
            if downstream_node:
                node_type = downstream_node.get("type", "")
                if node_type in ["hitl", "human-in-the-loop"]:
                    return True
        
        return False
    
    @staticmethod
    def auto_fix_common_issues(workflow_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically fix common workflow configuration issues.
        
        Args:
            workflow_json: Parsed workflow JSON
            
        Returns:
            Fixed workflow JSON
        """
        workflow = workflow_json.get("workflow", {})
        nodes = workflow.get("nodes", [])
        
        fixed_count = 0
        
        for node in nodes:
            node_type = node.get("type", "")
            
            if node_type in ["agent", "researcher", "business-analyst", "opportunity-classifier"]:
                config = node.get("data", {}).get("config", {})
                
                # Auto-fix #1: Add default outputSchema structure if has HITL but no schema
                # (Only suggest, don't actually add - requires user decision)
                pass
        
        if fixed_count > 0:
            logger.info("Auto-fixed %d workflow configuration issues", fixed_count)
        
        return workflow_json
    
    @staticmethod
    def validate_and_fix(workflow_json: Dict[str, Any], auto_fix: bool = True) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Validate workflow and optionally auto-fix issues.
        
        Args:
            workflow_json: Parsed workflow JSON
            auto_fix: Whether to automatically fix issues
            
        Returns:
            Tuple of (fixed_workflow, remaining_issues)
        """
        # Auto-fix if requested
        if auto_fix:
            workflow_json = WorkflowValidator.auto_fix_common_issues(workflow_json)
        
        # Validate
        issues = WorkflowValidator.validate_multi_agent_workflow(workflow_json)
        
        # Filter out auto-fixed issues
        if auto_fix:
            issues = [i for i in issues if i.get("severity") != "info" or not i.get("auto_fix")]
        
        return workflow_json, issues


def format_validation_report(issues: List[Dict[str, Any]]) -> str:
    """
    Format validation issues into a user-friendly report.
    
    Args:
        issues: List of validation issues
        
    Returns:
        Formatted report string
    """
    if not issues:
        return "✅ No workflow validation issues found."
    
    report = []
    
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]
    infos = [i for i in issues if i.get("severity") == "info"]
    
    if errors:
        report.append("❌ ERRORS (must fix):")
        for issue in errors:
            report.append(f"\n  • Node '{issue['node_label']}':")
            report.append(f"    Problem: {issue['issue']}")
            report.append(f"    Impact: {issue['impact']}")
            report.append(f"    Fix: {issue['suggestion']}")
    
    if warnings:
        report.append("\n⚠️  WARNINGS (recommended to fix):")
        for issue in warnings:
            report.append(f"\n  • Node '{issue['node_label']}':")
            report.append(f"    Problem: {issue['issue']}")
            report.append(f"    Impact: {issue['impact']}")
            report.append(f"    Fix: {issue['suggestion']}")
    
    if infos:
        report.append("\nℹ️  INFO (optional improvements):")
        for issue in infos:
            report.append(f"\n  • Node '{issue['node_label']}':")
            report.append(f"    {issue['issue']}")
            if issue.get("auto_fix"):
                report.append(f"    ✓ Auto-fixed: {issue['auto_fix']}")
    
    return "\n".join(report)

