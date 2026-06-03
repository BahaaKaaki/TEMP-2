"""
Workflow state management.

Defines the state structure that flows through the LangGraph workflow,
including messages, node outputs, variables, and execution metadata.
"""

from typing import TypedDict, Annotated, Sequence, Optional, Any, Dict, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from datetime import datetime
import json
import os


from config.keyvault import cfg

MAX_MESSAGES_IN_MEMORY = cfg.MAX_MESSAGES_IN_MEMORY
MAX_NODE_OUTPUTS_IN_MEMORY = cfg.MAX_NODE_OUTPUTS_IN_MEMORY


def add_messages_reducer(left: Sequence[BaseMessage], right: Sequence[BaseMessage]) -> Sequence[BaseMessage]:
    """
    Custom reducer for messages that appends right to left with intelligent pruning.
    
    Prevents unbounded memory growth by keeping only recent messages plus system messages.
    This fixes the critical memory leak in long-running conversations.
    
    LangGraph calls this with:
    - left: current state messages
    - right: new messages from node return
    
    Returns:
        Combined message list, pruned to MAX_MESSAGES_IN_MEMORY
    """
    # Convert to lists to ensure we can concatenate
    left_list = list(left) if left else []
    right_list = list(right) if right else []
    combined = left_list + right_list
    
    # Don't prune if we're under the limit
    if len(combined) <= MAX_MESSAGES_IN_MEMORY:
        return combined
    
    # Separate system messages (always keep) from conversation messages
    system_messages = [msg for msg in combined if isinstance(msg, SystemMessage)]
    conversation_messages = [msg for msg in combined if not isinstance(msg, SystemMessage)]
    
    # Keep most recent conversation messages
    # Reserve 10 slots for system messages, use rest for conversation
    max_conversation = MAX_MESSAGES_IN_MEMORY - min(len(system_messages), 10)
    pruned_conversation = conversation_messages[-max_conversation:] if max_conversation > 0 else []
    
    # Combine: system messages first, then recent conversation
    result = system_messages + pruned_conversation
    
    # Log pruning action
    if len(combined) > len(result):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"🧹 Memory pruning: {len(combined)} → {len(result)} messages "
            f"({len(system_messages)} system + {len(pruned_conversation)} conversation, "
            f"removed {len(combined) - len(result)} old messages)"
        )
    
    return result


def merge_node_outputs(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """
    Custom reducer for node_outputs that merges dicts with pruning.
    
    Prevents unbounded memory growth by keeping only recent node outputs.
    Old node outputs are removed to prevent memory accumulation.
    
    LangGraph calls this with:
    - left: current state node_outputs
    - right: new node_outputs from node return
    
    Returns:
        Merged dict, pruned to MAX_NODE_OUTPUTS_IN_MEMORY most recent entries
    """
    result = dict(left) if left else {}
    if right:
        result.update(right)
    
    # Prune if we exceed the limit
    if len(result) > MAX_NODE_OUTPUTS_IN_MEMORY:
        # Sort by timestamp (if available) or keep most recent entries
        sorted_items = sorted(
            result.items(),
            key=lambda x: x[1].get('timestamp', '9999-12-31') if isinstance(x[1], dict) else '9999-12-31',
            reverse=True
        )
        
        # Keep only the most recent MAX_NODE_OUTPUTS_IN_MEMORY entries
        result = dict(sorted_items[:MAX_NODE_OUTPUTS_IN_MEMORY])
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f"🧹 Memory pruning: node_outputs pruned to {len(result)} entries "
            f"(removed {len(sorted_items) - len(result)} old outputs)"
        )
    
    return result


class NodeOutput(TypedDict, total=False):
    """Output from a single node execution."""
    node_id: str
    node_type: str
    output: Any
    timestamp: str
    duration_ms: float
    status: str  # "success", "error", "skipped"
    error: Optional[str]


class ExecutionMetadata(TypedDict, total=False):
    """Metadata about the workflow execution."""
    execution_id: Optional[int]
    workflow_id: str
    workflow_name: str
    started_at: str
    completed_at: Optional[str]
    status: str  # "running", "completed", "failed", "paused", "pending_review"
    total_steps: int
    current_step: int
    current_agent_id: Optional[str]      # Which agent is currently executing
    current_agent_label: Optional[str]   # Human-readable agent name for UI
    user_id: Optional[str]               # Auth user running the workflow (for RLS + KB access)
    user_email: Optional[str]            # User email for Langfuse / observability
    session_id: Optional[str]            # Chat session that triggered this execution


class AgentDeliverable(TypedDict, total=False):
    """
    Structured deliverable produced by an agent or code-executor node.
    
    Represents the output from one node that becomes input for the next.
    Each deliverable can be reviewed by a human (via HITL) before proceeding.
    Code-executor deliverables carry an ``output_type`` for typed rendering.
    """
    deliverable_id: str               # Unique ID for this deliverable
    agent_id: str                     # Node ID that produced this
    agent_label: str                  # Human-readable agent name
    agent_type: str                   # Node type (e.g., "researcher", "code-executor")
    deliverable: Dict[str, Any]       # The actual structured output data
    schema: Optional[str]             # Expected output schema (for validation)
    status: str                       # "pending", "approved", "rejected"
    iteration: int                    # Which iteration (for rejected→retry flow)
    created_at: str                   # ISO timestamp
    approved_at: Optional[str]        # ISO timestamp when approved
    approved_by: Optional[str]        # User ID who approved
    review_notes: Optional[str]       # Feedback from reviewer
    previous_deliverable_id: Optional[str]  # Link to previous iteration
    # --- Code-executor extensions ---
    output_type: Optional[str]        # "data" | "table" | "chart" | "file" | "selection" | "form" | "sections"
    interactive: bool                 # Whether this deliverable expects user interaction
    user_response: Optional[Dict[str, Any]]  # Filled when user interacts with a widget


class AgentChatMessage(TypedDict, total=False):
    """
    Chat message with agent attribution for multi-agent workflows.
    
    Extends standard chat messages to track which agent sent each message,
    enabling clear visualization of multi-agent conversations in UI.
    """
    message_id: str                   # Unique message identifier
    agent_id: str                     # Which agent sent this message
    agent_label: str                  # Human-readable agent name (e.g., "Researcher")
    agent_type: str                   # Node type for icon/styling
    role: str                         # "user" or "assistant"
    content: str                      # Message content
    timestamp: str                    # ISO timestamp
    is_internal: bool                 # True if internal reasoning (not shown to user)


class WorkflowState(TypedDict):
    """
    State that flows through the workflow graph.
    
    This state is passed between nodes and updated by each node executor.
    LangGraph manages state transitions automatically.
    
    Enhanced for multi-agent workflows with deliverables and HITL review.
    """
    
    # Conversation messages (for chat-based workflows)
    # Using custom add_messages_reducer to properly append new messages from each node
    messages: Annotated[Sequence[BaseMessage], add_messages_reducer]
    
    # Current execution context
    current_node: str
    next_node: Optional[str]
    
    # Node execution results (merged via custom reducer)
    node_outputs: Annotated[Dict[str, NodeOutput], merge_node_outputs]
    
    # Workflow variables (accessible across all nodes)
    variables: Dict[str, Any]
    
    # Input data for the workflow
    input_data: Dict[str, Any]
    
    # Final output data
    output_data: Optional[Dict[str, Any]]
    
    # Human-in-the-loop support
    pending_user_input: Optional[Dict[str, Any]]
    user_input_response: Optional[Dict[str, Any]]
    
    # Multi-agent workflow support
    deliverables: List[AgentDeliverable]         # All deliverables produced in sequence
    current_agent_id: Optional[str]              # Which agent is currently executing
    current_agent_iteration: int                 # Loop count for current agent
    pending_deliverable: Optional[AgentDeliverable]  # Deliverable waiting for HITL review
    review_status: Dict[str, str]                # agent_id -> "approved"/"rejected"/"pending"
    
    # Error handling
    error: Optional[str]
    error_node: Optional[str]
    
    # Execution metadata
    metadata: ExecutionMetadata
    
    # Execution control
    should_continue: bool
    interrupted: bool
    force_deliver: bool


def get_workflow_id_from_state(state: WorkflowState) -> Optional[str]:
    """Return workflow id from state root or execution metadata."""
    if not state:
        return None
    wid = state.get("workflow_id")
    if wid:
        return str(wid)
    meta = state.get("metadata") or {}
    if isinstance(meta, dict):
        meta_wid = meta.get("workflow_id")
        if meta_wid:
            return str(meta_wid)
    return None


def get_session_id_from_state(state: WorkflowState) -> Optional[str]:
    """Return chat session id from execution metadata."""
    if not state:
        return None
    meta = state.get("metadata") or {}
    if isinstance(meta, dict):
        sid = meta.get("session_id")
        if sid:
            return str(sid)
    return None


def create_initial_state(
    workflow_id: str,
    workflow_name: str,
    input_data: Dict[str, Any],
    execution_id: Optional[int] = None,
    initial_message: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    session_id: Optional[str] = None,
) -> WorkflowState:
    """
    Create the initial workflow state.
    
    Args:
        workflow_id: ID of the workflow being executed
        workflow_name: Name of the workflow
        input_data: Input data for the workflow
        execution_id: Database execution ID (if available)
        initial_message: Optional initial user message
        
    Returns:
        Initial WorkflowState
    """
    # With 'add' reducer, start with EMPTY messages list
    # The initial_message will be added via input_data and processed by nodes
    messages = []
    
    return WorkflowState(
        messages=messages,
        current_node="__start__",
        next_node=None,
        node_outputs={},
        variables={},
        input_data=input_data,
        output_data=None,
        pending_user_input=None,
        user_input_response=None,
        deliverables=[],                    # Initialize empty deliverables list
        current_agent_id=None,              # No agent executing yet
        current_agent_iteration=0,          # Start at iteration 0
        pending_deliverable=None,           # No deliverable pending review
        review_status={},                   # No reviews yet
        error=None,
        error_node=None,
        metadata=ExecutionMetadata(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            started_at=datetime.utcnow().isoformat(),
            completed_at=None,
            status="running",
            total_steps=0,
            current_step=0,
            user_id=user_id,
            user_email=user_email,
            session_id=session_id,
        ),
        should_continue=True,
        interrupted=False,
        force_deliver=False
    )


def update_state_with_node_output(
    state: WorkflowState,
    node_id: str,
    node_type: str,
    output: Any,
    duration_ms: float,
    status: str = "success",
    error: Optional[str] = None
) -> WorkflowState:
    """
    Update state with the output from a node execution.
    
    Args:
        state: Current workflow state
        node_id: ID of the executed node
        node_type: Type of the node
        output: Output data from the node
        duration_ms: Execution duration in milliseconds
        status: Execution status
        error: Error message if any
        
    Returns:
        Updated WorkflowState
    """
    # Filter out 'messages' from output before storing in node_outputs
    # Messages are managed by LangGraph state and shouldn't be in node_outputs
    # (they're not JSON serializable and would cause storage errors)
    if isinstance(output, dict) and "messages" in output:
        output_for_storage = {k: v for k, v in output.items() if k != "messages"}
    else:
        output_for_storage = output
    
    node_output = NodeOutput(
        node_id=node_id,
        node_type=node_type,
        output=output_for_storage,
        timestamp=datetime.utcnow().isoformat(),
        duration_ms=duration_ms,
        status=status,
        error=error
    )
    
    # Update node outputs
    state["node_outputs"][node_id] = node_output
    
    # Update current node
    state["current_node"] = node_id
    
    # Update metadata
    state["metadata"]["current_step"] = len(state["node_outputs"])
    
    # Handle errors
    if status == "error":
        state["error"] = error
        state["error_node"] = node_id
        state["should_continue"] = False
        state["metadata"]["status"] = "failed"
    
    return state


def serialize_state_for_storage(state: WorkflowState, compact: bool = True) -> str:
    """
    Serialize workflow state to JSON for database storage with optimizations.
    
    Performance optimizations:
    - Uses compact JSON (no indentation) by default - saves 30-50% space and time
    - Efficient message serialization with minimal data extraction
    - Skips None/empty values to reduce payload size
    
    Args:
        state: Workflow state to serialize
        compact: If True, use compact JSON (no indentation). Default: True for performance
        
    Returns:
        JSON string representation
    """
    # Convert messages to dict format with unique IDs (optimized loop)
    messages_data = []
    for idx, msg in enumerate(state.get("messages", [])):
        # Get existing message_id from additional_kwargs, or generate new one
        additional_kwargs = getattr(msg, "additional_kwargs", {})
        msg_id = additional_kwargs.get("message_id") if additional_kwargs else None
        if not msg_id:
            # Generate message_id based on conversation position for consistency
            msg_id = f"msg_{idx + 1}"
        
        messages_data.append({
            "message_id": msg_id,
            "type": msg.__class__.__name__,
            "content": msg.content,
            "additional_kwargs": additional_kwargs
        })
    
    # Build state dict, skipping None/empty values to reduce payload size
    serializable_state = {
        "state_version": 2,  # Version tracking for future migrations
        "messages": messages_data,
        "node_outputs": state.get("node_outputs", {}),
        "variables": state.get("variables", {}),
        "deliverables": state.get("deliverables", []),
        "metadata": state.get("metadata", {}),
        "should_continue": state.get("should_continue", True),
        "interrupted": state.get("interrupted", False),
        "force_deliver": state.get("force_deliver", False)
    }
    
    # Add optional fields only if they have values (reduces payload)
    optional_fields = [
        ("current_node", state.get("current_node")),
        ("next_node", state.get("next_node")),
        ("input_data", state.get("input_data")),
        ("output_data", state.get("output_data")),
        ("pending_user_input", state.get("pending_user_input")),
        ("user_input_response", state.get("user_input_response")),
        ("current_agent_id", state.get("current_agent_id")),
        ("current_agent_iteration", state.get("current_agent_iteration", 0)),
        ("pending_deliverable", state.get("pending_deliverable")),
        ("review_status", state.get("review_status")),
        ("error", state.get("error")),
        ("error_node", state.get("error_node"))
    ]
    
    for field, value in optional_fields:
        if value is not None and value != {} and value != [] and value != 0:
            serializable_state[field] = value
    
    # Use compact JSON (no indentation) for 30-50% faster serialization and smaller size
    return json.dumps(serializable_state, separators=(',', ':') if compact else (', ', ': '))


def deserialize_state_from_storage(json_str: str) -> WorkflowState:
    """
    Deserialize workflow state from JSON storage.
    
    Handles backward compatibility with v1 states (pre-multi-agent).
    
    Args:
        json_str: JSON string representation
        
    Returns:
        WorkflowState object
    """
    data = json.loads(json_str)
    
    # Check state version for migration
    state_version = data.get("state_version", 1)
    
    # Convert message dicts back to LangChain message objects
    messages = []
    for msg_data in data.get("messages", []):
        msg_type = msg_data.get("type")
        content = msg_data.get("content")
        message_id = msg_data.get("message_id")
        additional_kwargs = msg_data.get("additional_kwargs", {})
        
        # Preserve message_id in additional_kwargs for tracking
        if message_id and "message_id" not in additional_kwargs:
            additional_kwargs["message_id"] = message_id
        
        if msg_type == "HumanMessage":
            messages.append(HumanMessage(content=content, additional_kwargs=additional_kwargs))
        elif msg_type == "AIMessage":
            messages.append(AIMessage(content=content, additional_kwargs=additional_kwargs))
        elif msg_type == "SystemMessage":
            messages.append(SystemMessage(content=content, additional_kwargs=additional_kwargs))
    
    # Build base state
    base_state = {
        "messages": messages,
        "current_node": data.get("current_node", "__start__"),
        "next_node": data.get("next_node"),
        "node_outputs": data.get("node_outputs", {}),
        "variables": data.get("variables", {}),
        "input_data": data.get("input_data", {}),
        "output_data": data.get("output_data"),
        "pending_user_input": data.get("pending_user_input"),
        "user_input_response": data.get("user_input_response"),
        "error": data.get("error"),
        "error_node": data.get("error_node"),
        "metadata": data.get("metadata", {}),
        "should_continue": data.get("should_continue", True),
        "interrupted": data.get("interrupted", False),
        "force_deliver": data.get("force_deliver", False)
    }
    
    # Add multi-agent fields (v2+)
    if state_version >= 2:
        base_state.update({
            "deliverables": data.get("deliverables", []),
            "current_agent_id": data.get("current_agent_id"),
            "current_agent_iteration": data.get("current_agent_iteration", 0),
            "pending_deliverable": data.get("pending_deliverable"),
            "review_status": data.get("review_status", {})
        })
    else:
        # Migrate v1 state to v2 (add default values)
        base_state.update({
            "deliverables": [],
            "current_agent_id": None,
            "current_agent_iteration": 0,
            "pending_deliverable": None,
            "review_status": {}
        })
    
    return WorkflowState(**base_state)


def get_node_output(state: WorkflowState, node_id: str) -> Optional[Any]:
    """
    Get the output from a specific node.
    
    Args:
        state: Current workflow state
        node_id: ID of the node
        
    Returns:
        Output from the node, or None if not found
    """
    node_output = state.get("node_outputs", {}).get(node_id)
    if node_output:
        return node_output.get("output")
    return None


def get_variable(state: WorkflowState, key: str, default: Any = None) -> Any:
    """
    Get a workflow variable.
    
    Args:
        state: Current workflow state
        key: Variable key
        default: Default value if not found
        
    Returns:
        Variable value
    """
    return state.get("variables", {}).get(key, default)


def set_variable(state: WorkflowState, key: str, value: Any) -> WorkflowState:
    """
    Set a workflow variable.
    
    Args:
        state: Current workflow state
        key: Variable key
        value: Variable value
        
    Returns:
        Updated WorkflowState
    """
    if "variables" not in state:
        state["variables"] = {}
    state["variables"][key] = value
    return state


# ============================================================================
# MULTI-AGENT WORKFLOW HELPERS
# ============================================================================

def add_deliverable_to_state(
    state: WorkflowState,
    agent_id: str,
    agent_label: str,
    agent_type: str,
    deliverable_data: Dict[str, Any],
    schema: Optional[str] = None
) -> WorkflowState:
    """
    Add a new deliverable to the workflow state.
    
    Args:
        state: Current workflow state
        agent_id: Node ID that produced the deliverable
        agent_label: Human-readable agent name
        agent_type: Node type (e.g., "researcher")
        deliverable_data: The structured output data
        schema: Expected output schema (for validation)
        
    Returns:
        Updated WorkflowState
    """
    import uuid
    
    deliverable = AgentDeliverable(
        deliverable_id=str(uuid.uuid4()),
        agent_id=agent_id,
        agent_label=agent_label,
        agent_type=agent_type,
        deliverable=deliverable_data,
        schema=schema,
        status="pending",
        iteration=state.get("current_agent_iteration", 1),
        created_at=datetime.utcnow().isoformat(),
        approved_at=None,
        approved_by=None,
        review_notes=None,
        previous_deliverable_id=None
    )
    
    if "deliverables" not in state:
        state["deliverables"] = []
    
    state["deliverables"].append(deliverable)
    return state


def get_deliverables_for_agent(
    state: WorkflowState,
    agent_id: Optional[str] = None
) -> List[AgentDeliverable]:
    """
    Get all deliverables, optionally filtered by agent.
    
    Args:
        state: Current workflow state
        agent_id: Optional agent ID to filter by
        
    Returns:
        List of deliverables
    """
    deliverables = state.get("deliverables", [])
    
    if agent_id:
        return [d for d in deliverables if d.get("agent_id") == agent_id]
    
    return deliverables


def get_previous_deliverables(
    state: WorkflowState,
    current_agent_id: str,
    specific_agent_ids: Optional[List[str]] = None
) -> List[AgentDeliverable]:
    """
    Get all approved deliverables from previous agents.
    
    Args:
        state: Current workflow state
        current_agent_id: ID of current agent (to exclude its own deliverables)
        specific_agent_ids: Optional list of specific agent IDs to include (if None, includes all)
        
    Returns:
        List of approved deliverables from previous agents
    """
    deliverables = state.get("deliverables", [])
    
    # Filter approved deliverables (excluding current agent's own)
    filtered = [
        d for d in deliverables
        if d.get("agent_id") != current_agent_id
        and d.get("status") == "approved"
    ]
    
    # If specific agent IDs are requested, filter further
    if specific_agent_ids is not None:
        filtered = [
            d for d in filtered
            if d.get("agent_id") in specific_agent_ids
        ]
    
    return filtered


def resolve_deliverable_sources(
    state: WorkflowState,
    current_agent_id: str,
    node_config: Dict[str, Any]
) -> List[AgentDeliverable]:
    """
    Resolve which previous deliverables an agent should receive based on its
    ``deliverableSources`` config.

    Backward-compatible: existing workflows that only have
    ``includePreviousDeliverables`` (or neither field) keep working unchanged.

    Config value semantics:
        - ``"all"`` / ``None`` / missing  → all approved previous deliverables
        - ``"none"`` / ``False``          → no deliverables
        - ``[id1, id2, ...]``            → only deliverables from those agent IDs
    """
    sources = node_config.get("deliverableSources")

    if sources is None or sources == "":
        legacy = node_config.get("includePreviousDeliverables", True)
        if not legacy:
            return []
        return get_previous_deliverables(state, current_agent_id)

    if sources == "all" or sources is True:
        return get_previous_deliverables(state, current_agent_id)

    if sources == "none" or sources is False:
        return []

    if isinstance(sources, list):
        return get_previous_deliverables(
            state, current_agent_id, specific_agent_ids=sources
        )

    return get_previous_deliverables(state, current_agent_id)


def mark_deliverable_reviewed(
    state: WorkflowState,
    deliverable_id: str,
    status: str,  # "approved" or "rejected"
    approved_by: Optional[str] = None,
    review_notes: Optional[str] = None
) -> WorkflowState:
    """
    Mark a deliverable as reviewed (approved or rejected).
    
    Args:
        state: Current workflow state
        deliverable_id: ID of the deliverable
        status: "approved" or "rejected"
        approved_by: User ID who reviewed
        review_notes: Feedback from reviewer
        
    Returns:
        Updated WorkflowState
    """
    deliverables = state.get("deliverables", [])
    
    for deliverable in deliverables:
        if deliverable.get("deliverable_id") == deliverable_id:
            deliverable["status"] = status
            deliverable["approved_at"] = datetime.utcnow().isoformat()
            deliverable["approved_by"] = approved_by
            deliverable["review_notes"] = review_notes
            break
    
    return state


def format_deliverables_for_prompt(
    deliverables: List[AgentDeliverable]
) -> str:
    """
    Format deliverables into a string for LLM prompt injection.
    
    Args:
        deliverables: List of deliverables to format
        
    Returns:
        Formatted string with all deliverables
    """
    if not deliverables:
        return "No previous agent outputs available."
    
    formatted = "## PREVIOUS AGENT OUTPUTS (AUTHORITATIVE - USE EXACTLY AS PROVIDED):\n\n"
    formatted += "⚠️ CRITICAL: These outputs from previous agents have been reviewed and approved.\n"
    formatted += "They are your PRIMARY DATA SOURCE. Use them exactly as provided - DO NOT re-analyze or contradict them.\n\n"
    formatted += (
        "Numbering starts at **0**: the first block below is **[0]**, the second **[1]**, "
        "matching `inputs[\"deliverables\"][0]`, `[1]`, … in Code Executor scripts.\n\n"
    )

    for idx, d in enumerate(deliverables):
        formatted += (
            f"### [{idx}] From {d.get('agent_label', 'Unknown Agent')} "
            f"(Status: {d.get('status', 'unknown').upper()}):\n"
        )
        formatted += f"```json\n{json.dumps(d.get('deliverable', {}), indent=2)}\n```\n\n"
    
    return formatted


_DELIVERABLE_MARKDOWN_SKIP_KEYS = frozenset({
    "_output_type",
    "_metadata",
    "_interactive",
    "_execution_log",
    "_output_files",
    "_visualization",
    "_raw",
    "_user_response",
})


def _markdown_titleize_key(key: str) -> str:
    return str(key).replace("_", " ").strip().title() or "Field"


def _should_skip_markdown_key(key: str) -> bool:
    return key in _DELIVERABLE_MARKDOWN_SKIP_KEYS or str(key).startswith("_")


def _scalar_to_markdown(value: Any) -> str:
    if value is None:
        return "_null_"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text if text else "_empty_"
    return json.dumps(value, indent=2, default=str)


def _value_to_markdown(value: Any, depth: int = 0) -> str:
    """Recursively render any JSON-like value as markdown."""
    if isinstance(value, dict):
        return _dict_to_markdown(value, depth)
    if isinstance(value, list):
        if not value:
            return "_empty list_"
        lines: List[str] = []
        for idx, item in enumerate(value):
            if isinstance(item, dict):
                lines.append(f"{'  ' * depth}{idx + 1}.")
                lines.append(_dict_to_markdown(item, depth + 1))
            else:
                lines.append(
                    f"{'  ' * depth}- {_scalar_to_markdown(item)}"
                )
        return "\n".join(lines)
    return _scalar_to_markdown(value)


def _dict_to_markdown(obj: Dict[str, Any], depth: int = 0) -> str:
    """Walk every key in a deliverable object and emit markdown sections."""
    parts: List[str] = []
    indent = "  " * depth
    heading = "###" if depth == 0 else "####"

    for key, val in obj.items():
        if _should_skip_markdown_key(key):
            continue
        title = _markdown_titleize_key(key)

        if isinstance(val, dict) and val:
            visible = {
                k: v for k, v in val.items() if not _should_skip_markdown_key(k)
            }
            if not visible:
                continue
            parts.append(f"{indent}{heading} {title}\n")
            parts.append(_dict_to_markdown(visible, depth + 1))
        elif isinstance(val, list) and val:
            if all(isinstance(x, dict) for x in val):
                parts.append(f"{indent}{heading} {title}\n")
                for idx, item in enumerate(val):
                    item_visible = {
                        k: v
                        for k, v in item.items()
                        if not _should_skip_markdown_key(k)
                    }
                    if not item_visible:
                        continue
                    parts.append(f"{indent}##### {title} {idx + 1}\n")
                    parts.append(_dict_to_markdown(item_visible, depth + 1))
            else:
                parts.append(f"{indent}**{title}:**\n")
                for item in val:
                    parts.append(f"{indent}- {_value_to_markdown(item, depth + 1)}")
        else:
            rendered = _value_to_markdown(val, depth + 1)
            if "\n" in rendered:
                parts.append(f"{indent}**{title}:**\n\n{rendered}\n")
            else:
                parts.append(f"{indent}**{title}:** {rendered}\n")

    return "\n".join(parts) + ("\n" if parts else "")


def _deliverable_body_to_markdown(body: Any) -> str:
    """Convert a single deliverable payload to markdown (all keys and fields)."""
    if body is None:
        return "_No content._\n\n"
    if isinstance(body, str):
        return f"{body.strip()}\n\n" if body.strip() else "_Empty._\n\n"
    if isinstance(body, list):
        return _value_to_markdown(body) + "\n"
    if isinstance(body, dict):
        md = _dict_to_markdown(body)
        if md.strip():
            return md + "\n"
        return f"```json\n{json.dumps(body, indent=2, default=str)}\n```\n\n"
    return f"```json\n{json.dumps(body, indent=2, default=str)}\n```\n\n"


def format_deliverables_as_markdown(
    deliverables: List[AgentDeliverable],
) -> str:
    """
    Format approved upstream deliverables as markdown for Edwin handoff.

    Args:
        deliverables: Resolved deliverables from ``resolve_deliverable_sources``.

    Returns:
        Markdown document combining all deliverables.
    """
    if not deliverables:
        return ""

    lines = [
        "# Workflow deliverables\n",
        "The following outputs were produced by earlier steps in this workflow.\n",
    ]

    for idx, d in enumerate(deliverables):
        label = d.get("agent_label") or "Unknown step"
        agent_type = d.get("agent_type") or "unknown"
        status = (d.get("status") or "unknown").upper()
        lines.append(f"## [{idx}] {label} ({agent_type}, {status})\n")
        body = d.get("deliverable") or {}
        lines.append(_deliverable_body_to_markdown(body))

    return "\n".join(lines).strip() + "\n"


