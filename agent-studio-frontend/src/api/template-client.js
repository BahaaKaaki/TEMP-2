/**
 * Template engine API client.
 *
 * Provides functions for uploading PPTX templates, retrieving metadata /
 * generated schemas, filling templates with deliverable data, and deleting
 * templates.
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';

/**
 * Upload a PPTX template for a workflow agent node.
 * @param {string} workflowId
 * @param {string} agentNodeId
 * @param {File}   file           - The .pptx File object
 * @param {string} [templateName] - Optional display name
 * @returns {Promise<Object>} { id, name, fileName, placeholders, generatedSchema }
 */
export async function uploadTemplate(workflowId, agentNodeId, file, templateName) {
  const form = new FormData();
  form.append('file', file);
  form.append('workflow_id', workflowId);
  form.append('agent_node_id', agentNodeId);
  if (templateName) form.append('template_name', templateName);

  const response = await authenticatedFetch(`${API_BASE_URL}/api/templates/upload`, {
    method: 'POST',
    body: form,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || 'Failed to upload template');
  }
  return response.json();
}

/**
 * Get template metadata including placeholders and generated schema.
 * @param {string} templateId
 * @returns {Promise<Object>}
 */
export async function getTemplate(templateId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/templates/${templateId}`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || 'Failed to get template');
  }
  return response.json();
}

/**
 * Get the auto-generated JSON Schema for a template.
 * @param {string} templateId
 * @returns {Promise<Object>} JSON Schema object
 */
export async function getTemplateSchema(templateId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/templates/${templateId}/schema`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || 'Failed to get template schema');
  }
  return response.json();
}

/**
 * List all templates for a workflow.
 * @param {string} workflowId
 * @returns {Promise<Array>}
 */
export async function listTemplatesForWorkflow(workflowId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/templates/workflow/${workflowId}`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || 'Failed to list templates');
  }
  return response.json();
}

/**
 * Fill a template with structured data and download the resulting PPTX.
 * @param {string} templateId
 * @param {Object} data - Deliverable data matching the template schema
 * @returns {Promise<Blob>} PPTX file blob
 */
export async function fillTemplate(templateId, data) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/templates/${templateId}/fill`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || 'Failed to fill template');
  }
  return response.blob();
}

/**
 * Delete a template and its stored blob.
 * @param {string} templateId
 * @returns {Promise<Object>}
 */
export async function deleteTemplate(templateId) {
  const response = await authenticatedFetch(`${API_BASE_URL}/api/templates/${templateId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || 'Failed to delete template');
  }
  return response.json();
}
