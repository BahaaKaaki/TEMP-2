"""
Knowledge Base service for managing RAG knowledge bases.
"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import uuid
import logging
import re
import asyncio

from .base import BaseService
from utils.embedding import EmbeddingClient
from repositories.knowledge_base_repository import KnowledgeBaseRepository
from repositories import SessionRepository
from domain.entities.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseStatus,
    ChunkingConfig,
    EmbeddingModel,
    ChunkingMethod,
    DocumentChunk,
    MetadataFieldDef,
    MetadataFieldType,
    MetadataFieldScope,
)
from core.exceptions import SessionNotFoundException
from utils.chunking import TextChunker


logger = logging.getLogger(__name__)


class KnowledgeBaseNotFoundException(Exception):
    """Exception raised when knowledge base is not found."""
    
    def __init__(self, kb_id: str):
        self.kb_id = kb_id
        super().__init__(f"Knowledge base not found: {kb_id}")


class KnowledgeBaseService(BaseService):
    """Service for managing knowledge bases."""
    
    def __init__(
        self,
        db: AsyncSession,
        kb_repo: KnowledgeBaseRepository,
        session_repo: SessionRepository
    ):
        super().__init__(db)
        self.kb_repo = kb_repo
        self.session_repo = session_repo
    
    async def create_knowledge_base(
        self,
        session_id: str,
        name: str,
        chunking_method: ChunkingMethod,
        chunk_size: int,
        chunk_overlap: int,
        embedding_model: EmbeddingModel,
        description: Optional[str] = None,
        separators: Optional[List[str]] = None,
        delimiter: Optional[str] = None,
        metadata: Optional[dict] = None,
        created_by: Optional[str] = None,
        metadata_fields: Optional[List[dict]] = None,
    ) -> KnowledgeBase:
        """
        Create a new knowledge base with dynamic chunk table.
        
        Args:
            session_id: Session ID (can be 'default' for standalone KBs)
            name: KB name
            chunking_method: Chunking strategy
            chunk_size: Size of chunks
            chunk_overlap: Overlap between chunks
            embedding_model: Embedding model to use
            description: KB description
            separators: Custom separators for recursive chunking
            metadata: Additional metadata
            created_by: User ID who created KB
        
        Returns:
            KnowledgeBase entity
        """
        # Skip session validation if session_id is 'default' or 'default-session'
        if session_id not in ['default', 'default-session']:
            session = await self.session_repo.get_by_id(session_id)
            if not session:
                raise SessionNotFoundException(session_id)
        
        existing_kb = await self.kb_repo.get_by_name(session_id, name)
        if existing_kb:
            raise ValueError(f"Knowledge base with name '{name}' already exists")
        
        chunking_config = ChunkingConfig(
            method=chunking_method,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            delimiter=delimiter
        )
        
        is_valid, error = TextChunker.validate_config(chunking_config)
        if not is_valid:
            raise ValueError(f"Invalid chunking configuration: {error}")
        
        kb_id = str(uuid.uuid4())
        
        sanitized_name = re.sub(r'[^a-z0-9_]', '_', name.lower())
        chunk_table_name = f"kb_chunks_{kb_id.replace('-', '_')}"
        azure_folder_path = f"{session_id}/{sanitized_name}_{kb_id}"
        
        vector_dimension = self._get_vector_dimension(embedding_model)

        validated_schema: Optional[list] = None
        if metadata_fields:
            seen_names: set = set()
            validated_schema = []
            for mf in metadata_fields:
                fname = mf.get("name", "").strip()
                if not fname or fname in seen_names:
                    continue
                seen_names.add(fname)
                MetadataFieldType(mf["type"])
                MetadataFieldScope(mf["scope"])
                validated_schema.append({
                    "name": fname,
                    "type": mf["type"],
                    "scope": mf["scope"],
                    "description": mf.get("description"),
                })

        try:
            await self.kb_repo.create_chunk_table(
                chunk_table_name,
                vector_dimension,
                metadata_fields=validated_schema,
            )

            kb = await self.kb_repo.create_kb(
                kb_id=kb_id,
                session_id=session_id,
                name=name,
                azure_folder_path=azure_folder_path,
                chunk_table_name=chunk_table_name,
                chunking_config=chunking_config,
                embedding_model=embedding_model,
                vector_dimension=vector_dimension,
                description=description,
                metadata=metadata,
                created_by=created_by,
                metadata_schema=validated_schema,
            )
            
            await self.kb_repo.update_status(kb_id, KnowledgeBaseStatus.ACTIVE)
            await self.commit()
            
            logger.info(
                f"Created knowledge base '{name}' (id: {kb_id}, "
                f"table: {chunk_table_name}, folder: {azure_folder_path})"
            )
            
            kb.status = KnowledgeBaseStatus.ACTIVE
            return kb
            
        except Exception as e:
            logger.error(f"Failed to create knowledge base '{name}': {e}")
            
            try:
                await self.kb_repo.drop_chunk_table(chunk_table_name)
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup chunk table: {cleanup_error}")
            
            await self.rollback()
            raise
    
    async def get_knowledge_base(self, kb_id: str) -> KnowledgeBase:
        """Get knowledge base by ID."""
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundException(kb_id)
        return kb
    
    async def list_all_knowledge_bases(
        self,
        include_deleted: bool = False
    ) -> List[KnowledgeBase]:
        """List all knowledge bases (across all sessions)."""
        return await self.kb_repo.list_all(include_deleted)
    
    async def list_session_knowledge_bases(
        self,
        session_id: str,
        include_deleted: bool = False
    ) -> List[KnowledgeBase]:
        """List all knowledge bases for a session."""
        return await self.kb_repo.get_by_session_id(session_id, include_deleted)
    
    async def delete_knowledge_base(
        self,
        kb_id: str,
        storage_connector=None
    ) -> None:
        """
        Hard delete knowledge base and all associated data:
        blobs, rag_document rows, chunk table, structured data, and KB row.
        """
        kb = await self.get_knowledge_base(kb_id)
        
        try:
            if storage_connector:
                from repositories.document_repository import DocumentRepository
                doc_repo = DocumentRepository(self.db)
                documents = await doc_repo.get_by_kb_id(kb_id, include_deleted=True)
                for doc in documents:
                    try:
                        await storage_connector.delete_blob(doc.blob_name)
                    except Exception as blob_err:
                        logger.warning(f"Failed to delete blob {doc.blob_name}: {blob_err}")
                logger.info(f"Deleted {len(documents)} blobs for KB {kb_id}")
            
            await self.kb_repo.drop_chunk_table(kb.chunk_table_name)
            logger.debug(f"Dropped chunk table {kb.chunk_table_name}")
            
            if kb.has_structured_data:
                try:
                    from repositories.structured_data_repository import StructuredDataRepository
                    structured_repo = StructuredDataRepository(self.db)
                    schema_name = f"kb_data_{kb_id[:8]}"
                    await structured_repo.drop_schema(schema_name)
                    logger.debug(f"Dropped structured data schema {schema_name}")
                except Exception as schema_err:
                    logger.error(f"Failed to drop structured schema: {schema_err}")
            
            delete_docs_sql = text('DELETE FROM rag_document WHERE "kbId" = :kb_id')
            await self.db.execute(delete_docs_sql, {"kb_id": kb_id})
            
            delete_kb_sql = text("DELETE FROM knowledge_base WHERE id = :kb_id")
            await self.db.execute(delete_kb_sql, {"kb_id": kb_id})
            
            await self.commit()
            logger.info(f"Permanently deleted knowledge base {kb_id} and all associated data")
            
        except Exception as e:
            logger.error(f"Failed to delete knowledge base {kb_id}: {e}")
            await self.rollback()
            raise
    
    async def add_chunks_to_kb(
        self,
        kb_id: str,
        document_id: str,
        text: str,
        document_name: Optional[str] = None,
        chunking_overrides: Optional[dict] = None,
        parsed_elements: Optional[list] = None,
        metadata_fields: Optional[list] = None,
        pre_chunked_texts: Optional[List[str]] = None,
        pre_chunked_metadata: Optional[List[dict]] = None,
    ) -> List[DocumentChunk]:
        """
        Chunk text and add to KB with parallel embedding processing.
        
        Args:
            kb_id: KB ID
            document_id: Document ID
            text: Text to chunk (also used for global metadata inference)
            document_name: Document filename (for BM25 search enhancement)
            chunking_overrides: Per-document chunking config that overrides KB defaults
            parsed_elements: Structured elements from FileParser (needed for page chunking)
            metadata_fields: Per-document metadata field definitions for LLM inference
            pre_chunked_texts: Pre-made chunk texts (e.g. from vision processing).
                When provided, the TextChunker is bypassed entirely.
            pre_chunked_metadata: Per-chunk metadata dicts to merge into each chunk's
                metadata field.  Must be same length as pre_chunked_texts.
        
        Returns:
            List of created chunks
        """
        kb = await self.get_knowledge_base(kb_id)
        
        if not kb.can_add_documents():
            raise ValueError(f"Knowledge base {kb_id} is not active")
        
        try:
            # Vision / pre-chunked path: chunks are already provided by the caller
            if pre_chunked_texts:
                chunks_text = pre_chunked_texts
            else:
                # Determine effective chunking method
                if chunking_overrides:
                    effective_config = ChunkingConfig(
                        method=ChunkingMethod(chunking_overrides["method"]),
                        chunk_size=chunking_overrides.get("chunk_size", 1000),
                        chunk_overlap=chunking_overrides.get("chunk_overlap", 0),
                        separators=chunking_overrides.get("separators"),
                        delimiter=chunking_overrides.get("delimiter"),
                    )
                    is_valid, error = TextChunker.validate_config(effective_config)
                    if not is_valid:
                        logger.warning("Invalid per-doc chunking config (%s), falling back to KB default", error)
                        effective_config = kb.chunking_config
                else:
                    effective_config = kb.chunking_config

                # Page chunking: group by page from parsed elements (bypasses TextChunker)
                if effective_config.method == ChunkingMethod.PAGE:
                    from utils.file_parser import FileParser
                    page_chunks = await asyncio.to_thread(
                        FileParser.group_elements_by_page,
                        parsed_elements,
                    )
                    if page_chunks:
                        chunks_text = page_chunks
                    else:
                        logger.warning(
                            "Page chunking produced no pages for document %s — "
                            "file type may lack page metadata. Falling back to recursive.",
                            document_id,
                        )
                        chunks_text = await asyncio.to_thread(
                            TextChunker.chunk_text,
                            text,
                            ChunkingConfig(
                                method=ChunkingMethod.RECURSIVE,
                                chunk_size=1000,
                                chunk_overlap=0,
                            ),
                        )
                else:
                    chunks_text = await asyncio.to_thread(
                        TextChunker.chunk_text,
                        text,
                        effective_config,
                    )
            
            logger.debug(f"📝 Created {len(chunks_text)} chunks for document {document_id}")
            
            # Generate embeddings for all chunks with parallel batch processing
            
            model_name = kb.embedding_model.api_model_id
            embedding_client = EmbeddingClient(model=model_name)

            async def _embed():
                try:
                    embs = await embedding_client.create_embeddings(
                        chunks_text, batch_size=50, max_concurrent_batches=5,
                    )
                    ok = len([e for e in embs if e is not None])
                    logger.debug(
                        "✅ Generated embeddings for document %s: %d/%d successful",
                        document_id, ok, len(embs),
                    )
                    return embs
                except Exception as e:
                    logger.warning(
                        "⚠️  Failed to generate embeddings: %s — storing without.", e,
                    )
                    return [None] * len(chunks_text)

            # Resolve effective metadata schema: per-document overrides KB-level
            effective_meta_schema = None
            if metadata_fields:
                from domain.entities.knowledge_base import MetadataFieldDef, MetadataFieldType, MetadataFieldScope
                try:
                    validated = []
                    seen = set()
                    for mf in metadata_fields:
                        fname = mf.get("name", "").strip()
                        if not fname or fname in seen:
                            continue
                        seen.add(fname)
                        MetadataFieldType(mf["type"])
                        MetadataFieldScope(mf["scope"])
                        validated.append(MetadataFieldDef(
                            name=fname,
                            type=MetadataFieldType(mf["type"]),
                            scope=MetadataFieldScope(mf["scope"]),
                            description=mf.get("description"),
                        ))
                    if validated:
                        effective_meta_schema = validated
                except (KeyError, ValueError) as e:
                    logger.warning("Invalid per-doc metadata_fields (%s), trying KB default", e)

            if not effective_meta_schema and kb.metadata_schema:
                effective_meta_schema = kb.metadata_schema

            async def _infer_meta():
                if not effective_meta_schema:
                    return [None] * len(chunks_text)
                try:
                    from utils.metadata_inference import infer_all_metadata
                    meta_list = await infer_all_metadata(
                        text, chunks_text, effective_meta_schema,
                    )
                    logger.debug(
                        "✅ Inferred metadata for %d chunks (document %s)",
                        len(meta_list), document_id,
                    )
                    return meta_list
                except Exception as e:
                    logger.warning(
                        "⚠️  Metadata inference failed for document %s: %s", document_id, e,
                    )
                    return [None] * len(chunks_text)

            embeddings, chunk_metadata_list = await asyncio.gather(
                _embed(), _infer_meta(),
            )

            chunks = []
            for idx, (chunk_text, embedding) in enumerate(zip(chunks_text, embeddings)):
                meta = (
                    chunk_metadata_list[idx]
                    if chunk_metadata_list and idx < len(chunk_metadata_list)
                    else None
                )
                if effective_meta_schema and document_name:
                    meta = meta or {}
                    meta["file_name"] = document_name
                # Merge pre-chunked metadata (from vision processing, etc.)
                if pre_chunked_metadata and idx < len(pre_chunked_metadata):
                    meta = {**(meta or {}), **pre_chunked_metadata[idx]}
                chunk = DocumentChunk(
                    id=str(uuid.uuid4()),
                    kb_id=kb_id,
                    document_id=document_id,
                    chunk_index=idx,
                    chunk_text=chunk_text,
                    chunk_size=len(chunk_text),
                    document_title=document_name,
                    embedding=embedding,
                    embedding_status='completed' if embedding else 'failed',
                    metadata=meta,
                    created_at=datetime.utcnow()
                )
                chunks.append(chunk)
            
            # Batch insert all chunks in a single query (95%+ faster than loop)
            await self.kb_repo.bulk_insert_chunks(kb.chunk_table_name, chunks)
            
            await self.kb_repo.increment_counts(
                kb_id=kb_id,
                chunk_count=len(chunks)
            )
            
            # NOTE: Don't commit here - let the calling code handle transaction
            # This allows the document service to update document status in the same transaction
            
            logger.debug(
                f"💾 Prepared {len(chunks)} chunks for KB {kb_id} "
                f"(document: {document_id}, will be committed by caller)"
            )
            
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to add chunks to KB {kb_id}: {e}")
            await self.rollback()
            raise
    
    async def get_document_chunks(
        self,
        kb_id: str,
        document_id: str
    ) -> List[DocumentChunk]:
        """Get all chunks for a document."""
        kb = await self.get_knowledge_base(kb_id)
        return await self.kb_repo.get_chunks_by_document(
            kb.chunk_table_name,
            document_id
        )
    
    async def similarity_search(
        self,
        kb_id: str,
        query_embedding: List[float],
        limit: int = 10,
        distance_threshold: Optional[float] = None,
        use_sphere: bool = True
    ) -> List[dict]:
        """
        Perform similarity search in KB using L2 distance.
        
        Args:
            kb_id: KB ID
            query_embedding: Query vector
            limit: Maximum results
            distance_threshold: Maximum distance (lower = more similar)
            use_sphere: Use sphere search (faster, recommended for RAG)
        
        Returns:
            List of matching chunks with distance scores
        """
        kb = await self.get_knowledge_base(kb_id)
        
        results = await self.kb_repo.similarity_search(
            table_name=kb.chunk_table_name,
            kb_id=kb_id,
            query_embedding=query_embedding,
            limit=limit,
            distance_threshold=distance_threshold,
            use_sphere=use_sphere
        )
        
        return [
            {
                "chunk_id": row[0],
                "document_id": row[1],
                "chunk_index": row[2],
                "chunk_text": row[3],
                "chunk_size": row[4],
                "metadata": row[5],
                "created_at": row[6],
                "distance": float(row[7])
            }
            for row in results
        ]
    
    @staticmethod
    def _get_vector_dimension(embedding_model: EmbeddingModel) -> int:
        """Get vector dimension for embedding model."""
        return embedding_model.dimension


from datetime import datetime

