"""
Citation API routes.

Provides endpoints to fetch citation details on-demand.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
import logging
from typing import Optional

from core.dependencies import get_current_user, get_azure_storage_connector
from db.pgsql import get_admin_db
from db.models import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/citations",
    tags=["Citations"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


@router.get("/{chunk_id}")
async def get_citation_details(
    chunk_id: str,
    kb_id: Optional[str] = None,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get full citation details for a specific chunk.
    
    This is called when user hovers over or clicks a citation marker [N].
    Returns all metadata needed for tooltip and modal display.
    
    Uses get_admin_db to bypass RLS - citations from public KBs should be
    accessible to all users who can use the shared workflow.
    """
    try:
        kb_name = None
        table_name = None
        
        if kb_id:
            # Fetch KB using raw SQL to bypass RLS
            # Allow access if: user owns the KB OR KB is public
            kb_result = await db.execute(
                text("""
                    SELECT id, name, "chunkTableName", "createdBy", "isPublic"
                    FROM knowledge_base
                    WHERE id = :kb_id
                      AND ("createdBy" = :user_id OR "isPublic" = true)
                """),
                {"kb_id": kb_id, "user_id": current_user.id}
            )
            kb_row = kb_result.fetchone()
            
            if not kb_row:
                raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found or access denied")
            
            kb_name = kb_row[1]
            table_name = kb_row[2]
            
            # Fetch chunk data from the chunk table
            query = text(f"""
                SELECT id, kb_id, document_id, chunk_index, chunk_text, 
                       chunk_size, metadata, created_at
                FROM {table_name}
                WHERE id = :chunk_id
                LIMIT 1
            """)
            result = await db.execute(query, {"chunk_id": chunk_id})
            chunk_data = result.fetchone()
            
            if not chunk_data:
                raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")
        else:
            # No kb_id provided - need to search across accessible KBs
            # Get all KBs the user can access (owned or public)
            kbs_result = await db.execute(
                text("""
                    SELECT id, name, "chunkTableName"
                    FROM knowledge_base
                    WHERE "createdBy" = :user_id OR "isPublic" = true
                """),
                {"user_id": current_user.id}
            )
            all_kbs = kbs_result.fetchall()
            
            chunk_data = None
            
            for kb in all_kbs:
                try:
                    kb_table = kb[2]  # chunkTableName
                    query = text(f"""
                        SELECT id, kb_id, document_id, chunk_index, chunk_text, 
                               chunk_size, metadata, created_at
                        FROM {kb_table}
                        WHERE id = :chunk_id
                        LIMIT 1
                    """)
                    result = await db.execute(query, {"chunk_id": chunk_id})
                    row = result.fetchone()
                    
                    if row:
                        chunk_data = row
                        kb_id = kb[0]
                        kb_name = kb[1]
                        table_name = kb_table
                        break
                except Exception as e:
                    logger.debug(f"Chunk not in {kb[2]}: {e}")
                    continue
            
            if not chunk_data:
                raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")
        
        # Extract chunk info
        document_id = chunk_data[2]
        chunk_index = chunk_data[3]
        chunk_text = chunk_data[4]
        chunk_size = chunk_data[5]
        created_at = chunk_data[7]
        
        # Fetch document metadata using raw SQL
        doc_result = await db.execute(
            text("""
                SELECT id, "fileName", "fileType", "fileSize", "mimeType", 
                       "createdAt", "blobName"
                FROM rag_document
                WHERE id = :doc_id
            """),
            {"doc_id": document_id}
        )
        doc_row = doc_result.fetchone()
        
        if not doc_row:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        
        # Build full citation response
        return {
            "chunk_id": chunk_id,
            "kb_id": kb_id,
            "document_id": document_id,
            "document_name": doc_row[1],  # file_name
            "document_file_type": doc_row[2],  # file_type
            "chunk_index": chunk_index,
            "chunk_text": chunk_text,
            "chunk_size": chunk_size,
            "file_size_bytes": doc_row[3],  # file_size
            "mime_type": doc_row[4],  # mime_type
            "uploaded_at": doc_row[5].isoformat() if doc_row[5] else None,  # created_at
            "blob_name": doc_row[6],  # blob_name
            "kb_name": kb_name
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching citation {chunk_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch citation details")


@router.get("/{chunk_id}/page-image")
async def get_citation_page_image(
    chunk_id: str,
    kb_id: Optional[str] = None,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_user),
    storage=Depends(get_azure_storage_connector),
):
    """
    Stream the source page snapshot (PNG) for a citation's chunk.

    Resolves the chunk's document_id + page_number, derives the deterministic
    page-image blob path, and streams the PNG. Returns 404 when no snapshot
    exists (e.g. recursive-chunked or non-PDF documents).

    Uses get_admin_db to bypass RLS so citations from public KBs are accessible
    to anyone who can use the shared workflow (mirrors get_citation_details).
    """
    try:
        # Resolve the chunk row (document_id + metadata) honoring KB access.
        chunk = None
        if kb_id:
            kb_row = (await db.execute(
                text("""
                    SELECT "chunkTableName" FROM knowledge_base
                    WHERE id = :kb_id AND ("createdBy" = :uid OR "isPublic" = true)
                """),
                {"kb_id": kb_id, "uid": current_user.id},
            )).fetchone()
            if not kb_row:
                raise HTTPException(status_code=404, detail="Knowledge base not found or access denied")
            chunk = (await db.execute(
                text(f"SELECT document_id, metadata FROM {kb_row[0]} WHERE id = :cid LIMIT 1"),
                {"cid": chunk_id},
            )).fetchone()
        else:
            kbs = (await db.execute(
                text("""
                    SELECT "chunkTableName" FROM knowledge_base
                    WHERE "createdBy" = :uid OR "isPublic" = true
                """),
                {"uid": current_user.id},
            )).fetchall()
            for (tbl,) in kbs:
                try:
                    row = (await db.execute(
                        text(f"SELECT document_id, metadata FROM {tbl} WHERE id = :cid LIMIT 1"),
                        {"cid": chunk_id},
                    )).fetchone()
                    if row:
                        chunk = row
                        break
                except Exception:
                    continue

        if not chunk:
            raise HTTPException(status_code=404, detail="Chunk not found")

        document_id = chunk[0]
        metadata = chunk[1]
        if isinstance(metadata, str):
            import json as _json
            try:
                metadata = _json.loads(metadata)
            except (ValueError, TypeError):
                metadata = None
        page_number = metadata.get("page_number") if isinstance(metadata, dict) else None
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            raise HTTPException(status_code=404, detail="No page snapshot for this citation")

        doc_row = (await db.execute(
            text('SELECT "blobName" FROM rag_document WHERE id = :doc_id'),
            {"doc_id": document_id},
        )).fetchone()
        if not doc_row or not doc_row[0]:
            raise HTTPException(status_code=404, detail="Document not found")

        base_path = doc_row[0].rsplit("/", 1)[0]
        page_blob = f"{base_path}/{document_id}/pages/{page_number:04d}.png"

        # Quiet existence check first: a missing snapshot is the common case
        # (documents uploaded before this feature, or recursive-chunked). This
        # avoids the download_blob 3-retry + ERROR-log storm that BlobNotFound
        # would otherwise trigger; blob_exists() is a single quiet HEAD.
        if not await storage.blob_exists(page_blob):
            raise HTTPException(status_code=404, detail="No page snapshot for this citation")
        try:
            data = await storage.download_blob(page_blob)
        except Exception:
            raise HTTPException(status_code=404, detail="Page snapshot not available")
        if not data:
            raise HTTPException(status_code=404, detail="Page snapshot not available")

        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching page image for chunk {chunk_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch page image")


@router.get("/batch")
async def get_citations_batch(
    chunk_ids: str,  # Comma-separated chunk IDs
    kb_id: Optional[str] = None,
    db: AsyncSession = Depends(get_admin_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get citation details for multiple chunks at once.
    More efficient than making multiple requests.
    
    Usage: GET /api/citations/batch?chunk_ids=id1,id2,id3&kb_id=...
    """
    try:
        ids = [id.strip() for id in chunk_ids.split(',') if id.strip()]
        
        if not ids:
            return []
        
        # Fetch all citations
        citations = []
        for chunk_id in ids:
            try:
                # Reuse single citation endpoint logic
                citation = await get_citation_details(chunk_id, kb_id, db, current_user)
                citations.append(citation)
            except HTTPException as e:
                logger.warning(f"Citation {chunk_id} not found: {e.detail}")
                # Skip missing citations rather than failing entire batch
                continue
        
        return citations
    
    except Exception as e:
        logger.error(f"Error fetching batch citations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch citation batch")

