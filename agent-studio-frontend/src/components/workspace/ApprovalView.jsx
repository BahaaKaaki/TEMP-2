import { useState, useEffect } from 'react';
import { fetchPendingSubmissions, approveSubmission, rejectSubmission } from '@/api/approval';
import Button from '../ui/Button';
import AlertModal from '../ui/AlertModal';
import ConfirmModal from '../ui/ConfirmModal';
import SharingTargetsFields from '../sharing/SharingTargetsFields';
import SubmissionWorkflowReview from '../admin/SubmissionWorkflowReview';

function submissionTypeLabel(type) {
  switch (type) {
    case 'shared_tool':
      return 'External Tool';
    case 'workflow_share_grant':
      return 'Share grant';
    case 'workflow_share_version':
      return 'Version update';
    default:
      return 'Marketplace';
  }
}

function submissionTypeBadgeClass(type) {
  switch (type) {
    case 'shared_tool':
      return 'bg-blue-100 text-blue-800';
    case 'workflow_share_grant':
      return 'bg-purple-100 text-purple-800';
    case 'workflow_share_version':
      return 'bg-amber-100 text-amber-800';
    default:
      return 'bg-orange-100 text-orange-800';
  }
}

function approveConfirmMessage(submission) {
  const name = submission.marketplaceName;
  switch (submission.submission_type) {
    case 'workflow_share_grant': {
      const m = submission.meta || {};
      if (m.principalType === 'group') {
        return `Approve sharing "${name}" with AD group "${m.displayName || m.principalId}"? Recipients in that group will gain access after approval.`;
      }
      return `Approve sharing "${name}" with an additional user (16+ user threshold)? They will gain access after approval.`;
    }
    case 'workflow_share_version':
      return `Approve the new published version for "${name}"? Shared recipients will see this version on the Storefront.`;
    default:
      return `Approve "${name}" for the public Storefront? All authenticated users will be able to use this workflow.`;
  }
}

function approveSuccessMessage(submission, result) {
  const name = submission.marketplaceName;
  switch (submission.submission_type) {
    case 'shared_tool':
      return `"${name}" is now on the Storefront with the sharing settings you configured.`;
    case 'workflow_share_grant':
      return result?.message || `"${name}" share grant is now active for recipients.`;
    case 'workflow_share_version':
      return result?.message || `Recipients of "${name}" will now see the approved version.`;
    default:
      return `"${name}" has been published to the marketplace.${result?.sharedKnowledgeBases > 0 ? ` ${result.sharedKnowledgeBases} knowledge base(s) were also shared.` : ''}`;
  }
}

/**
 * ApprovalView - Admin panel for reviewing and approving marketplace submissions
 * 
 * Features:
 * - View all pending submissions
 * - Inspect workflow on read-only canvas and test from the review view
 * - Approve submissions to publish to marketplace
 * - Reject submissions with reason
 */
export default function ApprovalView({ isAdmin }) {
  const [submissions, setSubmissions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(null);
  const [reviewSubmission, setReviewSubmission] = useState(null);
  
  // Modal states
  const [alertModal, setAlertModal] = useState({ isOpen: false, title: '', message: '', variant: 'error' });
  const [confirmModal, setConfirmModal] = useState({ isOpen: false, title: '', message: '', onConfirm: null });
  const [rejectModal, setRejectModal] = useState({ isOpen: false, submission: null });
  const [rejectionReason, setRejectionReason] = useState('');
  const [approveToolModal, setApproveToolModal] = useState({ isOpen: false, submission: null });
  const [approveIsPublic, setApproveIsPublic] = useState(false);
  const [approveGroups, setApproveGroups] = useState([]);
  const [approveEmails, setApproveEmails] = useState([]);

  useEffect(() => {
    if (isAdmin) {
      fetchSubmissions();
    }
  }, [isAdmin]);

  const fetchSubmissions = async () => {
    try {
      setLoading(true);
      const data = await fetchPendingSubmissions(1, 50);
      setSubmissions(data.items || []);
    } catch (error) {
      console.error('Failed to load submissions:', error);
      // Check if it's an admin access error
      if (error.message?.includes('Admin access required')) {
        setSubmissions([]);
      } else {
        setAlertModal({
          isOpen: true,
          title: 'Error',
          message: `Failed to load submissions: ${error.message}`,
          variant: 'error'
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const openApproveToolModal = (submission) => {
    const meta = submission.meta || {};
    setApproveIsPublic(!!meta.is_public);
    setApproveGroups(
      (meta.ad_group_names || []).map((name) => ({
        id: `name:${name}`,
        displayName: name,
      }))
    );
    setApproveEmails(
      (meta.emails || []).map((email) => ({
        id: `email:${email}`,
        email,
      }))
    );
    setApproveToolModal({ isOpen: true, submission });
  };

  const handleApprove = (submission) => {
    if (submission.submission_type === 'shared_tool') {
      openApproveToolModal(submission);
      return;
    }
    setConfirmModal({
      isOpen: true,
      title: 'Approve Submission',
      message: approveConfirmMessage(submission),
      onConfirm: () => executeApprove(submission)
    });
  };

  const executeApproveExternalTool = async () => {
    const submission = approveToolModal.submission;
    if (!submission) return;
    setApproveToolModal({ isOpen: false, submission: null });

    const sharingOverrides = {
      is_public: approveIsPublic,
      ad_group_names: approveGroups.map((g) => g.displayName || g.name).filter(Boolean),
      emails: approveEmails.map((u) => u.email).filter(Boolean),
    };
    await executeApprove(submission, sharingOverrides);
  };

  const executeApprove = async (submission, sharingOverrides = null) => {
    setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: null });
    
    try {
      setProcessing(submission.id);
      const result = await approveSubmission(submission.id, sharingOverrides);
      
      setAlertModal({
        isOpen: true,
        title: 'Approved',
        message: approveSuccessMessage(submission, result),
        variant: 'success'
      });
      
      // Refresh the list
      await fetchSubmissions();
    } catch (error) {
      setAlertModal({
        isOpen: true,
        title: 'Approval Failed',
        message: error.message,
        variant: 'error'
      });
    } finally {
      setProcessing(null);
    }
  };

  const handleReject = (submission) => {
    setRejectModal({ isOpen: true, submission });
    setRejectionReason('');
  };

  const executeReject = async () => {
    const submission = rejectModal.submission;
    if (!submission || !rejectionReason.trim()) return;
    
    setRejectModal({ isOpen: false, submission: null });
    
    try {
      setProcessing(submission.id);
      await rejectSubmission(submission.id, rejectionReason.trim());
      
      setAlertModal({
        isOpen: true,
        title: 'Rejected',
        message: `"${submission.marketplaceName}" has been rejected. The submitter will be notified.`,
        variant: 'warning'
      });
      
      // Refresh the list
      await fetchSubmissions();
    } catch (error) {
      setAlertModal({
        isOpen: true,
        title: 'Rejection Failed',
        message: error.message,
        variant: 'error'
      });
    } finally {
      setProcessing(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <div className="w-16 h-16 rounded-full bg-yellow-100 flex items-center justify-center mb-4">
          <span className="text-3xl">🔒</span>
        </div>
        <h3 className="text-lg font-medium text-gray-900 mb-2">
          Admin Access Required
        </h3>
        <p className="text-sm text-gray-600">
          Only administrators can view and manage marketplace submissions.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-400"></div>
      </div>
    );
  }

  if (submissions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mb-4">
          <span className="text-3xl">✓</span>
        </div>
        <h3 className="text-lg font-medium text-gray-900 mb-2">
          No Pending Submissions
        </h3>
        <p className="text-sm text-gray-600">
          All marketplace submissions have been reviewed.
        </p>
      </div>
    );
  }

  return (
    <>
      {reviewSubmission && (
        <SubmissionWorkflowReview
          submission={reviewSubmission}
          onClose={() => setReviewSubmission(null)}
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {submissions.map(submission => (
          <div
            key={submission.id}
            className="bg-white rounded-lg border border-gray-200 p-6 hover:shadow-lg transition-shadow"
          >
            {/* Header */}
            <div className="flex items-start justify-between mb-4">
              <div className="w-12 h-12 rounded-lg bg-orange-100 flex items-center justify-center">
                <span className="text-2xl">{submission.submission_type === 'shared_tool' ? '🔗' : '⏳'}</span>
              </div>
              <div className="flex gap-1.5">
                <span className={`px-2 py-1 text-xs font-medium rounded ${submissionTypeBadgeClass(submission.submission_type)}`}>
                  {submissionTypeLabel(submission.submission_type)}
                </span>
                <span className="px-2 py-1 text-xs font-medium bg-yellow-100 text-yellow-800 rounded">
                  Pending
                </span>
              </div>
            </div>

            {/* Title & Description */}
            <h3 className="text-lg font-semibold text-gray-900 mb-2">
              {submission.marketplaceName}
            </h3>
            <p className="text-sm text-gray-600 mb-3 line-clamp-2">
              {submission.marketplaceDescription || 'No description provided'}
            </p>

            {/* Metadata */}
            <div className="space-y-1 text-xs text-gray-500 mb-4">
              {submission.submission_type === 'shared_tool' && submission.meta?.url && (
                <div className="flex items-center gap-2">
                  <span>URL:</span>
                  <a href={submission.meta.url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-600 hover:underline truncate max-w-[200px]">
                    {submission.meta.url}
                  </a>
                </div>
              )}
              {submission.submission_type === 'shared_tool' && submission.meta?.is_public && (
                <div className="flex items-center gap-2">
                  <span>Visibility:</span>
                  <span className="font-medium text-green-700">Public (all users)</span>
                </div>
              )}
              {submission.submission_type === 'shared_tool' && submission.meta?.ad_group_names?.length > 0 && (
                <div className="flex items-center gap-2">
                  <span>AD Groups:</span>
                  <span className="font-medium text-gray-700">{submission.meta.ad_group_names.join(', ')}</span>
                </div>
              )}
              {submission.submission_type === 'shared_tool' && submission.meta?.emails?.length > 0 && (
                <div className="flex items-center gap-2">
                  <span>Emails:</span>
                  <span className="font-medium text-gray-700">{submission.meta.emails.join(', ')}</span>
                </div>
              )}
              {submission.submission_type === 'workflow_share_grant' && submission.meta && (
                <div className="flex items-center gap-2">
                  <span>Grant:</span>
                  <span className="font-medium text-gray-700">
                    {submission.meta.principalType === 'group'
                      ? `AD group — ${submission.meta.displayName || submission.meta.principalId}`
                      : `User — ${submission.meta.permission || 'read'}`}
                  </span>
                </div>
              )}
              {submission.submission_type === 'workflow_share_version' && (
                <div className="flex items-center gap-2">
                  <span>Type:</span>
                  <span className="font-medium text-gray-700">Republish for shared recipients</span>
                </div>
              )}
              {submission.submission_type !== 'shared_tool' && submission.workflowName && (
                <div className="flex items-center gap-2">
                  <span>Workflow:</span>
                  <span className="font-medium text-gray-700">{submission.workflowName}</span>
                </div>
              )}
              <div className="flex items-center gap-2">
                <span>Submitted by:</span>
                <span className="font-medium text-gray-700">
                  {submission.submitterName || submission.submitterEmail}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span>Date:</span>
                <span className="font-medium text-gray-700">
                  {new Date(submission.createdAt).toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric'
                  })}
                </span>
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-2">
              {submission.workflowId && submission.submission_type !== 'shared_tool' && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setReviewSubmission(submission)}
                  disabled={processing === submission.id}
                  className="w-full"
                >
                  Inspect &amp; test workflow
                </Button>
              )}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => handleApprove(submission)}
                  disabled={processing === submission.id}
                  className="flex-1 bg-green-600 hover:bg-green-700"
                >
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleReject(submission)}
                  disabled={processing === submission.id}
                  className="flex-1 text-red-600 border-red-300 hover:bg-red-50"
                >
                  Reject
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Approve external tool — admin can adjust sharing */}
      {approveToolModal.isOpen && approveToolModal.submission && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => setApproveToolModal({ isOpen: false, submission: null })}
        >
          <div
            className="bg-white border border-gray-200 rounded-xl p-6 max-w-lg w-full mx-4 shadow-2xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-1">
              Approve external tool
            </h3>
            <p className="text-sm text-gray-600 mb-4">
              {approveToolModal.submission.marketplaceName}
              {approveToolModal.submission.meta?.url && (
                <>
                  {' — '}
                  <a
                    href={approveToolModal.submission.meta.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline break-all"
                  >
                    {approveToolModal.submission.meta.url}
                  </a>
                </>
              )}
            </p>
            <p className="text-xs text-gray-500 mb-4">
              Adjust who can see this tool on the Storefront before approving. The submitter&apos;s
              choices are pre-filled below; you can change them.
            </p>

            <SharingTargetsFields
              variant="light"
              isPublic={approveIsPublic}
              onIsPublicChange={setApproveIsPublic}
              selectedGroups={approveGroups}
              onSelectedGroupsChange={setApproveGroups}
              selectedEmails={approveEmails}
              onSelectedEmailsChange={setApproveEmails}
            />

            <div className="flex gap-3 justify-end mt-6">
              <Button
                variant="outline"
                onClick={() => setApproveToolModal({ isOpen: false, submission: null })}
              >
                Cancel
              </Button>
              <Button
                onClick={executeApproveExternalTool}
                disabled={processing === approveToolModal.submission.id}
                className="bg-green-600 hover:bg-green-700"
              >
                {processing === approveToolModal.submission.id ? 'Approving...' : 'Approve & publish'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Reject Modal */}
      {rejectModal.isOpen && rejectModal.submission && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setRejectModal({ isOpen: false, submission: null })}>
          <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Reject Submission</h3>
            <p className="text-sm text-gray-600 mb-4">
              Provide a reason for rejecting "{rejectModal.submission.marketplaceName}". This will be shared with the submitter.
            </p>
            
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-900 mb-2">
                Rejection Reason <span className="text-red-500">*</span>
              </label>
              <textarea
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                placeholder="e.g., The workflow description needs more details about its use case..."
                rows={4}
                className="w-full px-4 py-2 bg-white border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-primary resize-none"
                autoFocus
              />
            </div>
            
            <div className="flex gap-3 justify-end">
              <Button
                onClick={executeReject}
                disabled={!rejectionReason.trim()}
                className="bg-red-600 hover:bg-red-700"
              >
                Reject
              </Button>
              <Button variant="outline" onClick={() => setRejectModal({ isOpen: false, submission: null })}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Alert Modal */}
      <AlertModal
        isOpen={alertModal.isOpen}
        title={alertModal.title}
        message={alertModal.message}
        variant={alertModal.variant}
        onClose={() => setAlertModal({ isOpen: false, title: '', message: '', variant: 'error' })}
      />
      
      {/* Confirm Modal */}
      <ConfirmModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        message={confirmModal.message}
        onConfirm={() => {
          confirmModal.onConfirm?.();
        }}
        onCancel={() => setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: null })}
        variant="default"
      />
    </>
  );
}
