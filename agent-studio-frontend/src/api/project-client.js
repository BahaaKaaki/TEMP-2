/**
 * API client for project management (session grouping).
 */

import { authenticatedFetch, API_BASE_URL } from './client.js';

/**
 * Create a new project.
 * @param {{ name: string, description?: string }} data
 * @returns {Promise<Object>} ProjectResponse
 */
export async function createProject({ name, description }) {
  const res = await authenticatedFetch(`${API_BASE_URL}/api/projects/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to create project');
  }
  return res.json();
}

/**
 * List all projects for the authenticated user.
 * @returns {Promise<{ items: Object[], total: number }>}
 */
export async function listProjects() {
  const res = await authenticatedFetch(`${API_BASE_URL}/api/projects/`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to list projects');
  }
  return res.json();
}

/**
 * Update a project.
 * @param {string} projectId
 * @param {{ name?: string, description?: string }} data
 * @returns {Promise<Object>} ProjectResponse
 */
export async function updateProject(projectId, { name, description }) {
  const res = await authenticatedFetch(`${API_BASE_URL}/api/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to update project');
  }
  return res.json();
}

/**
 * Soft-delete a project. Sessions are unassigned, not deleted.
 * @param {string} projectId
 */
export async function deleteProject(projectId) {
  const res = await authenticatedFetch(`${API_BASE_URL}/api/projects/${projectId}`, {
    method: 'DELETE',
  });
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to delete project');
  }
}

/**
 * Assign an existing session to a project.
 * @param {string} projectId
 * @param {string} sessionId
 */
export async function addSessionToProject(projectId, sessionId) {
  const res = await authenticatedFetch(`${API_BASE_URL}/api/projects/${projectId}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to assign session to project');
  }
}

/**
 * Remove a session from a project (unassign, not delete).
 * @param {string} projectId
 * @param {string} sessionId
 */
export async function removeSessionFromProject(projectId, sessionId) {
  const res = await authenticatedFetch(
    `${API_BASE_URL}/api/projects/${projectId}/sessions/${sessionId}`,
    { method: 'DELETE' },
  );
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to remove session from project');
  }
}
