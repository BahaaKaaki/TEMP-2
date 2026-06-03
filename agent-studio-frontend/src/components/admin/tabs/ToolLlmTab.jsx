import { useEffect, useState } from 'react';
import {
  fetchAdminToolBindings,
  updateAdminToolBinding,
  patchAdminModel,
} from '../../../api/admin';
import { fetchAllModels } from '../../../api/models';

function buildModelOptions(catalog, bindings) {
  const seen = new Set();
  const opts = [];
  const add = (value, label) => {
    if (!value || seen.has(value)) return;
    seen.add(value);
    opts.push({ value, label: label || value });
  };
  if (catalog?.providers) {
    Object.values(catalog.providers).forEach((p) => {
      (p.models || []).forEach((m) => add(m.id || m.value, m.label || m.id));
    });
  }
  bindings.forEach((b) => {
    add(b.primary_model_name, b.primary_model_name);
    if (b.fallback_model_name) add(b.fallback_model_name, b.fallback_model_name);
  });
  return opts.sort((a, b) => a.label.localeCompare(b.label));
}

export default function ToolLlmTab() {
  const [bindings, setBindings] = useState([]);
  const [modelOptions, setModelOptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(null);
  const [error, setError] = useState(null);

  const loadBindings = async () => {
    const tools = await fetchAdminToolBindings();
    setBindings(tools);
    return tools;
  };

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const catalog = await fetchAllModels().catch(() => null);
        const tools = await loadBindings();
        setModelOptions(buildModelOptions(catalog, tools));
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handlePrimaryChange = async (bindingKey, primary_model_name) => {
    try {
      setSaving(`primary:${bindingKey}`);
      setError(null);
      await updateAdminToolBinding(bindingKey, { primary_model_name });
      const tools = await loadBindings();
      setModelOptions((opts) => buildModelOptions(null, tools));
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(null);
    }
  };

  const handleFallbackChange = async (bindingKey, primaryModelName, fallback_model_name) => {
    try {
      setSaving(`fallback:${bindingKey}`);
      setError(null);
      await patchAdminModel(primaryModelName, {
        fallback_model_name: fallback_model_name || null,
      });
      setBindings((prev) =>
        prev.map((b) =>
          b.binding_key === bindingKey
            ? { ...b, fallback_model_name: fallback_model_name || null }
            : b
        )
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return <div className="p-8 text-gray-400">Loading tool LLM configuration…</div>;
  }

  return (
    <div className="p-6 overflow-auto h-full" style={{ color: '#e5e5e5' }}>
      <h2 className="text-xl font-semibold mb-2">Tool LLM</h2>
      <p className="text-sm text-gray-400 mb-6">
        Set which model each tool or service uses (primary) and which model to try if that call fails (fallback).
        Fallback applies to the primary model in the catalog and is used at runtime by the LLM manager.
      </p>
      {error && (
        <div className="mb-4 p-3 rounded bg-red-900/40 text-red-200 text-sm">{error}</div>
      )}
      <div className="overflow-x-auto rounded border border-gray-700">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-left">
            <tr>
              <th className="p-3">Binding</th>
              <th className="p-3">Type</th>
              <th className="p-3">Primary model</th>
              <th className="p-3">Fallback model</th>
              <th className="p-3">Source</th>
            </tr>
          </thead>
          <tbody>
            {bindings.map((b) => {
              const busy = saving === `primary:${b.binding_key}` || saving === `fallback:${b.binding_key}`;
              return (
                <tr key={b.binding_key} className="border-t border-gray-800">
                  <td className="p-3 font-medium">{b.display_name || b.binding_key}</td>
                  <td className="p-3 text-gray-400">{b.binding_type}</td>
                  <td className="p-3">
                    <select
                      className="bg-gray-900 border border-gray-600 rounded px-2 py-1 max-w-xs w-full"
                      value={b.primary_model_name}
                      disabled={busy}
                      onChange={(e) => handlePrimaryChange(b.binding_key, e.target.value)}
                    >
                      {modelOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="p-3">
                    <select
                      className="bg-gray-900 border border-orange-600/50 rounded px-2 py-1 max-w-xs w-full"
                      value={b.fallback_model_name || ''}
                      disabled={busy || !b.primary_model_name}
                      onChange={(e) =>
                        handleFallbackChange(
                          b.binding_key,
                          b.primary_model_name,
                          e.target.value
                        )
                      }
                    >
                      <option value="">— none —</option>
                      {modelOptions
                        .filter((o) => o.value !== b.primary_model_name)
                        .map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                    </select>
                  </td>
                  <td className="p-3 text-gray-500 text-xs">{b.source_file}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
