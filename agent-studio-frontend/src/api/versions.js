/**
 * API client for workflow version history endpoints.
 */

import { authenticatedFetch, API_BASE_URL } from './client';
import { safeLog } from '../utils/safeLogger';

const BASE = `${API_BASE_URL}/api/workflows`;

async function jsonOrThrow(response, action) {
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `${action}: ${response.statusText}`);
  }
  return response.json();
}

export async function listVersions(workflowId, { page = 1, pageSize = 30 } = {}) {
  const qs = new URLSearchParams({ page, page_size: pageSize });
  const res = await authenticatedFetch(
    `${BASE}/${workflowId}/versions?${qs}`,
    { method: 'GET', headers: { 'Content-Type': 'application/json' } },
  );
  return jsonOrThrow(res, 'Failed to list versions');
}

export async function getVersion(workflowId, versionId) {
  const res = await authenticatedFetch(
    `${BASE}/${workflowId}/versions/${versionId}`,
    { method: 'GET', headers: { 'Content-Type': 'application/json' } },
  );
  return jsonOrThrow(res, 'Failed to get version');
}

export async function restoreVersion(workflowId, versionId) {
  safeLog('Restoring version:', versionId);
  const res = await authenticatedFetch(
    `${BASE}/${workflowId}/versions/${versionId}/restore`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' } },
  );
  return jsonOrThrow(res, 'Failed to restore version');
}

export async function updateVersionName(workflowId, versionId, description) {
  const res = await authenticatedFetch(
    `${BASE}/${workflowId}/versions/${versionId}/name`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description }),
    },
  );
  return jsonOrThrow(res, 'Failed to update version name');
}

export async function checkForUpdates(workflowId) {
  const res = await authenticatedFetch(
    `${BASE}/${workflowId}/check-updates`,
    { method: 'GET', headers: { 'Content-Type': 'application/json' } },
  );
  return jsonOrThrow(res, 'Failed to check updates');
}

export async function pullUpdate(workflowId) {
  safeLog('Pulling marketplace update for:', workflowId);
  const res = await authenticatedFetch(
    `${BASE}/${workflowId}/pull-update`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' } },
  );
  return jsonOrThrow(res, 'Failed to pull update');
}
