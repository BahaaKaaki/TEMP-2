"""
Template engine API routes.

Endpoints for managing PPTX templates used by workflow agent nodes:
  - Upload a template and auto-extract placeholders / generate schema
  - Retrieve template metadata and schema
  - Fill a template with structured deliverable data (returns PPTX)
  - Delete a template
"""
from __future__ import annotations

import io
import logging
import unicodedata
import urllib.parse
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.dependencies import get_current_user, get_template_service
from db.models import User
from services.template_service import TemplateService
from utils.errors import safe_error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/templates",
    tags=["Templates"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


class FillRequest(BaseModel):
    data: Dict[str, Any]


# =========================================================================
# Upload
# =========================================================================

@router.post("/upload")
async def upload_template(
    file: UploadFile = File(...),
    workflow_id: str = Form(...),
    agent_node_id: str = Form(...),
    template_name: str = Form(None),
    current_user: User = Depends(get_current_user),
    svc: TemplateService = Depends(get_template_service),
):
    """Upload a PPTX template, extract placeholders, generate JSON Schema."""
    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(
            status_code=400,
            detail="Only .pptx files are accepted.",
        )

    try:
        file_bytes = await file.read()
        result = await svc.upload_template(
            workflow_id=workflow_id,
            agent_node_id=agent_node_id,
            file_name=file.filename,
            file_bytes=file_bytes,
            user_id=current_user.id,
            template_name=template_name,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Template upload failed"),
        )


# =========================================================================
# Read
# =========================================================================

@router.get("/{template_id}")
async def get_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    svc: TemplateService = Depends(get_template_service),
):
    """Get template metadata including placeholders and schema."""
    result = await svc.get_template(template_id)
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@router.get("/{template_id}/schema")
async def get_template_schema(
    template_id: str,
    current_user: User = Depends(get_current_user),
    svc: TemplateService = Depends(get_template_service),
):
    """Get only the generated JSON Schema for a template."""
    schema = await svc.get_template_schema(template_id)
    if schema is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return schema


@router.get("/workflow/{workflow_id}")
async def list_templates_for_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    svc: TemplateService = Depends(get_template_service),
):
    """List all templates belonging to a workflow."""
    return await svc.list_templates(workflow_id)


# =========================================================================
# Fill (export)
# =========================================================================

@router.post("/{template_id}/fill")
async def fill_template(
    template_id: str,
    body: FillRequest,
    current_user: User = Depends(get_current_user),
    svc: TemplateService = Depends(get_template_service),
):
    """Fill a template with structured data and return the PPTX file."""
    tpl = await svc.get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        pptx_bytes = await svc.fill(template_id, body.data)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Template fill failed"),
        )

    if pptx_bytes is None:
        raise HTTPException(status_code=404, detail="Template blob not found")

    title_slug = (tpl.get("name") or "Template").replace(" ", "_")[:40]
    filename = f"{title_slug}.pptx"
    ascii_slug = (
        unicodedata.normalize("NFKD", title_slug)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    filename_ascii = f"{ascii_slug}.pptx"

    return StreamingResponse(
        io.BytesIO(pptx_bytes),
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".presentationml.presentation"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename_ascii}"; '
                f"filename*=UTF-8''{urllib.parse.quote(filename)}"
            ),
            "Content-Length": str(len(pptx_bytes)),
        },
    )


# =========================================================================
# Delete
# =========================================================================

@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    svc: TemplateService = Depends(get_template_service),
):
    """Delete a template and its blob."""
    deleted = await svc.delete_template(template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}
