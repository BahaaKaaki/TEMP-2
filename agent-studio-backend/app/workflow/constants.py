"""
Workflow state constants.

Defines constant keys used in workflow state dictionaries to replace magic strings.
"""

# State keys
STATE_MESSAGES = "messages"
STATE_NODE_OUTPUTS = "node_outputs"
STATE_DELIVERABLES = "deliverables"
STATE_PENDING_DELIVERABLE = "pending_deliverable"
STATE_VARIABLES = "variables"
STATE_INPUT_DATA = "input_data"
STATE_OUTPUT_DATA = "output_data"
STATE_ERROR = "error"
STATE_INTERRUPTED = "interrupted"
STATE_METADATA = "metadata"
STATE_CURRENT_NODE = "current_node"
STATE_WORKFLOW_ID = "workflow_id"
STATE_WORKFLOW_NAME = "workflow_name"
STATE_EXECUTION_ID = "execution_id"

# Metadata keys
META_STATUS = "status"
META_START_TIME = "start_time"
META_END_TIME = "end_time"

# Message types (for logging/debugging)
MSG_TYPE_HUMAN = "human"
MSG_TYPE_AI = "ai"
MSG_TYPE_SYSTEM = "system"
MSG_TYPE_TOOL = "tool"

# Tool execution
TOOL_MAX_ITERATIONS = 5  # Default max iterations for tool loops
TOOL_TIMEOUT_SECONDS = 300  # Default timeout for tool execution (5 minutes)

# Research mode
RESEARCH_MAX_SUBAGENTS = 5  # Maximum number of parallel research subagents
RESEARCH_MIN_SUBAGENTS = 2  # Minimum number of research subagents

# Deliverable fields
DELIVERABLE_ID = "deliverable_id"
DELIVERABLE_NODE_ID = "node_id"
DELIVERABLE_CONTENT = "content"
DELIVERABLE_STATUS = "status"
DELIVERABLE_APPROVED_AT = "approved_at"
DELIVERABLE_REJECTED_AT = "rejected_at"
DELIVERABLE_FEEDBACK = "feedback"

