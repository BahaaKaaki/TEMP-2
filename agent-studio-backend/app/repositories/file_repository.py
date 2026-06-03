"""
File repository for data access.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from .base import BaseRepository
from db.models import ChatFile
from domain.entities import File


class FileRepository(BaseRepository[ChatFile, File]):
    """Repository for file data access."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, ChatFile)
    
    async def get_by_id(self, file_id: str) -> Optional[File]:
        """Get file by ID."""
        query = select(ChatFile).where(ChatFile.id == file_id)
        result = await self.db.execute(query)
        db_file = result.scalar_one_or_none()
        
        if not db_file:
            return None
        
        return self._to_domain(db_file)
    
    async def get_by_session_id(
        self,
        session_id: str,
        include_deleted: bool = False
    ) -> List[File]:
        """Get all files for a session."""
        query = select(ChatFile).where(
            ChatFile.sessionId == session_id
        )
        
        if not include_deleted:
            query = query.where(ChatFile.deletedAt == None)
        
        query = query.order_by(ChatFile.createdAt.asc())
        
        result = await self.db.execute(query)
        files = result.scalars().all()
        
        return [self._to_domain(f) for f in files]
    
    async def get_parsed_files_by_session(
        self,
        session_id: str
    ) -> List[File]:
        """Get all successfully parsed files for a session."""
        query = select(ChatFile).where(
            and_(
                ChatFile.sessionId == session_id,
                ChatFile.parsingStatus == "completed",
                ChatFile.deletedAt == None
            )
        ).order_by(ChatFile.createdAt.asc())
        
        result = await self.db.execute(query)
        files = result.scalars().all()
        
        return [self._to_domain(f) for f in files]
    
    async def get_local_files_for_agent(
        self,
        session_id: str,
        agent_id: str
    ) -> List[File]:
        """Get parsed local-scope files stamped to a specific agent.
        
        Used by the chat-send path to glue only that agent's local files
        into the user message (matches today's per-turn behaviour).
        """
        query = select(ChatFile).where(
            and_(
                ChatFile.sessionId == session_id,
                ChatFile.parsingStatus == "completed",
                ChatFile.deletedAt == None,
                ChatFile.scope == "local",
                ChatFile.uploadedAtAgentId == agent_id,
            )
        ).order_by(ChatFile.createdAt.asc())
        
        result = await self.db.execute(query)
        files = result.scalars().all()
        return [self._to_domain(f) for f in files]
    
    async def get_global_files_by_session(
        self,
        session_id: str
    ) -> List[File]:
        """Get parsed global-scope files for a session.
        
        Used by the workflow layer to inject document context into every
        agent's system prompt.
        
        Treats ``scope IS NULL`` as 'global' so legacy rows that pre-date
        the per-agent scope migration (or environments that auto-added
        the column without a DEFAULT) keep behaving like today: visible
        to every agent.
        """
        from sqlalchemy import or_
        query = select(ChatFile).where(
            and_(
                ChatFile.sessionId == session_id,
                ChatFile.parsingStatus == "completed",
                ChatFile.deletedAt == None,
                or_(
                    ChatFile.scope == "global",
                    ChatFile.scope == None,  # noqa: E711 — SQLAlchemy IS NULL
                ),
            )
        ).order_by(ChatFile.createdAt.asc())
        
        result = await self.db.execute(query)
        files = result.scalars().all()
        return [self._to_domain(f) for f in files]
    
    async def create_file(
        self,
        file_id: str,
        session_id: str,
        file_name: str,
        file_type: str,
        file_size: int,
        mime_type: Optional[str] = None,
        message_id: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        file_path: Optional[str] = None,
        container_name: Optional[str] = None,
        blob_name: Optional[str] = None,
        blob_url: Optional[str] = None,
        uploaded_at_agent_id: Optional[str] = None,
        uploaded_at_agent_label: Optional[str] = None,
        scope: str = "global",
    ) -> File:
        """Create new file record."""
        db_file = ChatFile(
            id=file_id,
            sessionId=session_id,
            messageId=message_id,
            fileName=file_name,
            fileType=file_type,
            filePath=file_path,
            fileSize=file_size,
            mimeType=mime_type,
            containerName=container_name,
            blobName=blob_name,
            blobUrl=blob_url,
            parsingStatus="pending",
            uploadedBy=uploaded_by,
            uploadedAtAgentId=uploaded_at_agent_id,
            uploadedAtAgentLabel=uploaded_at_agent_label,
            scope=scope,
            createdAt=datetime.utcnow(),
            updatedAt=datetime.utcnow()
        )
        
        await self.create(db_file)
        return self._to_domain(db_file)
    
    async def update_parsing_status(
        self,
        file_id: str,
        status: str,
        extracted_text: Optional[str] = None,
        parsed_elements: Optional[str] = None,
        error: Optional[str] = None
    ) -> File:
        """Update file parsing status."""
        query = select(ChatFile).where(ChatFile.id == file_id)
        result = await self.db.execute(query)
        db_file = result.scalar_one_or_none()
        if not db_file:
            raise ValueError(
                f"File {file_id} not found for parsing status update "
                f"(check RLS context matches uploadedBy)"
            )
        
        db_file.parsingStatus = status
        db_file.extractedText = extracted_text
        db_file.parsedElements = parsed_elements
        db_file.parsingError = error
        db_file.updatedAt = datetime.utcnow()
        
        await self.db.flush()
        await self.db.refresh(db_file)
        
        return self._to_domain(db_file)
    
    async def soft_delete(self, file_id: str) -> None:
        """Soft delete file."""
        query = select(ChatFile).where(ChatFile.id == file_id)
        result = await self.db.execute(query)
        db_file = result.scalar_one()
        
        db_file.deletedAt = datetime.utcnow()
        
        await self.db.flush()
    
    def _to_domain(self, db_file: ChatFile) -> File:
        """Convert database model to domain entity."""
        return File(
            id=db_file.id,
            session_id=db_file.sessionId,
            message_id=db_file.messageId,
            file_name=db_file.fileName,
            file_type=db_file.fileType,
            file_path=db_file.filePath,
            file_size=db_file.fileSize,
            mime_type=db_file.mimeType,
            extracted_text=db_file.extractedText,
            parsed_elements=db_file.parsedElements,
            parsing_status=db_file.parsingStatus,
            parsing_error=db_file.parsingError,
            uploaded_by=db_file.uploadedBy,
            description=db_file.description,
            container_name=getattr(db_file, 'containerName', None),
            blob_name=getattr(db_file, 'blobName', None),
            blob_url=getattr(db_file, 'blobUrl', None),
            uploaded_at_agent_id=getattr(db_file, 'uploadedAtAgentId', None),
            uploaded_at_agent_label=getattr(db_file, 'uploadedAtAgentLabel', None),
            scope=getattr(db_file, 'scope', None) or 'global',
            created_at=db_file.createdAt,
            updated_at=db_file.updatedAt,
            deleted_at=db_file.deletedAt
        )

