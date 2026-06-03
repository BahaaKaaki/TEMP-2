import { useCallback, useEffect, useState } from 'react';
import {
  fetchAdminModels,
  patchAdminModel,
  rebuildAdminModelCatalog,
  syncAllModelsToLangfuse,
  syncModelToLangfuse,
  triggerWorkflowModelScan,
} from '../../../api/admin';

function usageBadges(row) {
  const badges = [];
  if (row.in_tools) {
    badges.push(
      <span
        key="tools"
        className="inline-block px-2 py-0.5 rounded text-xs bg-blue-900/50 text-blue-200"
      >
        tools ({row.binding_count})
      </span>
    );
  }
  if (row.in_workflows) {
    badges.push(
      <span
        key="wf"
        className="inline-block px-2 py-0.5 rounded text-xs bg-purple-900/50 text-purple-200"
      >
        workflows ({row.live_workflows + row.published_workflows})
      </span>
    );
  }
  if (row.is_fallback_for_others) {
    badges.push(
      <span
        key="fb"
        className="inline-block px-2 py-0.5 rounded text-xs bg-orange-900/40 text-orange-200"
      >
        fallback for {row.fallback_for_models.length}
      </span>
    );
  }
  if (row.fallback_model_name) {
    badges.push(
      <span
        key="has-fb"
        className="inline-block px-2 py-0.5 rounded text-xs bg-gray-800 text-gray-300"
      >
        → {row.fallback_model_name}
      </span>
    );
  }
  if (!badges.length) {
    return <span className="text-gray-600 text-xs">catalog only</span>;
  }
  return <div className="flex flex-wrap gap-1">{badges}</div>;
}

function formatPrice(val) {
  if (val === null || val === undefined || val === '') return '';
  return String(val);
}

export default function AllModelsTab() {
  const [rows, setRows] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(null);
  const [syncing, setSyncing] = useState(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async () => {
    const data = await fetchAdminModels();
    setRows(data);
    const next = {};
    data.forEach((r) => {
      next[r.model_name] = {
        input_price_per_1m_tokens: formatPrice(r.input_price_per_1m_tokens),
        output_price_per_1m_tokens: formatPrice(r.output_price_per_1m_tokens),
        cache_read_price_per_1m_tokens: formatPrice(r.cache_read_price_per_1m_tokens),
        cache_creation_price_per_1m_tokens: formatPrice(r.cache_creation_price_per_1m_tokens),
        admin_notes: r.admin_notes || '',
        langfuse_match_pattern: r.langfuse_match_pattern || '',
      };
    });
    setDrafts(next);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        setError(null);
        await load();
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [load]);

  const setDraft = (modelName, field, value) => {
    setDrafts((prev) => ({
      ...prev,
      [modelName]: { ...prev[modelName], [field]: value },
    }));
  };

  const handleSave = async (modelName) => {
    const d = drafts[modelName];
    if (!d) return;
    try {
      setSaving(modelName);
      setError(null);
      const body = {};
      const parsePrice = (v) => {
        if (v === '' || v === null || v === undefined) return null;
        const n = parseFloat(v);
        return Number.isFinite(n) ? n : null;
      };
      body.input_price_per_1m_tokens = parsePrice(d.input_price_per_1m_tokens);
      body.output_price_per_1m_tokens = parsePrice(d.output_price_per_1m_tokens);
      body.cache_read_price_per_1m_tokens = parsePrice(d.cache_read_price_per_1m_tokens);
      body.cache_creation_price_per_1m_tokens = parsePrice(d.cache_creation_price_per_1m_tokens);
      body.admin_notes = d.admin_notes;
      body.langfuse_match_pattern = d.langfuse_match_pattern || null;
      await patchAdminModel(modelName, body);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(null);
    }
  };

  const handleSyncOne = async (modelName) => {
    try {
      setSyncing(modelName);
      setError(null);
      const result = await syncModelToLangfuse(modelName);
      if (result.status === 'error') {
        setError(`${modelName}: ${result.reason}`);
      }
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSyncing(null);
    }
  };

  const handleSyncAll = async () => {
    try {
      setSyncing('all');
      setError(null);
      const result = await syncAllModelsToLangfuse();
      if (result.failed > 0) {
        setError(`Langfuse sync: ${result.synced} ok, ${result.failed} failed`);
      }
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSyncing(null);
    }
  };

  const handleRebuild = async () => {
    try {
      setRebuilding(true);
      setError(null);
      await rebuildAdminModelCatalog();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setRebuilding(false);
    }
  };

  const handleScan = async () => {
    try {
      setScanning(true);
      setError(null);
      await triggerWorkflowModelScan();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-gray-400">Loading model catalog…</div>;
  }

  return (
    <div className="p-6 overflow-auto h-full" style={{ color: '#e5e5e5' }}>
      <h2 className="text-xl font-semibold mb-2">All models</h2>
      <p className="text-sm text-gray-400 mb-4 max-w-3xl">
        Single source of truth in <code className="text-gray-300">llm_models</code>: every model
        used in tools, workflows, and fallbacks. Set USD pricing per 1M tokens (input, output,
        cache read, cache write). Empty cache fields default to 10% / 125% of input when syncing
        to Langfuse. Run workflow scan to refresh usage counts.
      </p>

      <div className="flex flex-wrap gap-2 mb-6">
        <button
          type="button"
          className="px-3 py-1.5 rounded text-sm bg-gray-800 border border-gray-600 hover:bg-gray-700 disabled:opacity-50"
          disabled={rebuilding}
          onClick={handleRebuild}
        >
          {rebuilding ? 'Rebuilding…' : 'Rebuild catalog'}
        </button>
        <button
          type="button"
          className="px-3 py-1.5 rounded text-sm bg-gray-800 border border-gray-600 hover:bg-gray-700 disabled:opacity-50"
          disabled={scanning}
          onClick={handleScan}
        >
          {scanning ? 'Scanning workflows…' : 'Scan workflows'}
        </button>
        <button
          type="button"
          className="px-3 py-1.5 rounded text-sm bg-orange-900/40 border border-orange-600/50 hover:bg-orange-900/60 disabled:opacity-50"
          disabled={syncing === 'all'}
          onClick={handleSyncAll}
        >
          {syncing === 'all' ? 'Syncing to Langfuse…' : 'Sync all priced models → Langfuse'}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded bg-red-900/40 text-red-200 text-sm">{error}</div>
      )}

      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm min-w-[1300px]">
          <thead className="bg-gray-900 text-left">
            <tr>
              <th className="p-3">Model</th>
              <th className="p-3">Usage</th>
              <th className="p-3">Input $/1M</th>
              <th className="p-3">Output $/1M</th>
              <th className="p-3" title="Prompt cache read; blank = 10% of input">
                Cache read $/1M
              </th>
              <th className="p-3" title="Prompt cache write; blank = 125% of input">
                Cache write $/1M
              </th>
              <th className="p-3">Notes</th>
              <th className="p-3">Langfuse</th>
              <th className="p-3 w-32">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const d = drafts[r.model_name] || {};
              const busy = saving === r.model_name || syncing === r.model_name;
              return (
                <tr key={r.model_name} className="border-t border-gray-800 align-top">
                  <td className="p-3">
                    <div className="font-medium">{r.display_label || r.model_name}</div>
                    <div className="text-xs text-gray-500 font-mono break-all">{r.model_name}</div>
                    {r.provider && (
                      <div className="text-xs text-gray-600">{r.provider}</div>
                    )}
                  </td>
                  <td className="p-3 max-w-xs">
                    {usageBadges(r)}
                    {r.tool_bindings?.length > 0 && (
                      <ul className="mt-2 text-xs text-gray-500 list-disc pl-4">
                        {r.tool_bindings.slice(0, 4).map((b) => (
                          <li key={b.binding_key}>
                            {b.display_name || b.binding_key}
                          </li>
                        ))}
                        {r.tool_bindings.length > 4 && (
                          <li>+{r.tool_bindings.length - 4} more</li>
                        )}
                      </ul>
                    )}
                    {r.fallback_for_models?.length > 0 && (
                      <div className="mt-1 text-xs text-orange-400/80">
                        Fallback for: {r.fallback_for_models.join(', ')}
                      </div>
                    )}
                  </td>
                  <td className="p-3">
                    <input
                      type="number"
                      step="any"
                      min="0"
                      className="w-24 bg-gray-900 border border-gray-600 rounded px-2 py-1"
                      value={d.input_price_per_1m_tokens ?? ''}
                      disabled={busy}
                      onChange={(e) =>
                        setDraft(r.model_name, 'input_price_per_1m_tokens', e.target.value)
                      }
                    />
                  </td>
                  <td className="p-3">
                    <input
                      type="number"
                      step="any"
                      min="0"
                      className="w-24 bg-gray-900 border border-gray-600 rounded px-2 py-1"
                      value={d.output_price_per_1m_tokens ?? ''}
                      disabled={busy}
                      onChange={(e) =>
                        setDraft(r.model_name, 'output_price_per_1m_tokens', e.target.value)
                      }
                    />
                  </td>
                  <td className="p-3">
                    <input
                      type="number"
                      step="any"
                      min="0"
                      className="w-24 bg-gray-900 border border-gray-600 rounded px-2 py-1"
                      placeholder={
                        r.effective_cache_read_price_per_1m_tokens != null
                          ? String(r.effective_cache_read_price_per_1m_tokens)
                          : ''
                      }
                      value={d.cache_read_price_per_1m_tokens ?? ''}
                      disabled={busy}
                      onChange={(e) =>
                        setDraft(r.model_name, 'cache_read_price_per_1m_tokens', e.target.value)
                      }
                    />
                  </td>
                  <td className="p-3">
                    <input
                      type="number"
                      step="any"
                      min="0"
                      className="w-24 bg-gray-900 border border-gray-600 rounded px-2 py-1"
                      placeholder={
                        r.effective_cache_creation_price_per_1m_tokens != null
                          ? String(r.effective_cache_creation_price_per_1m_tokens)
                          : ''
                      }
                      value={d.cache_creation_price_per_1m_tokens ?? ''}
                      disabled={busy}
                      onChange={(e) =>
                        setDraft(r.model_name, 'cache_creation_price_per_1m_tokens', e.target.value)
                      }
                    />
                  </td>
                  <td className="p-3">
                    <textarea
                      rows={2}
                      className="w-full min-w-[140px] bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs"
                      placeholder="Pricing source, effective date…"
                      value={d.admin_notes ?? ''}
                      disabled={busy}
                      onChange={(e) => setDraft(r.model_name, 'admin_notes', e.target.value)}
                    />
                  </td>
                  <td className="p-3">
                    <input
                      type="text"
                      className="w-full min-w-[160px] bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs font-mono"
                      title="Langfuse match regex"
                      value={d.langfuse_match_pattern ?? ''}
                      disabled={busy}
                      onChange={(e) =>
                        setDraft(r.model_name, 'langfuse_match_pattern', e.target.value)
                      }
                    />
                    {r.langfuse_last_synced_at && (
                      <div className="text-xs text-gray-500 mt-1">
                        synced {new Date(r.langfuse_last_synced_at).toLocaleString()}
                      </div>
                    )}
                  </td>
                  <td className="p-3">
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        className="px-2 py-1 rounded text-xs bg-gray-800 border border-gray-600 disabled:opacity-50"
                        disabled={busy}
                        onClick={() => handleSave(r.model_name)}
                      >
                        {saving === r.model_name ? 'Saving…' : 'Save'}
                      </button>
                      <button
                        type="button"
                        className="px-2 py-1 rounded text-xs border border-orange-600/40 text-orange-300 disabled:opacity-50"
                        disabled={busy}
                        onClick={() => handleSyncOne(r.model_name)}
                      >
                        {syncing === r.model_name ? '…' : '→ Langfuse'}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && (
        <p className="mt-4 text-gray-500 text-sm">
          No models in catalog. Click Rebuild catalog or deploy with inventory YAML.
        </p>
      )}
    </div>
  );
}
