/**
 * Knowledge Base API client
 * Uses centralized authentication from client.js
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';

// ============================================
// KNOWLEDGE BASE MANAGEMENT
// ============================================

/**
 * @param {string|null} sessionId
 * @param {string|null} search
 * @param {{ scope?: 'manage' | 'attach' }} [options]
 *   - manage (default): owned + write-shared — My Tools
 *   - attach: all visible including read-only shares and marketplace — workflow picker
 */
export async function listKnowledgeBases(sessionId = null, search = null, options = {}) {
  let url;
  if (sessionId) {
    url = `${API_BASE_URL}/api/knowledge-bases/sessions/${sessionId}`;
  } else {
    const params = new URLSearchParams();
    if (search) params.append('search', search);
    if (options.scope) params.append('scope', options.scope);
    const qs = params.toString();
    url = `${API_BASE_URL}/api/knowledge-bases/${qs ? `?${qs}` : ''}`;
  }
  
  const response = await authenticatedFetch(url);
  if (!response.ok) {
    throw new Error(`Failed to list knowledge bases: ${response.statusText}`);
  }
  return response.json();
}

/** KBs available when attaching to an agent / code-runner (includes consume-only). */
export async function listKnowledgeBasesForAttach(search = null) {
  return listKnowledgeBases(null, search, { scope: 'attach' });
}

export async function toggleKBPin(kbId, pinned) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/knowledge-bases/${kbId}/pin?pinned=${pinned}`,
    { method: 'PATCH' }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to toggle KB pin');
  }
  return response.json();
}

export async function updateKBLastAccessed(kbId) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/knowledge-bases/${kbId}/last-accessed`,
    { method: 'PATCH' }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to update KB last accessed');
  }
  return response.json();
}

export async function getKnowledgeBase(kbId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}`);
  if (!response.ok) {
    throw new Error(`Failed to get knowledge base: ${response.statusText}`);
  }
  return response.json();
}

export async function createKnowledgeBase(data) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to create knowledge base: ${response.statusText}`);
  }
  return response.json();
}

export async function deleteKnowledgeBase(kbId, permanent = false) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}?permanent=${permanent}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete knowledge base: ${response.statusText}`);
  }
  return response.json();
}

export async function searchKnowledgeBase(kbId, query_embedding, limit = 10, distance_threshold = null) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query_embedding, limit, distance_threshold, use_sphere: true }),
  });
  if (!response.ok) {
    throw new Error(`Failed to search knowledge base: ${response.statusText}`);
  }
  return response.json();
}

// ============================================
// DOCUMENT MANAGEMENT
// ============================================

export async function uploadDocument(kbId, file, uploaded_by = null, chunkingOverrides = null, metadataFields = null, visionConfig = null) {
  const formData = new FormData();
  formData.append('file', file);
  if (uploaded_by) formData.append('uploaded_by', uploaded_by);

  if (chunkingOverrides) {
    if (chunkingOverrides.chunking_method) formData.append('chunking_method', chunkingOverrides.chunking_method);
    if (chunkingOverrides.chunk_size != null) formData.append('chunk_size', String(chunkingOverrides.chunk_size));
    if (chunkingOverrides.chunk_overlap != null) formData.append('chunk_overlap', String(chunkingOverrides.chunk_overlap));
    if (chunkingOverrides.delimiter) formData.append('delimiter', chunkingOverrides.delimiter);
  }

  if (metadataFields && metadataFields.length > 0) {
    formData.append('metadata_fields', JSON.stringify(metadataFields));
  }

  if (visionConfig) {
    formData.append('chunking_method', 'vision');
    if (visionConfig.prompt) formData.append('vision_prompt', visionConfig.prompt);
    if (visionConfig.model) formData.append('vision_model', visionConfig.model);
    if (visionConfig.output_schema) formData.append('vision_output_schema', JSON.stringify(visionConfig.output_schema));
  }

  const response = await authenticatedFetch(`${API_BASE_URL}/api/documents/knowledge-bases/${kbId}/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = error.detail;
    const message = typeof detail === 'object' && detail !== null
      ? detail.error || JSON.stringify(detail)
      : detail || `Failed to upload document: ${response.statusText}`;
    throw new Error(message);
  }
  return response.json();
}

export async function listKBDocuments(kbId, include_deleted = false) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/documents/knowledge-bases/${kbId}/documents?include_deleted=${include_deleted}`);
  if (!response.ok) {
    throw new Error(`Failed to list documents: ${response.statusText}`);
  }
  return response.json();
}

export async function getDocument(documentId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/documents/${documentId}`);
  if (!response.ok) {
    throw new Error(`Failed to get document: ${response.statusText}`);
  }
  return response.json();
}

export async function deleteDocument(documentId, permanent = false) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/documents/${documentId}?permanent=${permanent}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete document: ${response.statusText}`);
  }
  return response.json();
}

export async function getDocumentChunks(kbId, documentId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/documents/${documentId}/chunks`);
  if (!response.ok) {
    throw new Error(`Failed to get chunks: ${response.statusText}`);
  }
  return response.json();
}

export async function getDownloadUrl(documentId, expiry_hours = 24) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/documents/${documentId}/download-url?expiry_hours=${expiry_hours}`);
  if (!response.ok) {
    throw new Error(`Failed to get download URL: ${response.statusText}`);
  }
  return response.json();
}

// ============================================
// STRUCTURED DATA
// ============================================

export async function confirmStructuredSchema(documentId, tables) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/documents/${documentId}/confirm-schema`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tables }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to confirm schema: ${response.statusText}`);
  }
  return response.json();
}export async function searchDocumentChunks(kbId, documentId, { page = 1, pageSize = 20, q = '' } = {}) {
  let url = `${API_BASE_URL}/api/knowledge-bases/${kbId}/documents/${documentId}/chunks/search?page=${page}&page_size=${pageSize}`;
  if (q) url += `&q=${encodeURIComponent(q)}`;
  const response = await authenticatedFetch(url);
  if (!response.ok) {
    throw new Error(`Failed to search chunks: ${response.statusText}`);
  }
  return response.json();
}

export async function getKBAssets(kbId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/assets`);
  if (!response.ok) {
    throw new Error(`Failed to get KB assets: ${response.statusText}`);
  }
  return response.json();
}

export async function getStructuredTablePreview(documentId, { page = 1, pageSize = 50, sheetTableId = null } = {}) {
  let url = `${API_BASE_URL}/api/documents/${documentId}/structured-preview?page=${page}&page_size=${pageSize}`;
  if (sheetTableId) url += `&sheet=${sheetTableId}`;
  const response = await authenticatedFetch(url);
  if (!response.ok) {
    throw new Error(`Failed to get structured preview: ${response.statusText}`);
  }
  return response.json();
}

export async function listRelationships(kbId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/relationships`);
  if (!response.ok) throw new Error(`Failed to list relationships: ${response.statusText}`);
  return response.json();
}

export async function createRelationship(kbId, data) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/relationships`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to create relationship: ${response.statusText}`);
  }
  return response.json();
}

export async function deleteRelationship(kbId, relId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/relationships/${relId}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error(`Failed to delete relationship: ${response.statusText}`);
  return response.json();
}

export async function updateStructuredColumnDescription(kbId, columnId, description) {
  const response = await authenticatedFetch(
    `${API_BASE_URL}/api/knowledge-bases/${kbId}/structured-columns/${columnId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: description ?? '' }),
    }
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `Failed to update column description: ${response.statusText}`);
  }
  return response.json();
}