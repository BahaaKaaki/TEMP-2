import { useState, useEffect } from 'react';
import { APP_DATA } from '@/data/appData';
import { useWorkflow } from '@/context/WorkflowContext';
import { listWorkflows, duplicateWorkflow } from '@/api/client';
import AlertModal from '@/components/ui/AlertModal';
import { safeLog, safeError } from '../../utils/safeLogger';

export default function Sidebar({ onClose }) {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const [publishedWorkflows, setPublishedWorkflows] = useState([]);
  const [loadingWorkflows, setLoadingWorkflows] = useState(true);
  const [showLoadError, setShowLoadError] = useState(false);
  const [loadErrorMessage, setLoadErrorMessage] = useState('');
  const [isDuplicating, setIsDuplicating] = useState(null);

  const handleDuplicate = async (e, workflow) => {
    e.stopPropagation();
    try {
      setIsDuplicating(workflow.id);
      await duplicateWorkflow(workflow);
      const data = await listWorkflows(1, 50);
      setPublishedWorkflows(data.items || data.workflows || []);
    } catch (error) {
      safeError('Failed to duplicate workflow:', error);
      setLoadErrorMessage(`Failed to duplicate: ${error.message}`);
      setShowLoadError(true);
    } finally {
      setIsDuplicating(null);
    }
  };

  // Load workflows from backend
  useEffect(() => {
    const fetchWorkflows = async () => {
      try {
        setLoadingWorkflows(true);
        // Fetch published workflows
        const data = await listWorkflows(1, 50);
        setPublishedWorkflows(data.items || data.workflows || []);
      } catch (error) {
        safeError('Failed to load workflows:', error);
        setPublishedWorkflows([]);
      } finally {
        setLoadingWorkflows(false);
      }
    };
    fetchWorkflows();
  }, [state.selectedWorkflow?.id]);

  const loadWorkflow = (workflow) => {
    try {
      // Parse nodes and connections from workflow
      const nodesData = workflow.nodes ? JSON.parse(workflow.nodes) : [];
      const edgesData = workflow.connections ? JSON.parse(workflow.connections) : [];
      
      safeLog('📥 LOADING from DB - edgesData:', edgesData);
      edgesData.forEach((edge, idx) => {
        safeLog(`  Edge ${idx}: conditionId =`, edge.conditionId);
      });
      
      // Transform nodes using the same logic as importWorkflowJSON
      const nodes = nodesData.map(node => {
        safeLog(`🔍 LOADING Node ${node.id}:`, {
          'node.config': node.config,
          'node.data?.config': node.data?.config,
          'node.config.modelName': node.config?.modelName,
          'node.data?.config.modelName': node.data?.config?.modelName
        });
        
        // Extract node type from various possible locations
        const nodeType = node.type || node.data?.config?.type || node.config?.kind;
        
        // Extract config from various possible locations
        const nodeConfig = {
          ...(node.config || {}),
          ...(node.data?.config || {}),
          label: node.data?.label || node.config?.label || node.label
        };
        
        safeLog(`🔍 MERGED config for ${node.id}:`, {
          modelProvider: nodeConfig.modelProvider,
          modelName: nodeConfig.modelName,
          fullConfig: nodeConfig
        });
        
        // Find the matching node type definition from APP_DATA
        const nodeTypeDef = APP_DATA.nodeTypes
          .flatMap(cat => cat.nodes)
          .find(n => n.id === nodeType);

        return {
          id: node.id,
          type: nodeType || 'custom',
          x: node.position?.x || node.x || 0,  // Extract position properly!
          y: node.position?.y || node.y || 0,  // Extract position properly!
          config: nodeConfig,
          nodeType: nodeTypeDef || {
            id: nodeType,
            name: nodeConfig.label || 'Unknown',
            icon: '📦',
            color: '#6B7280',
            description: 'Imported node'
          }
        };
      });

      // Transform edges to connections
      const connections = (edgesData || []).map(edge => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle || null,
        targetHandle: edge.targetHandle || null,
        conditionId: edge.conditionId || null  // ✅ Preserve conditionId for condition nodes
      }));

      safeLog('📥 Transformed connections:', connections);
      connections.forEach((conn, idx) => {
        safeLog(`  Connection ${idx}: conditionId =`, conn.conditionId);
      });

      // Load into canvas
      const payload = {
        id: workflow.id,
        name: workflow.name,
        nodes: nodes,
        connections: connections
      };
      
      safeLog('🚀 DISPATCHING LOAD_TEMPLATE with payload:');
      safeLog('  workflow.id:', workflow.id);
      safeLog('  payload.id:', payload.id);
      safeLog('  payload.name:', payload.name);
      safeLog('  payload.nodes.length:', payload.nodes.length);
      safeLog('  payload.connections.length:', payload.connections.length);
      
      dispatch({
        type: ACTIONS.LOAD_TEMPLATE,
        payload: payload
      });
      
      // Store the selected workflow for chat
      dispatch({
        type: ACTIONS.SELECT_WORKFLOW,
        payload: workflow,
      });
    } catch (error) {
      safeError('Failed to load workflow:', error);
      setLoadErrorMessage(`Failed to load workflow: ${error.message}`);
      setShowLoadError(true);
    }
  };

  const loadTemplate = (template) => {
    // Map template node types to actual node type objects
    const templateWithTypes = {
      ...template,
      nodes: template.nodes.map(node => {
        const nodeType = APP_DATA.nodeTypes
          .flatMap(cat => cat.nodes)
          .find(n => n.id === node.type);
        return {
          ...node,
          nodeType: nodeType,
        };
      }),
    };

    dispatch({
      type: ACTIONS.LOAD_TEMPLATE,
      payload: templateWithTypes,
    });
  };

  return (
    <aside className="w-16 sm:w-52 lg:w-60 xl:w-64 bg-surface border-r border-border overflow-y-auto p-3 sm:p-4 flex-shrink-0 h-full relative">
      {onClose && (
        <button
          onClick={onClose}
          className="absolute right-0 top-1/2 -translate-y-1/2 w-8 h-20 bg-surface border border-border rounded-l-lg flex items-center justify-center hover:bg-primary/10 hover:border-primary transition-all z-50 shadow-md"
          title="Hide workflows"
        >
          <svg className="w-5 h-5 text-muted-foreground hover:text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      )}
      <nav className="flex flex-col gap-4 sm:gap-5 lg:gap-6">
        {/* Workflows Section */}
        <section>
          <div className="mb-2">
            <h3 className="hidden sm:block text-xs font-semibold text-muted-foreground uppercase tracking-wide px-1">
            Workflows
          </h3>
            <h3 className="sm:hidden text-center text-xs font-semibold text-muted-foreground uppercase" title="Workflows">
            WF
          </h3>
          </div>
          <div className="flex flex-col gap-1">
            {loadingWorkflows ? (
              <div className="hidden sm:flex px-2 sm:px-3 py-2 text-xs sm:text-sm text-muted-foreground italic">
                Loading...
              </div>
            ) : publishedWorkflows.length === 0 ? (
              <div className="hidden sm:flex px-2 sm:px-3 py-2 text-xs sm:text-sm text-muted-foreground italic">
                No workflows yet
              </div>
            ) : (
              publishedWorkflows.map((workflow) => (
                <div
                  key={workflow.id}
                  className={`flex items-center justify-center sm:justify-between p-2 sm:px-3 sm:py-2 rounded-lg cursor-pointer transition-all duration-200 hover:bg-secondary active:bg-muted text-foreground text-sm group ${
                    state.selectedWorkflow?.id === workflow.id ? 'bg-primary/10 border border-primary' : ''
                  }`}
                  onClick={() => loadWorkflow(workflow)}
                >
                  <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
                    <img src="/icons/workflow.svg" alt="Workflow" className="w-5 h-5 flex-shrink-0" />
                    <span className="hidden sm:inline truncate">{workflow.name}</span>
                  </div>
                  <button
                    type="button"
                    title="Duplicate"
                    onClick={(e) => handleDuplicate(e, workflow)}
                    disabled={isDuplicating === workflow.id}
                    className="hidden sm:flex w-6 h-6 items-center justify-center rounded opacity-0 group-hover:opacity-100 hover:bg-primary/10 text-muted-foreground hover:text-primary transition-all flex-shrink-0"
                  >
                    {isDuplicating === workflow.id ? (
                      <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                    ) : (
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
                    )}
                  </button>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Templates Section */}
        <section>
          <h3 className="hidden sm:block text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
            Templates
          </h3>
          <h3 className="sm:hidden text-center text-xs font-semibold text-muted-foreground uppercase mb-2" title="Templates">
            TM
          </h3>
          <div className="flex flex-col gap-1">
            {APP_DATA.templates.map((template) => (
              <button
                key={template.id}
                type="button"
                title={template.name}
                onClick={() => loadTemplate(template)}
                className="flex items-center justify-center sm:justify-start gap-2 sm:gap-2.5 p-2 sm:px-3 sm:py-2 rounded-lg cursor-pointer transition-all duration-200 hover:bg-secondary active:bg-muted text-foreground text-sm group"
              >
                <span className="text-lg sm:text-base flex-shrink-0">📋</span>
                <span className="hidden sm:inline truncate">{template.name}</span>
              </button>
            ))}
          </div>
        </section>
      </nav>

      <AlertModal
        isOpen={showLoadError}
        onClose={() => setShowLoadError(false)}
        title="Load Failed"
        message={loadErrorMessage}
        variant="error"
      />
    </aside>
  );
}
