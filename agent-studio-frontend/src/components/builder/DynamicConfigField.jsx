// Dynamic configuration field renderer based on field type from JSON
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { listKnowledgeBasesForAttach } from '@/api/kb-client';
import { resolveFieldOptions, isDynamicField, preloadDynamicOptions } from '@/utils/dynamicOptions';
import OutputSchemaBuilder from './OutputSchemaBuilder';
import CodeEditorModal from './CodeEditorModal';
import QuestionsBuilderModal from './QuestionsBuilderModal';
import KbMultiselectField from './KbMultiselectField';
import ConfigToggleRow from './ConfigToggleRow';
import CategoryRangeSlider from './CategoryRangeSlider';
import { COLOR, CATEGORY } from './figmaSpec';

function ExpandableCodeEditor({
  field,
  value,
  onChange,
  config,
  upstreamNodes,
  workflowId,
  nodeId,
}) {
  const [editorOpen, setEditorOpen] = useState(false);
  const codeVal = value || field.defaultValue || '';
  const lineCount = codeVal.split('\n').length;
  const hasCode = codeVal.trim().length > 0;

  const previewLines = codeVal.split('\n').slice(0, 8);
  const preview = previewLines.join('\n') + (lineCount > 8 ? '\n...' : '');

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium text-foreground flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
          {field.label}
        </span>
        <span className="text-xs text-muted-foreground">
          {hasCode ? `${lineCount} line${lineCount !== 1 ? 's' : ''}` : 'No code'} &middot; Python
        </span>
      </div>

      {/* Code preview card */}
      <div
        onClick={() => setEditorOpen(true)}
        className="group cursor-pointer border border-border rounded-lg overflow-hidden hover:ring-1 transition-all"
        style={{
          backgroundColor: COLOR.black,
          borderColor: COLOR.darker,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.borderColor = CATEGORY.agent.accent;
          e.currentTarget.style.boxShadow = `0 0 0 1px ${CATEGORY.agent.accent}4d`;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.borderColor = COLOR.darker;
          e.currentTarget.style.boxShadow = 'none';
        }}
      >
        {hasCode ? (
          <pre
            className="p-3 font-mono text-xs leading-relaxed overflow-hidden max-h-[180px]"
            style={{ color: `${CATEGORY.review.accent}cc` }}
          >
            {preview}
          </pre>
        ) : (
          <div className="p-4 flex flex-col items-center justify-center gap-1.5" style={{ color: COLOR.medium }}>
            <svg className="w-6 h-6" style={{ color: COLOR.dark }} viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            <span className="text-xs">No code yet</span>
          </div>
        )}

        {/* Hover overlay */}
        <div
          className="flex items-center justify-center gap-2 px-3 py-2 border-t transition-colors group-hover:bg-[rgba(130,22,197,0.12)]"
          style={{ backgroundColor: COLOR.darkest, borderColor: COLOR.darker }}
        >
          <svg className="w-3.5 h-3.5 transition-colors group-hover:text-[#8216c5]" style={{ color: COLOR.medium }} viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
          </svg>
          <span className="text-xs font-medium transition-colors group-hover:text-[#8216c5]" style={{ color: COLOR.medium }}>
            {hasCode ? 'Edit code' : 'Write code'}
          </span>
          <span className="text-[10px] ml-auto transition-colors group-hover:text-[#8216c5]/60" style={{ color: COLOR.dark }}>
            Full editor with AI assistant
          </span>
        </div>
      </div>

      {field.helpText && (
        <p className="mt-1 text-xs text-muted-foreground">{field.helpText}</p>
      )}

      <CodeEditorModal
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        code={codeVal}
        onSave={(newCode) => onChange(field.key, newCode)}
        config={config}
        upstreamNodes={upstreamNodes || []}
        workflowId={workflowId || null}
        nodeId={nodeId || null}
      />
    </div>
  );
}

// Preview card + modal launcher for the `questions_builder` field type.
// Mirrors the pattern used by ExpandableCodeEditor: show a compact
// summary of the configured payload in the inspector, click to open
// the full-screen editor.
function ExpandableQuestionsBuilder({
  field,
  value,
  onChange,
  contextLabel,
}) {
  const [open, setOpen] = useState(false);
  const payload = (value && typeof value === 'object' && !Array.isArray(value))
    ? value
    : { questions: Array.isArray(value) ? value : [] };
  const questions = Array.isArray(payload.questions) ? payload.questions : [];
  const count = questions.length;
  const intro = (payload.intro || '').trim();

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium text-foreground flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {field.label}
        </span>
        <span className="text-xs text-muted-foreground">
          {count > 0
            ? `${count} ${count === 1 ? 'question' : 'questions'}`
            : 'No questions'}
        </span>
      </div>

      <div
        onClick={() => setOpen(true)}
        className="group cursor-pointer rounded-lg overflow-hidden transition-all"
        style={{
          border: '1px solid #464646',
          backgroundColor: 'transparent',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.borderColor = '#d93854')}
        onMouseLeave={(e) => (e.currentTarget.style.borderColor = '#464646')}
      >
        {count > 0 ? (
          <div className="p-3 space-y-1.5">
            {intro && (
              <div className="text-[11px] italic line-clamp-2 mb-1" style={{ color: '#b5b5b5' }}>
                {intro}
              </div>
            )}
            {questions.slice(0, 4).map((q, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="font-mono shrink-0" style={{ color: '#888' }}>{i + 1}.</span>
                <span className="flex-1 truncate" style={{ color: '#e5e5e5' }}>
                  {q.prompt || <span className="italic" style={{ color: '#888' }}>Untitled</span>}
                </span>
                {q.required && (
                  <span className="text-[10px] shrink-0" style={{ color: '#d93854' }}>required</span>
                )}
              </div>
            ))}
            {count > 4 && (
              <div className="text-[11px]" style={{ color: '#888' }}>
                + {count - 4} more
              </div>
            )}
          </div>
        ) : (
          <div className="p-4 flex flex-col items-center justify-center gap-1.5" style={{ color: '#b5b5b5' }}>
            <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" style={{ color: '#666' }}>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="text-xs">No questions yet</span>
          </div>
        )}

        <div
          className="flex items-center justify-center gap-2 px-3 py-2 transition-colors"
          style={{
            backgroundColor: 'rgba(217, 56, 84, 0.08)',
            borderTop: '1px solid rgba(217, 56, 84, 0.3)',
          }}
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" style={{ color: '#d93854' }}>
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
          </svg>
          <span className="text-xs font-medium" style={{ color: '#d93854' }}>
            {count > 0 ? 'Edit questions' : 'Configure questions'}
          </span>
          <span className="text-[10px] ml-auto" style={{ color: 'rgba(217, 56, 84, 0.7)' }}>
            Opens fullscreen
          </span>
        </div>
      </div>

      {field.helpText && (
        <p className="mt-1 text-xs text-muted-foreground">{field.helpText}</p>
      )}

      <QuestionsBuilderModal
        isOpen={open}
        onClose={() => setOpen(false)}
        value={payload}
        onSave={(next) => onChange(field.key, next)}
        fieldLabel={field.label}
        contextLabel={contextLabel}
      />
    </div>
  );
}

// ── JSON Schema → condition variable picker paths ───────────────────────
// Mirrors deliverable shape under `input.deliverable.*` (array items use [0]
// as the first row — same convention users already type in expressions).

const MAX_CONDITION_SCHEMA_PATHS = 160;

function normalizeJsonSchemaType(typeField) {
  if (Array.isArray(typeField)) {
    const nonNull = typeField.filter((t) => t && t !== 'null');
    return nonNull[0] || 'string';
  }
  return typeField || '';
}

function isSchemaArray(prop) {
  if (!prop || typeof prop !== 'object') return false;
  if (prop.type === 'array') return true;
  if (Array.isArray(prop.type) && prop.type.includes('array')) return true;
  return false;
}

function unwrapOutputSchemaEnvelope(parsed) {
  if (!parsed || typeof parsed !== 'object') return parsed;
  const props = parsed.properties;
  if (
    props
    && typeof props === 'object'
    && Object.keys(props).length === 1
    && props.data
    && typeof props.data === 'object'
  ) {
    return props.data;
  }
  return parsed;
}

function humanizeSchemaPathForPicker(name) {
  return name
    .replace(/\[0\]/g, ' (first)')
    .replace(/\./g, ' → ');
}

/** Split `sections[0].content.mode` into [{key, index?}, …] for tree UI */
function expandSchemaPathToSegments(name) {
  if (!name) return [];
  return name.split('.').map((part) => {
    const m = part.match(/^([^[\]]+)(\[\d+\])?$/);
    if (!m) return { key: part, index: null };
    return {
      key: m[1],
      index: m[2] != null ? parseInt(m[2].slice(1, -1), 10) : null,
    };
  });
}

function segmentKeyForTree(seg) {
  return seg.index != null ? `${seg.key}[${seg.index}]` : seg.key;
}

function segmentLabelForTree(seg) {
  if (seg.index != null) {
    return seg.index === 0 ? `${seg.key} — first row` : `${seg.key} — row ${seg.index + 1}`;
  }
  return seg.key;
}

/** Build nested rows for collapsible field browser */
function buildVariablePickerTree(flatVars) {
  const sorted = [...flatVars].sort((a, b) => a.name.localeCompare(b.name));
  const roots = [];

  sorted.forEach((v) => {
    const segs = expandSchemaPathToSegments(v.name);
    let list = roots;
    let cumulative = '';
    segs.forEach((seg, i) => {
      const sk = segmentKeyForTree(seg);
      cumulative = cumulative ? `${cumulative}.${sk}` : sk;
      let node = list.find((n) => n.id === cumulative);
      if (!node) {
        node = {
          id: cumulative,
          segmentKey: sk,
          label: segmentLabelForTree(seg),
          children: [],
          var: null,
        };
        list.push(node);
      }
      if (i === segs.length - 1) {
        node.var = v;
      }
      list = node.children;
    });
  });

  const sortTree = (arr) => {
    arr.sort((a, b) => a.segmentKey.localeCompare(b.segmentKey));
    arr.forEach((n) => sortTree(n.children));
  };
  sortTree(roots);
  return roots;
}

/**
 * Flatten JSON Schema into dot paths for the If/Else variable picker.
 * Walks objects and `array` → `items` object schemas (first element `[0]`).
 */
function extractVariablesFromSchema(schema) {
  let parsed = schema;
  if (typeof schema === 'string') {
    try {
      parsed = JSON.parse(schema);
    } catch {
      return [];
    }
  }
  if (!parsed || typeof parsed !== 'object') return [];

  parsed = unwrapOutputSchemaEnvelope(parsed);

  const variables = [];
  const seen = new Set();

  const pushVar = (name, type, description, depth) => {
    if (variables.length >= MAX_CONDITION_SCHEMA_PATHS) return;
    if (!name || seen.has(name)) return;
    seen.add(name);
    variables.push({
      name,
      type: typeof type === 'string' ? type : 'string',
      description: description || '',
      depth,
    });
  };

  const walkProperties = (propertiesObj, pathPrefix, depth) => {
    if (!propertiesObj || typeof propertiesObj !== 'object' || depth > 16) return;
    Object.entries(propertiesObj).forEach(([key, prop]) => {
      if (!prop || typeof prop !== 'object') return;
      const path = pathPrefix ? `${pathPrefix}.${key}` : key;

      if (isSchemaArray(prop)) {
        const items = prop.items || {};
        const itemProps = items.properties;
        if (itemProps && typeof itemProps === 'object' && Object.keys(itemProps).length > 0) {
          pushVar(path, 'array', prop.description || prop.title || '', depth);
          walkProperties(itemProps, `${path}[0]`, depth + 1);
        } else {
          const itType = normalizeJsonSchemaType(items.type);
          pushVar(`${path}[0]`, itType || 'any', prop.description || prop.title || '', depth);
        }
        return;
      }

      if (prop.properties && typeof prop.properties === 'object') {
        pushVar(path, 'object', prop.description || prop.title || '', depth);
        walkProperties(prop.properties, path, depth + 1);
        return;
      }

      const typ = normalizeJsonSchemaType(prop.type);
      pushVar(path, typ || 'string', prop.description || prop.title || '', depth);
    });
  };

  if (parsed.properties && typeof parsed.properties === 'object') {
    walkProperties(parsed.properties, '', 0);
  } else {
    // Legacy flat map of schemas
    Object.values(parsed).forEach((schemaObj) => {
      if (schemaObj && typeof schemaObj === 'object' && schemaObj.properties) {
        walkProperties(schemaObj.properties, '', 0);
      }
    });
  }

  variables.sort((a, b) => a.name.localeCompare(b.name));
  return variables;
}

// Helper function to get available variables from connected source nodes
function getAvailableVariables(currentNodeId, workflowState) {
  if (!currentNodeId || !workflowState) return [];
  
  const { connections, canvasNodes } = workflowState;
  const availableVars = [];
  
  // Find all incoming connections to the current node
  const incomingConnections = connections.filter(conn => conn.target === currentNodeId);
  
  incomingConnections.forEach(conn => {
    const sourceNode = canvasNodes.get(conn.source);
    if (!sourceNode) return;
    
    // Extract variables from the source node's output schema
    const outputSchema = sourceNode.config?.outputSchema;
    if (outputSchema) {
      const vars = extractVariablesFromSchema(outputSchema);
      vars.forEach(v => {
        availableVars.push({
          ...v,
          nodeId: sourceNode.id,
          nodeLabel: sourceNode.label || sourceNode.type,
          path: `input.deliverable.${v.name}` // Parsed output is directly under deliverable
        });
      });
    }
    
    // For agent-like nodes, also expose raw text when present
    const agentLikeTypes = new Set([
      'agent',
      'researcher',
      'business-analyst',
      'financial-modeler',
      'opportunity-classifier',
      'research_agent',
    ]);
    if (agentLikeTypes.has(sourceNode.type)) {
      availableVars.push({
        name: 'output_text',
        type: 'string',
        description: 'Raw text output from the agent',
        nodeId: sourceNode.id,
        nodeLabel: sourceNode.label || sourceNode.type,
        path: 'input.output_text'
      });
    }
  });
  
  return availableVars;
}

/**
 * Walk backward through the workflow graph and return all upstream agent nodes
 * in topological order (earliest first), each with an enumeration index.
 */
function getUpstreamAgentNodes(currentNodeId, workflowState) {
  if (!currentNodeId || !workflowState) return [];

  const { connections, canvasNodes } = workflowState;
  const visited = new Set();
  const agentNodes = [];

  const queue = [currentNodeId];
  visited.add(currentNodeId);

  while (queue.length > 0) {
    const nodeId = queue.shift();
    const incoming = connections.filter(c => c.target === nodeId);

    for (const conn of incoming) {
      if (visited.has(conn.source)) continue;
      visited.add(conn.source);

      const sourceNode = canvasNodes.get(conn.source);
      if (!sourceNode) continue;

      const deliverableNodeTypes = ['agent', 'code-executor'];
      if (deliverableNodeTypes.includes(sourceNode.type)) {
        agentNodes.push({
          id: conn.source,
          label: sourceNode.config?.label || sourceNode.type,
        });
      }
      queue.push(conn.source);
    }
  }

  agentNodes.reverse();
  return agentNodes.map((node, idx) => ({
    ...node,
    enumeration: idx + 1,
  }));
}

// Centered modal + collapsible tree for picking `input.deliverable.*` paths
function VariablePickerPopup({ variables, onSelect, onClose }) {
  const tree = useMemo(() => buildVariablePickerTree(variables), [variables]);
  const [expanded, setExpanded] = useState(() => new Set());

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  useEffect(() => {
    const initial = new Set();
    const markDepth = (nodes, depth) => {
      nodes.forEach((n) => {
        if (depth < 2 && n.children.length > 0) {
          initial.add(n.id);
        }
        if (n.children.length) markDepth(n.children, depth + 1);
      });
    };
    markDepth(tree, 0);
    setExpanded(initial);
  }, [tree]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const typeBadge = (t) => {
    const typ = String(t || 'any').toLowerCase();
    const wrap = 'w-7 h-7 flex items-center justify-center rounded text-[10px] font-bold shrink-0 ';
    if (typ === 'object') return <span className={`${wrap}bg-gray-200 text-gray-700`}>{'{}'}</span>;
    if (typ === 'array') return <span className={`${wrap}bg-indigo-100 text-indigo-800`}>[]</span>;
    if (typ === 'string') return <span className={`${wrap}bg-emerald-50 text-emerald-800`}>Aa</span>;
    if (typ === 'number' || typ === 'integer') return <span className={`${wrap}bg-sky-50 text-sky-800`}>#</span>;
    if (typ === 'boolean') return <span className={`${wrap}bg-amber-50 text-amber-900`}>?</span>;
    return <span className={`${wrap}bg-gray-100 text-gray-600`}>{typ.slice(0, 3).toUpperCase()}</span>;
  };

  const renderNode = (node, depth) => {
    const hasKids = node.children.length > 0;
    const hasVar = !!node.var;
    const isOpen = expanded.has(node.id);
    const displayPath = hasVar ? node.var.path : `input.deliverable.${node.id}`;

    const onRowClick = () => {
      if (hasVar) {
        onSelect(node.var.path);
      } else if (hasKids) {
        toggle(node.id);
      }
    };

    return (
      <div key={node.id} className="select-none">
        <div
          className={`flex items-start gap-2 py-2 pl-1 rounded-lg border border-transparent ${
            hasVar ? 'hover:bg-secondary/80 cursor-pointer' : hasKids ? 'hover:bg-muted/50' : ''
          }`}
          style={{ paddingLeft: `${10 + depth * 20}px` }}
        >
          {hasKids ? (
            <button
              type="button"
              className="mt-0.5 w-8 h-8 shrink-0 flex items-center justify-center rounded-md border border-border bg-background hover:bg-secondary text-foreground"
              aria-expanded={isOpen}
              aria-label={isOpen ? 'Collapse' : 'Expand'}
              onClick={(e) => {
                e.stopPropagation();
                toggle(node.id);
              }}
            >
              <svg
                className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ) : (
            <span className="w-8 shrink-0" />
          )}
          <button
            type="button"
            disabled={!hasVar && !hasKids}
            onClick={onRowClick}
            className={`flex-1 min-w-0 text-left rounded-md px-2 py-1 ${
              hasVar ? 'ring-1 ring-transparent hover:ring-border' : ''
            }`}
          >
            <div className="flex items-start gap-3">
              {typeBadge(hasVar ? node.var.type : hasKids ? 'object' : 'any')}
              <div className="min-w-0 flex-1 space-y-1">
                <div className="text-sm font-medium text-foreground break-words">{node.label}</div>
                <div className="text-xs font-mono text-muted-foreground leading-snug break-all whitespace-normal">
                  {displayPath}
                </div>
                {hasVar && node.var.description ? (
                  <div className="text-[11px] text-muted-foreground italic break-words">{node.var.description}</div>
                ) : null}
              </div>
              {hasVar ? (
                <span className="shrink-0 text-[10px] uppercase tracking-wide px-2 py-1 rounded bg-secondary text-muted-foreground">
                  {node.var.type}
                </span>
              ) : hasKids ? (
                <span className="shrink-0 text-[10px] uppercase tracking-wide px-2 py-1 rounded bg-muted text-muted-foreground">
                  group
                </span>
              ) : null}
            </div>
          </button>
        </div>
        {hasKids && isOpen ? (
          <div className="border-l border-border/60 ml-4">{node.children.map((c) => renderNode(c, depth + 1))}</div>
        ) : null}
      </div>
    );
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 sm:p-8 bg-black/50 backdrop-blur-[1px]"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="bg-background rounded-2xl border border-border shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="field-picker-title"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4 border-b border-border bg-gradient-to-r from-secondary/40 to-background shrink-0">
          <div>
            <h4 id="field-picker-title" className="text-lg font-semibold text-foreground">
              Pick a field
            </h4>
            <p className="text-xs text-muted-foreground mt-1 max-w-2xl">
              Expand each group, then click a row to paste its path into your condition. Press Esc or Close to exit.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium rounded-lg border border-border bg-background hover:bg-secondary transition-colors"
            >
              Close
            </button>
            <button
              type="button"
              onClick={onClose}
              className="w-10 h-10 flex items-center justify-center rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              aria-label="Close"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4">
          {variables.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground text-sm">
              No fields found. Connect a node that has an output schema, or add one in that node&apos;s settings.
            </div>
          ) : (
            <div className="space-y-0.5">{tree.map((n) => renderNode(n, 0))}</div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// Condition Builder Component with Expression Builder and Variable Picker
function ConditionBuilder({ value, onChange, helpText, availableVariables = [] }) {
  const [activePickerIndex, setActivePickerIndex] = useState(null);
  const textareaRefs = useRef({});

  // Filter out 'else' type from UI - it's automatically added
  const conditions = Array.isArray(value) ? value.filter(c => c.type !== 'else') : [];
  
  // When saving, ensure we include conditions plus auto-generated else
  const saveConditions = (updatedConditions) => {
    // Always add an automatic "Else" at the end if we have at least one condition
    const finalConditions = updatedConditions.length > 0 
      ? [...updatedConditions, {
          id: `condition_else_${Date.now()}`,
          caseName: '',
          expression: '',
          type: 'else'
        }]
      : updatedConditions;
    onChange(finalConditions);
  };

  const addCondition = (type = 'else_if') => {
    const newCondition = {
      id: `condition_${Date.now()}`,
      caseName: '',
      expression: '',
      type: type
    };
    saveConditions([...conditions, newCondition]);
  };

  const updateCondition = (index, field, newValue) => {
    const updated = [...conditions];
    updated[index] = { ...updated[index], [field]: newValue };
    saveConditions(updated);
  };

  const removeCondition = (index) => {
    const updated = conditions.filter((_, i) => i !== index);
    saveConditions(updated);
  };

  const getConditionTypeLabel = (type) => {
    if (type === 'if') return 'If';
    if (type === 'else_if') return 'Else if';
    if (type === 'else') return 'Else';
    return type;
  };

  const insertOperator = (index, operator) => {
    const condition = conditions[index];
    const currentExpression = condition.expression || '';
    const newExpression = currentExpression ? `${currentExpression} ${operator} ` : `${operator} `;
    updateCondition(index, 'expression', newExpression);
  };

  const insertVariable = (index, varPath) => {
    const condition = conditions[index];
    const currentExpression = condition.expression || '';
    const newExpression = currentExpression ? `${currentExpression}${varPath}` : varPath;
    updateCondition(index, 'expression', newExpression);
    setActivePickerIndex(null);
  };

  const openVariablePicker = (index) => {
    setActivePickerIndex(index);
  };

  const closeVariablePicker = () => {
    setActivePickerIndex(null);
  };

  // Organize variables for the picker: readable labels + schema depth for indent
  const organizeVariablesHierarchically = () => {
    return availableVariables.map((v) => {
      const depth = typeof v.depth === 'number' ? v.depth : Math.max(0, (v.name.match(/\./g) || []).length);
      return {
        ...v,
        depth,
        displayName: humanizeSchemaPathForPicker(v.name),
      };
    });
  };

  return (
    <div className="mb-4">
      <label className="block text-sm font-medium text-foreground mb-2">
        Conditions
      </label>
      
      {helpText && (
        <div className="mb-3 p-2 bg-gray-50 border border-gray-300 rounded text-xs text-gray-700">
          {helpText}
        </div>
      )}
      
      {/* Variable Picker Popup */}
      {activePickerIndex !== null && (
        <VariablePickerPopup
          variables={organizeVariablesHierarchically()}
          onSelect={(path) => insertVariable(activePickerIndex, path)}
          onClose={closeVariablePicker}
        />
      )}

      <div className="space-y-4">
        {conditions.map((condition, index) => (
          <div key={condition.id || index} className="space-y-3">
            {/* Condition Header */}
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">
                {getConditionTypeLabel(condition.type)}
              </span>
              {conditions.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeCondition(index)}
                  className="text-red-600 hover:text-red-800 transition-colors"
                  title="Remove condition"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>

            {condition.type !== 'else' && (
              <>
                {/* Case Name */}
                <input
                  type="text"
                  value={condition.caseName || ''}
                  onChange={(e) => updateCondition(index, 'caseName', e.target.value)}
                  placeholder="Case name (optional)"
                  className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                />

                {/* Enter Condition + browse */}
                <div className="flex items-center justify-between gap-2">
                  <label className="block text-sm text-foreground">
                    Enter condition
                  </label>
                  {availableVariables.length > 0 && (
                    <button
                      type="button"
                      onClick={() => openVariablePicker(index)}
                      className="text-xs font-medium text-primary hover:underline shrink-0"
                    >
                      Browse fields
                    </button>
                  )}
                </div>

                {/* Condition Textarea */}
                <textarea
                  ref={el => textareaRefs.current[index] = el}
                  value={condition.expression || ''}
                  onChange={(e) => updateCondition(index, 'expression', e.target.value)}
                  placeholder='e.g., pick a field above or type a comparison'
                  rows={3}
                  className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 resize-none"
                />
                
                {/* Operator Buttons */}
                <div className="space-y-2">
                  {/* Comparison Row */}
                  <div className="flex items-center flex-wrap gap-2">
                    <span className="text-sm text-foreground">Comparison:</span>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '==')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      ==
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '!=')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      !=
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '>')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      &gt;
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '<')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      &lt;
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '>=')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      &gt;=
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '<=')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      &lt;=
                    </button>
                  </div>
                  
                  {/* Logic Row */}
                  <div className="flex items-center flex-wrap gap-2">
                    <span className="text-sm text-foreground">Logic:</span>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '&&')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      AND
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '||')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      OR
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, '(')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      (
                    </button>
                    <button
                      type="button"
                      onClick={() => insertOperator(index, ')')}
                      className="px-3 py-1 text-sm bg-background border border-border rounded-md hover:bg-secondary transition-colors"
                    >
                      )
                    </button>
                  </div>
                </div>
                
                {/* Help Text */}
                <div className="text-xs text-muted-foreground">
                  Use Common Expression Language to create a custom expression. <a href="#" className="text-gray-700 hover:underline">Learn more.</a>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Add Else If Button */}
      <button
        type="button"
        onClick={() => addCondition('else_if')}
        className="mt-4 flex items-center gap-1.5 text-sm text-foreground hover:text-primary transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
        </svg>
        Add Else If
      </button>
      
      {/* Else Info */}
      <div className="mt-3 flex items-start gap-2 p-3 bg-gray-50 border border-gray-300 rounded-lg">
        <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center bg-gray-600 text-white rounded text-xs font-bold">
          i
        </div>
        <p className="text-xs text-muted-foreground">
          An <strong className="text-foreground">Else</strong> (default) branch will be automatically added to handle unmatched cases
        </p>
      </div>
    </div>
  );
}

// Expanded Text Editor Modal Component
function ExpandedTextModal({ isOpen, label, value, onClose, onSave, isMultiline = true }) {
  const [editValue, setEditValue] = useState(value || '');
  
  useEffect(() => {
    setEditValue(value || '');
  }, [value, isOpen]);

  if (!isOpen) return null;

  const handleSave = () => {
    onSave(editValue);
    onClose();
  };

  return (
    <div
      data-theme="apex-dark"
      className="fixed inset-0 flex items-center justify-center z-[9999]"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl p-6 w-[90vw] max-w-3xl max-h-[80vh] flex flex-col shadow-2xl"
        style={{
          background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
          border: '1px solid #464646',
          color: '#ffffff',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold" style={{ color: '#ffffff' }}>{label}</h3>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
            style={{ color: '#b5b5b5', backgroundColor: 'transparent' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 min-h-0 mb-4">
          {isMultiline ? (
            <textarea
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="w-full h-full min-h-[300px] px-4 py-3 text-sm rounded-2xl resize-none focus:outline-none"
              style={{
                backgroundColor: 'transparent',
                border: '1px solid #464646',
                color: '#ffffff',
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = '#d93854')}
              onBlur={(e) => (e.currentTarget.style.borderColor = '#464646')}
              autoFocus
              placeholder={`Enter ${label.toLowerCase()}...`}
            />
          ) : (
            <input
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="w-full px-4 py-3 text-sm rounded-2xl focus:outline-none"
              style={{
                backgroundColor: 'transparent',
                border: '1px solid #464646',
                color: '#ffffff',
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = '#d93854')}
              onBlur={(e) => (e.currentTarget.style.borderColor = '#464646')}
              autoFocus
              placeholder={`Enter ${label.toLowerCase()}...`}
            />
          )}
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{
              color: '#ffffff',
              backgroundColor: 'transparent',
              border: '1px solid #464646',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{ color: '#ffffff', backgroundColor: '#d93854', border: 'none' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#c52a45')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#d93854')}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// Clickable Text Field Component
function ExpandableTextField({ label, value, onChange, placeholder, isMultiline = false, disabled = false }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const displayValue = value || '';
  const truncatedValue = displayValue.length > 50 ? displayValue.substring(0, 50) + '...' : displayValue;

  if (disabled) {
    return (
      <div className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg opacity-50 cursor-not-allowed">
        {displayValue ? (
          <span className="text-foreground">{truncatedValue}</span>
        ) : (
          <span className="text-muted-foreground">{placeholder}</span>
        )}
      </div>
    );
  }

  return (
    <>
      <div
        onClick={() => setIsModalOpen(true)}
        className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg cursor-pointer hover:border-primary/50 transition-colors"
      >
        {displayValue ? (
          <span className="text-foreground">{truncatedValue}</span>
        ) : (
          <span className="text-muted-foreground">{placeholder}</span>
        )}
      </div>
      <ExpandedTextModal
        isOpen={isModalOpen}
        label={label}
        value={value}
        onClose={() => setIsModalOpen(false)}
        onSave={onChange}
        isMultiline={isMultiline}
      />
    </>
  );
}

export default function DynamicConfigField({ 
  field, 
  value, 
  onChange, 
  config, 
  currentNodeId,
  workflowState,
  upstreamNodes,
  nodeType,
}) {
  const [dynamicOptions, setDynamicOptions] = useState(null);
  const [loadingOptions, setLoadingOptions] = useState(false);
  
  // Load dynamic options for select fields.
  // Uses a stale flag so that if config.modelProvider changes while a fetch is
  // in-flight, the earlier response is discarded and only the latest applies.
  useEffect(() => {
    if (field.type === 'select' && isDynamicField(field)) {
      let stale = false;
      setLoadingOptions(true);
      resolveFieldOptions(field, config)
        .then(options => {
          if (!stale) {
            setDynamicOptions(options);
            setLoadingOptions(false);
          }
        })
        .catch(error => {
          if (!stale) {
            console.error('Failed to load dynamic options:', error);
            setLoadingOptions(false);
            setDynamicOptions([]); // Fallback to empty
          }
        });
      return () => { stale = true; };
    }
  }, [field.key, field.type, field.options, config?.modelProvider]); // Re-fetch when provider changes
  
  // Get available variables from connected nodes for condition builder
  const availableVariables = field.type === 'condition_builder' 
    ? getAvailableVariables(currentNodeId, workflowState)
    : [];

  // Load dynamic options for knowledge base ID(s).
  // Fires for:
  //  - the Agent node's single `knowledgeBaseId` (kb_select / multiselect)
  //  - the Code Runner node's multi `knowledgeBaseIds` (kb_multiselect)
  useEffect(() => {
    const isKbSelector =
      (field.key === 'knowledgeBaseId' &&
        (field.type === 'multiselect' || field.type === 'kb_select')) ||
      field.type === 'kb_multiselect';
    if (!isKbSelector) return;

    const fetchKBs = async () => {
      try {
        setLoadingOptions(true);
        const data = await listKnowledgeBasesForAttach();
        const kbOptions = (data.knowledge_bases || []).map(kb => ({
          value: kb.kb_id,
          label: `${kb.name} (${kb.document_count} docs, ${kb.chunk_count} chunks)`
        }));
        setDynamicOptions(kbOptions);
      } catch (error) {
        console.error('Failed to load knowledge bases:', error);
        setDynamicOptions([]);
      } finally {
        setLoadingOptions(false);
      }
    };
    fetchKBs();
  }, [field.key, field.type]);

  // Check if field should be shown based on showIf condition
  if (field.showIf) {
    const conditionField = field.showIf.field;
    const conditionValue = field.showIf.value;
    const currentValue = config[conditionField];
    
    // Hide field if condition is not met
    if (currentValue !== conditionValue) {
      return null;
    }
  }

  // Check if field should be hidden based on hideIf condition
  if (field.hideIf) {
    const conditionField = field.hideIf.field;
    const conditionValue = field.hideIf.value;
    const currentValue = config[conditionField];

    if (currentValue === conditionValue) {
      return null;
    }
  }

  // Handle array fields (comma-separated)
  const handleArrayChange = (newValue) => {
    if (field.isArray) {
      const array = newValue.split(',').map(item => item.trim()).filter(item => item);
      onChange(field.key, array);
    } else {
      onChange(field.key, newValue);
    }
  };

  // Get array value as comma-separated string
  const getArrayValue = () => {
    return Array.isArray(value) ? value.join(', ') : '';
  };

  // Handle dependent select options (like modelName depends on modelProvider)
  const getSelectOptions = () => {
    // Use dynamically loaded options if available
    if (isDynamicField(field) && dynamicOptions !== null) {
      return dynamicOptions;
    }
    
    // Handle dependent options (conditional based on another field)
    if (field.dependsOn && typeof field.options === 'object') {
      const parentValue = config[field.dependsOn];
      return field.options[parentValue] || [];
    }
    
    // Return static options
    return Array.isArray(field.options) ? field.options : [];
  };

  switch (field.type) {
    case 'text':
      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
          </label>
          <ExpandableTextField
            label={field.label}
            value={field.isArray ? getArrayValue() : (value || '')}
            onChange={(val) => field.isArray ? handleArrayChange(val) : onChange(field.key, val)}
            placeholder={field.placeholder || ''}
            disabled={field.disabled}
            isMultiline={false}
          />
        </div>
      );

    case 'textarea':
      // Use OutputSchemaBuilder for outputSchema fields
      if (field.key === 'outputSchema') {
        return (
          <OutputSchemaBuilder
            value={value || ''}
            onChange={(val) => onChange(field.key, val)}
            onConfigChange={onChange}
            label={field.label}
            config={config}
            workflowId={workflowState?.selectedWorkflow?.id}
            nodeId={currentNodeId}
          />
        );
      }
      
      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
          </label>
          <ExpandableTextField
            label={field.label}
            value={value || ''}
            onChange={(val) => onChange(field.key, val)}
            placeholder={field.placeholder || ''}
            disabled={field.disabled}
            isMultiline={true}
          />
        </div>
      );

    case 'select': {
      const selectOptions = getSelectOptions();
      const isLoading = isDynamicField(field) && loadingOptions;
      
      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
            {isLoading && (
              <span className="ml-2 text-xs text-muted-foreground">
                (loading...)
              </span>
            )}
          </label>
          <select
            value={value || field.defaultValue}
            onChange={(e) => onChange(field.key, e.target.value)}
            disabled={field.disabled || isLoading}
            className={`custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 ${(field.disabled || isLoading) ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {isLoading ? (
              <option value="">Loading models...</option>
            ) : selectOptions.length === 0 ? (
              <option value="">No options available</option>
            ) : (
              selectOptions.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))
            )}
          </select>
          {field.helpText && (
            <p className="text-xs text-muted-foreground mt-1">
              {field.helpText}
            </p>
          )}
        </div>
      );
    }

    case 'slider': {
      const sliderValue = value !== undefined ? value : field.defaultValue;
      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
          </label>
          <CategoryRangeSlider
            nodeType={nodeType}
            min={field.min ?? 0}
            max={field.max ?? 100}
            step={field.step ?? 1}
            value={sliderValue}
            onChange={(e) => onChange(field.key, parseFloat(e.target.value))}
            disabled={field.disabled}
          />
          <div className="text-xs text-muted-foreground mt-1 text-right">
            {sliderValue}
          </div>
          {field.helpText && (
            <p className="text-xs text-muted-foreground mt-1">
              {field.helpText}
            </p>
          )}
        </div>
      );
    }

    case 'number':
      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
          </label>
          <input
            type="number"
            value={value !== undefined && value !== null ? value : (field.defaultValue !== undefined ? field.defaultValue : '')}
            onChange={(e) => onChange(field.key, e.target.value ? parseInt(e.target.value) : null)}
            placeholder={field.placeholder || ''}
            min={field.min}
            max={field.max}
            disabled={field.disabled}
            className={`w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 ${field.disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
          />
        </div>
      );

    case 'toggle_row': {
      const checked = value !== undefined ? value : field.defaultValue;
      let rowDisabled = !!field.disabled;
      let requiresHint;

      if (field.requires) {
        const reqMet = config[field.requires.field] === field.requires.value;
        if (!reqMet) {
          rowDisabled = true;
          requiresHint = field.requiresHint || `Requires ${field.requires.field === 'enableWebSearch' ? 'Web Search' : field.requires.field}`;
        }
      }

      const lockedForInteractive =
        field.key === 'enableUserQuestions' && config.agentMode === 'chat';
      if (lockedForInteractive) {
        rowDisabled = true;
        requiresHint = 'Always enabled for Interactive delivery mode.';
      }

      const handleToggle = (next) => {
        onChange(field.key, next);
        if (field.key === 'enableWebSearch' && !next && config.enableDeepResearch) {
          onChange('enableDeepResearch', false);
        }
      };

      return (
        <ConfigToggleRow
          label={field.label}
          helpText={field.helpText}
          icon={field.icon}
          badge={field.badge}
          checked={lockedForInteractive ? true : checked}
          disabled={rowDisabled}
          requiresHint={requiresHint}
          onChange={handleToggle}
          nodeType={nodeType}
        />
      );
    }

    case 'checkbox':
      return (
        <div className="mb-4">
          <label className={`flex items-center gap-2 ${field.disabled ? 'opacity-50 cursor-not-allowed' : ''}`}>
            <input
              type="checkbox"
              checked={value !== undefined ? value : field.defaultValue}
              onChange={(e) => onChange(field.key, e.target.checked)}
              disabled={field.disabled}
              className={`w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary ${field.disabled ? 'cursor-not-allowed' : ''}`}
            />
            <span className="text-sm font-medium text-foreground">{field.label}</span>
          </label>
          {field.helpText && (
            <p className="text-xs text-muted-foreground mt-1 ml-6">
              {field.helpText}
            </p>
          )}
        </div>
      );

    case 'multiselect':
      const options = dynamicOptions || field.options || [];
      
      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
          </label>
          {loadingOptions ? (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
              <span>Loading knowledge bases...</span>
            </div>
          ) : options.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground bg-background border border-border rounded-lg">
              No knowledge bases available. Create one first.
            </div>
          ) : (
            <div className="space-y-2 max-h-48 overflow-y-auto p-2 bg-background border border-border rounded-lg">
              {options.map(option => {
                const currentValue = Array.isArray(value) ? value : (field.defaultValue || []);
                const isChecked = currentValue.includes(option.value);
                
                return (
                  <label key={option.value} className={`flex items-center gap-2 p-2 rounded hover:bg-secondary transition-colors ${field.disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={(e) => {
                        const newValue = Array.isArray(value) ? [...value] : [...(field.defaultValue || [])];
                        if (e.target.checked) {
                          if (!newValue.includes(option.value)) {
                            newValue.push(option.value);
                          }
                        } else {
                          const index = newValue.indexOf(option.value);
                          if (index > -1) {
                            newValue.splice(index, 1);
                          }
                        }
                        onChange(field.key, newValue);
                      }}
                      disabled={field.disabled}
                      className={`w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary ${field.disabled ? 'cursor-not-allowed' : ''}`}
                    />
                    <span className="text-sm text-foreground">{option.label}</span>
                  </label>
                );
              })}
            </div>
          )}
        </div>
      );

    case 'kb_multiselect':
      return (
        <KbMultiselectField
          value={Array.isArray(value) ? value : (field.defaultValue || [])}
          onChange={(ids) => onChange(field.key, ids)}
          disabled={field.disabled}
          label="Attached bases"
          helpText={field.helpText}
          nodeType={nodeType}
        />
      );

    case 'kb_select':
      const kbOptions = dynamicOptions || field.options || [];
      // Get current value - now stored as single string, not array
      const currentKbValue = value || '';
      
      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
          </label>
          {loadingOptions ? (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
              <span>Loading knowledge bases...</span>
            </div>
          ) : kbOptions.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground bg-background border border-border rounded-lg">
              No knowledge bases available. Create one first.
            </div>
          ) : (
            <select
              value={currentKbValue}
              onChange={(e) => {
                // Store as single string
                const newValue = e.target.value || null;
                onChange(field.key, newValue);
              }}
              disabled={field.disabled}
              className={`custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 ${field.disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <option value="">Select a knowledge base...</option>
              {kbOptions.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
        </div>
      );

    case 'condition_builder':
      return (
        <ConditionBuilder
          value={value || field.defaultValue}
          onChange={(newValue) => onChange(field.key, newValue)}
          helpText={field.helpText}
          availableVariables={availableVariables}
        />
      );

    case 'deliverable_source_select': {
      const upstreamAgents = getUpstreamAgentNodes(currentNodeId, workflowState);
      const hasUpstream = upstreamAgents.length > 0;
      const isFileScope = field.key === 'fileScope';

      // Normalize current value for backward compat:
      // - undefined/null/""/true → "all" (existing deliverable workflows)
      // - false → "none" (old checkbox was unchecked)
      // fileScope: local/none/empty → this agent only; global/all → all previous uploads
      let currentMode;
      let selectedIds;
      if (isFileScope && (value === 'local' || value === false || value === 'none' || value == null || value === '')) {
        currentMode = 'none';
        selectedIds = [];
      } else if (isFileScope && (value === 'global' || value === 'all' || value === true)) {
        currentMode = 'all';
        selectedIds = [];
      } else if (value === false || value === 'none') {
        currentMode = 'none';
        selectedIds = [];
      } else if (Array.isArray(value)) {
        currentMode = 'select';
        selectedIds = value;
      } else {
        currentMode = isFileScope ? 'none' : 'all';
        selectedIds = [];
      }

      const handleModeChange = (newMode) => {
        if (newMode === 'all') {
          onChange(field.key, 'all');
        } else if (newMode === 'none') {
          onChange(field.key, 'none');
        } else {
          onChange(field.key, []);
        }
      };

      const handleAgentToggle = (agentId, checked) => {
        const current = Array.isArray(value) ? [...value] : [];
        if (checked) {
          if (!current.includes(agentId)) current.push(agentId);
        } else {
          const idx = current.indexOf(agentId);
          if (idx > -1) current.splice(idx, 1);
        }
        onChange(field.key, current);
      };

      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-2">
            {field.label}
          </label>
          {!hasUpstream ? (
            <div className="px-3 py-2 text-sm text-muted-foreground bg-background border border-border rounded-lg opacity-50">
              {isFileScope
                ? 'This agent only (no earlier steps yet)'
                : 'No previous agents in this workflow'}
            </div>
          ) : (
            <>
              <select
                value={currentMode}
                onChange={(e) => handleModeChange(e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="all">
                  {isFileScope
                    ? 'All previous uploads'
                    : `All previous agents (${upstreamAgents.length})`}
                </option>
                <option value="none">
                  {isFileScope ? 'This agent only' : 'None'}
                </option>
                {upstreamAgents.length > 1 && (
                  <option value="select">
                    {isFileScope ? 'Select specific steps...' : 'Select specific agents...'}
                  </option>
                )}
              </select>

              {currentMode === 'select' && (
                <div className="mt-2 space-y-1 max-h-48 overflow-y-auto p-2 bg-background border border-border rounded-lg">
                  {upstreamAgents.map((agent) => {
                    const isChecked = selectedIds.includes(agent.id);
                    return (
                      <label
                        key={agent.id}
                        className="flex items-center gap-2 p-2 rounded hover:bg-secondary transition-colors cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => handleAgentToggle(agent.id, e.target.checked)}
                          className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
                        />
                        <span className="text-sm text-foreground">
                          {agent.enumeration} - {agent.label}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </>
          )}
          {field.helpText && (
            <p className="text-xs text-muted-foreground mt-1">
              {field.helpText}
            </p>
          )}
        </div>
      );
    }

    case 'code_editor':
      return (
        <ExpandableCodeEditor
          field={field}
          value={value}
          onChange={onChange}
          config={config}
          upstreamNodes={upstreamNodes}
          workflowId={workflowState?.currentWorkflow?.id || workflowState?.selectedWorkflow?.id || null}
          nodeId={currentNodeId || null}
        />
      );

    case 'input_mapper': {
      const mappings = (typeof value === 'object' && value !== null && !Array.isArray(value))
        ? value
        : {};
      const entries = Object.entries(mappings);

      const updateMapping = (oldKey, newKey, newPath) => {
        const updated = { ...mappings };
        if (oldKey !== newKey) delete updated[oldKey];
        updated[newKey || oldKey] = newPath;
        onChange(field.key, updated);
      };
      const removeMapping = (key) => {
        const updated = { ...mappings };
        delete updated[key];
        onChange(field.key, updated);
      };
      const addMapping = () => {
        onChange(field.key, { ...mappings, [`var_${entries.length}`]: '' });
      };

      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-1.5">
            {field.label}
          </label>

          {entries.length === 0 && (
            <div className="text-xs text-muted-foreground bg-muted/30 rounded-lg p-3 mb-2 space-y-1">
              <p className="font-medium text-foreground">No mappings yet.</p>
              <p>Click <strong>+ Add mapping</strong> to wire upstream data into your script.</p>
              <p className="text-[10px] mt-1.5 leading-relaxed">
                <span className="font-semibold">Variable name</span> (left) = what you use in code as <code className="bg-gray-200 px-1 rounded">inputs["name"]</code><br/>
                <span className="font-semibold">Source path</span> (right) = where the data comes from. Examples:<br/>
                <code className="bg-gray-200 px-1 rounded">node.agent_1.deliverable</code> &mdash; full deliverable from agent_1<br/>
                <code className="bg-gray-200 px-1 rounded">node.agent_1.deliverable.revenue</code> &mdash; a specific field<br/>
                <code className="bg-gray-200 px-1 rounded">deliverables</code> &mdash; all approved deliverables as a list<br/>
                <code className="bg-gray-200 px-1 rounded">variables.my_var</code> &mdash; a workflow variable
              </p>
            </div>
          )}

          <div className="space-y-2">
            {entries.map(([varName, sourcePath], idx) => (
              <div key={idx} className="flex gap-2 items-center">
                <input
                  className="flex-1 px-2 py-1.5 text-xs border border-border rounded bg-background font-mono"
                  placeholder="variable_name"
                  value={varName}
                  onChange={(e) => updateMapping(varName, e.target.value, sourcePath)}
                />
                <span className="text-xs text-muted-foreground font-bold">&larr;</span>
                <input
                  className="flex-[2] px-2 py-1.5 text-xs border border-border rounded bg-background font-mono"
                  placeholder="node.<id>.deliverable"
                  value={sourcePath}
                  onChange={(e) => updateMapping(varName, varName, e.target.value)}
                />
                <button
                  type="button"
                  className="text-xs text-red-500 hover:text-red-700 font-bold px-1"
                  onClick={() => removeMapping(varName)}
                  title="Remove mapping"
                >
                  &times;
                </button>
              </div>
            ))}
          </div>

          <button
            type="button"
            className="mt-2 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            onClick={addMapping}
          >
            + Add mapping
          </button>

          {field.helpText && entries.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">{field.helpText}</p>
          )}
        </div>
      );
    }

    case 'form_schema_builder': {
      const fields = Array.isArray(value) ? value : [];

      const updateField = (idx, patch) => {
        const updated = fields.map((f, i) => (i === idx ? { ...f, ...patch } : f));
        onChange(field.key, updated);
      };
      const removeField = (idx) => {
        onChange(field.key, fields.filter((_, i) => i !== idx));
      };
      const addField = () => {
        onChange(field.key, [
          ...fields,
          { name: `field_${fields.length}`, type: 'text', label: '', required: false },
        ]);
      };

      return (
        <div className="mb-4">
          <label className="block text-sm font-medium text-foreground mb-1.5">
            {field.label}
          </label>

          {fields.length === 0 && (
            <div className="text-xs text-muted-foreground bg-muted/30 rounded-lg p-3 mb-2">
              <p>No runtime fields. The code will run immediately with upstream data only.</p>
              <p className="mt-1">Add fields here to show a form to the user before the code runs. Values arrive in <code className="bg-gray-200 px-1 rounded">inputs["runtime"]["field_name"]</code>.</p>
            </div>
          )}

          <div className="space-y-2">
            {fields.map((f, idx) => (
              <div key={idx} className="flex gap-2 items-center flex-wrap p-2.5 border border-border rounded-lg bg-muted/20">
                <input
                  className="w-24 px-2 py-1.5 text-xs border border-border rounded bg-background font-mono"
                  placeholder="field_name"
                  value={f.name || ''}
                  onChange={(e) => updateField(idx, { name: e.target.value })}
                />
                <select
                  className="w-24 px-2 py-1.5 text-xs border border-border rounded bg-background"
                  value={f.type || 'text'}
                  onChange={(e) => updateField(idx, { type: e.target.value })}
                >
                  <option value="text">Text</option>
                  <option value="number">Number</option>
                  <option value="select">Dropdown</option>
                  <option value="checkbox">Checkbox</option>
                </select>
                <input
                  className="flex-1 px-2 py-1.5 text-xs border border-border rounded bg-background"
                  placeholder="Display label"
                  value={f.label || ''}
                  onChange={(e) => updateField(idx, { label: e.target.value })}
                />
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={!!f.required}
                    onChange={(e) => updateField(idx, { required: e.target.checked })}
                  />
                  Required
                </label>
                <button
                  type="button"
                  className="text-xs text-red-500 hover:text-red-700 font-bold px-1"
                  onClick={() => removeField(idx)}
                  title="Remove field"
                >
                  &times;
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="mt-2 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            onClick={addField}
          >
            + Add runtime field
          </button>
          {field.helpText && fields.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">{field.helpText}</p>
          )}
        </div>
      );
    }

    case 'questions_builder':
      // Full editing happens in a dedicated full-screen tab — the
      // inspector only shows a summary preview that opens the modal.
      // Schema must stay in sync with the ask_user_questions Pydantic
      // model on the backend.
      return (
        <ExpandableQuestionsBuilder
          field={field}
          value={value}
          onChange={onChange}
          contextLabel={config?.label || ''}
        />
      );

    default:
      return (
        <div className="mb-4 text-sm text-muted-foreground">
          Unsupported field type: {field.type}
        </div>
      );
  }
}

