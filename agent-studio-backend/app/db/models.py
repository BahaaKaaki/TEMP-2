
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, BigInteger, ForeignKey, Enum, Index, UniqueConstraint, CheckConstraint, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from pgvector.sqlalchemy import Vector
import enum
import uuid

Base = declarative_base()


# ============================================================================
# ENUMS
# ============================================================================

class AuthProvider(enum.Enum):
    """Authentication provider types."""
    LOCAL = "local"  # Email/password authentication
    MICROSOFT = "microsoft"  # Microsoft OAuth
    GOOGLE = "google"  # Google OAuth
    OKTA = "okta"  # Okta SSO


class FeedbackCategory(enum.Enum):
    """Feedback submission categories."""
    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    IMPROVEMENT = "improvement"
    USABILITY = "usability"
    PERFORMANCE = "performance"
    OTHER = "other"


# ============================================================================
# USER & AUTHENTICATION TABLES
# ============================================================================

class User(Base):
    """
    User accounts with authentication support.
    Stores user authentication, profile information, and security settings.
    Supports both local (email/password) and OAuth providers.
    """
    __tablename__ = 'user'
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    email = Column(String(255), unique=True, nullable=False, index=True)  # User email (unique, indexed)
    firstName = Column(String(32), nullable=True)  # User's first name
    lastName = Column(String(32), nullable=True)  # User's last name
    password = Column(String(255), nullable=True)  # Hashed password (nullable for OAuth users)
    
    # OAuth/External authentication
    authProvider = Column(Enum(AuthProvider), nullable=False, default=AuthProvider.LOCAL)  # Auth provider type
    externalId = Column(String(255), nullable=True, index=True)  # External provider user ID
    
    # User settings and preferences
    personalizationAnswers = Column(Text, nullable=True)  # Onboarding answers (JSON)
    settings = Column(Text, nullable=True)  # User preferences (JSON)
    
    # Security and access control
    disabled = Column(Boolean, nullable=False, default=False)  # Account disabled flag
    mfaEnabled = Column(Boolean, nullable=False, default=False)  # Two-factor auth enabled
    mfaSecret = Column(Text, nullable=True)  # TOTP secret for 2FA
    mfaRecoveryCodes = Column(Text, nullable=True)  # Backup recovery codes (JSON)
    roleSlug = Column(String(128), nullable=False, default='global:member')  # Role identifier
    
    # Activity tracking
    lastActiveAt = Column(DateTime, nullable=True)  # Last activity timestamp
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Account creation timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp


# ============================================================================
# CORE TABLES - ACTIVELY USED BY API
# ============================================================================

class Migration(Base):
    """
    Database migration tracking table.
    Stores information about applied database migrations for version control.
    """
    __tablename__ = 'migrations'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(BigInteger, nullable=False)
    name = Column(String, nullable=False)


class WorkflowEntity(Base):
    """
    Core workflow definitions.
    Represents the complete configuration of an automation workflow including
    nodes, connections, settings, and state.
    
    USED BY: workflow_entity.py, workflow_execution.py, workflow_chat.py, executor.py
    """
    __tablename__ = 'workflow_entity'
    
    __table_args__ = (
        Index('idx_workflow_marketplace', 'isPublic', 'isArchived'),
        Index('idx_workflow_pin_accessed', 'isPinned', 'lastAccessedAt'),
    )
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    name = Column(String(128), nullable=False)  # Workflow display name
    description = Column(String(512), nullable=True)  # Workflow description
    active = Column(Boolean, nullable=False, default=True)  # Whether workflow is active (default: True)
    nodes = Column(Text, nullable=True)  # Node definitions (JSON array)
    connections = Column(Text, nullable=True)  # Node connection mappings (JSON object)
    settings = Column(Text, nullable=True)  # Workflow settings like execution order (JSON)
    staticData = Column(Text, nullable=True)  # Persistent data between executions (JSON)
    pinData = Column(Text, nullable=True)  # Pinned test data for nodes (JSON)
    versionId = Column(String(36), nullable=True)  # Current version UUID from workflow_history
    triggerCount = Column(Integer, nullable=True, default=0)  # Number of trigger nodes
    meta = Column(Text, nullable=True)  # Additional metadata (JSON)
    parentFolderId = Column(String(36), nullable=True, index=True)  # Containing folder UUID
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Creation timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp
    isArchived = Column(Boolean, nullable=False, default=False)  # Soft delete flag
    isDraft = Column(Boolean, nullable=False, default=True)  # Draft status (True = draft, False = published)
    
    # User ownership and sharing
    createdById = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)  # User who created this workflow
    createdByName = Column(String(128), nullable=True)  # Name of user who created this workflow
    isPublic = Column(Boolean, nullable=False, default=False)  # True if shared in marketplace
    marketplaceName = Column(String(255), nullable=True)  # Display name in marketplace
    marketplaceDescription = Column(Text, nullable=True)  # Description for marketplace listing
    approvedVersionId = Column(String(36), nullable=True)  # Last admin-approved version snapshot for marketplace
    
    # Visual identity
    icon = Column(String(512), nullable=True)  # Blob path of uploaded icon image

    # User preferences
    isPinned = Column(Boolean, nullable=False, default=False)  # Pinned to top of list
    lastAccessedAt = Column(DateTime, nullable=True)  # Last time user opened/accessed this workflow


class ExecutionEntity(Base):
    """
    Core execution records for workflow runs.
    Tracks each time a workflow is executed with status and timing information.
    
    USED BY: workflow_execution.py, workflow_chat.py, executor.py
    """
    __tablename__ = 'execution_entity'
    
    __table_args__ = (
        Index('idx_execution_workflow_status', 'workflowId', 'status'),
        Index('idx_execution_session_created', 'sessionId', 'createdAt'),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)  # Unique execution ID
    workflowId = Column(String(36), nullable=False, index=True)  # Associated workflow UUID
    sessionId = Column(String(36), nullable=True, index=True)  # Associated chat session UUID (for chat instances)
    finished = Column(Boolean, nullable=False)  # Whether execution completed
    mode = Column(String, nullable=False)  # Execution mode ('manual', 'trigger', 'webhook', 'retry')
    retryOf = Column(String, nullable=True)  # ID of original execution if this is a retry
    retrySuccessId = Column(String, nullable=True)  # ID of successful retry if applicable
    startedAt = Column(DateTime, nullable=True, index=True)  # Execution start time
    stoppedAt = Column(DateTime, nullable=True)  # Execution end time
    waitTill = Column(DateTime, nullable=True)  # Wait until this time before continuing
    status = Column(String, nullable=False, index=True)  # Status ('success', 'error', 'waiting', 'running')
    deletedAt = Column(DateTime, nullable=True)  # Soft delete timestamp
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)  # Record creation timestamp
    updatedAt = Column(DateTime, nullable=True, default=datetime.utcnow)  # Record update timestamp
    
    # User tracking
    triggeredById = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)  # User who triggered execution


class ExecutionData(Base):
    """
    Detailed execution data for workflow runs.
    Stores the actual data that flowed through each node during execution.
    
    USED BY: workflow_execution.py, workflow_chat.py, executor.py
    """
    __tablename__ = 'execution_data'
    
    executionId = Column(Integer, primary_key=True, nullable=False)  # Associated execution ID
    workflowData = Column(Text, nullable=False)  # Workflow definition at execution time (JSON)
    data = Column(Text, nullable=False)  # Execution data including input/output for each node (JSON)


class Project(Base):
    """
    Projects for organizing chat sessions into groups.
    Personal to each user — no sharing. A session belongs to at most one project.
    """
    __tablename__ = 'project'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    description = Column(String(512), nullable=True)
    userId = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    isArchived = Column(Boolean, nullable=False, default=False)


class ChatSession(Base):
    """
    Chat session/instance for a workflow.
    Each session represents an independent conversation with its own state.
    Multiple sessions can exist for the same workflow, each maintaining separate conversation history.
    
    USED BY: workflow_chat.py
    """
    __tablename__ = 'chat_session'
    
    __table_args__ = (
        Index('idx_session_workflow_deleted', 'workflowId', 'deletedAt'),
        Index('idx_session_pin_accessed', 'isPinned', 'lastAccessedAt'),
        Index('idx_session_user_deleted', 'userId', 'deletedAt'),
    )
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    workflowId = Column(String(36), nullable=False, index=True)  # Associated workflow UUID
    name = Column(String(128), nullable=True)  # User-friendly session name
    description = Column(String(512), nullable=True)  # Optional session description
    status = Column(String(20), nullable=False, default='active', index=True)  # Session status ('active', 'archived', 'deleted')
    messageCount = Column(Integer, nullable=False, default=0)  # Total messages in session
    sessionVariables = Column(Text, nullable=True)  # Session-scoped variables (JSON)
    sessionMetadata = Column(Text, nullable=True)  # Custom session metadata (JSON)
    userId = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)  # Associated user (owner of session)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Session creation timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp
    lastMessageAt = Column(DateTime, nullable=True, index=True)  # Last message timestamp
    deletedAt = Column(DateTime, nullable=True)  # Soft delete timestamp
    
    # Version pinning (for workflow versioning)
    workflowVersionId = Column(String(36), nullable=True)  # Pinned workflow_history.versionId at session creation time
    
    # User preferences
    isPinned = Column(Boolean, nullable=False, default=False)  # Pinned to top of list
    lastAccessedAt = Column(DateTime, nullable=True)  # Last time user accessed this session

    # Project assignment
    projectId = Column(String(36), ForeignKey('project.id', ondelete='SET NULL'), nullable=True, index=True)


class AgentDeliverable(Base):
    """
    Structured deliverables produced by agents in multi-agent workflows.
    
    Each agent in a workflow can produce a deliverable (structured output) that:
    - Serves as input for the next agent in the chain
    - Can be reviewed/approved by humans via HITL (Human-in-the-Loop) nodes
    - Maintains iteration history for rejected→retry cycles
    
    USED BY: workflow_chat.py, executor.py, nodes/agent.py, nodes/hitl.py
    """
    __tablename__ = 'agent_deliverable'
    
    __table_args__ = (
        Index('idx_deliverable_session_agent', 'sessionId', 'agentId'),
    )
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    sessionId = Column(String(36), nullable=False, index=True)  # Associated chat session
    executionId = Column(Integer, nullable=False, index=True)  # Associated execution
    
    # Agent information
    agentId = Column(String(100), nullable=False, index=True)  # Node ID that produced this deliverable
    agentLabel = Column(String(255), nullable=False)  # Human-readable agent name
    agentType = Column(String(50), nullable=False)  # Node type (e.g., "researcher", "business-analyst")
    
    # Deliverable content
    deliverable = Column(Text, nullable=False)  # Structured output data (JSON)
    deliverableSchema = Column(Text, nullable=True)  # Expected output schema for validation (JSON)
    vizMetadata = Column(Text, nullable=True)  # Visualization metadata (JSON) - suggested viz types and config
    vizConfigs = Column(Text, nullable=True)  # Per-section visualization configs (JSON) - cached runtime viz results
    openuiLang = Column(Text, nullable=True)  # Cached OpenUI Lang for instant render on chat reopen
    
    # Review status
    status = Column(String(20), nullable=False, default='pending', index=True)  # 'pending', 'approved', 'rejected'
    reviewedAt = Column(DateTime, nullable=True)  # Timestamp when reviewed
    reviewedBy = Column(String(36), ForeignKey('user.id'), nullable=True)  # User who reviewed
    reviewNotes = Column(Text, nullable=True)  # Feedback from reviewer
    createdById = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)  # User who created deliverable
    
    # Iteration tracking (for rejected→retry flow)
    iteration = Column(Integer, nullable=False, default=1)  # Which iteration (1, 2, 3...)
    previousDeliverableId = Column(String(36), nullable=True)  # Link to previous iteration if retry
    
    # Timestamps
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Creation timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp


class WorkflowCheckpoint(Base):
    """
    Snapshot of full session state taken before each user message.
    Enables atomic revert-to-any-point: restores messages, deliverables,
    execution status, and all workflow state in one operation.
    """
    __tablename__ = 'workflow_checkpoint'

    __table_args__ = (
        Index('idx_workflow_checkpoint_session_step', 'sessionId', 'stepIndex'),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    sessionId = Column(String(36), nullable=False, index=True)
    executionId = Column(Integer, nullable=True)

    # The user message this checkpoint is "before"
    userMessageId = Column(String(36), nullable=False)
    userMessageText = Column(Text, nullable=False)
    userMessageDisplay = Column(Text, nullable=True)

    # Full state snapshot
    workflowState = Column(Text, nullable=False)
    executionStatus = Column(String(30), nullable=True)
    deliverableSnapshots = Column(Text, nullable=False, default='[]')

    # Ordering and metadata
    stepIndex = Column(Integer, nullable=False)
    sessionMessageCount = Column(Integer, nullable=False, default=0)
    userId = Column(String(36), nullable=False, index=True)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)


class ChatFile(Base):
    """
    Files uploaded to chat sessions.
    
    Stores uploaded documents (PDF, TXT, XML, DOCX, etc.) that are:
    - Parsed using Unstructured library to extract text content
    - Associated with specific chat sessions
    - Optionally linked to specific messages
    - Available for agents to reference in their context
    
    USED BY: workflow_chat.py, file upload endpoints
    """
    __tablename__ = 'chat_file'
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    sessionId = Column(String(36), nullable=False, index=True)  # Associated chat session
    messageId = Column(String(36), nullable=True, index=True)  # Optional: message that uploaded this file
    
    # File information
    fileName = Column(String(255), nullable=False)  # Original filename
    fileType = Column(String(50), nullable=False)  # File extension (pdf, txt, xml, etc.)
    filePath = Column(String(512), nullable=True)  # DEPRECATED: Legacy local file path
    fileSize = Column(BigInteger, nullable=False)  # File size in bytes
    mimeType = Column(String(100), nullable=True)  # MIME type (application/pdf, text/plain, etc.)
    
    # Azure Blob Storage fields
    containerName = Column(String(255), nullable=True)  # Azure Storage container name
    blobName = Column(String(512), nullable=True)  # Blob name/path in container
    blobUrl = Column(String(1024), nullable=True)  # Full blob URL
    
    # Parsed content from Unstructured
    extractedText = Column(Text, nullable=True)  # Full text extracted from document
    parsedElements = Column(Text, nullable=True)  # Structured elements from Unstructured (JSON)
    parsingStatus = Column(String(20), nullable=False, default='pending', index=True)  # 'pending', 'completed', 'failed'
    parsingError = Column(Text, nullable=True)  # Error message if parsing failed
    
    # Metadata
    uploadedBy = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)  # User who uploaded
    description = Column(String(512), nullable=True)  # Optional file description
    
    # Upload provenance: which agent was active when the user uploaded.
    # Visibility is determined by each receiving agent's fileScope config.
    # scope is a legacy column (upload-time sharing); ignored by the resolver.
    uploadedAtAgentId = Column(String(64), nullable=True, index=True)
    uploadedAtAgentLabel = Column(String(255), nullable=True)
    scope = Column(String(20), nullable=False, default='global', server_default='global', index=True)
    
    # Timestamps
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Upload timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp
    deletedAt = Column(DateTime, nullable=True)  # Soft delete timestamp


class KnowledgeBaseEntity(Base):
    """
    Knowledge Base for organizing documents and chunks.
    
    Each KB has its own Azure folder and dynamically created chunk table.
    Supports custom chunking strategies and embedding configurations.
    
    USED BY: knowledge base service, RAG endpoints
    """
    __tablename__ = 'knowledge_base'
    
    __table_args__ = (
        Index('idx_kb_pin_accessed', 'isPinned', 'lastAccessedAt'),
    )
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    sessionId = Column(String(36), nullable=False, index=True)  # Associated chat session
    name = Column(String(255), nullable=False, index=True)  # KB name
    description = Column(Text, nullable=True)  # KB description
    azureFolderPath = Column(String(512), nullable=False, unique=True)  # Azure folder path
    chunkTableName = Column(String(128), nullable=False, unique=True)  # Dynamic chunk table name
    chunkingConfig = Column(Text, nullable=False)  # Chunking configuration (JSON)
    embeddingModel = Column(String(50), nullable=False)  # Embedding model
    vectorDimension = Column(Integer, nullable=False)  # Vector dimension size
    status = Column(String(20), nullable=False, default='creating', index=True)  # KB status
    documentCount = Column(Integer, nullable=False, default=0)  # Number of documents
    chunkCount = Column(Integer, nullable=False, default=0)  # Number of chunks
    totalSizeBytes = Column(BigInteger, nullable=False, default=0)  # Total size
    kb_metadata = Column('metadata', Text, nullable=True)  # Custom metadata (JSON) - 'metadata' in DB, 'kb_metadata' in Python
    metadataSchema = Column(Text, nullable=True)  # Metadata field definitions (JSON) for LLM inference
    hasStructuredData = Column(Boolean, nullable=False, default=False)  # True if KB has structured tables
    createdBy = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)  # User who created KB
    
    # Marketplace sharing (similar to workflows)
    isPublic = Column(Boolean, nullable=False, default=False)  # True if shared in marketplace
    marketplaceName = Column(String(255), nullable=True)  # Display name in marketplace
    marketplaceDescription = Column(Text, nullable=True)  # Description for marketplace listing
    
    # User preferences
    isPinned = Column(Boolean, nullable=False, default=False)  # Pinned to top of list
    lastAccessedAt = Column(DateTime, nullable=True)  # Last time user accessed this KB
    
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Creation timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Update timestamp
    deletedAt = Column(DateTime, nullable=True)  # Soft delete timestamp


class StructuredTableEntity(Base):
    """
    Metadata for structured data tables created from CSV/Excel uploads.
    Each row represents one table (one CSV file or one Excel sheet)
    stored in a per-KB PostgreSQL schema.

    USED BY: structured_data_service, structured_data_repository
    """
    __tablename__ = 'structured_table'

    id = Column(String(36), primary_key=True, nullable=False)
    kbId = Column('kb_id', String(36), ForeignKey('knowledge_base.id', ondelete='CASCADE'), nullable=False, index=True)
    documentId = Column('document_id', String(36), ForeignKey('rag_document.id', ondelete='CASCADE'), nullable=False, index=True)
    schemaName = Column('schema_name', String(128), nullable=False)
    tableName = Column('table_name', String(128), nullable=False)
    displayName = Column('display_name', String(255), nullable=False)
    description = Column(Text, nullable=True)
    rowCount = Column('row_count', Integer, nullable=False, default=0)
    sourceSheet = Column('source_sheet', String(255), nullable=True)
    status = Column(String(20), nullable=False, default='pending_review')
    createdBy = Column('created_by', String(36), nullable=True)
    createdAt = Column('created_at', DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column('updated_at', DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class StructuredColumnEntity(Base):
    """
    Column definitions for structured data tables.
    Stores data type and semantic description used by LLMs for text-to-SQL.

    USED BY: structured_data_service, structured_data_repository
    """
    __tablename__ = 'structured_column'

    id = Column(String(36), primary_key=True, nullable=False)
    tableId = Column('table_id', String(36), ForeignKey('structured_table.id', ondelete='CASCADE'), nullable=False, index=True)
    columnName = Column('column_name', String(128), nullable=False)
    displayName = Column('display_name', String(255), nullable=False)
    dataType = Column('data_type', String(20), nullable=False, default='text')
    description = Column(Text, nullable=True)
    columnOrder = Column('column_order', Integer, nullable=False, default=0)
    nullable = Column(Boolean, nullable=False, default=True)
    createdAt = Column('created_at', DateTime, nullable=False, default=datetime.utcnow)


class StructuredRelationshipEntity(Base):
    """
    Foreign key relationships between structured data tables.
    Used by LLMs to generate correct JOIN queries.

    USED BY: structured_data_repository, structured_data_service
    """
    __tablename__ = 'structured_relationship'

    id = Column(String(36), primary_key=True, nullable=False)
    kbId = Column('kb_id', String(36), ForeignKey('knowledge_base.id', ondelete='CASCADE'), nullable=False, index=True)
    sourceTableId = Column('source_table_id', String(36), ForeignKey('structured_table.id', ondelete='CASCADE'), nullable=False, index=True)
    sourceColumnId = Column('source_column_id', String(36), ForeignKey('structured_column.id', ondelete='CASCADE'), nullable=False)
    targetTableId = Column('target_table_id', String(36), ForeignKey('structured_table.id', ondelete='CASCADE'), nullable=False, index=True)
    targetColumnId = Column('target_column_id', String(36), ForeignKey('structured_column.id', ondelete='CASCADE'), nullable=False)
    relationshipType = Column('relationship_type', String(20), nullable=False, default='one_to_many')
    createdAt = Column('created_at', DateTime, nullable=False, default=datetime.utcnow)


class MarketplaceSubmission(Base):
    """
    Marketplace submission for workflow approval.
    
    Tracks workflows submitted for marketplace approval by users.
    Admins can review, test, approve, or reject submissions.
    
    USED BY: approval routes, marketplace routes
    """
    __tablename__ = 'marketplace_submission'
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    workflowId = Column(String(36), ForeignKey('workflow_entity.id'), nullable=True, index=True)  # Workflow being submitted (NULL for shared_tool)
    submittedById = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)  # User who submitted
    
    # Submission details
    marketplaceName = Column(String(255), nullable=False)  # Display name for marketplace
    marketplaceDescription = Column(Text, nullable=True)  # Description for marketplace listing
    
    # Status tracking
    status = Column(String(20), nullable=False, default='pending', index=True)  # 'pending', 'approved', 'rejected'
    
    # Submission type: 'workflow' (default) or 'shared_tool'
    submission_type = Column(String(20), nullable=False, default='workflow')
    # Metadata for shared_tool submissions (sharing targets, tool URL, etc.)
    meta = Column(JSONB, nullable=True)
    
    # Review information
    reviewedById = Column(String(36), ForeignKey('user.id'), nullable=True)  # Admin who reviewed
    reviewedAt = Column(DateTime, nullable=True)  # When reviewed
    rejectionReason = Column(Text, nullable=True)  # Reason for rejection (if rejected)
    
    # Timestamps
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Submission timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp


class AdGroup(Base):
    """
    Cache of Microsoft Entra ID (Azure AD) security groups we've seen.
    Populated when a user signs in (their groups) and when an admin picks
    a group from the share dialog. The id is the AD object id (GUID),
    which is stable across renames.
    """
    __tablename__ = 'ad_group'

    id = Column(String(36), primary_key=True, nullable=False)
    displayName = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    lastSyncedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserGroup(Base):
    """
    Mirror of AD group memberships. Replace-all on every login so RLS can
    evaluate group sharing without hitting Microsoft Graph per-request.
    """
    __tablename__ = 'user_group'

    __table_args__ = (
        Index('idx_user_group_group', 'groupId'),
    )

    userId = Column(String(36), ForeignKey('user.id', ondelete='CASCADE'), primary_key=True, nullable=False)
    groupId = Column(String(36), ForeignKey('ad_group.id', ondelete='CASCADE'), primary_key=True, nullable=False)
    addedAt = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkflowShare(Base):
    """
    Sharing grant for a workflow with an AD group or a specific user.

    principalType: 'group' (principalId = ad_group.id) | 'user' (principalId = user.id)
    permission:    'read' | 'write'
    """
    __tablename__ = 'workflow_share'

    __table_args__ = (
        # One grant per (workflow, principal) pair — prevents duplicate
        # rows if the create endpoint races with itself.
        UniqueConstraint(
            'workflowId', 'principalType', 'principalId',
            name='uq_workflow_share_target',
        ),
        # Defense-in-depth: stop bad enum values landing in the DB even if a
        # caller bypasses Pydantic.
        CheckConstraint(
            "\"principalType\" IN ('group', 'user')",
            name='ck_workflow_share_principal_type',
        ),
        CheckConstraint(
            "permission IN ('read', 'write')",
            name='ck_workflow_share_permission',
        ),
        Index('idx_workflow_share_principal', 'principalType', 'principalId'),
        Index('idx_workflow_share_workflow', 'workflowId'),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    workflowId = Column(String(36), ForeignKey('workflow_entity.id', ondelete='CASCADE'), nullable=False)
    principalType = Column(String(10), nullable=False)
    principalId = Column(String(36), nullable=False)
    permission = Column(String(10), nullable=False, default='read')
    grantedById = Column(String(36), ForeignKey('user.id'), nullable=False)
    grantedAt = Column(DateTime, nullable=False, default=datetime.utcnow)


class MicrosoftOAuthToken(Base):
    """
    Per-user Microsoft OAuth refresh token, stored encrypted at rest.

    Why we store it:
        Group-based sharing requires calling Microsoft Graph "as the user"
        — e.g. /groups?$search=… for the share-dialog typeahead. That's a
        delegated permission flow, so we need the user's refresh token to
        mint a short-lived Graph access token whenever they trigger a
        search.

    Security model:
        * `refreshTokenEncrypted` holds Fernet ciphertext (see
          utils/token_crypto.py). The plaintext refresh token NEVER hits
          disk in clear, NEVER appears in logs, and NEVER leaves the
          backend process.
        * RLS (configured in db/init_security.py) restricts SELECT on this
          table to rows owned by the current user. Even admins cannot read
          another user's refresh token via SQL — defense in depth on top
          of API-layer access control.
        * One row per user. Re-auth via SSO upserts; logout / token
          revocation deletes.
    """
    __tablename__ = 'ms_oauth_token'

    userId = Column(
        String(36),
        ForeignKey('user.id', ondelete='CASCADE'),
        primary_key=True,
        nullable=False,
    )
    refreshTokenEncrypted = Column(Text, nullable=False)
    # Comma-separated list of scopes the refresh token was issued against.
    # Stored so we can detect "user re-consented to a wider/narrower set"
    # and refuse to use a token that no longer covers what we need.
    scopes = Column(Text, nullable=False)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class KnowledgeBaseShare(Base):
    """
    Sharing grant for a knowledge base. Same shape as WorkflowShare.
    """
    __tablename__ = 'knowledge_base_share'

    __table_args__ = (
        UniqueConstraint(
            'knowledgeBaseId', 'principalType', 'principalId',
            name='uq_kb_share_target',
        ),
        CheckConstraint(
            "\"principalType\" IN ('group', 'user')",
            name='ck_kb_share_principal_type',
        ),
        CheckConstraint(
            "permission IN ('read', 'write')",
            name='ck_kb_share_permission',
        ),
        Index('idx_kb_share_principal', 'principalType', 'principalId'),
        Index('idx_kb_share_kb', 'knowledgeBaseId'),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    knowledgeBaseId = Column(String(36), ForeignKey('knowledge_base.id', ondelete='CASCADE'), nullable=False)
    principalType = Column(String(10), nullable=False)
    principalId = Column(String(36), nullable=False)
    permission = Column(String(10), nullable=False, default='read')
    grantedById = Column(String(36), ForeignKey('user.id'), nullable=False)
    grantedAt = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserFeedback(Base):
    """
    User feedback submissions.
    Captures bug reports, feature requests, improvement suggestions,
    and general feedback from platform users.
    """
    __tablename__ = 'user_feedback'

    id = Column(String(36), primary_key=True, nullable=False)
    userId = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)
    category = Column(Enum(FeedbackCategory), nullable=False)
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    rating = Column(Integer, nullable=True)  # 1-5 satisfaction score
    pageUrl = Column(String(512), nullable=True)  # Page the user was on when submitting
    userAgent = Column(String(512), nullable=True)  # Browser/device info
    status = Column(String(20), nullable=False, default='new')  # new, reviewed, resolved, dismissed
    adminNotes = Column(Text, nullable=True)  # Internal notes from admin review
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentEntity(Base):
    """
    Documents stored in Azure Blob Storage for RAG capabilities.
    
    Stores document metadata and processing status for documents uploaded to Azure Storage.
    Documents are parsed, chunked, and embedded for retrieval-augmented generation.
    
    USED BY: document service, RAG endpoints
    """
    __tablename__ = 'rag_document'
    
    id = Column(String(36), primary_key=True, nullable=False)  # UUID identifier
    kbId = Column(String(36), nullable=False, index=True)  # Associated knowledge base
    sessionId = Column(String(36), nullable=False, index=True)  # Associated chat session
    
    # Blob storage information
    blobName = Column(String(512), nullable=False, unique=True)  # Unique blob name in Azure Storage
    containerName = Column(String(255), nullable=False)  # Azure Storage container name
    blobUrl = Column(String(1024), nullable=True)  # Full blob URL
    
    # File information
    fileName = Column(String(255), nullable=False)  # Original filename
    fileType = Column(String(50), nullable=False)  # Document type (pdf, docx, txt, etc.)
    fileSize = Column(BigInteger, nullable=False)  # File size in bytes
    mimeType = Column(String(100), nullable=True)  # MIME type
    
    # Processing status
    status = Column(String(30), nullable=False, default='pending', index=True)
    processingError = Column(Text, nullable=True)  # Error message if processing failed
    
    # Extracted content
    extractedText = Column(Text, nullable=True)  # Full text extracted from document
    chunkCount = Column(Integer, nullable=True, default=0)  # Number of text chunks created
    
    # Embedding status (individual chunks have embeddings)
    embeddingStatus = Column(String(20), nullable=True)  # 'pending', 'processing', 'completed', 'failed'
    
    # Metadata (JSON) - 'metadata' in DB, 'doc_metadata' in Python
    doc_metadata = Column('metadata', Text, nullable=True)  # Custom metadata as JSON
    
    # User tracking
    uploadedBy = Column(String(36), nullable=True)  # User UUID who uploaded
    
    # Timestamps
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)  # Upload timestamp
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)  # Last update timestamp
    deletedAt = Column(DateTime, nullable=True, index=True)  # Soft delete timestamp


# ============================================================================
# TEMPLATE ENGINE
# ============================================================================

class WorkflowTemplate(Base):
    """
    PPTX templates uploaded for workflow agent nodes.

    When a user uploads a PPTX file with ``{{ }}`` placeholders, the system
    extracts placeholders, generates a matching JSON Schema, and stores both
    alongside the blob reference.  At export time the template is filled with
    structured deliverable data.

    USED BY: template_routes.py, template_service.py, template_repository.py
    """
    __tablename__ = 'workflow_template'

    id = Column(String(36), primary_key=True, nullable=False)
    workflowId = Column(String(36), nullable=False, index=True)
    agentNodeId = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    fileName = Column(String(255), nullable=False)

    # Azure Blob Storage location
    containerName = Column(String(255), nullable=True)
    blobName = Column(String(512), nullable=True)
    blobUrl = Column(Text, nullable=True)

    # Cached analysis results (JSON)
    placeholders = Column(Text, nullable=True)
    generatedSchema = Column(Text, nullable=True)

    # Ownership
    createdById = Column(String(36), ForeignKey('user.id'), nullable=False, index=True)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowHistory(Base):
    """
    Version history of workflow changes.
    
    Each row is a full snapshot of a workflow's definition at a point in time.
    Snapshots are created on save, publish, restore, and marketplace import-update.
    WorkflowEntity.versionId points to the currently-published snapshot.
    
    USED BY: workflow_version_service.py, workflow_version_routes.py, workflow_entity.py
    """
    __tablename__ = 'workflow_history'

    __table_args__ = (
        Index('idx_wh_workflow_version', 'workflowId', 'versionNumber'),
        Index('idx_wh_workflow_published', 'workflowId', 'isPublishedSnapshot'),
        Index('idx_wh_workflow_created', 'workflowId', 'createdAt'),
    )

    versionId = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflowId = Column(String(36), ForeignKey('workflow_entity.id', ondelete='CASCADE'), nullable=False)
    versionNumber = Column(Integer, nullable=False)
    authors = Column(String(255), nullable=False)
    nodes = Column(Text, nullable=False)
    connections = Column(Text, nullable=False)
    settings = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    isPublishedSnapshot = Column(Boolean, nullable=False, default=False)
    event = Column(String(50), nullable=False)  # 'save', 'publish', 'restore', 'import_update'
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)


# ============================================================================
# UNUSED TABLES - NOT CURRENTLY USED BY API
# Comment out to reduce clutter. Uncomment if needed in the future.
# ============================================================================

# class Settings(Base):
#     """
#     Global application settings and configuration.
#     Stores key-value pairs for tool instance configuration like user management,
#     UI preferences, feature flags, and LDAP settings.
#     """
#     __tablename__ = 'settings'
#     
#     key = Column(Text, primary_key=True, nullable=False)
#     value = Column(Text, nullable=False, default='')
#     loadOnStartup = Column(Boolean, nullable=False, default=False)


# class InstalledPackage(Base):
#     """
#     Community packages and custom nodes installed in the tool instance.
#     Tracks third-party integrations and extensions added to extend tool functionality.
#     """
#     __tablename__ = 'installed_packages'
#     
#     packageName = Column(String(214), primary_key=True, nullable=False)
#     installedVersion = Column(String(50), nullable=False)
#     authorName = Column(String(70), nullable=True)
#     authorEmail = Column(String(70), nullable=True)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class InstalledNode(Base):
#     """
#     Individual nodes (workflow components) from installed packages.
#     Each node represents a specific integration or action available in workflows.
#     """
#     __tablename__ = 'installed_nodes'
#     
#     name = Column(String(200), primary_key=True, nullable=False)
#     type = Column(String(200), nullable=False)
#     latestVersion = Column(Integer, nullable=True, default=1)
#     package = Column(String(214), nullable=False)


# class EventDestination(Base):
#     """
#     Event destination endpoints for tool telemetry and event streaming.
#     Defines where tool sends event data for monitoring and analytics.
#     """
#     __tablename__ = 'event_destinations'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     destination = Column(Text, nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class AuthIdentity(Base):
#     """
#     External authentication provider identities.
#     Links tool users to external identity providers (OAuth, SAML, LDAP, etc.).
#     """
#     __tablename__ = 'auth_identity'
#     
#     userId = Column(String(36), nullable=True)
#     providerId = Column(String(64), primary_key=True, nullable=False)
#     providerType = Column(String(32), primary_key=True, nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class AuthProviderSyncHistory(Base):
#     """
#     Authentication provider synchronization history.
#     Tracks sync operations with external auth providers.
#     """
#     __tablename__ = 'auth_provider_sync_history'
#     
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     providerType = Column(String(32), nullable=False)
#     runMode = Column(Text, nullable=False)
#     status = Column(Text, nullable=False)
#     startedAt = Column(DateTime, nullable=False)
#     endedAt = Column(DateTime, nullable=False)
#     scanned = Column(Integer, nullable=False)
#     created = Column(Integer, nullable=False)
#     updated = Column(Integer, nullable=False)
#     disabled = Column(Integer, nullable=False)
#     error = Column(Text, nullable=True)


# class TagEntity(Base):
#     """
#     Tags for organizing and categorizing workflows.
#     Users can assign tags to workflows for better organization and filtering.
#     """
#     __tablename__ = 'tag_entity'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     name = Column(String(24), nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class WorkflowsTag(Base):
#     """
#     Many-to-many relationship between workflows and tags.
#     Links workflows to their assigned tags for organization.
#     """
#     __tablename__ = 'workflows_tags'
#     
#     workflowId = Column(String(36), primary_key=True, nullable=False)
#     tagId = Column(Integer, primary_key=True, nullable=False)


# class WorkflowStatistics(Base):
#     """
#     Statistical data and metrics for workflow executions.
#     Tracks execution counts and timing data for performance monitoring.
#     """
#     __tablename__ = 'workflow_statistics'
#     
#     name = Column(String(128), primary_key=True, nullable=False)
#     workflowId = Column(String(36), primary_key=True, nullable=True)
#     count = Column(Integer, nullable=True, default=0)
#     latestEvent = Column(DateTime, nullable=True)
#     rootCount = Column(Integer, nullable=True, default=0)


# class WebhookEntity(Base):
#     """
#     Webhook endpoints for triggering workflows via HTTP requests.
#     Stores webhook configurations including URL paths and HTTP methods.
#     """
#     __tablename__ = 'webhook_entity'
#     
#     webhookPath = Column(String, primary_key=True, nullable=False)
#     method = Column(String, primary_key=True, nullable=False)
#     workflowId = Column(String(36), nullable=False)
#     node = Column(String, nullable=False)
#     webhookId = Column(String, nullable=True)
#     pathLength = Column(Integer, nullable=True)


# class Variable(Base):
#     """
#     Global variables accessible across all workflows.
#     Stores reusable configuration values and secrets for workflows.
#     """
#     __tablename__ = 'variables'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     key = Column(Text, nullable=False)
#     type = Column(Text, nullable=False, default='string')
#     value = Column(Text, nullable=True)


# WorkflowHistory — moved to CORE TABLES section above (now active)


# class CredentialsEntity(Base):
#     """
#     Stored credentials for external service integrations.
#     Contains encrypted authentication data (API keys, passwords, tokens) for services.
#     """
#     __tablename__ = 'credentials_entity'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     name = Column(String(128), nullable=False)
#     data = Column(Text, nullable=False)
#     type = Column(String(32), nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
#     isManaged = Column(Boolean, nullable=False, default=False)


# class SharedCredentials(Base):
#     """
#     Credential sharing permissions across projects.
#     Defines which projects have access to which credentials and their permission level.
#     """
#     __tablename__ = 'shared_credentials'
#     
#     credentialsId = Column(String(36), primary_key=True, nullable=False)
#     projectId = Column(String(36), primary_key=True, nullable=False)
#     role = Column(Text, nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class SharedWorkflow(Base):
#     """
#     Workflow sharing permissions across projects.
#     Defines which projects have access to which workflows and their permission level.
#     """
#     __tablename__ = 'shared_workflow'
#     
#     workflowId = Column(String(36), primary_key=True, nullable=False)
#     projectId = Column(String(36), primary_key=True, nullable=False)
#     role = Column(Text, nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class ExecutionMetadata(Base):
#     """
#     Additional metadata for workflow executions.
#     Stores custom key-value pairs with extra information about executions.
#     """
#     __tablename__ = 'execution_metadata'
#     
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     executionId = Column(Integer, nullable=False)
#     key = Column(String(255), nullable=False)
#     value = Column(Text, nullable=False)


# class InvalidAuthToken(Base):
#     """
#     Revoked or invalidated authentication tokens.
#     Blacklist of tokens that should no longer be accepted for authentication.
#     """
#     __tablename__ = 'invalid_auth_token'
#     
#     token = Column(String(512), primary_key=True, nullable=False)
#     expiresAt = Column(DateTime, nullable=False)


# class ExecutionAnnotations(Base):
#     """
#     User annotations and feedback on workflow executions.
#     Allows users to add notes and ratings to execution runs for training/improvement.
#     """
#     __tablename__ = 'execution_annotations'
#     
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     executionId = Column(Integer, nullable=False)
#     vote = Column(String(6), nullable=True)
#     note = Column(Text, nullable=True)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class AnnotationTagEntity(Base):
#     """
#     Tags for categorizing execution annotations.
#     Allows organizing annotations with custom labels.
#     """
#     __tablename__ = 'annotation_tag_entity'
#     
#     id = Column(String(16), primary_key=True, nullable=False)
#     name = Column(String(24), nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class ExecutionAnnotationTags(Base):
#     """
#     Many-to-many relationship between execution annotations and tags.
#     Links annotations to their categorization tags.
#     """
#     __tablename__ = 'execution_annotation_tags'
#     
#     annotationId = Column(Integer, primary_key=True, nullable=False)
#     tagId = Column(String(24), primary_key=True, nullable=False)


# class ProcessedData(Base):
#     """
#     Cache of processed/transformed data for workflows.
#     Stores intermediate data to avoid reprocessing in certain workflow scenarios.
#     """
#     __tablename__ = 'processed_data'
#     
#     workflowId = Column(String(36), primary_key=True, nullable=False)
#     context = Column(String(255), primary_key=True, nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
#     value = Column(Text, nullable=False)


# Project model is now active — see the class above ChatSession.


# class Folder(Base):
#     """
#     Folders for hierarchical organization within projects.
#     Allows creating nested folder structures to organize workflows.
#     """
#     __tablename__ = 'folder'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     name = Column(String(128), nullable=False)
#     parentFolderId = Column(String(36), nullable=True)
#     projectId = Column(String(36), nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class FolderTag(Base):
#     """
#     Many-to-many relationship between folders and tags.
#     Allows tagging folders for better organization.
#     """
#     __tablename__ = 'folder_tag'
#     
#     folderId = Column(String(36), primary_key=True, nullable=False)
#     tagId = Column(String(36), primary_key=True, nullable=False)


# class InsightsMetadata(Base):
#     """
#     Metadata for analytics insights.
#     Links insight data to workflows and projects for reporting.
#     """
#     __tablename__ = 'insights_metadata'
#     
#     metaId = Column(Integer, primary_key=True, autoincrement=True)
#     workflowId = Column(String(16), nullable=True)
#     projectId = Column(String(36), nullable=True)
#     workflowName = Column(String(128), nullable=False)
#     projectName = Column(String(255), nullable=False)


# class InsightsRaw(Base):
#     """
#     Raw analytics data points.
#     Time-series data for workflow execution metrics and events.
#     """
#     __tablename__ = 'insights_raw'
#     
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     metaId = Column(Integer, nullable=False)
#     type = Column(Integer, nullable=False)
#     value = Column(Integer, nullable=False)
#     timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)


# class InsightsByPeriod(Base):
#     """
#     Aggregated analytics data by time period.
#     Pre-computed metrics grouped by hour, day, week, or month for performance.
#     """
#     __tablename__ = 'insights_by_period'
#     
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     metaId = Column(Integer, nullable=False)
#     type = Column(Integer, nullable=False)
#     value = Column(Integer, nullable=False)
#     periodUnit = Column(Integer, nullable=False)
#     periodStart = Column(DateTime, nullable=True, default=datetime.utcnow)


# class UserApiKey(Base):
#     """
#     API keys for programmatic access to tool.
#     Allows users to authenticate API requests without credentials.
#     """
#     __tablename__ = 'user_api_keys'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     userId = Column(String, nullable=False)
#     label = Column(String(100), nullable=False)
#     apiKey = Column(String, nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
#     scopes = Column(Text, nullable=True)


# class TestRun(Base):
#     """
#     Workflow test run records.
#     Tracks automated or manual test executions of workflows.
#     """
#     __tablename__ = 'test_run'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     workflowId = Column(String(36), nullable=False)
#     status = Column(String, nullable=False)
#     errorCode = Column(String, nullable=True)
#     errorDetails = Column(Text, nullable=True)
#     runAt = Column(DateTime, nullable=True)
#     completedAt = Column(DateTime, nullable=True)
#     metrics = Column(Text, nullable=True)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class Scope(Base):
#     """
#     Permission scopes for role-based access control.
#     Defines granular permissions that can be assigned to roles.
#     """
#     __tablename__ = 'scope'
#     
#     slug = Column(String(128), primary_key=True, nullable=False)
#     displayName = Column(Text, nullable=True)
#     description = Column(Text, nullable=True)


# class RoleScope(Base):
#     """
#     Many-to-many relationship between roles and permission scopes.
#     Assigns specific permissions to roles for access control.
#     """
#     __tablename__ = 'role_scope'
#     
#     roleSlug = Column(String(128), primary_key=True, nullable=False)
#     scopeSlug = Column(String(128), primary_key=True, nullable=False)


# User model now activated above - see USER & AUTHENTICATION TABLES section


# class TestCaseExecution(Base):
#     """
#     Individual test case executions within a test run.
#     Tracks detailed results for each test case including inputs, outputs, and evaluations.
#     """
#     __tablename__ = 'test_case_execution'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     testRunId = Column(String(36), nullable=False)
#     pastExecutionId = Column(Integer, nullable=True)
#     executionId = Column(Integer, nullable=True)
#     evaluationExecutionId = Column(Integer, nullable=True)
#     status = Column(String, nullable=False)
#     runAt = Column(DateTime, nullable=True)
#     completedAt = Column(DateTime, nullable=True)
#     errorCode = Column(String, nullable=True)
#     errorDetails = Column(Text, nullable=True)
#     metrics = Column(Text, nullable=True)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
#     inputs = Column(Text, nullable=True)
#     outputs = Column(Text, nullable=True)


# class ProjectRelation(Base):
#     """
#     User membership and roles within projects.
#     Defines which users have access to which projects and their permission level.
#     """
#     __tablename__ = 'project_relation'
#     
#     projectId = Column(String(36), primary_key=True, nullable=False)
#     userId = Column(String, primary_key=True, nullable=False)
#     role = Column(String, nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class DataTable(Base):
#     """
#     Data tables for storing structured data.
#     Allows workflows to read/write from persistent data stores.
#     """
#     __tablename__ = 'data_table'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     name = Column(String(128), nullable=False)
#     projectId = Column(String(36), nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# class DataTableColumn(Base):
#     """
#     Column definitions for data tables.
#     Defines the schema of data tables including column names, types, and order.
#     """
#     __tablename__ = 'data_table_column'
#     
#     id = Column(String(36), primary_key=True, nullable=False)
#     name = Column(String(128), nullable=False)
#     type = Column(String(32), nullable=False)
#     index = Column(Integer, nullable=False)
#     dataTableId = Column(String(36), nullable=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================================
# LLM MODEL CATALOG (unified admin configuration)
# ============================================================================

class LlmModel(Base):
    """Canonical catalog of LLM model identifiers (pricing, Langfuse sync, usage)."""
    __tablename__ = "llm_models"

    model_name = Column(String(128), primary_key=True, nullable=False)
    provider = Column(String(32), nullable=True)
    display_label = Column(String(255), nullable=True)
    fallback_model_name = Column(String(128), ForeignKey("llm_models.model_name"), nullable=True)
    is_deprecated = Column(Boolean, nullable=False, default=False)
    discovered_in_proxy = Column(Boolean, nullable=False, default=False)
    input_price_per_1m_tokens = Column(Numeric(14, 6), nullable=True)
    output_price_per_1m_tokens = Column(Numeric(14, 6), nullable=True)
    cache_read_price_per_1m_tokens = Column(Numeric(14, 6), nullable=True)
    cache_creation_price_per_1m_tokens = Column(Numeric(14, 6), nullable=True)
    admin_notes = Column(Text, nullable=True)
    langfuse_match_pattern = Column(String(512), nullable=True)
    langfuse_last_synced_at = Column(DateTime, nullable=True)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class LlmModelBinding(Base):
    """Maps a code call-site (tool/service/settings) to a catalog model."""
    __tablename__ = "llm_model_bindings"

    __table_args__ = (
        Index('idx_llm_model_bindings_type', 'binding_type'),
    )

    binding_key = Column(String(128), primary_key=True, nullable=False)
    binding_type = Column(String(32), nullable=False)
    primary_model_name = Column(String(128), ForeignKey("llm_models.model_name"), nullable=False)
    display_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    source_file = Column(String(512), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    updatedById = Column(String(36), ForeignKey("user.id"), nullable=True)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class LlmModelWorkflowUsage(Base):
    """Workflow scan aggregates per model."""
    __tablename__ = "llm_model_workflow_usage"

    model_name = Column(String(128), ForeignKey("llm_models.model_name"), primary_key=True)
    # Legacy columns (kept for backward compatibility; scan writes field refs here too)
    live_occurrences = Column(Integer, nullable=False, default=0)
    published_occurrences = Column(Integer, nullable=False, default=0)
    # Preferred metrics
    live_workflows = Column(Integer, nullable=False, default=0)
    live_field_refs = Column(Integer, nullable=False, default=0)
    published_workflows = Column(Integer, nullable=False, default=0)
    published_snapshots = Column(Integer, nullable=False, default=0)
    published_field_refs = Column(Integer, nullable=False, default=0)
    lastScannedAt = Column(DateTime, nullable=True)


class AdminAuditLog(Base):
    """Lightweight admin action log."""
    __tablename__ = "admin_audit_log"

    __table_args__ = (
        Index('idx_admin_audit_log_created', 'createdAt', postgresql_ops={'createdAt': 'DESC'}),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    adminUserId = Column(String(36), ForeignKey("user.id"), nullable=True)
    action = Column(String(64), nullable=False)
    entity_type = Column(String(64), nullable=True)
    entity_id = Column(String(256), nullable=True)
    details = Column(Text, nullable=True)
    createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)


# ============================================================================
# ANALYTICS (pre-aggregated snapshots, refreshed on-demand)
# ============================================================================

class AnalyticsExecutionDaily(Base):
    """
    Daily execution aggregates: one row per (date, workflow, user, status, mode).
    Populated by on-demand refresh from execution_entity + Langfuse API.
    """
    __tablename__ = "analytics_execution_daily"

    __table_args__ = (
        UniqueConstraint('date', 'workflow_id', 'user_id', 'status', 'mode', name='uq_analytics_exec_daily'),
        Index('idx_analytics_exec_daily_date', 'date'),
        Index('idx_analytics_exec_daily_workflow', 'workflow_id', 'date'),
        Index('idx_analytics_exec_daily_user', 'user_id', 'date'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)
    workflow_id = Column(String(36), nullable=False)
    workflow_name = Column(String(128), nullable=True)
    user_id = Column(String(36), nullable=True)
    user_email = Column(String(255), nullable=True)
    status = Column(String(30), nullable=False)
    mode = Column(String(20), nullable=False, default='manual')

    execution_count = Column(Integer, nullable=False, default=0)
    avg_duration_ms = Column(Numeric, nullable=True)
    min_duration_ms = Column(Numeric, nullable=True)
    max_duration_ms = Column(Numeric, nullable=True)
    total_duration_ms = Column(Numeric, nullable=True)

    total_input_tokens = Column(BigInteger, default=0)
    total_output_tokens = Column(BigInteger, default=0)
    total_tokens = Column(BigInteger, default=0)
    total_cost_usd = Column(Numeric, default=0)
    llm_call_count = Column(Integer, default=0)

    snapshot_version = Column(Integer, nullable=False, default=1)
    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AnalyticsModelDaily(Base):
    """
    Model-level daily consumption aggregates (populated from Langfuse API).
    """
    __tablename__ = "analytics_model_daily"

    __table_args__ = (
        UniqueConstraint('date', 'model_name', name='uq_analytics_model_daily'),
        Index('idx_analytics_model_daily_date', 'date'),
        Index('idx_analytics_model_daily_model', 'model_name', 'date'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)
    model_name = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=True)

    generation_count = Column(Integer, nullable=False, default=0)
    total_input_tokens = Column(BigInteger, default=0)
    total_output_tokens = Column(BigInteger, default=0)
    total_tokens = Column(BigInteger, default=0)
    cache_read_tokens = Column(BigInteger, default=0)
    cache_creation_tokens = Column(BigInteger, default=0)
    total_cost_usd = Column(Numeric, default=0)

    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AnalyticsServiceDaily(Base):
    """
    Service-level daily consumption for non-workflow operations:
    embeddings (KB), code executor, OCR, image processing, etc.
    Populated from Langfuse generations that have no execution_id.
    """
    __tablename__ = "analytics_service_daily"

    __table_args__ = (
        UniqueConstraint('date', 'service_name', 'binding_key', 'model_name', 'user_id', name='uq_analytics_service_daily'),
        Index('idx_analytics_service_daily_date', 'date'),
        Index('idx_analytics_service_daily_service', 'service_name', 'date'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)
    service_name = Column(String(128), nullable=False)
    binding_key = Column(String(128), nullable=True)
    model_name = Column(String(128), nullable=True)
    user_id = Column(String(36), nullable=True)
    user_email = Column(String(255), nullable=True)

    call_count = Column(Integer, nullable=False, default=0)
    total_input_tokens = Column(BigInteger, default=0)
    total_output_tokens = Column(BigInteger, default=0)
    total_tokens = Column(BigInteger, default=0)
    total_cost_usd = Column(Numeric, default=0)

    computed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AnalyticsRefreshLog(Base):
    """Tracks analytics refresh operations."""
    __tablename__ = "analytics_refresh_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    refresh_type = Column(String(32), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default='running')
    date_from = Column(DateTime, nullable=True)
    date_to = Column(DateTime, nullable=True)
    rows_upserted = Column(Integer, default=0)
    langfuse_traces = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(36), nullable=True)


# ============================================================================
# SHARED EXTERNAL TOOLS
# ============================================================================

class SharedTool(Base):
    """
    External tool link that appears in the Storefront.
    
    Visibility is controlled by is_public (all users) or per-permission
    grants in shared_tool_permission (AD group / user).
    """
    __tablename__ = 'shared_tool'

    __table_args__ = (
        UniqueConstraint('tool_name', 'url', name='uq_shared_tool_name_url'),
        Index('idx_shared_tool_status', 'status'),
        Index('idx_shared_tool_public', 'is_public', 'status'),
        Index('idx_shared_tool_created_by', 'created_by'),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    tool_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    url = Column(Text, nullable=False)
    is_public = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default='approved')
    created_by = Column(String(36), ForeignKey('user.id'), nullable=False)
    approved_by = Column(String(36), ForeignKey('user.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SharedToolPermission(Base):
    """
    Sharing grant for a shared_tool with an AD group or a specific user.
    
    principalType: 'group' (principalId = ad_group.id) | 'user' (principalId = user.id)
    """
    __tablename__ = 'shared_tool_permission'

    __table_args__ = (
        UniqueConstraint(
            'shared_tool_id', 'principal_type', 'principal_id',
            name='uq_shared_tool_perm_target',
        ),
        CheckConstraint(
            "principal_type IN ('group', 'user')",
            name='ck_shared_tool_perm_principal_type',
        ),
        Index('idx_shared_tool_perm_tool', 'shared_tool_id'),
        Index('idx_shared_tool_perm_principal', 'principal_type', 'principal_id'),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    shared_tool_id = Column(String(36), ForeignKey('shared_tool.id', ondelete='CASCADE'), nullable=False)
    principal_type = Column(String(10), nullable=False)
    principal_id = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SharedToolAuditLog(Base):
    """
    Audit trail for shared tool operations (create, update, delete, CSV upload).
    """
    __tablename__ = 'shared_tool_audit_log'

    __table_args__ = (
        Index('idx_shared_tool_audit_time', 'performed_at', postgresql_ops={'performed_at': 'DESC'}),
        Index('idx_shared_tool_audit_tool', 'shared_tool_id'),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    shared_tool_id = Column(String(36), ForeignKey('shared_tool.id', ondelete='SET NULL'), nullable=True)
    action = Column(String(50), nullable=False)
    performed_by = Column(String(36), ForeignKey('user.id'), nullable=False)
    performed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    details = Column(JSONB, nullable=True)


# class Role(Base):
#     """
#     User and project roles for access control.
#     Defines sets of permissions that can be assigned to users.
#     """
#     __tablename__ = 'role'
#     
#     slug = Column(String(128), primary_key=True, nullable=False)
#     displayName = Column(Text, nullable=True)
#     description = Column(Text, nullable=True)
#     roleType = Column(Text, nullable=True)
#     systemRole = Column(Boolean, nullable=False, default=False)
#     createdAt = Column(DateTime, nullable=False, default=datetime.utcnow)
#     updatedAt = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
