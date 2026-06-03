/**
 * ProcessFlowchart — interactive directed-graph renderer for governance
 * process flows.  Uses ReactFlow + dagre.
 *
 * Supports two layout modes:
 *  1. **Position-based** (v3) — nodes carry normalised {x,y,width,height}
 *     and swimlanes carry {y_start,y_end} bounds.  Layout is pixel-accurate
 *     to the original BPMN diagram.
 *  2. **Auto-layout** (legacy) — dagre computes positions when no coords
 *     are present.
 *
 * Node shapes: rectangle, diamond, rounded_rectangle, comment_box
 * Swimlanes:   horizontal bands with a left-side label column
 */

import React, { useMemo, useState, useEffect } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  BaseEdge,
  getBezierPath,
  getSmoothStepPath,
  EdgeLabelRenderer,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';

// ── Colour palettes ──────────────────────────────────────────────────

const NODE_STYLES = {
  start:    { bg: '#dcfce7', border: '#16a34a', text: '#14532d', badge: '#bbf7d0' },
  action:   { bg: '#dbeafe', border: '#2563eb', text: '#1e3a8a', badge: '#bfdbfe' },
  decision: { bg: '#fef3c7', border: '#d97706', text: '#78350f', badge: '#fde68a' },
  end:      { bg: '#fee2e2', border: '#dc2626', text: '#7f1d1d', badge: '#fecaca' },
};
const DEFAULT_STYLE = { bg: '#f3f4f6', border: '#6b7280', text: '#1f2937', badge: '#e5e7eb' };

const EDGE_COLORS = {
  approval:    '#16a34a',
  rejection:   '#dc2626',
  escalation:  '#d97706',
  conditional: '#7c3aed',
  sequence:    '#6b7280',
};

const LANE_COLORS = [
  'rgba(241,245,249,0.7)', 'rgba(248,250,252,0.7)',
];

const CANVAS_W = 1800;
const CANVAS_H = 3200;
const LANE_LABEL_W = 110;

// ── Shape helpers ────────────────────────────────────────────────────

function nodeSize(node, shape) {
  if (node.position?.width && node.position?.height) {
    return {
      w: Math.max(node.position.width * CANVAS_W, 140),
      h: Math.max(node.position.height * CANVAS_H, 50),
    };
  }
  if (shape === 'diamond') return { w: 140, h: 100 };
  if (shape === 'comment_box') return { w: 320, h: 100 };
  return { w: 200, h: 70 };
}

// ── Custom Nodes ─────────────────────────────────────────────────────

function RectangleNode({ data }) {
  const s = NODE_STYLES[data.nodeType] || DEFAULT_STYLE;
  const [open, setOpen] = useState(false);
  return (
    <div
      className="shadow-sm overflow-hidden"
      style={{ border: `2px solid ${s.border}`, background: '#fff', borderRadius: 4, width: '100%', height: '100%' }}
    >
      <div className="px-2 py-1.5 cursor-pointer select-none h-full flex flex-col justify-center" style={{ background: s.bg }} onClick={() => setOpen(o => !o)}>
        <span className="text-[10px] font-semibold leading-tight block" style={{ color: s.text }}>{data.label}</span>
        {data.actor && <span className="text-[8px] text-gray-500 mt-0.5 block truncate">{data.actor}</span>}
      </div>
      {open && data.description && (
        <div className="absolute left-0 top-full z-50 mt-1 w-72 p-2 bg-white border border-gray-200 rounded shadow-lg text-[10px] text-gray-600 leading-relaxed">
          {data.description}
        </div>
      )}
      <Handle type="target" position={Position.Top}    style={{ background: s.border, width: 6, height: 6 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: s.border, width: 6, height: 6 }} />
      <Handle type="target" position={Position.Left}   id="left-t"  style={{ background: s.border, width: 6, height: 6 }} />
      <Handle type="source" position={Position.Right}  id="right-s" style={{ background: s.border, width: 6, height: 6 }} />
    </div>
  );
}

function RoundedRectNode({ data }) {
  const s = NODE_STYLES[data.nodeType] || DEFAULT_STYLE;
  const [open, setOpen] = useState(false);
  return (
    <div
      className="shadow-sm overflow-hidden"
      style={{ border: `2px solid ${s.border}`, background: '#fff', borderRadius: 14, width: '100%', height: '100%' }}
    >
      <div className="px-2 py-1.5 cursor-pointer select-none h-full flex flex-col justify-center" style={{ background: s.bg, borderRadius: 12 }} onClick={() => setOpen(o => !o)}>
        <span className="text-[10px] font-semibold leading-tight block text-center" style={{ color: s.text }}>{data.label}</span>
        {data.actor && <span className="text-[8px] text-gray-500 mt-0.5 block truncate text-center">{data.actor}</span>}
      </div>
      {open && data.description && (
        <div className="absolute left-0 top-full z-50 mt-1 w-64 p-2 bg-white border border-gray-200 rounded shadow-lg text-[10px] text-gray-600 leading-relaxed">
          {data.description}
        </div>
      )}
      <Handle type="target" position={Position.Top}    style={{ background: s.border, width: 6, height: 6 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: s.border, width: 6, height: 6 }} />
      <Handle type="target" position={Position.Left}   id="left-t"  style={{ background: s.border, width: 6, height: 6 }} />
      <Handle type="source" position={Position.Right}  id="right-s" style={{ background: s.border, width: 6, height: 6 }} />
    </div>
  );
}

function DiamondNode({ data }) {
  const s = NODE_STYLES.decision;
  const [open, setOpen] = useState(false);
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <div
        className="cursor-pointer select-none"
        onClick={() => setOpen(o => !o)}
        style={{
          position: 'absolute', inset: 0,
          background: s.bg, border: `2px solid ${s.border}`,
          clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        <span className="text-[9px] font-semibold leading-tight text-center px-4" style={{ color: s.text }}>
          {data.label}
        </span>
      </div>
      {open && data.description && (
        <div className="absolute left-full top-0 z-50 ml-2 w-64 p-2 bg-white border border-gray-200 rounded shadow-lg text-[10px] text-gray-600 leading-relaxed">
          {data.description}
        </div>
      )}
      <Handle type="target" position={Position.Top}    style={{ background: s.border, width: 6, height: 6, left: '50%' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: s.border, width: 6, height: 6, left: '50%' }} />
      <Handle type="source" position={Position.Right}  id="right-s" style={{ background: s.border, width: 6, height: 6, top: '50%' }} />
      <Handle type="source" position={Position.Left}   id="left-s"  style={{ background: s.border, width: 6, height: 6, top: '50%' }} />
    </div>
  );
}

function CommentBoxNode({ data }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="cursor-pointer select-none"
      onClick={() => setOpen(o => !o)}
      style={{
        width: '100%', height: '100%',
        border: '1.5px dashed #94a3b8', borderRadius: 3,
        background: '#fffde7', padding: '6px 8px',
        overflow: 'hidden', position: 'relative',
      }}
    >
      <div className="text-[9px] leading-snug text-gray-600" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {data.description || data.label}
      </div>
      {open && data.description && (
        <div className="absolute left-0 top-full z-50 mt-1 w-80 p-2 bg-white border border-gray-200 rounded shadow-lg text-[10px] text-gray-600 leading-relaxed max-h-60 overflow-y-auto">
          {data.description}
        </div>
      )}
      <Handle type="target" position={Position.Left} id="left-t" style={{ background: '#94a3b8', width: 5, height: 5 }} />
    </div>
  );
}

const nodeTypes = {
  rectangleNode:     RectangleNode,
  roundedRectNode:   RoundedRectNode,
  diamondNode:       DiamondNode,
  commentBoxNode:    CommentBoxNode,
};

const SHAPE_TO_TYPE = {
  rectangle:         'rectangleNode',
  rounded_rectangle: 'roundedRectNode',
  diamond:           'diamondNode',
  comment_box:       'commentBoxNode',
};

// ── Custom Edge ──────────────────────────────────────────────────────

function FlowchartEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, style }) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
    borderRadius: 8,
  });

  const color = EDGE_COLORS[data?.edgeType] || '#6b7280';

  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={{ ...style, stroke: color, strokeWidth: 1.5 }} />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'none',
              background: '#fff', border: `1px solid ${color}`,
              borderRadius: 3, padding: '0px 5px',
              fontSize: 9, fontWeight: 600, color,
              whiteSpace: 'nowrap', lineHeight: '16px',
            }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes = { flowchartEdge: FlowchartEdge };

// ── Detect if v3 positions exist ─────────────────────────────────────

function hasPositions(graphData) {
  return graphData?.nodes?.some(n => n.position?.x != null && n.position?.y != null);
}

// ── Build elements WITH positions (v3) ───────────────────────────────

function toPositionedElements(graphData) {
  const swimlanes = graphData.swimlanes || [];

  // Swimlane background nodes (non-interactive)
  const laneNodes = swimlanes.map((lane, i) => {
    const yPx = (lane.bounds?.y_start ?? 0) * CANVAS_H;
    const hPx = ((lane.bounds?.y_end ?? 0) - (lane.bounds?.y_start ?? 0)) * CANVAS_H;
    return {
      id: `lane-${i}`,
      type: 'group',
      position: { x: 0, y: yPx },
      style: {
        width: CANVAS_W + LANE_LABEL_W,
        height: hPx,
        background: LANE_COLORS[i % 2],
        borderTop: '1px solid #cbd5e1',
        borderBottom: i === swimlanes.length - 1 ? '1px solid #cbd5e1' : 'none',
        borderRadius: 0,
        pointerEvents: 'none',
        zIndex: -2,
      },
      data: { label: '' },
      selectable: false,
      draggable: false,
    };
  });

  // Swimlane label nodes
  const labelNodes = swimlanes.map((lane, i) => {
    const yPx = (lane.bounds?.y_start ?? 0) * CANVAS_H;
    const hPx = ((lane.bounds?.y_end ?? 0) - (lane.bounds?.y_start ?? 0)) * CANVAS_H;
    return {
      id: `lane-label-${i}`,
      type: 'default',
      position: { x: 2, y: yPx + 2 },
      style: {
        width: LANE_LABEL_W - 4,
        height: hPx - 4,
        background: 'rgba(255,255,255,0.85)',
        border: '1px solid #e2e8f0',
        borderRadius: 4,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 10,
        fontWeight: 600,
        color: '#475569',
        textAlign: 'center',
        lineHeight: '1.2',
        padding: '4px 6px',
        pointerEvents: 'none',
        zIndex: -1,
        writingMode: 'vertical-rl',
        textOrientation: 'mixed',
        transform: 'rotate(180deg)',
      },
      data: { label: lane.name || lane.actor_role },
      selectable: false,
      draggable: false,
    };
  });

  // Process nodes
  const processNodes = (graphData.nodes || []).map(n => {
    const shape = n.shape || (n.type === 'decision' ? 'diamond' : n.type === 'start' || n.type === 'end' ? 'rounded_rectangle' : 'rectangle');
    const rfType = SHAPE_TO_TYPE[shape] || 'rectangleNode';
    const { w, h } = nodeSize(n, shape);

    const cx = (n.position?.x ?? 0.5) * CANVAS_W + LANE_LABEL_W;
    const cy = (n.position?.y ?? 0.5) * CANVAS_H;

    return {
      id: n.id,
      type: rfType,
      position: { x: cx - w / 2, y: cy - h / 2 },
      style: { width: w, height: h },
      data: {
        label: n.label,
        nodeType: n.type || 'action',
        actor: n.actor,
        description: n.description,
        shape,
      },
    };
  });

  // Edges
  const edges = (graphData.edges || []).map((e, i) => ({
    id: `e-${e.from_node}-${e.to_node}-${i}`,
    source: e.from_node,
    target: e.to_node,
    type: 'flowchartEdge',
    data: { label: e.label || e.condition || null, edgeType: e.type || 'sequence' },
    markerEnd: { type: 'arrowclosed', color: EDGE_COLORS[e.type] || '#6b7280' },
    animated: e.type === 'rejection',
  }));

  return { nodes: [...laneNodes, ...labelNodes, ...processNodes], edges };
}

// ── Build elements WITHOUT positions (dagre fallback) ────────────────

function toDagreElements(graphData) {
  const nodes = (graphData?.nodes || []).map(n => {
    const shape = n.shape || (n.type === 'decision' ? 'diamond' : n.type === 'start' || n.type === 'end' ? 'rounded_rectangle' : 'rectangle');
    const rfType = SHAPE_TO_TYPE[shape] || 'rectangleNode';
    return {
      id: n.id,
      type: rfType,
      data: { label: n.label, nodeType: n.type || 'action', actor: n.actor, description: n.description, shape },
      position: { x: 0, y: 0 },
      style: { width: 220, height: 70 },
    };
  });

  const edges = (graphData?.edges || []).map((e, i) => ({
    id: `e-${e.from_node}-${e.to_node}-${i}`,
    source: e.from_node,
    target: e.to_node,
    type: 'flowchartEdge',
    data: { label: e.label || e.condition || null, edgeType: e.type || 'sequence' },
    markerEnd: { type: 'arrowclosed', color: EDGE_COLORS[e.type] || '#6b7280' },
    animated: e.type === 'rejection',
  }));

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 90, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach(n => g.setNode(n.id, { width: 220, height: 70 }));
  edges.forEach(e => g.setEdge(e.source, e.target));
  dagre.layout(g);

  const laidOut = nodes.map(n => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 110, y: pos.y - 35 } };
  });

  return { nodes: laidOut, edges };
}

// ── Main Component ───────────────────────────────────────────────────

export default function ProcessFlowchart({ graph, height = 600 }) {
  const [fullscreen, setFullscreen] = useState(false);

  const positioned = useMemo(() => hasPositions(graph), [graph]);

  const { initialNodes, initialEdges } = useMemo(() => {
    const { nodes, edges } = positioned ? toPositionedElements(graph) : toDagreElements(graph);
    return { initialNodes: nodes, initialEdges: edges };
  }, [graph, positioned]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e) => { if (e.key === 'Escape') setFullscreen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [fullscreen]);

  const nodeCount = (graph?.nodes || []).length;
  const edgeCount = (graph?.edges || []).length;
  const laneCount = (graph?.swimlanes || []).length;

  const wrapperClass = fullscreen ? 'fixed inset-0 z-[9999] bg-white' : 'rounded-lg overflow-hidden border border-gray-200';
  const wrapperHeight = fullscreen ? '100vh' : height;

  return (
    <div style={{ width: '100%', height: wrapperHeight }} className={wrapperClass}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        key={fullscreen ? 'fs' : 'inline'}
        minZoom={0.05}
        maxZoom={2.5}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
        style={{ background: '#f8fafc' }}
      >
        <Background gap={20} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} />

        <Panel position="top-left">
          <div className="text-xs font-medium px-2.5 py-1.5 rounded bg-white/90 backdrop-blur border border-gray-200 text-gray-600">
            {nodeCount} nodes &middot; {edgeCount} edges
            {laneCount > 0 && <> &middot; {laneCount} swimlanes</>}
            &nbsp;&mdash; click a node to expand
          </div>
        </Panel>

        <Panel position="top-right">
          <button
            type="button"
            onClick={() => setFullscreen(f => !f)}
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded bg-white/90 backdrop-blur border border-gray-200 text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors cursor-pointer"
          >
            {fullscreen ? (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
                Exit fullscreen
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
                </svg>
                Fullscreen
              </>
            )}
          </button>
        </Panel>
      </ReactFlow>
    </div>
  );
}
