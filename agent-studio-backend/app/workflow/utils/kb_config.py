"""
Knowledge-base configuration helpers.

Centralises the legacy ↔ multi-KB normalisation so every consumer
(agent, instructions builder, structured-schema check) reads the same
canonical list of KB IDs from the node config.

The frontend now stores ``knowledgeBaseIds: List[str]`` but workflows
saved before the multi-KB upgrade carry only ``knowledgeBaseId: str``.
``resolve_kb_ids`` returns the merged, deduplicated list so callers
never have to think about the migration shape.
"""

from typing import Any, Callable, Iterable, List, Mapping, Optional, Union

ConfigLike = Union[Mapping[str, Any], Callable[..., Any]]


def _coerce_list(value: Any) -> List[str]:
    """Coerce raw config values into a list of non-empty strings."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(v) for v in value if v]
    return []


def _read(config: ConfigLike, key: str, default: Any = None) -> Any:
    """Read a key from either a dict-like config or a getter callable.

    ``AgentNode.get_config_value`` is a callable; ``state["node_outputs"]``
    style configs are plain mappings.  Supporting both keeps the helper
    drop-in.
    """
    if callable(config):
        try:
            return config(key, default)
        except TypeError:
            return config(key)
    if isinstance(config, Mapping):
        return config.get(key, default)
    return default


def resolve_kb_ids(config: ConfigLike) -> List[str]:
    """Return the canonical, deduplicated list of KB IDs for this agent.

    Reads ``knowledgeBaseIds`` first; falls back to the legacy single
    ``knowledgeBaseId`` field if the new array is empty.  Order is
    preserved and duplicates are stripped.
    """
    raw = _read(config, "knowledgeBaseIds")
    kb_ids = _coerce_list(raw)

    if not kb_ids:
        legacy = _read(config, "knowledgeBaseId")
        kb_ids = _coerce_list(legacy)

    seen: set = set()
    deduped: List[str] = []
    for kb_id in kb_ids:
        if kb_id and kb_id not in seen:
            seen.add(kb_id)
            deduped.append(kb_id)
    return deduped


def primary_kb_id(config: ConfigLike) -> Optional[str]:
    """Return the first configured KB id, or None.

    Useful for legacy single-KB code paths (system-prompt wording,
    metadata schema lookup) that haven't been ported to multi-KB yet.
    """
    ids = resolve_kb_ids(config)
    return ids[0] if ids else None


def has_kb(config: ConfigLike) -> bool:
    """True when the agent has at least one knowledge base configured."""
    return bool(resolve_kb_ids(config))
