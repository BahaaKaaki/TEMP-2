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


def inject_summary_field(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of schema with `summary` injected as a required string property.

    No-op when schema is not a JSON-Schema object with a properties dict, or when
    `summary` already exists. Does not mutate input.
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

    required = list(schema.get("required", []) or [])
    if "summary" not in required:
        required = ["summary"] + required

    return {**schema, "properties": new_props, "required": required}
