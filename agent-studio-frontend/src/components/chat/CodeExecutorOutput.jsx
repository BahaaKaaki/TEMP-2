/**
 * CodeExecutorOutput -- renders typed outputs from the code-executor node.
 *
 * Two render pipelines:
 *
 *   1. DSL-visualized outputs  (`type: "data"` with `_visualization`, or the
 *      legacy `table`/`chart`/`document` types converted to DSL on the fly)
 *      → `<VisualizationRenderer>`.
 *
 *   2. Non-visualization outputs: file, files, list (interactive), selection,
 *      form, ask, error → dedicated widgets below.
 *
 * Anything else falls back to a generic key-value `DataRenderer`.
 */

import { useState, useMemo, useEffect, useRef, lazy, Suspense } from 'react';
import ExecutionStreamPanel from './ExecutionStreamPanel';
import { authenticatedFetch, API_BASE_URL } from '../../api/client';

const VisualizationRenderer = lazy(() => import('../ui/VisualizationRenderer'));

// ─── Editable row (used inside DataRenderer) ─────────────────────────
function EditableRow({ label, value, onChange }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  const display = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '');

  const startEdit = () => {
    setDraft(display);
    setEditing(true);
  };

  const commit = () => {
    setEditing(false);
    if (draft !== display && onChange) {
      const num = Number(draft);
      onChange(label, draft === '' ? '' : !isNaN(num) && draft.trim() !== '' ? num : draft);
    }
  };

  const cancel = () => { setEditing(false); };

  const handleKey = (e) => {
    if (e.key === 'Enter') commit();
    if (e.key === 'Escape') cancel();
  };

  return (
    <div className="px-4 py-3 hover:bg-gray-50 transition-colors">
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
      {editing ? (
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={handleKey}
          autoFocus
          className="block w-full mt-1 px-2 py-1 text-sm border border-indigo-300 rounded focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
        />
      ) : (
        <div
          onClick={startEdit}
          className="text-sm mt-0.5 text-gray-900 cursor-text rounded px-1 -mx-1 hover:bg-indigo-50 hover:text-indigo-900 transition-colors"
          title="Click to edit"
        >
          {display || <span className="text-gray-400 italic">empty</span>}
        </div>
      )}
    </div>
  );
}

// ─── Data (fallback for plain key-value payloads) ────────────────────
function DataRenderer({ data, title, onDataChange }) {
  const [localData, setLocalData] = useState(() => (data && typeof data === 'object' ? { ...data } : data));

  if (!localData) return null;

  if (typeof localData === 'string') {
    return <pre className="text-xs font-mono p-3 bg-gray-50 rounded-lg overflow-x-auto">{localData}</pre>;
  }

  if (localData.text && Object.keys(localData).length === 1) {
    return <pre className="text-xs font-mono p-3 bg-gray-50 rounded-lg whitespace-pre-wrap">{localData.text}</pre>;
  }

  const handleChange = (key, newVal, sectionKey) => {
    setLocalData(prev => {
      const next = sectionKey
        ? { ...prev, [sectionKey]: { ...prev[sectionKey], [key]: newVal } }
        : { ...prev, [key]: newVal };
      if (onDataChange) onDataChange(next);
      return next;
    });
  };

  const hasSections = Object.values(localData).some(v => v && typeof v === 'object' && !Array.isArray(v));

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {title && (
        <div className="px-4 py-2.5 bg-gray-50 border-b text-sm font-semibold text-gray-700">
          {title}
        </div>
      )}

      {hasSections ? (
        Object.entries(localData).map(([sectionKey, sectionVal]) => {
          if (sectionVal && typeof sectionVal === 'object' && !Array.isArray(sectionVal)) {
            return (
              <div key={sectionKey}>
                <div className="px-4 py-2 bg-gray-50 border-b border-t text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  {sectionKey.replace(/_/g, ' ')}
                </div>
                <div className="divide-y divide-gray-100">
                  {Object.entries(sectionVal).map(([k, v]) => (
                    <EditableRow key={k} label={k} value={v} onChange={(key, val) => handleChange(key, val, sectionKey)} />
                  ))}
                </div>
              </div>
            );
          }
          return (
            <div key={sectionKey} className="divide-y divide-gray-100">
              <EditableRow label={sectionKey} value={sectionVal} onChange={(key, val) => handleChange(key, val)} />
            </div>
          );
        })
      ) : (
        <div className="divide-y divide-gray-100">
          {Object.entries(localData).map(([key, value]) => (
            <EditableRow key={key} label={key} value={value} onChange={(k, val) => handleChange(k, val)} />
          ))}
        </div>
      )}

      <div className="px-4 py-2 bg-gray-50 border-t text-xs text-gray-400">
        {Object.keys(localData).length} items
      </div>
    </div>
  );
}

// ─── Legacy-payload → DSL spec conversion ────────────────────────────
// Old deliverables were stored as `type: "table"` / "chart" / "document" with
// their own shape. We convert them to DSL specs on the fly so they render
// through the same `VisualizationRenderer` pipeline as new deliverables.

function tableToSpec(payload, metadata) {
  let columns = metadata?.columns;
  let rows = [];

  if (Array.isArray(payload)) {
    if (!columns && payload.length > 0) columns = Object.keys(payload[0]);
    rows = payload;
  } else if (payload && typeof payload === 'object') {
    if (!columns) columns = Object.keys(payload);
    const length = Math.max(...columns.map(c => (payload[c] || []).length), 0);
    for (let i = 0; i < length; i++) {
      const row = {};
      columns.forEach(c => { row[c] = (payload[c] || [])[i]; });
      rows.push(row);
    }
  }

  return [{
    type: 'table',
    title: metadata?.title,
    columns: columns || [],
    rows,
  }];
}

function chartToSpec(payload, metadata) {
  return [{
    type: 'chart',
    title: metadata?.title || payload?.title,
    chart_type: payload?.chart_type || 'bar',
    chart_data: payload?.chart_data || payload,
    x_label: payload?.x_label,
    y_label: payload?.y_label,
  }];
}

function documentToSpec(payload) {
  const specs = [];
  const title = payload?.title;
  const metadata = payload?.metadata || {};
  if (title || Object.keys(metadata).length > 0) {
    specs.push({ type: 'header', title, badges: metadata });
  }
  const sections = payload?.sections || [];
  if (sections.length > 0) {
    const accordionSections = sections.map(sec => {
      const content = [];
      if (sec.type === 'text') content.push({ type: 'text', value: sec.content });
      else if (sec.type === 'list') content.push({ type: 'list', items: sec.items || [] });
      else if (sec.type === 'table') content.push({ type: 'table', columns: sec.columns || [], rows: sec.rows || [] });
      return { title: sec.title, content };
    });
    specs.push({ type: 'accordion', sections: accordionSections });
  }
  const graph = payload?.graph;
  if (graph && graph.nodes && graph.nodes.length > 0) {
    specs.push({ type: 'flowchart', title: 'Process Flow', nodes: graph.nodes, edges: graph.edges || [], swimlanes: graph.swimlanes || [] });
  }
  return specs;
}

// ─── File Icon by extension ──────────────────────────────────────────
const FILE_TYPE_COLORS = {
  xlsx: 'text-emerald-600', xls: 'text-emerald-600', csv: 'text-emerald-600',
  pptx: 'text-orange-500', ppt: 'text-orange-500',
  docx: 'text-blue-600', doc: 'text-blue-600',
  pdf: 'text-red-500',
  png: 'text-purple-500', jpg: 'text-purple-500', jpeg: 'text-purple-500', svg: 'text-purple-500',
  zip: 'text-yellow-600', json: 'text-gray-600', txt: 'text-gray-600',
};

function fileColor(name) {
  const ext = (name || '').split('.').pop()?.toLowerCase();
  return FILE_TYPE_COLORS[ext] || 'text-indigo-500';
}

function FileCard({ name, downloadUrl }) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async (e) => {
    e.preventDefault();
    if (downloading) return;
    setDownloading(true);
    try {
      const url = downloadUrl.startsWith('http') ? downloadUrl : `${API_BASE_URL}${downloadUrl}`;
      const resp = await authenticatedFetch(url);
      if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
      const blob = await resp.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objUrl;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objUrl);
    } catch (err) {
      console.error('Download failed:', err);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 flex items-center gap-3">
      <svg className={`w-8 h-8 ${fileColor(name)} shrink-0`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </svg>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{name}</p>
      </div>
      <button
        type="button"
        onClick={handleDownload}
        disabled={downloading}
        className="text-xs px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
      >
        {downloading ? 'Downloading...' : 'Download'}
      </button>
    </div>
  );
}

// ─── Single File ─────────────────────────────────────────────────────
function FileRenderer({ data, outputFiles }) {
  if (!data && (!outputFiles || outputFiles.length === 0)) return null;

  const files = outputFiles?.length
    ? outputFiles
    : data?.download_url
      ? [{ name: data.display_name || data.path || 'file', download_url: data.download_url }]
      : [];

  if (files.length === 0) {
    const name = data?.display_name || data?.path || 'file';
    return <FileCard name={name} downloadUrl={`/api/code-executor/files/${encodeURIComponent(data?.path || '')}`} />;
  }

  return (
    <div className="space-y-2">
      {files.map((f, i) => (
        <FileCard key={i} name={f.name || f.display_name} downloadUrl={f.download_url} />
      ))}
    </div>
  );
}

function AuthDownloadButton({ name, downloadUrl }) {
  const [downloading, setDownloading] = useState(false);
  const handleClick = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const url = downloadUrl.startsWith('http') ? downloadUrl : `${API_BASE_URL}${downloadUrl}`;
      const resp = await authenticatedFetch(url);
      if (!resp.ok) throw new Error(`Download failed: ${resp.status}`);
      const blob = await resp.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objUrl;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objUrl);
    } catch (err) {
      console.error('Download failed:', err);
    } finally {
      setDownloading(false);
    }
  };
  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={downloading}
      className="text-xs px-3 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
    >
      {downloading ? '...' : 'Download'}
    </button>
  );
}

// ─── Multi-file ──────────────────────────────────────────────────────
function FilesRenderer({ data, title }) {
  const entries = data?.files || [];
  if (entries.length === 0) return null;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {title && <div className="px-4 py-2.5 bg-gray-50 border-b text-sm font-semibold text-gray-700">{title}</div>}
      <div className="divide-y divide-gray-100">
        {entries.map((f, i) => (
          <div key={i} className="px-4 py-3 flex items-center gap-3">
            <svg className={`w-6 h-6 ${fileColor(f.display_name || f.path)} shrink-0`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
            <span className="text-sm text-gray-900 flex-1 truncate">{f.display_name || f.path}</span>
            {f.download_url && (
              <AuthDownloadButton name={f.display_name || f.path} downloadUrl={f.download_url} />
            )}
          </div>
        ))}
      </div>
      <div className="px-4 py-2 bg-gray-50 border-t text-xs text-gray-500">{entries.length} files</div>
    </div>
  );
}

// ─── Selection Widget (interactive) ──────────────────────────────────
function SelectionWidget({ data, onSubmit, isResponded }) {
  const [selected, setSelected] = useState(data?.allow_multiple ? [] : null);

  const handleToggle = (option) => {
    if (data?.allow_multiple) {
      setSelected(prev =>
        prev.includes(option.value) ? prev.filter(v => v !== option.value) : [...prev, option.value]
      );
    } else {
      setSelected(option.value);
    }
  };

  const canSubmit = data?.allow_multiple ? selected.length > 0 : selected !== null;

  if (isResponded) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
        Response submitted. Workflow continuing...
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
      <p className="text-sm font-medium text-gray-800">{data?.prompt || 'Make a selection'}</p>
      <div className="space-y-2">
        {(data?.options || []).map((opt, idx) => {
          const isActive = data?.allow_multiple
            ? selected.includes(opt.value)
            : JSON.stringify(selected) === JSON.stringify(opt.value);

          return (
            <button
              key={idx}
              type="button"
              onClick={() => handleToggle(opt)}
              className={`w-full text-left p-3 rounded-lg border-2 transition-all text-sm ${
                isActive
                  ? 'border-indigo-500 bg-indigo-50 text-indigo-900'
                  : 'border-gray-200 hover:border-gray-300 bg-white text-gray-700'
              }`}
            >
              <span className="font-medium">{opt.label}</span>
              {opt.description && <p className="text-xs mt-0.5 opacity-70">{opt.description}</p>}
            </button>
          );
        })}
      </div>
      <button
        type="button"
        disabled={!canSubmit}
        onClick={() => onSubmit({ selected_value: selected })}
        className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        Submit Selection
      </button>
    </div>
  );
}

// ─── Form Widget (interactive) ───────────────────────────────────────
function FormWidget({ data, onSubmit, isResponded }) {
  const [values, setValues] = useState(() => {
    const init = {};
    (data?.fields || []).forEach(f => { init[f.name] = f.default ?? ''; });
    return init;
  });

  if (isResponded) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
        Response submitted. Workflow continuing...
      </div>
    );
  }

  const handleChange = (name, val) => setValues(prev => ({ ...prev, [name]: val }));

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
      <p className="text-sm font-medium text-gray-800">{data?.prompt || 'Fill in the form'}</p>
      {(data?.fields || []).map((field) => (
        <div key={field.name}>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {field.label || field.name}
            {field.required && <span className="text-red-500 ml-0.5">*</span>}
          </label>
          {field.type === 'select' ? (
            <select
              value={values[field.name] || ''}
              onChange={(e) => handleChange(field.name, e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg"
            >
              <option value="">-- select --</option>
              {(field.options || []).map(o => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          ) : field.type === 'checkbox' ? (
            <input
              type="checkbox"
              checked={!!values[field.name]}
              onChange={(e) => handleChange(field.name, e.target.checked)}
            />
          ) : field.type === 'number' ? (
            <input
              type="number"
              value={values[field.name] ?? ''}
              onChange={(e) => handleChange(field.name, e.target.valueAsNumber)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg"
            />
          ) : (
            <input
              type="text"
              value={values[field.name] || ''}
              onChange={(e) => handleChange(field.name, e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg"
            />
          )}
        </div>
      ))}
      <button
        type="button"
        onClick={() => onSubmit(values)}
        className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
      >
        Submit
      </button>
    </div>
  );
}

// ─── List Selector (interactive: eliminate / pick one / pick many) ───
function ListSelector({ data, title, onDataChange }) {
  const items = data?.items || [];
  const mode = data?.mode || 'eliminate';

  const [kept, setKept] = useState(() => new Set(items.map((_, i) => i)));
  const [picked, setPicked] = useState(null);
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search) return items.map((item, i) => ({ ...item, _idx: i }));
    const q = search.toLowerCase();
    return items
      .map((item, i) => ({ ...item, _idx: i }))
      .filter(item => item.label.toLowerCase().includes(q));
  }, [items, search]);

  const emit = (nextKept, nextPicked) => {
    if (!onDataChange) return;
    if (mode === 'pick_one') {
      const chosen = nextPicked != null ? items[nextPicked] : null;
      onDataChange({ items, mode, selected: chosen ? chosen.value : null });
    } else {
      const remaining = items.filter((_, i) => nextKept.has(i));
      onDataChange({ items: remaining, mode });
    }
  };

  const toggleItem = (idx) => {
    if (mode === 'pick_one') {
      const next = picked === idx ? null : idx;
      setPicked(next);
      emit(kept, next);
    } else {
      setKept(prev => {
        const next = new Set(prev);
        if (next.has(idx)) next.delete(idx); else next.add(idx);
        emit(next, picked);
        return next;
      });
    }
  };

  const keptCount = mode === 'pick_one'
    ? (picked != null ? 1 : 0)
    : kept.size;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {title && (
        <div className="px-4 py-2.5 bg-gray-50 border-b text-sm font-semibold text-gray-700 flex items-center justify-between">
          <span>{title}</span>
          <span className="text-xs font-normal text-gray-500">
            {mode === 'pick_one' ? 'Pick one' : mode === 'pick_many' ? 'Pick items' : 'Uncheck to remove'}
          </span>
        </div>
      )}

      {items.length > 6 && (
        <div className="px-4 py-2 border-b">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search items..."
            className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
      )}

      <div className="max-h-80 overflow-y-auto divide-y divide-gray-100">
        {filtered.map((item) => {
          const idx = item._idx;
          const isActive = mode === 'pick_one' ? picked === idx : kept.has(idx);
          const isEliminated = mode !== 'pick_one' && !isActive;

          return (
            <button
              key={idx}
              type="button"
              onClick={() => toggleItem(idx)}
              className={`w-full text-left px-4 py-2.5 flex items-center gap-3 transition-colors ${
                isEliminated ? 'bg-gray-50 opacity-50' : 'hover:bg-gray-50'
              }`}
            >
              <div className={`w-5 h-5 rounded ${mode === 'pick_one' ? 'rounded-full' : ''} border-2 flex items-center justify-center shrink-0 transition-colors ${
                isActive
                  ? 'border-indigo-500 bg-indigo-500'
                  : 'border-gray-300 bg-white'
              }`}>
                {isActive && (
                  mode === 'pick_one'
                    ? <div className="w-2 h-2 rounded-full bg-white" />
                    : <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                )}
              </div>

              <span className={`text-sm flex-1 ${isEliminated ? 'line-through text-gray-400' : 'text-gray-900'}`}>
                {item.label}
              </span>
            </button>
          );
        })}
      </div>

      <div className="px-4 py-2 bg-gray-50 border-t flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {keptCount} of {items.length} selected
        </span>
        {mode !== 'pick_one' && kept.size < items.length && (
          <button
            type="button"
            onClick={() => { setKept(new Set(items.map((_, i) => i))); emit(new Set(items.map((_, i) => i)), picked); }}
            className="text-xs text-indigo-600 hover:text-indigo-700 font-medium"
          >
            Reset all
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Ask Widget (midway input — output.ask / selection / list / form) ──
//
// All four SDK pause primitives funnel through this widget because the
// backend tags every exit-42 deliverable with `output_type: "ask"` and
// stores the SDK's own `type` (one of "text" | "number" | "selection" |
// "confirm" | "file" | "list" | "form") in `data.type`.  We branch on
// `data.type` below.
//
// Submit contract: always emit `{ value: ... }` so the backend's resume
// path (`new_response = user_response`) and the SDK's
// `_pause_and_return` (which does `.get("value", cached)`) agree on the
// payload shape across every pause kind.
function AskWidget({ data, deliverableId, onSubmit, isResponded }) {
  const askType = data?.type || 'text';
  const allowMultipleSelection = askType === 'selection' && !!(data?.multiple || data?.allow_multiple);
  const listItems = Array.isArray(data?.items) ? data.items : [];
  const listMode = data?.mode || 'eliminate';
  const formFields = Array.isArray(data?.fields) ? data.fields : [];

  const [textValue, setTextValue] = useState(data?.default ?? '');
  const [selectedOption, setSelectedOption] = useState(null);
  const [selectedOptions, setSelectedOptions] = useState([]);
  const [listKept, setListKept] = useState(
    // eliminate starts with everything kept; pick_one / pick_many start empty
    () => new Set(listMode === 'eliminate' ? listItems.map((_, i) => i) : []),
  );
  const [listPicked, setListPicked] = useState(null);
  const [listSearch, setListSearch] = useState('');
  const [formValues, setFormValues] = useState(() => {
    const init = {};
    formFields.forEach(f => {
      const fallback = f.type === 'checkbox' ? false : (f.type === 'number' ? null : '');
      init[f.name] = f.default ?? fallback;
    });
    return init;
  });
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const allowMultiple = !!data?.multiple;

  if (isResponded || submitting) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
        Please wait while the process continues...
      </div>
    );
  }

  const addFiles = (newFiles) => {
    if (!newFiles || newFiles.length === 0) return;
    setUploadError(null);
    if (allowMultiple) {
      setFiles(prev => [...prev, ...Array.from(newFiles)]);
    } else {
      setFiles([newFiles[0]]);
    }
  };

  const removeFile = (idx) => setFiles(prev => prev.filter((_, i) => i !== idx));

  const handleFileChange = (e) => addFiles(e.target.files);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer.files);
  };

  const handleSubmitFile = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setUploadError(null);
    try {
      const results = [];
      for (const f of files) {
        const formData = new FormData();
        formData.append('file', f);
        formData.append('deliverable_id', deliverableId || '');
        const resp = await authenticatedFetch(`${API_BASE_URL}/api/code-executor/upload-midway`, {
          method: 'POST',
          body: formData,
        });
        if (!resp.ok) {
          const errBody = await resp.text();
          throw new Error(`Upload failed for ${f.name} (${resp.status}): ${errBody}`);
        }
        results.push(await resp.json());
      }
      if (allowMultiple) {
        onSubmit({
          value: results.map(r => `/workspace/uploads/${r.filename}`),
          files: results.map(r => ({
            filename: r.filename,
            blob_name: r.blob_name,
            local_path: r.local_path,
            upload_id: r.upload_id,
          })),
        });
      } else {
        const r = results[0];
        onSubmit({
          value: r.filename,
          filename: r.filename,
          blob_name: r.blob_name,
          local_path: r.local_path,
          upload_id: r.upload_id,
        });
      }
    } catch (err) {
      console.error('File upload failed:', err);
      setUploadError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleSubmitText = () => {
    if (!textValue && textValue !== 0) return;
    setSubmitting(true);
    const val = askType === 'number' ? Number(textValue) : textValue;
    onSubmit({ value: val });
  };

  const handleSubmitSelection = () => {
    if (selectedOption == null) return;
    setSubmitting(true);
    onSubmit({ value: selectedOption });
  };

  const handleSubmitSelectionMulti = () => {
    if (selectedOptions.length === 0) return;
    setSubmitting(true);
    onSubmit({ value: selectedOptions });
  };

  const toggleSelectionOption = (optVal) => {
    setSelectedOptions(prev =>
      prev.some(v => JSON.stringify(v) === JSON.stringify(optVal))
        ? prev.filter(v => JSON.stringify(v) !== JSON.stringify(optVal))
        : [...prev, optVal],
    );
  };

  const handleSubmitConfirm = (val) => {
    setSubmitting(true);
    onSubmit({ value: val });
  };

  // ── List (eliminate / pick_one / pick_many) ──
  const filteredListItems = listSearch
    ? listItems
        .map((item, i) => ({ ...item, _idx: i }))
        .filter(it => (it.label || '').toLowerCase().includes(listSearch.toLowerCase()))
    : listItems.map((item, i) => ({ ...item, _idx: i }));

  const toggleListItem = (idx) => {
    if (listMode === 'pick_one') {
      setListPicked(prev => (prev === idx ? null : idx));
    } else {
      setListKept(prev => {
        const next = new Set(prev);
        if (next.has(idx)) next.delete(idx); else next.add(idx);
        return next;
      });
    }
  };

  const handleSubmitList = () => {
    if (listMode === 'pick_one') {
      if (listPicked == null) return;
      setSubmitting(true);
      onSubmit({ value: listItems[listPicked]?.value });
    } else {
      if (listKept.size === 0) return;
      setSubmitting(true);
      const values = listItems
        .map((it, i) => ({ it, i }))
        .filter(x => listKept.has(x.i))
        .map(x => x.it.value);
      onSubmit({ value: values });
    }
  };

  // ── Form ──
  const handleFormFieldChange = (name, val) => {
    setFormValues(prev => ({ ...prev, [name]: val }));
  };

  const handleSubmitForm = () => {
    // Basic required-field check
    for (const f of formFields) {
      if (f.required) {
        const v = formValues[f.name];
        if (v === '' || v == null) return;
      }
    }
    setSubmitting(true);
    onSubmit({ value: formValues });
  };

  return (
    <div className="bg-white rounded-lg border-2 border-amber-200 p-5 space-y-4">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center shrink-0 mt-0.5">
          <svg className="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <p className="text-sm font-medium text-gray-800 pt-1">{data?.prompt || 'The script needs your input to continue.'}</p>
      </div>

      {/* Text / Number input */}
      {(askType === 'text' || askType === 'number') && (
        <div className="space-y-3">
          <input
            type={askType === 'number' ? 'number' : 'text'}
            value={textValue}
            onChange={(e) => setTextValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSubmitText()}
            placeholder={data?.default != null ? String(data.default) : 'Type your answer...'}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-transparent"
            autoFocus
          />
          <button
            type="button"
            onClick={handleSubmitText}
            disabled={!textValue && textValue !== 0}
            className="px-4 py-2 text-sm bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Submit
          </button>
        </div>
      )}

      {/* Single-select (radio) */}
      {askType === 'selection' && !allowMultipleSelection && data?.options && (
        <div className="space-y-3">
          <div className="space-y-2">
            {data.options.map((opt, idx) => {
              const optVal = typeof opt === 'string' ? opt : opt.value;
              const optLabel = typeof opt === 'string' ? opt : opt.label;
              const isActive = JSON.stringify(selectedOption) === JSON.stringify(optVal);
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setSelectedOption(optVal)}
                  className={`w-full text-left p-3 rounded-lg border-2 transition-all text-sm ${
                    isActive
                      ? 'border-amber-400 bg-amber-50 text-amber-900'
                      : 'border-gray-200 hover:border-gray-300 bg-white text-gray-700'
                  }`}
                >
                  {optLabel}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={handleSubmitSelection}
            disabled={selectedOption == null}
            className="px-4 py-2 text-sm bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Submit Selection
          </button>
        </div>
      )}

      {/* Multi-select (checkboxes) */}
      {askType === 'selection' && allowMultipleSelection && data?.options && (
        <div className="space-y-3">
          <div className="space-y-2">
            {data.options.map((opt, idx) => {
              const optVal = typeof opt === 'string' ? opt : opt.value;
              const optLabel = typeof opt === 'string' ? opt : opt.label;
              const isActive = selectedOptions.some(v => JSON.stringify(v) === JSON.stringify(optVal));
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => toggleSelectionOption(optVal)}
                  className={`w-full text-left p-3 rounded-lg border-2 transition-all text-sm flex items-center gap-3 ${
                    isActive
                      ? 'border-amber-400 bg-amber-50 text-amber-900'
                      : 'border-gray-200 hover:border-gray-300 bg-white text-gray-700'
                  }`}
                >
                  <div className={`w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-colors ${
                    isActive ? 'border-amber-500 bg-amber-500' : 'border-gray-300 bg-white'
                  }`}>
                    {isActive && (
                      <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    )}
                  </div>
                  <span>{optLabel}</span>
                </button>
              );
            })}
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">
              {selectedOptions.length} of {(data.options || []).length} selected
            </span>
            <button
              type="button"
              onClick={handleSubmitSelectionMulti}
              disabled={selectedOptions.length === 0}
              className="px-4 py-2 text-sm bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Submit ({selectedOptions.length})
            </button>
          </div>
        </div>
      )}

      {/* Filterable list (eliminate / pick_one / pick_many) */}
      {askType === 'list' && listItems.length > 0 && (
        <div className="space-y-3">
          {listItems.length > 6 && (
            <input
              type="text"
              value={listSearch}
              onChange={(e) => setListSearch(e.target.value)}
              placeholder="Search items..."
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
          )}
          <div className="max-h-80 overflow-y-auto divide-y divide-gray-100 border border-gray-200 rounded-lg">
            {filteredListItems.map((item) => {
              const idx = item._idx;
              const isActive = listMode === 'pick_one' ? listPicked === idx : listKept.has(idx);
              const isDimmed = listMode === 'eliminate' && !isActive;
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => toggleListItem(idx)}
                  className={`w-full text-left px-3 py-2 flex items-center gap-3 transition-colors ${
                    isDimmed ? 'bg-gray-50 opacity-50' : 'hover:bg-gray-50'
                  }`}
                >
                  <div className={`w-4 h-4 ${listMode === 'pick_one' ? 'rounded-full' : 'rounded'} border-2 flex items-center justify-center shrink-0 transition-colors ${
                    isActive ? 'border-amber-500 bg-amber-500' : 'border-gray-300 bg-white'
                  }`}>
                    {isActive && (
                      listMode === 'pick_one'
                        ? <div className="w-1.5 h-1.5 rounded-full bg-white" />
                        : <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                    )}
                  </div>
                  <span className={`text-sm flex-1 ${isDimmed ? 'line-through text-gray-400' : 'text-gray-800'}`}>
                    {item.label}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">
              {listMode === 'pick_one'
                ? (listPicked != null ? '1 selected' : 'Pick one')
                : `${listKept.size} of ${listItems.length} selected`}
            </span>
            <button
              type="button"
              onClick={handleSubmitList}
              disabled={listMode === 'pick_one' ? listPicked == null : listKept.size === 0}
              className="px-4 py-2 text-sm bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Submit
            </button>
          </div>
        </div>
      )}

      {/* Form (multi-field) */}
      {askType === 'form' && formFields.length > 0 && (
        <div className="space-y-3">
          {formFields.map((field) => (
            <div key={field.name}>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                {field.label || field.name}
                {field.required && <span className="text-red-500 ml-0.5">*</span>}
              </label>
              {field.type === 'select' ? (
                <select
                  value={formValues[field.name] ?? ''}
                  onChange={(e) => handleFormFieldChange(field.name, e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-400"
                >
                  <option value="">-- select --</option>
                  {(field.options || []).map((o, oi) => {
                    const oVal = typeof o === 'string' ? o : o.value;
                    const oLabel = typeof o === 'string' ? o : o.label;
                    return <option key={oi} value={oVal}>{oLabel}</option>;
                  })}
                </select>
              ) : field.type === 'checkbox' ? (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!formValues[field.name]}
                    onChange={(e) => handleFormFieldChange(field.name, e.target.checked)}
                    className="w-4 h-4 text-amber-500 rounded focus:ring-amber-400"
                  />
                  <span className="text-xs text-gray-600">{field.description || ''}</span>
                </label>
              ) : field.type === 'number' ? (
                <input
                  type="number"
                  value={formValues[field.name] ?? ''}
                  onChange={(e) => handleFormFieldChange(field.name, e.target.valueAsNumber)}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-400"
                />
              ) : (
                <input
                  type="text"
                  value={formValues[field.name] ?? ''}
                  onChange={(e) => handleFormFieldChange(field.name, e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-400"
                />
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={handleSubmitForm}
            className="px-4 py-2 text-sm bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors"
          >
            Submit
          </button>
        </div>
      )}

      {/* Confirm (yes/no) */}
      {askType === 'confirm' && (
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => handleSubmitConfirm(true)}
            className="flex-1 px-4 py-2.5 text-sm bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-colors font-medium"
          >
            Yes
          </button>
          <button
            type="button"
            onClick={() => handleSubmitConfirm(false)}
            className="flex-1 px-4 py-2.5 text-sm bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors font-medium"
          >
            No
          </button>
        </div>
      )}

      {/* File upload */}
      {askType === 'file' && (
        <div className="space-y-2">
          {files.length > 0 && (
            <div className="space-y-1">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-2 px-2 py-1.5 bg-emerald-50 border border-emerald-200 rounded text-xs">
                  <svg className="w-3.5 h-3.5 text-emerald-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="font-medium text-gray-700 truncate flex-1">{f.name}</span>
                  <span className="text-gray-400 shrink-0">({(f.size / 1024).toFixed(1)} KB)</span>
                  <button type="button" onClick={() => removeFile(i)} className="text-red-400 hover:text-red-600 shrink-0">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}

          <label
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`block border-2 border-dashed rounded-lg p-3 text-center transition-colors cursor-pointer ${
              dragOver ? 'border-amber-400 bg-amber-50' : 'border-gray-300 hover:border-gray-400'
            }`}
          >
            <svg className="w-6 h-6 mx-auto text-gray-400 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-xs text-gray-500">
              {files.length > 0
                ? (allowMultiple ? 'Drop or click to add more files' : 'Drop or click to replace')
                : (allowMultiple ? 'Drag & drop files here, or click to browse' : 'Drag & drop a file here, or click to browse')}
            </p>
            <input
              type="file"
              className="hidden"
              onChange={handleFileChange}
              accept={data?.accept || '*'}
              multiple={allowMultiple}
            />
          </label>

          {uploadError && <p className="text-xs text-red-600">{uploadError}</p>}
          <button
            type="button"
            onClick={handleSubmitFile}
            disabled={files.length === 0 || uploading}
            className="px-3 py-1 text-xs bg-amber-500 text-white rounded hover:bg-amber-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {uploading ? 'Uploading...' : `Upload${files.length > 1 ? ` ${files.length} files` : ''} & Continue`}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Error Renderer ──────────────────────────────────────────────────
function ErrorRenderer({ data, execLog }) {
  const errorMsg = data?.error || execLog?.error || 'Unknown error';

  return (
    <div className="bg-red-50 border border-red-200 rounded-lg overflow-hidden">
      <div className="px-4 py-3 flex items-start gap-3">
        <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-red-800">Execution Failed</p>
          <pre className="mt-1 text-xs text-red-700 whitespace-pre-wrap break-words font-mono">{errorMsg}</pre>
        </div>
      </div>
    </div>
  );
}

// ─── Execution Log Panel ─────────────────────────────────────────────
function ExecutionLogPanel({ execLog }) {
  const [expanded, setExpanded] = useState(false);

  if (!execLog) return null;
  const { stdout, stderr, exit_code, duration_ms, error } = execLog;
  const hasContent = stdout || stderr || error;

  return (
    <div className="bg-gray-950 rounded-lg border border-gray-800 overflow-hidden text-xs">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-900 hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2z" />
          </svg>
          <span className="font-medium text-gray-300">Execution Logs</span>
          {exit_code != null && (
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
              exit_code === 0 ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'
            }`}>
              exit {exit_code}
            </span>
          )}
          {duration_ms != null && (
            <span className="text-gray-500">{(duration_ms / 1000).toFixed(1)}s</span>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="p-3 font-mono leading-5 overflow-x-auto max-h-80 overflow-y-auto">
          {!hasContent && (
            <div className="text-gray-500 italic">No console output (script used SDK structured output).</div>
          )}
          {stdout && (
            <div>
              <div className="text-gray-500 mb-1 select-none">stdout:</div>
              <pre className="text-green-300 whitespace-pre-wrap break-words">{stdout}</pre>
            </div>
          )}
          {stderr && (
            <div className={stdout ? 'mt-3' : ''}>
              <div className="text-gray-500 mb-1 select-none">stderr:</div>
              <pre className="text-red-400 whitespace-pre-wrap break-words">{stderr}</pre>
            </div>
          )}
          {error && !stderr?.includes(error) && (
            <div className="mt-3">
              <div className="text-gray-500 mb-1 select-none">error:</div>
              <pre className="text-red-400 whitespace-pre-wrap break-words">{error}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────
const INTERNAL_KEYS = new Set(['_output_type', '_interactive', '_metadata', '_user_response', '_output_files', '_visualization', '_execution_log', '_raw']);

function stripInternal(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return obj;
  if ('_raw' in obj) return obj._raw;
  const clean = {};
  for (const [k, v] of Object.entries(obj)) {
    if (!INTERNAL_KEYS.has(k)) clean[k] = v;
  }
  return clean;
}

// ─── Interactive self-contained HTML export ─────────────────────────
//
// The user can reopen any rendered visualization (DSL primitives OR a
// JS `type: "render"` custom script) as a *live* standalone file in
// Chrome — filters, buttons, accordions, tabs, sorting, and any
// custom render() JavaScript keep working after export.  The export
// is NOT a DOM screenshot; it's a real React app bootstrapped via
// UMD bundles from CDN, carrying its own inlined DSL runtime.  See
// ../../utils/vizExport.js for the runtime + template.
//
// For the export to work offline the user needs the CDN bundles
// cached (React/ReactDOM/Recharts/Tailwind).  First-time open
// online, subsequent opens work offline because of browser caching.
// ───────────────────────────────────────────────────────────────────

function VizRenderer({ visualization, data, title }) {
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      // One tick so the button's "Exporting…" label paints before we
      // start serializing; the work itself is synchronous but large
      // dashboards can block for a frame while we JSON.stringify the
      // payload.
      await new Promise((r) => requestAnimationFrame(r));
      const { downloadVisualizationAsHtml } = await import('../../utils/vizExport');
      downloadVisualizationAsHtml({
        visualization,
        data,
        title: title || 'Visualization',
      });
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="relative group">
      <button
        type="button"
        onClick={handleExport}
        disabled={exporting}
        title="Download this visualization as a self-contained, interactive HTML file"
        className="absolute top-2 right-2 z-10 inline-flex items-center gap-1 px-2 py-1 text-[10.5px] font-medium rounded border border-gray-300 bg-white/90 text-gray-700 shadow-sm opacity-0 group-hover:opacity-100 hover:bg-white hover:border-gray-400 transition-opacity disabled:opacity-60"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3v12" />
          <path d="m7 10 5 5 5-5" />
          <path d="M5 21h14" />
        </svg>
        {exporting ? 'Exporting…' : 'Export HTML'}
      </button>
      <Suspense fallback={<div className="text-sm text-gray-400 p-4">Loading visualization...</div>}>
        <VisualizationRenderer visualization={visualization} data={data} />
      </Suspense>
    </div>
  );
}

// ─── Main ────────────────────────────────────────────────────────────
export default function CodeExecutorOutput({ deliverable, onWidgetRespond, onDataChange, executionId }) {
  const [responded, setResponded] = useState(!!deliverable.userResponse);
  const rawPayload = deliverable.deliverable || {};
  const outputType = deliverable.outputType;

  // Multi-pause: only reset `responded` when a genuinely NEW ask arrives.
  // Watching updatedAt caused false resets because backend status changes
  // (approved) bump updatedAt before the next ask's deliverable data arrives.
  // Note: DeliverableReview also keys this component on pause_index to
  // force a full remount, so this effect is a belt-and-suspenders reset.
  const pauseIndex = rawPayload?.pause_index;
  const prevPauseIndexRef = useRef(pauseIndex);
  useEffect(() => {
    if (pauseIndex !== prevPauseIndexRef.current) {
      prevPauseIndexRef.current = pauseIndex;
      setResponded(!!deliverable.userResponse);
    }
  }, [pauseIndex, deliverable.userResponse]);
  const metadata = rawPayload._metadata || {};
  const outputFiles = rawPayload._output_files || [];
  const payload = stripInternal(rawPayload);

  const handleSubmit = async (response) => {
    setResponded(true);
    if (onWidgetRespond) await onWidgetRespond(response);
  };

  const handleDataChange = (updatedData) => {
    if (onDataChange) {
      const full = { ...rawPayload };
      for (const key of Object.keys(updatedData)) {
        full[key] = updatedData[key];
      }
      for (const ik of INTERNAL_KEYS) {
        if (ik in rawPayload) full[ik] = rawPayload[ik];
      }
      onDataChange(full);
    }
  };

  let content;
  switch (outputType) {
    case 'data': {
      // Canonical path: data + optional visualization DSL.
      if (rawPayload._visualization) {
        content = <VizRenderer visualization={rawPayload._visualization} data={payload} title={metadata.title} />;
      } else {
        content = <DataRenderer data={payload} title={metadata.title} onDataChange={handleDataChange} />;
      }
      break;
    }

    case 'table': {
      // Legacy: convert to DSL table spec.
      const viz = tableToSpec(payload, metadata);
      content = <VizRenderer visualization={viz} data={payload} title={metadata.title || 'Table'} />;
      break;
    }

    case 'chart': {
      // Legacy: convert to DSL chart spec.
      const viz = chartToSpec(payload, metadata);
      content = <VizRenderer visualization={viz} data={payload} title={metadata.title || 'Chart'} />;
      break;
    }

    case 'document': {
      // Legacy: convert to DSL (header + accordion + flowchart).
      const viz = documentToSpec(payload);
      content = <VizRenderer visualization={viz} data={payload} title={metadata.title || 'Document'} />;
      break;
    }

    case 'file':
      content = <FileRenderer data={payload} outputFiles={outputFiles} />;
      break;

    case 'files':
      content = <FilesRenderer data={payload} title={metadata.title} />;
      break;

    case 'list':
      content = <ListSelector data={payload} title={metadata.title} onDataChange={handleDataChange} />;
      break;

    case 'selection':
      content = <SelectionWidget data={payload} onSubmit={handleSubmit} isResponded={responded} />;
      break;

    case 'form':
      content = <FormWidget data={payload} onSubmit={handleSubmit} isResponded={responded} />;
      break;

    case 'ask':
      content = <AskWidget data={payload} deliverableId={deliverable.id} onSubmit={handleSubmit} isResponded={responded} />;
      break;

    case 'error':
      content = <ErrorRenderer data={payload} execLog={rawPayload._execution_log} />;
      break;

    case 'edwin_handoff': {
      const edwinUrl = rawPayload.edwin_url || rawPayload.edwinUrl;
      const sourceCount = rawPayload.source_count ?? rawPayload.sourceCount;
      content = (
        <div className="rounded-lg border border-[#6b6b6b] bg-[rgba(70,70,70,0.35)] p-4 space-y-2">
          <p className="text-sm text-white font-medium">
            Edwin presentation session created
            {typeof sourceCount === 'number' ? ` from ${sourceCount} workflow step(s)` : ''}.
          </p>
          <p className="text-xs text-[#b5b5b5]">
            A new tab should open automatically. If it did not, use the link below.
          </p>
          {edwinUrl ? (
            <a
              href={edwinUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex text-sm text-[#d93854] hover:underline font-medium"
            >
              Open in Edwin
            </a>
          ) : null}
        </div>
      );
      break;
    }

    default:
      content = <DataRenderer data={payload} title={metadata.title || 'Output'} />;
  }

  const execLog = rawPayload._execution_log || null;
  const hasAttachedFiles = outputFiles.length > 0 && outputType !== 'file' && outputType !== 'files';
  const isExecuting = deliverable.status === 'running' || deliverable.status === 'executing';

  return (
    <div className="space-y-3">
      {executionId && isExecuting && (
        <ExecutionStreamPanel executionId={executionId} />
      )}
      {content}
      {execLog && <ExecutionLogPanel execLog={execLog} />}
      {hasAttachedFiles && (
        <div className="mt-2">
          <div className="text-xs font-medium text-gray-500 mb-1.5 uppercase tracking-wide">Attached Files</div>
          <div className="space-y-1.5">
            {outputFiles.map((f, i) => (
              <FileCard key={i} name={f.name || f.display_name} downloadUrl={f.download_url} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
