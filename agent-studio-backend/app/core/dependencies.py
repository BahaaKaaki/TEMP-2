"""
Dependency injection setup for FastAPI.
"""
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError
import os

logger = logging.getLogger(__name__)
from config.keyvault import cfg

from db.pgsql import get_write_db, get_static_read_db
from db.models import User
from repositories import (
    SessionRepository,
    ExecutionRepository,
    DeliverableRepository,
    FileRepository,
    WorkflowRepository,
    DocumentRepository,
    KnowledgeBaseRepository,
    CheckpointRepository,
    ProjectRepository,
)
from repositories.user_repository import UserRepository
from services import (
    SessionService,
    ChatService,
    DeliverableService,
    FileService,
    DocumentService,
    KnowledgeBaseService,
    CheckpointService,
    ProjectService,
)
from services.auth_service import AuthService
from connectors import AzureStorageConnector
from workflow.executor import WorkflowExecutor
from utils.security import verify_token


# Security scheme for JWT bearer tokens
security = HTTPBearer()


def get_user_repository(db: AsyncSession = Depends(get_write_db)) -> UserRepository:
    """Get user repository."""
    return UserRepository(db)


def get_auth_service(
    db: AsyncSession = Depends(get_write_db),
    user_repo: UserRepository = Depends(get_user_repository)
) -> AuthService:
    """Get authentication service."""
    return AuthService(db, user_repo)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_write_db),
    user_repo: UserRepository = Depends(get_user_repository)
) -> User:
    """
    Dependency to get current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Authorization header with Bearer token
        db: Database session
        user_repo: User repository
        
    Returns:
        Current authenticated User
        
    Raises:
        HTTPException: If authentication fails (401)
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Extract token from credentials
        token = credentials.credentials

        # Verify and decode token
        payload = verify_token(token, token_type="access")
        user_id: str = payload.get("sub")

        if user_id is None:
            raise credentials_exception

        # Get user from database
        user = await user_repo.get_by_id(user_id)

        if user is None:
            raise credentials_exception

        # Check if account is disabled
        if user.disabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled"
            )

        # Update last active timestamp (non-critical; never fail auth over this)
        try:
            await user_repo.update_last_active(user_id)
        except Exception as exc:
            logger.warning("update_last_active failed for user %s: %s", user_id, exc)

        # Set user_id in request context for RLS. AD groups are intentionally
        # NOT loaded here — get_db_with_user_context loads them from the
        # user_group table on demand. The 'groups' claim is no longer included
        # in the JWT (see auth_service.create_tokens) because enterprise users
        # in hundreds of groups would blow past Authorization-header size
        # limits on common ingresses (~8KB), truncating the token mid-flight.
        from core.request_context import (
            set_current_user_groups,
            set_current_user_email,
            set_current_user_id,
            set_current_user_name,
        )
        from app.llm.observability_context import (
            format_user_display_name,
            format_user_email,
        )

        set_current_user_id(user_id)
        set_current_user_name(format_user_display_name(user))
        set_current_user_email(format_user_email(user))
        set_current_user_groups(None)

        return user

    except JWTError:
        raise credentials_exception


def is_admin(user: User) -> bool:
    """
    Check if a user has admin role.
    
    Args:
        user: User to check
        
    Returns:
        True if user has admin role, False otherwise
    """
    if not user or not user.roleSlug:
        return False
    return 'admin' in user.roleSlug.lower()


async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Dependency to get current authenticated admin user.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        Current authenticated admin User
        
    Raises:
        HTTPException: If user is not an admin (403)
    """
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


async def get_db_with_user_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_write_db)
) -> AsyncSession:
    """
    Get database session with user + AD-group RLS context already set.

    This dependency:
      1. Sets ``app.current_user_id`` so user-scoped RLS policies work and
         ``user_group`` becomes readable to this user (its policy filters by
         the same GUC).
      2. Loads the user's AD group GUIDs from the ``user_group`` table.
      3. Re-sets context with both user_id + groups so group-share RLS
         clauses (workflow_share / knowledge_base_share) evaluate correctly.

    Why per-request DB lookup instead of a JWT claim:
      Enterprise users can be members of hundreds of AD groups. A JWT with
      that many GUIDs in a "groups" claim balloons past the Authorization
      header size limits enforced by common ingresses (Azure Container Apps
      ingress, NGINX default, etc. — typically 8KB). The truncated token
      then fails signature verification on the next request, producing a
      mysterious post-login 401 / login loop.
    """
    from db.pgsql import set_user_context
    from core.request_context import set_current_user_groups
    from sqlalchemy import text

    user_id = str(current_user.id)

    # Step 1: set user_id only (groups GUC = ''). user_group RLS now allows
    # the row-owner to SELECT their own membership rows.
    await set_user_context(db, user_id)

    # Step 2: load the user's AD groups from the local cache table. This is
    # an indexed lookup on (userId) and adds < 1ms per authenticated request.
    try:
        result = await db.execute(
            text('SELECT "groupId" FROM user_group WHERE "userId" = :uid'),
            {"uid": user_id},
        )
        group_ids = [row[0] for row in result.all()]
    except Exception as exc:  # noqa: BLE001 - never block auth on group lookup
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Failed to load AD groups for user %s; group-shared resources "
            "will be hidden this request: %s", user_id, exc,
        )
        group_ids = []

    # Step 3: stamp groups onto both the request ContextVar and the DB GUC
    # so RLS policies that reference app_current_user_groups() see them.
    set_current_user_groups(group_ids)
    if group_ids:
        await set_user_context(db, user_id, group_ids=group_ids)

    return db


def get_session_repository(db: AsyncSession = Depends(get_write_db)) -> SessionRepository:
    """Get session repository."""
    return SessionRepository(db)


def get_execution_repository(db: AsyncSession = Depends(get_write_db)) -> ExecutionRepository:
    """Get execution repository."""
    return ExecutionRepository(db)


def get_deliverable_repository(db: AsyncSession = Depends(get_write_db)) -> DeliverableRepository:
    """Get deliverable repository."""
    return DeliverableRepository(db)


def get_file_repository(db: AsyncSession = Depends(get_write_db)) -> FileRepository:
    """Get file repository."""
    return FileRepository(db)


def get_workflow_repository(db: AsyncSession = Depends(get_write_db)) -> WorkflowRepository:
    """Get workflow repository."""
    return WorkflowRepository(db)


def get_workflow_executor(
    db: AsyncSession = Depends(get_write_db),
    current_user: User = Depends(get_current_user)
) -> WorkflowExecutor:
    """Get workflow executor with user context."""
    return WorkflowExecutor(db, user_id=current_user.id)


def get_session_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
) -> SessionService:
    """Get session service."""
    # Create repositories with the user-context-aware session
    session_repo = SessionRepository(db)
    workflow_repo = WorkflowRepository(db)
    execution_repo = ExecutionRepository(db)
    
    return SessionService(db, session_repo, workflow_repo, execution_repo)


def get_chat_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
) -> ChatService:
    """Get chat service."""
    # Create repositories with the user-context-aware session
    session_repo = SessionRepository(db)
    execution_repo = ExecutionRepository(db)
    deliverable_repo = DeliverableRepository(db)
    file_repo = FileRepository(db)
    workflow_repo = WorkflowRepository(db)
    checkpoint_repo = CheckpointRepository(db)
    
    # CRITICAL: WorkflowExecutor must use the SAME session as the service
    # to avoid "Could not refresh instance" errors
    workflow_executor = WorkflowExecutor(db, user_id=current_user.id)
    
    return ChatService(
        db,
        session_repo,
        execution_repo,
        deliverable_repo,
        file_repo,
        workflow_repo,
        workflow_executor,
        checkpoint_repo=checkpoint_repo,
    )


def get_project_service(
    db: AsyncSession = Depends(get_db_with_user_context),
) -> ProjectService:
    """Get project service."""
    project_repo = ProjectRepository(db)
    return ProjectService(db, project_repo)


def get_checkpoint_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
) -> CheckpointService:
    """Get checkpoint service."""
    checkpoint_repo = CheckpointRepository(db)
    session_repo = SessionRepository(db)
    execution_repo = ExecutionRepository(db)
    deliverable_repo = DeliverableRepository(db)
    
    return CheckpointService(
        db,
        checkpoint_repo,
        session_repo,
        execution_repo,
        deliverable_repo,
    )


def get_deliverable_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
) -> DeliverableService:
    """Get deliverable service."""
    # Create repositories with the user-context-aware session
    deliverable_repo = DeliverableRepository(db)
    execution_repo = ExecutionRepository(db)
    workflow_repo = WorkflowRepository(db)
    session_repo = SessionRepository(db)
    
    # CRITICAL: WorkflowExecutor must use the SAME session as the service
    # to avoid "Could not refresh instance" errors
    workflow_executor = WorkflowExecutor(db, user_id=current_user.id)
    
    return DeliverableService(
        db,
        deliverable_repo,
        execution_repo,
        workflow_repo,
        session_repo,
        workflow_executor
    )


def get_document_repository(db: AsyncSession = Depends(get_write_db)) -> DocumentRepository:
    """Get document repository."""
    return DocumentRepository(db)


# Singleton Azure Storage connector - reused across all requests
# Initialized at startup via init_azure_storage_connector(), closed at shutdown
_azure_storage_connector: AzureStorageConnector | None = None


def create_azure_storage_connector() -> AzureStorageConnector:
    """
    Create a new Azure Storage connector instance.
    
    Uses Managed Identity if AZURE_STORAGE_USE_MANAGED_IDENTITY=true (secure, for Azure cloud).
    Falls back to connection string for local development with Azurite.
    """
    container_name = cfg.AZURE_STORAGE_CONTAINER_NAME
    use_managed_identity = cfg.AZURE_STORAGE_USE_MANAGED_IDENTITY
    
    if use_managed_identity:
        account_name = cfg.AZURE_STORAGE_ACCOUNT_NAME
        if not account_name:
            raise ValueError(
                "AZURE_STORAGE_ACCOUNT_NAME must be set when AZURE_STORAGE_USE_MANAGED_IDENTITY=true"
            )
        
        managed_identity_client_id = cfg.AZURE_CLIENT_ID_ADSLGEN2
        
        return AzureStorageConnector(
            container_name=container_name,
            account_name=account_name,
            use_managed_identity=True,
            managed_identity_client_id=managed_identity_client_id,
            create_container=True
        )
    else:
        # Local dev: Use connection string
        connection_string = (
            cfg.AZURE_STORAGE_CONNECTION_STRING
            or "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;"
        )
        
        return AzureStorageConnector(
            container_name=container_name,
            connection_string=connection_string,
            create_container=True
        )


async def init_azure_storage_connector() -> AzureStorageConnector:
    """
    Initialize the singleton Azure Storage connector at app startup.
    Creates and initializes the connector (incl. container creation).
    
    Returns:
        The initialized singleton connector
    """
    global _azure_storage_connector
    _azure_storage_connector = create_azure_storage_connector()
    await _azure_storage_connector.initialize()
    return _azure_storage_connector


async def close_azure_storage_connector() -> None:
    """Close the singleton Azure Storage connector at app shutdown."""
    global _azure_storage_connector
    if _azure_storage_connector:
        await _azure_storage_connector.close()
        _azure_storage_connector = None


def get_azure_storage_connector() -> AzureStorageConnector:
    """
    Get the singleton Azure Storage connector.
    
    Returns the shared connector instance that was initialized at startup.
    This avoids creating a new BlobServiceClient per request, preventing
    resource leaks (unclosed aiohttp sessions/connectors).
    """
    if _azure_storage_connector is None:
        raise RuntimeError(
            "Azure Storage connector not initialized. "
            "Call init_azure_storage_connector() at startup first."
        )
    return _azure_storage_connector


def get_file_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    storage_connector: AzureStorageConnector = Depends(get_azure_storage_connector),
    current_user: User = Depends(get_current_user)
) -> FileService:
    """Get file service."""
    # Create repositories with the user-context-aware session
    file_repo = FileRepository(db)
    session_repo = SessionRepository(db)
    # Execution + Workflow repos are required for resolving the active agent
    # at upload time so files can be stamped with their per-agent scope.
    execution_repo = ExecutionRepository(db)
    workflow_repo = WorkflowRepository(db)
    
    return FileService(
        db,
        file_repo,
        session_repo,
        storage_connector,
        execution_repo=execution_repo,
        workflow_repo=workflow_repo,
    )


def get_document_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    session_repo: SessionRepository = Depends(get_session_repository),
    storage_connector: AzureStorageConnector = Depends(get_azure_storage_connector),
    current_user: User = Depends(get_current_user)
) -> DocumentService:
    """Get document service."""
    document_repo = DocumentRepository(db)
    return DocumentService(db, document_repo, session_repo, storage_connector)


def get_structured_data_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    current_user: User = Depends(get_current_user)
):
    """Get structured data service."""
    from repositories.structured_data_repository import StructuredDataRepository
    from services.structured_data_service import StructuredDataService
    structured_repo = StructuredDataRepository(db)
    return StructuredDataService(db, structured_repo)


def get_knowledge_base_repository(db: AsyncSession = Depends(get_write_db)) -> KnowledgeBaseRepository:
    """Get knowledge base repository."""
    return KnowledgeBaseRepository(db)


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_write_db),
    user_repo: UserRepository = Depends(get_user_repository)
) -> User | None:
    """
    Optional dependency to get current user without requiring authentication.
    Used for endpoints that work both with and without authentication.
    
    Returns:
        Current authenticated User or None if not authenticated
    """
    try:
        return await get_current_user(credentials, db, user_repo)
    except HTTPException:
        return None


def get_knowledge_base_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    kb_repo: KnowledgeBaseRepository = Depends(get_knowledge_base_repository),
    session_repo: SessionRepository = Depends(get_session_repository),
    current_user: User = Depends(get_current_user)
) -> KnowledgeBaseService:
    """Get knowledge base service."""
    return KnowledgeBaseService(db, kb_repo, session_repo)


def get_template_service(
    db: AsyncSession = Depends(get_db_with_user_context),
    storage_connector: AzureStorageConnector = Depends(get_azure_storage_connector),
    current_user: User = Depends(get_current_user),
):
    """Get template service for PPTX template upload / fill."""
    from repositories.template_repository import TemplateRepository
    from services.template_service import TemplateService

    repo = TemplateRepository(db)
    return TemplateService(repo, storage_connector)

