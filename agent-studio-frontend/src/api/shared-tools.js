/**
 * API client for Shared External Tools
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';

// ─── Public endpoints (authenticated users) ────────────────────────────────

export async function fetchVisibleSharedTools() {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/shared-tools/list`,
    { method: 'GET', headers: { 'Content-Type': 'application/json' } }
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch shared tools: ${response.statusText}`);
  }
  return response.json();
}

export async function submitToolForApproval(data) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/shared-tools/submit`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }
  );
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || 'Failed to submit tool');
  }
  return response.json();
}

// ─── Admin endpoints ───────────────────────────────────────────────────────

export async function fetchAllSharedTools() {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/admin/shared-tools`,
    { method: 'GET', headers: { 'Content-Type': 'application/json' } }
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch shared tools: ${response.statusText}`);
  }
  return response.json();
}

export async function createSharedTool(data) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/admin/shared-tools`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }
  );
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || 'Failed to create tool');
  }
  return response.json();
}

export async function updateSharedTool(toolId, data) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/admin/shared-tools/${toolId}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }
  );
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || 'Failed to update tool');
  }
  return response.json();
}

export async function deleteSharedTool(toolId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/admin/shared-tools/${toolId}`,
    { method: 'DELETE', headers: { 'Content-Type': 'application/json' } }
  );
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || 'Failed to delete tool');
  }
  return response.json();
}

export async function uploadSharedToolsCsv(file) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/admin/shared-tools/csv-upload`,
    { method: 'POST', body: formData }
  );
  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || 'CSV upload failed');
  }
  return response.json();
}

export async function fetchSharedToolAuditLog(limit = 100, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/admin/shared-tools/audit-log?${params}`,
    { method: 'GET', headers: { 'Content-Type': 'application/json' } }
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch audit log: ${response.statusText}`);
  }
  return response.json();
}
