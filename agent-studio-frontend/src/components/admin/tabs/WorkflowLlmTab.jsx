import { useEffect, useState } from 'react';
import {
  fetchAdminWorkflowModels,
  patchAdminModel,
  triggerWorkflowModelScan,
  previewWorkflowModelReplace,
  executeWorkflowModelReplace,
} from '../../../api/admin';
import { fetchAllModels } from '../../../api/models';

function usageCell(workflows, fieldRefs, snapshotNote) {
  if (!workflows && !fieldRefs) return <span className="text-gray-600">—</span>;
  return (
    <div>
      <div>{workflows} workflow{workflows === 1 ? '' : 's'}</div>
      <div className="text-xs text-gray-500">
        {fieldRefs} node field{fieldRefs === 1 ? '' : 's'}
        {snapshotNote ? ` · ${snapshotNote}` : ''}
      </div>
    </div>
  );
}

export default function WorkflowLlmTab() {
  const [rows, setRows] = useState([]);
  const [modelOptions, setModelOptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const [lastScan, setLastScan] = useState(null);

  const [replaceRow, setReplaceRow] = useState(null);
  const [replaceTo, setReplaceTo] = useState('');
  const [includeLive, setIncludeLive] = useState(true);
  const [includePublished, setIncludePublished] = useState(true);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [replacing, setReplacing] = useState(false);

  const load = async () => {
    const data = await fetchAdminWorkflowModels();
    setRows(data);
    const latest = data.find((r) => r.last_scanned_at);
    if (latest?.last_scanned_at) setLastScan(latest.last_scanned_at);
  };

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const catalog = await fetchAllModels().catch(() => null);
        const opts = [];
        if (catalog?.providers) {
          Object.values(catalog.providers).forEach((p) => {
            (p.models || []).forEach((m) => {
              opts.push({ value: m.id || m.value, label: m.label || m.id });
            });
          });
        }
        setModelOptions(opts);
        await load();
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const openReplace = (row) => {
    setReplaceRow(row);
    setReplaceTo('');
    setPreview(null);
    setConfirmText('');
    setIncludeLive(true);
    setIncludePublished(true);
    setError(null);
  };

  const closeReplace = () => {
    setReplaceRow(null);
    setPreview(null);
    setConfirmText('');
  };

  const handlePreviewReplace = async () => {
    if (!replaceRow || !replaceTo) return;
    try {
      setPreviewLoading(true);
      setError(null);
      const result = await previewWorkflowModelReplace({
        from_model: replaceRow.model_name,
        to_model: replaceTo,
        include_live: includeLive,
        include_published: includePublished,
      });
      setPreview(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleExecuteReplace = async () => {
    if (!replaceRow || !replaceTo || !preview?.required_confirmation) return;
    try {
      setReplacing(true);
      setError(null);
      await executeWorkflowModelReplace({
        from_model: replaceRow.model_name,
        to_model: replaceTo,
        confirmation: confirmText,
        include_live: includeLive,
        include_published: includePublished,
      });
      closeReplace();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setReplacing(false);
    }
  };

  const handleScan = async () => {
    try {
      setScanning(true);
      setError(null);
      const summary = await triggerWorkflowModelScan();
      setLastScan(summary.scanned_at);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  };

  const handleFallback = async (modelName, fallback_model_name) => {
    try {
      await patchAdminModel(modelName, {
        fallback_model_name: fallback_model_name || null,
      });
      setRows((prev) =>
        prev.map((r) =>
          r.model_name === modelName ? { ...r, fallback_model_name } : r
        )
      );
    } catch (e) {
      setError(e.message);
    }
  };

  const hasUsage = (r) =>
    (r.live_workflows ?? 0) > 0 ||
    (r.published_workflows ?? 0) > 0 ||
    (r.live_field_refs ?? r.live_occurrences ?? 0) > 0;

  if (loading) {
    return <div className="p-8 text-gray-400">Loading workflow LLM inventory…</div>;
  }

  return (
    <div className="p-6 overflow-auto h-full" style={{ color: '#e5e5e5' }}>
      <div className="flex items-center justify-between mb-4">
        <div className="max-w-3xl">
          <h2 className="text-xl font-semibold">Workflow LLM</h2>
          <p className="text-sm text-gray-400 mt-1">
            Models referenced in saved workflow graphs (agent nodes). Counts come from the last scan
            stored in <span className="font-mono text-gray-500">llm_model_workflow_usage</span> in Postgres.
            {lastScan && (
              <span className="ml-1">Last scan: {new Date(lastScan).toLocaleString()}.</span>
            )}
          </p>
          <p className="text-xs text-gray-500 mt-2 leading-relaxed">
            <strong>Live</strong> — current <span className="font-mono">workflow_entity</span> definitions.
            <strong className="ml-2">Published</strong> — unique workflows that have a published snapshot
            in <span className="font-mono">workflow_history</span> using this model (plus snapshot count).
            <strong className="ml-2">Scan now</strong> re-reads all workflow JSON, updates usage counts, and
            registers any newly seen models in <span className="font-mono">llm_models</span>.
            Fallback applies at runtime when a call fails; <strong>Replace in workflows</strong> rewrites
            saved node configs.
          </p>
        </div>
        <button
          type="button"
          onClick={handleScan}
          disabled={scanning}
          className="px-4 py-2 rounded bg-orange-600 hover:bg-orange-500 text-white text-sm font-medium disabled:opacity-50 shrink-0"
        >
          {scanning ? 'Scanning…' : 'Scan now'}
        </button>
      </div>
      {error && (
        <div className="mb-4 p-3 rounded bg-red-900/40 text-red-200 text-sm">{error}</div>
      )}

      {replaceRow && (
        <div className="mb-6 p-4 rounded border border-orange-600/40 bg-orange-950/20">
          <h3 className="font-semibold text-orange-300 mb-2">Replace model in workflows</h3>
          <p className="text-sm text-gray-400 mb-4">
            Rewrites <span className="font-mono text-gray-200">{replaceRow.model_name}</span> to a new
            model in agent node configs (modelName + modelProvider). Run preview first.
          </p>
          <div className="flex flex-wrap gap-4 items-end mb-4">
            <label className="text-sm">
              <span className="block text-gray-500 mb-1">Replace with</span>
              <select
                className="bg-gray-900 border border-gray-600 rounded px-2 py-1 min-w-[220px]"
                value={replaceTo}
                onChange={(e) => {
                  setReplaceTo(e.target.value);
                  setPreview(null);
                  setConfirmText('');
                }}
              >
                <option value="">Select target model…</option>
                {modelOptions
                  .filter((o) => o.value !== replaceRow.model_name)
                  .map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeLive}
                onChange={(e) => setIncludeLive(e.target.checked)}
              />
              Live workflows
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includePublished}
                onChange={(e) => setIncludePublished(e.target.checked)}
              />
              Published snapshots
            </label>
            <button
              type="button"
              disabled={!replaceTo || previewLoading}
              onClick={handlePreviewReplace}
              className="px-3 py-1.5 rounded border border-gray-600 hover:bg-gray-800 text-sm disabled:opacity-50"
            >
              {previewLoading ? 'Previewing…' : 'Preview impact'}
            </button>
            <button type="button" onClick={closeReplace} className="px-3 py-1.5 text-sm text-gray-400">
              Cancel
            </button>
          </div>

          {preview && (
            <div className="mb-4 p-3 rounded bg-gray-900/80 text-sm space-y-1">
              <p>Live workflows affected: <strong>{preview.live_workflows_affected}</strong> ({preview.live_node_fields_affected} fields)</p>
              <p>Published snapshots affected: <strong>{preview.published_snapshots_affected}</strong> ({preview.published_node_fields_affected} fields)</p>
              {preview.live_workflow_names?.length > 0 && (
                <div className="mt-2">
                  <p className="text-gray-400 text-xs font-medium mb-1">
                    Live workflows ({preview.live_workflow_names.length})
                  </p>
                  <ul className="text-xs text-gray-300 max-h-32 overflow-y-auto list-disc pl-4 space-y-0.5">
                    {preview.live_workflow_names.map((n) => (
                      <li key={`live-${n}`}>{n}</li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.published_workflow_names?.length > 0 && (
                <div className="mt-2">
                  <p className="text-gray-400 text-xs font-medium mb-1">
                    Published workflows ({preview.published_workflow_names.length})
                  </p>
                  <ul className="text-xs text-gray-300 max-h-32 overflow-y-auto list-disc pl-4 space-y-0.5">
                    {preview.published_workflow_names.map((n) => (
                      <li key={`pub-${n}`}>{n}</li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.affected_workflow_names?.length === 0 &&
                preview.live_workflows_affected === 0 &&
                preview.published_snapshots_affected === 0 && (
                  <p className="text-gray-500 text-xs mt-2">No workflows would be changed.</p>
                )}
              <p className="text-amber-400/90 mt-2">
                Type this exactly to confirm:
              </p>
              <p className="font-mono text-xs bg-black/40 p-2 rounded select-all">{preview.required_confirmation}</p>
              <input
                type="text"
                className="mt-2 w-full bg-gray-950 border border-gray-600 rounded px-2 py-1 font-mono text-sm"
                placeholder={preview.required_confirmation}
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
              />
              <button
                type="button"
                disabled={
                  replacing ||
                  confirmText.trim() !== preview.required_confirmation
                }
                onClick={handleExecuteReplace}
                className="mt-3 px-4 py-2 rounded bg-red-700 hover:bg-red-600 text-white text-sm font-medium disabled:opacity-40"
              >
                {replacing ? 'Replacing…' : 'Replace in all matching workflows'}
              </button>
            </div>
          )}
        </div>
      )}

      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-left">
            <tr>
              <th className="p-3">Model</th>
              <th className="p-3" title="Unique workflow_entity rows using this model">
                Live
              </th>
              <th className="p-3" title="Unique workflows with a published snapshot using this model">
                Published
              </th>
              <th className="p-3">Fallback</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const liveWf = r.live_workflows ?? 0;
              const pubWf = r.published_workflows ?? 0;
              const liveRefs = r.live_field_refs ?? r.live_occurrences ?? 0;
              const pubRefs = r.published_field_refs ?? r.published_occurrences ?? 0;
              const pubSnaps = r.published_snapshots ?? 0;
              return (
                <tr key={r.model_name} className="border-t border-gray-800">
                  <td className="p-3 font-mono text-xs">{r.model_name}</td>
                  <td className="p-3">{usageCell(liveWf, liveRefs)}</td>
                  <td className="p-3">
                    {usageCell(
                      pubWf,
                      pubRefs,
                      pubSnaps > 0 ? `${pubSnaps} snapshot${pubSnaps === 1 ? '' : 's'}` : null
                    )}
                  </td>
                  <td className="p-3">
                    <select
                      className="bg-gray-900 border border-gray-600 rounded px-2 py-1 max-w-[200px]"
                      value={r.fallback_model_name || ''}
                      onChange={(e) => handleFallback(r.model_name, e.target.value)}
                    >
                      <option value="">— none —</option>
                      {modelOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="p-3">
                    {hasUsage(r) ? (
                      <button
                        type="button"
                        onClick={() => openReplace(r)}
                        className="text-orange-400 hover:text-orange-300 text-xs font-medium"
                      >
                        Replace in workflows
                      </button>
                    ) : (
                      <span className="text-gray-600 text-xs">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="p-6 text-gray-500 text-center">No models yet. Run a scan to populate inventory.</p>
        )}
      </div>
    </div>
  );
}
