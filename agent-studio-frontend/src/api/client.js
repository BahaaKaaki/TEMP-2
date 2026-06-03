/**
 * API client for agent-studio-backend.
 */

import { getAccessToken, refreshAccessToken, clearAuth } from './auth-client.js';
import { safeLog, safeError, safeWarn } from '../utils/safeLogger';

// Use ?? (nullish coalescing) instead of || to allow empty string for Docker
// Docker: VITE_API_BASE_URL="" → requests go to /api/* (proxied by nginx)
// Local dev: VITE_API_BASE_URL=undefined → requests go to http://localhost:8000/api/*
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

/**
 * Create fetch headers with authentication
 * @param {Object} additionalHeaders - Additional headers to include
 * @returns {Object} Headers object with authentication
 */
export function createHeaders(additionalHeaders = {}) {
  const headers = {
    ...additionalHeaders,
  };
  
  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  return headers;
}

let _logoutDispatched = false;

/**
 * Enhanced fetch with authentication and token refresh.
 *
 * refreshAccessToken() is already serialised (singleton promise) so
 * concurrent 401s share one in-flight refresh instead of racing.
 * We also gate the auth:logout event so it fires at most once per
 * session to prevent multiple components from each triggering a
 * redirect loop.
 */
function validateFetchUrl(url) {
  if (typeof url !== 'string') return;
  if (url.startsWith('/') || url.startsWith(API_BASE_URL)) return;
  const parsed = new URL(url, window.location.origin);
  const allowed = new URL(API_BASE_URL || window.location.origin);
  if (parsed.origin !== allowed.origin) {
    throw new Error('Fetch URL does not match allowed API origin');
  }
}

export async function authenticatedFetch(url, options = {}, isRetry = false) {
  validateFetchUrl(url);
  const headers = createHeaders(options.headers || {});
  const fetchOptions = {
    ...options,
    headers,
    credentials: 'include',
  };
  
  let response;
  try {
    response = await fetch(url, fetchOptions);
  } catch (networkError) {
    if (!isRetry) {
      safeWarn('Network error, retrying once:', networkError.message);
      return authenticatedFetch(url, options, true);
    }
    throw networkError;
  }
  
  if (response.status === 401 && !isRetry) {
    try {
      await refreshAccessToken();
      _logoutDispatched = false;
      return authenticatedFetch(url, options, true);
    } catch {
      if (!_logoutDispatched) {
        _logoutDispatched = true;
        clearAuth();
        window.dispatchEvent(new CustomEvent('auth:logout'));
      }
      throw new Error('Session expired. Please login again.');
    }
  }
  
  if (response.status >= 502 && response.status <= 504 && !isRetry) {
    safeWarn(`Gateway error ${response.status}, retrying once`);
    return authenticatedFetch(url, options, true);
  }
  
  return response;
}

/**
 * List all workflows
 * @param {number} page - Page number (1-based)
 * @param {number} pageSize - Items per page (backend enforces max 100)
 */
export async function listWorkflows(page = 1, pageSize = 20, options = {}) {
  // Backend: workflow_entity.list_workflows uses Query(..., le=100).
  // Values above 100 return 422 — callers that `.catch(() => [])` then see empty lists.
  const safePageSize = Math.min(100, Math.max(1, Number(pageSize) || 20));
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: safePageSize.toString(),
  });
  
  if (options.activeOnly) params.append('active_only', 'true');
  if (options.search) params.append('search', options.search);
  
  const url = `${API_BASE_URL}/api/workflows/?${params.toString()}`;
  safeLog('Fetching workflows from:', url);
  
  const response = await authenticatedFetch(url);
  safeLog('Response status:', response.status);
  
  if (!response.ok) {
    const errorText = await response.text();
    safeError('Error response:', errorText);
    throw new Error(`Failed to list workflows: ${response.statusText}`);
  }
  
  const data = await response.json();
  safeLog('Raw API response:', data);
  
  // Backend returns { items, total, ... }
  return {
    workflows: data.items || [],
    total: data.total || 0,
  };
}

/**
 * Get a specific workflow by ID
 */
export async function getWorkflow(workflowId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/workflows/${workflowId}`);
  if (!response.ok) {
    throw new Error(`Failed to get workflow: ${response.statusText}`);
  }
  return response.json();
}

// ============================================================================
// SESSION-BASED CHAT API (New Approach)
// ============================================================================

/**
 * Create a new chat session for a workflow
 */
export async function createChatSession(workflowId, sessionData = {}) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/workflows/${workflowId}/sessions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(sessionData),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to create session: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * List all chat sessions for a workflow
 */
export async function listChatSessions(workflowId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/workflows/${workflowId}/sessions`);
  if (!response.ok) {
    throw new Error(`Failed to list sessions: ${response.statusText}`);
  }
  return response.json();
}

/**
 * List all sessions for the current user across all workflows in one request.
 */
export async function listAllMySessions(limit = 200) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/my-sessions?limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Failed to list sessions: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get session details including conversation history
 */
export async function getChatSession(sessionId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`);
  if (!response.ok) {
    throw new Error(`Failed to get session: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get current execution status for a session (for polling)
 * Returns which agent is currently executing
 */
export async function getSessionStatus(sessionId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/status`);
  if (!response.ok) {
    throw new Error(`Failed to get session status: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Send a message to a specific session
 */
export async function sendMessageToSession(sessionId, message, options = {}) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message, ...options }),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to send message: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Update session metadata
 */
export async function updateChatSession(sessionId, updates) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to update session: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Delete a chat session
 */
export async function deleteChatSession(sessionId, permanent = false) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}?permanent=${permanent}`, {
    method: 'DELETE',
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to delete session: ${response.statusText}`);
  }
  
  return response.json();
}

// ============================================================================
// PIN & LAST ACCESSED API
// ============================================================================

/**
 * Toggle pin status for a workflow
 */
export async function toggleWorkflowPin(workflowId, pinned) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/workflows/${workflowId}/pin?pinned=${pinned}`,
    { method: 'PATCH' }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to toggle pin');
  }
  return response.json();
}

/**
 * Update last accessed timestamp for a workflow
 */
export async function updateWorkflowLastAccessed(workflowId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/workflows/${workflowId}/last-accessed`,
    { method: 'PATCH' }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to update last accessed');
  }
  return response.json();
}

/**
 * Toggle pin status for a chat session
 */
export async function toggleSessionPin(sessionId, pinned) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/chat/sessions/${sessionId}/pin?pinned=${pinned}`,
    { method: 'PATCH' }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to toggle session pin');
  }
  return response.json();
}

/**
 * Update last accessed timestamp for a chat session
 */
export async function updateSessionLastAccessed(sessionId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/chat/sessions/${sessionId}/last-accessed`,
    { method: 'PATCH' }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to update session last accessed');
  }
  return response.json();
}

// ============================================================================
// LEGACY API (Deprecated - kept for backward compatibility)
// ============================================================================

/**
 * Send a message to a workflow (LEGACY - use sessions instead)
 * @deprecated Use createChatSession + sendMessageToSession instead
 */
export async function chatWithWorkflow(workflowId, message, conversationId) {
  const body = { message };
  if (conversationId) {
    body.conversation_id = conversationId;
  }

  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/workflows/${workflowId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to chat: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Create a new workflow
 */
export async function createWorkflow(workflowData) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/workflows/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(workflowData),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to create workflow: ${response.statusText}`);
  }
  
  const result = await response.json();
  safeLog('Workflow created:', result);
  return result;
}

/**
 * Update an existing workflow
 */
export async function updateWorkflow(workflowId, workflowData) {
  safeLog('Updating workflow:', workflowId, workflowData);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/workflows/${workflowId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(workflowData),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to update workflow: ${response.statusText}`);
  }
  
  const result = await response.json();
  safeLog('Workflow updated:', result);
  return result;
}

/**
 * Duplicate a workflow by cloning its data and creating a new one
 */
export async function duplicateWorkflow(workflow) {
  const cloned = {
    name: `${workflow.name} (Copy)`,
    description: workflow.description || '',
    nodes: workflow.nodes || '[]',
    connections: workflow.connections || '[]',
    settings: workflow.settings || null,
    isDraft: true,
  };
  return createWorkflow(cloned);
}

/**
 * Delete a workflow
 */
export async function deleteWorkflow(workflowId, permanent = false) {
  safeLog('Deleting workflow:', workflowId, 'permanent:', permanent);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/workflows/${workflowId}?permanent=${permanent}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to delete workflow: ${response.statusText}`);
  }
  
  safeLog('Workflow deleted:', workflowId);
  return true;
}

/**
 * Publish a draft workflow
 */
export async function publishWorkflow(workflowId, { force = false } = {}) {
  safeLog('Publishing workflow:', workflowId, force ? '(force)' : '');
  
  const url = `${API_BASE_URL}/api/workflows/${workflowId}/publish${force ? '?force=true' : ''}`;
  const response = await authenticatedFetch(url, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (response.status === 409) {
    const body = await response.json().catch(() => ({}));
    if (body.has_pending_submission) {
      const err = new Error(body.detail || 'An admin approval is already pending for this workflow.');
      err.hasPendingSubmission = true;
      throw err;
    }
  }
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to publish workflow: ${response.statusText}`);
  }
  
  const result = await response.json();
  safeLog('Workflow published:', result);
  return result;
}

// ============================================
// DELIVERABLE MANAGEMENT (HITL)
// ============================================

/**
 * Get all deliverables for a session
 * @param {string} sessionId - Session UUID
 * @returns {Promise<Object>} Deliverables list
 */
export async function getSessionDeliverables(sessionId) {
  safeLog('Getting deliverables for session:', sessionId);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/deliverables`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to get deliverables: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Get single deliverable details
 * @param {string} deliverableId - Deliverable UUID
 * @returns {Promise<Object>} Deliverable details
 */
export async function getDeliverable(deliverableId) {
  safeLog('Getting deliverable:', deliverableId);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/deliverables/${deliverableId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to get deliverable: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Approve a deliverable
 * @param {string} deliverableId - Deliverable UUID
 * @param {Object} approvalData - { review_notes?, edited_deliverable?, reviewed_by? }
 * @returns {Promise<Object>} Approval response
 */
export async function approveDeliverable(deliverableId, approvalData = {}) {
  safeLog('Approving deliverable:', deliverableId, approvalData);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/deliverables/${deliverableId}/approve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(approvalData),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to approve deliverable: ${response.statusText}`);
  }
  
  const result = await response.json();
  safeLog('Deliverable approved:', result);
  return result;
}

export async function respondToWidget(deliverableId, response) {
  const resp = await authenticatedFetch(`${API_BASE_URL}/api/chat/deliverables/${deliverableId}/respond`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ response }),
  });
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(error.detail || 'Failed to submit widget response');
  }
  return resp.json();
}

/**
 * Create an on-demand Edwin handoff for a single deliverable.
 * @param {string} deliverableId - Deliverable UUID
 * @returns {Promise<{id: string, url: string}>} Edwin handoff id and URL
 */
export async function getOpenUITranslationPrompt() {
  const resp = await authenticatedFetch(`${API_BASE_URL}/api/openui/debug/prompt`);
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(error.detail || 'Failed to load OpenUI prompt');
  }
  return resp.json();
}

export async function createDeliverableEdwinHandoff(deliverableId) {
  const resp = await authenticatedFetch(
    `${API_BASE_URL}/api/chat/deliverables/${deliverableId}/edwin-handoff`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' } },
  );
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(error.detail || 'Failed to create Edwin handoff');
  }
  return resp.json();
}

/**
 * Reject a deliverable
 * @param {string} deliverableId - Deliverable UUID
 * @param {Object} rejectionData - { review_notes (required), reviewed_by? }
 * @returns {Promise<Object>} Rejection response
 */
export async function rejectDeliverable(deliverableId, rejectionData) {
  safeLog('Rejecting deliverable:', deliverableId, rejectionData);
  
  if (!rejectionData.review_notes) {
    throw new Error('review_notes is required for rejection');
  }
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/deliverables/${deliverableId}/reject`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(rejectionData),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to reject deliverable: ${response.statusText}`);
  }
  
  const result = await response.json();
  safeLog('Deliverable rejected:', result);
  return result;
}

// ============================================
// FEEDBACK
// ============================================

/**
 * Submit user feedback
 * @param {Object} feedbackData - { category, subject, message, rating?, pageUrl? }
 * @returns {Promise<Object>} Created feedback object
 */
export async function submitFeedback(feedbackData) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(feedbackData),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to submit feedback: ${response.statusText}`);
  }

  return response.json();
}

// ============================================
// FILE UPLOAD MANAGEMENT
// ============================================

/**
 * Upload a file to a chat session
 * @param {string} sessionId - Session UUID
 * @param {File} file - File object to upload
 * @param {Object} options - Optional { description, uploaded_by }
 * @returns {Promise<Object>} Upload response with file metadata
 */
export async function uploadFileToSession(sessionId, file, options = {}) {
  safeLog('Uploading file to session:', sessionId, file.name);
  
  const formData = new FormData();
  formData.append('file', file);
  
  if (options.description) {
    formData.append('description', options.description);
  }
  if (options.uploaded_by) {
    formData.append('uploaded_by', options.uploaded_by);
  }
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/files`, {
    method: 'POST',
    body: formData,
    // Don't set Content-Type header - browser will set it with boundary for multipart/form-data
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to upload file: ${response.statusText}`);
  }
  
  const result = await response.json();
  safeLog('File uploaded:', result);
  return result;
}

/**
 * List all files in a session
 * @param {string} sessionId - Session UUID
 * @returns {Promise<Object>} Files list { files: [], total: number }
 */
export async function listSessionFiles(sessionId) {
  safeLog('Listing files for session:', sessionId);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/files`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to list files: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Get file details including extracted text
 * @param {string} fileId - File UUID
 * @returns {Promise<Object>} File details
 */
export async function getFileDetails(fileId) {
  safeLog('Getting file details:', fileId);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/files/${fileId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to get file details: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Download a file
 * @param {string} fileId - File UUID
 * @returns {Promise<Blob>} File blob
 */
export async function downloadFile(fileId) {
  safeLog('Downloading file:', fileId);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/files/${fileId}/download`);
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to download file: ${response.statusText}`);
  }
  
  return await response.blob();
}

/**
 * Delete a file
 * @param {string} fileId - File UUID
 * @returns {Promise<Object>} Delete confirmation
 */
export async function deleteFile(fileId) {
  safeLog('Deleting file:', fileId);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/files/${fileId}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to delete file: ${response.statusText}`);
  }
  
  const result = await response.json();
  safeLog('File deleted:', result);
  return result;
}

// ============================================
// POWERPOINT GENERATION
// ============================================

/**
 * Generate horizontal logic (storyline) from deliverable data.
 * @param {Object} data - { deliverable_id, deliverable_data, num_slides?, context? }
 * @returns {Promise<Object>} { horizontal_logic, message }
 */
export async function generateHorizontalLogic(data) {
  safeLog('Generating horizontal logic for deliverable:', data.deliverable_id);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/pptx/horizontal-logic`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to generate storyline: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Update horizontal logic after user edits.
 * @param {Object} horizontalLogic - The edited horizontal logic object
 * @returns {Promise<Object>} { horizontal_logic, message }
 */
export async function updateHorizontalLogic(horizontalLogic) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/pptx/horizontal-logic`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(horizontalLogic),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to update storyline: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Generate content for all slides in parallel (vertical logic).
 * @param {Object} data - { deliverable_data, horizontal_logic, context? }
 * @returns {Promise<Object>} { slides, total, message }
 */
export async function generateVerticalLogic(data) {
  safeLog('Generating vertical logic for', data.horizontal_logic?.slides?.length, 'slides');
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/pptx/vertical-logic`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to generate slide content: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Generate or regenerate a single slide.
 * @param {Object} data - { deliverable_data, headline, subtitle, layout, context? }
 * @returns {Promise<Object>} { slide, message }
 */
export async function generateSlide(data) {
  safeLog('Generating slide:', data.headline);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/pptx/generate-slide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to generate slide: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Modify an existing slide via chat instruction.
 * @param {Object} data - { slide, instruction, deliverable_data? }
 * @returns {Promise<Object>} { slide, message }
 */
export async function modifySlide(data) {
  safeLog('Modifying slide:', data.slide?.id, 'instruction:', data.instruction);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/pptx/modify-slide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to modify slide: ${response.statusText}`);
  }
  
  return await response.json();
}

/**
 * Export presentation to .pptx file and trigger download.
 * @param {Object} presentation - Full presentation object { title, slides, theme }
 * @returns {Promise<Blob>} The .pptx file as a Blob
 */
export async function exportPowerPoint(presentation) {
  safeLog('Exporting presentation:', presentation.title);
  
  const response = await authenticatedFetch(`${API_BASE_URL}/api/pptx/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ presentation }),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to export presentation: ${response.statusText}`);
  }
  
  return await response.blob();
}

/**
 * Export a branded CV presentation using the S& template engine.
 * @param {Object} cvData - { profiles, single_profile_contents, case_projects_all, team_slide_title }
 * @returns {Promise<Blob>} The .pptx file as a Blob
 */
// ============================================================================
// Checkpoint / Revert
// ============================================================================

/**
 * List checkpoints for a session (used to show revert buttons on user messages).
 * @param {string} sessionId
 * @returns {Promise<{checkpoints: Array<{id, user_message_id, step_index, created_at}>}>}
 */
export async function getSessionCheckpoints(sessionId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/checkpoints`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to get checkpoints: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Revert a session to a checkpoint (restores everything to before a specific user message).
 * @param {string} sessionId
 * @param {string} checkpointId
 * @returns {Promise<{session_id, checkpoint_id, conversation_history, prefill_message, deliverables, pending_deliverable, status}>}
 */
export async function revertToCheckpoint(sessionId, checkpointId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/revert/${checkpointId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to revert: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Upload a workflow icon image.
 * @param {string} workflowId
 * @param {File} file
 * @returns {Promise<{icon: string}>}
 */
export async function uploadWorkflowIcon(workflowId, file) {
  const formData = new FormData();
  formData.append('file', file);
  const response = await authenticatedFetch(`${API_BASE_URL}/api/workflows/${workflowId}/icon`, {
    method: 'POST',
    body: formData,
    // Don't set Content-Type — browser sets it with boundary for multipart
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to upload icon');
  }
  return response.json();
}

/**
 * Delete a workflow icon.
 * @param {string} workflowId
 * @returns {Promise<{icon: null}>}
 */
export async function deleteWorkflowIcon(workflowId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/workflows/${workflowId}/icon`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to delete icon');
  }
  return response.json();
}

