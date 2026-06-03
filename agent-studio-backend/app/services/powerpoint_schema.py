"""
PowerPoint Slide JSON Schema

Defines the canonical data structures for the PowerPoint generation feature.
The LLM generates slide data conforming to these schemas, which are then:
  1. Rendered as HTML preview on the frontend (SlidePreview component)
  2. Built into .pptx files by the PowerPoint builder (python-pptx)

Design references:
  - app/assets/powerpoints/S&_Polished_Layouts.html
  - app/assets/powerpoints/S&_Approach_Slides_with_CVs.html
  - app/assets/powerpoints/20260211_ai_global_economy_impact_slide.html
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, Union, Dict, Any, Literal
from pydantic import BaseModel, Field
import uuid


# =============================================================================
# THEME
# =============================================================================

class SlideTheme(BaseModel):
    """
    Strategy& brand theme extracted from the HTML asset CSS variables.
    All colors are hex strings without '#' prefix for python-pptx compatibility.
    """
    brand_color: str = Field(default="A32020", description="Primary brand red")
    brand_color_dark: str = Field(default="7a1818", description="Darker brand red")
    brand_color_light: str = Field(default="FDF2F4", description="Light red background")
    text_main: str = Field(default="2d2d2d", description="Primary text color")
    text_light: str = Field(default="5e5e5e", description="Secondary text color")
    grey_light: str = Field(default="f4f4f4", description="Light grey fill")
    grey_border: str = Field(default="e0e0e0", description="Border grey")
    white: str = Field(default="FFFFFF", description="White")
    green: str = Field(default="2e7d32", description="Positive/success green")
    green_light: str = Field(default="e8f5e9", description="Light green background")
    yellow: str = Field(default="f9a825", description="Warning yellow")
    red_bright: str = Field(default="c62828", description="Negative/alert red")

    # Typography
    title_font: str = Field(default="Georgia", description="Serif font for titles")
    body_font: str = Field(default="Arial", description="Sans-serif font for body")

    # Geometry (inches) - matches 960x540pt = 13.333" x 7.5"
    slide_width: float = Field(default=13.333, description="Slide width in inches")
    slide_height: float = Field(default=7.5, description="Slide height in inches")


# =============================================================================
# LAYOUT TYPES
# =============================================================================

class LayoutType(str, Enum):
    """Supported slide layout types derived from the HTML assets."""
    TITLE_CONTENT = "title_content"
    TWO_COLUMN = "two_column"
    THREE_COLUMN = "three_column"
    SPOTLIGHT = "spotlight"
    APPROACH_3STEP = "approach_3step"
    APPROACH_4STEP = "approach_4step"
    APPROACH_5STEP = "approach_5step"
    HORIZONTAL_APPROACH = "horizontal_approach"
    METRICS_DASHBOARD = "metrics_dashboard"
    TIMELINE = "timeline"
    COMPARISON_TABLE = "comparison_table"
    CALL_TO_ACTION = "call_to_action"
    KPI_HERO = "kpi_hero"
    CV_TEAM_SUMMARY = "cv_team_summary"
    CV_INDIVIDUAL = "cv_individual"


# =============================================================================
# CONTENT BLOCK TYPES
# =============================================================================

class BulletItem(BaseModel):
    """A single bullet point with optional bold prefix."""
    text: str
    bold_prefix: Optional[str] = Field(default=None, description="Bold text before the main text")
    level: int = Field(default=0, description="Indentation level (0 = top)")


class BulletList(BaseModel):
    """A list of bullet items."""
    type: Literal["bullet_list"] = "bullet_list"
    items: List[BulletItem]


class Card(BaseModel):
    """A styled card container (maps to bordered rect with red top bar)."""
    tag: Optional[str] = Field(default=None, description="Category tag (e.g., 'Lever 1')")
    title: str
    description: Optional[str] = Field(default=None, description="Italic description text")
    items: List[str] = Field(default_factory=list, description="Numbered action items")
    footer: Optional[str] = Field(default=None, description="Footer text in red-light bar")
    icon: Optional[str] = Field(default=None, description="Icon letter or emoji")


class CardGrid(BaseModel):
    """Grid of cards (used in two_column, three_column layouts)."""
    type: Literal["card_grid"] = "card_grid"
    cards: List[Card]


class SpotlightContent(BaseModel):
    """Spotlight layout: one main card + sidebar cards + optional stats."""
    type: Literal["spotlight"] = "spotlight"
    main_card: Card
    stats: Optional[List[Dict[str, str]]] = Field(
        default=None, description="Stats row [{'value': '$18M', 'label': 'Annual Value'}]"
    )
    sidebar_cards: List[Card] = Field(default_factory=list)


class ApproachPhase(BaseModel):
    """A single phase in an approach slide."""
    number: int
    title: str
    duration: Optional[str] = None
    substeps: List[str] = Field(default_factory=list, description="Short substep labels")


class ApproachContent(BaseModel):
    """Approach phases (3/4/5-step variants)."""
    type: Literal["approach"] = "approach"
    phases: List[ApproachPhase]
    crosscut: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional crosscut bar: {'title': '...', 'items': ['...']}"
    )


class MetricBox(BaseModel):
    """A single KPI metric box."""
    value: str
    label: str
    change: Optional[str] = Field(default=None, description="Change indicator (e.g., '+24%')")
    status: Optional[str] = Field(default=None, description="up/down/neutral")


class InsightColumn(BaseModel):
    """A column in the insight panel below metrics."""
    title: str
    items: List[str]


class MetricsDashboardContent(BaseModel):
    """Metrics dashboard: KPI boxes + insight panel."""
    type: Literal["metrics_dashboard"] = "metrics_dashboard"
    metrics: List[MetricBox]
    insights: Optional[List[InsightColumn]] = None


class TimelinePhase(BaseModel):
    """A phase in the timeline."""
    phase_label: str = Field(description="e.g., 'Q1 2025'")
    date_range: Optional[str] = Field(default=None, description="e.g., 'Jan-Mar'")
    title: str
    items: List[str] = Field(default_factory=list)
    status: Optional[str] = Field(default=None, description="past/current/future")


class TimelineContent(BaseModel):
    """Timeline layout with phase cards."""
    type: Literal["timeline"] = "timeline"
    phases: List[TimelinePhase]


class ComparisonTableContent(BaseModel):
    """Comparison table with optional recommendation."""
    type: Literal["comparison_table"] = "comparison_table"
    headers: List[str]
    rows: List[List[str]]
    recommended_column: Optional[int] = Field(
        default=None, description="0-based index of recommended column"
    )
    recommendation: Optional[str] = Field(default=None, description="Recommendation text")


class ActionItem(BaseModel):
    """An action card for CTA slides."""
    number: int
    title: str
    description: str
    owner: Optional[str] = None
    due_date: Optional[str] = None


class CallToActionContent(BaseModel):
    """Call to action layout: banner + action cards."""
    type: Literal["call_to_action"] = "call_to_action"
    banner_headline: str
    banner_subtext: Optional[str] = None
    actions: List[ActionItem]


class KPIHeroContent(BaseModel):
    """KPI hero layout: large KPI left + detail cards right."""
    type: Literal["kpi_hero"] = "kpi_hero"
    pill_label: Optional[str] = Field(default=None, description="Small tag above KPI")
    kpi_value: str = Field(description="Large hero number (e.g., '+$7-10T')")
    kpi_label: str = Field(description="Label below the KPI value")
    kpi_subnote: Optional[str] = None
    kpi_footnote: Optional[str] = None
    cards: List[Card] = Field(default_factory=list, description="Detail cards on the right")


# =============================================================================
# CV LAYOUT CONTENT TYPES
# =============================================================================

class CVProfileSummary(BaseModel):
    """One person's summary for the team overview slide."""
    name: str
    level: str = Field(default="", description="Job title / seniority")
    city: str = Field(default="", description="Location or practice area")
    summary_lines: List[str] = Field(default_factory=list, description="Executive summary bullets")
    relevant_experience_lines: List[str] = Field(default_factory=list, description="Relevant experience bullets")


class CVTeamSummaryContent(BaseModel):
    """Content for a CV team summary slide (up to 6 profiles)."""
    type: Literal["cv_team_summary"] = "cv_team_summary"
    team_title: str = Field(default="", description="Short team description")
    profiles: List[CVProfileSummary] = Field(default_factory=list)


class CVProject(BaseModel):
    """A single case project with title and bullet points."""
    title: str
    bullets: List[str] = Field(default_factory=list)


class CVLeftColumn(BaseModel):
    """Left-hand profile sections for an individual CV slide."""
    executive_summary: List[str] = Field(default_factory=list)
    relevant_experience: List[str] = Field(default_factory=list)
    prior_experience: List[str] = Field(default_factory=list)
    education_and_languages: List[str] = Field(default_factory=list)


class CVIndividualContent(BaseModel):
    """Content for a single-person CV slide (two-column layout)."""
    type: Literal["cv_individual"] = "cv_individual"
    name: str
    level: str = Field(default="")
    city: str = Field(default="")
    left_column: CVLeftColumn = Field(default_factory=CVLeftColumn)
    projects: List[CVProject] = Field(default_factory=list)


# Union of all content types
SlideContentBlock = Union[
    BulletList,
    CardGrid,
    SpotlightContent,
    ApproachContent,
    MetricsDashboardContent,
    TimelineContent,
    ComparisonTableContent,
    CallToActionContent,
    KPIHeroContent,
    CVTeamSummaryContent,
    CVIndividualContent,
]


# =============================================================================
# SLIDE & PRESENTATION
# =============================================================================

class Slide(BaseModel):
    """
    A single slide following the Strategy& structure:
    Headline (active "so what" sentence) -> Subtitle (topic tag) -> Frame (content)
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    layout: LayoutType
    headline: str = Field(description="Active, news-style sentence (the 'so what')")
    subtitle: str = Field(description="Short topic tag (e.g., 'Market context')")
    content: SlideContentBlock
    speaker_notes: Optional[str] = Field(default=None, description="Speaker notes for the slide")


class HorizontalLogicSlide(BaseModel):
    """A slide stub for horizontal logic (storyline) phase."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    headline: str = Field(description="Action title - active sentence")
    subtitle: str = Field(description="Topic tag")
    message: str = Field(
        default="",
        description="Slide narrative — what the slide should convey and what content to generate"
    )
    suggested_layout: LayoutType
    rationale: Optional[str] = Field(
        default=None, description="Brief reasoning for this slide and layout choice"
    )


class HorizontalLogic(BaseModel):
    """The storyline / horizontal logic for the entire deck."""
    deck_title: str
    slides: List[HorizontalLogicSlide]


class Presentation(BaseModel):
    """Complete presentation with all slides."""
    title: str
    slides: List[Slide]
    theme: SlideTheme = Field(default_factory=SlideTheme)


# =============================================================================
# API REQUEST / RESPONSE SCHEMAS
# =============================================================================

class HorizontalLogicRequest(BaseModel):
    """Request to generate horizontal logic from deliverable data."""
    deliverable_id: str
    deliverable_data: Dict[str, Any]
    num_slides: Optional[int] = Field(
        default=None,
        description="Desired number of slides (LLM will decide if not specified)"
    )
    context: Optional[str] = Field(
        default=None,
        description="Additional context or instructions from the user"
    )


class HorizontalLogicResponse(BaseModel):
    """Response containing the generated storyline."""
    horizontal_logic: HorizontalLogic
    message: str = "Storyline generated successfully"


class VerticalLogicRequest(BaseModel):
    """Request to generate content for all slides."""
    deliverable_data: Dict[str, Any]
    horizontal_logic: HorizontalLogic
    context: Optional[str] = None


class SlideGenerationResponse(BaseModel):
    """Response for a single generated slide."""
    slide: Slide
    message: str = "Slide generated successfully"


class ModifySlideRequest(BaseModel):
    """Request to modify a slide via chat."""
    slide: Slide
    instruction: str = Field(description="User's modification instruction")
    deliverable_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Original deliverable data for context"
    )


class ExportRequest(BaseModel):
    """Request to export a presentation to .pptx."""
    presentation: Presentation


class GenerateSingleSlideRequest(BaseModel):
    """Request to generate a single slide."""
    deliverable_data: Dict[str, Any]
    headline: str
    subtitle: str
    layout: LayoutType
    context: Optional[str] = None


