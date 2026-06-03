import React, { useState, useEffect, useRef, useCallback, useMemo, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { authenticatedFetch, API_BASE_URL } from '../../api/client';
import useCodeEditorSession from '../../hooks/useCodeEditorSession';
import AppliedBanner from './AppliedBanner';
import CodeDiffDrawer from './CodeDiffDrawer';
import KnowledgeBaseTablesPanel from './KnowledgeBaseTablesPanel';
import {
  APEX_MONACO_THEME,
  applyApexMonacoTheme,
  defineApexMonacoTheme,
} from '../../theme/monacoApexTheme';

const MonacoEditor = lazy(() => import('@monaco-editor/react'));

const AGENT_STUDIO_COMPLETIONS = [
  { label: 'output.data', kind: 1, insertText: 'output.data(${1:data})', insertTextRules: 4, detail: 'Emit structured data output' },
  { label: 'output.table', kind: 1, insertText: 'output.table(${1:data})', insertTextRules: 4, detail: 'Emit table output' },
  { label: 'output.chart', kind: 1, insertText: 'output.chart(chart_type="${1:bar}", chart_data=${2:data})', insertTextRules: 4, detail: 'Emit chart output' },
  { label: 'output.document', kind: 1, insertText: 'output.document(title="${1:Title}", sections=${2:[]})', insertTextRules: 4, detail: 'Emit document output' },
  { label: 'output.file', kind: 1, insertText: 'output.file("${1:path}")', insertTextRules: 4, detail: 'Emit a file as output' },
  { label: 'output.ask', kind: 1, insertText: 'output.ask(type="${1:text}", prompt="${2:Enter value}")', insertTextRules: 4, detail: 'Pause and ask user for input' },
  { label: 'output.selection', kind: 1, insertText: 'output.selection(options=${1:[]}, prompt="${2:Choose}")', insertTextRules: 4, detail: 'Emit selection widget' },
  { label: 'output.form', kind: 1, insertText: 'output.form(fields=${1:[]})', insertTextRules: 4, detail: 'Emit interactive form' },
  { label: 'output.list', kind: 1, insertText: 'output.list(${1:items})', insertTextRules: 4, detail: 'Emit list output' },
  { label: 'uploads.list', kind: 1, insertText: 'uploads.list()', detail: 'List uploaded files' },
  { label: 'uploads.get', kind: 1, insertText: 'uploads.get("${1:filename}")', insertTextRules: 4, detail: 'Read an uploaded file' },
  { label: 'llm.complete', kind: 1, insertText: 'llm.complete("${1:prompt}")', insertTextRules: 4, detail: 'Call the GenAI proxy LLM' },
  { label: 'inputs', kind: 5, insertText: 'inputs', detail: 'Dict of injected inputs from upstream nodes' },
];

const INPUTS_PANEL_WIDTH_KEY = 'agent-studio.code-editor.inputs-panel-width';
const INPUTS_PANEL_DEFAULT_WIDTH = 360;
const INPUTS_PANEL_MIN_WIDTH = 260;
const INPUTS_PANEL_MAX_WIDTH = 720;

function readStoredInputsPanelWidth() {
  try {
    const n = parseInt(localStorage.getItem(INPUTS_PANEL_WIDTH_KEY), 10);
    if (Number.isFinite(n) && n >= INPUTS_PANEL_MIN_WIDTH && n <= INPUTS_PANEL_MAX_WIDTH) {
      return n;
    }
  } catch {
    /* ignore */
  }
  return INPUTS_PANEL_DEFAULT_WIDTH;
}

function clampInputsPanelWidth(w) {
  return Math.min(INPUTS_PANEL_MAX_WIDTH, Math.max(INPUTS_PANEL_MIN_WIDTH, w));
}

function persistInputsPanelWidth(w) {
  try {
    localStorage.setItem(INPUTS_PANEL_WIDTH_KEY, String(clampInputsPanelWidth(w)));
  } catch {
    /* ignore */
  }
}

// ── JSON Schema → Tree ──────────────────────────────────────────────────

function unwrapSchemaRootData(schema) {
  if (!schema || typeof schema !== 'object') return schema;
  const props = schema.properties;
  if (!props || typeof props !== 'object') return schema;
  const keys = Object.keys(props);
  if (keys.length === 1 && keys[0] === 'data' && props.data && typeof props.data === 'object') {
    return props.data;
  }
  return schema;
}

function jsonSchemaToTree(schema, basePath, maxDepth = 14, depth = 0) {
  if (!schema || depth > maxDepth) return [];
  const nodes = [];

  const jsType = (s) => {
    if (!s) return 'any';
    if (s.type === 'string') return 'str';
    if (s.type === 'integer' || s.type === 'number') return 'num';
    if (s.type === 'boolean') return 'bool';
    if (s.type === 'array') return 'list';
    if (s.type === 'object') return 'dict';
    return 'any';
  };

  if (schema.type === 'object' && schema.properties) {
    for (const [key, prop] of Object.entries(schema.properties)) {
      const path = `${basePath}["${key}"]`;
      const t = jsType(prop);
      const children = [];

      if (prop.type === 'object' && prop.properties) {
        children.push(...jsonSchemaToTree(prop, path, maxDepth, depth + 1));
      } else if (prop.type === 'array' && prop.items) {
        const itemPath = `${path}[0]`;
        const itemT = jsType(prop.items);
        if (prop.items.type === 'object' && prop.items.properties) {
          children.push({
            label: '[i]',
            path: itemPath,
            type: itemT,
            desc: prop.items.title || 'array element',
            children: jsonSchemaToTree(prop.items, itemPath, maxDepth, depth + 1),
          });
        } else {
          children.push({ label: '[i]', path: itemPath, type: itemT, desc: prop.items.description || 'element' });
        }
      }

      nodes.push({
        label: key,
        path,
        type: t,
        desc: prop.description || prop.title || undefined,
        children: children.length ? children : undefined,
      });
    }
  }
  return nodes;
}

function parseOutputSchema(raw) {
  if (!raw) return null;
  try {
    const s = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (s && typeof s === 'object') return s;
  } catch { /* ignore */ }
  return null;
}

// ── Inputs Tree Builder ─────────────────────────────────────────────────

function buildInputsTree(upstreamNodes) {
  return upstreamNodes.map((node, idx) => {
    const isCodeExec = node.type === 'code-executor';
    const nodeLabel = node.label || node.type;
    const dataPath = `inputs["deliverables"][${idx}]["data"]`;

    let dataChildren = [];

    if (isCodeExec) {
      dataChildren = [
        { label: '_output_type', path: `${dataPath}["_output_type"]`, type: 'str', desc: 'e.g. "data", "table", "document"' },
        { label: '_metadata', path: `${dataPath}["_metadata"]`, type: 'dict', desc: 'Title & extra info' },
        { label: '...', path: dataPath, type: 'dict', desc: 'Dynamic — depends on output.* call' },
      ];
    } else {
      const schema = unwrapSchemaRootData(parseOutputSchema(node.config?.outputSchema));
      if (schema) {
        dataChildren = jsonSchemaToTree(schema, dataPath);
      }
      if (dataChildren.length === 0) {
        dataChildren = [
          {
            label: 'sections', path: `${dataPath}["sections"]`, type: 'list',
            desc: 'Document sections',
            children: [{
              label: '[i]', path: `${dataPath}["sections"][0]`, type: 'dict',
              desc: 'Section object',
              children: [
                { label: 'title', path: `${dataPath}["sections"][0]["title"]`, type: 'str' },
                { label: 'type', path: `${dataPath}["sections"][0]["type"]`, type: 'str', desc: '"text" | "table" | "list"' },
                { label: 'content', path: `${dataPath}["sections"][0]["content"]`, type: 'str', desc: 'For type="text"' },
                {
                  label: 'rows', path: `${dataPath}["sections"][0]["rows"]`, type: 'list', desc: 'For type="table"',
                  children: [{ label: '[i]', path: `${dataPath}["sections"][0]["rows"][0]`, type: 'dict', desc: 'Row object' }],
                },
                { label: 'columns', path: `${dataPath}["sections"][0]["columns"]`, type: 'list', desc: 'For type="table"' },
                { label: 'items', path: `${dataPath}["sections"][0]["items"]`, type: 'list', desc: 'For type="list"' },
              ],
            }],
          },
          { label: 'metadata', path: `${dataPath}["metadata"]`, type: 'dict', desc: 'Document metadata' },
          { label: 'title', path: `${dataPath}["title"]`, type: 'str' },
          { label: 'graph', path: `${dataPath}["graph"]`, type: 'dict', desc: 'Process graph (optional)' },
        ];
      }
    }

    return {
      label: nodeLabel,
      annotation: `[${idx}]`,
      path: dataPath,
      type: 'dict',
      desc: `${node.type} — payload at ${dataPath}`,
      icon: isCodeExec ? 'code' : 'agent',
      defaultOpen: true,
      children: dataChildren,
    };
  });
}

const TYPE_COLORS = {
  str: 'text-green-400',
  dict: 'text-yellow-400',
  list: 'text-blue-400',
  num: 'text-[var(--ce-accent)]',
  bool: 'text-pink-400',
  any: 'text-gray-400',
};

const ICON_MAP = {
  code: (
    <svg className="w-3 h-3 text-[var(--ce-review)]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
    </svg>
  ),
  agent: (
    <svg className="w-3 h-3 text-violet-400" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  ),
};

function InputTreeNode({ node, onInsert, depth = 0 }) {
  const [open, setOpen] = useState(node.defaultOpen || false);
  const hasChildren = node.children && node.children.length > 0;

  const handleClick = () => {
    if (hasChildren) {
      setOpen(prev => !prev);
    } else {
      onInsert(node.path);
    }
  };

  const handleInsertThis = (e) => {
    e.stopPropagation();
    onInsert(node.path);
  };

  return (
    <div>
      <div
        onClick={handleClick}
        className={`flex items-center gap-1.5 py-1 px-2 rounded cursor-pointer transition-colors group
          ${hasChildren ? 'hover:bg-[#2a2d32]' : 'hover:bg-[var(--ce-accent-soft)]'}`}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
      >
        {/* Expand/collapse chevron */}
        {hasChildren ? (
          <svg className={`w-3 h-3 text-gray-500 transition-transform shrink-0 ${open ? 'rotate-90' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        ) : (
          <span className="w-3 shrink-0" />
        )}

        {/* Icon for special nodes */}
        {node.icon && ICON_MAP[node.icon]}

        {/* Label */}
        <span className="text-xs font-mono text-gray-200 truncate">{node.label}</span>

        {/* Annotation (node label) */}
        {node.annotation && (
          <span className="text-[10px] text-gray-500 truncate ml-1">
            {node.annotation}
          </span>
        )}

        {/* Type badge */}
        <span className={`text-[10px] ml-auto shrink-0 ${TYPE_COLORS[node.type] || TYPE_COLORS.any}`}>
          {node.type}
        </span>

        {/* Insert button for expandable nodes */}
        {hasChildren && (
          <button
            onClick={handleInsertThis}
            className="opacity-0 group-hover:opacity-100 ml-1 px-1.5 py-0.5 text-[10px] bg-[var(--ce-accent)]/80 text-white rounded transition-opacity shrink-0"
            title={`Insert ${node.path}`}
          >
            +
          </button>
        )}
      </div>

      {/* Description on hover area */}
      {node.desc && !hasChildren && (
        <div className="text-[10px] text-gray-600 truncate" style={{ paddingLeft: `${depth * 14 + 28}px` }}>
          {node.desc}
        </div>
      )}

      {/* Children */}
      {open && hasChildren && node.children.map((child, i) => (
        <InputTreeNode key={i} node={child} onInsert={onInsert} depth={depth + 1} />
      ))}
    </div>
  );
}


// ── SDK Docs Renderer ───────────────────────────────────────────────────
//
// Hand-rolled markdown renderer tuned for the SDK_REFERENCE.md contents.
// We don't pull in react-markdown + remark-gfm because the docs pane is a
// tiny island inside the CodeEditorModal and the bundle diet matters; the
// reference uses a well-known, constrained subset of markdown that's
// cheaper to parse inline.  If the reference ever needs the long tail of
// CommonMark (footnotes, task lists, HTML escapes), swap this out.
//
// Supported surfaces:
//   - H1/H2/H3 headings with auto-generated slugs (for the TOC)
//   - GFM tables with header row + separator
//   - Fenced code blocks (any language); python blocks stay click-to-insert
//   - Inline `code`, **bold**, *italic*, [links](url)
//   - Horizontal rules (`---`)
//   - Blockquotes (`> `)
//   - Nested bullet lists (2-space indent → nesting level)
//   - Ordered lists (`1.` / `2.` …)
//   - A sticky table-of-contents (H2s) + a live search filter
//
// The renderer is pure: it takes the markdown string and produces a
// React tree.  No network calls, no side effects outside of scroll to
// anchors triggered by the TOC.
// ───────────────────────────────────────────────────────────────────────

function slugify(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[`*_~]/g, '')
    .replace(/[^\w\s.-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 80);
}

// Render inline markdown spans (bold, italic, code, links) for a line of
// text.  Returns an array of React nodes suitable for {...} in JSX.
function renderInlineMarkdown(text, keyBase) {
  if (!text) return null;
  const nodes = [];
  // Single regex that matches any inline token.  Order matters: code
  // first so `**not bold**` inside backticks stays literal.
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)|(\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match;
  let idx = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    const key = `${keyBase}-${idx++}`;
    if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(
        <code key={key} className="font-mono text-[10.5px] bg-[var(--ce-bg)] text-[var(--ce-review)] px-1 py-0.5 rounded border border-[var(--ce-border)]">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith('**') && token.endsWith('**')) {
      nodes.push(<strong key={key} className="font-semibold text-gray-200">{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('*') && token.endsWith('*')) {
      nodes.push(<em key={key} className="italic text-gray-300">{token.slice(1, -1)}</em>);
    } else if (token.startsWith('[')) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        nodes.push(
          <a
            key={key}
            href={linkMatch[2]}
            target="_blank"
            rel="noreferrer noopener"
            className="text-[var(--ce-review)] hover:text-[var(--ce-review)] underline decoration-dotted underline-offset-2"
          >
            {linkMatch[1]}
          </a>
        );
      } else {
        nodes.push(token);
      }
    } else {
      nodes.push(token);
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

// Walks the markdown line-by-line and groups it into a list of typed
// blocks.  Keeping parse + render as separate passes lets us reuse the
// block list for the TOC and for search filtering.
function parseMarkdownBlocks(content) {
  const blocks = [];
  const lines = String(content || '').split('\n');
  let i = 0;

  const flushTable = (tableLines, key) => {
    // GFM table: first row = header, second row = separator, rest = body.
    const clean = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
    if (tableLines.length < 2) return;
    const header = clean(tableLines[0]);
    const body = tableLines.slice(2).map(clean);
    blocks.push({ type: 'table', header, rows: body, key });
  };

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.replace(/\s+$/, '');

    // Fenced code block (any language, first fence line ends immediately)
    const fenceMatch = line.match(/^```(\w*)\s*$/);
    if (fenceMatch) {
      const lang = (fenceMatch[1] || '').toLowerCase();
      const codeLines = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }
      i++;  // consume closing fence
      blocks.push({
        type: 'code',
        lang,
        text: codeLines.join('\n'),
        insertable: lang === 'python' || lang === 'py',
        key: blocks.length,
      });
      continue;
    }

    // Horizontal rule
    if (/^---+\s*$/.test(line)) {
      blocks.push({ type: 'hr', key: blocks.length });
      i++;
      continue;
    }

    // GFM table (must have at least one `|` and a separator row next)
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-+/.test(lines[i + 1])) {
      const tableLines = [line];
      i++;
      while (i < lines.length && lines[i].includes('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      flushTable(tableLines, blocks.length);
      continue;
    }

    // Headings
    if (line.startsWith('### ')) {
      const text = line.replace(/^###\s*/, '');
      blocks.push({ type: 'h3', text, slug: slugify(text), key: blocks.length });
      i++;
      continue;
    }
    if (line.startsWith('## ')) {
      const text = line.replace(/^##\s*/, '');
      blocks.push({ type: 'h2', text, slug: slugify(text), key: blocks.length });
      i++;
      continue;
    }
    if (line.startsWith('# ')) {
      const text = line.replace(/^#\s*/, '');
      blocks.push({ type: 'h1', text, slug: slugify(text), key: blocks.length });
      i++;
      continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      const quoteLines = [line.slice(2)];
      i++;
      while (i < lines.length && lines[i].startsWith('> ')) {
        quoteLines.push(lines[i].slice(2));
        i++;
      }
      blocks.push({ type: 'quote', text: quoteLines.join(' '), key: blocks.length });
      continue;
    }

    // Unordered list (allow nesting by leading spaces, 2-space indent)
    const ulMatch = line.match(/^(\s*)[-*]\s+(.*)$/);
    if (ulMatch) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)[-*]\s+(.*)$/);
        if (!m) break;
        items.push({ depth: Math.floor(m[1].length / 2), text: m[2] });
        i++;
        // Allow a continuation line (indented further) to glue onto the previous item.
        while (
          i < lines.length &&
          /^\s+\S/.test(lines[i]) &&
          !/^\s*[-*]\s+/.test(lines[i]) &&
          !/^\s*\d+\.\s+/.test(lines[i])
        ) {
          items[items.length - 1].text += ' ' + lines[i].trim();
          i++;
        }
      }
      blocks.push({ type: 'ul', items, key: blocks.length });
      continue;
    }

    // Ordered list
    const olMatch = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
    if (olMatch) {
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)(\d+)\.\s+(.*)$/);
        if (!m) break;
        items.push({ depth: Math.floor(m[1].length / 2), text: m[3] });
        i++;
      }
      blocks.push({ type: 'ol', items, key: blocks.length });
      continue;
    }

    // Paragraph — join consecutive non-blank lines into a single block.
    if (line.trim()) {
      const paraLines = [line];
      i++;
      while (
        i < lines.length &&
        lines[i].trim() &&
        !lines[i].startsWith('#') &&
        !/^```/.test(lines[i]) &&
        !/^---+\s*$/.test(lines[i]) &&
        !/^\s*[-*]\s+/.test(lines[i]) &&
        !/^\s*\d+\.\s+/.test(lines[i]) &&
        !lines[i].startsWith('> ')
      ) {
        paraLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'p', text: paraLines.join(' '), key: blocks.length });
      continue;
    }

    i++;  // blank line
  }

  return blocks;
}

function SdkDocsRenderer({ content, onInsert }) {
  const [query, setQuery] = useState('');
  const containerRef = useRef(null);

  const blocks = useMemo(() => parseMarkdownBlocks(content), [content]);

  // TOC is just the H2 set — H1 is the document title, H3s are noisy.
  const toc = useMemo(
    () => blocks.filter(b => b.type === 'h2').map(b => ({ text: b.text, slug: b.slug })),
    [blocks]
  );

  const needle = query.trim().toLowerCase();

  // When a search is active we keep any heading that introduces a
  // matching section visible, so the user can still see where each hit
  // lives.  We do this in a single pass: walk forward, carry the most
  // recent headings, and when a match hits, flush the headings + match.
  const visibleKeys = useMemo(() => {
    if (!needle) return null;
    const matchesBlock = (b) => {
      const haystack = (b.text || '')
        + (b.items ? ' ' + b.items.map(it => it.text).join(' ') : '')
        + (b.rows ? ' ' + b.rows.map(r => r.join(' ')).join(' ') : '')
        + (b.header ? ' ' + b.header.join(' ') : '');
      return haystack.toLowerCase().includes(needle);
    };
    const keep = new Set();
    let pendingH1 = null;
    let pendingH2 = null;
    let pendingH3 = null;
    for (const b of blocks) {
      if (b.type === 'h1') { pendingH1 = b; continue; }
      if (b.type === 'h2') { pendingH2 = b; pendingH3 = null; continue; }
      if (b.type === 'h3') { pendingH3 = b; continue; }
      if (matchesBlock(b)) {
        if (pendingH1) { keep.add(pendingH1.key); pendingH1 = null; }
        if (pendingH2) { keep.add(pendingH2.key); pendingH2 = null; }
        if (pendingH3) { keep.add(pendingH3.key); pendingH3 = null; }
        keep.add(b.key);
      }
    }
    return keep;
  }, [blocks, needle]);

  const scrollToSlug = (slug) => {
    const root = containerRef.current;
    if (!root) return;
    const target = root.querySelector(`[data-slug="${slug}"]`);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const renderBlock = (b) => {
    if (visibleKeys && !visibleKeys.has(b.key)) return null;
    switch (b.type) {
      case 'h1':
        return (
          <h1 key={b.key} data-slug={b.slug} className="text-base font-bold text-gray-100 mt-1 mb-2 tracking-tight">
            {renderInlineMarkdown(b.text, b.key)}
          </h1>
        );
      case 'h2':
        return (
          <h2
            key={b.key}
            data-slug={b.slug}
            className="text-[13px] font-bold text-[var(--ce-review)] mt-5 mb-2 pb-1 border-b border-[var(--ce-border)] scroll-mt-2 uppercase tracking-wider"
          >
            {renderInlineMarkdown(b.text, b.key)}
          </h2>
        );
      case 'h3':
        return (
          <h3
            key={b.key}
            data-slug={b.slug}
            className="text-[12px] font-semibold text-gray-200 mt-4 mb-1.5 font-mono"
          >
            {renderInlineMarkdown(b.text, b.key)}
          </h3>
        );
      case 'p':
        return (
          <p key={b.key} className="text-[11.5px] text-gray-400 leading-relaxed mb-2">
            {renderInlineMarkdown(b.text, b.key)}
          </p>
        );
      case 'quote':
        return (
          <blockquote key={b.key} className="border-l-2 border-[var(--ce-review)]/60 pl-3 py-0.5 mb-2 text-[11.5px] text-gray-400 italic">
            {renderInlineMarkdown(b.text, b.key)}
          </blockquote>
        );
      case 'hr':
        return <div key={b.key} className="my-4 border-t border-[var(--ce-border)]" />;
      case 'ul':
        return (
          <ul key={b.key} className="mb-2 space-y-1">
            {b.items.map((it, idx) => (
              <li
                key={idx}
                className="flex items-start gap-1.5 text-[11.5px] text-gray-400 leading-relaxed"
                style={{ paddingLeft: `${Math.min(it.depth, 3) * 12}px` }}
              >
                <span className="text-gray-600 select-none mt-[5px] shrink-0">•</span>
                <span>{renderInlineMarkdown(it.text, `${b.key}-${idx}`)}</span>
              </li>
            ))}
          </ul>
        );
      case 'ol':
        return (
          <ol key={b.key} className="mb-2 space-y-1 list-decimal pl-5 marker:text-gray-600">
            {b.items.map((it, idx) => (
              <li
                key={idx}
                className="text-[11.5px] text-gray-400 leading-relaxed pl-1"
                style={{ marginLeft: `${Math.min(it.depth, 3) * 12}px` }}
              >
                {renderInlineMarkdown(it.text, `${b.key}-${idx}`)}
              </li>
            ))}
          </ol>
        );
      case 'table':
        return (
          <div key={b.key} className="mb-3 overflow-x-auto rounded border border-[var(--ce-border)]">
            <table className="w-full text-[11px] border-collapse">
              <thead className="bg-[#2a2a2a] text-gray-300">
                <tr>
                  {b.header.map((h, i) => (
                    <th key={i} className="text-left font-semibold px-2 py-1.5 border-b border-[var(--ce-border)] whitespace-nowrap">
                      {renderInlineMarkdown(h, `${b.key}-th-${i}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-gray-400">
                {b.rows.map((row, r) => (
                  <tr key={r} className="odd:bg-[#232323] even:bg-[#262626]">
                    {row.map((cell, c) => (
                      <td key={c} className="px-2 py-1.5 align-top border-t border-[#2f2f2f]">
                        {renderInlineMarkdown(cell, `${b.key}-td-${r}-${c}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      case 'code': {
        const insertable = b.insertable && typeof onInsert === 'function';
        const Tag = insertable ? 'button' : 'div';
        const label = b.lang ? b.lang.toUpperCase() : 'CODE';
        return (
          <div key={b.key} className="mb-3">
            <div className="flex items-center justify-between bg-[#1a1a1a] px-2 py-1 border border-b-0 border-[var(--ce-border)] rounded-t text-[9.5px] uppercase tracking-wider text-gray-500">
              <span>{label}</span>
              {insertable && <span className="text-[var(--ce-review)]/80">click to insert ↵</span>}
            </div>
            <Tag
              onClick={insertable ? () => onInsert(b.text) : undefined}
              className={
                'block w-full text-left font-mono text-[11px] leading-relaxed text-[var(--ce-review)] bg-[#141414] rounded-b border border-[var(--ce-border)] px-3 py-2 whitespace-pre overflow-x-auto '
                + (insertable ? 'hover:border-[var(--ce-review)]/60 hover:bg-[var(--ce-success-bg)] transition-colors cursor-pointer' : '')
              }
            >
              {b.text}
            </Tag>
          </div>
        );
      }
      default:
        return null;
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Search + TOC header — sticky so they stay available while
          scrolling through the body.  TOC only shows H2s to keep it
          digestible; click to scroll. */}
      <div className="sticky top-0 z-10 bg-[var(--ce-panel)] border-b border-[var(--ce-border)] px-3 py-2 space-y-2 shrink-0">
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search SDK docs…"
            className="w-full bg-[var(--ce-bg)] border border-[var(--ce-border)] rounded pl-7 pr-2 py-1.5 text-[11px] text-gray-200 placeholder-gray-600 focus:outline-none focus:border-[var(--ce-review)]/70"
          />
          <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="11" cy="11" r="7" />
            <path strokeLinecap="round" d="M21 21l-4.35-4.35" />
          </svg>
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-500 hover:text-gray-300 px-1"
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>
        {toc.length > 0 && !query && (
          <div className="flex flex-wrap gap-1">
            {toc.map((item) => (
              <button
                key={item.slug}
                type="button"
                onClick={() => scrollToSlug(item.slug)}
                className="px-1.5 py-0.5 text-[10px] rounded bg-[var(--ce-surface)] hover:bg-[#3a3a3a] text-gray-400 hover:text-gray-200 border border-[var(--ce-border)] transition-colors"
              >
                {item.text}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Body */}
      <div ref={containerRef} className="flex-1 overflow-y-auto min-h-0 px-4 py-3">
        {blocks.map(renderBlock)}
        {needle && visibleKeys && visibleKeys.size === 0 && (
          <div className="text-center text-[11px] text-gray-500 py-8">
            No matches for "{query}".
          </div>
        )}
      </div>
    </div>
  );
}


// ── Main Modal ──────────────────────────────────────────────────────────

export default function CodeEditorModal({
  isOpen,
  onClose,
  code,
  onSave,
  config,
  upstreamNodes = [],
  workflowId = null,
  nodeId = null,
}) {
  const [localCode, setLocalCode] = useState(code || '');
  const [validationResult, setValidationResult] = useState(null);
  const [validating, setValidating] = useState(false);
  const [inputsPanelOpen, setInputsPanelOpen] = useState(true);
  const [inputsPanelWidth, setInputsPanelWidth] = useState(() => readStoredInputsPanelWidth());
  const [rightPanel, setRightPanel] = useState(null); // null | 'ai' | 'docs' | 'versions'
  const knowledgeBaseIdsRaw = config?.knowledgeBaseIds;
  // Stable reference as long as the underlying IDs don't change.
  const knowledgeBaseIdsKey = Array.isArray(knowledgeBaseIdsRaw)
    ? knowledgeBaseIdsRaw.join(',')
    : '';
  const knowledgeBaseIds = useMemo(
    () => (Array.isArray(knowledgeBaseIdsRaw) ? knowledgeBaseIdsRaw.filter(Boolean) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- memoize by stringified key
    [knowledgeBaseIdsKey],
  );
  const hasKnowledgeBases = knowledgeBaseIds.length > 0;
  const [leftPanelOpen, setLeftPanelOpen] = useState(false);
  useEffect(() => {
    // Open the Tables panel automatically whenever at least one KB is
    // configured on the node.  Close it if they're all removed.
    setLeftPanelOpen(hasKnowledgeBases);
  }, [hasKnowledgeBases]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [sdkDocs, setSdkDocs] = useState(null);
  // Image attachments for the AI code generator.  Each entry:
  //   { id: string, name: string, dataUrl: string, size: number }
  const [attachedImages, setAttachedImages] = useState([]);
  const [attachError, setAttachError] = useState('');
  // Floating banner shown after we auto-apply a code reply.  Persists
  // until the user hits Keep, Revert, or starts hand-editing the buffer.
  const [appliedBanner, setAppliedBanner] = useState(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const editorRef = useRef(null);
  const chatEndRef = useRef(null);
  const chatInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const inputsResizeRef = useRef({ active: false, startX: 0, startWidth: INPUTS_PANEL_DEFAULT_WIDTH });
  // Guard so our own `editor.setValue(newCode)` doesn't dismiss the banner
  // via the Monaco onChange it emits.
  const suppressNextChangeRef = useRef(false);
  // Prevents a double-push when the Ask-AI-to-fix shortcut is clicked while
  // another request is in flight.
  const askFixBusyRef = useRef(false);

  const {
    messages: chatMessages,
    versions,
    currentVersionId,
    pushUserTurn,
    pushAssistantTurn,
    restoreVersion,
    markVersionReverted,
    clear: clearSession,
  } = useCodeEditorSession({ workflowId, nodeId });

  const inputsTree = buildInputsTree(upstreamNodes);

  useEffect(() => {
    if (isOpen) {
      setLocalCode(code || '');
      setValidationResult(null);
      setAppliedBanner(null);
      setDiffOpen(false);
      setToast(null);
    }
  }, [isOpen, code]);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        onSave(localCode);
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, localCode, onClose, onSave]);

  useEffect(() => {
    if (isOpen) document.body.style.overflow = 'hidden';
    else document.body.style.overflow = '';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  useEffect(() => {
    if (rightPanel === 'docs' && sdkDocs === null) {
      authenticatedFetch(`${API_BASE_URL}/api/code-executor/sdk-reference`)
        .then(r => {
          if (!r.ok) throw new Error(`Server returned ${r.status}`);
          return r.json();
        })
        .then(d => setSdkDocs(d.content || 'No SDK documentation found.'))
        .catch(err => setSdkDocs(`Failed to load SDK documentation: ${err.message}`));
    }
  }, [rightPanel, sdkDocs]);

  const insertAtCursor = useCallback((text) => {
    const editor = editorRef.current;
    if (!editor) return;
    const position = editor.getPosition();
    const lineContent = editor.getModel().getLineContent(position.lineNumber);
    const isEmptyLine = lineContent.trim() === '';

    const snippet = isEmptyLine ? text : `\n${text}`;
    editor.executeEdits('inputs-browser', [{
      range: {
        startLineNumber: position.lineNumber,
        startColumn: isEmptyLine ? 1 : lineContent.length + 1,
        endLineNumber: position.lineNumber,
        endColumn: isEmptyLine ? 1 : lineContent.length + 1,
      },
      text: snippet,
    }]);
    editor.focus();
  }, []);

  const handleEditorBeforeMount = useCallback((monaco) => {
    defineApexMonacoTheme(monaco);
  }, []);

  const handleEditorMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    window.monaco = monaco;
    applyApexMonacoTheme(monaco);
    editor.focus();

    editor.addAction({
      id: 'save-code',
      label: 'Save and Close',
      keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
      run: () => {
        onSave(editor.getValue());
        onClose();
      },
    });

    monaco.languages.registerCompletionItemProvider('python', {
      provideCompletionItems: (model, position) => {
        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };
        return { suggestions: AGENT_STUDIO_COMPLETIONS.map(c => ({ ...c, range })) };
      },
    });
  }, [onSave, onClose]);

  const handleValidate = async () => {
    setValidationResult(null);
    setValidating(true);
    try {
      const resp = await authenticatedFetch(`${API_BASE_URL}/api/code-executor/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: localCode }),
      });
      if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
      const data = await resp.json();
      setValidationResult(data);
      if (editorRef.current && window.monaco) {
        const model = editorRef.current.getModel();
        if (data.violations?.length) {
          const markers = data.violations.map((v) => {
            const lineMatch = v.match(/line (\d+)/i);
            const line = lineMatch ? parseInt(lineMatch[1], 10) : 1;
            return {
              severity: window.monaco.MarkerSeverity.Error,
              message: v,
              startLineNumber: line, startColumn: 1,
              endLineNumber: line, endColumn: model?.getLineMaxColumn(line) || 100,
            };
          });
          window.monaco.editor.setModelMarkers(model, 'code-validator', markers);
        } else {
          window.monaco.editor.setModelMarkers(model, 'code-validator', []);
        }
      }
    } catch (err) {
      setValidationResult({ valid: false, violations: [`Backend error: ${err.message}`] });
    } finally {
      setValidating(false);
    }
  };

  // ── Image attachment handling (AI code generator) ──────────────────────
  // Mirror the backend's limits so users get instant feedback without a
  // round-trip.  Keep these in sync with `_MAX_IMAGES_PER_REQUEST` and
  // `_MAX_IMAGE_BYTES` in `code_executor_routes.py`.
  const MAX_IMAGES = 6;
  const MAX_IMAGE_BYTES = 6 * 1024 * 1024;
  const ALLOWED_IMAGE_MIME = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

  const readFileAsDataUrl = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });

  const addImageFiles = async (fileList) => {
    const files = Array.from(fileList || []);
    if (files.length === 0) return;
    setAttachError('');
    const next = [...attachedImages];
    for (const file of files) {
      if (!ALLOWED_IMAGE_MIME.includes(file.type)) {
        setAttachError(`Unsupported file type: ${file.type || 'unknown'}`);
        continue;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        setAttachError(`"${file.name}" exceeds ${MAX_IMAGE_BYTES / (1024 * 1024)} MB limit`);
        continue;
      }
      if (next.length >= MAX_IMAGES) {
        setAttachError(`Maximum ${MAX_IMAGES} images per request`);
        break;
      }
      try {
        const dataUrl = await readFileAsDataUrl(file);
        next.push({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          name: file.name || 'pasted-image',
          dataUrl,
          size: file.size,
        });
      } catch (err) {
        setAttachError(`Could not read "${file.name}": ${err.message}`);
      }
    }
    setAttachedImages(next);
  };

  const handleImagePaste = (e) => {
    const items = e.clipboardData?.items;
    if (!items || items.length === 0) return;
    const files = [];
    for (const item of items) {
      if (item.kind === 'file') {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      addImageFiles(files);
    }
  };

  const removeAttachedImage = (id) => {
    setAttachedImages(prev => prev.filter(img => img.id !== id));
    setAttachError('');
  };

  const handleApplyCode = useCallback((newCode) => {
    // Flag this as a programmatic change so the banner's auto-dismiss
    // doesn't trigger on the resulting Monaco onChange event.
    suppressNextChangeRef.current = true;
    setLocalCode(newCode);
    setValidationResult(null);
    if (editorRef.current) {
      editorRef.current.setValue(newCode);
      editorRef.current.focus();
    }
  }, []);

  // Serialize the in-memory session into the `ChatTurn[]` shape the backend
  // expects, dropping any display-only fields (thumbnails, ts, message id).
  const buildChatHistoryForApi = useCallback((source) => {
    return (source || []).map((m) => {
      if (m.role === 'user') {
        const imgs = (m.images || [])
          .map((i) => (typeof i === 'string' ? i : i?.dataUrl))
          .filter(Boolean);
        return {
          role: 'user',
          content: m.content || '',
          images: imgs,
        };
      }
      // assistant
      const isCode = (m.kind || 'code') === 'code';
      return {
        role: 'assistant',
        content: isCode
          ? m.summary || m.content || ''
          : m.question || m.content || '',
        kind: m.kind || 'code',
        code: isCode && typeof m.code === 'string' ? m.code : null,
        summary: m.summary || '',
        images: [],
      };
    });
  }, []);

  // Core send.  `overridePrompt` lets the Ask-AI-to-fix / chip-reply flows
  // dispatch a synthesized user turn without the text having to round-trip
  // through the chat input.
  const sendChatRequest = useCallback(
    async ({ prompt, images = [] }) => {
      if (chatLoading) return;
      const trimmed = (prompt || '').trim();
      if (!trimmed && images.length === 0) return;

      setAttachError('');
      setChatLoading(true);

      // Snapshot history BEFORE pushing this user turn — that's the
      // "prior conversation" the backend should see.
      const historyForApi = buildChatHistoryForApi(chatMessages);

      pushUserTurn({
        content: trimmed,
        images: images.map((i) => ({ dataUrl: i.dataUrl, name: i.name })),
      });

      try {
        const upstreamSummary = upstreamNodes.map((n, i) => {
          const schema = n.config?.outputSchema;
          const schemaStr = schema
            ? typeof schema === 'string'
              ? schema
              : JSON.stringify(schema)
            : null;
          return {
            index: i,
            label: n.label || n.type,
            type: n.type,
            output_schema: schemaStr || undefined,
          };
        });

        const resp = await authenticatedFetch(
          `${API_BASE_URL}/api/code-executor/generate-code`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: trimmed,
              context: {
                existing_code: localCode || undefined,
                allowed_imports: config?.allowedImports || [],
                upstream_nodes:
                  upstreamSummary.length > 0
                    ? JSON.stringify(upstreamSummary)
                    : undefined,
              },
              knowledge_base_ids: knowledgeBaseIds.length > 0
                ? knowledgeBaseIds
                : undefined,
              images: images.map((i) => i.dataUrl),
              chat_history: historyForApi,
            }),
          },
        );
        if (!resp.ok) {
          let detail = `Server returned ${resp.status}`;
          try {
            const errBody = await resp.json();
            if (errBody?.detail) detail = errBody.detail;
          } catch {
            /* keep the generic detail */
          }
          throw new Error(detail);
        }
        const data = await resp.json();
        const envelopeKind = data.kind || (data.code ? 'code' : 'code');

        if (envelopeKind === 'clarify') {
          pushAssistantTurn({
            kind: 'clarify',
            content: data.question || data.explanation || '',
            question: data.question || data.explanation || '',
            options: Array.isArray(data.options) ? data.options : [],
            summary: '',
            valid: true,
            violations: [],
          });
        } else {
          const newCode = data.code || '';
          const summary =
            data.summary ||
            data.explanation ||
            "Here's the generated code:";
          const prevCode = localCode;

          const { versionId } = pushAssistantTurn({
            kind: 'code',
            content: summary,
            summary,
            code: newCode,
            assumptions: Array.isArray(data.assumptions) ? data.assumptions : [],
            valid: data.valid !== false,
            violations: Array.isArray(data.violations) ? data.violations : [],
            prevCode,
          });

          // Instant-apply + banner — Cursor-style.
          if (newCode) {
            handleApplyCode(newCode);
            setAppliedBanner({
              versionId,
              summary,
              prevCode,
              newCode,
              truncated: newCode.length > 200_000,
            });
          }
        }
      } catch (err) {
        pushAssistantTurn({
          kind: 'code',
          content: `Error: ${err.message}`,
          summary: `Error: ${err.message}`,
          code: null,
          valid: false,
          violations: [],
        });
      } finally {
        setChatLoading(false);
        setTimeout(() => chatInputRef.current?.focus(), 50);
      }
    },
    [
      chatLoading,
      chatMessages,
      buildChatHistoryForApi,
      pushUserTurn,
      pushAssistantTurn,
      upstreamNodes,
      localCode,
      config?.allowedImports,
      handleApplyCode,
      knowledgeBaseIds,
    ],
  );

  const handleChatSend = async () => {
    const prompt = chatInput.trim();
    if ((!prompt && attachedImages.length === 0) || chatLoading) return;
    const sentImages = attachedImages;
    setChatInput('');
    setAttachedImages([]);
    await sendChatRequest({ prompt, images: sentImages });
  };

  // Auto-reply shortcut for clarify chips and the "Ask AI to fix" button.
  const handleSyntheticSend = useCallback(
    async (text) => {
      const prompt = (text || '').trim();
      if (!prompt || chatLoading || askFixBusyRef.current) return;
      askFixBusyRef.current = true;
      try {
        await sendChatRequest({ prompt, images: [] });
      } finally {
        askFixBusyRef.current = false;
      }
    },
    [chatLoading, sendChatRequest],
  );

  // ── Banner / diff / versions handlers ─────────────────────────────────

  const showToast = useCallback((payload) => {
    setToast(payload);
    // Auto-dismiss after 5s — matches Cursor's undo toast.
    setTimeout(() => setToast((t) => (t === payload ? null : t)), 5000);
  }, []);

  const handleKeepApplied = useCallback(() => {
    setAppliedBanner(null);
    setDiffOpen(false);
  }, []);

  const handleRevertApplied = useCallback(() => {
    if (!appliedBanner) return;
    const { versionId, prevCode, summary } = appliedBanner;
    handleApplyCode(prevCode || '');
    if (versionId) markVersionReverted(versionId, true);
    setAppliedBanner(null);
    setDiffOpen(false);
    showToast({
      type: 'reverted',
      summary,
      versionId,
      newCode: appliedBanner.newCode,
      prevCode,
    });
  }, [appliedBanner, handleApplyCode, markVersionReverted, showToast]);

  const handleReapply = useCallback(
    (versionId, newCode, prevCode, summary) => {
      handleApplyCode(newCode);
      if (versionId) markVersionReverted(versionId, false);
      setAppliedBanner({
        versionId,
        summary,
        prevCode,
        newCode,
        truncated: (newCode || '').length > 200_000,
      });
      setToast(null);
    },
    [handleApplyCode, markVersionReverted],
  );

  const handleOpenDiff = useCallback(() => setDiffOpen(true), []);
  const handleCloseDiff = useCallback(() => setDiffOpen(false), []);

  const handleRestoreVersion = useCallback(
    (version) => {
      if (!version) return;
      const prevCode = localCode;
      handleApplyCode(version.code || '');
      restoreVersion(version.id);
      setAppliedBanner({
        versionId: version.id,
        summary: version.summary || 'Restored version',
        prevCode,
        newCode: version.code || '',
        truncated: !!version.truncated,
      });
    },
    [handleApplyCode, localCode, restoreVersion],
  );

  const handleClearSession = useCallback(() => {
    clearSession();
    setAppliedBanner(null);
    setDiffOpen(false);
    setToast(null);
    setShowClearConfirm(false);
  }, [clearSession]);

  const togglePanel = (panel) => setRightPanel(prev => prev === panel ? null : panel);

  const handleInputsPanelWidthChange = useCallback((e) => {
    const w = clampInputsPanelWidth(Number(e.target.value));
    setInputsPanelWidth(w);
    persistInputsPanelWidth(w);
  }, []);

  const handleInputsResizePointerDown = useCallback((e) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    inputsResizeRef.current = {
      active: true,
      startX: e.clientX,
      startWidth: inputsPanelWidth,
    };
  }, [inputsPanelWidth]);

  const handleInputsResizePointerMove = useCallback((e) => {
    if (!inputsResizeRef.current.active) return;
    const delta = inputsResizeRef.current.startX - e.clientX;
    setInputsPanelWidth(clampInputsPanelWidth(inputsResizeRef.current.startWidth + delta));
  }, []);

  const handleInputsResizePointerUp = useCallback((e) => {
    if (!inputsResizeRef.current.active) return;
    inputsResizeRef.current.active = false;
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    setInputsPanelWidth((w) => {
      persistInputsPanelWidth(w);
      return w;
    });
  }, []);

  if (!isOpen) return null;

  const modal = (
    <div className="code-editor-modal fixed inset-0 z-50 flex bg-black/60">
      <div className="flex flex-col w-full h-full bg-[var(--ce-bg)]" onClick={e => e.stopPropagation()}>

        {/* ── Title bar ── */}
        <div className="flex items-center justify-between px-4 py-2 bg-[var(--ce-panel)] border-b border-[var(--ce-border)] shrink-0">
          <div className="flex items-center gap-3">
            <svg className="w-4 h-4 text-[var(--ce-accent)]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            <span className="text-sm font-medium text-[var(--ce-text)]">Code Editor</span>
            <span className="text-xs text-[var(--ce-muted)]">Python</span>
            {validationResult && (
              <span className={`text-xs px-2 py-0.5 rounded-full ${validationResult.valid ? 'bg-[var(--ce-success-bg)] text-[var(--ce-success)]' : 'bg-[var(--ce-error-bg)] text-[var(--ce-error)]'}`}>
                {validationResult.valid ? 'Valid' : `${validationResult.violations.length} error(s)`}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={handleValidate} disabled={validating}
              className="px-3 py-1.5 text-xs rounded bg-[var(--ce-btn)] text-[var(--ce-text)] hover:bg-[var(--ce-border)] border border-[var(--ce-border)] transition-colors disabled:opacity-50">
              {validating ? 'Checking...' : 'Validate'}
            </button>
            {hasKnowledgeBases && (
              <button onClick={() => setLeftPanelOpen(p => !p)}
                className={`px-3 py-1.5 text-xs rounded border transition-colors flex items-center gap-1.5 ${
                  leftPanelOpen ? 'bg-[var(--ce-initiator)] text-white border-[var(--ce-initiator)]' : 'bg-[var(--ce-btn)] text-[var(--ce-text)] hover:bg-[var(--ce-border)] border-[var(--ce-border)]'
                }`}>
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <ellipse cx="12" cy="6" rx="8" ry="3" />
                  <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
                  <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
                </svg>
                Tables
                <span className={`text-[10px] px-1 rounded-full ${leftPanelOpen ? 'bg-[var(--ce-initiator)]' : 'bg-[var(--ce-border)]'}`}>
                  {knowledgeBaseIds.length}
                </span>
              </button>
            )}
            <button onClick={() => togglePanel('docs')}
              className={`px-3 py-1.5 text-xs rounded border transition-colors flex items-center gap-1.5 ${
                rightPanel === 'docs' ? 'bg-[var(--ce-review)] text-white border-[var(--ce-review)]' : 'bg-[var(--ce-btn)] text-[var(--ce-text)] hover:bg-[var(--ce-border)] border-[var(--ce-border)]'
              }`}>
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.746 0 3.332.477 4.5 1.253v13C19.832 18.477 18.246 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
              Docs
            </button>
            <button onClick={() => setInputsPanelOpen((p) => !p)}
              className={`px-3 py-1.5 text-xs rounded border transition-colors flex items-center gap-1.5 ${
                inputsPanelOpen ? 'bg-[var(--ce-logic)] text-white border-[var(--ce-logic)]' : 'bg-[var(--ce-btn)] text-[var(--ce-text)] hover:bg-[var(--ce-border)] border-[var(--ce-border)]'
              }`}>
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
              </svg>
              Inputs
              {upstreamNodes.length > 0 && (
                <span className={`text-[10px] px-1 rounded-full ${inputsPanelOpen ? 'bg-[var(--ce-logic)]' : 'bg-[var(--ce-border)]'}`}>
                  {upstreamNodes.length}
                </span>
              )}
            </button>
            <button onClick={() => togglePanel('ai')}
              className={`px-3 py-1.5 text-xs rounded border transition-colors flex items-center gap-1.5 ${
                rightPanel === 'ai' ? 'bg-[var(--ce-accent)] text-white border-[var(--ce-accent)]' : 'bg-[var(--ce-btn)] text-[var(--ce-text)] hover:bg-[var(--ce-border)] border-[var(--ce-border)]'
              }`}>
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              AI Assistant
            </button>
            <button onClick={() => togglePanel('versions')}
              className={`px-3 py-1.5 text-xs rounded border transition-colors flex items-center gap-1.5 ${
                rightPanel === 'versions' ? 'bg-[var(--ce-accent)] text-white border-[var(--ce-accent)]' : 'bg-[var(--ce-btn)] text-[var(--ce-text)] hover:bg-[var(--ce-border)] border-[var(--ce-border)]'
              }`}>
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Versions
              {versions.length > 0 && (
                <span className={`text-[10px] px-1 rounded-full ${rightPanel === 'versions' ? 'bg-[var(--ce-accent-hover)]' : 'bg-[var(--ce-border)]'}`}>
                  {versions.length}
                </span>
              )}
            </button>
            <div className="w-px h-5 bg-[#505050] mx-1" />
            <button onClick={() => { onSave(localCode); onClose(); }}
              className="px-4 py-1.5 text-xs rounded bg-[var(--ce-cta)] text-white hover:bg-[var(--ce-cta-hover)] transition-colors font-medium">
              Save
            </button>
            <button onClick={onClose}
              className="px-3 py-1.5 text-xs rounded bg-[var(--ce-btn)] text-gray-400 hover:bg-[var(--ce-border)] hover:text-gray-200 border border-[var(--ce-border)] transition-colors">
              Cancel
            </button>
          </div>
        </div>

        {/* ── Validation bar ── */}
        {validationResult && !validationResult.valid && (
          <div className="px-4 py-2 bg-red-900/30 border-b border-red-800/50 shrink-0">
            <div className="flex items-center gap-2 text-xs text-red-300">
              <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="truncate">{validationResult.violations.join(' · ')}</span>
            </div>
          </div>
        )}

        {/* ── Main content ── */}
        <div className="flex flex-1 min-h-0">

          {/* Left panel: Knowledge Base tables (only when configured) */}
          {leftPanelOpen && hasKnowledgeBases && (
            <div className="w-[280px] flex flex-col border-r border-[var(--ce-border)] bg-[var(--ce-panel)] shrink-0">
              <div className="px-3 py-2 border-b border-[var(--ce-border)] shrink-0 flex items-center gap-2">
                <svg className="w-4 h-4 text-teal-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <ellipse cx="12" cy="6" rx="8" ry="3" />
                  <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
                  <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
                </svg>
                <span className="text-sm font-medium text-gray-200 flex-1">
                  KB Tables
                </span>
                <button
                  type="button"
                  onClick={() => setLeftPanelOpen(false)}
                  className="text-gray-500 hover:text-gray-200"
                  aria-label="Close tables panel"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="flex-1 min-h-0 flex flex-col">
                <KnowledgeBaseTablesPanel
                  knowledgeBaseIds={knowledgeBaseIds}
                  onInsert={insertAtCursor}
                />
              </div>
            </div>
          )}

          {/* Editor pane */}
          <div className="flex-1 min-w-0 flex flex-col">
            {appliedBanner && (
              <AppliedBanner
                summary={appliedBanner.summary}
                truncated={appliedBanner.truncated}
                onKeep={handleKeepApplied}
                onRevert={handleRevertApplied}
                onViewDiff={handleOpenDiff}
              />
            )}
            {toast && (
              <div className="px-4 pt-3 shrink-0">
                <div className="flex items-center gap-3 px-3 py-2 rounded-lg border border-amber-500/40 bg-amber-900/30 backdrop-blur-sm shadow-lg">
                  <svg
                    className="w-4 h-4 text-amber-300 shrink-0"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 14l-4-4m0 0l4-4m-4 4h14a4 4 0 010 8h-1"
                    />
                  </svg>
                  <span className="text-sm text-gray-100 truncate flex-1">
                    Undone: {toast.summary || 'change reverted'}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      handleReapply(
                        toast.versionId,
                        toast.newCode,
                        toast.prevCode,
                        toast.summary,
                      )
                    }
                    className="px-2.5 py-1 text-[11px] rounded bg-amber-500 text-black font-medium hover:bg-amber-400 transition-colors shrink-0"
                  >
                    Re-apply
                  </button>
                  <button
                    type="button"
                    onClick={() => setToast(null)}
                    className="text-gray-400 hover:text-gray-200 transition-colors"
                    aria-label="Dismiss"
                  >
                    <svg
                      className="w-4 h-4"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                </div>
              </div>
            )}
            <div
              className="flex-1 min-h-0"
              onDragOver={(e) => {
                // Accept drops carrying our custom MIME so Monaco sees the
                // event too (native Monaco drop handles text/plain by
                // itself, but we also want the snippet to land at the
                // current cursor reliably across browsers).
                if (
                  e.dataTransfer.types.includes('application/x-agent-studio-kb-table')
                ) {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = 'copy';
                }
              }}
              onDrop={(e) => {
                const raw = e.dataTransfer.getData(
                  'application/x-agent-studio-kb-table',
                );
                if (!raw) return;
                e.preventDefault();
                try {
                  const payload = JSON.parse(raw);
                  if (payload?.snippet) {
                    insertAtCursor(payload.snippet);
                  }
                } catch {
                  const text = e.dataTransfer.getData('text/plain');
                  if (text) insertAtCursor(text);
                }
              }}
            >
            <Suspense fallback={
              <div className="w-full h-full bg-[var(--ce-bg)] flex items-center justify-center text-gray-500 text-sm">Loading editor...</div>
            }>
              <MonacoEditor
                height="100%"
                language="python"
                theme={APEX_MONACO_THEME}
                beforeMount={handleEditorBeforeMount}
                value={localCode}
                onChange={(val) => {
                  setLocalCode(val || '');
                  setValidationResult(null);
                  if (editorRef.current && window.monaco)
                    window.monaco.editor.setModelMarkers(editorRef.current.getModel(), 'code-validator', []);
                  // Auto-dismiss the "Applied" banner on the first manual edit
                  // so a subsequent Revert never nukes hand-typed content.
                  // Skip the first onChange that immediately follows our own
                  // programmatic setValue (which is the auto-apply itself).
                  if (suppressNextChangeRef.current) {
                    suppressNextChangeRef.current = false;
                    return;
                  }
                  if (appliedBanner) setAppliedBanner(null);
                }}
                onMount={handleEditorMount}
                options={{
                  minimap: { enabled: true },
                  fontSize: 13,
                  lineNumbers: 'on',
                  scrollBeyondLastLine: true,
                  wordWrap: 'on',
                  tabSize: 4,
                  insertSpaces: true,
                  automaticLayout: true,
                  bracketPairColorization: { enabled: true },
                  renderLineHighlight: 'line',
                  padding: { top: 12, bottom: 12 },
                  suggest: { showKeywords: true, showSnippets: true },
                  folding: true,
                  foldingStrategy: 'indentation',
                  renderWhitespace: 'selection',
                  guides: { indentation: true, bracketPairs: true },
                  cursorBlinking: 'smooth',
                  cursorSmoothCaretAnimation: 'on',
                  smoothScrolling: true,
                  mouseWheelZoom: true,
                  contextmenu: true,
                  quickSuggestions: { other: true, comments: true, strings: true },
                  parameterHints: { enabled: true },
                }}
              />
            </Suspense>
            </div>
          </div>

          {/* ── Inputs browser (open by default; drag grip + status-bar slider) ── */}
          {inputsPanelOpen && (
            <>
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label="Drag to resize inputs panel"
                aria-valuemin={INPUTS_PANEL_MIN_WIDTH}
                aria-valuemax={INPUTS_PANEL_MAX_WIDTH}
                aria-valuenow={inputsPanelWidth}
                className="code-editor-inputs-resize-handle shrink-0 touch-none"
                onPointerDown={handleInputsResizePointerDown}
                onPointerMove={handleInputsResizePointerMove}
                onPointerUp={handleInputsResizePointerUp}
                onPointerCancel={handleInputsResizePointerUp}
              />
              <div
                className="flex flex-col border-l border-[var(--ce-border)] bg-[var(--ce-panel)] shrink-0"
                style={{ width: inputsPanelWidth, minWidth: INPUTS_PANEL_MIN_WIDTH, maxWidth: INPUTS_PANEL_MAX_WIDTH }}
              >
              <div className="px-4 py-3 border-b border-[var(--ce-border)] shrink-0">
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-amber-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
                  </svg>
                  <span className="text-sm font-medium text-gray-200 flex-1 min-w-0">Upstream Deliverables</span>
                  <button
                    type="button"
                    onClick={() => setInputsPanelOpen(false)}
                    className="text-gray-500 hover:text-gray-200 shrink-0"
                    aria-label="Hide inputs panel"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <p className="text-[10px] text-gray-500 mt-1">
                  Click a field to insert its path. Rows match{' '}
                  <code className="text-amber-400/80">inputs[&quot;deliverables&quot;]</code>
                  {' '}at run time: <span className="text-gray-400">[0]</span> is the first real
                  payload, then <span className="text-gray-400">[1]</span>, … If/Else, Chat, and
                  other steps that do not publish a deliverable are not listed. Each row is{' '}
                  <code className="text-amber-400/80">inputs[&quot;deliverables&quot;][i][&quot;data&quot;]</code>.
                </p>
              </div>

              <div className="flex-1 overflow-y-auto py-1 min-h-0">
                {inputsTree.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-center px-4">
                    <svg className="w-8 h-8 text-gray-700 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    <p className="text-xs text-gray-500">No upstream nodes connected</p>
                    <p className="text-[10px] text-gray-600 mt-1">Connect nodes to this code runner to see their output schemas</p>
                  </div>
                ) : (
                  inputsTree.map((node, i) => (
                    <InputTreeNode key={i} node={node} onInsert={insertAtCursor} />
                  ))
                )}
              </div>

              {inputsTree.length > 0 && (
                <div className="px-3 py-2 border-t border-[var(--ce-border)] shrink-0 bg-[var(--ce-bg)]">
                  <p className="text-[10px] text-gray-600 font-medium mb-1">Iterate all deliverables</p>
                  <button onClick={() => insertAtCursor('for deliv in inputs["deliverables"]:\n    data = deliv["data"]')}
                    className="text-[10px] font-mono px-2 py-1 rounded bg-[var(--ce-surface)] text-gray-400 hover:text-amber-300 hover:bg-amber-900/20 border border-[var(--ce-border)] transition-colors w-full text-left">
                    for deliv in inputs["deliverables"]:
                  </button>
                </div>
              )}
              </div>
            </>
          )}

          {/* ── Right panel: Documentation ── */}
          {rightPanel === 'docs' && (
            <div className="w-[400px] flex flex-col border-l border-[var(--ce-border)] bg-[var(--ce-panel)] shrink-0">
              <div className="px-4 py-3 border-b border-[var(--ce-border)] shrink-0">
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-[var(--ce-review)]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.746 0 3.332.477 4.5 1.253v13C19.832 18.477 18.246 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                  </svg>
                  <span className="text-sm font-medium text-gray-200">SDK Reference</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-1">Click any code snippet to insert it at cursor</p>
              </div>
              <div className="flex-1 overflow-y-auto min-h-0">
                {sdkDocs === null ? (
                  <div className="flex items-center justify-center h-32 text-xs text-gray-500">Loading...</div>
                ) : (
                  <SdkDocsRenderer content={sdkDocs} onInsert={insertAtCursor} />
                )}
              </div>
            </div>
          )}

          {/* ── Right panel: Versions ── */}
          {rightPanel === 'versions' && (
            <div className="w-[360px] flex flex-col border-l border-[var(--ce-border)] bg-[var(--ce-panel)] shrink-0">
              <div className="px-4 py-3 border-b border-[var(--ce-border)] shrink-0">
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 text-[var(--ce-accent)]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="text-sm font-medium text-gray-200">Versions</span>
                  <span className="ml-auto text-[10px] text-gray-500">{versions.length} / 20</span>
                </div>
                <p className="text-[10px] text-gray-500 mt-1">
                  Every AI code reply is snapshotted. Restore a version to swap it into the editor.
                </p>
              </div>

              <div className="flex-1 overflow-y-auto min-h-0">
                {versions.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-center px-4">
                    <svg className="w-8 h-8 text-gray-700 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <p className="text-xs text-gray-500">No versions yet</p>
                    <p className="text-[10px] text-gray-600 mt-1">Ask the AI to generate or edit code — each reply shows up here.</p>
                  </div>
                ) : (
                  <ul className="divide-y divide-[#404040]">
                    {[...versions].reverse().map((v, idx) => {
                      const isCurrent = v.id === currentVersionId;
                      const when = new Date(v.ts || Date.now());
                      const label = when.toLocaleString([], {
                        month: 'short',
                        day: 'numeric',
                        hour: 'numeric',
                        minute: '2-digit',
                      });
                      // Cursor-like: a version is only "Current" when it still
                      // matches the editor buffer.  Hand-edits detach the
                      // current marker.
                      const isUnmodifiedCurrent =
                        isCurrent && (v.code || '') === (localCode || '');
                      return (
                        <li
                          key={v.id}
                          className={`px-3 py-2 flex items-start gap-2 ${
                            isUnmodifiedCurrent ? 'bg-[var(--ce-accent-soft)]' : 'hover:bg-[var(--ce-surface)]'
                          } ${v.reverted ? 'opacity-60' : ''} transition-colors`}
                        >
                          <div className="w-6 h-6 rounded-full bg-[var(--ce-btn)] flex items-center justify-center text-[10px] font-mono text-gray-400 shrink-0 mt-0.5">
                            {versions.length - idx}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {isUnmodifiedCurrent && (
                                <span className="text-[9px] uppercase tracking-wide text-[var(--ce-accent)] font-semibold bg-[var(--ce-accent-soft)] px-1.5 py-0.5 rounded">
                                  Current
                                </span>
                              )}
                              {isCurrent && !isUnmodifiedCurrent && (
                                <span className="text-[9px] uppercase tracking-wide text-gray-400 font-semibold bg-[var(--ce-btn)] px-1.5 py-0.5 rounded">
                                  Edited
                                </span>
                              )}
                              {v.reverted && (
                                <span className="text-[9px] uppercase tracking-wide text-amber-300 font-semibold bg-amber-900/40 px-1.5 py-0.5 rounded">
                                  Reverted
                                </span>
                              )}
                              <span className="text-[10px] text-gray-500">{label}</span>
                            </div>
                            <p className="text-xs text-gray-200 mt-0.5 truncate" title={v.summary || 'Generated code'}>
                              {v.summary || 'Generated code'}
                            </p>
                            <div className="flex gap-1.5 mt-1.5">
                              <button
                                type="button"
                                onClick={() => handleRestoreVersion(v)}
                                className="px-2 py-0.5 text-[10px] rounded bg-[var(--ce-accent)] text-white hover:bg-[var(--ce-accent-hover)] transition-colors"
                              >
                                Restore
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setAppliedBanner({
                                    versionId: v.id,
                                    summary: v.summary || 'Diff',
                                    prevCode: localCode,
                                    newCode: v.code || '',
                                    truncated: !!v.truncated,
                                  });
                                  setDiffOpen(true);
                                }}
                                className="px-2 py-0.5 text-[10px] rounded bg-[var(--ce-btn)] text-gray-300 border border-[var(--ce-border)] hover:bg-[var(--ce-border)] transition-colors"
                              >
                                Diff vs current
                              </button>
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              {versions.length > 0 && (
                <div className="px-3 py-2 border-t border-[var(--ce-border)] shrink-0 bg-[var(--ce-bg)]">
                  <button
                    type="button"
                    onClick={() => setShowClearConfirm(true)}
                    className="w-full px-2 py-1 text-[11px] rounded bg-[var(--ce-surface)] text-red-300 hover:bg-red-900/30 border border-red-600/40 transition-colors"
                  >
                    Clear chat &amp; versions
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ── Right panel: AI Chat ── */}
          {rightPanel === 'ai' && (
            <div className="w-[380px] flex flex-col border-l border-[var(--ce-border)] bg-[var(--ce-panel)] shrink-0">
              <div className="px-4 py-3 border-b border-[var(--ce-border)] shrink-0">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-[var(--ce-accent)]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    <span className="text-sm font-medium text-gray-200">AI Assistant</span>
                  </div>
                  <button
                    onClick={() => {
                      if (chatMessages.length === 0 && versions.length === 0) return;
                      setShowClearConfirm(true);
                    }}
                    disabled={chatMessages.length === 0 && versions.length === 0}
                    className="text-xs text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    Clear
                  </button>
                </div>
                <p className="text-[10px] text-gray-500 mt-1">Describe what you want and I'll write the code</p>
              </div>

              <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0">
                {chatMessages.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full text-center px-4">
                    <div className="w-10 h-10 rounded-full bg-[var(--ce-accent-soft)] flex items-center justify-center mb-3">
                      <svg className="w-5 h-5 text-[var(--ce-accent)]" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                      </svg>
                    </div>
                    <p className="text-sm text-gray-400 mb-1">Ask me anything</p>
                    <p className="text-xs text-gray-600">"Parse the uploaded Excel and output a summary table"</p>
                    <p className="text-xs text-gray-600 mt-1">"Add error handling to the existing code"</p>
                    <p className="text-xs text-gray-600 mt-1">"Use llm.complete to classify each row"</p>
                  </div>
                )}
                {chatMessages.map((msg) => {
                  const isUser = msg.role === 'user';
                  const isClarify = !isUser && msg.kind === 'clarify';
                  const fixPrompt = !isUser && !msg.valid && (msg.violations || []).length > 0
                    ? `Fix the validation errors from the last attempt:\n${(msg.violations || [])
                        .map((v) => `- ${v}`)
                        .join('\n')}`
                    : null;
                  return (
                    <div key={msg.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[95%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
                        isUser
                          ? 'bg-[var(--ce-accent)] text-white'
                          : isClarify
                            ? 'bg-amber-900/30 text-amber-100 border border-amber-600/50'
                            : 'bg-[var(--ce-surface)] text-white border border-[var(--ce-border)]'
                      }`}>
                        {msg.images?.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mb-1.5">
                            {msg.images.map((img, idx) => (
                              <img key={idx} src={img.dataUrl || img} alt={img.name || 'attachment'}
                                className="h-20 rounded border border-white/20 object-cover" />
                            ))}
                          </div>
                        )}
                        {isClarify ? (
                          <>
                            <div className="flex items-start gap-2">
                              <svg className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093M12 17h.01M12 2a10 10 0 100 20 10 10 0 000-20z" />
                              </svg>
                              <p className="whitespace-pre-wrap font-medium">
                                {msg.question || msg.content || 'Need more info to continue.'}
                              </p>
                            </div>
                            {(msg.options || []).length > 0 && (
                              <div className="flex flex-wrap gap-1.5 mt-2.5">
                                {(msg.options || []).map((opt, idx) => (
                                  <button
                                    key={idx}
                                    type="button"
                                    onClick={() => handleSyntheticSend(opt)}
                                    disabled={chatLoading}
                                    className="px-2.5 py-1 rounded-full text-[11px] bg-amber-700/40 hover:bg-amber-600/50 text-amber-100 border border-amber-500/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                  >
                                    {opt}
                                  </button>
                                ))}
                              </div>
                            )}
                          </>
                        ) : (
                          <>
                            {msg.summary && !isUser && (
                              <p className="text-[11px] uppercase tracking-wide text-[var(--ce-accent)]/80 font-semibold mb-1">
                                {msg.summary}
                              </p>
                            )}
                            {msg.content && !msg.summary && <p className="whitespace-pre-wrap">{msg.content}</p>}
                            {msg.content && msg.summary && msg.content !== msg.summary && (
                              <p className="whitespace-pre-wrap text-gray-300 text-xs">{msg.content}</p>
                            )}
                            {!isUser && (msg.assumptions || []).length > 0 && (
                              <div className="mt-2 text-[11px] text-gray-400 border-l-2 border-[var(--ce-accent)]/50 pl-2">
                                <div className="font-semibold text-[var(--ce-accent)] mb-0.5">Assumptions</div>
                                <ul className="list-disc list-inside space-y-0.5">
                                  {(msg.assumptions || []).map((a, idx) => (
                                    <li key={idx}>{a}</li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {msg.code && (
                              <div className="mt-2">
                                <div className="bg-[var(--ce-bg)] rounded border border-[var(--ce-border)] p-2 font-mono text-[11px] text-[var(--ce-success)] max-h-60 overflow-y-auto whitespace-pre-wrap">{msg.code}</div>
                                {/*
                                  Code is auto-applied to the editor the moment
                                  the turn arrives (see the Instant-apply branch
                                  around handleApplyCode).  We show an
                                  unobtrusive "Applied" status chip here so the
                                  user can see *which* turn produced the
                                  current editor buffer, without tempting them
                                  to re-apply an older turn and clobber newer
                                  edits.  A small Copy shortcut stays available
                                  for pasting the snippet elsewhere.
                                */}
                                <div className="flex items-center gap-2 mt-2">
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-[var(--ce-success-bg)] text-[var(--ce-success)] border border-[var(--ce-review)]/40">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                                      <path fillRule="evenodd" d="M16.704 5.296a1 1 0 010 1.414l-7.5 7.5a1 1 0 01-1.414 0l-3.5-3.5a1 1 0 011.414-1.414L8.5 12.086l6.79-6.79a1 1 0 011.414 0z" clipRule="evenodd" />
                                    </svg>
                                    Applied to editor
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => navigator.clipboard.writeText(msg.code)}
                                    title="Copy this version to clipboard"
                                    className="text-[10px] text-gray-500 hover:text-gray-300 underline-offset-2 hover:underline transition-colors"
                                  >
                                    Copy
                                  </button>
                                </div>
                              </div>
                            )}
                            {!isUser && !msg.valid && (msg.violations || []).length > 0 && (
                              <div className="mt-2 text-[11px] text-yellow-300 bg-yellow-900/20 border border-yellow-600/40 rounded px-2 py-1.5">
                                <div className="font-semibold mb-0.5">Validation failed</div>
                                <ul className="list-disc list-inside space-y-0.5 text-yellow-200/90">
                                  {(msg.violations || []).slice(0, 5).map((v, idx) => (
                                    <li key={idx}>{v}</li>
                                  ))}
                                </ul>
                                {fixPrompt && (
                                  <button
                                    type="button"
                                    onClick={() => handleSyntheticSend(fixPrompt)}
                                    disabled={chatLoading}
                                    className="mt-1.5 px-2.5 py-1 rounded text-[11px] bg-yellow-600 text-black hover:bg-yellow-500 transition-colors font-medium disabled:opacity-50"
                                  >
                                    Ask AI to fix
                                  </button>
                                )}
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
                {chatLoading && (
                  <div className="flex justify-start">
                    <div className="bg-[var(--ce-surface)] border border-[var(--ce-border)] rounded-lg px-3 py-2 text-xs text-gray-400">
                      <div className="flex items-center gap-2">
                        <div className="flex gap-1">
                          <div className="w-1.5 h-1.5 rounded-full bg-[var(--ce-accent)] animate-bounce" style={{ animationDelay: '0ms' }} />
                          <div className="w-1.5 h-1.5 rounded-full bg-[var(--ce-accent)] animate-bounce" style={{ animationDelay: '150ms' }} />
                          <div className="w-1.5 h-1.5 rounded-full bg-[var(--ce-accent)] animate-bounce" style={{ animationDelay: '300ms' }} />
                        </div>
                        <span>Generating...</span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              <div className="p-3 border-t border-[var(--ce-border)] shrink-0">
                {attachedImages.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {attachedImages.map(img => (
                      <div key={img.id} className="relative group">
                        <img src={img.dataUrl} alt={img.name}
                          className="h-14 w-14 rounded border border-[var(--ce-border)] object-cover" />
                        <button type="button" onClick={() => removeAttachedImage(img.id)}
                          title="Remove"
                          className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-gray-900 text-gray-200 border border-[#606060] text-[10px] leading-none flex items-center justify-center hover:bg-red-600 hover:text-white hover:border-red-600 transition-colors">
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {attachError && (
                  <p className="text-[10px] text-red-400 mb-1.5 px-1">{attachError}</p>
                )}
                <div className="flex gap-2">
                  <textarea ref={chatInputRef}
                    className="force-white-text flex-1 bg-[var(--ce-bg)] border border-[var(--ce-border)] rounded-lg px-3 py-2 text-sm text-white placeholder-[var(--ce-muted)] resize-y min-h-[84px] focus:outline-none focus:border-[var(--ce-accent)] transition-colors"
                    rows={4} placeholder="Describe what you need... (paste images with Cmd/Ctrl+V)"
                    value={chatInput} onChange={e => setChatInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChatSend(); } }}
                    onPaste={handleImagePaste}
                    disabled={chatLoading}
                  />
                  <input
                    ref={imageInputRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      addImageFiles(e.target.files);
                      e.target.value = ''; // allow re-selecting the same file later
                    }}
                  />
                  <button type="button"
                    onClick={() => imageInputRef.current?.click()}
                    disabled={chatLoading || attachedImages.length >= MAX_IMAGES}
                    title={attachedImages.length >= MAX_IMAGES ? `Max ${MAX_IMAGES} images` : 'Attach image'}
                    className="self-end px-2.5 py-2 rounded-lg bg-[var(--ce-btn)] text-gray-300 hover:text-white hover:bg-[#4a4a4a] border border-[var(--ce-border)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 10-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                    </svg>
                  </button>
                  <button onClick={handleChatSend}
                    disabled={chatLoading || (!chatInput.trim() && attachedImages.length === 0)}
                    className="self-end px-3 py-2 rounded-lg bg-[var(--ce-cta)] text-white hover:bg-[var(--ce-cta-hover)] disabled:opacity-40 transition-colors">
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19V5m0 0l-7 7m7-7l7 7" />
                    </svg>
                  </button>
                </div>
                <p className="text-[10px] text-gray-600 mt-1.5 px-1">
                  Enter to send · Shift+Enter for new line · Paste or attach up to {MAX_IMAGES} images ({MAX_IMAGE_BYTES / (1024 * 1024)} MB each)
                </p>
              </div>
            </div>
          )}
        </div>

        {/* ── Status bar ── */}
        <div className="flex items-center justify-between gap-4 px-4 py-1.5 bg-[var(--ce-cta)] text-white text-[11px] shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <span>Python</span>
            <span>UTF-8</span>
            <span>Spaces: 4</span>
            {inputsPanelOpen && (
              <label
                htmlFor="code-editor-inputs-width"
                className="flex items-center gap-2 pl-3 ml-1 border-l border-white/30 shrink-0"
              >
                <span className="text-white/90 whitespace-nowrap">Inputs width</span>
                <input
                  id="code-editor-inputs-width"
                  type="range"
                  className="code-editor-inputs-width-slider"
                  min={INPUTS_PANEL_MIN_WIDTH}
                  max={INPUTS_PANEL_MAX_WIDTH}
                  step={10}
                  value={inputsPanelWidth}
                  onChange={handleInputsPanelWidthChange}
                  aria-valuemin={INPUTS_PANEL_MIN_WIDTH}
                  aria-valuemax={INPUTS_PANEL_MAX_WIDTH}
                  aria-valuenow={inputsPanelWidth}
                />
                <span className="tabular-nums text-white/90 w-10 text-right">{inputsPanelWidth}px</span>
              </label>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <span>{localCode.split('\n').length} lines</span>
            <span>{upstreamNodes.length} deliverable(s)</span>
            <span>Cmd+S to save</span>
          </div>
        </div>
      </div>

      {/* ── Diff drawer (full-screen overlay) ── */}
      <CodeDiffDrawer
        isOpen={diffOpen && !!appliedBanner}
        prevCode={appliedBanner?.prevCode || ''}
        newCode={appliedBanner?.newCode || ''}
        summary={appliedBanner?.summary || ''}
        onClose={handleCloseDiff}
        onKeep={handleKeepApplied}
        onRevert={handleRevertApplied}
      />

      {/* ── Clear-chat confirmation ── */}
      {showClearConfirm && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 px-4"
          onClick={() => setShowClearConfirm(false)}
        >
          <div
            className="w-full max-w-sm rounded-lg bg-[var(--ce-panel)] border border-[var(--ce-border)] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-red-900/40 flex items-center justify-center shrink-0">
                <svg
                  className="w-4 h-4 text-red-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M10 3h4a2 2 0 012 2v2H8V5a2 2 0 012-2z"
                  />
                </svg>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-gray-100">
                  Clear chat and version history?
                </h3>
                <p className="text-xs text-gray-400 mt-1">
                  This wipes {chatMessages.length} message
                  {chatMessages.length === 1 ? '' : 's'} and {versions.length}{' '}
                  version{versions.length === 1 ? '' : 's'} stored locally for
                  this node. The code currently in the editor is kept.
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={() => setShowClearConfirm(false)}
                className="px-3 py-1.5 text-xs rounded bg-[var(--ce-btn)] text-gray-300 hover:bg-[var(--ce-border)] border border-[var(--ce-border)] transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleClearSession}
                className="px-3 py-1.5 text-xs rounded bg-red-600 text-white hover:bg-red-700 transition-colors font-medium"
              >
                Clear everything
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  if (typeof document === 'undefined') return modal;
  return createPortal(modal, document.body);
}
