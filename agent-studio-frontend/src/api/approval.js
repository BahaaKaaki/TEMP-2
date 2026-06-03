/**
 * API client for Marketplace Approval
 * 
 * Handles workflow submissions for marketplace approval and admin review
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';
import { safeLog, safeError } from '../utils/safeLogger';

/**
 * Submit a workflow for marketplace approval
 * 
 * @param {string} workflowId - Workflow ID to submit
 * @param {Object} submissionData - Submission details
 * @param {string} submissionData.marketplaceName - Display name in marketplace
 * @param {string} submissionData.marketplaceDescription - Description for marketplace listing
 * @returns {Promise<Object>} Created submission
 */
export async function submitWorkflowForApproval(workflowId, submissionData) {
  try {
    safeLog(`📤 Submitting workflow ${workflowId} for approval...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/marketplace/approval/submit`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          workflowId,
          ...submissionData
        }),
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to submit workflow for approval');
    }

    const submission = await response.json();
    safeLog(`✅ Workflow ${workflowId} submitted for approval: ${submission.id}`);
    return submission;
  } catch (error) {
    safeError('❌ Failed to submit workflow for approval:', error);
    throw error;
  }
}

/**
 * Get current user's submissions
 * 
 * @param {number} page - Page number
 * @param {number} pageSize - Items per page
 * @param {string} statusFilter - Filter by status (optional)
 * @returns {Promise<Object>} List of user's submissions
 */
export async function fetchMySubmissions(page = 1, pageSize = 10, statusFilter = null) {
  try {
    let url = `${API_BASE_URL}/api/marketplace/approval/my-submissions?page=${page}&page_size=${pageSize}`;
    if (statusFilter) {
      url += `&status_filter=${statusFilter}`;
    }
    
    const response = await authenticatedFetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch submissions: ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    safeError('❌ Failed to fetch my submissions:', error);
    throw error;
  }
}

/**
 * Get all pending submissions (admin only)
 * 
 * @param {number} page - Page number
 * @param {number} pageSize - Items per page
 * @returns {Promise<Object>} List of pending submissions
 */
export async function fetchPendingSubmissions(page = 1, pageSize = 10) {
  try {
    safeLog(`🔍 Fetching pending submissions (page: ${page})...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/marketplace/approval/pending?page=${page}&page_size=${pageSize}`,
      {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to fetch pending submissions');
    }

    const data = await response.json();
    safeLog(`✅ Loaded ${data.items?.length || 0} pending submissions`);
    return data;
  } catch (error) {
    safeError('❌ Failed to fetch pending submissions:', error);
    throw error;
  }
}

/**
 * Get submission details
 * 
 * @param {string} submissionId - Submission ID
 * @returns {Promise<Object>} Submission details
 */
export async function fetchSubmission(submissionId) {
  try {
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/marketplace/approval/${submissionId}`,
      {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to fetch submission');
    }

    return await response.json();
  } catch (error) {
    safeError('❌ Failed to fetch submission:', error);
    throw error;
  }
}

/**
 * Load submitted workflow graph for admin review (read-only canvas).
 *
 * @param {string} submissionId - Submission ID
 * @returns {Promise<Object>} Workflow snapshot (nodes, connections, etc.)
 */
export async function fetchSubmissionWorkflowPreview(submissionId) {
  try {
    safeLog(`🔍 Loading workflow preview for submission ${submissionId}...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/marketplace/approval/${submissionId}/workflow`,
      {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      const detail = error.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg || String(d)).join(', ')
          : 'Failed to load submission workflow';
      throw new Error(message);
    }

    return await response.json();
  } catch (error) {
    safeError('❌ Failed to load submission workflow preview:', error);
    throw error;
  }
}

/**
 * Create test copy of submission workflow (admin only)
 * 
 * @param {string} submissionId - Submission ID
 * @returns {Promise<Object>} Test workflow details
 */
export async function testSubmissionWorkflow(submissionId) {
  try {
    safeLog(`🧪 Creating test copy for submission ${submissionId}...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/marketplace/approval/${submissionId}/test`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to create test workflow');
    }

    const result = await response.json();
    safeLog(`✅ Test workflow created: ${result.testWorkflowId}`);
    return result;
  } catch (error) {
    safeError('❌ Failed to create test workflow:', error);
    throw error;
  }
}

/**
 * Approve submission and publish to marketplace (admin only)
 * 
 * @param {string} submissionId - Submission ID to approve
 * @returns {Promise<Object>} Approval result
 */
/**
 * @param {string} submissionId
 * @param {Object} [sharingOverrides] - For external tool submissions only
 * @param {boolean} [sharingOverrides.is_public]
 * @param {string[]} [sharingOverrides.ad_group_names]
 * @param {string[]} [sharingOverrides.emails]
 */
export async function approveSubmission(submissionId, sharingOverrides = null) {
  try {
    safeLog(`✅ Approving submission ${submissionId}...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/marketplace/approval/${submissionId}/approve`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: sharingOverrides ? JSON.stringify(sharingOverrides) : undefined,
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to approve submission');
    }

    const result = await response.json();
    safeLog(`✅ Submission approved: ${result.workflowId} published to marketplace`);
    return result;
  } catch (error) {
    safeError('❌ Failed to approve submission:', error);
    throw error;
  }
}

/**
 * Reject submission with reason (admin only)
 * 
 * @param {string} submissionId - Submission ID to reject
 * @param {string} reason - Rejection reason
 * @returns {Promise<Object>} Rejection result
 */
export async function rejectSubmission(submissionId, reason) {
  try {
    safeLog(`❌ Rejecting submission ${submissionId}...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/marketplace/approval/${submissionId}/reject`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ reason }),
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to reject submission');
    }

    const result = await response.json();
    safeLog(`✅ Submission rejected: ${submissionId}`);
    return result;
  } catch (error) {
    safeError('❌ Failed to reject submission:', error);
    throw error;
  }
}

/**
 * Import a marketplace workflow directly to user's workflows
 * 
 * @param {string} workflowId - Marketplace workflow ID to import
 * @returns {Promise<Object>} Imported workflow
 */
export async function importMarketplaceWorkflow(workflowId) {
  try {
    safeLog(`📥 Importing marketplace workflow ${workflowId} to workflows...`);
    const response = await authenticatedFetch(
      `${API_BASE_URL}/api/workflows/marketplace/${workflowId}/import`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to import marketplace workflow');
    }

    const workflow = await response.json();
    safeLog(`✅ Imported workflow ${workflow.id}: "${workflow.name}"`);
    return workflow;
  } catch (error) {
    safeError('❌ Failed to import marketplace workflow:', error);
    throw error;
  }
}
