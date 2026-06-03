import { useState, useEffect } from 'react';
import { useWorkflow } from '@/context/WorkflowContext';
import { listKnowledgeBases, createKnowledgeBase, deleteKnowledgeBase, getKnowledgeBase, toggleKBPin, updateKBLastAccessed } from '@/api/kb-client';
import Button from '../ui/Button';
import Input from '../ui/Input';
import Select from '../ui/Select';
import AlertModal from '../ui/AlertModal';
import ShareDialog from '../sharing/ShareDialog';

export default function KnowledgeBasesView({ showCreateModal, setShowCreateModal, knowledgeBases, setKnowledgeBases, onKBsChanged }) {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const [loading, setLoading] = useState(false); // Changed to false - parent handles fetching
  const [creating, setCreating] = useState(false);
  const [deletingKB, setDeletingKB] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Form state for creating KB (chunking is configured per-document at upload time)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    embedding_model: 'azure_ada_002',
  });

  // Modal state
  const [alertModal, setAlertModal] = useState({ isOpen: false, title: '', message: '', variant: 'error' });
  // Unified Share dialog state for KBs (AD group | person; marketplace tab is hidden for KBs)
  const [shareDialog, setShareDialog] = useState({ isOpen: false, resource: null });

  // Parent component handles initial fetch, but keep this function for fallback
  const fetchKnowledgeBases = async () => {
    try {
      setLoading(true);
      // List all knowledge bases (not filtered by session)
      const data = await listKnowledgeBases();
      setKnowledgeBases(data.knowledge_bases || []);
    } catch (error) {
      console.error('Failed to load knowledge bases:', error);
      setKnowledgeBases([]);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKB = async () => {
    if (!formData.name.trim()) return;

    try {
      setCreating(true);
      // Use 'default-session' as the session ID for knowledge bases
      const sessionId = state.selectedSession?.id || 'default-session';
      
      const payload = {
        session_id: sessionId,
        name: formData.name.trim(),
        description: formData.description.trim() || undefined,
        embedding_model: formData.embedding_model,
      };
      await createKnowledgeBase(payload);

      setShowCreateModal(false);
      setFormData({
        name: '',
        description: '',
        embedding_model: 'azure_ada_002',
      });
      // Refresh knowledge bases list
      if (onKBsChanged) {
        await onKBsChanged();
      } else {
        await fetchKnowledgeBases();
      }
    } catch (error) {
      console.error('Failed to create knowledge base:', error);
      setAlertModal({ 
        isOpen: true, 
        title: 'Creation Failed', 
        message: `Failed to create knowledge base: ${error.message}`, 
        variant: 'error' 
      });
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteKB = async () => {
    if (!deletingKB) return;

    try {
      setIsDeleting(true);
      await deleteKnowledgeBase(deletingKB.kb_id, false); // Soft delete
      // Refresh knowledge bases list
      if (onKBsChanged) {
        await onKBsChanged();
      } else {
        await fetchKnowledgeBases();
      }
      setDeletingKB(null);
    } catch (error) {
      console.error('Failed to delete knowledge base:', error);
      setAlertModal({ 
        isOpen: true, 
        title: 'Deletion Failed', 
        message: `Failed to delete knowledge base: ${error.message}`, 
        variant: 'error' 
      });
    } finally {
      setIsDeleting(false);
    }
  };

  const handleOpenKB = (kb) => {
    updateKBLastAccessed(kb.kb_id).catch(() => {});
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: {
        view: 'kb-detail',
        selectedKB: {
          ...kb,
          kb_id: kb.kb_id || kb.id,
          is_shared: kb.share_access === 'read',
          share_access: kb.share_access || (kb.is_shared ? 'read' : 'owner'),
        },
      },
    });
  };

  const handleToggleKBPin = async (e, kb) => {
    e.stopPropagation();
    try {
      await toggleKBPin(kb.kb_id, !kb.is_pinned);
      if (onKBsChanged) {
        await onKBsChanged();
      } else {
        await fetchKnowledgeBases();
      }
    } catch (error) {
      console.error('Failed to toggle KB pin:', error);
    }
  };

  const formatSize = (bytes) => {
    if (!bytes) return '0 B';
    const mb = bytes / (1024 * 1024);
    if (mb < 1) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${mb.toFixed(1)} MB`;
  };


  return (
    <div className="h-full">
      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-400"></div>
        </div>
      ) : knowledgeBases.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
            <span className="text-3xl">📚</span>
          </div>
          <h3 className="text-lg font-medium text-gray-900 mb-2">
            No Knowledge Bases yet
          </h3>
          <p className="text-sm text-gray-600 mb-6">
            Create your first knowledge base to store and search documents
          </p>
          {/* <Button onClick={() => setShowCreateModal(true)}>Create Knowledge Base</Button> */}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {knowledgeBases.map((kb) => {
            const isKbReadOnly = kb.share_access === 'read';
            const isKbShared = kb.share_access === 'read' || kb.share_access === 'write';
            return (
            <div
              key={kb.kb_id}
              onClick={() => handleOpenKB(kb)}
              className="bg-white rounded-lg border border-gray-200 p-6 hover:shadow-lg transition-shadow cursor-pointer group"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="w-12 h-12 rounded-lg bg-gray-100 flex items-center justify-center">
                  <svg className="w-7 h-7 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                  </svg>
                </div>
                <div className="flex items-center gap-1">
                  {!isKbShared && (
                    <button
                      onClick={(e) => handleToggleKBPin(e, kb)}
                      className={`w-7 h-7 rounded-md flex items-center justify-center transition-all ${
                        kb.is_pinned
                          ? 'text-blue-600 bg-blue-50 hover:bg-blue-100'
                          : 'text-gray-400 opacity-0 group-hover:opacity-100 hover:bg-gray-100 hover:text-gray-600'
                      }`}
                      title={kb.is_pinned ? 'Unpin' : 'Pin to top'}
                    >
                      <svg className="w-3.5 h-3.5" fill={kb.is_pinned ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
                      </svg>
                    </button>
                  )}
                  {isKbShared && (
                    <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded" title="Shared with you">
                      Shared
                    </span>
                  )}
                  {!isKbShared && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setShareDialog({
                          isOpen: true,
                          resource: { id: kb.kb_id, name: kb.name },
                        });
                      }}
                      className="group/share h-6 rounded-md opacity-0 group-hover:opacity-100 hover:bg-gray-100 text-gray-500 hover:text-gray-700 flex items-center justify-center transition-all overflow-hidden"
                      title="Share with an AD group or a person"
                    >
                      <span className="px-1.5 text-sm">🔗</span>
                      <span className="max-w-0 group-hover/share:max-w-xs transition-all duration-300 ease-in-out whitespace-nowrap overflow-hidden text-xs font-medium pr-0 group-hover/share:pr-1.5">
                        Share
                      </span>
                    </button>
                  )}
                  {!isKbShared && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeletingKB(kb);
                      }}
                      className="w-6 h-6 rounded-md opacity-0 group-hover:opacity-100 hover:bg-red-50 text-gray-400 hover:text-red-500 flex items-center justify-center transition-all text-xs"
                      title="Delete knowledge base"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                {kb.name}
              </h3>
              <p className="text-sm text-gray-600 mb-4 line-clamp-2">
                {kb.description || 'No description'}
              </p>

              <div className="space-y-2 mb-4 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Documents:</span>
                  <span className="font-medium text-gray-900">{kb.document_count || 0}</span>
                </div>
                <div className="flex justify-between">
                  <span>Chunks:</span>
                  <span className="font-medium text-gray-900">{kb.chunk_count || 0}</span>
                </div>
                <div className="flex justify-between">
                  <span>Size:</span>
                  <span className="font-medium text-gray-900">{formatSize(kb.total_size_mb * 1024 * 1024)}</span>
                </div>
              </div>

              <div className="text-xs text-gray-500 mb-4">
                {new Date(kb.created_at).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit'
                })}
              </div>

              <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleOpenKB(kb);
                  }}
                  className="flex-1 px-3 py-1.5 text-sm bg-white hover:bg-gray-50 text-gray-700 font-medium rounded-md border border-gray-300 transition-colors"
                >
                  {isKbReadOnly ? 'View' : 'Manage'}
                </button>
              </div>
            </div>
            );
          })}
        </div>
      )}

      {/* Create KB Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreateModal(false)}>
          <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Create Knowledge Base</h3>
            <p className="text-sm text-gray-600 mb-6">Configure your knowledge base for document storage and retrieval.</p>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-900 mb-2">
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({...formData, name: e.target.value})}
                  placeholder="e.g., Research Papers"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-900 mb-2">Description</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({...formData, description: e.target.value})}
                  placeholder="e.g., Academic research collection"
                  rows={2}
                  className="w-full px-4 py-2 bg-white border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-primary resize-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-900 mb-2">Embedding Model</label>
                <Select
                  value={formData.embedding_model}
                  onChange={(e) => setFormData({...formData, embedding_model: e.target.value})}
                >
                  <optgroup label="Azure (via GenAI Proxy)">
                    <option value="azure_ada_002">Azure Ada-002 (1536D)</option>
                    {/* <option value="azure_small">Azure Small (1536D)</option>
                    <option value="azure_large">Azure Large (3072D)</option>
                  </optgroup>
                  <optgroup label="Vertex AI (via GenAI Proxy)">
                    <option value="vertex_embedding_001">Gemini Embedding 001 (768D)</option>
                    <option value="vertex_embedding_005">Text Embedding 005 (768D)</option>
                    <option value="vertex_gemini_embedding">Gemini Embedding (768D)</option>
                  </optgroup>
                  <optgroup label="AWS Bedrock (via GenAI Proxy)">
                    <option value="bedrock_titan_v1">Titan Embed Text V1 (1536D)</option>
                    <option value="bedrock_titan_v2">Titan Embed Text V2 (1024D)</option>
                  </optgroup>
                  <optgroup label="OpenAI (Direct)">
                    <option value="openai_ada_002">OpenAI Ada-002 (1536D)</option>
                    <option value="openai_small">OpenAI Small (1536D)</option>
                    <option value="openai_large">OpenAI Large (3072D)</option> */}
                  </optgroup>
                </Select>
                <p className="text-xs text-gray-600 mt-1">Choose embedding model (must match for indexing & querying)</p>
              </div>

              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-2">
                <p className="text-xs text-gray-600">
                  Chunking strategy and metadata inference are configured per-document at upload time, allowing you to tailor settings for each file.
                </p>
                <p className="text-xs text-gray-600">
                  CSV and Excel files are loaded as queryable database tables with a schema review step.
                </p>
              </div>
            </div>

            <div className="flex gap-3 justify-end mt-6">
              <Button onClick={handleCreateKB} disabled={!formData.name.trim() || creating}>
                {creating ? 'Creating...' : 'Create Knowledge Base'}
              </Button>
              <Button variant="outline" onClick={() => setShowCreateModal(false)} disabled={creating}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deletingKB && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-md w-full mx-4 shadow-xl">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">Delete Knowledge Base</h3>
            <p className="text-sm text-gray-600 mb-4">
              Are you sure you want to delete <strong className="text-gray-900">{deletingKB.name}</strong>?
              All documents and chunks will be removed.
            </p>
            <div className="flex gap-3">
              <Button
                onClick={handleDeleteKB}
                disabled={isDeleting}
                className="flex-1 bg-red-600 hover:bg-red-700"
              >
                {isDeleting ? 'Deleting...' : 'Delete'}
              </Button>
              <Button
                variant="outline"
                onClick={() => setDeletingKB(null)}
                disabled={isDeleting}
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

      {/* Unified Share dialog (KBs only support AD group / person — marketplace
          tab is hidden because KBs go public via the workflow approval flow). */}
      <ShareDialog
        resourceType="kb"
        resource={shareDialog.resource}
        isOpen={shareDialog.isOpen}
        onClose={() => setShareDialog({ isOpen: false, resource: null })}
        onChanged={() => {
          if (onKBsChanged) onKBsChanged();
          else fetchKnowledgeBases();
        }}
      />
    </div>
  );
}

