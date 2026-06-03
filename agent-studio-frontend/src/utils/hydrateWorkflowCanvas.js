import { APP_DATA } from '@/data/appData';
import { ensureDefaultChatNode } from '@/utils/ensureDefaultChatNode';

/** Parse nodes/connections whether the API returned a JSON string or an already-parsed value. */
export function parseWorkflowJsonField(value, fallback = []) {
  if (value == null || value === '') return fallback;
  if (Array.isArray(value)) return value;
  if (typeof value === 'object') return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : fallback;
    } catch {
      return fallback;
    }
  }
  return fallback;
}

/**
 * Parse workflow_entity nodes/connections JSON into canvas LOAD_TEMPLATE payload.
 */
export function buildCanvasPayloadFromWorkflow(workflow) {
  const nodesData = parseWorkflowJsonField(workflow.nodes, []);
  const edgesData = parseWorkflowJsonField(workflow.connections, []);

  const nodes = nodesData.map((node) => {
    const nodeType = node.type || node.data?.config?.type || node.config?.kind;
    const nodeConfig = {
      ...(node.config || {}),
      ...(node.data?.config || {}),
      label: node.data?.label || node.config?.label || node.label,
    };

    const nodeTypeDef = APP_DATA.nodeTypes
      .flatMap((cat) => cat.nodes)
      .find((n) => n.id === nodeType);

    return {
      id: node.id,
      type: nodeType || 'custom',
      x: node.position?.x || node.x || 0,
      y: node.position?.y || node.y || 0,
      config: nodeConfig,
      nodeType: nodeTypeDef || {
        id: nodeType,
        name: nodeConfig.label || 'Unknown',
        icon: '📦',
        color: '#6B7280',
        description: 'Imported node',
      },
    };
  });

  const connections = (edgesData || []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle || null,
    targetHandle: edge.targetHandle || null,
    conditionId: edge.conditionId || null,
  }));

  const ensured = ensureDefaultChatNode(nodes, connections);

  return {
    id: workflow.id,
    name: workflow.name,
    nodes: ensured.nodes,
    connections: ensured.connections,
  };
}
