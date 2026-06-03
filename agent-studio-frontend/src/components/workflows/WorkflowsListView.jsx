import { useState, useEffect } from 'react';
import { listWorkflows, updateWorkflow, deleteWorkflow } from '@/api/client';
import { useWorkflow } from '@/context/WorkflowContext';
import Button from '../ui/Button';
import AlertModal from '../ui/AlertModal';

export default function WorkflowsListView() {
  const { dispatch, ACTIONS } = useWorkflow();
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingWorkflow, setEditingWorkflow] = useState(null);
  const [editedName, setEditedName] = useState('');
  const [deletingWorkflow, setDeletingWorkflow] = useState(null);
  const [isUpdating, setIsUpdating] = useState(false);
  
  // Modal state
  const [alertModal, setAlertModal] = useState({ isOpen: false, title: '', message: '', variant: 'error' });

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listWorkflows();
      setWorkflows(data.workflows);
    } catch (err) {
      console.error('Error loading workflows:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  const getNodeCount = (workflow) => {
    if (!workflow.nodes) return 0;
    try {
      const nodes = JSON.parse(workflow.nodes);
      return Array.isArray(nodes) ? nodes.length : 0;
    } catch {
      return 0;
    }
  };

  const handleSelectWorkflow = (workflow) => {
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: { view: 'chat', selectedWorkflow: workflow },
    });
  };

  const handleEditClick = (e, workflow) => {
    e.stopPropagation();
    setEditingWorkflow(workflow);
    setEditedName(workflow.name);
  };

  const handleSaveEdit = async () => {
    if (!editedName.trim() || !editingWorkflow) return;
    
    try {
      setIsUpdating(true);
      await updateWorkflow(editingWorkflow.id, { name: editedName.trim() });
      await loadWorkflows(); // Reload to get updated data
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
      await loadWorkflows(); // Reload to get updated list
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

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-60px)] max-w-3xl mx-auto w-full px-4 sm:px-6">
        <div className="animate-spin w-12 h-12 border-4 border-primary border-t-transparent rounded-full mb-4"></div>
        <p className="text-muted-foreground">Loading workflows...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-60px)] max-w-3xl mx-auto w-full px-4 sm:px-6">
        <div className="text-center space-y-4">
          <div className="w-16 h-16 mx-auto bg-red-500/10 rounded-full flex items-center justify-center text-3xl">
            ⚠️
          </div>
          <h2 className="text-xl font-bold text-foreground">Error Loading Workflows</h2>
          <p className="text-muted-foreground">{error}</p>
          <Button onClick={loadWorkflows}>Retry</Button>
        </div>
      </div>
    );
  }

  if (workflows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-60px)] max-w-3xl mx-auto w-full px-4 sm:px-6">
        <div className="text-center space-y-4">
          <div className="w-24 h-24 mx-auto bg-secondary rounded-2xl flex items-center justify-center text-5xl">
            📋
          </div>
          <h2 className="text-2xl font-bold text-foreground">No Workflows Yet</h2>
          <p className="text-muted-foreground">
            Create your first workflow in the builder to get started
          </p>
          <Button onClick={() => dispatch({ type: ACTIONS.NAVIGATE, payload: { view: 'builder' } })}>
            Go to Builder
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-60px)] overflow-y-auto">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Workflows</h1>
            <p className="text-muted-foreground">
              {workflows.length} workflow{workflows.length !== 1 ? 's' : ''} available
            </p>
          </div>
          <Button variant="outline" onClick={loadWorkflows}>
            <span className="mr-2">🔄</span>
            Refresh
          </Button>
        </div>

        {/* Workflows Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {workflows.map((workflow) => (
            <div
              key={workflow.id}
              className="group bg-surface border border-border rounded-xl p-6 hover:border-primary hover:shadow-lg transition-all duration-200 cursor-pointer"
              onClick={() => handleSelectWorkflow(workflow)}
            >
              {/* Header */}
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-semibold text-foreground truncate mb-1">
                    {workflow.name}
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    ID: {workflow.id.substring(0, 8)}...
                  </p>
                </div>
                <div className="flex gap-1 ml-2 flex-shrink-0">
                  <button
                    onClick={(e) => handleEditClick(e, workflow)}
                    className="w-8 h-8 rounded-lg bg-secondary hover:bg-secondary/80 text-muted-foreground hover:text-foreground flex items-center justify-center transition-all duration-200"
                    title="Edit workflow name"
                  >
                    ✏️
                  </button>
                  <button
                    onClick={(e) => handleDeleteClick(e, workflow)}
                    className="w-8 h-8 rounded-lg bg-secondary hover:bg-red-500/10 text-muted-foreground hover:text-red-500 flex items-center justify-center transition-all duration-200"
                    title="Delete workflow"
                  >
                    🗑️
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSelectWorkflow(workflow);
                    }}
                    className="w-10 h-10 rounded-lg bg-primary/10 hover:bg-primary hover:text-white text-primary flex items-center justify-center transition-all duration-200"
                    title="Chat with workflow"
                  >
                    💬
                  </button>
                </div>
              </div>

              {/* Metadata */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Nodes:</span>
                  <span className="font-medium text-foreground">{getNodeCount(workflow)}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Status:</span>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    workflow.active
                      ? 'bg-gray-500/10 text-gray-700'
                      : 'bg-gray-500/10 text-gray-600'
                  }`}>
                    {workflow.active ? 'Active' : 'Inactive'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm pt-2 border-t border-border">
                  <span className="text-muted-foreground">Updated:</span>
                  <span className="text-xs text-muted-foreground">
                    {formatDate(workflow.updatedAt)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Edit Name Modal */}
      {editingWorkflow && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-surface border border-border rounded-xl p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-lg font-semibold text-foreground mb-4">Edit Workflow Name</h3>
            <input
              type="text"
              value={editedName}
              onChange={(e) => setEditedName(e.target.value)}
              placeholder="Workflow name"
              className="w-full px-4 py-2 text-sm bg-background border border-border rounded-lg focus:outline-none focus:border-primary text-foreground placeholder:text-muted-foreground mb-4"
              autoFocus
              onKeyPress={(e) => {
                if (e.key === 'Enter') handleSaveEdit();
              }}
            />
            <div className="flex gap-3">
              <Button
                onClick={handleSaveEdit}
                disabled={!editedName.trim() || isUpdating}
                className="flex-1"
              >
                {isUpdating ? 'Saving...' : 'Save'}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setEditingWorkflow(null);
                  setEditedName('');
                }}
                disabled={isUpdating}
              >
                Cancel
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
    </div>
  );
}


