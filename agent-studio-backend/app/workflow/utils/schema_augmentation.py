"""
Shared helpers that augment user-defined output schemas before they are
applied to LLM structured-output calls or surfaced via tool args.
"""
from typing import Any, Dict


_SUMMARY_PROPERTY: Dict[str, Any] = {
    "type": "string",
    "description": (
        "Summary of the deliverable. Rendered immediately above the "
        "structured output, so it must stand on its own."
    ),
}

_TITLE_PROPERTY: Dict[str, Any] = {
    "type": "string",
    "description": (
        "A short, specific human-readable title naming this deliverable "
        "(3-8 words), e.g. 'Comparable-Company Benchmark' or "
        "'Operating-Model Options'. Shown as the deliverable's name in the UI; "
        "name the deliverable itself, not the agent or the task."
    ),
}


def inject_summary_field(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of schema with `title` and `summary` injected as required strings.

    `title` is the deliverable's human-facing name (shown on the card); `summary`
    is rendered above the structured output. No-op when schema is not a JSON-Schema
    object with a properties dict, or when the field already exists. Does not mutate
    input.
    """
    if not isinstance(schema, dict):
        return schema
    if schema.get("type") != "object" or "properties" not in schema:
        return schema

    props = schema["properties"]
    if not isinstance(props, dict):
        return schema

    new_props = dict(props)
    if "summary" not in new_props:
        new_props = {"summary": dict(_SUMMARY_PROPERTY), **new_props}
    if "title" not in new_props:
        new_props = {"title": dict(_TITLE_PROPERTY), **new_props}

    required = list(schema.get("required", []) or [])
    if "summary" not in required:
        required = ["summary"] + required
    if "title" not in required:
        required = ["title"] + required

    return {**schema, "properties": new_props, "required": required}
