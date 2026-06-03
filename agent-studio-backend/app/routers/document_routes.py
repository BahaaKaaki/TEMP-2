"""
Document management routes for RAG capabilities.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response, Query, Request
from fastapi.responses import StreamingResponse
from typing import List, Optional
import logging
import json as _json
from io import BytesIO

from services.document_service import DocumentService, DocumentNotFoundException, DuplicateDocumentException
from core.dependencies import (
    get_document_service,
    get_current_user,
    get_structured_data_service,
    get_db_with_user_context,
)
from db.pgsql import get_write_db
from db.models import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.exceptions import (
    SessionNotFoundException,
    DomainException,
    FileTooLargeException,
    ValidationException
)
from schemas import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentDetailResponse,
    DocumentDownloadUrlResponse
)
from config.settings import settings, get_max_file_size_bytes
from utils.rate_limit import rate_limit_kb_upload
from utils.errors import safe_error_detail

STRUCTURED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/documents",
    tags=["Documents"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


async def _check_kb_write_access(kb_id: str, user_id: str, db: AsyncSession):
    """
    Verify the user may mutate a knowledge base (owner or write share).
    Read-only / public viewers receive 403.
    """
    from services.sharing_access import can_write, resolve_kb_share_access

    result = await db.execute(
        text('SELECT "createdBy", "isPublic" FROM knowledge_base WHERE id = :kb_id'),
        {"kb_id": kb_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")

    created_by = row[0]
    is_public = row[1]

    access = await resolve_kb_share_access(
        db, kb_id, user_id, owner_id=created_by
    )
    if can_write(access):
        return

    if created_by != user_id:
        if is_public or access == "read":
            raise HTTPException(
                status_code=403,
                detail="You have read-only access to this knowledge base",
            )
        raise HTTPException(status_code=403, detail="Access denied")


@router.post(
    "/knowledge-bases/{kb_id}/upload",
)
@rate_limit_kb_upload()
async def upload_document_to_kb(
    request: Request,
    response: Response,
    kb_id: str,
    file: UploadFile = File(...),
    chunking_method: Optional[str] = Form(None),
    chunk_size: Optional[int] = Form(None),
    chunk_overlap: Optional[int] = Form(None),
    separators: Optional[str] = Form(None),
    delimiter: Optional[str] = Form(None),
    metadata_fields: Optional[str] = Form(None),
    vision_prompt: Optional[str] = Form(None),
    vision_model: Optional[str] = Form(None),
    vision_output_schema: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """
    Upload a document to a knowledge base for RAG processing.
    Requires owner or write share on the KB.
    
    Rate limit: 3 uploads per minute per IP address.
    """
    try:
        # Check KB ownership - only owners can upload
        await _check_kb_write_access(kb_id, current_user.id, db)
        # Validate file name exists
        if not file.filename:
            raise ValidationException("File name is required", field="file")
        
        # Read file content
        content = await file.read()
        
        # Validate file size
        file_size_bytes = len(content)
        max_size_bytes = get_max_file_size_bytes()
        
        if file_size_bytes > max_size_bytes:
            size_mb = file_size_bytes / (1024 * 1024)
            raise FileTooLargeException(
                file_name=file.filename,
                size_mb=size_mb,
                max_mb=settings.MAX_FILE_SIZE_MB
            )
        
        # Detect structured file types (CSV/Excel)
        file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        is_structured = file_ext in STRUCTURED_EXTENSIONS

        # Build per-document chunking overrides (ignored for structured files)
        chunking_overrides = None
        if not is_structured and chunking_method:
            parsed_seps = None
            if separators:
                try:
                    parsed_seps = _json.loads(separators)
                except (ValueError, TypeError):
                    parsed_seps = None
            chunking_overrides = {
                "method": chunking_method,
                "chunk_size": chunk_size or 1000,
                "chunk_overlap": chunk_overlap or 0,
                "separators": parsed_seps,
                "delimiter": delimiter if chunking_method == "delimiter" else None,
            }

        # Parse per-document metadata field definitions (JSON array)
        parsed_metadata_fields = None
        if not is_structured and metadata_fields:
            try:
                parsed_metadata_fields = _json.loads(metadata_fields)
                if not isinstance(parsed_metadata_fields, list):
                    parsed_metadata_fields = None
            except (ValueError, TypeError):
                parsed_metadata_fields = None

        # Build vision processing config when chunking_method is "vision"
        vision_config = None
        is_vision = chunking_method == "vision"
        if is_vision:
            if not vision_prompt:
                raise ValidationException(
                    "vision_prompt is required when chunking_method is 'vision'",
                    field="vision_prompt",
                )
            vision_exts = {"pdf", "pptx", "docx", "doc"}
            if file_ext not in vision_exts:
                raise ValidationException(
                    f"Vision processing only supports {', '.join(sorted(vision_exts))} files",
                    field="file",
                )

            parsed_vision_schema = None
            if vision_output_schema:
                try:
                    parsed_vision_schema = _json.loads(vision_output_schema)
                    if not isinstance(parsed_vision_schema, list):
                        parsed_vision_schema = None
                except (ValueError, TypeError):
                    parsed_vision_schema = None

            vision_config = {
                "prompt": vision_prompt,
                "model": vision_model or "vertex_ai.gemini-2.5-flash",
                "output_schema": parsed_vision_schema,
            }
            chunking_overrides = {"method": "vision"}

        document = await document_service.upload_document(
            kb_id=kb_id,
            file_name=file.filename,
            file_content=content,
            mime_type=file.content_type,
            uploaded_by=current_user.id,
            skip_processing=is_structured,
            chunking_overrides=chunking_overrides,
            metadata_fields=parsed_metadata_fields,
            vision_config=vision_config,
        )
        
        response_data = {
            "document_id": document.id,
            "file_name": document.file_name,
            "file_type": document.file_type.value,
            "file_size": document.file_size,
            "status": document.status.value,
            "blob_url": document.blob_url,
            "message": f"Document '{file.filename}' uploaded successfully",
            "requires_schema_review": is_structured,
        }

        if is_structured:
            from services.structured_data_service import StructuredDataService
            from repositories.structured_data_repository import StructuredDataRepository
            from sqlalchemy import text as sa_text
            from db.pgsql import set_user_context
            await set_user_context(db, current_user.id)
            result = await db.execute(
                sa_text('UPDATE rag_document SET status = :status, "updatedAt" = NOW() WHERE id = :doc_id'),
                {"status": "schema_review", "doc_id": document.id},
            )
            await db.commit()
            logger.debug("Upload: set status=schema_review for %s, rows=%s", document.id, result.rowcount)
            structured_repo = StructuredDataRepository(db)
            structured_service = StructuredDataService(db, structured_repo)
            schema_preview = await structured_service.preview_schema(content, file.filename)
            existing_names = list(await structured_repo.get_table_names_for_kb(kb_id))
            schema_preview["existing_table_names"] = existing_names
            response_data["schema_preview"] = schema_preview
            response_data["status"] = "schema_review"
            response_data["message"] = f"Structured file '{file.filename}' uploaded. Review schema before loading."

        return response_data
    
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DuplicateDocumentException as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": str(e),
                "error_code": "DUPLICATE_DOCUMENT",
                "file_name": e.file_name,
            }
        )
    except ValidationException as e:
        if isinstance(e, FileTooLargeException):
            raise HTTPException(
                status_code=413,
                detail={
                    "error": str(e),
                    "error_code": "FILE_TOO_LARGE",
                    "file_name": e.file_name,
                    "size_mb": round(e.size_mb, 2),
                    "max_size_mb": e.max_mb
                }
            )
        raise HTTPException(status_code=400, detail=str(e))
    except DomainException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error uploading document: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to upload document")


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentListResponse
)
async def list_kb_documents(
    kb_id: str,
    include_deleted: bool = False,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """List all documents in a knowledge base."""
    try:
        documents = await document_service.list_kb_documents(
            kb_id=kb_id,
            include_deleted=include_deleted
        )
        
        # Check which documents have structured tables
        structured_doc_ids = set()
        try:
            from repositories.structured_data_repository import StructuredDataRepository
            structured_repo = StructuredDataRepository(document_service.db)
            for doc in documents:
                doc_ext = doc.file_name.rsplit('.', 1)[-1].lower() if '.' in doc.file_name else ''
                if doc_ext in STRUCTURED_EXTENSIONS:
                    structured_doc_ids.add(doc.id)
        except Exception:
            pass

        return DocumentListResponse(
            documents=[
                {
                    "id": doc.id,
                    "file_name": doc.file_name,
                    "file_type": doc.file_type.value,
                    "file_size": doc.file_size,
                    "status": doc.status.value,
                    "blob_url": doc.blob_url,
                    "chunk_count": doc.chunk_count,
                    "embedding_status": doc.embedding_status,
                    "created_at": doc.created_at.isoformat(),
                    "is_structured": doc.id in structured_doc_ids,
                }
                for doc in documents
            ],
            total=len(documents)
        )
    
    except Exception as e:
        logger.error("Error listing documents: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list documents")


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse
)
async def get_document_details(
    document_id: str,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Get detailed document information."""
    try:
        doc = await document_service.get_document(document_id)
        
        return DocumentDetailResponse(
            id=doc.id,
            session_id=doc.session_id,
            blob_name=doc.blob_name,
            file_name=doc.file_name,
            file_type=doc.file_type.value,
            file_size=doc.file_size,
            mime_type=doc.mime_type,
            status=doc.status.value,
            container_name=doc.container_name,
            blob_url=doc.blob_url,
            metadata=doc.metadata,
            extracted_text=doc.extracted_text,
            chunk_count=doc.chunk_count,
            embedding_status=doc.embedding_status,
            processing_error=doc.processing_error,
            uploaded_by=doc.uploaded_by,
            created_at=doc.created_at,
            updated_at=doc.updated_at
        )
    
    except DocumentNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error getting document: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get document")


@router.get(
    "/{document_id}/download",
    response_class=StreamingResponse
)
async def download_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Download document content from Azure Blob Storage."""
    try:
        doc = await document_service.get_document(document_id)
        content = await document_service.download_document(document_id)
        
        return StreamingResponse(
            BytesIO(content),
            media_type=doc.mime_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{doc.file_name}"'
            }
        )
    
    except DocumentNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error downloading document: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to download document")


@router.get(
    "/{document_id}/download-url",
    response_model=DocumentDownloadUrlResponse
)
async def get_download_url(
    document_id: str,
    expiry_hours: int = 24,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Generate a temporary download URL for document."""
    try:
        sas_url = await document_service.generate_download_url(
            document_id=document_id,
            expiry_hours=expiry_hours
        )
        
        return DocumentDownloadUrlResponse(
            document_id=document_id,
            download_url=sas_url,
            expiry_hours=expiry_hours
        )
    
    except DocumentNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error generating download URL: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate download URL")


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db_with_user_context)
):
    """Permanently delete a document: blob, chunks, and metadata. Only KB owner can delete."""
    try:
        doc_result = await db.execute(
            text('SELECT "kbId" FROM rag_document WHERE id = :doc_id'),
            {"doc_id": document_id}
        )
        doc_row = doc_result.fetchone()
        if doc_row:
            await _check_kb_write_access(doc_row[0], current_user.id, db)
        
        from repositories.structured_data_repository import StructuredDataRepository
        structured_repo = StructuredDataRepository(db)
        await structured_repo.drop_tables_for_document(document_id)
        
        await document_service.delete_document(document_id=document_id)
        
        if doc_row:
            remaining = await structured_repo.get_table_names_for_kb(doc_row[0])
            if not remaining:
                await structured_repo.update_kb_structured_flag(doc_row[0], False)
                await db.commit()

        return {"message": f"Document {document_id} permanently deleted"}
    
    except DocumentNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting document: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete document")


@router.get("/sessions/{session_id}/count")
async def count_session_documents(
    session_id: str,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Count documents in a session."""
    try:
        count = await document_service.count_session_documents(session_id)
        return {"session_id": session_id, "document_count": count}
    
    except Exception as e:
        logger.error("Error counting documents: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to count documents")


@router.get("/pending")
async def get_pending_documents(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Get pending documents for processing (admin endpoint)."""
    try:
        documents = await document_service.get_pending_documents(limit)
        
        return {
            "documents": [
                {
                    "id": doc.id,
                    "file_name": doc.file_name,
                    "status": doc.status.value,
                    "created_at": doc.created_at.isoformat()
                }
                for doc in documents
            ],
            "total": len(documents)
        }
    
    except Exception as e:
        logger.error("Error getting pending documents: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get pending documents")


@router.post("/{document_id}/confirm-schema")
async def confirm_structured_schema(
    document_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """
    Confirm the schema for a structured (CSV/Excel) document and load data into PG tables.
    Called after the user reviews and edits column types/descriptions in the schema editor.
    """
    try:
        body = await request.json()
        confirmed_tables = body.get("tables", [])
        if not confirmed_tables:
            raise HTTPException(status_code=400, detail="No tables provided")

        doc = await document_service.get_document(document_id)

        # Check KB ownership
        await _check_kb_write_access(doc.kb_id, current_user.id, db)

        # Download file content from blob storage
        content = await document_service.download_document(document_id)

        from services.structured_data_service import StructuredDataService
        from repositories.structured_data_repository import StructuredDataRepository
        structured_repo = StructuredDataRepository(db)
        structured_service = StructuredDataService(db, structured_repo)

        tables, data_warnings = await structured_service.confirm_and_load(
            kb_id=doc.kb_id,
            document_id=document_id,
            file_content=content,
            file_name=doc.file_name,
            confirmed_tables=confirmed_tables,
            created_by=current_user.id,
        )

        from sqlalchemy import text as sa_text
        from db.pgsql import set_user_context
        await set_user_context(db, current_user.id)
        result = await db.execute(
            sa_text('UPDATE rag_document SET status = :status, "updatedAt" = NOW() WHERE id = :doc_id'),
            {"status": "completed", "doc_id": document_id},
        )
        logger.debug("Confirm: status=completed for %s, rows=%s", document_id, result.rowcount)
        await db.execute(
            sa_text("""
                UPDATE knowledge_base
                SET "documentCount" = "documentCount" + :dc,
                    "totalSizeBytes" = "totalSizeBytes" + :sz
                WHERE id = :kb_id
            """),
            {"dc": 1, "sz": doc.file_size or 0, "kb_id": doc.kb_id},
        )
        await db.commit()

        return {
            "document_id": document_id,
            "status": "completed",
            "tables": [t.to_dict() for t in tables],
            "message": f"Successfully loaded {len(tables)} table(s) with structured data",
            "warnings": data_warnings,
        }

    except DocumentNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to confirm schema"),
        )


@router.get("/{document_id}/structured-preview")
async def get_structured_preview(
    document_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sheet: Optional[str] = Query(None, description="Specific table ID for multi-sheet Excel"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_user_context),
):
    """
    Get a paginated preview of structured data for a document.
    For Excel files with multiple sheets, use the sheet parameter to select a specific table.
    """
    try:
        from services.structured_data_service import StructuredDataService
        from repositories.structured_data_repository import StructuredDataRepository
        structured_repo = StructuredDataRepository(db)
        structured_service = StructuredDataService(db, structured_repo)

        preview = await structured_service.get_table_preview(
            document_id=document_id,
            page=page,
            page_size=page_size,
            sheet_table_id=sheet,
        )
        return preview

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to get preview"),
        )


@router.get("/knowledge-bases/{kb_id}/documents/{document_id}/chunks")
async def get_document_chunks(
    kb_id: str,
    document_id: str,
    include_embeddings: bool = Query(False, description="Include vector embeddings"),
    limit: int = Query(100, ge=1, le=1000, description="Max chunks to return"),
    current_user: User = Depends(get_current_user)
):
    """Get all chunks for a document, optionally with embeddings (vectors)."""
    try:
        from core.dependencies import get_knowledge_base_service, get_current_user
        from db.pgsql import get_static_read_db
        from sqlalchemy import text
        
        async for db in get_static_read_db():
            # Get KB to find chunk table
            kb_query = text("SELECT chunk_table_name FROM knowledge_base WHERE id = :kb_id")
            kb_result = await db.execute(kb_query, {"kb_id": kb_id})
            kb_row = kb_result.first()
            
            if not kb_row:
                raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")
            
            chunk_table = kb_row[0]
            
            # Query chunks
            if include_embeddings:
                chunk_query = text(f"""
                    SELECT id, document_id, chunk_index, chunk_text, chunk_size, 
                           metadata, created_at, embedding
                    FROM {chunk_table}
                    WHERE document_id = :document_id
                    ORDER BY chunk_index
                    LIMIT :limit
                """)
            else:
                chunk_query = text(f"""
                    SELECT id, document_id, chunk_index, chunk_text, chunk_size, 
                           metadata, created_at
                    FROM {chunk_table}
                    WHERE document_id = :document_id
                    ORDER BY chunk_index
                    LIMIT :limit
                """)
            
            result = await db.execute(chunk_query, {"document_id": document_id, "limit": limit})
            rows = result.all()
            
            chunks = []
            for row in rows:
                chunk_data = {
                    "chunk_id": str(row[0]),
                    "document_id": str(row[1]),
                    "chunk_index": row[2],
                    "chunk_text": row[3][:200] + "..." if len(row[3]) > 200 else row[3],  # Preview
                    "chunk_text_full": row[3],
                    "chunk_size": row[4],
                    "metadata": row[5],
                    "created_at": row[6].isoformat() if row[6] else None,
                }
                
                if include_embeddings and len(row) > 7 and row[7]:
                    chunk_data["embedding"] = list(row[7])  # Convert to list
                    chunk_data["embedding_dimension"] = len(row[7])
                
                chunks.append(chunk_data)
            
            return {
                "kb_id": kb_id,
                "document_id": document_id,
                "chunk_table": chunk_table,
                "total_chunks": len(chunks),
                "chunks": chunks
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to get chunks"),
        )

