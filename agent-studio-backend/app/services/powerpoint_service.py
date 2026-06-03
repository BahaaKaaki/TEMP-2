"""
PowerPoint Generation Service

Orchestrates LLM calls for the three-phase PowerPoint workflow:
  1. Horizontal Logic - generate the storyline (slide titles)
  2. Vertical Logic  - fill each slide with content (parallel)
  3. Modification     - modify individual slides via chat

Uses LLMClientManager to call Claude Opus 4.6 via the GenAI proxy.
"""
import asyncio
import json
import logging
from typing import Dict, Any, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from config.llm_config import LLMClientManager
from services.powerpoint_schema import (
    HorizontalLogic,
    HorizontalLogicSlide,
    Slide,
    Presentation,
    SlideTheme,
    LayoutType,
)
from services.powerpoint_prompts import (
    get_horizontal_logic_prompt,
    get_vertical_logic_prompt,
    get_modify_slide_prompt,
)

logger = logging.getLogger(__name__)

PPTX_TEMPERATURE = 0.4
PPTX_MAX_TOKENS = 8192


def _get_pptx_llm():
    """Get the dedicated LLM client for PowerPoint generation."""
    return LLMClientManager.get_client_for_binding(
        "service.powerpoint",
        temperature=PPTX_TEMPERATURE,
        max_tokens=PPTX_MAX_TOKENS,
        timeout=120,
    )


def _parse_json_response(response_text: str) -> dict:
    """
    Parse JSON from LLM response, handling markdown code fences.
    """
    text = response_text.strip()
    
    # Remove markdown code fences if present
    if text.startswith("```"):
        # Find the first newline after the opening fence
        first_nl = text.index("\n")
        # Find the last closing fence
        last_fence = text.rfind("```")
        if last_fence > first_nl:
            text = text[first_nl + 1:last_fence].strip()
        else:
            text = text[first_nl + 1:].strip()
    
    return json.loads(text)


async def generate_horizontal_logic(
    deliverable_data: Dict[str, Any],
    num_slides: Optional[int] = None,
    user_context: Optional[str] = None,
) -> HorizontalLogic:
    """
    Phase 1: Generate the horizontal logic (storyline) from deliverable data.
    
    Returns a HorizontalLogic object with slide stubs (headlines + layouts).
    """
    logger.debug("Generating horizontal logic for PowerPoint")
    
    system_prompt, user_prompt = get_horizontal_logic_prompt(
        deliverable_data=deliverable_data,
        num_slides=num_slides,
        user_context=user_context,
    )
    
    llm = _get_pptx_llm()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    
    response = await llm.ainvoke(messages)
    response_text = response.content if hasattr(response, "content") else str(response)
    
    logger.debug("Horizontal logic raw response: %s", response_text[:500])
    
    parsed = _parse_json_response(response_text)
    
    # Validate and build the HorizontalLogic object
    slides = []
    for s in parsed.get("slides", []):
        # Validate layout type
        layout = s.get("suggested_layout", "title_content")
        try:
            layout = LayoutType(layout)
        except ValueError:
            logger.warning("Unknown layout '%s', falling back to title_content", layout)
            layout = LayoutType.TITLE_CONTENT
        
        slides.append(HorizontalLogicSlide(
            id=s.get("id", ""),
            headline=s.get("headline", ""),
            subtitle=s.get("subtitle", ""),
            message=s.get("message", ""),
            suggested_layout=layout,
            rationale=s.get("rationale"),
        ))
    
    horizontal_logic = HorizontalLogic(
        deck_title=parsed.get("deck_title", "Untitled Presentation"),
        slides=slides,
    )
    
    logger.debug(
        "Generated horizontal logic: %d slides, title='%s'",
        len(slides),
        horizontal_logic.deck_title,
    )
    
    return horizontal_logic


async def generate_single_slide(
    deliverable_data: Dict[str, Any],
    headline: str,
    subtitle: str,
    layout: str,
    message: str = "",
    user_context: Optional[str] = None,
) -> Slide:
    """
    Generate content for a single slide (vertical logic).
    
    Returns a fully populated Slide object.
    """
    logger.debug("Generating slide: '%s' (%s)", headline[:50], layout)
    
    system_prompt, user_prompt = get_vertical_logic_prompt(
        deliverable_data=deliverable_data,
        slide_headline=headline,
        slide_subtitle=subtitle,
        slide_layout=layout,
        slide_message=message,
        user_context=user_context,
    )
    
    llm = _get_pptx_llm()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    
    response = await llm.ainvoke(messages)
    response_text = response.content if hasattr(response, "content") else str(response)
    
    logger.debug("Slide generation raw response: %s", response_text[:500])
    
    parsed = _parse_json_response(response_text)
    
    # Build Slide object (content validation via Pydantic)
    slide = Slide.model_validate(parsed)
    
    logger.debug("Generated slide '%s' with layout '%s'", slide.id, slide.layout)
    return slide


async def generate_vertical_logic(
    deliverable_data: Dict[str, Any],
    horizontal_logic: HorizontalLogic,
    user_context: Optional[str] = None,
) -> List[Slide]:
    """
    Phase 2: Generate content for ALL slides in parallel.
    
    Uses asyncio.gather to call the LLM concurrently for each slide.
    Returns a list of fully populated Slide objects.
    """
    logger.debug(
        "Generating vertical logic for %d slides in parallel",
        len(horizontal_logic.slides),
    )
    
    tasks = [
        generate_single_slide(
            deliverable_data=deliverable_data,
            headline=slide_stub.headline,
            subtitle=slide_stub.subtitle,
            layout=slide_stub.suggested_layout.value,
            message=slide_stub.message,
            user_context=user_context,
        )
        for slide_stub in horizontal_logic.slides
    ]
    
    # Run all slide generations in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    slides = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(
                "Failed to generate slide %d ('%s'): %s",
                i,
                horizontal_logic.slides[i].headline[:40],
                result,
            )
            # Create a fallback slide with error info
            slides.append(Slide(
                id=horizontal_logic.slides[i].id,
                layout=horizontal_logic.slides[i].suggested_layout,
                headline=horizontal_logic.slides[i].headline,
                subtitle=horizontal_logic.slides[i].subtitle,
                content={
                    "type": "bullet_list",
                    "items": [{"text": f"Error generating slide: {str(result)}", "level": 0}],
                },
                speaker_notes="This slide failed to generate. Please regenerate.",
            ))
        else:
            slides.append(result)
    
    logger.debug("Generated %d slides (%d successful)", len(slides), sum(1 for r in results if not isinstance(r, Exception)))
    return slides


async def modify_slide(
    current_slide: Dict[str, Any],
    instruction: str,
    deliverable_data: Optional[Dict[str, Any]] = None,
) -> Slide:
    """
    Phase 3: Modify an existing slide based on user chat instruction.
    
    Returns the updated Slide object.
    """
    logger.debug("Modifying slide '%s': %s", current_slide.get("id", "?"), instruction[:80])
    
    system_prompt, user_prompt = get_modify_slide_prompt(
        current_slide=current_slide,
        instruction=instruction,
        deliverable_data=deliverable_data,
    )
    
    llm = _get_pptx_llm()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    
    response = await llm.ainvoke(messages)
    response_text = response.content if hasattr(response, "content") else str(response)
    
    logger.debug("Slide modification raw response: %s", response_text[:500])
    
    parsed = _parse_json_response(response_text)
    slide = Slide.model_validate(parsed)
    
    logger.debug("Modified slide '%s'", slide.id)
    return slide


def build_presentation(
    title: str,
    slides: List[Slide],
    theme: Optional[SlideTheme] = None,
) -> Presentation:
    """
    Assemble slides into a Presentation object.
    """
    return Presentation(
        title=title,
        slides=slides,
        theme=theme or SlideTheme(),
    )
