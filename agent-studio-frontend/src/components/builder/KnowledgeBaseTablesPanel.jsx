/**
 * Knowledge Base tables panel for the Code Editor.
 *
 * Shown as a left sidebar when the Code Runner node has one or more
 * Knowledge Bases configured.  Lists every structured table the user can
 * access in those KBs, with columns nested under each table.  Tables can
 * be:
 *   - clicked, to insert a `knowledge_base.read_table(...)` snippet at the
 *     editor's cursor, or
 *   - dragged and dropped directly into the Monaco editor.
 *
 * The snippet that's inserted depends on whether the same table name
 * appears in multiple configured KBs -- we pass `kb_id=` whenever the
 * name is ambiguous (or always, if the caller prefers explicit binding).
 */

import React, { useEffect, useMemo, useState } from 'react';
import { getKbTables } from '@/api/code-executor-kb-client.js';

const TYPE_COLORS = {
  text: 'bg-blue-900/40 text-blue-300',
  integer: 'bg-emerald-900/40 text-emerald-300',
  numeric: 'bg-emerald-900/40 text-emerald-300',
  boolean: 'bg-purple-900/40 text-purple-300',
  date: 'bg-amber-900/40 text-amber-300',
  datetime: 'bg-amber-900/40 text-amber-300',
};

function TypePill({ type }) {
  const classes = TYPE_COLORS[type] || 'bg-gray-800 text-gray-300';
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${classes}`}>
      {type || 'text'}
    </span>
  );
}

/**
 * Build the snippet we insert when a table is clicked or dropped.
 *
 * Default -- Pandas-first read:
 *   df_orders = knowledge_base.read_table("orders", limit=100)
 *
 * If the same table name exists in multiple configured KBs we splice in
 * `, kb_id="<uuid>"` to avoid ambiguity.
 */
function buildReadTableSnippet(table, { ambiguous }) {
  const varName = safeVariableName(table.table);
  const kbArg = ambiguous ? `, kb_id="${table.kb_id}"` : '';
  return `${varName} = knowledge_base.read_table("${table.table}", limit=100${kbArg})`;
}

function safeVariableName(tableName) {
  if (!tableName) return 'df';
  const cleaned = String(tableName).replace(/[^A-Za-z0-9_]/g, '_');
  const leading = /^[A-Za-z_]/.test(cleaned) ? cleaned : `df_${cleaned}`;
  return `df_${leading}`.replace(/^df_df_/, 'df_');
}

function TableRow({ table, ambiguous, expanded, onToggle, onInsert, onShowDesc, onHideDesc }) {
  const snippet = useMemo(
    () => buildReadTableSnippet(table, { ambiguous }),
    [table, ambiguous],
  );

  const handleDragStart = (e) => {
    e.dataTransfer.setData('text/plain', snippet);
    e.dataTransfer.setData(
      'application/x-agent-studio-kb-table',
      JSON.stringify({ ...table, snippet }),
    );
    e.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <div className="border-b border-[#333] last:border-b-0">
      <div
        draggable
        onDragStart={handleDragStart}
        onClick={() => onInsert(snippet)}
        title={`Click or drag to insert: ${snippet}`}
        className="group flex items-start gap-1.5 px-2 py-1.5 hover:bg-[#2a2d2e] cursor-grab active:cursor-grabbing transition-colors"
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggle(table);
          }}
          className="-my-1 -ml-1 p-1.5 rounded text-gray-400 hover:text-white hover:bg-[#3a3d3e] active:bg-[#45484a] shrink-0 transition-colors"
          aria-label={expanded ? 'Collapse columns' : 'Expand columns'}
          title={expanded ? 'Collapse columns' : 'Expand columns'}
        >
          <svg
            className={`w-4 h-4 transition-transform ${expanded ? 'rotate-90' : ''}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
        <svg
          className="w-3.5 h-3.5 text-teal-400 mt-0.5 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 7h16M4 12h16M4 17h16"
          />
        </svg>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-mono text-gray-200 truncate">
            {table.table}
          </div>
          {table.display_name && table.display_name !== table.table && (
            <div className="text-[10px] text-gray-500 truncate">
              {table.display_name}
            </div>
          )}
        </div>
        <span className="text-[10px] text-gray-500 shrink-0 mt-0.5">
          {(table.row_count || 0).toLocaleString()} rows
        </span>
      </div>
      {expanded && (
        <div className="bg-[#1e1e1e] pl-7 pr-2 py-1 space-y-0.5">
          {(table.columns || []).length === 0 && (
            <div className="text-[10px] text-gray-600 italic py-0.5">
              No columns
            </div>
          )}
          {(table.columns || []).map((col) => (
            <div
              key={col.name}
              className="group flex items-center gap-1.5 px-1.5 py-0.5 rounded hover:bg-[#2a2d2e]"
            >
              <button
                type="button"
                onClick={() => onInsert(`"${col.name}"`)}
                title={`Insert column name "${col.name}"`}
                className="flex-1 min-w-0 text-left"
              >
                <span className="text-[11px] font-mono text-gray-300 truncate block">
                  {col.name}
                </span>
              </button>
              <TypePill type={col.type} />
              <button
                type="button"
                onMouseEnter={(e) => onShowDesc(e, col)}
                onMouseLeave={onHideDesc}
                onFocus={(e) => onShowDesc(e, col)}
                onBlur={onHideDesc}
                onClick={(e) => {
                  e.stopPropagation();
                  onShowDesc(e, col);
                }}
                aria-label={col.description ? 'Column description' : 'No description available'}
                title={col.description || 'No description'}
                className={`inline-flex items-center justify-center w-4 h-4 rounded-full shrink-0 transition-colors ${
                  col.description
                    ? 'text-blue-400 hover:text-blue-300'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                    clipRule="evenodd"
                  />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function KnowledgeBaseTablesPanel({
  knowledgeBaseIds = [],
  onInsert,
}) {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  // Floating description tooltip for the "!" icon on columns.
  // Read-only here — editing lives in the KB detail view.
  const [descTooltip, setDescTooltip] = useState(null);

  const showDesc = (e, col) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const POP_W = 240;
    const winW = typeof window !== 'undefined' ? window.innerWidth : 1200;
    // Prefer right of the icon; fall back to the left if it would overflow.
    let x = rect.right + 8;
    if (x + POP_W + 8 > winW) {
      x = Math.max(8, rect.left - POP_W - 8);
    }
    setDescTooltip({
      name: col.name,
      type: col.type,
      text: col.description || '',
      x,
      y: rect.top,
    });
  };

  const hideDesc = () => setDescTooltip(null);

  const idsKey = useMemo(
    () => (Array.isArray(knowledgeBaseIds) ? knowledgeBaseIds : []).filter(Boolean).join(','),
    [knowledgeBaseIds],
  );

  useEffect(() => {
    const ids = idsKey ? idsKey.split(',') : [];
    if (ids.length === 0) {
      setTables([]);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    getKbTables(ids)
      .then((data) => {
        if (cancelled) return;
        setTables(Array.isArray(data.tables) ? data.tables : []);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('Failed to load KB tables:', err);
        setError(err.message || 'Failed to load tables');
        setTables([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [idsKey]);

  const grouped = useMemo(() => {
    const byKb = new Map();
    for (const t of tables) {
      if (!byKb.has(t.kb_id)) {
        byKb.set(t.kb_id, { kb_id: t.kb_id, kb_name: t.kb_name, tables: [] });
      }
      byKb.get(t.kb_id).tables.push(t);
    }
    return Array.from(byKb.values()).sort((a, b) =>
      (a.kb_name || '').localeCompare(b.kb_name || ''),
    );
  }, [tables]);

  // Mark tables whose bare name is ambiguous across KBs so we inject
  // kb_id= into their snippet.
  const ambiguousNames = useMemo(() => {
    const byName = new Map();
    for (const t of tables) {
      byName.set(t.table, (byName.get(t.table) || 0) + 1);
    }
    return new Set(
      Array.from(byName.entries())
        .filter(([, count]) => count > 1)
        .map(([name]) => name),
    );
  }, [tables]);

  const toggle = (t) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      const key = `${t.kb_id}:${t.table}`;
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (!Array.isArray(knowledgeBaseIds) || knowledgeBaseIds.filter(Boolean).length === 0) {
    return (
      <div className="p-4 text-center">
        <svg
          className="w-8 h-8 text-gray-700 mx-auto mb-2"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"
          />
        </svg>
        <p className="text-xs text-gray-500 leading-relaxed">
          No Knowledge Bases selected on this node.
        </p>
        <p className="text-[10px] text-gray-600 mt-1 leading-relaxed">
          Close this editor and pick one or more KBs in the node's
          &ldquo;Knowledge Bases&rdquo; field to query their structured tables from
          your code.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-4 flex items-center gap-2 text-xs text-gray-500">
        <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-teal-400" />
        Loading tables…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 text-[11px] text-red-400 leading-relaxed">
        Failed to load tables:
        <div className="mt-1 font-mono text-red-300 break-words">{error}</div>
      </div>
    );
  }

  if (grouped.length === 0) {
    return (
      <div className="p-4 text-center">
        <p className="text-xs text-gray-500 leading-relaxed">
          The selected Knowledge Base{knowledgeBaseIds.length > 1 ? 's have' : ' has'} no
          structured tables yet.
        </p>
        <p className="text-[10px] text-gray-600 mt-1 leading-relaxed">
          Upload a spreadsheet (CSV, XLSX) to a KB to add tables.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-0 h-full">
      <div className="flex-1 min-h-0 overflow-y-auto">
        {grouped.map(({ kb_id, kb_name, tables: kbTables }) => (
          <div key={kb_id} className="border-b border-[#333]">
            <div className="px-2 py-1.5 bg-[#252526] sticky top-0 z-10 border-b border-[#333]">
              <div className="flex items-center gap-1.5">
                <svg
                  className="w-3.5 h-3.5 text-teal-400 shrink-0"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <ellipse cx="12" cy="6" rx="8" ry="3" />
                  <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
                  <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
                </svg>
                <span className="text-[11px] font-semibold text-gray-200 truncate flex-1">
                  {kb_name}
                </span>
                <span className="text-[10px] text-gray-500 shrink-0">
                  {kbTables.length}
                </span>
              </div>
            </div>
            {kbTables.map((t) => {
              const key = `${t.kb_id}:${t.table}`;
              return (
                <TableRow
                  key={key}
                  table={t}
                  ambiguous={ambiguousNames.has(t.table)}
                  expanded={expanded.has(key)}
                  onToggle={toggle}
                  onInsert={onInsert}
                  onShowDesc={showDesc}
                  onHideDesc={hideDesc}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div className="border-t border-[#333] px-2 py-1.5 bg-[#1e1e1e] shrink-0">
        <p className="text-[10px] text-gray-500 leading-snug">
          Drag a table into the editor or click to insert a
          <code className="text-teal-400 px-1">read_table()</code> snippet.
        </p>
      </div>

      {descTooltip && (
        <div
          className="fixed z-[70] pointer-events-none bg-[#252526] border border-[#3f3f46] rounded-md shadow-xl px-3 py-2 w-[240px]"
          style={{ left: descTooltip.x, top: descTooltip.y }}
        >
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-[11px] font-mono text-gray-200 truncate flex-1">
              {descTooltip.name}
            </span>
            {descTooltip.type && <TypePill type={descTooltip.type} />}
          </div>
          <p className="text-[10px] text-gray-400 leading-relaxed whitespace-pre-wrap">
            {descTooltip.text
              ? descTooltip.text
              : <span className="italic text-gray-600">No description</span>}
          </p>
        </div>
      )}
    </div>
  );
}
