"""
File service for file upload and parsing business logic.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import uuid
import logging
import asyncio
from io import BytesIO

from .base import BaseService
from .file_scope_resolver import resolve_active_agent
from repositories import (
    FileRepository,
    SessionRepository,
    ExecutionRepository,
    WorkflowRepository,
)
from domain.entities import File
from core.exceptions import FileNotFoundException, SessionNotFoundException
from utils.file_parser import FileParser
from connectors import AzureStorageConnector
from config.keyvault import cfg

logger = logging.getLogger(__name__)


class FileService(BaseService):
    """Service for file upload and management."""
    
    def __init__(
        self,
        db: AsyncSession,
        file_repo: FileRepository,
        session_repo: SessionRepository,
        storage_connector: AzureStorageConnector,
        execution_repo: Optional[ExecutionRepository] = None,
        workflow_repo: Optional[WorkflowRepository] = None,
    ):
        super().__init__(db)
        self.file_repo = file_repo
        self.session_repo = session_repo
        self.storage_connector = storage_connector
        # ExecutionRepository / WorkflowRepository are optional for backward
        # compatibility with older callers that don't supply them. Without them
        # we can't resolve the "current agent" stamp at upload time and the
        # file falls back to scope="global" with no agent attribution.
        self.execution_repo = execution_repo
        self.workflow_repo = workflow_repo
    
    async def upload_file(
        self,
        session_id: str,
        file_name: str,
        file_content: bytes,
        mime_type: Optional[str] = None,
        message_id: Optional[str] = None,
        uploaded_by: Optional[str] = None
    ) -> File:
        """Upload file to Azure Blob Storage."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundException(session_id)
        
        # Ensure storage connector is initialized
        await self.storage_connector.initialize()
        
        file_id = str(uuid.uuid4())
        file_type = file_name.split('.')[-1] if '.' in file_name else 'unknown'
        file_size = len(file_content)
        
        # Stamp provenance only; receiving agents decide visibility via fileScope.
        active_agent_id, active_agent_label = await self._resolve_upload_agent(
            session_id=session_id,
            workflow_id=session.workflow_id,
        )
        scope = "local"  # legacy column; ignored by consumption resolver
        
        # Upload to Azure Blob Storage
        blob_name = f"chat-sessions/{session_id}/{file_id}_{file_name}"
        
        try:
            blob_url = await self.storage_connector.upload_blob(
                blob_name=blob_name,
                data=file_content,
                content_type=mime_type,
                metadata={
                    "file_id": file_id,
                    "session_id": session_id,
                    "uploaded_by": uploaded_by or "unknown",
                    "message_id": message_id or "",
                    "uploaded_at_agent_id": active_agent_id or "",
                    "scope": scope,
                }
            )
            
            file = await self.file_repo.create_file(
                file_id=file_id,
                session_id=session_id,
                file_name=file_name,
                file_type=file_type,
                file_size=file_size,
                mime_type=mime_type,
                message_id=message_id,
                uploaded_by=uploaded_by,
                container_name=self.storage_connector.container_name,
                blob_name=blob_name,
                blob_url=blob_url,
                uploaded_at_agent_id=active_agent_id,
                uploaded_at_agent_label=active_agent_label,
                scope=scope,
            )
            
            await self.commit()
            
            logger.debug("Uploaded file %s to session %s (blob: %s)", file_name, session_id, blob_name)
        
            # Trigger parsing in background (fire-and-forget)
            # This allows immediate response to user while parsing happens asynchronously
            asyncio.create_task(
                self._parse_file(
                    file.id,
                    file.file_name,
                    blob_name,
                    self.storage_connector.container_name,
                    uploaded_by=uploaded_by,
                )
            )
            
            return file
        
        except Exception as e:
            logger.error(f"Failed to upload file {file_name}: {e}")
            await self.rollback()
            raise
    
    async def _resolve_upload_agent(
        self,
        session_id: str,
        workflow_id: str,
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve (uploaded_at_agent_id, uploaded_at_agent_label) for provenance."""
        if not self.execution_repo or not self.workflow_repo:
            logger.debug(
                "file_scope: execution/workflow repo unavailable; "
                "upload will have no agent stamp"
            )
            return None, None

        try:
            active = await resolve_active_agent(
                session_id=session_id,
                workflow_id=workflow_id,
                execution_repo=self.execution_repo,
                workflow_repo=self.workflow_repo,
            )
        except Exception as e:
            logger.warning("file_scope: active agent resolution failed: %s", e)
            return None, None

        if not active.agent_id:
            logger.debug(
                "file_scope: no active agent for session %s; no agent stamp",
                session_id,
            )
            return None, None

        logger.debug(
            "file_scope: stamping upload with agent_id=%s label=%s",
            active.agent_id,
            active.agent_label,
        )
        return active.agent_id, active.agent_label
    
    async def _parse_file(
        self,
        file_id: str,
        file_name: str,
        blob_name: str,
        container_name: str,
        uploaded_by: Optional[str] = None,
    ) -> None:
        """Parse file content using unstructured library."""
        from db.pgsql import PrimarySessionLocal, set_user_context
        from repositories import FileRepository
        from connectors import AzureStorageConnector
        from config.settings import settings
        import os
        import tempfile
        
        # Create a new database session for the background task
        async with PrimarySessionLocal() as session:
            temp_path = None

            async def _ensure_rls() -> None:
                # Background tasks do not inherit request ContextVars reliably;
                # chat_file RLS requires app.current_user_id == uploadedBy.
                if uploaded_by:
                    await set_user_context(session, uploaded_by)
            
            try:
                await _ensure_rls()
                file_repo = FileRepository(session)
                
                # Create new storage connector instance for this task
                container_name_env = cfg.AZURE_STORAGE_CONTAINER_NAME
                use_managed_identity = cfg.AZURE_STORAGE_USE_MANAGED_IDENTITY
                
                if use_managed_identity:
                    account_name = cfg.AZURE_STORAGE_ACCOUNT_NAME
                    managed_identity_client_id = cfg.AZURE_CLIENT_ID_ADSLGEN2
                    storage_conn = AzureStorageConnector(
                        container_name=container_name_env,
                        account_name=account_name,
                        use_managed_identity=True,
                        managed_identity_client_id=managed_identity_client_id,
                        create_container=True
                    )
                else:
                    connection_string = (
                        cfg.AZURE_STORAGE_CONNECTION_STRING
                        or "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;"
                    )
                    storage_conn = AzureStorageConnector(
                        container_name=container_name_env,
                        connection_string=connection_string,
                        create_container=True
                    )
                
                # Use storage connector as async context manager to ensure proper cleanup
                async with storage_conn:
                    # Download file from blob storage
                    file_content = await storage_conn.download_blob(blob_name)
                    
                    file_ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
                    
                    if FileParser.is_image_file_type(file_ext):
                        # Image -> vision LLM OCR. Skip the temp-file dance; the
                        # vision helper takes raw bytes.
                        from utils.vision_ocr import (
                            extract_text_from_image,
                            guess_image_mime,
                        )
                        success, extracted_text, error = await extract_text_from_image(
                            file_bytes=file_content,
                            file_name=file_name,
                            mime_type=guess_image_mime(file_ext),
                        )
                    else:
                        # Write to temp file for parsing
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_name}") as temp_file:
                            temp_file.write(file_content)
                            temp_path = temp_file.name
                        
                        # Run blocking file parsing in thread pool to avoid blocking event loop
                        success, extracted_text, parsed_elements, error = await asyncio.to_thread(
                            FileParser.parse_file,
                            temp_path
                        )
                
                    if success and extracted_text:
                        await file_repo.update_parsing_status(
                            file_id,
                            "completed",
                            extracted_text=extracted_text
                        )
                        
                        await session.commit()
                        await _ensure_rls()
                        
                        logger.debug("Parsed file %s (%d chars)", file_name, len(extracted_text))
                    else:
                        await file_repo.update_parsing_status(
                            file_id,
                            "failed",
                            error=error or "Unknown parsing error"
                        )
                        await session.commit()
                        await _ensure_rls()
                        logger.error("Failed to parse file %s: %s", file_name, error)
            
            except Exception as e:
                logger.error("Failed to parse file %s: %s", file_name, e)
                
                try:
                    await _ensure_rls()
                    file_repo = FileRepository(session)
                    await file_repo.update_parsing_status(
                        file_id,
                        "failed",
                        error=str(e)
                    )
                    
                    await session.commit()
                except Exception as commit_error:
                    logger.error("Failed to update parsing error status: %s", commit_error)
                    # Rollback to clean up the session
                    await session.rollback()
            
            finally:
                # Clean up temp file
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
    
    async def list_session_files(
        self,
        session_id: str,
        include_deleted: bool = False
    ) -> List[File]:
        """List all files for a session."""
        return await self.file_repo.get_by_session_id(session_id, include_deleted)
    
    async def get_file(self, file_id: str) -> File:
        """Get file by ID."""
        file = await self.file_repo.get_by_id(file_id)
        if not file:
            raise FileNotFoundException(file_id)
        return file
    
    async def delete_file(self, file_id: str, permanent: bool = False) -> None:
        """Delete file."""
        file = await self.get_file(file_id)
        
        if permanent:
            # Delete from blob storage if blob_name exists
            if file.blob_name:
                try:
                    await self.storage_connector.initialize()
                    await self.storage_connector.delete_blob(file.blob_name)
                    logger.debug("Permanently deleted file %s from blob storage", file.file_name)
                except Exception as e:
                    logger.error("Failed to delete blob %s: %s", file.blob_name, e)
            
            query = text(f"DELETE FROM chat_file WHERE id = :file_id")
            await self.db.execute(query, {"file_id": file_id})
        else:
            await self.file_repo.soft_delete(file_id)
            logger.debug("Soft deleted file %s", file.file_name)
        
        await self.commit()

