/**
 * Resolve knowledge bases attached to a workflow node (agent, code runner, etc.).
 */

export function getNodeKnowledgeBaseIds(node) {
  if (!node) return [];
  const cfg = node.data?.config || node.config || {};
  if (cfg.knowledgeBase === false) return [];

  const ids = cfg.knowledgeBaseId || cfg.knowledgeBaseIds || cfg.knowledge_base_id;
  if (Array.isArray(ids)) return ids.filter(Boolean).map(String);
  if (ids) return [String(ids)];
  return [];
}

/**
 * @returns {Map<string, string[]>} node id → display names (sorted)
 */
export function buildAgentKbNamesByNodeId(nodes, kbAssets) {
  const map = new Map();
  const assetsById = new Map(
    (kbAssets || []).map((kb) => [String(kb.kb_id), kb.kb_name || 'Knowledge base']),
  );

  for (const node of nodes || []) {
    const ids = getNodeKnowledgeBaseIds(node);
    if (!ids.length) continue;

    const names = ids
      .map((id) => assetsById.get(String(id)))
      .filter(Boolean);

    if (names.length > 0) {
      map.set(node.id, [...new Set(names)].sort((a, b) => a.localeCompare(b)));
    } else {
      map.set(
        node.id,
        ids.map((id) => `Knowledge base (${String(id).slice(0, 8)}…)`),
      );
    }
  }

  return map;
}
