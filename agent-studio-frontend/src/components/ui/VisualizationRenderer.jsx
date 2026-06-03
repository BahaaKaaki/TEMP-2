/**
 * VisualizationRenderer — generic recursive renderer for the visualization DSL.
 *
 * Walks a list of component specs (each with a `type` key) and renders
 * the corresponding React component.  Container types (`accordion`,
 * `tabs`, `grid`, `card`) nest child specs recursively.
 *
 * Special type "render" evaluates a user-supplied JavaScript function
 * body that receives `data` and `React` and returns a React element,
 * wrapped in an ErrorBoundary for safety.
 */

import React, { useState, useMemo, useRef, lazy, Suspense, Component } from 'react';
import * as Recharts from 'recharts';
import AIChart from './AIChart';

const ProcessFlowchart = lazy(() => import('./ProcessFlowchart'));

// ─── ErrorBoundary for JS render functions ───────────────────────────
//
// Why the reset-key dance:
//
// Before, this boundary latched `error` forever once it caught anything.
// That's a problem for transient failures — most commonly the
// "Maximum update depth exceeded" infinite-loop error triggered when
// the deliverables pane is resized (see the CustomRender comment below).
// After React recovers (e.g. the user refreshes the deliverable, or
// the script/data props change), we want the subtree to re-mount and
// try again rather than leaving a red box stuck on screen.
//
// The `resetKey` prop is a string that callers bump whenever they want
// the boundary to give the tree another chance.  CustomRender wires it
// up to `spec.script` + a structural signature of `data`, so the next
// legitimate spec/data change clears a previous error automatically.
class RenderErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      // A new attempt is worth it: the script or data changed, so the
      // previous error may no longer apply.  React will unmount+remount
      // the children by the normal reconciliation path when we clear
      // state here.
      // eslint-disable-next-line react/no-did-update-set-state
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm">
          <p className="font-semibold text-red-700">Render function error</p>
          <pre className="mt-1 text-xs text-red-600 whitespace-pre-wrap">
            {this.state.error.message || String(this.state.error)}
          </pre>
          <p className="mt-2 text-[11px] text-red-500/80">
            The next edit to this visualization will retry automatically.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

// ─── JS render function evaluator ────────────────────────────────────
// The script is evaluated with a rich scope:
//   data     -- the payload passed to output.data()
//   React    -- the React module (hooks, createElement, Fragment)
//   Recharts -- the Recharts library (BarChart, LineChart, PieChart, etc.)
//
// The script must return a React element.  To use hooks (useState, etc.)
// define a component inside the script and return React.createElement(Component).
//
// IMPORTANT — the re-mount / update-depth bug this component avoids:
//
// Upstream, `CodeExecutorOutput` produces a FRESH `data` object every
// time it renders (via `stripInternal(rawPayload)`).  A naive
// `useMemo([spec.script, data])` would therefore bust on every parent
// render — even when the data's *values* haven't changed.  On each bust
// we'd call `new Function(spec.script)` again, producing a fresh
// function that, when it internally declares any `function MyChart(...)`
// components, yields fresh component identities every time.  React sees
// "new component type" and remounts the subtree, which re-fires every
// `useEffect` inside the AI-authored script.  If any of those effects
// call `setState` (a very common pattern for measuring or deriving
// state), that setState triggers another parent render → new `data`
// reference → memo busts again → remount → setState → loop.
//
// We break that chain by gating on the *structural* signature of data
// (a best-effort JSON stringify — falls back to the raw reference when
// the payload contains cycles).  Expanding/collapsing the deliverables
// pane changes container width but NOT data values, so the signature is
// stable and the script/tree are preserved across resize events.
function CustomRender({ spec, data }) {
  // A cheap stable signature for `data`.  JSON.stringify is O(n) on the
  // payload size, which is acceptable here because deliverables are
  // typically small-to-medium structured outputs — not streaming frames.
  const dataSig = useMemo(() => {
    try {
      return JSON.stringify(data);
    } catch {
      // Circular refs, BigInts, etc. fall back to referential identity.
      return null;
    }
  }, [data]);

  // Latest data is always readable via the ref even when the memo is
  // intentionally preserved across reference-only changes.  Scripts
  // that want to read data at runtime get the freshest copy.
  const latestDataRef = useRef(data);
  latestDataRef.current = data;

  const element = useMemo(() => {
    try {
      // eslint-disable-next-line no-new-func
      const fn = new Function('data', 'React', 'Recharts', spec.script);
      return fn(latestDataRef.current, React, Recharts);
    } catch (err) {
      return (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm">
          <p className="font-semibold text-red-700">Script evaluation error</p>
          <pre className="mt-1 text-xs text-red-600 whitespace-pre-wrap">
            {err.message || String(err)}
          </pre>
        </div>
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec.script, dataSig]);

  return (
    <RenderErrorBoundary resetKey={`${spec.script}:${dataSig}`}>
      {element}
    </RenderErrorBoundary>
  );
}

// ─── DSL Primitives ──────────────────────────────────────────────────

function HeaderPrimitive({ spec }) {
  const badges = spec.badges || {};
  const entries = Object.entries(badges).filter(([, v]) => v);
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-5 py-4">
      {spec.title && <h2 className="text-lg font-bold text-gray-900">{spec.title}</h2>}
      {spec.subtitle && <p className="text-sm text-gray-500 mt-0.5">{spec.subtitle}</p>}
      {entries.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-2">
          {entries.map(([k, v]) => (
            <span
              key={k}
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 border border-gray-200"
            >
              <span className="font-medium text-gray-500">{k.replace(/_/g, ' ')}:</span>{' '}
              {String(v)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function TextPrimitive({ spec }) {
  const value = spec.value || spec.content || '';
  if (spec.format === 'markdown') {
    return (
      <div
        className="prose prose-sm max-w-none text-gray-700"
        dangerouslySetInnerHTML={{ __html: simpleMarkdown(value) }}
      />
    );
  }
  return <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{value}</p>;
}

function simpleMarkdown(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code class="bg-gray-100 px-1 rounded text-xs">$1</code>')
    .replace(/\n/g, '<br/>');
}

function TablePrimitive({ spec }) {
  const columns = spec.columns || [];
  const rows = spec.rows || [];
  const [sortCol, setSortCol] = useState(null);
  const [sortAsc, setSortAsc] = useState(true);

  const sorted = useMemo(() => {
    if (!sortCol) return rows;
    return [...rows].sort((a, b) => {
      const av = a[sortCol], bv = b[sortCol];
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'number' && typeof bv === 'number')
        return sortAsc ? av - bv : bv - av;
      return sortAsc
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }, [rows, sortCol, sortAsc]);

  const handleSort = (col) => {
    if (sortCol === col) setSortAsc(!sortAsc);
    else {
      setSortCol(col);
      setSortAsc(true);
    }
  };

  if (columns.length === 0) return null;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {spec.title && (
        <div className="px-4 py-2 bg-gray-50 border-b text-sm font-semibold text-gray-700">
          {spec.title}
        </div>
      )}
      <div className="overflow-x-auto max-h-96">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  className="px-3 py-2 text-left font-medium text-gray-600 cursor-pointer hover:bg-gray-100 select-none"
                  onClick={() => handleSort(col)}
                >
                  {col} {sortCol === col ? (sortAsc ? '\u25B2' : '\u25BC') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr key={i} className="border-t hover:bg-gray-50">
                {columns.map((col) => (
                  <td key={col} className="px-3 py-1.5 text-gray-800">
                    {typeof row[col] === 'object'
                      ? JSON.stringify(row[col])
                      : String(row[col] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-1.5 bg-gray-50 border-t text-xs text-gray-500">
        {rows.length} rows
      </div>
    </div>
  );
}

function ListPrimitive({ spec }) {
  const items = spec.items || [];
  const Tag = spec.ordered ? 'ol' : 'ul';
  const listClass = spec.ordered ? 'list-decimal' : 'list-disc';
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
      {spec.title && (
        <div className="text-sm font-semibold text-gray-700 mb-2">{spec.title}</div>
      )}
      <Tag className={`${listClass} list-inside space-y-1 text-sm text-gray-700`}>
        {items.map((item, i) => (
          <li key={i}>{typeof item === 'string' ? item : item.label || JSON.stringify(item)}</li>
        ))}
      </Tag>
    </div>
  );
}

function AccordionPrimitive({ spec, data }) {
  const sections = spec.sections || [];
  const [open, setOpen] = useState(() => new Set(sections.map((_, i) => i)));
  const toggle = (idx) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });

  return (
    <div className="space-y-2">
      {sections.map((sec, idx) => (
        <div key={idx} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <button
            type="button"
            onClick={() => toggle(idx)}
            className="w-full text-left px-4 py-3 flex items-center justify-between bg-gray-50 hover:bg-gray-100 transition-colors"
          >
            <span className="text-sm font-semibold text-gray-700">
              {sec.title || `Section ${idx + 1}`}
            </span>
            <svg
              className={`w-4 h-4 text-gray-400 transition-transform ${open.has(idx) ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>
          {open.has(idx) && (
            <div className="px-4 py-3">
              <ComponentList specs={sec.content || []} data={data} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function TabsPrimitive({ spec, data }) {
  const tabs = spec.tabs || [];
  const [active, setActive] = useState(0);
  if (tabs.length === 0) return null;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="flex border-b bg-gray-50 overflow-x-auto">
        {tabs.map((tab, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => setActive(idx)}
            className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
              active === idx
                ? 'text-indigo-600 border-b-2 border-indigo-600 bg-white'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
            }`}
          >
            {tab.label || `Tab ${idx + 1}`}
          </button>
        ))}
      </div>
      <div className="p-4">
        <ComponentList specs={tabs[active]?.content || []} data={data} />
      </div>
    </div>
  );
}

function GridPrimitive({ spec, data }) {
  const cols = spec.columns || 2;
  const children = spec.children || [];
  return (
    <div className={`grid gap-4`} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
      {children.map((child, idx) => (
        <div key={idx}>
          <ComponentList specs={Array.isArray(child) ? child : [child]} data={data} />
        </div>
      ))}
    </div>
  );
}

function CardPrimitive({ spec, data }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {spec.title && (
        <div className="px-4 py-2.5 bg-gray-50 border-b text-sm font-semibold text-gray-700">
          {spec.title}
        </div>
      )}
      <div className="p-4">
        <ComponentList specs={spec.children || []} data={data} />
      </div>
    </div>
  );
}

function ChartPrimitive({ spec }) {
  const config = {
    type: spec.chart_type || spec.chartType || 'bar',
    data: spec.chart_data || spec.chartData || spec.data,
    title: spec.title,
    xAxisKey: spec.x_label || spec.xLabel,
    yAxisKey: spec.y_label || spec.yLabel,
  };
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <AIChart config={config} />
    </div>
  );
}

function FlowchartPrimitive({ spec }) {
  const graph = {
    nodes: spec.nodes || [],
    edges: spec.edges || [],
    swimlanes: spec.swimlanes || [],
  };
  if (graph.nodes.length === 0) return null;
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 border-b text-sm font-semibold text-gray-700 flex items-center justify-between">
        <span>{spec.title || 'Process Flow'}</span>
        <span className="text-xs font-normal text-gray-400">
          {graph.nodes.length} nodes &middot; {graph.edges.length} edges
        </span>
      </div>
      <Suspense
        fallback={
          <div className="flex items-center justify-center h-96 text-gray-400 text-sm">
            Loading flowchart...
          </div>
        }
      >
        <ProcessFlowchart graph={graph} height={spec.height || 600} />
      </Suspense>
    </div>
  );
}

function MetricPrimitive({ spec }) {
  const trendColors = {
    up: 'text-emerald-600',
    down: 'text-red-600',
    neutral: 'text-gray-500',
  };
  const trendArrows = { up: '\u2191', down: '\u2193', neutral: '\u2192' };
  const trend = spec.trend || 'neutral';

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
      <div className="text-2xl font-bold text-gray-900">{spec.value}</div>
      {spec.label && <div className="text-sm text-gray-500 mt-1">{spec.label}</div>}
      {spec.change != null && (
        <div className={`text-sm mt-1 font-medium ${trendColors[trend] || trendColors.neutral}`}>
          {trendArrows[trend] || ''} {spec.change}
        </div>
      )}
    </div>
  );
}

function DividerPrimitive() {
  return <hr className="border-gray-200 my-2" />;
}

function CodePrimitive({ spec }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {spec.title && (
        <div className="px-4 py-2 bg-gray-50 border-b text-xs font-semibold text-gray-600 flex items-center justify-between">
          <span>{spec.title}</span>
          {spec.language && (
            <span className="text-gray-400 font-normal">{spec.language}</span>
          )}
        </div>
      )}
      <pre className="p-4 text-xs font-mono text-gray-800 overflow-x-auto bg-gray-50 whitespace-pre-wrap">
        {spec.value || ''}
      </pre>
    </div>
  );
}

// ─── Primitive registry ──────────────────────────────────────────────
const PRIMITIVES = {
  header: HeaderPrimitive,
  text: TextPrimitive,
  table: TablePrimitive,
  list: ListPrimitive,
  accordion: AccordionPrimitive,
  tabs: TabsPrimitive,
  grid: GridPrimitive,
  card: CardPrimitive,
  chart: ChartPrimitive,
  flowchart: FlowchartPrimitive,
  metric: MetricPrimitive,
  divider: DividerPrimitive,
  code: CodePrimitive,
};

// ─── Recursive component list renderer ───────────────────────────────
function ComponentList({ specs, data }) {
  if (!specs || specs.length === 0) return null;
  return (
    <div className="space-y-4">
      {specs.map((spec, idx) => (
        <VizComponent key={idx} spec={spec} data={data} />
      ))}
    </div>
  );
}

function VizComponent({ spec, data }) {
  if (!spec || !spec.type) return null;

  if (spec.type === 'render') {
    return <CustomRender spec={spec} data={data} />;
  }

  const Comp = PRIMITIVES[spec.type];
  if (!Comp) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-xs text-yellow-700">
        Unknown visualization type: <code>{spec.type}</code>
      </div>
    );
  }

  return <Comp spec={spec} data={data} />;
}

// ─── Main export ─────────────────────────────────────────────────────
export default function VisualizationRenderer({ visualization, data }) {
  const specs = useMemo(() => {
    if (!visualization) return [];
    if (Array.isArray(visualization)) return visualization;
    return [visualization];
  }, [visualization]);

  if (specs.length === 0) return null;

  return <ComponentList specs={specs} data={data} />;
}
