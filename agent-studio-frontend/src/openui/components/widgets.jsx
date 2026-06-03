import { useEffect, useMemo } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  Panel,
  getBezierPath,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import { defineComponent } from '@openuidev/react-lang';
import { z } from 'zod/v4';

function stringifyValue(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'object' ? stringifyValue(item) : String(item)))
      .filter(Boolean)
      .join(', ');
  }
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${stringifyValue(item)}`)
      .join('; ');
  }
  return String(value);
}

const TreeNodeSchema = z
  .object({
    name: z.string().optional(),
    title: z.string().optional(),
    label: z.string().optional(),
    role: z.string().optional(),
    department: z.string().optional(),
    children: z.array(z.any()).optional(),
    attributes: z.record(z.string(), z.any()).optional(),
  })
  .catchall(z.any());

// ── Org-chart palette (PwC / Strategy& red, dark canvas) ──
const ORG_CANVAS = '#1b1b1b';
const ORG_DOT = 'rgba(217, 56, 84, 0.10)';

// Header tone shaded by depth: root darkest, lighter as it descends.
function depthHeader(depth) {
  if (depth <= 0) return { bg: '#7A1818', text: '#FFFFFF' };
  if (depth === 1) return { bg: '#A32020', text: '#FFFFFF' };
  if (depth === 2) return { bg: '#BB2740', text: '#FFFFFF' };
  return { bg: '#F8DDE1', text: '#1F2937' };
}

function normalizeTreeInput(data) {
  if (!data || typeof data !== 'object') return null;
  if (Array.isArray(data.companies) && data.companies[0]?.root_node) {
    return normalizeTreeNode(data.companies[0].root_node);
  }
  if (data.root_node) return normalizeTreeNode(data.root_node);
  return normalizeTreeNode(data);
}

function normalizeTreeNode(node) {
  if (!node || typeof node !== 'object') return null;

  const name = node.name ?? node.title ?? node.label ?? 'Node';
  const role = node.role ?? node.type ?? node.department ?? '';

  // Surface remaining scalar-ish fields as labelled attributes.
  const skipped = new Set([
    'name', 'title', 'label', 'children', 'attributes', 'role', 'type', 'department',
  ]);
  const attrSource = { ...(typeof node.attributes === 'object' && !Array.isArray(node.attributes) ? node.attributes : {}) };
  for (const [key, value] of Object.entries(node)) {
    if (!skipped.has(key) && value !== undefined && value !== null && value !== '') {
      attrSource[key] = value;
    }
  }
  const attributes = Object.entries(attrSource)
    .map(([key, value]) => ({ key: key.replace(/_/g, ' '), value: stringifyValue(value) }))
    .filter((item) => item.value);

  const children = Array.isArray(node.children)
    ? node.children.map(normalizeTreeNode).filter(Boolean)
    : [];

  return { name, role, attributes, children };
}

// Estimate a node box so dagre can lay out without overlap. Width is bounded;
// height grows with the (clamped) role text and a few attribute rows.
const ORG_NODE_WIDTH = 300;

function estimateNodeHeight(node) {
  const charsPerLine = (ORG_NODE_WIDTH - 28) / 6.6;
  const roleLines = node.role ? Math.min(3, Math.ceil(node.role.length / charsPerLine)) : 0;
  const attrCount = Math.min(node.attributes?.length ?? 0, 3);
  return 44 + (roleLines ? roleLines * 16 + 8 : 0) + (attrCount ? attrCount * 17 + 8 : 0);
}

// Curved gradient edge between org boxes.
function TurboEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd }) {
  const [edgePath] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });
  return (
    <path
      id={id}
      className="react-flow__edge-path"
      d={edgePath}
      markerEnd={markerEnd}
      fill="none"
      stroke="url(#org-edge-gradient)"
      strokeWidth={2.5}
      strokeOpacity={0.95}
    />
  );
}

// Gradient-bordered org node card with depth-shaded header.
function OrgNode({ data }) {
  const header = depthHeader(data.depth);
  const hasChildren = (data.childCount || 0) > 0;

  return (
    <div className="rounded-[12px]" style={{ width: ORG_NODE_WIDTH, boxShadow: '0 6px 18px rgba(0,0,0,0.45)' }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div
        className="overflow-hidden rounded-[12px]"
        style={{
          background: 'conic-gradient(from -160deg at 50% 50%, #A32020 0deg, #BA2741 120deg, #DB536A 240deg, #A32020 360deg)',
          padding: 2,
        }}
      >
        <div className="rounded-[10px]" style={{ background: '#262626' }}>
          <div
            className="flex items-center justify-between gap-2 rounded-t-[10px] px-3 py-2"
            style={{ background: header.bg }}
          >
            <div className="text-[13px] font-semibold leading-snug" style={{ color: header.text }}>
              {data.name}
            </div>
            {hasChildren ? (
              <span
                className="flex-none rounded-full px-2 py-0.5 text-[10px] font-medium"
                style={{ background: 'rgba(0,0,0,0.22)', color: header.text }}
              >
                {data.childCount}
              </span>
            ) : null}
          </div>

          {(data.role || (data.attributes && data.attributes.length)) ? (
            <div className="px-3 py-2">
              {data.role ? (
                <div
                  className="text-[11px] leading-snug text-white/75"
                  style={{ display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                >
                  {data.role}
                </div>
              ) : null}
              {data.attributes && data.attributes.length ? (
                <div className="mt-1.5 space-y-1">
                  {data.attributes.slice(0, 3).map((attr) => (
                    <div key={attr.key} className="flex gap-1.5 text-[10px] leading-snug">
                      <span className="font-semibold uppercase tracking-wide text-[#f1b8c2]">{attr.key}:</span>
                      <span className="text-white/70">{attr.value}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const orgNodeTypes = { org: OrgNode };
const orgEdgeTypes = { turbo: TurboEdge };

// Flatten the normalized tree into ReactFlow nodes/edges.
function treeToElements(root) {
  const nodes = [];
  const edges = [];

  const walk = (node, parentId, path) => {
    const id = path.join('.') || 'root';
    const depth = path.length;
    nodes.push({
      id,
      type: 'org',
      data: {
        name: node.name,
        role: node.role,
        attributes: node.attributes,
        depth,
        childCount: (node.children || []).length,
      },
      position: { x: 0, y: 0 },
      width: ORG_NODE_WIDTH,
      height: estimateNodeHeight(node),
    });
    if (parentId) {
      edges.push({
        id: `${parentId}->${id}`,
        source: parentId,
        target: id,
        type: 'turbo',
        animated: true,
        markerEnd: 'org-edge-circle',
      });
    }
    (node.children || []).forEach((child, i) => walk(child, id, [...path, i]));
  };

  walk(root, null, []);
  return { nodes, edges };
}

// Hierarchical top-down dagre layout.
function applyOrgLayout(nodes, edges) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: 36, ranksep: 70 });
  g.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((n) => g.setNode(n.id, { width: n.width, height: n.height }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - n.width / 2, y: pos.y - n.height / 2 } };
  });
}

function OrgChartCanvas({ data }) {
  const { laidOutNodes, builtEdges } = useMemo(() => {
    const root = normalizeTreeInput(data);
    if (!root) return { laidOutNodes: [], builtEdges: [] };
    const { nodes, edges } = treeToElements(root);
    return { laidOutNodes: applyOrgLayout(nodes, edges), builtEdges: edges };
  }, [data]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidOutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(builtEdges);

  // Re-seed when the deliverable swaps without a full remount.
  useEffect(() => {
    setNodes(laidOutNodes);
    setEdges(builtEdges);
  }, [laidOutNodes, builtEdges, setNodes, setEdges]);

  if (!nodes.length) {
    return (
      <div className="rounded-xl border border-white/10 bg-white/[0.04] p-4 text-sm text-white/60">
        No hierarchy data available.
      </div>
    );
  }

  return (
    <ReactFlow
      className="agent-org-chart"
      nodes={nodes}
      edges={edges}
      nodeTypes={orgNodeTypes}
      edgeTypes={orgEdgeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      fitView
      fitViewOptions={{ padding: 0.18 }}
      minZoom={0.2}
      maxZoom={1.75}
      nodesDraggable
      nodesConnectable={false}
      elementsSelectable={false}
      zoomOnScroll={false}
      panOnScroll={false}
      preventScrolling={false}
      proOptions={{ hideAttribution: true }}
      style={{ background: ORG_CANVAS }}
    >
      <Background gap={20} size={1} color={ORG_DOT} />
      <Controls showInteractive={false} position="bottom-right" />
      <Panel position="top-left">
        <div className="rounded-md px-2.5 py-1 text-[11px] font-medium text-white/70" style={{ background: 'rgba(70,70,70,0.7)' }}>
          Drag to pan, use controls to zoom
        </div>
      </Panel>
      <svg width="0" height="0" style={{ position: 'absolute' }}>
        <defs>
          <linearGradient id="org-edge-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#A32020" />
            <stop offset="100%" stopColor="#DB536A" />
          </linearGradient>
          <marker
            id="org-edge-circle"
            viewBox="-5 -5 10 10"
            refX="0"
            refY="0"
            markerUnits="strokeWidth"
            markerWidth="9"
            markerHeight="9"
            orient="auto"
          >
            <circle stroke="#DB536A" strokeOpacity="0.85" fill="#BA2741" r="2" cx="0" cy="0" />
          </marker>
        </defs>
      </svg>
    </ReactFlow>
  );
}

const TreeView = defineComponent({
  name: 'TreeView',
  description:
    'A native top-down org-chart visualization. Use for org charts, operating models, reporting lines, and any parent-child hierarchy. The full hierarchy is laid out automatically and is pan/zoomable.',
  props: z.object({
    data: TreeNodeSchema.describe('Root tree node with optional nested children'),
    title: z.string().optional().describe('Optional tree title'),
  }),
  component: ({ props }) => (
    <div className="my-3 overflow-hidden rounded-2xl border border-white/10 bg-[#151515]">
      {props.title ? (
        <div className="border-b border-white/10 px-4 py-2.5 text-sm font-semibold uppercase tracking-wide text-white/55">
          {props.title}
        </div>
      ) : null}
      <div style={{ height: 'min(70vh, 560px)', minHeight: 380, width: '100%' }}>
        <ReactFlowProvider>
          <OrgChartCanvas data={props.data} />
        </ReactFlowProvider>
      </div>
    </div>
  ),
});

const Slide = defineComponent({
  name: 'Slide',
  description:
    'A native presentation-style card. Use for slide-like summaries with a title, subtitle, bullets, or body text.',
  props: z.object({
    title: z.string().describe('Slide title'),
    bullets: z.array(z.string()).optional().describe('Bullet list content'),
    body: z.string().optional().describe('Body paragraph alternative to bullets'),
    subtitle: z.string().optional().describe('Optional subtitle'),
    layout: z.enum(['title-content', 'title-only', 'two-column']).optional().describe('Slide layout hint'),
  }),
  component: ({ props }) => (
    <div className="my-3 aspect-video rounded-2xl border border-white/10 bg-gradient-to-br from-[#2a2a2a] to-[#111] p-6 shadow-xl">
      {props.subtitle ? (
        <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-[#ef6b80]">
          {props.subtitle}
        </div>
      ) : null}
      <h3 className="max-w-3xl text-2xl font-bold leading-tight text-white">{props.title}</h3>
      {props.body ? <p className="mt-4 max-w-3xl text-sm leading-relaxed text-white/75">{props.body}</p> : null}
      {props.bullets?.length ? (
        <ul className="mt-5 grid gap-2 text-sm text-white/80">
          {props.bullets.map((bullet, index) => (
            <li key={index} className="flex gap-2">
              <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-[#d93854]" />
              <span>{bullet}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  ),
});

const QueryTrace = defineComponent({
  name: 'QueryTrace',
  description:
    'A native collapsible trace of structured queries or tool calls used to produce the deliverable.',
  props: z.object({
    queries: z
      .array(
        z.object({
          name: z.string(),
          query: z.string().optional(),
          result: z.any().optional(),
        }),
      )
      .describe('List of query traces to display'),
  }),
  component: ({ props }) => (
    <div className="my-3 space-y-2">
      {(props.queries ?? []).map((query, index) => (
        <details key={`${query.name}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
          <summary className="cursor-pointer text-sm font-semibold text-white">
            {query.name}
          </summary>
          {query.query ? (
            <pre className="mt-3 overflow-x-auto rounded-lg bg-black/30 p-3 text-xs text-white/80">
              <code>{query.query}</code>
            </pre>
          ) : null}
          {query.result !== undefined ? (
            <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-black/20 p-3 text-xs text-white/70">
              {JSON.stringify(query.result, null, 2)}
            </pre>
          ) : null}
        </details>
      ))}
    </div>
  ),
});

export {
  TreeView,
  Slide,
  QueryTrace,
};
