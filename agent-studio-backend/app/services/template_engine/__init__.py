"""Generic PPTX template engine.

Provides placeholder extraction, JSON Schema generation, and template
filling for arbitrary PPTX templates with ``{{ }}``, ``{{* }}``, ``{{+ }}``,
``{{# }}``/``{{/ }}``, and ``{{@ }}`` (variant) placeholders.
"""

from .placeholder_parser import (
    Placeholder,
    PlaceholderKind,
    detect_loops,
    detect_repeat_groups,
    detect_variants,
    extract_placeholders,
    summarise,
)
from .schema_generator import generate_schema, schema_to_json
from .template_filler import fill_template, fill_template_to_file
from .template_sanitizer import sanitize_template

__all__ = [
    "Placeholder",
    "PlaceholderKind",
    "detect_loops",
    "detect_repeat_groups",
    "detect_variants",
    "extract_placeholders",
    "fill_template",
    "fill_template_to_file",
    "generate_schema",
    "sanitize_template",
    "schema_to_json",
    "summarise",
]
