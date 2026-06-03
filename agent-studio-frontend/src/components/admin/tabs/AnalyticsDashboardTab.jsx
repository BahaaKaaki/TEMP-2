import { useCallback, useEffect, useState } from 'react';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import {
  fetchAnalyticsSummary,
  fetchAnalyticsTimeseries,
  fetchAnalyticsModels,
  fetchAnalyticsModelTimeseries,
  fetchAnalyticsTopWorkflows,
  fetchAnalyticsTopUsers,
  fetchAnalyticsStatusBreakdown,
  fetchAnalyticsFilters,
  fetchAnalyticsLastRefresh,
  fetchAnalyticsServices,
  fetchAnalyticsServiceTimeseries,
  refreshAnalytics,
  cancelStuckAnalyticsRefresh,
  fetchAnalyticsUserActivity,
  exportAnalyticsData,
} from '../../../api/admin';

const COLORS = ['#fb923c', '#38bdf8', '#a78bfa', '#34d399', '#f87171', '#fbbf24', '#818cf8', '#f472b6'];

const METRICS = [
  { key: 'execution_count', label: 'Executions', format: 'number' },
  { key: 'avg_duration_ms', label: 'Avg Duration (ms)', format: 'duration' },
  { key: 'total_tokens', label: 'Total Tokens', format: 'number' },
  { key: 'total_cost_usd', label: 'Total Cost ($)', format: 'currency' },
  { key: 'llm_call_count', label: 'LLM Calls', format: 'number' },
];

const DIMENSIONS = [
  { key: 'date', label: 'Date' },
  { key: 'workflow', label: 'Workflow' },
  { key: 'user', label: 'User' },
  { key: 'status', label: 'Status' },
  { key: 'mode', label: 'Mode' },
];

function formatNumber(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatCurrency(n) {
  if (n == null) return '—';
  return `$${n.toFixed(4)}`;
}

function formatDuration(ms) {
  if (ms == null) return '—';
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function KPICard({ label, value, format }) {
  let display = value;
  if (format === 'currency') display = formatCurrency(value);
  else if (format === 'duration') display = formatDuration(value);
  else display = formatNumber(value);

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 flex flex-col">
      <span className="text-xs text-gray-400 uppercase tracking-wide">{label}</span>
      <span className="text-2xl font-semibold text-white mt-1">{display}</span>
    </div>
  );
}

function FilterBar({ filters, activeFilters, onFilterChange, onReset }) {
  return (
    <div className="flex flex-wrap gap-3 items-end">
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">From</label>
        <input
          type="date"
          value={activeFilters.from_date || ''}
          onChange={e => onFilterChange('from_date', e.target.value || null)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">To</label>
        <input
          type="date"
          value={activeFilters.to_date || ''}
          onChange={e => onFilterChange('to_date', e.target.value || null)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">Workflow</label>
        <select
          value={activeFilters.workflow_id || ''}
          onChange={e => onFilterChange('workflow_id', e.target.value || null)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white max-w-[200px]"
        >
          <option value="">All workflows</option>
          {(filters.workflows || []).map(w => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">User</label>
        <select
          value={activeFilters.user_id || ''}
          onChange={e => onFilterChange('user_id', e.target.value || null)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white max-w-[200px]"
        >
          <option value="">All users</option>
          {(filters.users || []).map(u => (
            <option key={u.id} value={u.id}>{u.email || u.id.slice(0, 8)}</option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">Status</label>
        <select
          value={activeFilters.status || ''}
          onChange={e => onFilterChange('status', e.target.value || null)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
        >
          <option value="">All</option>
          {(filters.statuses || []).map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400">Mode</label>
        <select
          value={activeFilters.mode || ''}
          onChange={e => onFilterChange('mode', e.target.value || null)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
        >
          <option value="">All</option>
          {(filters.modes || []).map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      <button
        onClick={onReset}
        className="px-3 py-1 text-sm border border-gray-600 rounded text-gray-300 hover:bg-gray-800"
      >
        Reset
      </button>
    </div>
  );
}

function DimensionMetricPicker({ dimension, metric, onDimensionChange, onMetricChange }) {
  return (
    <div className="flex gap-4 items-center">
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">Group by:</span>
        <select
          value={dimension}
          onChange={e => onDimensionChange(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
        >
          {DIMENSIONS.map(d => (
            <option key={d.key} value={d.key}>{d.label}</option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">Metric:</span>
        <select
          value={metric}
          onChange={e => onMetricChange(e.target.value)}
          className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
        >
          {METRICS.map(m => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

function csvFromData(data, filename) {
  if (!data || !data.length) return;
  const headers = Object.keys(data[0]);
  const csvContent = [
    headers.join(','),
    ...data.map(row => headers.map(h => JSON.stringify(row[h] ?? '')).join(',')),
  ].join('\n');

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

export default function AnalyticsDashboardTab() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const [lastRefresh, setLastRefresh] = useState(null);
  const [summary, setSummary] = useState(null);
  const [timeseries, setTimeseries] = useState([]);
  const [models, setModels] = useState([]);
  const [modelTimeseries, setModelTimeseries] = useState([]);
  const [services, setServices] = useState([]);
  const [serviceTimeseries, setServiceTimeseries] = useState([]);
  const [topWorkflows, setTopWorkflows] = useState([]);
  const [topUsers, setTopUsers] = useState([]);
  const [statusBreakdown, setStatusBreakdown] = useState([]);
  const [filters, setFilters] = useState({ workflows: [], users: [], statuses: [], modes: [], models: [], services: [] });

  const [activeFilters, setActiveFilters] = useState({});
  const [dimension, setDimension] = useState('date');
  const [metric, setMetric] = useState('execution_count');
  const [userActivity, setUserActivity] = useState(null);
  const [userActivityLoading, setUserActivityLoading] = useState(false);
  const [activeView, setActiveView] = useState('overview');

  const loadDashboard = useCallback(async (filterParams = {}) => {
    setLoading(true);
    setError(null);
    try {
      const params = { ...filterParams, group_by: dimension };
      const [sumRes, tsRes, modRes, modTsRes, svcRes, svcTsRes, wfRes, uRes, stRes, fRes, lrRes] = await Promise.all([
        fetchAnalyticsSummary(params),
        fetchAnalyticsTimeseries(params),
        fetchAnalyticsModels(params),
        fetchAnalyticsModelTimeseries(params),
        fetchAnalyticsServices(params),
        fetchAnalyticsServiceTimeseries(params),
        fetchAnalyticsTopWorkflows(params),
        fetchAnalyticsTopUsers(params),
        fetchAnalyticsStatusBreakdown(params),
        fetchAnalyticsFilters(),
        fetchAnalyticsLastRefresh(),
      ]);
      setSummary(sumRes);
      setTimeseries(tsRes);
      setModels(modRes);
      setModelTimeseries(modTsRes);
      setServices(svcRes);
      setServiceTimeseries(svcTsRes);
      setTopWorkflows(wfRes);
      setTopUsers(uRes);
      setStatusBreakdown(stRes);
      setFilters(fRes);
      setLastRefresh(lrRes);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [dimension]);

  useEffect(() => {
    loadDashboard(activeFilters);
  }, [loadDashboard, activeFilters]);

  const loadUserActivity = useCallback(async () => {
    setUserActivityLoading(true);
    try {
      const data = await fetchAnalyticsUserActivity({ months: 12 });
      setUserActivity(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setUserActivityLoading(false);
    }
  }, []);

  const pollRefreshUntilDone = useCallback(async () => {
    const maxAttempts = 120;
    for (let i = 0; i < maxAttempts; i += 1) {
      await new Promise(r => setTimeout(r, 3000));
      const lr = await fetchAnalyticsLastRefresh();
      setLastRefresh(lr);
      if (lr?.status === 'completed') {
        await loadDashboard(activeFilters);
        return;
      }
      if (lr?.status === 'failed') {
        throw new Error(lr.error_message || 'Analytics refresh failed');
      }
      if (lr?.status !== 'running' && lr?.status !== 'queued') {
        return;
      }
    }
    throw new Error('Refresh is taking longer than expected. Check back shortly or try again.');
  }, [loadDashboard, activeFilters]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      let started;
      try {
        started = await refreshAnalytics({ days_back: 7, refresh_type: 'incremental' });
      } catch (err) {
        const stuck = /already in progress/i.test(err.message || '');
        if (!stuck) throw err;
        await cancelStuckAnalyticsRefresh({ force: true });
        started = await refreshAnalytics({
          days_back: 7,
          refresh_type: 'incremental',
          force: true,
        });
      }
      if (started?.status === 'queued' || started?.status === 'accepted') {
        setLastRefresh({ status: 'queued', started_at: new Date().toISOString() });
        await pollRefreshUntilDone();
      } else {
        await loadDashboard(activeFilters);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  };

  // Reload when a scheduled refresh completes while this tab is open.
  useEffect(() => {
    const active = lastRefresh?.status === 'running' || lastRefresh?.status === 'queued';
    if (!active || refreshing) return undefined;
    const id = setInterval(async () => {
      try {
        const lr = await fetchAnalyticsLastRefresh();
        setLastRefresh(lr);
        if (lr?.status === 'completed') {
          await loadDashboard(activeFilters);
        }
      } catch {
        /* ignore poll errors */
      }
    }, 15000);
    return () => clearInterval(id);
  }, [lastRefresh?.status, refreshing, loadDashboard, activeFilters]);

  const handleFilterChange = (key, value) => {
    setActiveFilters(prev => {
      const next = { ...prev };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
  };

  const handleExport = async (dataset) => {
    try {
      const result = await exportAnalyticsData({ ...activeFilters, dataset });
      csvFromData(result.data, `analytics_${dataset}_${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (err) {
      setError(`Export failed: ${err.message}`);
    }
  };

  if (loading && !summary) {
    return <div className="p-6 text-gray-400">Loading analytics...</div>;
  }

  return (
    <div className="p-6 space-y-6 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 80px)' }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Analytics Dashboard</h2>
          {(lastRefresh?.status === 'running' || lastRefresh?.status === 'queued') && (
            <p className="text-xs text-amber-400 mt-1">
              Refresh in progress… (dashboard reloads when complete)
            </p>
          )}
          {lastRefresh?.status === 'completed' && lastRefresh?.completed_at && (
            <p className="text-xs text-gray-500 mt-1">
              Last refreshed: {new Date(lastRefresh.completed_at).toLocaleString()}
              {' '}({lastRefresh.langfuse_traces} Langfuse traces, {lastRefresh.rows_upserted} rows)
            </p>
          )}
          {lastRefresh?.status === 'failed' && (
            <p className="text-xs text-red-400 mt-1">
              Last refresh failed{lastRefresh.error_message ? `: ${lastRefresh.error_message}` : ''}
            </p>
          )}
          {lastRefresh?.status === 'never_refreshed' && (
            <p className="text-xs text-amber-400 mt-1">
              No snapshot yet. Click Refresh to build data, or wait for the nightly job.
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="px-4 py-2 bg-orange-600 hover:bg-orange-700 disabled:opacity-50 text-white rounded text-sm font-medium flex items-center gap-2"
          >
            {refreshing ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" aria-hidden>
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Refreshing…
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Refresh
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 rounded p-3 text-red-200 text-sm">{error}</div>
      )}

      {/* View tabs */}
      <div className="flex gap-1 border-b border-gray-700">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'consumption', label: 'Token Consumption' },
          { id: 'services', label: 'Services' },
          { id: 'leaderboards', label: 'Leaderboards' },
          { id: 'user-activity', label: 'User Activity' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => {
              setActiveView(tab.id);
              if (tab.id === 'user-activity') loadUserActivity();
            }}
            className={`px-4 py-2 text-sm rounded-t ${
              activeView === tab.id
                ? 'bg-gray-800 text-orange-400 border border-gray-700 border-b-0'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Filters (not used on User Activity — live platform-wide counts) */}
      {activeView !== 'user-activity' && (
        <FilterBar
          filters={filters}
          activeFilters={activeFilters}
          onFilterChange={handleFilterChange}
          onReset={() => setActiveFilters({})}
        />
      )}

      {/* OVERVIEW VIEW */}
      {activeView === 'overview' && (
        <div className="space-y-6">
          {/* KPI Cards */}
          {summary && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
                <KPICard label="Total Executions" value={summary.total_executions} format="number" />
                <KPICard label="Avg Duration" value={summary.avg_duration_ms} format="duration" />
                <KPICard label="Total Tokens" value={summary.total_tokens} format="number" />
                <KPICard
                  label={summary.cost_scope === 'workflow' || activeFilters.workflow_id
                    ? 'Workflow Cost'
                    : 'Total Cost'}
                  value={summary.total_cost_usd}
                  format="currency"
                />
                <KPICard label="LLM Calls" value={summary.total_llm_calls} format="number" />
              </div>
              <p className="text-xs text-gray-500">
                {activeFilters.workflow_id || summary.cost_scope === 'workflow' ? (
                  <>
                    Workflow filter active — cost above is workflow runs only.
                    {' '}Platform total {formatCurrency(summary.platform_cost_usd ?? 0)}
                    {' '}(see Token Consumption for all models/tools).
                  </>
                ) : (
                  <>
                    Cost and LLM calls match Token Consumption (all Langfuse usage).
                    {' '}Workflows {formatCurrency(summary.workflow_cost_usd ?? 0)}
                    {' · '}Services/tools {formatCurrency(summary.service_cost_usd ?? 0)}
                  </>
                )}
              </p>
            </>
          )}

          {/* Dimension/Metric picker + Chart */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <div className="flex justify-between items-center mb-4">
              <DimensionMetricPicker
                dimension={dimension}
                metric={metric}
                onDimensionChange={setDimension}
                onMetricChange={setMetric}
              />
              <button
                onClick={() => handleExport('executions')}
                className="text-xs text-gray-400 hover:text-white border border-gray-600 rounded px-2 py-1"
              >
                Export CSV
              </button>
            </div>
            <ResponsiveContainer width="100%" height={300}>
              {dimension === 'date' ? (
                <AreaChart data={timeseries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="dimension" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} />
                  <Area type="monotone" dataKey={metric} stroke="#fb923c" fill="#fb923c" fillOpacity={0.2} />
                </AreaChart>
              ) : (
                <BarChart data={timeseries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="dimension" tick={{ fill: '#9ca3af', fontSize: 11 }} angle={-20} textAnchor="end" height={60} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} />
                  <Bar dataKey={metric} fill="#fb923c" radius={[4, 4, 0, 0]} />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>

          {/* Status breakdown pie */}
          {statusBreakdown.length > 0 && (
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Status Breakdown</h3>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={statusBreakdown}
                    dataKey="count"
                    nameKey="status"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    label={({ status, count }) => `${status} (${count})`}
                    labelLine={false}
                  >
                    {statusBreakdown.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 12, color: '#9ca3af' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* CONSUMPTION VIEW */}
      {activeView === 'consumption' && (
        <div className="space-y-6">
          {/* Model consumption table */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-sm font-medium text-gray-300">Model Consumption</h3>
              <button
                onClick={() => handleExport('models')}
                className="text-xs text-gray-400 hover:text-white border border-gray-600 rounded px-2 py-1"
              >
                Export CSV
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-700">
                    <th className="py-2 px-2">Model</th>
                    <th className="py-2 px-2">Provider</th>
                    <th className="py-2 px-2 text-right">Generations</th>
                    <th className="py-2 px-2 text-right">Input Tokens</th>
                    <th className="py-2 px-2 text-right">Output Tokens</th>
                    <th className="py-2 px-2 text-right">Total Tokens</th>
                    <th className="py-2 px-2 text-right">Cache Read</th>
                    <th className="py-2 px-2 text-right">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m, i) => (
                    <tr key={i} className="border-b border-gray-800 text-gray-200">
                      <td className="py-2 px-2 font-mono text-xs">{m.model_name}</td>
                      <td className="py-2 px-2">{m.provider}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(m.generation_count)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(m.total_input_tokens)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(m.total_output_tokens)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(m.total_tokens)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(m.cache_read_tokens)}</td>
                      <td className="py-2 px-2 text-right font-mono">{formatCurrency(m.total_cost_usd)}</td>
                    </tr>
                  ))}
                  {models.length === 0 && (
                    <tr><td colSpan={8} className="py-4 text-center text-gray-500">No model data. Click Refresh to pull from Langfuse.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Model consumption time-series */}
          {modelTimeseries.length > 0 && (
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Daily Token Consumption</h3>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={modelTimeseries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" dataKey="total_input_tokens" name="Input" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.15} />
                  <Area type="monotone" dataKey="total_output_tokens" name="Output" stroke="#a78bfa" fill="#a78bfa" fillOpacity={0.15} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Cost over time */}
          {modelTimeseries.length > 0 && (
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Daily Cost ($)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={modelTimeseries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} formatter={(v) => `$${Number(v).toFixed(4)}`} />
                  <Bar dataKey="total_cost_usd" name="Cost" fill="#34d399" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Token usage by user */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-3">Usage by User</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-700">
                    <th className="py-2 px-2">User</th>
                    <th className="py-2 px-2 text-right">Executions</th>
                    <th className="py-2 px-2 text-right">Total Tokens</th>
                    <th className="py-2 px-2 text-right">LLM Calls</th>
                    <th className="py-2 px-2 text-right">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {topUsers.map((u, i) => (
                    <tr key={i} className="border-b border-gray-800 text-gray-200">
                      <td className="py-2 px-2">{u.user_email || u.user_id?.slice(0, 8)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(u.execution_count)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(u.total_tokens)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(u.llm_call_count)}</td>
                      <td className="py-2 px-2 text-right font-mono">{formatCurrency(u.total_cost_usd)}</td>
                    </tr>
                  ))}
                  {topUsers.length === 0 && (
                    <tr><td colSpan={5} className="py-4 text-center text-gray-500">No data yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Token usage by workflow */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-300 mb-3">Usage by Workflow</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-700">
                    <th className="py-2 px-2">Workflow</th>
                    <th className="py-2 px-2 text-right">Executions</th>
                    <th className="py-2 px-2 text-right">Total Tokens</th>
                    <th className="py-2 px-2 text-right">LLM Calls</th>
                    <th className="py-2 px-2 text-right">Avg Duration</th>
                    <th className="py-2 px-2 text-right">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {topWorkflows.map((w, i) => (
                    <tr key={i} className="border-b border-gray-800 text-gray-200">
                      <td className="py-2 px-2">{w.workflow_name}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(w.execution_count)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(w.total_tokens)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(w.llm_call_count)}</td>
                      <td className="py-2 px-2 text-right">{formatDuration(w.avg_duration_ms)}</td>
                      <td className="py-2 px-2 text-right font-mono">{formatCurrency(w.total_cost_usd)}</td>
                    </tr>
                  ))}
                  {topWorkflows.length === 0 && (
                    <tr><td colSpan={6} className="py-4 text-center text-gray-500">No data yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* SERVICES VIEW (non-workflow: embeddings, code executor, OCR, etc.) */}
      {activeView === 'services' && (
        <div className="space-y-6">
          {/* Service consumption summary */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-sm font-medium text-gray-300">Service Consumption (Non-Workflow)</h3>
              <div className="flex gap-2 items-center">
                <select
                  value={activeFilters.service_name || ''}
                  onChange={e => handleFilterChange('service_name', e.target.value || null)}
                  className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
                >
                  <option value="">All services</option>
                  {(filters.services || []).map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <button
                  onClick={() => csvFromData(services, `analytics_services_${new Date().toISOString().slice(0, 10)}.csv`)}
                  className="text-xs text-gray-400 hover:text-white border border-gray-600 rounded px-2 py-1"
                >
                  Export CSV
                </button>
              </div>
            </div>
            <p className="text-xs text-gray-500 mb-3">
              Token usage from operations outside workflow executions: KB embeddings, code executor, image/OCR processing, web search, etc.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-700">
                    <th className="py-2 px-2">Service</th>
                    <th className="py-2 px-2">Model</th>
                    <th className="py-2 px-2 text-right">Calls</th>
                    <th className="py-2 px-2 text-right">Input Tokens</th>
                    <th className="py-2 px-2 text-right">Output Tokens</th>
                    <th className="py-2 px-2 text-right">Total Tokens</th>
                    <th className="py-2 px-2 text-right">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {services.map((s, i) => (
                    <tr key={i} className="border-b border-gray-800 text-gray-200">
                      <td className="py-2 px-2">
                        <span className="inline-block px-2 py-0.5 rounded text-xs bg-teal-900/50 text-teal-200">
                          {s.service_name}
                        </span>
                      </td>
                      <td className="py-2 px-2 font-mono text-xs">{s.model_name}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(s.call_count)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(s.total_input_tokens)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(s.total_output_tokens)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(s.total_tokens)}</td>
                      <td className="py-2 px-2 text-right font-mono">{formatCurrency(s.total_cost_usd)}</td>
                    </tr>
                  ))}
                  {services.length === 0 && (
                    <tr><td colSpan={7} className="py-4 text-center text-gray-500">No service usage data. Click Refresh to pull from Langfuse.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Service usage time-series */}
          {serviceTimeseries.length > 0 && (
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Daily Service Usage</h3>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={serviceTimeseries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="call_count" name="Calls" fill="#2dd4bf" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Service token breakdown chart */}
          {serviceTimeseries.length > 0 && (
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Daily Service Tokens</h3>
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={serviceTimeseries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" dataKey="total_input_tokens" name="Input" stroke="#2dd4bf" fill="#2dd4bf" fillOpacity={0.15} />
                  <Area type="monotone" dataKey="total_output_tokens" name="Output" stroke="#fb923c" fill="#fb923c" fillOpacity={0.15} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Service breakdown pie chart */}
          {services.length > 0 && (
            <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Cost by Service</h3>
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={services.reduce((acc, s) => {
                      const existing = acc.find(a => a.service_name === s.service_name);
                      if (existing) { existing.total_cost_usd += s.total_cost_usd; }
                      else { acc.push({ service_name: s.service_name, total_cost_usd: s.total_cost_usd }); }
                      return acc;
                    }, [])}
                    dataKey="total_cost_usd"
                    nameKey="service_name"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    label={({ service_name, total_cost_usd }) => `${service_name} ($${total_cost_usd.toFixed(3)})`}
                    labelLine={false}
                  >
                    {services.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} formatter={(v) => `$${Number(v).toFixed(4)}`} />
                  <Legend wrapperStyle={{ fontSize: 12, color: '#9ca3af' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* LEADERBOARDS VIEW */}
      {activeView === 'leaderboards' && (
        <div className="space-y-6">
          {/* Top workflows */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-sm font-medium text-gray-300">Top Workflows</h3>
              <button
                onClick={() => handleExport('workflows')}
                className="text-xs text-gray-400 hover:text-white border border-gray-600 rounded px-2 py-1"
              >
                Export CSV
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-700">
                    <th className="py-2 px-2">Workflow</th>
                    <th className="py-2 px-2 text-right">Executions</th>
                    <th className="py-2 px-2 text-right">Avg Duration</th>
                    <th className="py-2 px-2 text-right">Tokens</th>
                    <th className="py-2 px-2 text-right">Cost</th>
                    <th className="py-2 px-2 text-right">LLM Calls</th>
                  </tr>
                </thead>
                <tbody>
                  {topWorkflows.map((w, i) => (
                    <tr key={i} className="border-b border-gray-800 text-gray-200">
                      <td className="py-2 px-2">{w.workflow_name}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(w.execution_count)}</td>
                      <td className="py-2 px-2 text-right">{formatDuration(w.avg_duration_ms)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(w.total_tokens)}</td>
                      <td className="py-2 px-2 text-right font-mono">{formatCurrency(w.total_cost_usd)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(w.llm_call_count)}</td>
                    </tr>
                  ))}
                  {topWorkflows.length === 0 && (
                    <tr><td colSpan={6} className="py-4 text-center text-gray-500">No data yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Top users */}
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-sm font-medium text-gray-300">Top Users</h3>
              <button
                onClick={() => handleExport('users')}
                className="text-xs text-gray-400 hover:text-white border border-gray-600 rounded px-2 py-1"
              >
                Export CSV
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-700">
                    <th className="py-2 px-2">User</th>
                    <th className="py-2 px-2 text-right">Executions</th>
                    <th className="py-2 px-2 text-right">Tokens</th>
                    <th className="py-2 px-2 text-right">Cost</th>
                    <th className="py-2 px-2 text-right">LLM Calls</th>
                  </tr>
                </thead>
                <tbody>
                  {topUsers.map((u, i) => (
                    <tr key={i} className="border-b border-gray-800 text-gray-200">
                      <td className="py-2 px-2">{u.user_email || u.user_id?.slice(0, 8)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(u.execution_count)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(u.total_tokens)}</td>
                      <td className="py-2 px-2 text-right font-mono">{formatCurrency(u.total_cost_usd)}</td>
                      <td className="py-2 px-2 text-right">{formatNumber(u.llm_call_count)}</td>
                    </tr>
                  ))}
                  {topUsers.length === 0 && (
                    <tr><td colSpan={5} className="py-4 text-center text-gray-500">No data yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* USER ACTIVITY VIEW */}
      {activeView === 'user-activity' && (
        <div className="space-y-6">
          {userActivityLoading && !userActivity && (
            <p className="text-gray-400 text-sm">Loading user activity…</p>
          )}
          {userActivity && (
            <>
              <p className="text-xs text-gray-500">
                Active user = at least one workflow run. Counts use UTC
                {userActivity.timezone ? ` (${userActivity.timezone})` : ''}.
                Admins: roleSlug contains &quot;admin&quot; (e.g. global:Admin).
              </p>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <KPICard label="Active (all time)" value={userActivity.active_all_time} />
                <KPICard label="Active today" value={userActivity.active_today} />
                <KPICard label="Active this week" value={userActivity.active_this_week} />
                <KPICard label="Active this month" value={userActivity.active_this_month} />
              </div>

              {userActivity.workflows_created && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <KPICard
                    label="Workflows by users"
                    value={userActivity.workflows_created.workflows_by_users}
                  />
                  <KPICard
                    label="Workflows by admins"
                    value={userActivity.workflows_created.workflows_by_admins}
                  />
                  <KPICard
                    label="Workflows total"
                    value={userActivity.workflows_created.workflows_total}
                  />
                </div>
              )}

              <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
                <h3 className="text-sm font-medium text-gray-300 mb-1">Monthly active users</h3>
                <p className="text-xs text-gray-500 mb-4">
                  Red bars = month-over-month drop in active users. Delta vs previous month in table below.
                </p>
                {(userActivity.monthly || []).length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height={320}>
                      <BarChart data={userActivity.monthly}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                        <XAxis dataKey="month_label" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                        <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} allowDecimals={false} />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
                          formatter={(value, name, props) => {
                            const row = props.payload;
                            if (name === 'active_users') {
                              const delta = row.delta != null ? ` (Δ ${row.delta >= 0 ? '+' : ''}${row.delta})` : '';
                              return [`${value}${delta}`, 'Active users'];
                            }
                            return [value, name];
                          }}
                        />
                        <Bar dataKey="active_users" name="Active users" radius={[4, 4, 0, 0]}>
                          {(userActivity.monthly || []).map((row) => (
                            <Cell
                              key={row.month}
                              fill={row.is_drop ? '#f87171' : '#38bdf8'}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>

                    <div className="overflow-x-auto mt-4">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-gray-400 border-b border-gray-700">
                            <th className="py-2 px-2">Month</th>
                            <th className="py-2 px-2 text-right">Active users</th>
                            <th className="py-2 px-2 text-right">Δ vs prior month</th>
                            <th className="py-2 px-2 text-right">% change</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...(userActivity.monthly || [])].reverse().map((row) => (
                            <tr
                              key={row.month}
                              className={`border-b border-gray-800 ${
                                row.is_drop ? 'bg-red-950/30 text-red-200' : 'text-gray-200'
                              }`}
                            >
                              <td className="py-2 px-2">{row.month_label}</td>
                              <td className="py-2 px-2 text-right">{formatNumber(row.active_users)}</td>
                              <td className="py-2 px-2 text-right font-mono">
                                {row.delta == null
                                  ? '—'
                                  : `${row.delta >= 0 ? '+' : ''}${row.delta}`}
                              </td>
                              <td className="py-2 px-2 text-right font-mono">
                                {row.pct_change == null
                                  ? '—'
                                  : `${row.pct_change >= 0 ? '+' : ''}${row.pct_change}%`}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <p className="text-gray-500 text-sm py-8 text-center">No execution history yet.</p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
