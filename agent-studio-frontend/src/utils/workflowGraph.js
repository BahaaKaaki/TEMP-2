/**
 * Build workflow nodes/connections JSON from builder canvas state.
 * Used so test chat and selectedWorkflow stay aligned with the live canvas.
 */
export function buildWorkflowGraphFromCanvas(canvasNodes, connections) {
  const nodesArray = Array.from(canvasNodes.entries()).map(([id, node]) => ({
    id,
    type: node.type,
    position: { x: node.x, y: node.y },
    data: {
      label: node.config?.label || node.nodeType?.name || 'Node',
      config: node.config,
    },
    config: node.config,
  }));

  const edgesArray = (connections || []).map((conn) => ({
    id: conn.id,
    source: conn.source,
    target: conn.target,
    sourceHandle: conn.sourceHandle || null,
    targetHandle: conn.targetHandle || null,
    conditionId: conn.conditionId || null,
  }));

  return {
    nodes: JSON.stringify(nodesArray),
    connections: JSON.stringify(edgesArray),
  };
}
