"""Generate a JSON Schema from extracted placeholders.

Maps placeholder paths to a JSON Schema ``object`` that can be used as the
output schema of an LLM-driven workflow agent.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Set

from .placeholder_parser import (
    Placeholder,
    PlaceholderKind,
    detect_loops,
    detect_repeat_groups,
    detect_variants,
)


def _set_nested(schema_props: Dict, path_parts: List[str],
                prop_def: Dict) -> None:
    """Set a property definition at an arbitrary nesting depth."""
    current = schema_props
    for part in path_parts[:-1]:
        if part not in current:
            current[part] = {
                "type": "object",
                "properties": {},
            }
        node = current[part]
        if node.get("type") == "array":
            node = node.setdefault("items", {"type": "object", "properties": {}})
        if "properties" not in node:
            node["properties"] = {}
        current = node["properties"]

    leaf = path_parts[-1]
    if leaf not in current:
        current[leaf] = prop_def


def _finalize_objects(node: Dict, required_paths: Set[str],
                      prefix: str = "") -> None:
    """Walk the schema tree and finalise nested ``object`` nodes.

    Adds ``additionalProperties: false`` to every nested object so the LLM
    does not hallucinate extra fields.  Fields whose full dotted path appears
    in *required_paths* are added to the object's ``required`` list; all
    others remain optional.
    """
    if node.get("type") != "object" or "properties" not in node:
        return

    child_required: List[str] = []
    for key, child in node["properties"].items():
        full = "%s.%s" % (prefix, key) if prefix else key
        if full in required_paths:
            child_required.append(key)
        _finalize_objects(child, required_paths, full)

    if child_required:
        node["required"] = sorted(child_required)
    node["additionalProperties"] = False


def generate_schema(placeholders: List[Placeholder],
                    title: str = "template_output") -> Dict[str, Any]:
    """Build a JSON Schema from a list of :class:`Placeholder` objects.

    Fields whose placeholder includes a ``| description`` hint are treated
    as required inside their parent object.  All other fields are optional,
    which prevents the LLM from hallucinating data for unused slots.
    """
    props: Dict[str, Any] = {}
    required: List[str] = []
    required_paths: Set[str] = set()

    loops = {l["name"]: l for l in detect_loops(placeholders)}

    repeat_groups = detect_repeat_groups(placeholders)
    repeat_roots: Set[str] = set()

    # Build a mapping of repeat-group roots that live inside loops.
    # Key = loop name, value = set of field prefixes (e.g. "projects_left").
    loop_repeat_roots: Dict[str, Set[str]] = {}
    for rg in repeat_groups:
        root = rg["array_root"]
        if not root.startswith("item."):
            continue
        field_root = root[len("item."):]
        for loop_name, loop_info in loops.items():
            if loop_info["start_slide"] <= rg["slide_index"] <= loop_info["end_slide"]:
                loop_repeat_roots.setdefault(loop_name, set()).add(
                    field_root.split(".")[0]
                )
                break

    for loop_name, loop_info in loops.items():
        item_props: Dict[str, Any] = {}
        rg_prefixes = loop_repeat_roots.get(loop_name, set())

        for field_name in loop_info["fields"]:
            top_part = field_name.split(".")[0]
            if top_part in rg_prefixes:
                continue

            parts = field_name.split(".")
            leaf_def: Dict[str, Any] = {"type": "string"}

            for ph in placeholders:
                if (ph.loop_context == loop_name
                        and ph.path == f"item.{field_name}"):
                    if ph.kind == PlaceholderKind.BULLET_ARRAY:
                        leaf_def = {"type": "array", "items": {"type": "string"}}
                    if ph.description:
                        leaf_def["description"] = ph.description
                    break

            _set_nested(item_props, parts, leaf_def)

        props[loop_name] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": item_props,
                "required": list(item_props.keys()),
                "additionalProperties": False,
            },
        }
        required.append(loop_name)
        required_paths.add(loop_name)

    for rg in repeat_groups:
        root = rg["array_root"]
        repeat_roots.add(root)

        rg_item_props: Dict[str, Any] = {}
        rg_item_required: List[str] = []
        for field in rg["fields"]:
            leaf = field["leaf"]
            if field["kind"] == PlaceholderKind.BULLET_ARRAY.value:
                leaf_def: Dict[str, Any] = {
                    "type": "array",
                    "items": {"type": "string"},
                }
            else:
                leaf_def = {"type": "string"}
            if field.get("description"):
                leaf_def["description"] = field["description"]
            rg_item_props[leaf] = leaf_def
            rg_item_required.append(leaf)

        array_def: Dict[str, Any] = {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": rg_item_props,
                "required": sorted(rg_item_required),
                "additionalProperties": False,
            },
        }

        if root.startswith("item."):
            field_root = root[len("item."):]
            parent_loop = None
            for ln, li in loops.items():
                if li["start_slide"] <= rg["slide_index"] <= li["end_slide"]:
                    parent_loop = ln
                    break
            if parent_loop and parent_loop in props:
                loop_items = props[parent_loop].get("items", {})
                loop_item_props = loop_items.get("properties", {})
                field_parts = field_root.split(".")
                if len(field_parts) == 1:
                    loop_item_props[field_root] = array_def
                else:
                    _set_nested(loop_item_props, field_parts, array_def)
                if field_root not in loop_items.get("required", []):
                    loop_items.setdefault("required", []).append(field_root)
                    loop_items["required"] = sorted(loop_items["required"])
                continue

        root_parts = root.split(".")
        _set_nested(props, root_parts, array_def)
        required_paths.add(root)
        top_key = root_parts[0]
        if top_key not in required:
            required.append(top_key)

    variant_groups = detect_variants(placeholders)
    variant_arrays: Dict[str, Dict] = {vg["name"]: vg for vg in variant_groups}
    variant_slide_set: Set[int] = set()
    for vg in variant_groups:
        for slide_list in vg["variants"].values():
            variant_slide_set.update(slide_list)

    # Collect item fields from variant slides.  Paths like
    # ``people.0.full_name`` on a variant-tagged slide are folded into
    # the array's item schema as ``full_name``.
    variant_item_fields: Dict[str, Dict[str, Dict]] = {}
    for ph in placeholders:
        if ph.kind in (
            PlaceholderKind.VARIANT,
            PlaceholderKind.LOOP_START,
            PlaceholderKind.LOOP_END,
        ):
            continue
        if ph.slide_index not in variant_slide_set:
            continue
        path_parts = ph.path.split(".")
        if len(path_parts) < 3 or not path_parts[1].isdigit():
            continue
        array_name = path_parts[0]
        if array_name not in variant_arrays:
            continue
        field_path = ".".join(path_parts[2:])
        if array_name not in variant_item_fields:
            variant_item_fields[array_name] = {}
        if field_path not in variant_item_fields[array_name]:
            if ph.kind == PlaceholderKind.BULLET_ARRAY:
                leaf_def: Dict[str, Any] = {
                    "type": "array",
                    "items": {"type": "string"},
                }
            else:
                leaf_def = {"type": "string"}
            if ph.description:
                leaf_def["description"] = ph.description
            variant_item_fields[array_name][field_path] = leaf_def

    for array_name, fields in variant_item_fields.items():
        vg = variant_arrays[array_name]
        if array_name in props and props[array_name].get("type") == "array":
            items_node = props[array_name].setdefault(
                "items", {"type": "object", "properties": {}},
            )
            item_props = items_node.setdefault("properties", {})
        else:
            item_props: Dict[str, Any] = {}
            props[array_name] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": item_props,
                    "additionalProperties": False,
                },
            }
            if array_name not in required:
                required.append(array_name)
            required_paths.add(array_name)
            items_node = props[array_name]["items"]

        for field_path, field_def in fields.items():
            parts = field_path.split(".")
            _set_nested(item_props, parts, field_def)

        if items_node.get("required") is not None:
            existing_req = set(items_node["required"])
            existing_req.update(item_props.keys())
            items_node["required"] = sorted(existing_req)
        else:
            items_node["required"] = sorted(item_props.keys())

        if vg["min_count"] > 0:
            props[array_name]["minItems"] = vg["min_count"]
        if vg["max_count"] > 0:
            props[array_name]["maxItems"] = vg["max_count"]

    for ph in placeholders:
        if ph.kind in (
            PlaceholderKind.LOOP_START,
            PlaceholderKind.LOOP_END,
            PlaceholderKind.VARIANT,
        ):
            continue
        if ph.loop_context:
            continue
        if ph.kind == PlaceholderKind.REPEAT_FIELD:
            continue

        parts = ph.path.rsplit(".", 1)
        if len(parts) == 2 and parts[0] in repeat_roots:
            continue

        path_parts = ph.path.split(".")

        # Skip array-index paths handled by variant logic above.
        if (
            len(path_parts) >= 3
            and path_parts[1].isdigit()
            and path_parts[0] in variant_arrays
        ):
            continue

        if ph.kind == PlaceholderKind.BULLET_ARRAY:
            prop_def: Dict[str, Any] = {
                "type": "array",
                "items": {"type": "string"},
            }
        else:
            prop_def = {"type": "string"}

        if ph.description:
            prop_def["description"] = ph.description
            required_paths.add(ph.path)

        _set_nested(props, path_parts, prop_def)
        top_key = path_parts[0]
        if top_key not in required:
            required.append(top_key)

    schema: Dict[str, Any] = {
        "type": "object",
        "title": title,
        "properties": props,
        "required": sorted(required),
        "additionalProperties": False,
    }

    _finalize_objects(schema, required_paths)

    return schema


def schema_to_json(placeholders: List[Placeholder],
                   title: str = "template_output",
                   indent: int = 2) -> str:
    """Convenience wrapper that returns the schema as a JSON string."""
    return json.dumps(generate_schema(placeholders, title), indent=indent)
