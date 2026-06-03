"""
Document repository for RAG capabilities with Azure Blob Storage.
"""
from typing import Optional, List
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
import json
from datetime import datetime

from .base import BaseRepository
from db.models import DocumentEntity
from domain.entities.document import Document, DocumentStatus, DocumentType


class DocumentRepository(BaseRepository[DocumentEntity, Document]):
    """Repository for managing RAG documents in Azure Blob Storage."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, DocumentEntity)
    
    def _to_domain(self, entity: DocumentEntity) -> Document:
        """Convert database entity to domain entity."""
        return Document(
            id=entity.id,
            kb_id=entity.kbId,
            session_id=entity.sessionId,
            blob_name=entity.blobName,
            file_name=entity.fileName,
            file_type=DocumentType(entity.fileType),
            file_size=entity.fileSize,
            mime_type=entity.mimeType,
            status=DocumentStatus(entity.status),
            container_name=entity.containerName,
            blob_url=entity.blobUrl,
            metadata=json.loads(entity.doc_metadata) if entity.doc_metadata else None,
            extracted_text=entity.extractedText,
            chunk_count=entity.chunkCount,
            embedding_status=entity.embeddingStatus,
            processing_error=entity.processingError,
            uploaded_by=entity.uploadedBy,
            created_at=entity.createdAt,
            updated_at=entity.updatedAt,
            deleted_at=entity.deletedAt
        )
    
    async def create_document(
        self,
        document_id: str,
        kb_id: str,
        session_id: str,
        blob_name: str,
        file_name: str,
        file_type: str,
        file_size: int,
        container_name: str,
        mime_type: Optional[str] = None,
        blob_url: Optional[str] = None,
        metadata: Optional[dict] = None,
        uploaded_by: Optional[str] = None
    ) -> Document:
        """Create new document record."""
        entity = DocumentEntity(
            id=document_id,
            kbId=kb_id,
            sessionId=session_id,
            blobName=blob_name,
            fileName=file_name,
            fileType=file_type,
            fileSize=file_size,
            containerName=container_name,
            mimeType=mime_type,
            blobUrl=blob_url,
            status=DocumentStatus.PENDING.value,
            doc_metadata=json.dumps(metadata) if metadata else None,
            uploadedBy=uploaded_by,
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow()
        )
        
        await self.create(entity)
        return self._to_domain(entity)
    
    async def get_by_id(self, document_id: str) -> Optional[Document]:
        """Get document by ID."""
        entity = await super().get_by_id(document_id)
        return self._to_domain(entity) if entity else None
    
    async def get_by_blob_name(self, blob_name: str) -> Optional[Document]:
        """Get document by blob name."""
        query = select(DocumentEntity).where(DocumentEntity.blobName == blob_name)
        result = await self.db.execute(query)
        entity = result.scalar_one_or_none()
        return self._to_domain(entity) if entity else None
    
    async def get_by_kb_id(
        self,
        kb_id: str,
        include_deleted: bool = False
    ) -> List[Document]:
        """Get all documents for a knowledge base."""
        query = select(DocumentEntity).where(DocumentEntity.kbId == kb_id)
        
        if not include_deleted:
            query = query.where(DocumentEntity.deletedAt.is_(None))
        
        query = query.order_by(DocumentEntity.createdAt.desc())
        
        result = await self.db.execute(query)
        entities = result.scalars().all()
        return [self._to_domain(entity) for entity in entities]
    
    async def get_by_status(
        self,
        status: DocumentStatus,
        limit: int = 100
    ) -> List[Document]:
        """Get documents by processing status."""
        query = (
            select(DocumentEntity)
            .where(
                and_(
                    DocumentEntity.status == status.value,
                    DocumentEntity.deletedAt.is_(None)
                )
            )
            .order_by(DocumentEntity.createdAt.asc())
            .limit(limit)
        )
        
        result = await self.db.execute(query)
        entities = result.scalars().all()
        return [self._to_domain(entity) for entity in entities]
    
    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        error: Optional[str] = None
    ) -> None:
        """Update document processing status."""
        values = {
            "status": status.value,
            "updatedAt": datetime.utcnow()
        }
        
        if error:
            values["processingError"] = error
        
        query = (
            update(DocumentEntity)
            .where(DocumentEntity.id == document_id)
            .values(**values)
        )
        
        await self.db.execute(query)
    
    async def update_extracted_text(
        self,
        document_id: str,
        extracted_text: str,
        chunk_count: Optional[int] = None
    ) -> None:
        """Update document extracted text and chunk count."""
        values = {
            "extractedText": extracted_text,
            "updatedAt": datetime.utcnow()
        }
        
        if chunk_count is not None:
            values["chunkCount"] = chunk_count
        
        query = (
            update(DocumentEntity)
            .where(DocumentEntity.id == document_id)
            .values(**values)
        )
        
        await self.db.execute(query)
    
    async def update_embedding_status(
        self,
        document_id: str,
        embedding_status: str
    ) -> None:
        """Update document embedding status."""
        query = (
            update(DocumentEntity)
            .where(DocumentEntity.id == document_id)
            .values(
                embeddingStatus=embedding_status,
                updatedAt=datetime.utcnow()
            )
        )
        
        await self.db.execute(query)
    
    async def update_metadata(
        self,
        document_id: str,
        metadata: dict
    ) -> None:
        """Update document metadata."""
        query = (
            update(DocumentEntity)
            .where(DocumentEntity.id == document_id)
            .values(
                doc_metadata=json.dumps(metadata),
                updatedAt=datetime.utcnow()
            )
        )
        
        await self.db.execute(query)
    
    async def soft_delete(self, document_id: str) -> None:
        """Soft delete document."""
        query = (
            update(DocumentEntity)
            .where(DocumentEntity.id == document_id)
            .values(
                deletedAt=datetime.utcnow(),
                updatedAt=datetime.utcnow()
            )
        )
        
        await self.db.execute(query)
    
    async def restore(self, document_id: str) -> None:
        """Restore soft-deleted document."""
        query = (
            update(DocumentEntity)
            .where(DocumentEntity.id == document_id)
            .values(
                deletedAt=None,
                updatedAt=datetime.utcnow()
            )
        )
        
        await self.db.execute(query)
    
    async def count_by_session(self, session_id: str) -> int:
        """Count documents in a session."""
        from sqlalchemy import func
        
        query = select(func.count(DocumentEntity.id)).where(
            and_(
                DocumentEntity.sessionId == session_id,
                DocumentEntity.deletedAt.is_(None)
            )
        )
        
        result = await self.db.execute(query)
        return result.scalar()
    
    async def get_pending_documents(self, limit: int = 50) -> List[Document]:
        """Get pending documents for processing."""
        return await self.get_by_status(DocumentStatus.PENDING, limit)
    
    async def get_failed_documents(self, limit: int = 100) -> List[Document]:
        """Get failed documents for review."""
        return await self.get_by_status(DocumentStatus.FAILED, limit)

