"""
LLM Prompts for PowerPoint Generation

Three dedicated prompts:
  1. Horizontal Logic - builds the storyline (slide titles)
  2. Vertical Logic - fills each slide with content
  3. Slide Modification - modifies a slide based on user chat

All prompts enforce the JSON schema and consulting best practices
inspired by the Strategy& brand and the analyzed ChatGPT prompt.
"""

import json
from typing import Optional

# =============================================================================
# LAYOUT TYPE DESCRIPTIONS (for LLM context)
# =============================================================================

LAYOUT_DESCRIPTIONS = """
Available layout types and when to use each:

- title_content: Simple title + bullet points. Use for introductions, executive summaries, or text-heavy content.
- two_column: Two card columns side by side. Use for comparing two concepts, imperatives, or focus areas.
- three_column: Three card columns (pillars). Use for three strategic levers, options, or workstreams.
- spotlight: One large main card + two smaller sidebar cards. Use when one topic is primary with supporting items.
- approach_3step / approach_4step / approach_5step: Phased approach with numbered phases and substeps. Use for methodology, project plans, implementation roadmaps.
- horizontal_approach: Horizontal phase layout with arrow connectors and optional crosscut bar. Use as an alternative approach layout with process flow emphasis.
- metrics_dashboard: KPI metric boxes on top + insight panel below. Use for performance dashboards, status updates, scorecard reviews.
- timeline: Quarterly or phased timeline with cards. Use for roadmaps, delivery timelines, milestones.
- comparison_table: Options comparison matrix. Use for evaluating strategic options, vendor comparisons, scenario analysis.
- call_to_action: Banner + action cards with owners and dates. Use for next steps, decision requests, closing slides.
- kpi_hero: Hero KPI on the left + detail cards on the right. Use for impact slides, headline metrics with supporting evidence.
- cv_team_summary: Team overview grid showing up to 6 profiles with name, role, city, summary and relevant experience bullets. Use when presenting the full consulting team.
- cv_individual: Two-column individual CV (left: profile sections, right: case studies/projects). Use for detailed single-person CVs following the Strategy& branded template.
"""

# =============================================================================
# HORIZONTAL LOGIC PROMPT
# =============================================================================

def get_horizontal_logic_prompt(
    deliverable_data: dict,
    num_slides: Optional[int] = None,
    user_context: Optional[str] = None
) -> str:
    """
    Build the system + user prompt for horizontal logic generation.
    
    The LLM reads the deliverable output and creates the "red thread" storyline -
    a sequence of slide titles (action titles) that tell a complete story.
    """
    
    slide_count_instruction = ""
    if num_slides:
        slide_count_instruction = f"Generate exactly {num_slides} slides."
    else:
        slide_count_instruction = "Determine the optimal number of slides (typically 4-8) based on the content. Do not exceed 10 slides."
    
    user_context_section = ""
    if user_context:
        user_context_section = f"\n## Additional Instructions from the User\n{user_context}\n"
    
    system_prompt = f"""You are an expert Strategy& consultant and executive slide designer.

Your task is to create the HORIZONTAL LOGIC (storyline) for a consulting presentation.

## What is Horizontal Logic?
Horizontal logic is the "red thread" that runs through the presentation. If you lay the slides on a table and read ONLY the headlines, they should tell a complete, cohesive story. A partner should be able to flip through in 30 seconds and understand the entire recommendation.

## Rules for Headlines
- Every headline must be an ACTIVE, NEWS-STYLE SENTENCE (the "so what") - NOT a passive topic label.
- BAD: "Market Overview" or "Revenue Analysis"
- GOOD: "Market growth is decelerating, creating urgency for differentiation" or "Three levers can unlock $45M in annual value"
- Headlines should flow logically from problem to solution to action.

## Rules for Subtitles
- Short topic tags (2-4 words): "Market context", "Strategic options", "Implementation approach"

## Rules for Message
- The "message" is a 1-3 sentence brief that directs the slide content generator.
- It describes WHAT the slide should contain, WHAT data or arguments to present, and WHY.
- Think of it as the creative brief for the person building the slide.
- Example: "Show the 119 NEOM engagements since 2020 as the hero KPI. Support with cards detailing coverage across The Line, Oxagon, Gulf of Aqaba, NEOM Mountain, and sector breadth."

{LAYOUT_DESCRIPTIONS}

## Slide Sequencing Best Practices
- Start with context/situation (what's happening)
- Move to implications (so what)
- Present the solution/recommendation (what we propose)
- Detail the approach (how we'll do it)
- Close with next steps/call to action

{slide_count_instruction}
{user_context_section}

## Output Format
Return a JSON object with this exact structure:
{{
  "deck_title": "Short deck title",
  "slides": [
    {{
      "id": "s1",
      "headline": "Active sentence headline (the so what)",
      "subtitle": "Short topic tag",
      "message": "1-3 sentence brief directing what content this slide should contain and why",
      "suggested_layout": "one of the layout type values",
      "rationale": "Brief reason for this slide and layout choice"
    }}
  ]
}}

Respond ONLY with valid JSON. No markdown, no explanation."""

    user_prompt = f"""Analyze the following deliverable data and create a compelling storyline:

{json.dumps(deliverable_data, indent=2, default=str)[:12000]}"""

    return system_prompt, user_prompt


# =============================================================================
# VERTICAL LOGIC PROMPT
# =============================================================================

def get_vertical_logic_prompt(
    deliverable_data: dict,
    slide_headline: str,
    slide_subtitle: str,
    slide_layout: str,
    slide_message: str = "",
    user_context: Optional[str] = None
) -> str:
    """
    Build the prompt to fill one slide with content (vertical logic).
    
    Vertical logic ensures everything under the title supports the claim.
    If the title says "Market growth is slowing," the content must prove it.
    """
    
    user_context_section = ""
    if user_context:
        user_context_section = f"\n## Additional Context\n{user_context}\n"
    
    message_section = ""
    if slide_message:
        message_section = f'\n- Message / Brief: "{slide_message}"'
    
    # Build layout-specific schema guidance
    content_schema = _get_content_schema_for_layout(slide_layout)
    
    system_prompt = f"""You are an expert Strategy& consultant building a single executive slide.

## Your Task
Fill the slide with content that PROVES the headline. This is VERTICAL LOGIC:
- Every piece of content must support the headline claim.
- No filler. No redundancy. Every element earns its place.
- Content should be executive-level: minimal text, clear structure, data-driven.

## Slide Info
- Headline: "{slide_headline}"
- Subtitle: "{slide_subtitle}"
- Layout: "{slide_layout}"{message_section}

## Content Structure for "{slide_layout}"
{content_schema}

## Design Rules
- Minimum font is 12pt conceptually - keep text concise.
- Slides should be LIGHT on text and executive, but FILL the space beautifully.
- Use numbers and data points wherever possible.
- Bold prefixes highlight key terms (e.g., "Define value pools" in bold, then explanation).
- Limit bullet items to 3-5 per section/card.
- Substep labels for approaches: max 4-5 words, not full sentences.
{user_context_section}

## Output Format
Return a JSON object with this exact structure:
{{
  "id": "unique_id",
  "layout": "{slide_layout}",
  "headline": "{slide_headline}",
  "subtitle": "{slide_subtitle}",
  "content": {{ /* content matching the schema for this layout */ }},
  "speaker_notes": "Optional notes for the presenter"
}}

Respond ONLY with valid JSON. No markdown, no explanation."""

    user_prompt = f"""Build the slide content using the following source data:

{json.dumps(deliverable_data, indent=2, default=str)[:12000]}"""

    return system_prompt, user_prompt


# =============================================================================
# SLIDE MODIFICATION PROMPT
# =============================================================================

def get_modify_slide_prompt(
    current_slide: dict,
    instruction: str,
    deliverable_data: Optional[dict] = None
) -> str:
    """
    Build the prompt to modify an existing slide based on user instruction.
    """
    
    context_section = ""
    if deliverable_data:
        context_section = f"""
## Source Data (for reference if needed)
{json.dumps(deliverable_data, indent=2, default=str)[:6000]}
"""
    
    system_prompt = f"""You are an expert Strategy& consultant modifying an executive slide.

## Rules
- Apply the user's modification precisely.
- Maintain the Strategy& brand style: clean, executive, minimal text.
- Keep the same layout type unless the user explicitly asks to change it.
- Keep the headline as an active, news-style sentence.
- Preserve content that the user didn't ask to change.

{LAYOUT_DESCRIPTIONS}
{context_section}

## Output Format
Return the COMPLETE updated slide as a JSON object with the same structure.
Include ALL fields (id, layout, headline, subtitle, content, speaker_notes).

Respond ONLY with valid JSON. No markdown, no explanation."""

    user_prompt = f"""## Current Slide
{json.dumps(current_slide, indent=2, default=str)}

## User Instruction
{instruction}

Apply the instruction and return the updated slide JSON."""

    return system_prompt, user_prompt


# =============================================================================
# HELPERS
# =============================================================================

def _get_content_schema_for_layout(layout: str) -> str:
    """Return the expected JSON content structure for a given layout type."""
    
    schemas = {
        "title_content": """{
  "type": "bullet_list",
  "items": [
    {"text": "Main point text", "bold_prefix": "Key term", "level": 0},
    {"text": "Supporting detail", "bold_prefix": null, "level": 1}
  ]
}""",
        "two_column": """{
  "type": "card_grid",
  "cards": [
    {
      "tag": "Category tag (e.g., 'Imperative 1')",
      "title": "Card title",
      "description": "Brief italic description",
      "items": ["Numbered action item 1", "Item 2", "Item 3"],
      "footer": "Footer text (e.g., 'Target: +15% CAGR')"
    }
  ]
}
Use exactly 2 cards for two_column layout.""",
        "three_column": """{
  "type": "card_grid",
  "cards": [
    {
      "tag": "Lever 1",
      "title": "Card title",
      "description": "Brief italic description",
      "items": ["Item 1", "Item 2", "Item 3"],
      "footer": "Footer tagline"
    }
  ]
}
Use exactly 3 cards for three_column layout.""",
        "spotlight": """{
  "type": "spotlight",
  "main_card": {
    "tag": "Primary",
    "title": "Main topic",
    "description": "Detailed description",
    "items": ["Action 1", "Action 2", "Action 3", "Action 4"]
  },
  "stats": [
    {"value": "$18M", "label": "Annual Value"},
    {"value": "40%", "label": "of Total Benefit"},
    {"value": "6 mo", "label": "Time to Value"}
  ],
  "sidebar_cards": [
    {"tag": "Supporting", "title": "Side topic", "description": "Brief desc", "footer": "$15M value"}
  ]
}
Use 2-3 sidebar cards.""",
        "approach_3step": """{
  "type": "approach",
  "phases": [
    {
      "number": 1,
      "title": "Phase Name (max 3 words for 3-step)",
      "duration": "Weeks 1-4",
      "substeps": ["Substep label (max 4-5 words)", "Substep 2", "Substep 3"]
    }
  ]
}
Use exactly 3 phases. Phase titles max 3 words.""",
        "approach_4step": """{
  "type": "approach",
  "phases": [
    {
      "number": 1,
      "title": "Phase (max 3 words)",
      "duration": "Weeks 1-3",
      "substeps": ["Substep 1", "Substep 2", "Substep 3"]
    }
  ]
}
Use exactly 4 phases. Phase titles max 3 words.""",
        "approach_5step": """{
  "type": "approach",
  "phases": [
    {
      "number": 1,
      "title": "Phase (max 2 words)",
      "duration": "Wk 1-2",
      "substeps": ["Substep 1", "Substep 2", "Substep 3"]
    }
  ]
}
Use exactly 5 phases. Phase titles max 2 words.""",
        "horizontal_approach": """{
  "type": "approach",
  "phases": [
    {
      "number": 1,
      "title": "Phase Name",
      "duration": "Weeks 1-4",
      "substeps": ["Step 1", "Step 2", "Step 3"]
    }
  ],
  "crosscut": {
    "title": "Cross-cutting workstream name",
    "items": ["Activity 1", "Activity 2", "Activity 3", "Activity 4"]
  }
}
Use 3-4 phases plus a crosscut bar.""",
        "metrics_dashboard": """{
  "type": "metrics_dashboard",
  "metrics": [
    {"value": "$18.4M", "label": "Cost Savings", "change": "+24% vs plan", "status": "up"}
  ],
  "insights": [
    {"title": "What's Working", "items": ["Insight 1", "Insight 2", "Insight 3"]},
    {"title": "Watch Items", "items": ["Risk 1", "Risk 2"]},
    {"title": "Next Focus", "items": ["Action 1", "Action 2"]}
  ]
}
Use 3-4 metric boxes and 3 insight columns.""",
        "timeline": """{
  "type": "timeline",
  "phases": [
    {
      "phase_label": "Q1 2025",
      "date_range": "Jan-Mar",
      "title": "Foundation",
      "items": ["Activity 1", "Activity 2", "Activity 3"],
      "status": "past"
    }
  ]
}
Use 3-4 timeline phases. Status: past/current/future.""",
        "comparison_table": """{
  "type": "comparison_table",
  "headers": ["Criteria", "Option A", "Option B: Recommended", "Option C"],
  "rows": [
    ["Row label", "Cell 1", "Cell 2", "Cell 3"]
  ],
  "recommended_column": 2,
  "recommendation": "Summary recommendation text"
}
Use 4-6 rows and 3-4 columns (first column is criteria).""",
        "call_to_action": """{
  "type": "call_to_action",
  "banner_headline": "Key message requiring action",
  "banner_subtext": "Urgency or consequence of inaction",
  "actions": [
    {
      "number": 1,
      "title": "Action title",
      "description": "What needs to happen and why",
      "owner": "CFO",
      "due_date": "Dec 15"
    }
  ]
}
Use 2-3 action items.""",
        "kpi_hero": """{
  "type": "kpi_hero",
  "pill_label": "Category tag (e.g., 'Long-term impact')",
  "kpi_value": "+$7-10T",
  "kpi_label": "Label explaining the KPI",
  "kpi_subnote": "Supporting explanation",
  "kpi_footnote": "Caveat or source note",
  "cards": [
    {
      "icon": "P",
      "title": "Category title",
      "items": ["Detail point 1", "Detail point 2"]
    }
  ]
}
Use 2-3 detail cards.""",
        "cv_team_summary": """{
  "type": "cv_team_summary",
  "team_title": "Short team description (e.g. 'AI & Digital Government Team')",
  "profiles": [
    {
      "name": "Person Name",
      "level": "Director - AI & Digital Government",
      "city": "Riyadh",
      "summary_lines": ["Executive summary bullet 1", "Executive summary bullet 2"],
      "relevant_experience_lines": ["Exp bullet 1", "Exp bullet 2", "Exp bullet 3", "Exp bullet 4"]
    }
  ]
}
Include 2-6 profiles. Each profile: name, level (job title), city, exactly 2 summary_lines (each <=42 chars), exactly 4 relevant_experience_lines (each <=42 chars). Telegraphic style, no full sentences.""",
        "cv_individual": """{
  "type": "cv_individual",
  "name": "Person Name",
  "level": "Director - AI & Digital Government",
  "city": "Riyadh",
  "left_column": {
    "executive_summary": ["Summary bullet 1 (<=42 chars)", "Bullet 2"],
    "relevant_experience": ["Experience 1", "Experience 2", "Experience 3", "Experience 4"],
    "prior_experience": ["Prior role 1", "Prior role 2"],
    "education_and_languages": ["Degree", "Languages"]
  },
  "projects": [
    {
      "title": "Short project title (max 8 words)",
      "bullets": ["What was done (8-15 words)", "Impact achieved (8-15 words)"]
    }
  ]
}
LEFT COLUMN: executive_summary exactly 2 bullets <=42 chars each, relevant_experience exactly 4 bullets <=42 chars each, prior_experience exactly 2 bullets <=42 chars each, education_and_languages exactly 2 bullets <=42 chars each. Telegraphic style, no full sentences.
RIGHT COLUMN: at least 3 projects, title max 8 words, 2-3 bullets each (8-15 words per bullet), at least 15 bullets total, never more than 22.""",
    }

    return schemas.get(layout, schemas["title_content"])
