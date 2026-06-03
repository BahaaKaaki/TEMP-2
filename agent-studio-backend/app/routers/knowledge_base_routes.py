"""
Knowledge Base management routes for RAG system.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Literal, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from pydantic import BaseModel
from services.knowledge_base_service import (
    KnowledgeBaseService,
    KnowledgeBaseNotFoundException
)
from core.dependencies import (
    get_knowledge_base_service,
    get_current_user,
    get_document_service,
    get_structured_data_service,
    get_azure_storage_connector,
    get_db_with_user_context,
)
from services.sharing_access import (
    kb_shows_in_my_tools,
    load_user_group_ids,
    resolve_kb_effective_access,
)
from connectors import AzureStorageConnector
from services.document_service import DocumentService
from services.structured_data_service import StructuredDataService
from db.pgsql import get_write_db
from db.models import User
from core.exceptions import SessionNotFoundException, DomainException
from domain.entities.knowledge_base import ChunkingMethod, EmbeddingModel
from schemas import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseListResponse,
    KnowledgeBaseDetailResponse,
    ChunkSearchRequest,
    ChunkSearchResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/knowledge-bases",
    tags=["Knowledge Bases"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


@router.post("/", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
    request: KnowledgeBaseCreateRequest,
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service)
):
    """Create a new knowledge base with custom chunking configuration."""
    try:
        metadata_fields_raw = None
        if request.metadata_fields:
            metadata_fields_raw = [mf.model_dump() for mf in request.metadata_fields]

        chunking_method = ChunkingMethod(request.chunking_method) if request.chunking_method else ChunkingMethod.RECURSIVE
        chunk_size = request.chunk_size if request.chunk_size is not None else 1000
        chunk_overlap = request.chunk_overlap if request.chunk_overlap is not None else 0

        kb = await kb_service.create_knowledge_base(
            session_id=request.session_id,
            name=request.name,
            chunking_method=chunking_method,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_model=EmbeddingModel(request.embedding_model),
            description=request.description,
            separators=request.separators,
            delimiter=request.delimiter,
            metadata=request.metadata,
            created_by=current_user.id,
            metadata_fields=metadata_fields_raw,
        )

        resp_schema = None
        if kb.metadata_schema:
            from schemas import MetadataFieldSchema
            resp_schema = [
                MetadataFieldSchema(
                    name=f.name, type=f.type.value, scope=f.scope.value,
                    description=f.description,
                )
                for f in kb.metadata_schema
            ]

        return KnowledgeBaseResponse(
            kb_id=kb.id,
            name=kb.name,
            description=kb.description,
            status=kb.status.value,
            azure_folder_path=kb.azure_folder_path,
            chunk_table_name=kb.chunk_table_name,
            chunking_method=kb.chunking_config.method.value,
            chunk_size=kb.chunking_config.chunk_size,
            chunk_overlap=kb.chunking_config.chunk_overlap,
            embedding_model=kb.embedding_model.value,
            vector_dimension=kb.vector_dimension,
            document_count=kb.document_count,
            chunk_count=kb.chunk_count,
            created_at=kb.created_at,
            message=f"Knowledge base '{kb.name}' created successfully",
            metadata_schema=resp_schema,
        )
    
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create knowledge base")


@router.get("/", response_model=KnowledgeBaseListResponse)
async def list_all_knowledge_bases(
    include_deleted: bool = False,
    search: Optional[str] = Query(None, description="Search by KB name or description"),
    scope: Literal["manage", "attach"] = Query(
        "manage",
        description=(
            "manage: owned and write-shared KBs for My Tools. "
            "attach: all visible KBs including read-only shares and marketplace (workflow picker)."
        ),
    ),
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service)
):
    """List knowledge bases visible to the user (RLS), filtered by scope."""
    try:
        kbs = await kb_service.list_all_knowledge_bases(include_deleted=include_deleted)
        
        if search:
            search_lower = search.lower()
            kbs = [kb for kb in kbs if 
                   search_lower in (kb.name or '').lower() or 
                   search_lower in (kb.description or '').lower()]
        
        # Sort: pinned first, then by last_accessed_at, then by created_at
        kbs.sort(key=lambda kb: (
            not getattr(kb, 'is_pinned', False),
            -(getattr(kb, 'last_accessed_at', None) or kb.created_at).timestamp() if (getattr(kb, 'last_accessed_at', None) or kb.created_at) else 0
        ))
        
        group_ids = await load_user_group_ids(kb_service.db, current_user.id)
        kb_items = []
        for kb in kbs:
            access = await resolve_kb_effective_access(
                kb_service.db,
                kb.id,
                current_user.id,
                owner_id=kb.created_by,
                is_public=kb.is_public,
                group_ids=group_ids,
            )
            if scope == "manage" and not kb_shows_in_my_tools(access):
                continue
            kb_items.append({
                "kb_id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "status": kb.status.value,
                "document_count": kb.document_count,
                "chunk_count": kb.chunk_count,
                "total_size_mb": kb.get_total_size_mb(),
                "chunking_method": kb.chunking_config.method.value,
                "created_at": kb.created_at.isoformat(),
                "created_by": kb.created_by,
                "is_shared": access == "read",
                "share_access": access,
                "is_pinned": getattr(kb, 'is_pinned', False),
                "last_accessed_at": (
                    getattr(kb, 'last_accessed_at', None).isoformat()
                    if getattr(kb, 'last_accessed_at', None)
                    else None
                ),
            })

        return KnowledgeBaseListResponse(
            knowledge_bases=kb_items,
            total=len(kb_items),
        )
    
    except Exception as e:
        logger.error(f"Error listing all knowledge bases: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list knowledge bases")


@router.get("/sessions/{session_id}", response_model=KnowledgeBaseListResponse)
async def list_session_knowledge_bases(
    session_id: str,
    include_deleted: bool = False,
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service)
):
    """List all knowledge bases in a session."""
    try:
        kbs = await kb_service.list_session_knowledge_bases(
            session_id=session_id,
            include_deleted=include_deleted
        )
        
        return KnowledgeBaseListResponse(
            knowledge_bases=[
                {
                    "kb_id": kb.id,
                    "name": kb.name,
                    "description": kb.description,
                    "status": kb.status.value,
                    "document_count": kb.document_count,
                    "chunk_count": kb.chunk_count,
                    "total_size_mb": kb.get_total_size_mb(),
                    "created_at": kb.created_at.isoformat()
                }
                for kb in kbs
            ],
            total=len(kbs)
        )
    
    except Exception as e:
        logger.error(f"Error listing knowledge bases: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list knowledge bases")


@router.get("/{kb_id}", response_model=KnowledgeBaseDetailResponse)
async def get_knowledge_base_details(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service)
):
    """Get detailed knowledge base information."""
    try:
        kb = await kb_service.get_knowledge_base(kb_id)
        access = await resolve_kb_effective_access(
            kb_service.db,
            kb.id,
            current_user.id,
            owner_id=kb.created_by,
            is_public=kb.is_public,
        )

        return KnowledgeBaseDetailResponse(
            kb_id=kb.id,
            session_id=kb.session_id,
            name=kb.name,
            description=kb.description,
            azure_folder_path=kb.azure_folder_path,
            chunk_table_name=kb.chunk_table_name,
            chunking_config=kb.chunking_config.to_dict(),
            embedding_model=kb.embedding_model.value,
            vector_dimension=kb.vector_dimension,
            status=kb.status.value,
            document_count=kb.document_count,
            chunk_count=kb.chunk_count,
            total_size_bytes=kb.total_size_bytes,
            metadata=kb.metadata,
            created_by=kb.created_by,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
            share_access=access,
        )
    
    except KnowledgeBaseNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get knowledge base")


@router.patch("/{kb_id}/pin")
async def toggle_kb_pin(
    kb_id: str,
    pinned: bool = Query(..., description="True to pin, False to unpin"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_write_db)
):
    """Toggle pin status for a knowledge base."""
    from db.models import KnowledgeBaseEntity
    from db.pgsql import set_user_context
    try:
        await set_user_context(db, current_user.id)
        result = await db.execute(
            select(KnowledgeBaseEntity).where(KnowledgeBaseEntity.id == kb_id)
        )
        kb = result.scalar_one_or_none()
        if not kb:
            raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")
        kb.isPinned = pinned
        await db.commit()
        return {"kb_id": kb_id, "is_pinned": pinned}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error toggling KB pin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to toggle pin")


@router.patch("/{kb_id}/last-accessed")
async def update_kb_last_accessed(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_write_db)
):
    """Update last accessed timestamp for a knowledge base."""
    from db.models import KnowledgeBaseEntity
    from db.pgsql import set_user_context
    from datetime import datetime
    try:
        await set_user_context(db, current_user.id)
        result = await db.execute(
            select(KnowledgeBaseEntity).where(KnowledgeBaseEntity.id == kb_id)
        )
        kb = result.scalar_one_or_none()
        if not kb:
            raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")
        kb.lastAccessedAt = datetime.utcnow()
        await db.commit()
        return {"message": "Last accessed updated"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating KB last accessed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update last accessed")


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    storage_connector: AzureStorageConnector = Depends(get_azure_storage_connector)
):
    """Permanently delete a knowledge base and all its data (blobs, documents, chunks)."""
    try:
        kb = await kb_service.get_knowledge_base(kb_id)
        if kb.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Only the owner can delete this knowledge base")
        
        await kb_service.delete_knowledge_base(
            kb_id=kb_id,
            storage_connector=storage_connector
        )
        
        return {"message": f"Knowledge base {kb_id} permanently deleted"}
    
    except KnowledgeBaseNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete knowledge base")


@router.post("/{kb_id}/search", response_model=ChunkSearchResponse)
async def search_knowledge_base(
    kb_id: str,
    request: ChunkSearchRequest,
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service)
):
    """Perform similarity search in knowledge base."""
    try:
        results = await kb_service.similarity_search(
            kb_id=kb_id,
            query_embedding=request.query_embedding,
            limit=request.limit,
            distance_threshold=request.distance_threshold,
            use_sphere=request.use_sphere
        )
        
        return ChunkSearchResponse(
            kb_id=kb_id,
            results=results,
            total=len(results)
        )
    
    except KnowledgeBaseNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error searching knowledge base: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to search knowledge base")


@router.get("/{kb_id}/documents/{document_id}/chunks")
async def get_document_chunks(
    kb_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service)
):
    """Get all chunks for a document."""
    try:
        chunks = await kb_service.get_document_chunks(kb_id, document_id)
        
        return {
            "kb_id": kb_id,
            "document_id": document_id,
            "chunks": [
                {
                    "chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_text": chunk.chunk_text,
                    "chunk_size": chunk.chunk_size,
                    "embedding_status": chunk.embedding_status,
                    "created_at": chunk.created_at.isoformat()
                }
                for chunk in chunks
            ],
            "total": len(chunks)
        }
    
    except KnowledgeBaseNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting document chunks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get document chunks")


@router.get("/{kb_id}/documents/{document_id}/chunks/search")
async def search_document_chunks(
    kb_id: str,
    document_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None, description="Keyword search within chunk text"),
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
):
    """Paginated chunk listing with optional keyword search."""
    try:
        kb = await kb_service.get_knowledge_base(kb_id)
        result = await kb_service.kb_repo.get_chunks_paginated(
            table_name=kb.chunk_table_name,
            document_id=document_id,
            page=page,
            page_size=page_size,
            search=q or None,
        )
        return result
    except KnowledgeBaseNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error searching chunks: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to search chunks")


@router.get("/{kb_id}/assets")
async def get_kb_assets(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base_service),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_write_db),
):
    """Return documents and structured tables for a KB, used by chat @ mentions."""
    try:
        kb = await kb_service.get_knowledge_base(kb_id)

        docs_raw = await document_service.list_kb_documents(kb_id=kb_id, include_deleted=False)
        documents = [
            {
                "id": d.id,
                "file_name": d.file_name,
                "file_type": d.file_type.value,
                "status": d.status.value,
                "chunk_count": d.chunk_count,
            }
            for d in docs_raw
        ]

        structured_tables = []
        try:
            from repositories.structured_data_repository import StructuredDataRepository
            repo = StructuredDataRepository(db)
            tables = await repo.get_tables_for_kb(kb_id)
            for t in tables:
                structured_tables.append({
                    "id": t.id,
                    "table_name": t.table_name,
                    "display_name": t.display_name or t.table_name,
                    "description": t.description or "",
                    "document_id": t.document_id,
                    "columns": [
                        {
                            "id": c.id,
                            "column_name": c.column_name,
                            "display_name": c.display_name or c.column_name,
                            "data_type": c.data_type.value if hasattr(c.data_type, "value") else c.data_type,
                            "description": c.description or "",
                        }
                        for c in (t.columns or [])
                    ],
                })
        except Exception as e:
            logger.warning("Could not load structured tables for KB %s: %s", kb_id, e)

        return {
            "kb_id": kb_id,
            "kb_name": kb.name,
            "documents": documents,
            "structured_tables": structured_tables,
        }
    except KnowledgeBaseNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error getting KB assets for %s: %s", kb_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get KB assets")


# ── Relationship CRUD ───────────────────────────────────────────────────

class RelationshipCreateRequest(BaseModel):
    source_table_id: str
    source_column_id: str
    target_table_id: str
    target_column_id: str
    relationship_type: str = "one_to_many"


@router.get("/{kb_id}/relationships")
async def list_relationships(
    kb_id: str,
    structured_service: StructuredDataService = Depends(get_structured_data_service),
    current_user: User = Depends(get_current_user),
):
    try:
        rels = await structured_service.structured_repo.get_relationships_for_kb(kb_id)
        return [r.to_dict() for r in rels]
    except Exception as e:
        logger.error("Error listing relationships for KB %s: %s", kb_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list relationships")


@router.post("/{kb_id}/relationships", status_code=201)
async def create_relationship(
    kb_id: str,
    body: RelationshipCreateRequest,
    structured_service: StructuredDataService = Depends(get_structured_data_service),
    db: AsyncSession = Depends(get_write_db),
    current_user: User = Depends(get_current_user),
):
    import uuid as _uuid
    from domain.entities.structured_data import StructuredRelationship, RelationshipType

    try:
        rel_type = RelationshipType(body.relationship_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid relationship_type: {body.relationship_type}. Must be one_to_one, one_to_many, or many_to_one.")

    rel = StructuredRelationship(
        id=str(_uuid.uuid4()),
        kb_id=kb_id,
        source_table_id=body.source_table_id,
        source_column_id=body.source_column_id,
        target_table_id=body.target_table_id,
        target_column_id=body.target_column_id,
        relationship_type=rel_type,
    )
    try:
        saved = await structured_service.structured_repo.save_relationship(rel)
        await db.commit()
        rels = await structured_service.structured_repo.get_relationships_for_kb(kb_id)
        matched = [r for r in rels if r.id == saved.id]
        return matched[0].to_dict() if matched else saved.to_dict()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error("Error creating relationship in KB %s: %s", kb_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create relationship")


@router.delete("/{kb_id}/relationships/{rel_id}", status_code=200)
async def delete_relationship(
    kb_id: str,
    rel_id: str,
    structured_service: StructuredDataService = Depends(get_structured_data_service),
    db: AsyncSession = Depends(get_write_db),
    current_user: User = Depends(get_current_user),
):
    try:
        deleted = await structured_service.structured_repo.delete_relationship(rel_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Relationship not found")
        await db.commit()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Error deleting relationship %s: %s", rel_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete relationship")


# ── Structured column description updates ────────────────────────────────

class ColumnDescriptionUpdateRequest(BaseModel):
    description: Optional[str] = None


@router.patch("/{kb_id}/structured-columns/{column_id}")
async def update_structured_column_description(
    kb_id: str,
    column_id: str,
    body: ColumnDescriptionUpdateRequest,
    structured_service: StructuredDataService = Depends(get_structured_data_service),
    db: AsyncSession = Depends(get_write_db),
    current_user: User = Depends(get_current_user),
):
    """Update the semantic description on a single structured-data column.

    The ``{kb_id}`` path segment double-checks that the caller owns the
    column -- we resolve the column's KB via its parent table and 404 if
    the two don't match (prevents users from patching columns in KBs
    that RLS would otherwise hide).
    """
    try:
        owning_kb = await structured_service.structured_repo.get_column_kb_id(column_id)
        if not owning_kb:
            raise HTTPException(status_code=404, detail="Column not found")
        if owning_kb != kb_id:
            raise HTTPException(
                status_code=404, detail="Column does not belong to this knowledge base"
            )

        # Confirm the caller can actually see this KB (RLS check).
        # get_by_id returns None when RLS hides the row.
        from repositories.knowledge_base_repository import KnowledgeBaseRepository
        kb_repo = KnowledgeBaseRepository(db)
        kb = await kb_repo.get_by_id(kb_id)
        if kb is None:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        desc = (body.description or "").strip() or None
        updated = await structured_service.structured_repo.update_column_description(
            column_id, desc
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Column not found")

        await db.commit()
        return updated.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            "Error updating column %s description in KB %s: %s",
            column_id, kb_id, e, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update column description")

