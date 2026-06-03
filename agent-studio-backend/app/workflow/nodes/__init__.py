"""
Node executors for different workflow node types.

Each node type implements the BaseNode interface and can be executed
within a LangGraph workflow.
"""

from .base import BaseNode, NodeConfig
from .start import StartNode
from .end import EndNode
from .agent import AgentNode
from .tool import ToolNode
from .condition import ConditionNode
from .transform import TransformNode
from .human import HumanNode
from .hitl import HITLNode
from .subagent import SubagentNode
from .code_executor import CodeExecutorNode
from .powerpoint_generator import PowerpointGeneratorNode

# Node registry mapping node types to executor classes
NODE_REGISTRY = {
    "start": StartNode,
    "chat": StartNode,  # Chat node is a start node
    "end": EndNode,
    "agent": AgentNode,
    "opportunity-classifier": AgentNode,  # Custom agent type
    "researcher": AgentNode,  # Researcher node (supports Deep Research Mode)
    "business-analyst": AgentNode,  # Business analyst node
    "financial-modeler": AgentNode,  # Financial modeler node
    "tool": ToolNode,
    "condition": ConditionNode,
    "transform": TransformNode,
    "human": HumanNode,
    "hitl": HITLNode,  # Human-in-the-loop node
    "human-in-the-loop": HITLNode,  # Alternative name
    "subagent": SubagentNode,
    "code-executor": CodeExecutorNode,
    "powerpoint-generator": PowerpointGeneratorNode,
}

__all__ = [
    "BaseNode",
    "NodeConfig",
    "StartNode",
    "EndNode",
    "AgentNode",
    "ToolNode",
    "ConditionNode",
    "TransformNode",
    "HumanNode",
    "HITLNode",
    "SubagentNode",
    "CodeExecutorNode",
    "PowerpointGeneratorNode",
    "NODE_REGISTRY",
]


