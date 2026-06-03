import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useWorkflow } from '@/context/WorkflowContext';
import { useAuth } from '@/context/AuthContext';
import { listWorkflows, createWorkflow, updateWorkflow, deleteWorkflow, toggleWorkflowPin, updateWorkflowLastAccessed, duplicateWorkflow } from '@/api/client';
import { listKnowledgeBases } from '@/api/kb-client';
// unshareWorkflowFromMarketplace is invoked from inside ShareDialog.
import { fetchMarketplaceWorkflows } from '@/api/marketplace';
// submitWorkflowForApproval is now invoked from inside ShareDialog (the
// workspace no longer owns the submit modal).
import { fetchMySubmissions, importMarketplaceWorkflow, fetchPendingSubmissions } from '@/api/approval';
import Button from '../ui/Button';
import AlertModal from '../ui/AlertModal';
import ConfirmModal from '../ui/ConfirmModal';
import KnowledgeBasesView from '../knowledgebases/KnowledgeBasesView';
import ApprovalView from './ApprovalView';
import WorkflowDescriptionViewer from '../ui/WorkflowDescriptionViewer';
import ShareDialog from '../sharing/ShareDialog';
import SharedWithMeView from '../sharing/SharedWithMeView';

export default function WorkspaceView() {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const { user } = useAuth();
  // activeTab is kept in WorkflowContext so it survives refreshes and is
  // restored when the user navigates back to the workspace.
  const activeTab = state.activeTab || 'marketplace';
  const setActiveTab = (tab) => dispatch({ type: ACTIONS.SET_ACTIVE_TAB, payload: tab });
  const [publishedWorkflows, setPublishedWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newWorkflowName, setNewWorkflowName] = useState('');
  const [newWorkflowDescription, setNewWorkflowDescription] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState(null);
  const [editedName, setEditedName] = useState('');
  const [deletingWorkflow, setDeletingWorkflow] = useState(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [showCreateKBModal, setShowCreateKBModal] = useState(false);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [marketplaceWorkflows, setMarketplaceWorkflows] = useState([]);
  const [pendingSubmissionsCount, setPendingSubmissionsCount] = useState(0);
  const [mySubmissions, setMySubmissions] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const searchTimerRef = useRef(null);
  
  // Check if user is admin
  const isAdmin = user?.roleSlug?.toLowerCase().includes('admin') || false;
  
  // Modal states
  const [alertModal, setAlertModal] = useState({ isOpen: false, title: '', message: '', variant: 'error' });
  const [confirmModal, setConfirmModal] = useState({ isOpen: false, title: '', message: '', onConfirm: null });
  const [descriptionViewer, setDescriptionViewer] = useState({ isOpen: false, data: null });
  // Unified Share dialog (marketplace | AD group | person)
  const [shareDialog, setShareDialog] = useState({ isOpen: false, resource: null });

  // Reset search and reload when changing tabs
  useEffect(() => {
    setSearchQuery('');
    fetchWorkflows();
    fetchKnowledgeBases();
    if (activeTab === 'marketplace') {
      fetchMarketplace();
    }
    if (activeTab === 'approval' && isAdmin) {
      fetchPendingCount();
    }
    fetchUserSubmissions();
  }, [activeTab, isAdmin]);

  // Fetch pending submissions count for admin badge
  useEffect(() => {
    if (isAdmin) {
      fetchPendingCount();
    }
  }, [isAdmin]);

  const fetchWorkflows = async (search = '') => {
    try {
      setLoading(true);
      const searchOpt = search ? { search } : {};
      const data = await listWorkflows(1, 50, searchOpt);
      setPublishedWorkflows(data.items || data.workflows || []);
    } catch (error) {
      console.error('Failed to load workflows:', error);
      setPublishedWorkflows([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchKnowledgeBases = async (search = '') => {
    try {
      const data = await listKnowledgeBases(null, search || null);
      setKnowledgeBases(data.knowledge_bases || []);
    } catch (error) {
      console.error('Failed to load knowledge bases:', error);
      setKnowledgeBases([]);
    }
  };

  const fetchMarketplace = async (search = '') => {
    try {
      setLoading(true);
      const data = await fetchMarketplaceWorkflows(0, 100, search || null);
      setMarketplaceWorkflows(data.items || []);
    } catch (error) {
      console.error('Failed to load marketplace workflows:', error);
      setMarketplaceWorkflows([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSearchChange = useCallback((value) => {
    setSearchQuery(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      if (activeTab === 'workflows') {
        fetchWorkflows(value);
      } else if (activeTab === 'knowledge-bases') {
        fetchKnowledgeBases(value);
      } else if (activeTab === 'marketplace') {
        fetchMarketplace(value);
      }
    }, 300);
  }, [activeTab]);

  const fetchPendingCount = async () => {
    if (!isAdmin) return;
    try {
      const data = await fetchPendingSubmissions(1, 1);
      setPendingSubmissionsCount(data.total || 0);
    } catch (error) {
      console.error('Failed to fetch pending count:', error);
      setPendingSubmissionsCount(0);
    }
  };

  const fetchUserSubmissions = async () => {
    try {
      const data = await fetchMySubmissions(1, 100);
      setMySubmissions(data.items || []);
    } catch (error) {
      console.error('Failed to fetch user submissions:', error);
      setMySubmissions([]);
    }
  };

  const submissionByWorkflowId = useMemo(() => {
    const map = new Map();
    for (const s of mySubmissions) {
      map.set(s.workflowId, { status: s.status, rejectionReason: s.rejectionReason });
    }
    return map;
  }, [mySubmissions]);

  const getWorkflowSubmissionStatus = (workflowId) => submissionByWorkflowId.get(workflowId) || null;

  const getDetailedDescription = (workflow) => {
    try {
      const meta = workflow.meta ? JSON.parse(workflow.meta) : null;
      return meta?.detailedDescription || null;
    } catch {
      return null;
    }
  };

  const handleShowDescription = (e, workflow) => {
    e.stopPropagation();
    const desc = getDetailedDescription(workflow);
    setDescriptionViewer({ isOpen: true, data: desc });
  };

  const handleCreateNew = () => {
    if (activeTab === 'knowledge-bases') {
      setShowCreateKBModal(true);
    } else {
    // Show modal to get workflow name and description
    setNewWorkflowName('');
    setNewWorkflowDescription('');
    setShowCreateModal(true);
    }
  };

  const handleCreateWorkflow = async () => {
    if (!newWorkflowName.trim()) return;
    
    try {
      setIsCreating(true);
      
      // Create the workflow as a draft in the database
      const newWorkflow = await createWorkflow({
        name: newWorkflowName.trim(),
        description: newWorkflowDescription.trim() || 'New workflow',
        config: {
          nodes: [],
          connections: []
        },
        active: false
      });
      
      // Close modal
      setShowCreateModal(false);
      
      // Clear canvas and navigate to builder with the new workflow.
      // NAVIGATE (instead of SET_VIEW) records the current workspace tab so
      // pressing Back in the builder returns the user to exactly here.
      dispatch({ type: ACTIONS.CLEAR_CANVAS });
      dispatch({
        type: ACTIONS.NAVIGATE,
        payload: { view: 'builder', selectedWorkflow: newWorkflow },
      });
      
      // Refresh the workflows list
      await fetchWorkflows();
    } catch (error) {
      console.error('Failed to create workflow:', error);
      setAlertModal({ 
        isOpen: true, 
        title: 'Creation Failed', 
        message: 'Failed to create workflow. Please try again.', 
        variant: 'error' 
      });
    } finally {
      setIsCreating(false);
    }
  };

  const handleEditWorkflow = (workflow) => {
    updateWorkflowLastAccessed(workflow.id).catch(() => {});
    const shareAccess =
      workflow.shareAccess
      || (workflow.permission === 'write' ? 'write' : workflow.permission === 'read' ? 'read' : null);
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: {
        view: 'builder',
        selectedWorkflow: { ...workflow, shareAccess },
      },
    });
  };

  const handleChatWorkflow = (workflow) => {
    updateWorkflowLastAccessed(workflow.id).catch(() => {});
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: { view: 'chat', selectedWorkflow: workflow },
    });
  };

  const handleTogglePin = async (e, workflow) => {
    e.stopPropagation();
    try {
      await toggleWorkflowPin(workflow.id, !workflow.isPinned);
      await fetchWorkflows(searchQuery);
    } catch (error) {
      console.error('Failed to toggle pin:', error);
    }
  };

  const handleEditNameClick = (e, workflow) => {
    e.stopPropagation();
    setEditingWorkflow(workflow);
    setEditedName(workflow.name);
  };

  const handleSaveEdit = async () => {
    if (!editedName.trim() || !editingWorkflow) {
      setEditingWorkflow(null);
      setEditedName('');
      return;
    }
    
    // Don't save if name hasn't changed
    if (editedName.trim() === editingWorkflow.name) {
      setEditingWorkflow(null);
      setEditedName('');
      return;
    }
    
    try {
      setIsUpdating(true);
      await updateWorkflow(editingWorkflow.id, { name: editedName.trim() });
      await fetchWorkflows(); // Reload to get updated data
      setEditingWorkflow(null);
      setEditedName('');
    } catch (err) {
      console.error('Failed to update workflow:', err);
      setAlertModal({ 
        isOpen: true, 
        title: 'Update Failed', 
        message: `Failed to update workflow: ${err.message}`, 
        variant: 'error' 
      });
      setEditingWorkflow(null);
      setEditedName('');
    } finally {
      setIsUpdating(false);
    }
  };

  const handleDeleteClick = (e, workflow) => {
    e.stopPropagation();
    setDeletingWorkflow(workflow);
  };

  const handleConfirmDelete = async () => {
    if (!deletingWorkflow) return;
    
    try {
      setIsUpdating(true);
      await deleteWorkflow(deletingWorkflow.id, false); // Archive, not permanent delete
      await fetchWorkflows(); // Reload to get updated list
      setDeletingWorkflow(null);
    } catch (err) {
      console.error('Failed to delete workflow:', err);
      setAlertModal({ 
        isOpen: true, 
        title: 'Deletion Failed', 
        message: `Failed to delete workflow: ${err.message}`, 
        variant: 'error' 
      });
    } finally {
      setIsUpdating(false);
    }
  };

  const handleDuplicateWorkflow = async (e, workflow) => {
    e.stopPropagation();
    try {
      setIsUpdating(true);
      await duplicateWorkflow(workflow);
      await fetchWorkflows();
      setAlertModal({
        isOpen: true,
        title: 'Duplicated',
        message: `"${workflow.name}" has been duplicated.`,
        variant: 'success',
      });
    } catch (err) {
      console.error('Failed to duplicate workflow:', err);
      setAlertModal({
        isOpen: true,
        title: 'Duplication Failed',
        message: `Failed to duplicate workflow: ${err.message}`,
        variant: 'error',
      });
    } finally {
      setIsUpdating(false);
    }
  };

  // Get workflows based on active tab
  const displayedWorkflows = activeTab === 'workflows' ? publishedWorkflows : [];

  const tabs = [
    { id: 'workflows', label: 'Workflows', count: publishedWorkflows.length },
    { id: 'knowledge-bases', label: 'Knowledge Bases', count: knowledgeBases.length },
    { id: 'shared-with-me', label: 'Shared with me' },
    { id: 'marketplace', label: 'Marketplace', count: marketplaceWorkflows.length },
    ...(isAdmin ? [{ id: 'approval', label: 'Approval', count: pendingSubmissionsCount, highlight: pendingSubmissionsCount > 0 }] : [])
  ];

  // Open the unified Share dialog (marketplace | AD group | person).
  const handleOpenShareDialog = (e, workflow) => {
    e?.stopPropagation?.();
    // Embed the latest submission status so the dialog can render
    // "Pending approval" / "Resubmit" instead of the default form.
    const submissionStatus = getWorkflowSubmissionStatus(workflow.id) || null;
    setShareDialog({
      isOpen: true,
      resource: { ...workflow, _submissionStatus: submissionStatus },
    });
  };

  const handleCloseShareDialog = () => {
    setShareDialog({ isOpen: false, resource: null });
  };

  const handleShareDialogChanged = async () => {
    // Refresh everything that might have changed:
    //   - workflow list (isPublic toggled by marketplace remove)
    //   - submission list (new pending submission created)
    //   - marketplace tab cards
    await Promise.all([
      fetchWorkflows(),
      fetchUserSubmissions(),
      fetchMarketplace(),
    ]);
  };

  const handleImportFromMarketplace = async (workflow) => {
    try {
      setIsUpdating(true);
      const importedWorkflow = await importMarketplaceWorkflow(workflow.id);
      await fetchWorkflows();
      // Switch to workflows tab so user can see the imported workflow
      setActiveTab('workflows');
      setAlertModal({
        isOpen: true,
        title: 'Imported Successfully',
        message: `"${importedWorkflow.name}" has been imported to your Workflows.`,
        variant: 'success'
      });
    } catch (error) {
      console.error('Failed to import workflow:', error);
      setAlertModal({ 
        isOpen: true, 
        title: 'Import Failed', 
        message: `Failed to import workflow: ${error.message}`, 
        variant: 'error' 
      });
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <div className="h-full w-full bg-gray-50 overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white">
        <div className="px-6 py-6">
          <div className="mb-6">
            <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-2xl font-bold text-foreground">Home</h1>
              <p className="text-sm text-muted-foreground mt-1">
                  Build chat agents, manage knowledge bases, and explore templates
              </p>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex items-center justify-between">
          <div className="flex gap-1">
            {tabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                  activeTab === tab.id
                    ? 'bg-gray-100 text-foreground border-b-2 border-primary'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label}
                {tab.count > 0 && (
                  <span className={`ml-2 px-2 py-0.5 text-xs rounded-full ${
                    tab.highlight 
                      ? 'bg-orange-500 text-white animate-pulse' 
                      : 'bg-gray-200'
                  }`}>
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
            </div>
            {/* Create button - shown only for workflows, drafts, and knowledge bases */}
            {(activeTab === 'workflows' || activeTab === 'knowledge-bases') && (
              <Button onClick={handleCreateNew} className="flex items-center gap-2">
                <span>+</span>
                <span>Create</span>
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Search Bar */}
      {activeTab !== 'approval' && (
        <div className="px-6 pt-4">
          <div className="relative max-w-md">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder={`Search ${activeTab === 'knowledge-bases' ? 'knowledge bases' : activeTab}...`}
              className="w-full pl-10 pr-4 py-2 text-sm bg-white border border-gray-200 rounded-lg text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
            />
            {searchQuery && (
              <button
                onClick={() => handleSearchChange('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Content Area */}
      <div className="px-6 py-4 h-[calc(100%-220px)] overflow-y-auto">
        {activeTab === 'approval' ? (
          <ApprovalView 
            isAdmin={isAdmin}
            onRefresh={fetchPendingCount}
          />
        ) : activeTab === 'knowledge-bases' ? (
          <KnowledgeBasesView 
            showCreateModal={showCreateKBModal} 
            setShowCreateModal={setShowCreateKBModal}
            knowledgeBases={knowledgeBases}
            setKnowledgeBases={setKnowledgeBases}
            onKBsChanged={fetchKnowledgeBases}
          />
        ) : activeTab === 'shared-with-me' ? (
          <SharedWithMeView
            onOpenWorkflow={(wf) => handleEditWorkflow(wf)}
            onChatWorkflow={(wf) => handleChatWorkflow(wf)}
            onOpenKB={(kb) => {
              // KBDetailView expects `kb_id` and `is_shared`; the shared-with-me
              // backend response uses `id`. Normalize the shape so the existing
              // detail view works without modification.
              dispatch({
                type: ACTIONS.NAVIGATE,
                payload: {
                  view: 'kb-detail',
                  selectedKB: {
                    ...kb,
                    kb_id: kb.id,
                    is_shared: kb.permission === 'read',
                    share_access: kb.permission || 'read',
                  },
                },
              });
            }}
          />
        ) : loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-400"></div>
          </div>
        ) : activeTab === 'marketplace' ? (
          // Marketplace Workflows
          marketplaceWorkflows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-center">
              <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
                <span className="text-3xl">🛒</span>
              </div>
              <h3 className="text-lg font-medium text-foreground mb-2">
                No workflows in marketplace
              </h3>
              <p className="text-sm text-muted-foreground">
                Share your workflows to make them available to everyone
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {marketplaceWorkflows.map(workflow => (
                <div
                  key={workflow.id}
                  className="bg-white rounded-lg border border-gray-200 p-6 hover:shadow-lg transition-shadow group"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="w-12 h-12 rounded-lg bg-gray-200 flex items-center justify-center">
                      <svg className="w-7 h-7 text-gray-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                      </svg>
                    </div>
                    {getDetailedDescription(workflow) && (
                      <button
                        onClick={(e) => handleShowDescription(e, workflow)}
                        className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 flex items-center justify-center transition-colors text-sm font-bold"
                        title="View workflow guide"
                      >
                        ?
                      </button>
                    )}
                  </div>
                  <h3 className="text-lg font-semibold text-foreground mb-2">
                    {workflow.marketplaceName || workflow.name}
                  </h3>
                  <p className="text-sm text-muted-foreground mb-4">
                    {workflow.marketplaceDescription || workflow.description || 'No description'}
                  </p>
                  <div className="flex items-center justify-between text-xs text-muted-foreground mb-4">
                    <span>
                      {new Date(workflow.updatedAt || workflow.createdAt).toLocaleDateString('en-US', {
                        month: 'short',
                        day: 'numeric'
                      })}
                    </span>
                  </div>
                  <div className="flex flex-col gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      size="sm"
                      onClick={() => handleImportFromMarketplace(workflow)}
                      disabled={isUpdating}
                      className="w-full"
                    >
                      Import to Workflows
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : displayedWorkflows.length === 0 ? (
          // Empty State
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
              <span className="text-3xl">📋</span>
            </div>
            <h3 className="text-lg font-medium text-foreground mb-2">
              No {activeTab} yet
            </h3>
            <p className="text-sm text-muted-foreground mb-6">
              Create and publish workflows to see them here
            </p>
            {/* <Button onClick={handleCreateNew}>Create New Workflow</Button> */}
          </div>
        ) : (
          // Workflow Cards
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {displayedWorkflows.map(workflow => (
              <div
                key={workflow.id}
                className="bg-white rounded-lg border border-border p-6 hover:shadow-lg transition-shadow group"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="w-12 h-12 rounded-lg bg-gray-200 flex items-center justify-center">
                    <img src="/icons/workflow.svg" alt="Workflow" className="w-7 h-7 text-gray-700" />
                  </div>
                  <div className="flex gap-1 items-center">
                    <button
                      onClick={(e) => handleTogglePin(e, workflow)}
                      className={`w-8 h-8 rounded-md flex items-center justify-center transition-all ${
                        workflow.isPinned
                          ? 'text-blue-600 bg-blue-50 hover:bg-blue-100'
                          : 'text-gray-400 opacity-0 group-hover:opacity-100 hover:bg-gray-100 hover:text-gray-600'
                      }`}
                      title={workflow.isPinned ? 'Unpin' : 'Pin to top'}
                    >
                      <svg className="w-4 h-4" fill={workflow.isPinned ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
                      </svg>
                    </button>
                    {getDetailedDescription(workflow) && (
                      <button
                        onClick={(e) => handleShowDescription(e, workflow)}
                        className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 flex items-center justify-center transition-colors text-sm font-bold"
                        title="View workflow guide"
                      >
                        ?
                      </button>
                    )}
                    {(() => {
                      const submissionStatus = getWorkflowSubmissionStatus(workflow.id);
                      // Show a small pending pill when a marketplace submission is
                      // awaiting admin review — the Share dialog itself also
                      // surfaces this, but the pill keeps the existing UX cue on
                      // the card.
                      if (submissionStatus?.status === 'pending' && !workflow.isPublic) {
                        return (
                          <span
                            className="h-8 px-3 flex items-center text-xs font-medium text-yellow-600 bg-yellow-50 rounded-md cursor-pointer"
                            title="Click to view submission status"
                            onClick={(e) => handleOpenShareDialog(e, workflow)}
                          >
                            ⏳ Pending Approval
                          </span>
                        );
                      }
                      const isShared = workflow.isPublic;
                      return (
                        <button
                          onClick={(e) => handleOpenShareDialog(e, workflow)}
                          className={`group/share h-8 rounded-md opacity-0 group-hover:opacity-100 flex items-center justify-center transition-all overflow-hidden ${
                            isShared
                              ? 'hover:bg-blue-50 text-blue-600'
                              : 'hover:bg-gray-200 text-gray-700'
                          }`}
                          title={
                            isShared
                              ? 'Manage sharing (currently in marketplace)'
                              : 'Share with marketplace, an AD group, or a person'
                          }
                        >
                          <span className="px-2 text-base">{isShared ? '🌐' : '🔗'}</span>
                          <span className="max-w-0 group-hover/share:max-w-xs transition-all duration-300 ease-in-out whitespace-nowrap overflow-hidden text-sm font-medium pr-0 group-hover/share:pr-2">
                            Share
                          </span>
                        </button>
                      );
                    })()}
                    <button
                      onClick={(e) => handleDuplicateWorkflow(e, workflow)}
                      className="w-8 h-8 rounded-md opacity-0 group-hover:opacity-100 hover:bg-blue-50 text-gray-400 hover:text-blue-500 flex items-center justify-center transition-all text-xs"
                      title="Duplicate workflow"
                      disabled={isUpdating}
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </button>
                    <button
                      onClick={(e) => handleDeleteClick(e, workflow)}
                      className="w-8 h-8 rounded-md opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-400 hover:text-red-500 flex items-center justify-center transition-all text-xs"
                      title="Delete workflow"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
                {editingWorkflow?.id === workflow.id ? (
                  <input
                    type="text"
                    value={editedName}
                    onChange={(e) => setEditedName(e.target.value)}
                    onBlur={handleSaveEdit}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleSaveEdit();
                      } else if (e.key === 'Escape') {
                        setEditingWorkflow(null);
                        setEditedName('');
                      }
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="text-lg font-semibold text-foreground mb-2 w-full px-2 py-1 bg-background border border-primary rounded focus:outline-none focus:ring-2 focus:ring-primary"
                    autoFocus
                  />
                ) : (
                  <h3 
                    className="text-lg font-semibold text-foreground mb-2 px-2 py-1 rounded cursor-text hover:text-primary hover:bg-gray-50 transition-colors"
                    onClick={(e) => handleEditNameClick(e, workflow)}
                    title="Click to rename"
                  >
                    {workflow.name || 'New workflow'}
                  </h3>
                )}
                <p className="text-sm text-muted-foreground mb-4">
                  {workflow.description || ''}
                </p>
                <div className="flex items-center justify-between text-xs text-muted-foreground mb-4">
                  <span>
                    {new Date(workflow.updatedAt || workflow.createdAt).toLocaleDateString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </span>
                  {workflow.createdByName && (
                    <span>{workflow.createdByName}</span>
                  )}
                </div>
                <div className="space-y-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <div className="flex gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleChatWorkflow(workflow);
                      }}
                      className="flex-1 px-3 py-1.5 text-sm bg-gray-700 text-white font-medium rounded-md hover:bg-gray-800 transition-colors"
                    >
                      Launch
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleEditWorkflow(workflow);
                      }}
                      className="flex-1 px-3 py-1.5 text-sm bg-white hover:bg-gray-50 text-gray-700 font-medium rounded-md border border-gray-300 transition-colors"
                    >
                      Edit
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Workflow Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreateModal(false)}>
          <div className="bg-surface border border-border rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-foreground mb-4">Create New Workflow</h3>
            <p className="text-sm text-muted-foreground mb-4">Give your workflow a name and description.</p>
            
            <div className="space-y-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-foreground mb-2">
                  Workflow Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={newWorkflowName}
                  onChange={(e) => setNewWorkflowName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newWorkflowName.trim()) {
                      handleCreateWorkflow();
                    } else if (e.key === 'Escape') {
                      setShowCreateModal(false);
                    }
                  }}
                  placeholder="e.g., Customer Support Automation"
                  autoFocus
                  className="w-full px-4 py-2 bg-background border border-border rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-foreground mb-2">
                  Description (optional)
                </label>
                <textarea
                  value={newWorkflowDescription}
                  onChange={(e) => setNewWorkflowDescription(e.target.value)}
                  placeholder="e.g., Automated workflow for handling customer inquiries and routing to appropriate agents"
                  rows={3}
                  className="w-full px-4 py-2 bg-background border border-border rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-primary resize-none"
                />
              </div>
            </div>
            
            <div className="flex gap-3 justify-end">
              <Button variant="outline" onClick={() => setShowCreateModal(false)} disabled={isCreating}>
                Cancel
              </Button>
              <Button onClick={handleCreateWorkflow} disabled={!newWorkflowName.trim() || isCreating}>
                {isCreating ? 'Creating...' : 'Create Workflow'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deletingWorkflow && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-surface border border-border rounded-xl p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-lg font-semibold text-foreground mb-3">Delete Workflow</h3>
            <p className="text-sm text-muted-foreground mb-4">
              Are you sure you want to delete <strong className="text-foreground">{deletingWorkflow.name}</strong>? 
              This action will archive the workflow.
            </p>
            <div className="flex gap-3">
              <Button
                onClick={handleConfirmDelete}
                disabled={isUpdating}
                className="flex-1 bg-red-600 hover:bg-red-700"
              >
                {isUpdating ? 'Deleting...' : 'Delete'}
              </Button>
              <Button
                variant="outline"
                onClick={() => setDeletingWorkflow(null)}
                disabled={isUpdating}
              >
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
          setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: null });
        }}
        onCancel={() => setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: null })}
        variant="default"
      />

      {/* Workflow Description Viewer */}
      <WorkflowDescriptionViewer
        isOpen={descriptionViewer.isOpen}
        onClose={() => setDescriptionViewer({ isOpen: false, data: null })}
        data={descriptionViewer.data}
      />

      {/* Unified Share dialog (marketplace | AD group | person) */}
      <ShareDialog
        resourceType="workflow"
        resource={shareDialog.resource}
        isOpen={shareDialog.isOpen}
        onClose={handleCloseShareDialog}
        onChanged={handleShareDialogChanged}
      />
    </div>
  );
}

