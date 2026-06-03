/**
 * API client for Workflow Marketplace
 * 
 * Handles sharing workflows to marketplace and copying marketplace workflows
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';
import { safeLog, safeError } from '../utils/safeLogger';

/**
 * Share a workflow to the marketplace
 * 
 * @param {string} workflowId - Workflow ID to share
 * @param {Object} marketplaceData - Marketplace details
 * @param {string} marketplaceData.marketplaceName - Display name in marketplace
 * @param {string} marketplaceData.marketplaceDescription - Description for marketplace listing
 * @returns {Promise<Object>} Updated workflow
 */
export async function shareWorkflowToMarketplace(workflowId, marketplaceData) {
  try {
    safeLog(`🚀 Sharing workflow ${workflowId} to marketplace...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/workflows/${workflowId}/share-to-marketplace`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(marketplaceData),
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to share workflow to marketplace');
    }

    const workflow = await response.json();
    safeLog(`✅ Workflow ${workflowId} shared to marketplace as "${workflow.marketplaceName}"`);
    return workflow;
  } catch (error) {
    safeError('❌ Failed to share workflow to marketplace:', error);
    throw error;
  }
}

/**
 * Remove a workflow from the marketplace
 * 
 * @param {string} workflowId - Workflow ID to unshare
 * @returns {Promise<Object>} Updated workflow
 */
export async function unshareWorkflowFromMarketplace(workflowId) {
  try {
    safeLog(`🔒 Unsharing workflow ${workflowId} from marketplace...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/workflows/${workflowId}/unshare-from-marketplace`,
      {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to unshare workflow from marketplace');
    }

    const workflow = await response.json();
    safeLog(`✅ Workflow ${workflowId} removed from marketplace`);
    return workflow;
  } catch (error) {
    safeError('❌ Failed to unshare workflow from marketplace:', error);
    throw error;
  }
}

/**
 * Get all workflows shared to marketplace
 * 
 * @param {number} skip - Number of records to skip (pagination)
 * @param {number} limit - Maximum number of records to return
 * @returns {Promise<Object>} List of marketplace workflows
 */
export async function fetchMarketplaceWorkflows(skip = 0, limit = 100, search = null) {
  try {
    const params = new URLSearchParams({ skip: skip.toString(), limit: limit.toString() });
    if (search) params.append('search', search);
    safeLog(`🛒 Fetching marketplace workflows (skip: ${skip}, limit: ${limit})...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/workflows/marketplace/list?${params.toString()}`,
      {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      throw new Error(`Failed to fetch marketplace workflows: ${response.statusText}`);
    }

    const data = await response.json();
    safeLog(`✅ Loaded ${data.items?.length || 0} marketplace workflows (total: ${data.total})`);
    return data;
  } catch (error) {
    safeError('❌ Failed to fetch marketplace workflows:', error);
    throw error;
  }
}

/**
 * Copy a marketplace workflow to user's drafts
 * 
 * @param {string} workflowId - Marketplace workflow ID to copy
 * @returns {Promise<Object>} New draft workflow
 */
export async function copyMarketplaceWorkflow(workflowId) {
  try {
    safeLog(`📋 Copying marketplace workflow ${workflowId} to drafts...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/workflows/marketplace/${workflowId}/copy`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to copy marketplace workflow');
    }

    const newWorkflow = await response.json();
    safeLog(`✅ Copied to draft workflow ${newWorkflow.id}: "${newWorkflow.name}"`);
    return newWorkflow;
  } catch (error) {
    safeError('❌ Failed to copy marketplace workflow:', error);
    throw error;
  }
}
