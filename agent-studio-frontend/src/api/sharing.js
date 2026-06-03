/**
 * API client for AD-group / per-user sharing of workflows and knowledge bases.
 *
 * Backend reference: app/routers/sharing_router.py (prefix: /api/sharing)
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';
import { safeLog, safeError } from '../utils/safeLogger';

async function _json(response, fallbackError) {
  if (!response.ok) {
    let detail = fallbackError;
    let body = {};
    try {
      body = await response.json();
      detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.message || detail;
    } catch (_) {
      /* swallow */
    }
    const err = new Error(detail);
    if (response.status === 409 && body?.has_pending_submission) {
      err.hasPendingSubmission = true;
      err.submissionId = body.submissionId;
    }
    throw err;
  }
  if (response.status === 204) return null;
  return response.json();
}

// ---------------------------------------------------------------------------
// Workflow shares
// ---------------------------------------------------------------------------

/**
 * Create or update a sharing grant on a workflow.
 *
 * @param {string} workflowId
 * @param {{principalType:'group'|'user', principalId:string, permission?:'read'|'write', displayName?:string}} body
 * @returns {Promise<Object>}
 */
export async function shareWorkflow(workflowId, body, { force = false } = {}) {
  try {
    const url = `${API_BASE_URL}/api/sharing/workflows/${workflowId}/shares${force ? '?force=true' : ''}`;
    const response = await authenticatedFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await _json(response, 'Failed to create share');
    if (data?.status === 'pending') {
      safeLog(`⏳ Share grant pending approval for workflow ${workflowId}`);
    } else {
      safeLog(`✅ Shared workflow ${workflowId} with ${body.principalType}:${body.principalId}`);
    }
    return data;
  } catch (error) {
    safeError('❌ Failed to share workflow:', error);
    throw error;
  }
}

export async function listWorkflowShares(workflowId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/workflows/${workflowId}/shares`,
    { method: 'GET' }
  );
  const data = await _json(response, 'Failed to list workflow shares');
  return {
    shares: data?.shares || [],
    pendingGrants: data?.pendingGrants || [],
  };
}

export async function revokeWorkflowShare(workflowId, shareId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/workflows/${workflowId}/shares/${shareId}`,
    { method: 'DELETE' }
  );
  await _json(response, 'Failed to revoke share');
  return true;
}

// ---------------------------------------------------------------------------
// Knowledge-base shares
// ---------------------------------------------------------------------------

export async function shareKnowledgeBase(kbId, body) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/knowledge-bases/${kbId}/shares`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }
  );
  return _json(response, 'Failed to share knowledge base');
}

export async function listKnowledgeBaseShares(kbId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/knowledge-bases/${kbId}/shares`,
    { method: 'GET' }
  );
  const data = await _json(response, 'Failed to list KB shares');
  return data?.shares || [];
}

export async function revokeKnowledgeBaseShare(kbId, shareId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/knowledge-bases/${kbId}/shares/${shareId}`,
    { method: 'DELETE' }
  );
  await _json(response, 'Failed to revoke KB share');
  return true;
}

// ---------------------------------------------------------------------------
// Shared-with-me feed
// ---------------------------------------------------------------------------

export async function listSharedWithMeWorkflows() {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/shared-with-me/workflows`,
    { method: 'GET' }
  );
  return _json(response, 'Failed to load shared workflows');
}

export async function listSharedWithMeKnowledgeBases() {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/shared-with-me/knowledge-bases`,
    { method: 'GET' }
  );
  return _json(response, 'Failed to load shared knowledge bases');
}

// ---------------------------------------------------------------------------
// Discovery / pickers
// ---------------------------------------------------------------------------

/**
 * Search Microsoft Entra ID groups (proxied through the backend Graph call,
 * with a local cache fallback).
 *
 * @param {string} q
 * @param {number} [limit=20]
 */
export async function searchAdGroups(q = '', limit = 20) {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  params.set('limit', String(limit));
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/groups/search?${params.toString()}`,
    { method: 'GET' }
  );
  return _json(response, 'Failed to search groups');
}

/** List the AD groups the current user is a member of. */
export async function listMyGroups() {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/groups/me`,
    { method: 'GET' }
  );
  return _json(response, 'Failed to list my groups');
}

/**
 * Search local users by email/first/last name (does NOT hit Graph because we
 * can only share with users that already have a row in our user table).
 */
export async function searchUsers(q, limit = 20) {
  if (!q || q.length < 2) return [];
  const params = new URLSearchParams({ q, limit: String(limit) });
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/sharing/users/search?${params.toString()}`,
    { method: 'GET' }
  );
  return _json(response, 'Failed to search users');
}
