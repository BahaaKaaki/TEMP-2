"""
Prompt templates for design-time output-schema generation.

Analyzes an agent prompt and generates a multi-section output schema
(the `sections` array each deliverable is built from).
"""

from typing import Optional


# =============================================================================
# DESIGN-TIME: Schema Generation Prompts
# =============================================================================

def build_system_prompt() -> str:
    """
    Build the system prompt for multi-section schema generation.
    Called at design-time when the user clicks 'Generate' on the output schema builder.
    
    Returns:
        Complete system prompt that instructs the LLM to produce a multi-section schema.
    """
    return """You design COMPACT structured output schemas for LLM agents.

Given an agent's prompt, produce a JSON Schema with a `sections` array. Each section has a title, short description, and a content schema.

## RESPONSE FORMAT (strict)

Return ONLY a JSON object — no markdown, no explanation outside the JSON:
{
  "reasoning": "1-2 sentences on why these sections",
  "suggestedSchema": {
    "type": "object",
    "properties": {
      "sections": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "section_title": { "type": "string" },
            "description": { "type": "string" },
            "content": { ... }
          },
          "required": ["section_title", "description", "content"]
        }
      }
    },
    "required": ["sections"]
  }
}

## HARD CONSTRAINTS

1. **2-4 sections MAX.** Combine related data. Never exceed 4.
2. **Flat content schemas.** Max 2 levels of nesting inside content.
3. **Short property names** — "pct" not "percentage_change", "desc" not "full_description".
4. **Descriptions ≤ 10 words** in the schema. They inflate runtime prompt tokens.
5. **Tabular data → columns+rows**, never array-of-objects:
   GOOD: { "table": { "columns": ["name","value"], "rows": [["A",1]] } }
   BAD:  { "items": [{"name":"A","value":1}] }
6. **No $ref, definitions, oneOf, anyOf** — inline everything.
7. **Valid JSON Schema only** — no comments, no trailing commas.
8. Each content schema should have at most 5-8 properties.

## CONTENT PATTERNS (pick the right one)

- **Table/list data**: `{ "table": { "columns": [...], "rows": [[...]] } }`
- **Key metrics**: `{ "total": num, "growth_pct": num, "top_item": "..." }`
- **Analysis/findings**: `{ "summary": "...", "findings": ["..."] }`
- **Hierarchy**: `{ "name": "...", "children": [...] }`

## EXAMPLE

Agent prompt: "Analyze Q4 sales data across regions"
Response:
{
  "reasoning": "Sales analysis needs regional breakdown, key metrics, and insights.",
  "suggestedSchema": {
    "type": "object",
    "properties": {
      "sections": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "section_title": { "type": "string" },
            "description": { "type": "string" },
            "content": {
              "type": "object",
              "properties": {
                "table": {
                  "type": "object",
                  "properties": {
                    "columns": { "type": "array", "items": { "type": "string" } },
                    "rows": { "type": "array", "items": { "type": "array", "items": {} } }
                  }
                },
                "summary": { "type": "string" },
                "findings": { "type": "array", "items": { "type": "string" } },
                "metrics": {
                  "type": "object",
                  "properties": {
                    "total": { "type": "number" },
                    "growth_pct": { "type": "number" },
                    "top_region": { "type": "string" }
                  }
                }
              }
            }
          },
          "required": ["section_title", "description", "content"]
        }
      }
    },
    "required": ["sections"]
  }
}

This produces 3 sections: "Revenue by Region" (table), "Key Metrics" (metrics), "Insights" (summary+findings). Content uses a shared shape — the agent fills only the relevant fields per section."""


def build_user_prompt(
    prompt: str,
    task_instructions: Optional[str] = None,
    user_requirements: Optional[str] = None,
    output_schema: Optional[str] = None
) -> str:
    """
    Build the user prompt for schema generation.
    
    Args:
        prompt: The agent's main prompt/instructions
        task_instructions: Additional task-specific instructions
        user_requirements: User's additional requirements for the schema
        output_schema: Existing output schema (if any)
        
    Returns:
        Complete user prompt with all provided context
    """
    user_content = f"""Generate a multi-section output schema (2-4 sections MAX) for this agent:

AGENT PROMPT:
{prompt}"""
    
    if task_instructions:
        user_content += f"""

TASK INSTRUCTIONS:
{task_instructions}"""
    
    if user_requirements:
        user_content += f"""

USER REQUIREMENTS:
{user_requirements}"""
    
    if output_schema:
        user_content += f"""

EXISTING SCHEMA (refine, keep compact):
{output_schema}"""
    
    user_content += """

Remember: 2-4 sections max, flat content schemas, short property names. Return ONLY valid JSON."""
    
    return user_content


# =============================================================================
