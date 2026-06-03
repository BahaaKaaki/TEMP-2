"""
PowerPoint generation API routes.

Endpoints for the three-phase PowerPoint generation workflow:
  1. Horizontal Logic - generate/update storyline
  2. Vertical Logic   - generate slide content (parallel)
  3. Modify/Export    - modify individual slides, export to .pptx
"""
import io
import logging
import unicodedata
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Any, Dict, List

from core.dependencies import get_current_user
from db.models import User
from services.powerpoint_schema import (
    HorizontalLogicRequest,
    HorizontalLogicResponse,
    VerticalLogicRequest,
    SlideGenerationResponse,
    ModifySlideRequest,
    ExportRequest,
    GenerateSingleSlideRequest,
    HorizontalLogic,
    Slide,
    Presentation,
    SlideTheme,
)
from services.powerpoint_service import (
    generate_horizontal_logic,
    generate_vertical_logic,
    generate_single_slide,
    modify_slide,
    build_presentation,
)
from services.powerpoint_builder import build_pptx
from utils.errors import safe_error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/pptx",
    tags=["PowerPoint"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)


# =============================================================================
# PHASE 1: HORIZONTAL LOGIC
# =============================================================================

@router.post("/horizontal-logic", response_model=HorizontalLogicResponse)
async def create_horizontal_logic(
    request: HorizontalLogicRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Generate the horizontal logic (storyline) from deliverable data.
    
    The LLM analyzes the deliverable output and creates slide titles
    that tell a complete story when read in sequence.
    """
    try:
        horizontal_logic = await generate_horizontal_logic(
            deliverable_data=request.deliverable_data,
            num_slides=request.num_slides,
            user_context=request.context,
        )
        
        return HorizontalLogicResponse(
            horizontal_logic=horizontal_logic,
            message=f"Generated storyline with {len(horizontal_logic.slides)} slides",
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to generate storyline"),
        )


@router.put("/horizontal-logic", response_model=HorizontalLogicResponse)
async def update_horizontal_logic(
    horizontal_logic: HorizontalLogic,
    current_user: User = Depends(get_current_user),
):
    """
    Update horizontal logic after user edits (reorder, rename, add/remove slides).
    
    This endpoint validates the user-edited storyline and returns it.
    No LLM call needed - just validation.
    """
    try:
        return HorizontalLogicResponse(
            horizontal_logic=horizontal_logic,
            message=f"Storyline updated: {len(horizontal_logic.slides)} slides",
        )
    except Exception as e:
        logger.error("Error updating horizontal logic: %s", e, exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid storyline data: {str(e)}",
        )


# =============================================================================
# PHASE 2: VERTICAL LOGIC
# =============================================================================

@router.post("/vertical-logic")
async def create_vertical_logic(
    request: VerticalLogicRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Generate content for all slides in parallel.
    
    Takes the approved horizontal logic and deliverable data,
    generates full content for each slide concurrently.
    """
    try:
        slides = await generate_vertical_logic(
            deliverable_data=request.deliverable_data,
            horizontal_logic=request.horizontal_logic,
            user_context=request.context,
        )
        
        return {
            "slides": [s.model_dump() for s in slides],
            "total": len(slides),
            "message": f"Generated content for {len(slides)} slides",
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to generate slide content"),
        )


@router.post("/generate-slide", response_model=SlideGenerationResponse)
async def create_single_slide(
    request: GenerateSingleSlideRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Generate or regenerate a single slide.
    """
    try:
        slide = await generate_single_slide(
            deliverable_data=request.deliverable_data,
            headline=request.headline,
            subtitle=request.subtitle,
            layout=request.layout.value,
            user_context=request.context,
        )
        
        return SlideGenerationResponse(
            slide=slide,
            message="Slide generated successfully",
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to generate slide"),
        )


# =============================================================================
# PHASE 3: MODIFICATION & EXPORT
# =============================================================================

@router.post("/modify-slide", response_model=SlideGenerationResponse)
async def modify_existing_slide(
    request: ModifySlideRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Modify an existing slide based on a user chat instruction.
    """
    try:
        slide = await modify_slide(
            current_slide=request.slide.model_dump(),
            instruction=request.instruction,
            deliverable_data=request.deliverable_data,
        )
        
        return SlideGenerationResponse(
            slide=slide,
            message="Slide modified successfully",
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to modify slide"),
        )


@router.post("/export")
async def export_presentation(
    request: ExportRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Export the presentation to a .pptx file.
    
    Returns the file as a downloadable binary stream.
    """
    try:
        pptx_bytes = build_pptx(request.presentation)
        
        title_slug = request.presentation.title.replace(" ", "_")[:40]
        filename = f"Strategy_and_{title_slug}.pptx"
        ascii_slug = (
            unicodedata.normalize("NFKD", title_slug)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        filename_ascii = f"Strategy_and_{ascii_slug}.pptx"
        
        return StreamingResponse(
            io.BytesIO(pptx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename_ascii}"; '
                    f"filename*=UTF-8''{urllib.parse.quote(filename)}"
                ),
                "Content-Length": str(len(pptx_bytes)),
            },
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_error_detail(e, "Failed to export presentation"),
        )
