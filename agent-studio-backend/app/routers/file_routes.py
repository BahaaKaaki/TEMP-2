"""
File upload routes.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, Response
from typing import List, Dict, Any, Optional
import logging

from services import FileService
from core.dependencies import get_file_service, get_current_user
from db.models import User
from core.exceptions import (
    FileNotFoundException,
    SessionNotFoundException,
    DomainException,
    FileTooLargeException,
    ValidationException
)
from schemas import (
    FileUploadResponse,
    FileListResponse,
    FileDetailResponse
)
from config.settings import settings, get_max_file_size_bytes
from utils.rate_limit import rate_limit_file_upload

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["File Upload"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}}
)


@router.post(
    "/sessions/{session_id}/files",
    response_model=FileUploadResponse
)
@rate_limit_file_upload()
async def upload_file(
    request: Request,
    response: Response,
    session_id: str,
    file: UploadFile = File(...),
    message_id: Optional[str] = Form(None),
    uploaded_by: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """
    Upload a file to a chat session.
    
    Rate limit: 5 uploads per minute per IP address.
    """
    try:
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
        
        # Use uploaded_by from form if provided, otherwise use current_user.id
        uploader_id = uploaded_by if uploaded_by else current_user.id
        
        uploaded_file = await file_service.upload_file(
            session_id=session_id,
            file_name=file.filename,
            file_content=content,
            mime_type=file.content_type,
            message_id=message_id,
            uploaded_by=uploader_id
        )
        
        extracted_preview = None
        if uploaded_file.has_extracted_text():
            extracted_preview = uploaded_file.extracted_text[:500]
        
        return FileUploadResponse(
            file_id=uploaded_file.id,
            file_name=uploaded_file.file_name,
            file_type=uploaded_file.file_type,
            file_size=uploaded_file.file_size,
            parsing_status=uploaded_file.parsing_status,
            extracted_text_preview=extracted_preview,
            message=f"File '{file.filename}' uploaded successfully",
            scope=getattr(uploaded_file, "scope", None),
            uploaded_at_agent_id=getattr(uploaded_file, "uploaded_at_agent_id", None),
            uploaded_at_agent_label=getattr(uploaded_file, "uploaded_at_agent_label", None),
        )
    
    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationException as e:
        # Return 413 for size-related validation errors
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
        logger.error("Error uploading file: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to upload file")


@router.get(
    "/sessions/{session_id}/files",
    response_model=FileListResponse
)
async def list_session_files(
    session_id: str,
    include_deleted: bool = False,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """List all files in a session."""
    try:
        files = await file_service.list_session_files(
            session_id=session_id,
            include_deleted=include_deleted
        )
        
        return FileListResponse(
            files=[
                {
                    "id": f.id,
                    "file_name": f.file_name,
                    "file_type": f.file_type,
                    "file_size": f.file_size,
                    "parsing_status": f.parsing_status,
                    "created_at": f.created_at.isoformat(),
                    "scope": getattr(f, "scope", None),
                    "uploaded_at_agent_id": getattr(f, "uploaded_at_agent_id", None),
                    "uploaded_at_agent_label": getattr(f, "uploaded_at_agent_label", None),
                }
                for f in files
            ],
            total=len(files)
        )
    
    except Exception as e:
        logger.error("Error listing files: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list files")


@router.get(
    "/files/{file_id}",
    response_model=FileDetailResponse
)
async def get_file_details(
    file_id: str,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """Get detailed file information."""
    try:
        f = await file_service.get_file(file_id)
        
        return FileDetailResponse(
            id=f.id,
            session_id=f.session_id,
            file_name=f.file_name,
            file_type=f.file_type,
            file_size=f.file_size,
            mime_type=f.mime_type,
            parsing_status=f.parsing_status,
            parsing_error=f.parsing_error,
            extracted_text=f.extracted_text,
            created_at=f.created_at,
            uploaded_by=f.uploaded_by,
            scope=getattr(f, "scope", None),
            uploaded_at_agent_id=getattr(f, "uploaded_at_agent_id", None),
            uploaded_at_agent_label=getattr(f, "uploaded_at_agent_label", None),
        )
    
    except FileNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error getting file: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get file")


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    permanent: bool = False,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """Delete a file."""
    try:
        await file_service.delete_file(
            file_id=file_id,
            permanent=permanent
        )
        
        return {"message": f"File {file_id} deleted successfully"}
    
    except FileNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error deleting file: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete file")

