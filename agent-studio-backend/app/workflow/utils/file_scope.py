"""
Per-agent uploaded file scope (workflow layer, no service/repository imports).

Receiving-agent ``fileScope`` controls visibility; uploads store provenance only.
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional, Set, Tuple

from domain.entities import Workflow, File

DEFAULT_FILE_SCOPE = "local"

_UPSTREAM_FILE_NODE_TYPES = frozenset({"agent", "subagent", "code-executor"})
_AGENT_NODE_TYPES = frozenset({"agent", "subagent"})


def resolve_file_scope_mode(node_config: dict) -> str:
    """Normalize ``fileScope`` to ``self_only``, ``all``, or ``specific``."""
    raw = (node_config or {}).get("fileScope")

    if raw is None or raw == "":
        return "self_only"
    if raw is False or raw == "none":
        return "self_only"
    if raw is True or raw == "all" or raw == "global":
        return "all"
    if raw == "local":
        return "self_only"
    if isinstance(raw, list):
        return "specific"
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in ("local", "none"):
            return "self_only"
        if normalized in ("global", "all"):
            return "all"
    return "self_only"


def get_upstream_agent_ids(
    workflow: Optional[Workflow],
    current_node_id: str,
) -> List[str]:
    """Return upstream agent/code-executor node ids (earliest first)."""
    if not workflow or not current_node_id:
        return []

    try:
        nodes = workflow.get_nodes_list() or []
        edges = workflow.get_edges_list() or []
    except Exception:
        return []

    nodes_by_id = {
        n.get("id"): n
        for n in nodes
        if isinstance(n, dict) and n.get("id")
    }
    incoming: dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src, tgt = edge.get("source"), edge.get("target")
        if src and tgt:
            incoming[tgt].append(src)

    visited: Set[str] = set()
    queue = list(incoming.get(current_node_id, []))
    agent_ids: List[str] = []

    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)

        node = nodes_by_id.get(node_id)
        if not node:
            continue

        if node.get("type") in _UPSTREAM_FILE_NODE_TYPES:
            agent_ids.append(node_id)

        for src in incoming.get(node_id, []):
            if src not in visited:
                queue.append(src)

    agent_ids.reverse()
    return agent_ids


def resolve_allowed_upload_agent_ids(
    workflow: Optional[Workflow],
    current_agent_id: str,
    node_config: dict,
) -> Tuple[Set[str], str]:
    """Return agent ids whose uploads ``current_agent_id`` may read, plus mode."""
    mode = resolve_file_scope_mode(node_config)

    if mode == "self_only":
        return {current_agent_id}, mode

    if mode == "all":
        upstream = get_upstream_agent_ids(workflow, current_agent_id)
        return set(upstream) | {current_agent_id}, mode

    if mode == "specific":
        raw = (node_config or {}).get("fileScope")
        selected = {
            aid for aid in raw
            if isinstance(aid, str) and aid.strip()
        }
        return selected | {current_agent_id}, mode

    return {current_agent_id}, mode


def get_node_config_for_agent(
    workflow: Optional[Workflow],
    agent_id: str,
) -> dict:
    if not workflow or not agent_id:
        return {}
    node = _node_by_id(workflow, agent_id)
    if not node:
        return {}
    return _node_config(node)


def filter_files_for_agent(
    files: List[File],
    allowed_agent_ids: Set[str],
    mode: str,
) -> List[File]:
    visible: List[File] = []
    for f in files:
        if f is None:
            continue
        stamp = f.uploaded_at_agent_id
        if stamp:
            if stamp in allowed_agent_ids:
                visible.append(f)
            continue
        if mode == "all":
            visible.append(f)
    return visible


def partition_files_for_injection(
    files: List[File],
    current_agent_id: str,
) -> Tuple[List[File], List[File]]:
    own: List[File] = []
    other: List[File] = []
    for f in files:
        stamp = f.uploaded_at_agent_id
        if stamp == current_agent_id:
            own.append(f)
        else:
            other.append(f)
    return own, other


def resolve_agent_file_scope(
    workflow: Optional[Workflow],
    agent_id: Optional[str],
) -> str:
    if not workflow or not agent_id:
        return DEFAULT_FILE_SCOPE
    config = get_node_config_for_agent(workflow, agent_id)
    mode = resolve_file_scope_mode(config)
    return "global" if mode == "all" else "local"


def _node_config(node: dict) -> dict:
    if not isinstance(node, dict):
        return {}
    data = node.get("data") or {}
    if isinstance(data, dict):
        cfg = data.get("config")
        if isinstance(cfg, dict):
            return cfg
    cfg = node.get("config")
    if isinstance(cfg, dict):
        return cfg
    return {}


def _label_for_node(node: dict) -> Optional[str]:
    cfg = _node_config(node)
    label = cfg.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    data = node.get("data") if isinstance(node, dict) else None
    if isinstance(data, dict):
        label = data.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    nid = node.get("id") if isinstance(node, dict) else None
    return nid


def _node_by_id(workflow: Workflow, agent_id: str) -> Optional[dict]:
    try:
        for node in workflow.get_nodes_list():
            if isinstance(node, dict) and node.get("id") == agent_id:
                return node
    except Exception:
        return None
    return None


def label_for_agent(
    workflow: Optional[Workflow],
    agent_id: str,
) -> Optional[str]:
    if not workflow:
        return agent_id
    node = _node_by_id(workflow, agent_id)
    if not node:
        return agent_id
    return _label_for_node(node)


def first_agent_node(workflow: Workflow) -> Optional[dict]:
    try:
        nodes = workflow.get_nodes_list()
    except Exception:
        nodes = []
    if not nodes:
        return None

    try:
        edges = workflow.get_edges_list()
    except Exception:
        edges = []

    nodes_by_id = {
        n.get("id"): n for n in nodes
        if isinstance(n, dict) and n.get("id")
    }
    outgoing: dict = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = e.get("source")
        tgt = e.get("target")
        if src and tgt:
            outgoing.setdefault(src, []).append(tgt)

    incoming_ids = {
        e.get("target") for e in edges
        if isinstance(e, dict) and e.get("target")
    }
    entries = [
        n for n in nodes
        if isinstance(n, dict) and n.get("id") and n.get("id") not in incoming_ids
    ]
    if not entries:
        for n in nodes:
            if isinstance(n, dict) and n.get("type") in _AGENT_NODE_TYPES:
                return n
        return None

    visited: set = set()
    queue = [entries[0]]
    while queue:
        current = queue.pop(0)
        if not isinstance(current, dict):
            continue
        nid = current.get("id")
        if not nid or nid in visited:
            continue
        visited.add(nid)
        if current.get("type") in _AGENT_NODE_TYPES:
            return current
        for nxt_id in outgoing.get(nid, []):
            nxt = nodes_by_id.get(nxt_id)
            if nxt:
                queue.append(nxt)

    for n in nodes:
        if isinstance(n, dict) and n.get("type") in _AGENT_NODE_TYPES:
            return n
    return None
