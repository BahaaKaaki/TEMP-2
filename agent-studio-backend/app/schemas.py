"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


# WorkflowEntity Schemas
class WorkflowEntityBase(BaseModel):
    """Base schema for WorkflowEntity with common fields"""
    name: str = Field(..., min_length=1, max_length=128, description="Workflow display name")
    description: Optional[str] = Field(None, max_length=512, description="Workflow description")
    active: bool = Field(default=True, description="Whether workflow is active")
    nodes: Optional[str] = Field(None, description="Node definitions (JSON array)")
    connections: Optional[str] = Field(None, description="Node connection mappings (JSON object)")
    settings: Optional[str] = Field(None, description="Workflow settings (JSON)")
    staticData: Optional[str] = Field(None, description="Persistent data between executions (JSON)")
    pinData: Optional[str] = Field(None, description="Pinned test data for nodes (JSON)")
    versionId: Optional[str] = Field(None, max_length=36, description="Current version UUID")
    triggerCount: Optional[int] = Field(0, ge=0, description="Number of trigger nodes")
    meta: Optional[str] = Field(None, description="Additional metadata (JSON)")
    parentFolderId: Optional[str] = Field(None, max_length=36, description="Containing folder UUID")
    isArchived: bool = Field(default=False, description="Soft delete flag")
    isDraft: bool = Field(default=True, description="True if no version has been published yet")
    isPublic: bool = Field(default=False, description="True if shared in marketplace")
    marketplaceName: Optional[str] = Field(None, max_length=255, description="Display name in marketplace")
    marketplaceDescription: Optional[str] = Field(None, description="Description for marketplace listing")
    approvedVersionId: Optional[str] = Field(None, max_length=36, description="Last admin-approved version for marketplace")
    icon: Optional[str] = Field(None, max_length=512, description="URL of uploaded icon image")


class WorkflowEntityCreate(WorkflowEntityBase):
    """Schema for creating a new workflow"""
    id: Optional[str] = Field(None, max_length=36, description="UUID identifier (auto-generated if not provided)")


class WorkflowEntityUpdate(BaseModel):
    """Schema for updating an existing workflow (all fields optional)"""
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    active: Optional[bool] = None
    nodes: Optional[str] = None
    connections: Optional[str] = None
    settings: Optional[str] = None
    staticData: Optional[str] = None
    pinData: Optional[str] = None
    versionId: Optional[str] = Field(None, max_length=36)
    triggerCount: Optional[int] = Field(None, ge=0)
    meta: Optional[str] = None
    parentFolderId: Optional[str] = Field(None, max_length=36)
    isArchived: Optional[bool] = None
    isDraft: Optional[bool] = None
    icon: Optional[str] = Field(None, max_length=512, description="URL of uploaded icon image")


class WorkflowEntityResponse(WorkflowEntityBase):
    """Schema for workflow response"""
    id: str = Field(..., description="UUID identifier")
    createdById: str = Field(..., description="User who created the workflow")
    createdByName: Optional[str] = Field(None, description="Name of user who created the workflow")
    createdAt: datetime = Field(..., description="Creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")
    isPinned: bool = Field(default=False, description="Whether workflow is pinned")
    lastAccessedAt: Optional[datetime] = Field(None, description="Last access timestamp")
    shareAccess: Optional[str] = Field(
        None,
        description="Effective access for current user: owner | read | write",
    )

    class Config:
        from_attributes = True  # Pydantic v2
        orm_mode = True  # Pydantic v1 compatibility


class WorkflowEntityList(BaseModel):
    """Schema for paginated workflow list"""
    total: int = Field(..., description="Total number of workflows")
    items: list[WorkflowEntityResponse] = Field(..., description="List of workflows")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")


# Health Check Schemas
class HealthCheckResponse(BaseModel):
    """Schema for health check response"""
    status: str
    timestamp: str
    service: str
    database: dict
    redis: dict
    instance: dict


class DatabaseStatus(BaseModel):
    """Schema for database connection status"""
    postgres: bool
    redis: bool
    status: str
    postgres_error: Optional[str] = None
    redis_error: Optional[str] = None


# Workflow Execution Schemas
class WorkflowExecutionInput(BaseModel):
    """Schema for workflow execution request"""
    input_data: dict = Field(default_factory=dict, description="Input data for the workflow")
    initial_message: Optional[str] = Field(None, description="Optional initial message for chat workflows")
    variables: dict = Field(default_factory=dict, description="Initial workflow variables")


class WorkflowExecutionResponse(BaseModel):
    """Schema for workflow execution response"""
    execution_id: int = Field(..., description="Database execution ID")
    workflow_id: str = Field(..., description="Workflow UUID")
    status: str = Field(..., description="Execution status (running, completed, failed, paused)")
    started_at: str = Field(..., description="Execution start timestamp")
    message: str = Field(..., description="Status message")


class ExecutionStatusResponse(BaseModel):
    """Schema for execution status query response"""
    execution_id: int
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    current_step: int
    total_steps: int
    output_data: Optional[dict] = None
    error: Optional[str] = None
    error_node: Optional[str] = None
    node_outputs: dict = Field(default_factory=dict, description="Outputs from each node")


class ExecutionResumeInput(BaseModel):
    """Schema for resuming a paused execution"""
    user_input: dict = Field(..., description="User input to resume execution")


class ExecutionListResponse(BaseModel):
    """Schema for paginated execution list"""
    total: int
    items: list[ExecutionStatusResponse]
    page: int
    page_size: int
    total_pages: int


class ExecutionEventStream(BaseModel):
    """Schema for execution event streaming"""
    event_type: str = Field(..., description="Event type (node_start, node_end, message, error, complete)")
    timestamp: str
    data: dict = Field(default_factory=dict)
    node_id: Optional[str] = None
    message: Optional[str] = None

# Chat Session Schemas
class CreateSessionRequest(BaseModel):
    """Schema for creating a new chat session/instance"""
    name: Optional[str] = Field(None, description="Session name (auto-generated if not provided)")
    description: Optional[str] = Field(None, description="Session description")
    variables: dict = Field(default_factory=dict, description="Session-scoped variables")
    metadata: dict = Field(default_factory=dict, description="Custom metadata")
    user_id: Optional[str] = Field(None, description="User ID (optional)")
    project_id: Optional[str] = Field(None, max_length=36, description="Project UUID to assign session to")


class UpdateSessionRequest(BaseModel):
    """Schema for updating session metadata"""
    name: Optional[str] = Field(None, description="New session name")
    description: Optional[str] = Field(None, description="New session description")
    status: Optional[str] = Field(None, description="Session status (active, archived)")
    metadata: Optional[dict] = Field(None, description="Custom metadata")
    project_id: Optional[str] = Field(None, max_length=36, description="Project UUID (set null to unassign)")


class SendMessageRequest(BaseModel):
    """Schema for sending a message to a chat session"""
    message: str = Field(..., description="User message to send")
    variables: dict = Field(default_factory=dict, description="Additional variables for this message")
    force_deliver: bool = Field(default=False, description="Force the current agent to produce its deliverable immediately")
    question_message_id: Optional[str] = Field(
        None,
        description=(
            "Set when this user message is the answer to a QuestionsCard. "
            "The backend uses it to stamp 'answered_at' on the matching "
            "agent message so the UI can render it as resolved."
        ),
    )
    question_response: Optional[dict] = Field(
        None,
        description=(
            "Structured answers keyed by question id. Stored on the user "
            "HumanMessage's metadata for audit + future restore."
        ),
    )


class ChatSessionResponse(BaseModel):
    """Schema for chat session response"""
    id: str = Field(..., description="Session UUID")
    workflowId: str = Field(..., description="Workflow UUID")
    name: Optional[str] = Field(None, description="Session name")
    description: Optional[str] = Field(None, description="Session description")
    status: str = Field(..., description="Session status")
    messageCount: int = Field(..., description="Total messages in session")
    createdAt: datetime = Field(..., description="Creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")
    lastMessageAt: Optional[datetime] = Field(None, description="Last message timestamp")
    isPinned: bool = Field(default=False, description="Whether session is pinned")
    lastAccessedAt: Optional[datetime] = Field(None, description="Last access timestamp")
    projectId: Optional[str] = Field(None, description="Assigned project UUID")
    
    class Config:
        from_attributes = True
        orm_mode = True


class ChatMessage(BaseModel):
    """Schema for a single chat message"""
    message_id: Optional[str] = Field(None, description="Message UUID")
    role: str = Field(..., description="Message role (user/assistant)")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")
    agent_id: Optional[str] = Field(None, description="Agent ID (for assistant messages)")
    agent_label: Optional[str] = Field(None, description="Agent label (for assistant messages)")
    agent_type: Optional[str] = Field(None, description="Agent type (for assistant messages)")
    citations: Optional[list[dict]] = Field(
        None, 
        description="Minimal citation references (chunk_id, kb_id, citation_number). Full details fetched on-demand."
    )
    structured_queries: Optional[list[dict]] = Field(
        None,
        description="SQL queries executed during this message (sql, tables_used, row_count, question)."
    )
    questions: Optional[dict] = Field(
        None,
        description=(
            "Multi-question questionnaire payload (rendered as an inline "
            "QuestionsCard). Set when an agent paused via the "
            "ask_user_questions tool, or when a Chat/Agent node has "
            "hand-configured initial/startup questions."
        ),
    )
    answered_at: Optional[str] = Field(
        None,
        description=(
            "ISO timestamp when the user submitted answers to the questions "
            "carried by this message. Used by the UI to render the answered/"
            "collapsed state."
        ),
    )


class ChatSessionDetailResponse(BaseModel):
    """Schema for detailed session with conversation history"""
    session: ChatSessionResponse
    execution_count: int = Field(..., description="Number of executions in this session")
    execution_status: Optional[str] = Field(None, description="Status of latest execution (running, completed, paused, pending_review, failed, cancelled)")
    execution_id: Optional[int] = Field(None, description="ID of the latest execution (for SSE streaming)")
    conversation_history: list[ChatMessage] = Field(default_factory=list, description="Full conversation history")


class SessionChatResponse(BaseModel):
    """Schema for chat response in session context"""
    session_id: str = Field(..., description="Chat session UUID")
    message: str = Field(..., description="Assistant response")
    role: str = Field(default="assistant", description="Response role")
    timestamp: str = Field(..., description="Response timestamp")
    status: str = Field(..., description="Execution status")
    execution_id: Optional[int] = Field(None, description="Execution ID for live SSE trace streaming")
    conversation_history: list[ChatMessage] = Field(default_factory=list, description="Full conversation history")
    pending_deliverable: Optional[dict] = Field(None, description="Deliverable waiting for HITL review")


# Multi-Agent Deliverable Schemas
class DeliverableResponse(BaseModel):
    """Schema for agent deliverable response"""
    id: str = Field(..., description="Deliverable UUID")
    sessionId: str = Field(..., description="Associated chat session UUID")
    executionId: int = Field(..., description="Associated execution ID")
    agentId: str = Field(..., description="Node ID that produced this deliverable")
    agentLabel: str = Field(..., description="Human-readable agent name")
    agentType: str = Field(..., description="Node type (e.g., 'researcher', 'business-analyst')")
    deliverable: dict = Field(..., description="Structured output data")
    deliverableSchema: Optional[str] = Field(None, description="Expected output schema (JSON)")
    status: str = Field(..., description="Review status (pending, approved, rejected)")
    iteration: int = Field(..., description="Iteration number (for retry cycles)")
    reviewedAt: Optional[datetime] = Field(None, description="Review timestamp")
    reviewedBy: Optional[str] = Field(None, description="User UUID who reviewed")
    reviewNotes: Optional[str] = Field(None, description="Feedback from reviewer")
    previousDeliverableId: Optional[str] = Field(None, description="Previous iteration UUID")
    createdAt: datetime = Field(..., description="Creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")
    outputType: Optional[str] = Field(None, description="Typed output kind: data, table, chart, file, selection, form, sections")
    interactive: bool = Field(False, description="Whether this deliverable expects user interaction")
    userResponse: Optional[dict] = Field(None, description="User's response to an interactive widget")
    openuiLang: Optional[str] = Field(None, description="Pre-translated OpenUI Lang (null = not yet translated)")
    
    class Config:
        from_attributes = True
        orm_mode = True


class DeliverableListResponse(BaseModel):
    """Schema for list of deliverables in a session"""
    session_id: str = Field(..., description="Chat session UUID")
    total: int = Field(..., description="Total deliverables count")
    deliverables: list[DeliverableResponse] = Field(default_factory=list, description="List of deliverables")


class DeliverableApprovalRequest(BaseModel):
    """Schema for approving a deliverable"""
    review_notes: Optional[str] = Field(None, description="Optional feedback notes")
    edited_deliverable: Optional[dict] = Field(None, description="Edited deliverable content (if modified)")
    reviewed_by: Optional[str] = Field(None, description="User UUID who reviewed")


class DeliverableRejectionRequest(BaseModel):
    """Schema for rejecting a deliverable"""
    review_notes: str = Field(default="", description="Feedback explaining why rejected")
    reviewed_by: Optional[str] = Field(None, description="User UUID who reviewed")


class DeliverableApprovalResponse(BaseModel):
    """Schema for approval/rejection response"""
    deliverable_id: str = Field(..., description="Deliverable UUID")
    status: str = Field(..., description="New status (approved/rejected)")
    workflow_resumed: bool = Field(..., description="Whether workflow execution resumed")
    next_agent: Optional[Dict[str, Any]] = Field(None, description="Next agent info (if resumed)")
    startup_message: Optional[str] = Field(None, description="Startup message from next agent")
    startup_message_full: Optional[Dict[str, Any]] = Field(None, description="Complete startup message object for UI display")
    message: str = Field(..., description="Status message")
    # ── Post-resume snapshot (included by /respond so the UI can update
    #    the deliverables pane synchronously for chained output.ask()
    #    sequences without relying on a secondary GET).  Always None for
    #    /approve and /reject to keep the payload minimal there. ──
    updated_deliverables: Optional[list[DeliverableResponse]] = Field(
        None,
        description="Session's deliverables after resume (for chained widget flows)",
    )
    execution_status: Optional[str] = Field(
        None,
        description="Current execution status after resume (running/paused/completed/...)",
    )
    execution_id: Optional[int] = Field(None, description="Active execution ID after resume")


class DeliverableWidgetResponse(BaseModel):
    """Schema for responding to an interactive widget (selection / form)."""
    response: dict = Field(..., description="User's response payload (selected value, form values, etc.)")
    reviewed_by: Optional[str] = Field(None, description="User UUID")


# ============================================================================
# FILE UPLOAD SCHEMAS
# ============================================================================

class FileUploadResponse(BaseModel):
    """Schema for file upload response"""
    file_id: str = Field(..., description="File UUID")
    file_name: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="File extension")
    file_size: int = Field(..., description="File size in bytes")
    parsing_status: str = Field(..., description="Parsing status (pending/completed/failed)")
    extracted_text_preview: Optional[str] = Field(None, description="Preview of extracted text (first 500 chars)")
    message: str = Field(..., description="Status message")
    scope: Optional[str] = Field(
        None,
        description="File visibility scope: 'local' (only the uploading agent) or 'global' (every agent).",
    )
    uploaded_at_agent_id: Optional[str] = Field(
        None,
        description="Workflow node id of the agent that was active when this file was uploaded.",
    )
    uploaded_at_agent_label: Optional[str] = Field(
        None,
        description="Human-readable label of the uploading agent at upload time.",
    )


class FileListResponse(BaseModel):
    """Schema for listing files in a session"""
    files: List[Dict[str, Any]] = Field(..., description="List of files")
    total: int = Field(..., description="Total number of files")


class FileDetailResponse(BaseModel):
    """Schema for detailed file information"""
    id: str = Field(..., description="File UUID")
    session_id: str = Field(..., description="Session UUID")
    file_name: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="File extension")
    file_size: int = Field(..., description="File size in bytes")
    mime_type: Optional[str] = Field(None, description="MIME type")
    parsing_status: str = Field(..., description="Parsing status")
    parsing_error: Optional[str] = Field(None, description="Parsing error if failed")
    extracted_text: Optional[str] = Field(None, description="Full extracted text")
    created_at: datetime = Field(..., description="Upload timestamp")
    uploaded_by: Optional[str] = Field(None, description="User who uploaded")
    scope: Optional[str] = Field(
        None,
        description="File visibility scope: 'local' or 'global'.",
    )
    uploaded_at_agent_id: Optional[str] = Field(
        None,
        description="Workflow node id of the agent that was active at upload time.",
    )
    uploaded_at_agent_label: Optional[str] = Field(
        None,
        description="Human-readable label of the uploading agent.",
    )


# ============================================================================
# DOCUMENT (RAG) SCHEMAS
# ============================================================================

class DocumentUploadResponse(BaseModel):
    """Schema for document upload response"""
    document_id: str = Field(..., description="Document UUID")
    file_name: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="Document type")
    file_size: int = Field(..., description="File size in bytes")
    status: str = Field(..., description="Processing status")
    blob_url: Optional[str] = Field(None, description="Blob URL in Azure Storage")
    message: str = Field(..., description="Status message")


class DocumentListResponse(BaseModel):
    """Schema for listing documents in a session"""
    documents: List[Dict[str, Any]] = Field(..., description="List of documents")
    total: int = Field(..., description="Total number of documents")


class DocumentDetailResponse(BaseModel):
    """Schema for detailed document information"""
    id: str = Field(..., description="Document UUID")
    session_id: str = Field(..., description="Session UUID")
    blob_name: str = Field(..., description="Blob name in Azure Storage")
    file_name: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="Document type")
    file_size: int = Field(..., description="File size in bytes")
    mime_type: Optional[str] = Field(None, description="MIME type")
    status: str = Field(..., description="Processing status")
    container_name: str = Field(..., description="Azure Storage container name")
    blob_url: Optional[str] = Field(None, description="Blob URL")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Custom metadata")
    extracted_text: Optional[str] = Field(None, description="Extracted text content")
    chunk_count: Optional[int] = Field(None, description="Number of text chunks")
    embedding_status: Optional[str] = Field(None, description="Embedding status")
    processing_error: Optional[str] = Field(None, description="Processing error if failed")
    uploaded_by: Optional[str] = Field(None, description="User who uploaded")
    created_at: datetime = Field(..., description="Upload timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class DocumentDownloadUrlResponse(BaseModel):
    """Schema for temporary download URL"""
    document_id: str = Field(..., description="Document UUID")
    download_url: str = Field(..., description="Temporary SAS URL")
    expiry_hours: int = Field(..., description="URL expiry time in hours")


# ============================================================================
# KNOWLEDGE BASE SCHEMAS
# ============================================================================

class MetadataFieldSchema(BaseModel):
    """Schema for a single metadata field definition."""
    name: str = Field(..., min_length=1, max_length=64, description="Field name (alphanumeric + underscores)")
    type: str = Field(..., description="Data type: string, number, date, boolean")
    scope: str = Field(..., description="Inference scope: global (document-level) or local (chunk-level)")
    description: Optional[str] = Field(None, max_length=256, description="Optional hint for the LLM during extraction")


class KnowledgeBaseCreateRequest(BaseModel):
    """Schema for creating a knowledge base.
    Chunking config is optional here; per-document chunking is set at upload time.
    """
    session_id: str = Field(..., description="Session UUID")
    name: str = Field(..., min_length=1, max_length=255, description="KB name")
    description: Optional[str] = Field(None, description="KB description")
    chunking_method: Optional[str] = Field(None, description="Default chunking method (overridable per-document)")
    chunk_size: Optional[int] = Field(None, gt=0, description="Default chunk size in characters")
    chunk_overlap: Optional[int] = Field(None, ge=0, description="Default overlap between chunks")
    embedding_model: str = Field(..., description="Embedding model (openai_ada_002, openai_large, etc.)")
    separators: Optional[List[str]] = Field(None, description="Custom separators for recursive chunking")
    delimiter: Optional[str] = Field(None, description="Delimiter string for delimiter chunking")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Custom metadata")
    metadata_fields: Optional[List[MetadataFieldSchema]] = Field(None, description="Metadata field definitions for LLM inference")


class KnowledgeBaseResponse(BaseModel):
    """Schema for knowledge base creation response"""
    kb_id: str = Field(..., description="KB UUID")
    name: str = Field(..., description="KB name")
    description: Optional[str] = Field(None, description="KB description")
    status: str = Field(..., description="KB status")
    azure_folder_path: str = Field(..., description="Azure folder path")
    chunk_table_name: str = Field(..., description="Chunk table name")
    chunking_method: str = Field(..., description="Chunking method")
    chunk_size: int = Field(..., description="Chunk size")
    chunk_overlap: int = Field(..., description="Chunk overlap")
    embedding_model: str = Field(..., description="Embedding model")
    vector_dimension: int = Field(..., description="Vector dimension")
    document_count: int = Field(..., description="Document count")
    chunk_count: int = Field(..., description="Chunk count")
    created_at: datetime = Field(..., description="Creation timestamp")
    message: str = Field(..., description="Status message")
    metadata_schema: Optional[List[MetadataFieldSchema]] = Field(None, description="Metadata field definitions")


class KnowledgeBaseListResponse(BaseModel):
    """Schema for listing knowledge bases"""
    knowledge_bases: List[Dict[str, Any]] = Field(..., description="List of KBs")
    total: int = Field(..., description="Total number of KBs")


class KnowledgeBaseDetailResponse(BaseModel):
    """Schema for detailed KB information"""
    kb_id: str = Field(..., description="KB UUID")
    session_id: str = Field(..., description="Session UUID")
    name: str = Field(..., description="KB name")
    description: Optional[str] = Field(None, description="KB description")
    azure_folder_path: str = Field(..., description="Azure folder path")
    chunk_table_name: str = Field(..., description="Chunk table name")
    chunking_config: Dict[str, Any] = Field(..., description="Chunking configuration")
    embedding_model: str = Field(..., description="Embedding model")
    vector_dimension: int = Field(..., description="Vector dimension")
    status: str = Field(..., description="KB status")
    document_count: int = Field(..., description="Document count")
    chunk_count: int = Field(..., description="Chunk count")
    total_size_bytes: int = Field(..., description="Total size in bytes")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Custom metadata")
    metadata_schema: Optional[List[MetadataFieldSchema]] = Field(None, description="Metadata field definitions")
    created_by: Optional[str] = Field(None, description="Creator UUID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    share_access: Optional[str] = Field(
        None,
        description="Effective access for current user: owner | read | write",
    )


class ChunkSearchRequest(BaseModel):
    """Schema for chunk similarity search"""
    query_embedding: List[float] = Field(..., description="Query embedding vector")
    limit: int = Field(10, ge=1, le=100, description="Maximum results")
    distance_threshold: Optional[float] = Field(None, ge=0.0, description="Maximum L2 distance (lower = more similar)")
    use_sphere: bool = Field(True, description="Use sphere search (faster, recommended for RAG)")


class ChunkSearchResponse(BaseModel):
    """Schema for chunk search results"""
    kb_id: str = Field(..., description="KB UUID")
    results: List[Dict[str, Any]] = Field(..., description="Search results")
    total: int = Field(..., description="Total results")


# ============================================================================
# AUTHENTICATION SCHEMAS
# ============================================================================

class RegisterRequest(BaseModel):
    """Request schema for user registration."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password")
    firstName: Optional[str] = Field(None, max_length=32, description="User's first name")
    lastName: Optional[str] = Field(None, max_length=32, description="User's last name")


class LoginRequest(BaseModel):
    """Request schema for user login."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class RefreshTokenRequest(BaseModel):
    """Request schema for refreshing access token (legacy body-based flow)."""
    refresh_token: str = Field(..., description="Valid refresh token")


class OAuthCodeExchangeRequest(BaseModel):
    """Request schema for exchanging a one-time OAuth code for tokens."""
    code: str = Field(..., description="One-time authorization code from OAuth callback")


class TokenResponse(BaseModel):
    """Response schema for login and token refresh.
    
    refresh_token is no longer returned in the body — it is set as an HttpOnly cookie.
    The field is kept optional for backward compatibility during migration.
    """
    access_token: str = Field(..., description="JWT access token")
    refresh_token: Optional[str] = Field(None, description="Deprecated — refresh token is now in HttpOnly cookie")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration time in seconds")


class UserResponse(BaseModel):
    """Response schema for user information."""
    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User email address")
    firstName: Optional[str] = Field(None, description="User's first name")
    lastName: Optional[str] = Field(None, description="User's last name")
    authProvider: str = Field(..., description="Authentication provider")
    disabled: bool = Field(..., description="Account disabled status")
    mfaEnabled: bool = Field(..., description="MFA enabled status")
    roleSlug: str = Field(..., description="User role")
    lastActiveAt: Optional[datetime] = Field(None, description="Last activity timestamp")
    createdAt: datetime = Field(..., description="Account creation timestamp")
    
    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    """Request schema for changing password."""
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")


class UpdateProfileRequest(BaseModel):
    """Request schema for updating user profile."""
    firstName: Optional[str] = Field(None, max_length=32, description="User's first name")
    lastName: Optional[str] = Field(None, max_length=32, description="User's last name")


# ============================================================================
# FEEDBACK SCHEMAS
# ============================================================================

class SubmitFeedbackRequest(BaseModel):
    """Request schema for submitting user feedback."""
    category: str = Field(..., description="Feedback category (bug, feature_request, improvement, usability, performance, other)")
    subject: str = Field(..., min_length=1, max_length=255, description="Short summary of the feedback")
    message: str = Field(..., min_length=1, description="Detailed feedback message")
    rating: Optional[int] = Field(None, ge=1, le=5, description="Satisfaction rating 1-5")
    pageUrl: Optional[str] = Field(None, max_length=512, description="Page URL where feedback was submitted")


class FeedbackResponse(BaseModel):
    """Response schema for a feedback submission."""
    id: str = Field(..., description="Feedback UUID")
    userId: str = Field(..., description="User UUID who submitted")
    category: str = Field(..., description="Feedback category")
    subject: str = Field(..., description="Feedback subject")
    message: str = Field(..., description="Feedback message")
    rating: Optional[int] = Field(None, description="Satisfaction rating")
    status: str = Field(..., description="Feedback status")
    createdAt: datetime = Field(..., description="Submission timestamp")

    class Config:
        from_attributes = True


class FeedbackListResponse(BaseModel):
    """Response schema for listing feedback."""
    feedback: List[FeedbackResponse] = Field(..., description="List of feedback entries")
    total: int = Field(..., description="Total feedback count")


# ============================================================================
# Checkpoint / Revert Schemas
# ============================================================================

class CheckpointSummary(BaseModel):
    """Lightweight checkpoint info for listing (frontend uses to show revert buttons)."""
    id: str = Field(..., description="Checkpoint UUID")
    user_message_id: str = Field(..., description="The user message this checkpoint is before")
    step_index: int = Field(..., description="Ordering within session")
    created_at: str = Field(..., description="Checkpoint creation timestamp")


class CheckpointListResponse(BaseModel):
    """Response for listing checkpoints."""
    checkpoints: List[CheckpointSummary] = Field(default_factory=list)


class RevertResponse(BaseModel):
    """Response after performing a revert."""
    session_id: str = Field(..., description="Session UUID")
    checkpoint_id: str = Field(..., description="Checkpoint that was reverted to")
    conversation_history: List[ChatMessage] = Field(default_factory=list, description="Restored conversation")
    prefill_message: str = Field(..., description="User message text to prefill in input")
    deliverables: list = Field(default_factory=list, description="Restored deliverable snapshots")
    pending_deliverable: Optional[dict] = Field(None, description="Pending deliverable if at HITL pause")
    status: str = Field(..., description="Restored execution status")


# ============================================================================
# WORKFLOW VERSION HISTORY SCHEMAS
# ============================================================================

class WorkflowVersionResponse(BaseModel):
    """Response for a single workflow version snapshot."""
    versionId: str = Field(..., description="Version UUID")
    workflowId: str = Field(..., description="Parent workflow UUID")
    versionNumber: int = Field(..., description="Sequential version number within this workflow")
    authors: str = Field(..., description="User who created this version")
    nodes: Optional[str] = Field(None, description="Node definitions snapshot (JSON)")
    connections: Optional[str] = Field(None, description="Connection mappings snapshot (JSON)")
    settings: Optional[str] = Field(None, description="Settings snapshot (JSON)")
    description: Optional[str] = Field(None, description="Version label / description")
    isPublishedSnapshot: bool = Field(..., description="True if this was the version deployed by a Publish action")
    event: str = Field(..., description="What triggered this version: save, publish, restore, import_update")
    createdAt: datetime = Field(..., description="When this version was created")

    class Config:
        from_attributes = True
        orm_mode = True


class WorkflowVersionListResponse(BaseModel):
    """Paginated list of workflow versions."""
    workflowId: str = Field(..., description="Parent workflow UUID")
    total: int = Field(..., description="Total version count")
    items: List[WorkflowVersionResponse] = Field(default_factory=list, description="Version list (newest first)")
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total pages")


class WorkflowVersionSummaryResponse(BaseModel):
    """Lightweight version info (no node/connection payloads) for list views."""
    versionId: str = Field(..., description="Version UUID")
    versionNumber: int = Field(..., description="Sequential version number")
    authors: str = Field(..., description="User who created this version")
    description: Optional[str] = Field(None, description="Version label / description")
    isPublishedSnapshot: bool = Field(..., description="Whether this is the published version")
    event: str = Field(..., description="Trigger event type")
    createdAt: datetime = Field(..., description="Creation timestamp")

    class Config:
        from_attributes = True
        orm_mode = True


class WorkflowVersionSummaryListResponse(BaseModel):
    """Paginated list of lightweight version summaries."""
    workflowId: str = Field(..., description="Parent workflow UUID")
    total: int = Field(..., description="Total version count")
    items: List[WorkflowVersionSummaryResponse] = Field(default_factory=list)
    page: int = Field(..., description="Current page")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total pages")


class WorkflowVersionNameUpdate(BaseModel):
    """Request to label / rename a version."""
    description: str = Field(..., max_length=512, description="Version label or description")


class WorkflowUpdateCheckResponse(BaseModel):
    """Response for checking if a marketplace-imported workflow has an update available."""
    hasUpdate: bool = Field(..., description="True if the source has a newer published version")
    currentVersionId: Optional[str] = Field(None, description="The versionId this import is pinned to")
    availableVersionId: Optional[str] = Field(None, description="The source's latest published versionId (if newer)")
    sourceWorkflowId: Optional[str] = Field(None, description="The source marketplace workflow ID")


# ── Project Schemas ──────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    """Schema for creating a new project"""
    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    description: Optional[str] = Field(None, max_length=512, description="Project description")


class UpdateProjectRequest(BaseModel):
    """Schema for updating a project"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="New project name")
    description: Optional[str] = Field(None, max_length=512, description="New project description")


class ProjectResponse(BaseModel):
    """Schema for project response"""
    id: str = Field(..., description="Project UUID")
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    userId: str = Field(..., description="Owner user UUID")
    createdAt: datetime = Field(..., description="Creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")
    sessionCount: int = Field(default=0, description="Number of sessions in this project")

    class Config:
        from_attributes = True
        orm_mode = True


class ProjectListResponse(BaseModel):
    """Schema for project list response"""
    items: List[ProjectResponse] = Field(default_factory=list)
    total: int = Field(..., description="Total number of projects")


class AssignSessionRequest(BaseModel):
    """Schema for assigning a session to a project"""
    session_id: str = Field(..., description="Session UUID to assign")
