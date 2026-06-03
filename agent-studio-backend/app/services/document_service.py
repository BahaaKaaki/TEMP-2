"""
Document service for RAG capabilities with Azure Blob Storage.
"""
from typing import Optional, List, BinaryIO
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import uuid
import logging
from pathlib import Path
from io import BytesIO
import asyncio

from .base import BaseService
from repositories import DocumentRepository, SessionRepository
from domain.entities import Document
from domain.entities.document import DocumentStatus, DocumentType
from connectors import AzureStorageConnector
from core.exceptions import SessionNotFoundException


logger = logging.getLogger(__name__)


class DocumentNotFoundException(Exception):
    """Exception raised when document is not found."""
    
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(f"Document not found: {document_id}")


class DuplicateDocumentException(Exception):
    """Exception raised when a document with the same name already exists in the KB."""

    def __init__(self, file_name: str, kb_id: str):
        self.file_name = file_name
        self.kb_id = kb_id
        super().__init__(
            f"A file named '{file_name}' already exists in this knowledge base. "
            f"To upload a new version, please delete the existing file first and then upload the replacement."
        )


class DocumentService(BaseService):
    """Service for managing documents in Azure Blob Storage."""
    
    def __init__(
        self,
        db: AsyncSession,
        document_repo: DocumentRepository,
        session_repo: SessionRepository,
        storage_connector: AzureStorageConnector,
        kb_service = None
    ):
        super().__init__(db)
        self.document_repo = document_repo
        self.session_repo = session_repo
        self.storage_connector = storage_connector
        self.kb_service = kb_service
    
    async def upload_document(
        self,
        kb_id: str,
        file_name: str,
        file_content: bytes,
        mime_type: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        metadata: Optional[dict] = None,
        skip_processing: bool = False,
        chunking_overrides: Optional[dict] = None,
        metadata_fields: Optional[list] = None,
        vision_config: Optional[dict] = None,
    ) -> Document:
        """
        Upload document to Azure Blob Storage and add to knowledge base.
        
        Args:
            kb_id: Knowledge Base ID
            file_name: Original filename
            file_content: File content as bytes
            mime_type: MIME type of the file
            uploaded_by: User ID who uploaded the document
            metadata: Additional metadata
        
        Returns:
            Document entity
        """
        if not self.kb_service:
            from services.knowledge_base_service import KnowledgeBaseService
            from repositories.knowledge_base_repository import KnowledgeBaseRepository
            self.kb_service = KnowledgeBaseService(
                self.db,
                KnowledgeBaseRepository(self.db),
                self.session_repo
            )
        
        kb = await self.kb_service.get_knowledge_base(kb_id)
        if not kb.can_add_documents():
            raise ValueError(f"Knowledge base {kb_id} is not active")
        
        existing_doc_id = await self.kb_service.kb_repo.find_document_id_by_name(kb_id, file_name)
        if existing_doc_id:
            raise DuplicateDocumentException(file_name, kb_id)
        
        session_id = kb.session_id
        
        document_id = str(uuid.uuid4())
        file_type = self._get_file_type(file_name)
        file_size = len(file_content)
        
        blob_name = f"{kb.azure_folder_path}/{document_id}_{file_name}"
        
        try:
            blob_url = await self.storage_connector.upload_blob(
                blob_name=blob_name,
                data=file_content,
                content_type=mime_type,
                metadata={
                    "document_id": document_id,
                    "session_id": session_id,
                    "uploaded_by": uploaded_by or "unknown",
                    **(metadata or {})
                }
            )
            
            document = await self.document_repo.create_document(
                document_id=document_id,
                kb_id=kb_id,
                session_id=session_id,
                blob_name=blob_name,
                file_name=file_name,
                file_type=file_type.value,
                file_size=file_size,
                container_name=self.storage_connector.container_name,
                mime_type=mime_type,
                blob_url=blob_url,
                metadata=metadata,
                uploaded_by=uploaded_by
            )
            
            await self.commit()
            
            logger.info(
                f"Uploaded document {file_name} to KB {kb_id} "
                f"(document_id: {document_id}, size: {file_size} bytes)"
            )
            
            if not skip_processing:
                asyncio.create_task(self._process_document_async(document_id, kb_id, uploaded_by, chunking_overrides, metadata_fields, vision_config))
            
            return document
            
        except Exception as e:
            logger.error(f"Failed to upload document {file_name}: {e}")
            await self.rollback()
            raise
    
    async def upload_document_stream(
        self,
        kb_id: str,
        session_id: str,
        file_name: str,
        file_stream: BinaryIO,
        mime_type: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Document:
        """
        Upload document from stream to Azure Blob Storage.
        
        Args:
            kb_id: Knowledge base ID
            session_id: Session ID to associate document with
            file_name: Original filename
            file_stream: File stream
            mime_type: MIME type of the file
            uploaded_by: User ID who uploaded the document
            metadata: Additional metadata
        
        Returns:
            Document entity
        """
        # Skip session validation if session_id is 'default' or 'default-session'
        if session_id not in ['default', 'default-session']:
            session = await self.session_repo.get_by_id(session_id)
            if not session:
                raise SessionNotFoundException(session_id)
        
        document_id = str(uuid.uuid4())
        file_type = self._get_file_type(file_name)
        
        blob_name = f"{session_id}/{document_id}_{file_name}"
        
        try:
            file_stream.seek(0, 2)
            file_size = file_stream.tell()
            file_stream.seek(0)
            
            blob_url = await self.storage_connector.upload_stream(
                blob_name=blob_name,
                stream=file_stream,
                content_type=mime_type,
                metadata={
                    "document_id": document_id,
                    "session_id": session_id,
                    "uploaded_by": uploaded_by or "unknown",
                    **(metadata or {})
                }
            )
            
            document = await self.document_repo.create_document(
                document_id=document_id,
                kb_id=kb_id,
                session_id=session_id,
                blob_name=blob_name,
                file_name=file_name,
                file_type=file_type.value,
                file_size=file_size,
                container_name=self.storage_connector.container_name,
                mime_type=mime_type,
                blob_url=blob_url,
                metadata=metadata,
                uploaded_by=uploaded_by
            )
            
            await self.commit()
            
            logger.info(
                f"Uploaded document stream {file_name} to KB {kb_id} "
                f"(document_id: {document_id})"
            )
            
            # Process document in background (fire-and-forget)
            # Pass uploaded_by so background task can set RLS context explicitly
            # (ContextVar propagation to asyncio tasks is unreliable with ASGI middleware)
            import asyncio
            asyncio.create_task(self._process_document_async(document_id, kb_id, uploaded_by))
            
            return document
            
        except Exception as e:
            logger.error(f"Failed to upload document stream {file_name}: {e}")
            await self.rollback()
            raise
    
    async def get_document(self, document_id: str) -> Document:
        """Get document by ID."""
        document = await self.document_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundException(document_id)
        return document
    
    async def get_document_by_blob_name(self, blob_name: str) -> Optional[Document]:
        """Get document by blob name."""
        return await self.document_repo.get_by_blob_name(blob_name)
    
    async def list_kb_documents(
        self,
        kb_id: str,
        include_deleted: bool = False
    ) -> List[Document]:
        """List all documents for a knowledge base."""
        return await self.document_repo.get_by_kb_id(kb_id, include_deleted)
    
    async def download_document(self, document_id: str) -> bytes:
        """
        Download document content from Azure Blob Storage.
        
        Args:
            document_id: Document ID
        
        Returns:
            Document content as bytes
        """
        document = await self.get_document(document_id)
        
        try:
            content = await self.storage_connector.download_blob(document.blob_name)
            logger.debug(f"Downloaded document {document_id} ({len(content)} bytes)")
            return content
            
        except Exception as e:
            logger.error(f"Failed to download document {document_id}: {e}")
            raise
    
    async def download_document_to_stream(
        self,
        document_id: str,
        stream: BinaryIO
    ) -> int:
        """
        Download document to stream from Azure Blob Storage.
        
        Args:
            document_id: Document ID
            stream: Binary stream to write to
        
        Returns:
            Number of bytes downloaded
        """
        document = await self.get_document(document_id)
        
        try:
            bytes_downloaded = await self.storage_connector.download_blob_to_stream(
                document.blob_name,
                stream
            )
            logger.debug(f"Downloaded document {document_id} to stream ({bytes_downloaded} bytes)")
            return bytes_downloaded
            
        except Exception as e:
            logger.error(f"Failed to download document {document_id} to stream: {e}")
            raise
    
    async def delete_document(self, document_id: str) -> None:
        """
        Hard delete document: removes blob, chunks, and rag_document row.
        Recalculates KB counters from actual data.
        """
        document = await self.get_document(document_id)
        
        if not self.kb_service:
            from services.knowledge_base_service import KnowledgeBaseService
            from repositories.knowledge_base_repository import KnowledgeBaseRepository
            self.kb_service = KnowledgeBaseService(
                self.db,
                KnowledgeBaseRepository(self.db),
                self.session_repo
            )
        
        try:
            kb = await self.kb_service.get_knowledge_base(document.kb_id)
            
            deleted_chunks = await self.kb_service.kb_repo.delete_chunks_by_document_id(
                kb.chunk_table_name, document_id
            )
            logger.info(f"Deleted {deleted_chunks} chunks for document {document_id}")
            
            await self.storage_connector.delete_blob(document.blob_name)
            logger.info(f"Deleted blob for document {document_id}")
            
            query = text("DELETE FROM rag_document WHERE id = :document_id")
            await self.db.execute(query, {"document_id": document_id})
            
            await self.kb_service.kb_repo.recalculate_counts(kb.id, kb.chunk_table_name)
            
            await self.commit()
            logger.info(f"Permanently deleted document {document_id}")
            
        except Exception as e:
            logger.error(f"Failed to delete document {document_id}: {e}")
            await self.rollback()
            raise
    
    async def update_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        error: Optional[str] = None
    ) -> None:
        """Update document processing status."""
        await self.document_repo.update_status(document_id, status, error)
        await self.commit()
    
    async def update_extracted_text(
        self,
        document_id: str,
        extracted_text: str,
        chunk_count: Optional[int] = None
    ) -> None:
        """Update document extracted text."""
        await self.document_repo.update_extracted_text(
            document_id,
            extracted_text,
            chunk_count
        )
        await self.commit()
    
    async def get_pending_documents(self, limit: int = 50) -> List[Document]:
        """Get pending documents for processing."""
        return await self.document_repo.get_pending_documents(limit)
    
    async def count_session_documents(self, session_id: str) -> int:
        """Count documents in a session."""
        return await self.document_repo.count_by_session(session_id)
    
    async def generate_download_url(
        self,
        document_id: str,
        expiry_hours: int = 24
    ) -> str:
        """
        Generate temporary download URL for document.
        
        Args:
            document_id: Document ID
            expiry_hours: URL expiry time in hours
        
        Returns:
            Temporary SAS URL
        """
        document = await self.get_document(document_id)
        
        try:
            sas_url = await self.storage_connector.generate_sas_url(
                document.blob_name,
                expiry_hours=expiry_hours,
                permissions="r"
            )
            logger.debug(f"Generated download URL for document {document_id}")
            return sas_url
            
        except Exception as e:
            logger.error(f"Failed to generate download URL for document {document_id}: {e}")
            raise
    
    async def _process_document_async(self, document_id: str, kb_id: str, user_id: str = None, chunking_overrides: Optional[dict] = None, metadata_fields: Optional[list] = None, vision_config: Optional[dict] = None) -> None:
        """
        Process document asynchronously (extract text, create chunks, etc.).
        This runs as a background task with its own DB session.
        
        Args:
            document_id: Document ID to process
            kb_id: Knowledge base ID
            user_id: User ID who uploaded the document (needed for RLS context,
                     since ContextVar propagation to background tasks is unreliable)
            vision_config: If set, use vision LLM processing instead of text extraction
        """
        # Create new DB session for background task
        from db.pgsql import get_write_db, set_user_context
        
        async for db in get_write_db():
            try:
                # CRITICAL: Explicitly set RLS context for the background task.
                # The ContextVar from the parent request may not be available here
                # (ASGI middleware clears it after the response, and asyncio task
                # context propagation is unreliable). Without this, UPDATE/SELECT
                # on RLS-protected tables like rag_document would silently fail.
                if user_id:
                    await set_user_context(db, user_id)
                    logger.debug(f"Background task: RLS context set for user {user_id}")
                
                # Recreate repos with new session
                from repositories.document_repository import DocumentRepository
                from repositories.knowledge_base_repository import KnowledgeBaseRepository
                from services.knowledge_base_service import KnowledgeBaseService
                
                doc_repo = DocumentRepository(db)
                kb_repo = KnowledgeBaseRepository(db)
                kb_service = KnowledgeBaseService(db, kb_repo, None)
                
                await doc_repo.update_status(
                    document_id,
                    DocumentStatus.PROCESSING
                )
                await db.commit()
                
                # CRITICAL: Re-set RLS context after commit.
                # db.commit() may return the underlying connection to the pool,
                # and the next query may use a NEW connection that does NOT have
                # app.current_user_id set, causing RLS to filter out all rows.
                if user_id:
                    await set_user_context(db, user_id)
                
                document = await doc_repo.get_by_id(document_id)
                if document is None:
                    raise RuntimeError(
                        f"Document {document_id} not found after status update. "
                        f"Possible RLS context issue."
                    )
            
                content = await self.storage_connector.download_blob(document.blob_name)
                
                from utils.file_parser import FileParser
                import tempfile
                import os
                
                # Create temp file with proper cleanup
                with tempfile.NamedTemporaryFile(
                    mode='wb',
                    suffix=f"_{document.file_name}",
                    delete=False
                ) as temp_file:
                    temp_file.write(content)
                    temp_file_path = temp_file.name
                
                try:
                    if vision_config:
                        # --- Vision LLM processing path ---
                        from utils.vision_processor import process_document as vision_process

                        results = await vision_process(
                            file_path=temp_file_path,
                            prompt=vision_config["prompt"],
                            model=vision_config.get("model", "vertex_ai.gemini-2.5-flash"),
                            output_schema=vision_config.get("output_schema"),
                        )

                        if results:
                            pre_chunked_texts = [r.text for r in results]
                            pre_chunked_metadata = [
                                {"page_number": r.page_number, **(r.structured_data or {})}
                                for r in results
                            ]
                            combined_text = "\n\n".join(pre_chunked_texts)

                            chunks = await kb_service.add_chunks_to_kb(
                                kb_id=kb_id,
                                document_id=document_id,
                                text=combined_text,
                                document_name=document.file_name,
                                chunking_overrides={"method": "vision"},
                                pre_chunked_texts=pre_chunked_texts,
                                pre_chunked_metadata=pre_chunked_metadata,
                            )

                            await doc_repo.update_extracted_text(
                                document_id,
                                combined_text,
                                chunk_count=len(chunks),
                            )
                            await doc_repo.update_status(document_id, DocumentStatus.COMPLETED)
                            await kb_repo.increment_counts(
                                kb_id=kb_id, document_count=1, size_bytes=len(combined_text),
                            )
                            await db.commit()
                            logger.info(
                                "Vision-processed document %s (%d pages -> %d chunks)",
                                document_id, len(results), len(chunks),
                            )
                        else:
                            await doc_repo.update_status(
                                document_id, DocumentStatus.FAILED,
                                "Vision processing produced no results (all pages skipped)",
                            )
                            await db.commit()
                            logger.warning("Vision processing: all pages skipped for %s", document_id)
                    else:
                        # --- Standard text extraction path ---
                        success, extracted_text, parsed_elements, error = await asyncio.to_thread(
                            FileParser.parse_file,
                            temp_file_path
                        )

                        if success and extracted_text:
                            chunks = await kb_service.add_chunks_to_kb(
                                kb_id=kb_id,
                                document_id=document_id,
                                text=extracted_text,
                                document_name=document.file_name,
                                chunking_overrides=chunking_overrides,
                                parsed_elements=parsed_elements,
                                metadata_fields=metadata_fields,
                            )

                            await doc_repo.update_extracted_text(
                                document_id,
                                extracted_text,
                                chunk_count=len(chunks)
                            )
                            await doc_repo.update_status(
                                document_id,
                                DocumentStatus.COMPLETED
                            )

                            await kb_repo.increment_counts(
                                kb_id=kb_id,
                                document_count=1,
                                size_bytes=len(extracted_text)
                            )

                            await db.commit()

                            logger.info(
                                f"Processed document {document_id} "
                                f"({len(extracted_text)} chars, {len(chunks)} chunks)"
                            )
                        else:
                            await doc_repo.update_status(
                                document_id,
                                DocumentStatus.FAILED,
                                error or "Failed to extract text"
                            )
                            await db.commit()
                            logger.error(f"Failed to process document {document_id}: {error}")
                finally:
                    # Clean up temp file
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    
            except Exception as e:
                logger.error(f"Failed to process document {document_id}: {e}")
                try:
                    # Re-set RLS context in case it was lost after a prior commit
                    if user_id:
                        await set_user_context(db, user_id)
                    await doc_repo.update_status(
                        document_id,
                        DocumentStatus.FAILED,
                        str(e)
                    )
                    await db.commit()
                except Exception as commit_error:
                    logger.error(f"Failed to update document status: {commit_error}")
    
    @staticmethod
    def _get_file_type(file_name: str) -> DocumentType:
        """Get document type from filename."""
        suffix = Path(file_name).suffix.lower()[1:] if '.' in file_name else ''
        
        type_mapping = {
            'pdf': DocumentType.PDF,
            'docx': DocumentType.DOCX,
            'doc': DocumentType.DOCX,
            'txt': DocumentType.TXT,
            'csv': DocumentType.CSV,
            'json': DocumentType.JSON,
            'xml': DocumentType.XML,
            'html': DocumentType.HTML,
            'htm': DocumentType.HTML,
            'md': DocumentType.MARKDOWN,
            'markdown': DocumentType.MARKDOWN,
            'png': DocumentType.IMAGE,
            'jpg': DocumentType.IMAGE,
            'jpeg': DocumentType.IMAGE,
            'gif': DocumentType.IMAGE,
            'bmp': DocumentType.IMAGE,
        }
        
        return type_mapping.get(suffix, DocumentType.OTHER)

