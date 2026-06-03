"""
Shared helpers for reading/updating LLM fields inside workflow node JSON.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.llm.model_normalizer import infer_provider, normalize_model_name

AGENT_NODE_TYPES = {
    "agent",
    "researcher",
    "business-analyst",
    "financial-modeler",
    "opportunity-classifier",
    "subagent",
}

MODEL_CONFIG_KEYS = (
    ("modelName", "modelProvider"),
    ("deliverableModelName", "deliverableModelProvider"),
)


def extract_config(node: Dict[str, Any]) -> Dict[str, Any]:
    cfg = node.get("config") or {}
    if not cfg and isinstance(node.get("data"), dict):
        cfg = node["data"].get("config") or {}
    return cfg if isinstance(cfg, dict) else {}


def config_matches_model(cfg: Dict[str, Any], from_normalized: str) -> bool:
    """True if any LLM field normalizes to from_normalized."""
    for name_key, provider_key in MODEL_CONFIG_KEYS:
        name = cfg.get(name_key)
        if not name:
            continue
        provider = cfg.get(provider_key)
        if normalize_model_name(str(name), provider) == from_normalized:
            return True
    return False


def apply_model_replace_to_config(
    cfg: Dict[str, Any],
    from_normalized: str,
    to_normalized: str,
    to_provider: str,
) -> int:
    """Update matching fields in place. Returns number of fields changed."""
    changes = 0
    for name_key, provider_key in MODEL_CONFIG_KEYS:
        name = cfg.get(name_key)
        if not name:
            continue
        provider = cfg.get(provider_key)
        if normalize_model_name(str(name), provider) != from_normalized:
            continue
        cfg[name_key] = to_normalized
        cfg[provider_key] = to_provider
        changes += 1
    return changes


def replace_models_in_nodes_json(
    nodes_json: Optional[str],
    from_model: str,
    to_model: str,
) -> Tuple[Optional[str], int, int]:
    """
    Replace from_model -> to_model in agent node configs.

    Returns (new_json_or_none, workflows_changed_flag as 0/1, node_field_changes).
    If no changes, returns (None, 0, 0).
    """
    if not nodes_json:
        return None, 0, 0

    from_norm = normalize_model_name(from_model)
    to_norm = normalize_model_name(to_model)
    if from_norm == to_norm:
        return None, 0, 0

    to_provider = infer_provider(to_norm)

    try:
        payload = json.loads(nodes_json) if isinstance(nodes_json, str) else nodes_json
    except (json.JSONDecodeError, TypeError):
        return None, 0, 0

    nodes = payload if isinstance(payload, list) else payload.get("nodes", [])
    if not isinstance(nodes, list):
        return None, 0, 0

    total_field_changes = 0
    any_node_touched = False

    for node in nodes:
        if not isinstance(node, dict) or node.get("type") not in AGENT_NODE_TYPES:
            continue
        cfg = extract_config(node)
        if not config_matches_model(cfg, from_norm):
            continue

        n = apply_model_replace_to_config(cfg, from_norm, to_norm, to_provider)
        if n == 0:
            continue

        total_field_changes += n
        any_node_touched = True
        node["config"] = cfg
        if isinstance(node.get("data"), dict):
            data = dict(node["data"])
            data["config"] = cfg
            node["data"] = data

    if not any_node_touched:
        return None, 0, 0

    if isinstance(payload, list):
        new_payload: Any = nodes
    else:
        payload = dict(payload)
        payload["nodes"] = nodes
        new_payload = payload

    return json.dumps(new_payload, separators=(",", ":")), 1, total_field_changes
