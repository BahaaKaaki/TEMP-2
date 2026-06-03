/**
 * Admin portal API — LLM catalog, tool bindings, workflow model inventory.
 */
import { API_BASE_URL, authenticatedFetch } from './client.js';

async function adminFetch(path, options = {}) {
  const response = await authenticatedFetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Admin API error: ${response.status}`);
  }
  return response.json();
}

export function fetchAdminToolBindings() {
  return adminFetch('/api/admin/llm/tools');
}

export function updateAdminToolBinding(bindingKey, body) {
  return adminFetch(`/api/admin/llm/tools/${encodeURIComponent(bindingKey)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function fetchAdminWorkflowModels() {
  return adminFetch('/api/admin/llm/workflows');
}

export function patchAdminModel(modelName, body) {
  return adminFetch(`/api/admin/llm/models/${encodeURIComponent(modelName)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function triggerWorkflowModelScan() {
  return adminFetch('/api/admin/llm/workflows/scan', { method: 'POST' });
}

export function previewWorkflowModelReplace(body) {
  return adminFetch('/api/admin/llm/workflows/replace-model/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function executeWorkflowModelReplace(body) {
  return adminFetch('/api/admin/llm/workflows/replace-model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function fetchAdminModels() {
  return adminFetch('/api/admin/llm/models');
}

export function rebuildAdminModelCatalog() {
  return adminFetch('/api/admin/llm/models/rebuild', { method: 'POST' });
}

export function syncAllModelsToLangfuse() {
  return adminFetch('/api/admin/llm/models/sync-langfuse', { method: 'POST' });
}

export function syncModelToLangfuse(modelName) {
  return adminFetch(
    `/api/admin/llm/models/${encodeURIComponent(modelName)}/sync-langfuse`,
    { method: 'POST' }
  );
}

export function fetchAdminSharingOverview() {
  return adminFetch('/api/admin/sharing/overview');
}

export function fetchAdminUsers() {
  return adminFetch('/api/admin/users/admins');
}

export function searchAdminUsers(q, limit = 20) {
  if (!q || q.length < 2) return Promise.resolve([]);
  const params = new URLSearchParams({ q, limit: String(limit) });
  return adminFetch(`/api/admin/users/search?${params.toString()}`);
}

export function grantAdminUser({ email, userId } = {}) {
  const body = userId ? { userId } : { email };
  return adminFetch('/api/admin/users/admins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function revokeAdminUser(userId) {
  return adminFetch(`/api/admin/users/admins/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
}

// ---------------------------------------------------------------------------
// Analytics dashboard
// ---------------------------------------------------------------------------

function buildAnalyticsParams(params = {}) {
  const sp = new URLSearchParams();
  if (params.from_date) sp.set('from_date', params.from_date);
  if (params.to_date) sp.set('to_date', params.to_date);
  if (params.workflow_id) sp.set('workflow_id', params.workflow_id);
  if (params.user_id) sp.set('user_id', params.user_id);
  if (params.status) sp.set('status', params.status);
  if (params.mode) sp.set('mode', params.mode);
  if (params.model_name) sp.set('model_name', params.model_name);
  if (params.service_name) sp.set('service_name', params.service_name);
  if (params.group_by) sp.set('group_by', params.group_by);
  if (params.limit) sp.set('limit', params.limit);
  if (params.dataset) sp.set('dataset', params.dataset);
  if (params.days_back) sp.set('days_back', params.days_back);
  if (params.refresh_type) sp.set('refresh_type', params.refresh_type);
  if (params.force) sp.set('force', 'true');
  if (params.months) sp.set('months', String(params.months));
  const qs = sp.toString();
  return qs ? `?${qs}` : '';
}

export function refreshAnalytics(params = {}) {
  return adminFetch(`/api/admin/analytics/refresh${buildAnalyticsParams(params)}`, {
    method: 'POST',
  });
}

export function cancelStuckAnalyticsRefresh({ force = true } = {}) {
  const qs = force ? '?force=true' : '';
  return adminFetch(`/api/admin/analytics/refresh/cancel-stuck${qs}`, {
    method: 'POST',
  });
}

export function fetchAnalyticsLastRefresh() {
  return adminFetch('/api/admin/analytics/last-refresh');
}

export function fetchAnalyticsUserActivity(params = {}) {
  return adminFetch(`/api/admin/analytics/user-activity${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsSummary(params = {}) {
  return adminFetch(`/api/admin/analytics/summary${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsTimeseries(params = {}) {
  return adminFetch(`/api/admin/analytics/timeseries${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsModels(params = {}) {
  return adminFetch(`/api/admin/analytics/models${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsModelTimeseries(params = {}) {
  return adminFetch(`/api/admin/analytics/models/timeseries${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsServices(params = {}) {
  return adminFetch(`/api/admin/analytics/services${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsServiceTimeseries(params = {}) {
  return adminFetch(`/api/admin/analytics/services/timeseries${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsServiceByUser(params = {}) {
  return adminFetch(`/api/admin/analytics/services/by-user${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsTopWorkflows(params = {}) {
  return adminFetch(`/api/admin/analytics/top-workflows${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsTopUsers(params = {}) {
  return adminFetch(`/api/admin/analytics/top-users${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsStatusBreakdown(params = {}) {
  return adminFetch(`/api/admin/analytics/status-breakdown${buildAnalyticsParams(params)}`);
}

export function fetchAnalyticsFilters() {
  return adminFetch('/api/admin/analytics/filters');
}

export function exportAnalyticsData(params = {}) {
  return adminFetch(`/api/admin/analytics/export${buildAnalyticsParams(params)}`);
}
