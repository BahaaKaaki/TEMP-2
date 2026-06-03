import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useWorkflow } from '@/context/WorkflowContext';
import Button from '../ui/Button';
import { getNodeConfigFields } from '@/data/appData';
import { groupAgentConfigFields } from '@/data/agentConfigLayout';
import DynamicConfigField from './DynamicConfigField';
import CategoryRangeSlider from './CategoryRangeSlider';
import { fetchAllModels } from '@/api/models';
import ConfirmModal from '../ui/ConfirmModal';
import { safeError } from '../../utils/safeLogger';
import { getNodeStyle, getPanelGradient } from './nodeCategoryStyles';
import { COLOR, FONT, NAVBAR, PANEL } from './figmaSpec';
import { useFigmaPx } from './useFigmaScale';
import AppIcon from '../ui/AppIcon';

// Figma 83:1437 — the right config panel only shows a small handful of
// fields per node type ("basic mode"). Everything else is gated behind the
// "Advanced mode" toggle in the header. Each entry is the list of field
// keys (matching nodePaletteConfig.json) visible in basic mode.
//
// Note: dependency fields (e.g. `startupType` controls when
// `startupMessage` shows) intentionally aren't listed — DynamicConfigField
// reads the *backfilled* `config` (which already contains defaults) for
// `showIf` so the dependent field still becomes visible without exposing
// the controller. Default values resolve `showIf` correctly.
const BASIC_FIELDS_BY_TYPE = {
  chat: ['label'],
  condition: ['label', 'conditions'],
  'human-in-the-loop': ['label', 'instructions'],
  'code-executor': ['label', 'code', 'startupMessage'],
  'powerpoint-generator': ['label', 'deliverableSources'],
};

/**
 * Upstream node ids in the same order runtime uses for `inputs["deliverables"]`
 * (earlier in the workflow = lower index).
 *
 * A naive BFS from the code node walks *backward* along edges, so a linear
 * chain A→B→Code would list [B, A] while deliverables are appended [A, B].
 * We fix that by sorting with descending graph distance from the code node
 * (farther upstream first), then stable tie-break on BFS discovery order.
 */
function computeUpstreamNodeIdsExecutionOrder(connections, codeExecNodeId) {
  const visited = new Set();
  const queue = [];
  const bfsOrder = [];
  for (const conn of connections) {
    if (conn.target === codeExecNodeId) queue.push(conn.source);
  }
  while (queue.length) {
    const nid = queue.shift();
    if (visited.has(nid)) continue;
    visited.add(nid);
    bfsOrder.push(nid);
    for (const conn of connections) {
      if (conn.target === nid) queue.push(conn.source);
    }
  }
  const unique = [...new Set(bfsOrder)];
  if (unique.length <= 1) return unique;

  const dist = new Map();
  const q2 = [{ id: codeExecNodeId, d: 0 }];
  const seenDist = new Set([codeExecNodeId]);
  let qi = 0;
  while (qi < q2.length) {
    const { id: t, d } = q2[qi++];
    for (const c of connections) {
      if (c.target !== t) continue;
      const s = c.source;
      if (!visited.has(s) || seenDist.has(s)) continue;
      seenDist.add(s);
      dist.set(s, d + 1);
      q2.push({ id: s, d: d + 1 });
    }
  }

  unique.sort((a, b) => {
    const da = dist.get(a) ?? 0;
    const db = dist.get(b) ?? 0;
    if (db !== da) return db - da;
    return bfsOrder.indexOf(a) - bfsOrder.indexOf(b);
  });
  return unique;
}

/**
 * Node types that never append rows to ``state["deliverables"]`` (and thus
 * never get an ``inputs["deliverables"][i]`` slot). Listing them in the Code
 * Executor tree invents bogus indices — e.g. If/Else + Agent shows [0] and [1]
 * while runtime only has the agent at [0].
 */
const NODE_TYPES_NEVER_IN_DELIVERABLES_ARRAY = new Set([
  'condition',
  'end',
  'chat',
  'webhook',
  'scheduled-start',
  'sticky-note',
  'start',
  'tool',
  'transform',
  'human',
]);

/**
 * Keep only upstream nodes whose outputs can appear in ``inputs["deliverables"]``,
 * and honour ``deliverableSources`` when set to ``none`` or a specific id list.
 */
function filterOrderedUpstreamForCodeExecutorDeliverables(orderedIds, canvasNodes, deliverableSources) {
  let ids = orderedIds.filter((nid) => {
    const node = canvasNodes.get(nid);
    if (!node) return false;
    return !NODE_TYPES_NEVER_IN_DELIVERABLES_ARRAY.has(node.type);
  });

  const src = deliverableSources;
  if (src === 'none' || src === false) {
    return [];
  }
  if (Array.isArray(src) && src.length > 0) {
    const allow = new Set(src);
    ids = ids.filter((id) => allow.has(id));
  }
  return ids;
}

// Expanded Text Editor Modal Component
function ExpandedTextModal({ isOpen, label, value, onClose, onSave, isMultiline = true }) {
  const [editValue, setEditValue] = useState(value || '');
  
  useEffect(() => {
    setEditValue(value || '');
  }, [value, isOpen]);

  if (!isOpen) return null;

  const handleSave = () => {
    onSave(editValue);
    onClose();
  };

  // Portal to document.body and use the same Apex OS dark theme
  // (gradient bg + #464646 borders + rose CTA) as the right-hand
  // config panel so popups feel like part of the workflow builder.
  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center z-[9999]"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl p-6 w-[90vw] max-w-3xl max-h-[80vh] flex flex-col shadow-2xl"
        style={{
          background: 'linear-gradient(135deg, #1a1a1a 0%, #121212 100%)',
          border: '1px solid #464646',
          color: '#ffffff',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold" style={{ color: '#ffffff' }}>{label}</h3>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
            style={{ backgroundColor: 'transparent', color: '#b5b5b5' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 min-h-0 mb-4">
          {isMultiline ? (
            <textarea
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="w-full h-full min-h-[300px] px-4 py-3 text-sm rounded-2xl resize-none focus:outline-none"
              style={{
                backgroundColor: 'transparent',
                border: '1px solid #464646',
                color: '#ffffff',
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = '#8216c5')}
              onBlur={(e) => (e.currentTarget.style.borderColor = '#464646')}
              autoFocus
              placeholder={`Enter ${label.toLowerCase()}...`}
            />
          ) : (
            <input
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="w-full px-4 py-3 text-sm rounded-2xl focus:outline-none"
              style={{
                backgroundColor: 'transparent',
                border: '1px solid #464646',
                color: '#ffffff',
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = '#8216c5')}
              onBlur={(e) => (e.currentTarget.style.borderColor = '#464646')}
              autoFocus
              placeholder={`Enter ${label.toLowerCase()}...`}
            />
          )}
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{
              color: '#ffffff',
              backgroundColor: 'transparent',
              border: '1px solid #464646',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{ color: '#ffffff', backgroundColor: '#d93854', border: 'none' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#c52a45')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#d93854')}
          >
            Done
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// Clickable Text Field Component
function ExpandableTextField({ label, value, onChange, placeholder, isMultiline = false, rows = 3, className = '' }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const displayValue = value || '';
  const truncatedValue = displayValue.length > 50 ? displayValue.substring(0, 50) + '...' : displayValue;

  return (
    <>
      <div
        onClick={() => setIsModalOpen(true)}
        className={`w-full px-3 py-2 text-sm bg-gray-50 border border-border rounded-lg cursor-pointer hover:border-primary/50 transition-colors ${className}`}
      >
        {displayValue ? (
          <span className="text-foreground">{truncatedValue}</span>
        ) : (
          <span className="text-muted-foreground">{placeholder}</span>
        )}
      </div>
      <ExpandedTextModal
        isOpen={isModalOpen}
        label={label}
        value={value}
        onClose={() => setIsModalOpen(false)}
        onSave={onChange}
        isMultiline={isMultiline}
      />
    </>
  );
}

// Module-level cache so models survive component remounts (key-based)
let _modelsCache = null;
let _modelsCachePromise = null;

export default function NodeConfigPanel({ readOnly = false }) {
  const { state, dispatch, ACTIONS, registerNodeConfigFlush } = useWorkflow();
  const { px } = useFigmaPx();

  // The parent renders this component with key={selectedNodeId}, so
  // the component remounts from scratch whenever the selected node changes.
  // We can safely derive the initial config from the selected node.
  const selectedNodeId = state.selectedNodeIds && state.selectedNodeIds.length > 0
    ? state.selectedNodeIds[0]
    : null;

  const selectedNode = state.canvasNodes.get(selectedNodeId);

  // Migrate legacy single-tool configs to the new multi-tool shape:
  //  - Drop the synthetic `selectedTool` radio key (no longer needed)
  //  - Promote single `knowledgeBaseId` → `knowledgeBaseIds: [id]` so the
  //    multi-KB picker shows the previously-saved selection.
  const migrateToolConfig = (cfg) => {
    if ('selectedTool' in cfg) {
      delete cfg.selectedTool;
    }
    const hasMulti = Array.isArray(cfg.knowledgeBaseIds) && cfg.knowledgeBaseIds.length > 0;
    if (!hasMulti && cfg.knowledgeBaseId) {
      cfg.knowledgeBaseIds = [cfg.knowledgeBaseId];
    }
    if (!Array.isArray(cfg.knowledgeBaseIds)) {
      cfg.knowledgeBaseIds = [];
    }
    return cfg;
  };

  // Deep-clone the node config for local editing so we never share references
  const [localConfig, setLocalConfig] = useState(() => {
    const node = selectedNodeId ? state.canvasNodes.get(selectedNodeId) : null;
    const cfg = node?.config ? JSON.parse(JSON.stringify(node.config)) : {};
    return migrateToolConfig(cfg);
  });
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [showSavedIndicator, setShowSavedIndicator] = useState(false);
  const [availableModels, setAvailableModels] = useState(_modelsCache);
  const [isLoadingModels, setIsLoadingModels] = useState(!_modelsCache);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  // Figma 83:1562 — Advanced mode toggle. When OFF only the small Figma-spec
  // field set per node type is shown. When ON every field defined in JSON is
  // exposed. Defaults to OFF so the panel matches the Figma frame on open.
  const [advancedMode, setAdvancedMode] = useState(false);
  const autoSaveTimerRef = useRef(null);



  // Refs that always hold the latest values — used by the unmount cleanup
  const localConfigRef = useRef(localConfig);
  localConfigRef.current = localConfig;
  const hasUnsavedChangesRef = useRef(hasUnsavedChanges);
  hasUnsavedChangesRef.current = hasUnsavedChanges;

  // Fetch available models on mount (with module-level cache)
  useEffect(() => {
    if (_modelsCache) return;

    if (!_modelsCachePromise) {
      _modelsCachePromise = fetchAllModels();
    }

    let cancelled = false;
    _modelsCachePromise
      .then(modelsData => {
        _modelsCache = modelsData;
        if (!cancelled) {
          setAvailableModels(modelsData);
          setIsLoadingModels(false);
        }
      })
      .catch(error => {
        safeError('Failed to load models:', error);
        _modelsCachePromise = null;
        if (!cancelled) setIsLoadingModels(false);
      });

    return () => { cancelled = true; };
  }, []);

  const flushLocalConfigToCanvas = () => {
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
      autoSaveTimerRef.current = null;
    }
    if (!selectedNodeId) {
      return null;
    }
    const config = localConfigRef.current;
    const canvasConfig = state.canvasNodes.get(selectedNodeId)?.config;
    const differsFromCanvas =
      JSON.stringify(config ?? {}) !== JSON.stringify(canvasConfig ?? {});
    if (!hasUnsavedChangesRef.current && !differsFromCanvas) {
      return null;
    }
    dispatch({
      type: ACTIONS.UPDATE_NODE,
      payload: {
        nodeId: selectedNodeId,
        config,
        replace: true,
      },
    });
    setHasUnsavedChanges(false);
    return { nodeId: selectedNodeId, config };
  };

  useEffect(() => {
    registerNodeConfigFlush(() => flushLocalConfigToCanvas());
    return () => registerNodeConfigFlush(null);
  }, [registerNodeConfigFlush, selectedNodeId, selectedNode?.config, dispatch, ACTIONS]);

  // On unmount (triggered by key change = node switch) flush unsaved changes
  useEffect(() => {
    return () => {
      flushLocalConfigToCanvas();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Once models finish loading, seed localConfig with default provider/model
  // only if the node doesn't already have them set (e.g. newly created node).
  useEffect(() => {
    if (!availableModels || isLoadingModels) return;
    if (!selectedNode) return;
    const nodeType = selectedNode.type;
    if (nodeType !== 'agent' && nodeType !== 'chat') return;

    setLocalConfig(prev => {
      const needsProvider = !prev.modelProvider;
      const needsModel = !prev.modelName;
      if (!needsProvider && !needsModel) return prev;

      const provider = prev.modelProvider || availableModels.default_provider || Object.keys(availableModels.providers || {})[0] || 'openai';
      const providerModels = availableModels.providers?.[provider]?.models || [];
      const model = prev.modelName || availableModels.default_model || (providerModels.length > 0 ? providerModels[0].value : '');

      return { ...prev, modelProvider: provider, modelName: model };
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableModels, isLoadingModels]);

  // When the canvas node config changes externally (e.g. after test-chat save), resync
  // the panel unless the user still has local unsaved edits.
  useEffect(() => {
    if (!selectedNode || hasUnsavedChanges) return;
    const next = migrateToolConfig(JSON.parse(JSON.stringify(selectedNode.config || {})));
    setLocalConfig((prev) => {
      if (JSON.stringify(prev) === JSON.stringify(next)) return prev;
      return next;
    });
  }, [selectedNode, hasUnsavedChanges]);

  // Auto-save after 2 seconds of no changes
  useEffect(() => {
    if (readOnly) return undefined;
    if (hasUnsavedChanges && selectedNodeId) {
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }

      autoSaveTimerRef.current = setTimeout(() => {
        dispatch({
          type: ACTIONS.UPDATE_NODE,
          payload: {
            nodeId: selectedNodeId,
            config: localConfig,
            replace: true,
          },
        });
        setHasUnsavedChanges(false);
        setShowSavedIndicator(true);

        setTimeout(() => {
          setShowSavedIndicator(false);
        }, 2000);
      }, 2000);

      return () => {
        if (autoSaveTimerRef.current) {
          clearTimeout(autoSaveTimerRef.current);
        }
      };
    }
  }, [localConfig, hasUnsavedChanges, selectedNodeId, dispatch, ACTIONS]);

  if (!selectedNodeId) {
    return (
      <div className="w-96 bg-white border-l border-border rounded-l-2xl p-4 mr-4 my-4 overflow-y-auto flex-shrink-0 h-[calc(100%-2rem)]">
        <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
          <div className="text-4xl mb-3">⚙️</div>
          <p className="text-sm">Select a node to configure</p>
        </div>
      </div>
    );
  }

  if (!selectedNode) return null;

  // Hide config panel for sticky notes - they don't have configurable properties
  if (selectedNode.type === 'sticky-note') {
    return (
      <div
        className="overflow-y-auto flex-shrink-0"
        style={{
          width: px(PANEL.width),
          backgroundColor: COLOR.darkest,
          borderWidth: PANEL.borderWidth,
          borderStyle: 'solid',
          borderColor: COLOR.darker,
          borderRadius: px(PANEL.radius),
          padding: px(PANEL.padding),
          marginRight: px(24),
          marginTop: px(16),
          marginBottom: px(16),
          height: 'calc(100% - 32px)',
        }}
      >
        <div className="flex flex-col items-center justify-center h-full text-center" style={{ color: COLOR.medium }}>
          <div style={{ fontSize: px(32), marginBottom: px(12) }}>📝</div>
          <p style={{ color: COLOR.white, fontSize: px(14), fontWeight: 500, marginBottom: px(8) }}>Sticky Note</p>
          <p style={{ fontSize: px(12) }}>Edit the note directly on the canvas</p>
        </div>
      </div>
    );
  }

  const handleConfigChange = (key, value) => {
    if (readOnly) return;
    // When provider changes, reset the model to the first available model for that provider
    if (key === 'modelProvider') {
      const newProviderModels = availableModels?.providers?.[value]?.models;
      const firstModel = newProviderModels && newProviderModels.length > 0 ? newProviderModels[0].value : '';

      setLocalConfig(prev => ({
        ...prev,
        [key]: value,
        modelName: firstModel,
      }));
    } else if (key === 'knowledgeBaseIds') {
      // Mirror the new array into the legacy single-id field so older
      // backends/consumers that still read `knowledgeBaseId` keep working.
      const ids = Array.isArray(value) ? value : [];
      setLocalConfig(prev => ({
        ...prev,
        knowledgeBaseIds: ids,
        knowledgeBaseId: ids[0] || null,
      }));
    } else if (key === 'knowledgeBase' && value === false) {
      // Disabling KB clears the picker so stale selections don't get
      // re-enabled the next time the user toggles the checkbox on.
      setLocalConfig(prev => ({
        ...prev,
        knowledgeBase: false,
        knowledgeBaseIds: [],
        knowledgeBaseId: null,
      }));
    } else if (key === 'enableWebSearch' && value === false) {
      setLocalConfig(prev => ({
        ...prev,
        enableWebSearch: false,
        enableDeepResearch: false,
      }));
    } else {
      setLocalConfig(prev => ({
        ...prev,
        [key]: value,
      }));
    }

    setHasUnsavedChanges(true);
    setShowSavedIndicator(false);
  };

  const renderConfigField = (field, config, upstreamNodes) => (
    <DynamicConfigField
      key={field.key}
      field={field}
      value={config[field.key]}
      config={config}
      onChange={handleConfigChange}
      currentNodeId={selectedNodeId}
      workflowState={state}
      upstreamNodes={upstreamNodes}
      nodeType={selectedNode?.type}
    />
  );

  const renderAgentCategoryHeading = (title) => (
    <h4
      key={`cat-${title}`}
      className="uppercase tracking-wide"
      style={{
        color: COLOR.medium,
        fontSize: px(FONT.caption.size),
        lineHeight: `${px(FONT.caption.height)}px`,
        fontWeight: 600,
        marginTop: px(10),
        marginBottom: px(6),
      }}
    >
      {title}
    </h4>
  );

  const handleSaveChanges = () => {
    dispatch({
      type: ACTIONS.UPDATE_NODE,
      payload: {
        nodeId: selectedNodeId,
        config: localConfig,
        replace: true,
      },
    });
    setHasUnsavedChanges(false);
    setShowSavedIndicator(true);

    // Hide saved indicator after 2 seconds
    setTimeout(() => {
      setShowSavedIndicator(false);
    }, 2000);
  };

  const handleDelete = () => {
    setShowDeleteConfirm(true);
  };

  const confirmDelete = () => {
    dispatch({ type: ACTIONS.REMOVE_NODE, payload: selectedNodeId });
    setShowDeleteConfirm(false);
  };

  // Check if the current node has incoming connections
  const hasIncomingConnections = () => {
    if (!selectedNodeId) return false;
    return state.connections.some(conn => conn.target === selectedNodeId);
  };

  const renderConfigFields = () => {
    const nodeType = selectedNode.type;

    // Get configuration fields from JSON
    const configFields = getNodeConfigFields(nodeType);

    // If no config fields defined in JSON, check if we have legacy hardcoded configs
    if (!configFields || configFields.length === 0) {
      return renderLegacyConfigFields();
    }

    // Build a *view-only* config that backfills any field whose value
    // hasn't been set yet on this node with the field's defaultValue.
    // This keeps `showIf` predicates working for legacy nodes that
    // pre-date newer fields (e.g. `initialType` / `startupType` were
    // added later, but old chat/agent nodes were saved without them).
    // We don't write the defaults back into localConfig — only the
    // existing onChange path mutates the stored config.
    const config = (() => {
      const out = { ...localConfig };
      configFields.forEach((f) => {
        if (out[f.key] === undefined && f.defaultValue !== undefined) {
          out[f.key] = f.defaultValue;
        }
      });
      return out;
    })();
    
    // Compute upstream nodes for the inputs browser / codegen (indices must
    // match `inputs["deliverables"][i]` at runtime — execution order, not BFS-from-code).
    const upstreamNodes = (() => {
      if (!selectedNodeId) return [];
      let orderedIds = computeUpstreamNodeIdsExecutionOrder(
        state.connections,
        selectedNodeId,
      );
      if (nodeType === 'code-executor') {
        orderedIds = filterOrderedUpstreamForCodeExecutorDeliverables(
          orderedIds,
          state.canvasNodes,
          config.deliverableSources,
        );
      }
      return orderedIds
        .map((nid) => {
          const node = state.canvasNodes.get(nid);
          if (!node) return null;
          return {
            id: nid,
            type: node.type,
            label: node.config?.label || node.type,
            config: node.config || {},
          };
        })
        .filter(Boolean);
    })();

    // Hide input_mapper / form_schema_builder for code-executor since
    // they're now handled inside the full-screen code editor modal.
    const hiddenFieldTypes = nodeType === 'code-executor'
      ? new Set(['input_mapper', 'form_schema_builder'])
      : new Set();

    const filterField = (field) => !hiddenFieldTypes.has(field.type);

    const SOURCE_TOGGLE_KEYS = new Set([
      'enableWebSearch',
      'enableDeepResearch',
      'knowledgeBase',
    ]);

    const BEHAVIOR_TOGGLE_KEYS = new Set([
      'showReasoning',
      'enableUserQuestions',
    ]);

    const HUMAN_REVIEW_TOGGLE_KEYS = new Set([
      'requireApproval',
      'allowEditing',
    ]);

    const renderToggleGroup = (toggleFields, restFields) => (
      <>
        {toggleFields.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
            {toggleFields.map((field) => renderConfigField(field, config, upstreamNodes))}
          </div>
        )}
        {restFields.map((field) => renderConfigField(field, config, upstreamNodes))}
      </>
    );

    const renderAgentSectionFields = (title, fields) => {
      const visible = fields.filter(filterField);
      if (title === 'Sources') {
        const toggles = visible.filter((f) => SOURCE_TOGGLE_KEYS.has(f.key));
        const rest = visible.filter((f) => !SOURCE_TOGGLE_KEYS.has(f.key));
        return renderToggleGroup(toggles, rest);
      }
      if (title === 'Behavior') {
        const toggles = visible.filter((f) => BEHAVIOR_TOGGLE_KEYS.has(f.key));
        const rest = visible.filter((f) => !BEHAVIOR_TOGGLE_KEYS.has(f.key));
        return renderToggleGroup(toggles, rest);
      }
      return visible.map((field) => renderConfigField(field, config, upstreamNodes));
    };

    if (nodeType === 'agent') {
      const groups = groupAgentConfigFields(configFields, advancedMode);
      return (
        <>
          {groups.map(({ title, fields }) => (
            <section key={title} className="mb-3">
              {renderAgentCategoryHeading(title)}
              {renderAgentSectionFields(title, fields)}
            </section>
          ))}
        </>
      );
    }

    if (nodeType === 'human-in-the-loop') {
      const basicKeysForHitl = BASIC_FIELDS_BY_TYPE['human-in-the-loop'];
      const fieldsAfterModeFilter = (advancedMode || !basicKeysForHitl)
        ? configFields
        : configFields.filter((f) => basicKeysForHitl.includes(f.key));
      const visible = fieldsAfterModeFilter.filter(filterField);
      const toggles = visible.filter((f) => HUMAN_REVIEW_TOGGLE_KEYS.has(f.key));
      const labelField = visible.find((f) => f.key === 'label');
      const restFields = visible.filter(
        (f) => f.key !== 'label' && !HUMAN_REVIEW_TOGGLE_KEYS.has(f.key),
      );

      return (
        <>
          {labelField && renderConfigField(labelField, config, upstreamNodes)}
          {renderToggleGroup(toggles, restFields)}
        </>
      );
    }

    const basicKeys =
      nodeType === 'chat' || nodeType === 'condition' ? null : BASIC_FIELDS_BY_TYPE[nodeType];
    const fieldsAfterModeFilter = (advancedMode || !basicKeys)
      ? configFields
      : configFields.filter((f) => basicKeys.includes(f.key));

    return (
      <>
        {fieldsAfterModeFilter
          .filter(filterField)
          .map((field) => renderConfigField(field, config, upstreamNodes))}
      </>
    );
  };

  // Legacy hardcoded config rendering for backward compatibility
  const renderLegacyConfigFields = () => {
    const nodeType = selectedNode.type;
    const config = localConfig;

    switch (nodeType) {
      case 'agent':
        return (
          <>
            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Label
              </label>
              <ExpandableTextField
                label="Label"
                value={config.label || ''}
                onChange={(val) => handleConfigChange('label', val)}
                placeholder="Agent name"
                isMultiline={false}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Model Provider
              </label>
              <select
                value={config.modelProvider || ''}
                onChange={(e) => handleConfigChange('modelProvider', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                disabled={isLoadingModels}
              >
                {isLoadingModels ? (
                  <option>Loading providers...</option>
                ) : availableModels?.providers ? (
                  Object.entries(availableModels.providers).map(([providerId, providerData]) => (
                    <option key={providerId} value={providerId}>
                      {providerData.name}
                    </option>
                  ))
                ) : (
                  <option value="openai">OpenAI</option>
                )}
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Model Name
              </label>
              <select
                value={config.modelName || ''}
                onChange={(e) => handleConfigChange('modelName', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                disabled={isLoadingModels}
              >
                {isLoadingModels ? (
                  <option>Loading models...</option>
                ) : availableModels?.providers && config.modelProvider ? (
                  availableModels.providers[config.modelProvider]?.models?.map((model) => (
                    <option key={model.value} value={model.value}>
                      {model.label} {model.tier && `(${model.tier})`}
                    </option>
                  ))
                ) : (
                  <option value="">Select a provider first</option>
                )}
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                System Instructions
              </label>
              <ExpandableTextField
                label="System Instructions"
                value={config.systemInstructions || ''}
                onChange={(val) => handleConfigChange('systemInstructions', val)}
                placeholder="Enter system instructions..."
                isMultiline={true}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Temperature
              </label>
              <CategoryRangeSlider
                nodeType={selectedNode?.type}
                min={0}
                max={2}
                step={0.1}
                value={config.temperature ?? 0.7}
                onChange={(e) => handleConfigChange('temperature', parseFloat(e.target.value))}
              />
              <div className="text-xs text-muted-foreground mt-1 text-right">
                {config.temperature ?? 0.7}
              </div>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Max Tokens (optional)
              </label>
              <input
                type="number"
                value={config.maxTokens || ''}
                onChange={(e) => handleConfigChange('maxTokens', e.target.value ? parseInt(e.target.value) : null)}
                placeholder="Leave empty for default"
                className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Tools (comma-separated)
              </label>
              <ExpandableTextField
                label="Tools"
                value={Array.isArray(config.tools) ? config.tools.join(', ') : ''}
                onChange={(val) => handleConfigChange('tools', val.split(',').map(t => t.trim()).filter(t => t))}
                placeholder="web_search, knowledge_base, code_interpreter"
                isMultiline={false}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Knowledge Base ID
              </label>
              <Input
                value={config.knowledgeBaseId || ''}
                onChange={(e) => handleConfigChange('knowledgeBaseId', e.target.value || null)}
                placeholder="kb-uuid-123"
              />
            </div>

            <div className="mb-4">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.allowFileUpload || false}
                  onChange={(e) => handleConfigChange('allowFileUpload', e.target.checked)}
                  className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
                />
                <span className="text-sm font-medium text-foreground">Allow File Upload at Runtime</span>
              </label>
            </div>


            <details className="mb-4">
              <summary className="text-sm font-medium text-foreground mb-2 cursor-pointer hover:text-primary">
                Advanced: Structured I/O (JSON Schema)
              </summary>
              <div className="mt-3 space-y-3">
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">
                    Input Schema (JSON)
                  </label>
                  <ExpandableTextField
                    label="Input Schema (JSON)"
                    value={config.structuredInputSchema || ''}
                    onChange={(val) => handleConfigChange('structuredInputSchema', val)}
                    placeholder='{"type": "object", "properties": {...}}'
                    isMultiline={true}
                    className="font-mono text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">
                    Output Schema (JSON)
                  </label>
                  <ExpandableTextField
                    label="Output Schema (JSON)"
                    value={config.structuredOutputSchema || ''}
                    onChange={(val) => handleConfigChange('structuredOutputSchema', val)}
                    placeholder='{"type": "object", "properties": {...}}'
                    isMultiline={true}
                    className="font-mono text-xs"
                  />
                </div>
              </div>
            </details>
          </>
        );

      case 'chat':
        return (
          <>
            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Label
              </label>
              <ExpandableTextField
                label="Label"
                value={config.label || ''}
                onChange={(val) => handleConfigChange('label', val)}
                placeholder="Chat name"
                isMultiline={false}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Model Provider
              </label>
              <select
                value={config.modelProvider || ''}
                onChange={(e) => handleConfigChange('modelProvider', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                disabled={isLoadingModels}
              >
                {isLoadingModels ? (
                  <option>Loading providers...</option>
                ) : availableModels?.providers ? (
                  Object.entries(availableModels.providers).map(([providerId, providerData]) => (
                    <option key={providerId} value={providerId}>
                      {providerData.name}
                    </option>
                  ))
                ) : (
                  <option value="openai">OpenAI</option>
                )}
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Model Name
              </label>
              <select
                value={config.modelName || ''}
                onChange={(e) => handleConfigChange('modelName', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                disabled={isLoadingModels}
              >
                {isLoadingModels ? (
                  <option>Loading models...</option>
                ) : availableModels?.providers && config.modelProvider ? (
                  availableModels.providers[config.modelProvider]?.models?.map((model) => (
                    <option key={model.value} value={model.value}>
                      {model.label} {model.tier && `(${model.tier})`}
                    </option>
                  ))
                ) : (
                  <option value="">Select a provider first</option>
                )}
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                System Instructions
              </label>
              <ExpandableTextField
                label="System Instructions"
                value={config.systemInstructions || ''}
                onChange={(val) => handleConfigChange('systemInstructions', val)}
                placeholder="You are a helpful conversational assistant..."
                isMultiline={true}
              />
            </div>


            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Temperature
              </label>
              <CategoryRangeSlider
                nodeType={selectedNode?.type}
                min={0}
                max={2}
                step={0.1}
                value={config.temperature ?? 0.7}
                onChange={(e) => handleConfigChange('temperature', parseFloat(e.target.value))}
              />
              <div className="text-xs text-muted-foreground mt-1 text-right">
                {config.temperature ?? 0.7}
              </div>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Exit Condition
              </label>
              <select
                value={config.exitCondition || 'manual_continue'}
                onChange={(e) => handleConfigChange('exitCondition', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="manual_continue">Manual Continue</option>
                <option value="approval_required">Approval Required</option>
              </select>
            </div>

            <div className="mb-4">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.contextFromPreviousNodes || false}
                  onChange={(e) => handleConfigChange('contextFromPreviousNodes', e.target.checked)}
                  className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
                />
                <span className="text-sm font-medium text-foreground">Include Context from Previous Nodes</span>
              </label>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Max Turns (optional)
              </label>
              <input
                type="number"
                value={config.maxTurns || ''}
                onChange={(e) => handleConfigChange('maxTurns', e.target.value ? parseInt(e.target.value) : null)}
                placeholder="Unlimited"
                className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Tools (comma-separated)
              </label>
              <ExpandableTextField
                label="Tools"
                value={Array.isArray(config.tools) ? config.tools.join(', ') : ''}
                onChange={(val) => handleConfigChange('tools', val.split(',').map(t => t.trim()).filter(t => t))}
                placeholder="web_search, knowledge_base"
                isMultiline={false}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Knowledge Base ID
              </label>
              <Input
                value={config.knowledgeBaseId || ''}
                onChange={(e) => handleConfigChange('knowledgeBaseId', e.target.value || null)}
                placeholder="kb-uuid-123"
              />
            </div>
          </>
        );

      case 'action':
        return (
          <>
            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Label
              </label>
              <ExpandableTextField
                label="Label"
                value={config.label || ''}
                onChange={(val) => handleConfigChange('label', val)}
                placeholder="Action name"
                isMultiline={false}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Action Type
              </label>
              <select
                value={config.actionType || 'web_search'}
                onChange={(e) => handleConfigChange('actionType', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="web_search">Web Search</option>
                <option value="api_call">API Call</option>
                <option value="mcp_tool">MCP Tool</option>
              </select>
            </div>

            {config.actionType === 'web_search' && (
              <>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Search Query
                  </label>
                  <ExpandableTextField
                    label="Search Query"
                    value={config.config?.query || ''}
                    onChange={(val) => handleConfigChange('config', { ...config.config, query: val })}
                    placeholder="Enter search query..."
                    isMultiline={true}
                  />
                </div>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Max Results
                  </label>
                  <input
                    type="number"
                    value={config.config?.maxResults || 5}
                    onChange={(e) => handleConfigChange('config', { ...config.config, maxResults: parseInt(e.target.value) })}
                    placeholder="5"
                    className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
              </>
            )}

            {config.actionType === 'api_call' && (
              <>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Endpoint URL
                  </label>
                  <ExpandableTextField
                    label="Endpoint URL"
                    value={config.config?.endpoint || ''}
                    onChange={(val) => handleConfigChange('config', { ...config.config, endpoint: val })}
                    placeholder="https://api.example.com/endpoint"
                    isMultiline={false}
                  />
                </div>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Method
                  </label>
                  <select
                    value={config.config?.method || 'GET'}
                    onChange={(e) => handleConfigChange('config', { ...config.config, method: e.target.value })}
                    className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                    <option value="PUT">PUT</option>
                    <option value="DELETE">DELETE</option>
                  </select>
                </div>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Headers (JSON)
                  </label>
                  <ExpandableTextField
                    label="Headers (JSON)"
                    value={config.config?.headers || ''}
                    onChange={(val) => handleConfigChange('config', { ...config.config, headers: val })}
                    placeholder='{"Authorization": "Bearer token"}'
                    isMultiline={true}
                    className="font-mono text-xs"
                  />
                </div>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Body (JSON)
                  </label>
                  <ExpandableTextField
                    label="Body (JSON)"
                    value={config.config?.body || ''}
                    onChange={(val) => handleConfigChange('config', { ...config.config, body: val })}
                    placeholder='{"key": "value"}'
                    isMultiline={true}
                    className="font-mono text-xs"
                  />
                </div>
              </>
            )}

            {config.actionType === 'mcp_tool' && (
              <>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Tool Name
                  </label>
                  <ExpandableTextField
                    label="Tool Name"
                    value={config.config?.toolName || ''}
                    onChange={(val) => handleConfigChange('config', { ...config.config, toolName: val })}
                    placeholder="mcp_tool_name"
                    isMultiline={false}
                  />
                </div>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-foreground mb-2">
                    Parameters (JSON)
                  </label>
                  <ExpandableTextField
                    label="Parameters (JSON)"
                    value={config.config?.parameters || ''}
                    onChange={(val) => handleConfigChange('config', { ...config.config, parameters: val })}
                    placeholder='{"param1": "value1"}'
                    isMultiline={true}
                    className="font-mono text-xs"
                  />
                </div>
              </>
            )}
          </>
        );

      case 'hitl':
        return (
          <>
            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Label
              </label>
              <ExpandableTextField
                label="Label"
                value={config.label || ''}
                onChange={(val) => handleConfigChange('label', val)}
                placeholder="Review step name"
                isMultiline={false}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Review Mode
              </label>
              <select
                value={config.mode || 'review_and_edit'}
                onChange={(e) => handleConfigChange('mode', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="review_and_approve">Review and Approve</option>
                <option value="review_and_edit">Review and Edit</option>
                <option value="edit_only">Edit Only</option>
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Instructions
              </label>
              <ExpandableTextField
                label="Instructions"
                value={config.instructions || ''}
                onChange={(val) => handleConfigChange('instructions', val)}
                placeholder="Please review and approve the content before continuing..."
                isMultiline={true}
              />
            </div>

            <div className="mb-4">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.requireApproval || false}
                  onChange={(e) => handleConfigChange('requireApproval', e.target.checked)}
                  className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
                />
                <span className="text-sm font-medium text-foreground">Require Explicit Approval</span>
              </label>
            </div>

            <div className="mb-4">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.allowEditing || false}
                  onChange={(e) => handleConfigChange('allowEditing', e.target.checked)}
                  className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
                />
                <span className="text-sm font-medium text-foreground">Allow Content Editing</span>
              </label>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Editable Format
              </label>
              <select
                value={config.editableFormat || 'text'}
                onChange={(e) => handleConfigChange('editableFormat', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="text">Plain Text</option>
                <option value="markdown">Markdown</option>
                <option value="structured">Structured (JSON)</option>
              </select>
            </div>
          </>
        );

      case 'output':
      case 'end': // Support legacy 'end' node type
        return (
          <>
            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Label
              </label>
              <ExpandableTextField
                label="Label"
                value={config.label || ''}
                onChange={(val) => handleConfigChange('label', val)}
                placeholder="Output name"
                isMultiline={false}
              />
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Export Formats
              </label>
              <div className="space-y-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Array.isArray(config.exportFormats) && config.exportFormats.includes('text')}
                    onChange={(e) => {
                      const formats = Array.isArray(config.exportFormats) ? [...config.exportFormats] : [];
                      if (e.target.checked) {
                        if (!formats.includes('text')) formats.push('text');
                      } else {
                        const index = formats.indexOf('text');
                        if (index > -1) formats.splice(index, 1);
                      }
                      handleConfigChange('exportFormats', formats);
                    }}
                    className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
                  />
                  <span className="text-sm text-foreground">Text</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Array.isArray(config.exportFormats) && config.exportFormats.includes('pdf')}
                    onChange={(e) => {
                      const formats = Array.isArray(config.exportFormats) ? [...config.exportFormats] : [];
                      if (e.target.checked) {
                        if (!formats.includes('pdf')) formats.push('pdf');
                      } else {
                        const index = formats.indexOf('pdf');
                        if (index > -1) formats.splice(index, 1);
                      }
                      handleConfigChange('exportFormats', formats);
                    }}
                    className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
                  />
                  <span className="text-sm text-foreground">PDF</span>
                </label>
              </div>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-foreground mb-2">
                Display Mode
              </label>
              <select
                value={config.displayMode || 'conversational'}
                onChange={(e) => handleConfigChange('displayMode', e.target.value)}
                className="custom-select w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="conversational">Conversational</option>
                <option value="structured">Structured</option>
              </select>
            </div>
          </>
        );

      case 'start':
      case 'manual-input':
        return (
          <div className="mb-4">
            <label className="block text-sm font-medium text-foreground mb-2">
              Label
            </label>
            <ExpandableTextField
              label="Label"
              value={config.label || ''}
              onChange={(val) => handleConfigChange('label', val)}
              placeholder="Node label"
              isMultiline={false}
            />
            {nodeType === 'manual-input' && (
              <>
                <label className="block text-sm font-medium text-foreground mb-2 mt-4">
                  Placeholder
                </label>
                <ExpandableTextField
                  label="Placeholder"
                  value={config.placeholder || ''}
                  onChange={(val) => handleConfigChange('placeholder', val)}
                  placeholder="Enter your text here..."
                  isMultiline={false}
                />
                <label className="block text-sm font-medium text-foreground mb-2 mt-4">
                  Description
                </label>
                <ExpandableTextField
                  label="Description"
                  value={config.description || ''}
                  onChange={(val) => handleConfigChange('description', val)}
                  placeholder="Provide input to start the workflow"
                  isMultiline={true}
                />
              </>
            )}
          </div>
        );

      default:
        return (
          <div className="text-sm text-muted-foreground">
            No configuration options for this node type.
          </div>
        );
    }
  };

  // Get category color for node icon background
  const getCategoryColor = () => {
    const colorMap = {
      // Initiators (light cyan)
      'chat': '#A5F3FC',
      'scheduled-start': '#A5F3FC',
      'webhook': '#A5F3FC',
      'start': '#A5F3FC',
      'manual-input': '#A5F3FC',
      
      // Processors (blue)
      'agent': '#93C5FD',
      'researcher': '#93C5FD',
      'business-analyst': '#93C5FD',
      'opportunity-classifier': '#93C5FD',
      'data-classifier': '#93C5FD',
      'financial-modeler': '#93C5FD',
      'action': '#93C5FD',
      
      // Review (violet)
      'human-in-the-loop': '#C4B5FD',
      'hitl': '#C4B5FD',
      'ai-judge': '#C4B5FD',
      
      // Generators (yellow)
      'powerpoint-generator': '#8216c5',
      'pdf-generator': '#FCD34D',
      'excel-generator': '#FCD34D',
      'output': '#FCD34D',
      'end': '#FCD34D',
    };
    return colorMap[selectedNode.type] || 'var(--color-secondary)';
  };

  const catStyle = getNodeStyle(selectedNode.type);
  const panelGradient = getPanelGradient(selectedNode.type);

  return (
    <>
      <ConfirmModal
        isOpen={showDeleteConfirm}
        title="Delete Node"
        message={`Are you sure you want to delete "${selectedNode?.nodeType?.name || 'this node'}"? This action cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
      <div
        className="builder-config-panel overflow-y-auto flex-shrink-0 flex flex-col"
        style={{
          width: px(PANEL.width),
          padding: px(PANEL.padding),
          marginRight: px(24),
          marginTop: px(16),
          marginBottom: px(16),
          height: 'calc(100% - 32px)',
          borderRadius: px(PANEL.radius),
          borderWidth: PANEL.borderWidth,
          borderStyle: 'solid',
          borderColor: COLOR.darker,
          background: panelGradient,
          gap: px(PANEL.gap),
          // Expose the Figma scale as a CSS var so the input/select/textarea
          // styling in index.css (paddings, radii, font-size) can rescale too.
          '--fig-scale': px(1),
        }}
      >
        {/* Header (Figma 83:1496) — gap 12, icon 36px, title/subtitle + toggle */}
        <div className="flex items-center" style={{ gap: px(PANEL.header.gap) }}>
          {/* Header icon — Figma 86:1750 renders a 36×36 mask without a tile.
              We keep a subtle category-coloured tile so the icon remains
              readable against the panel gradient on every node type. */}
          <span
            className="flex items-center justify-center flex-shrink-0"
            style={{
              width: px(PANEL.header.iconSize),
              height: px(PANEL.header.iconSize),
              padding: px(6),
              borderRadius: px(8),
              backgroundColor: catStyle.iconBg,
            }}
          >
            {selectedNode.nodeType?.icon?.startsWith('/') ? (
              <img
                src={selectedNode.nodeType.icon}
                alt={selectedNode.nodeType.name}
                className="brightness-0 invert"
                style={{ width: px(24), height: px(24) }}
                draggable={false}
              />
            ) : (
              <span style={{ color: COLOR.white, fontSize: px(20) }}>{selectedNode.nodeType?.icon || '❓'}</span>
            )}
          </span>
          <div className="flex-1 min-w-0">
            <h3
              className="truncate"
              style={{
                color: COLOR.white,
                fontSize: px(FONT.subhead2Bold.size),
                lineHeight: `${px(FONT.subhead2Bold.height)}px`,
                fontWeight: FONT.subhead2Bold.weight,
              }}
            >
              {selectedNode.nodeType?.name || 'Unknown Node'}
            </h3>
            <p
              className="truncate"
              style={{
                color: COLOR.medium,
                fontSize: px(FONT.body2.size),
                lineHeight: `${px(FONT.body2.height)}px`,
                fontWeight: FONT.body2.weight,
              }}
            >
              {selectedNode.nodeType?.description || 'No description available'}
            </p>
          </div>

          {selectedNode.type !== 'chat' && selectedNode.type !== 'condition' && (
            <button
              type="button"
              role="switch"
              aria-checked={advancedMode}
              aria-label="Advanced mode"
              onClick={() => setAdvancedMode((v) => !v)}
              className="flex items-center hover:bg-white/5 transition-colors flex-shrink-0"
              style={{
                borderWidth: PANEL.toggle.border,
                borderStyle: 'solid',
                borderColor: COLOR.darker,
                borderRadius: px(PANEL.toggle.radius),
                gap: px(PANEL.toggle.gap),
                paddingLeft: px(PANEL.toggle.paddingLeft),
                paddingRight: px(PANEL.toggle.paddingRight),
                paddingTop: px(PANEL.toggle.paddingY),
                paddingBottom: px(PANEL.toggle.paddingY),
              }}
              title={advancedMode ? 'Hide advanced fields' : 'Show all fields (advanced mode)'}
            >
              <span
                className={`flex items-center transition-colors ${advancedMode ? 'justify-end' : 'justify-start'}`}
                style={{
                  width: px(PANEL.toggle.track.width),
                  padding: px(PANEL.toggle.track.padding),
                  borderRadius: px(PANEL.toggle.track.radius),
                  backgroundColor: advancedMode ? COLOR.rose : COLOR.darker,
                }}
              >
                <span
                  className="block bg-white shadow-sm"
                  style={{
                    width: px(PANEL.toggle.knob.width),
                    height: px(PANEL.toggle.knob.height),
                    borderRadius: px(PANEL.toggle.knob.radius),
                  }}
                />
              </span>
              <span
                className="whitespace-nowrap"
                style={{
                  color: COLOR.light,
                  fontSize: px(FONT.caption.size),
                  lineHeight: `${px(FONT.caption.height)}px`,
                  fontWeight: FONT.caption.weight,
                }}
              >
                Advanced mode
              </span>
            </button>
          )}
        </div>

        {/* Divider (Figma 83:1441) — 1px #464646 across the full width */}
        <div style={{ height: PANEL.divider.height, backgroundColor: COLOR.darker, width: '100%' }} />

        {/* Configuration fields — Figma goes straight from header divider into
            the field stack. The save/unsaved indicator is kept inline. */}
        <div className="flex-1 overflow-y-auto pr-1 -mr-1 relative">
          {(showSavedIndicator || hasUnsavedChanges) && (
            <div className="absolute top-0 right-1 z-10">
              {showSavedIndicator && (
                <span className="flex items-center gap-1" style={{ color: COLOR.medium, fontSize: 12 }}>
                  ✓ Saved
                </span>
              )}
              {hasUnsavedChanges && !showSavedIndicator && (
                <span className="flex items-center gap-1" style={{ color: '#fbbf24', fontSize: 12 }}>
                  • Unsaved
                </span>
              )}
            </div>
          )}
          {renderConfigFields()}
        </div>

        {hasUnsavedChanges && (
          <div className="mt-4 pt-3" style={{ borderTop: `1px solid ${COLOR.darker}` }}>
            <button
              type="button"
              onClick={handleSaveChanges}
              className="w-full flex items-center justify-center transition-[background-color,border-color,box-shadow,transform] duration-200"
              style={{
                boxSizing: 'border-box',
                height: px(PANEL.delete.height),
                borderWidth: PANEL.delete.borderWidth,
                borderStyle: 'solid',
                borderColor: NAVBAR.secondaryButton.border,
                borderRadius: px(PANEL.delete.radius),
                gap: px(PANEL.delete.gap),
                paddingLeft: px(PANEL.delete.paddingLeft),
                paddingRight: px(PANEL.delete.paddingRight),
                paddingTop: px(PANEL.delete.paddingY),
                paddingBottom: px(PANEL.delete.paddingY),
                backgroundColor: NAVBAR.secondaryButton.bg,
                color: NAVBAR.secondaryButton.text,
                boxShadow: NAVBAR.secondaryButton.shadow,
              }}
              onMouseEnter={(e) => {
                const s = NAVBAR.secondaryButton;
                e.currentTarget.style.backgroundColor = s.bgHover;
                e.currentTarget.style.borderColor = s.borderHover;
                e.currentTarget.style.boxShadow = s.shadowHover;
              }}
              onMouseLeave={(e) => {
                const s = NAVBAR.secondaryButton;
                e.currentTarget.style.backgroundColor = s.bg;
                e.currentTarget.style.borderColor = s.border;
                e.currentTarget.style.boxShadow = s.shadow;
                e.currentTarget.style.transform = 'none';
              }}
              onMouseDown={(e) => {
                e.currentTarget.style.transform = 'scale(0.98)';
              }}
              onMouseUp={(e) => {
                e.currentTarget.style.transform = 'none';
              }}
            >
              <AppIcon name="save" size={px(PANEL.delete.iconSize)} color="currentColor" weight="regular" />
              <span
                style={{
                  fontSize: px(FONT.button.size),
                  lineHeight: `${px(FONT.button.height)}px`,
                  fontWeight: FONT.button.weight,
                }}
              >
                Save Changes
              </span>
            </button>
            <div className="mt-2 text-center" style={{ color: COLOR.medium, fontSize: px(12) }}>
              Auto-saves after 2 seconds
            </div>
          </div>
        )}

        <div className="mt-4 pt-3" style={{ borderTop: `1px solid ${COLOR.darker}` }}>
          <button
            type="button"
            onClick={handleDelete}
            className="w-full flex items-center justify-center transition-[background-color,border-color,box-shadow,transform] duration-200"
            style={{
              height: px(PANEL.delete.height),
              borderWidth: PANEL.delete.borderWidth,
              borderStyle: 'solid',
              borderColor: COLOR.deleteBorder,
              borderRadius: px(PANEL.delete.radius),
              gap: px(PANEL.delete.gap),
              paddingLeft: px(PANEL.delete.paddingLeft),
              paddingRight: px(PANEL.delete.paddingRight),
              paddingTop: px(PANEL.delete.paddingY),
              paddingBottom: px(PANEL.delete.paddingY),
              backgroundColor: COLOR.deleteBg,
              color: COLOR.deleteSoft,
              boxShadow: 'inset 0 1px 0 rgba(255, 107, 122, 0.12)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = COLOR.deleteBgHover;
              e.currentTarget.style.borderColor = COLOR.deleteBorderHover;
              e.currentTarget.style.boxShadow = 'inset 0 1px 0 rgba(255, 107, 122, 0.2), 0 0 14px rgba(255, 77, 110, 0.1)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = COLOR.deleteBg;
              e.currentTarget.style.borderColor = COLOR.deleteBorder;
              e.currentTarget.style.boxShadow = 'inset 0 1px 0 rgba(255, 107, 122, 0.12)';
              e.currentTarget.style.transform = 'none';
            }}
            onMouseDown={(e) => {
              e.currentTarget.style.transform = 'scale(0.98)';
            }}
            onMouseUp={(e) => {
              e.currentTarget.style.transform = 'none';
            }}
          >
            <AppIcon name="trash" size={px(PANEL.delete.iconSize)} color="currentColor" weight="regular" />
            <span style={{ fontSize: px(FONT.button.size), lineHeight: `${px(FONT.button.height)}px`, fontWeight: FONT.button.weight }}>
              Delete Node
            </span>
          </button>
          <div className="mt-2 text-center" style={{ color: COLOR.medium, fontSize: px(12) }}>
            Press Delete or Backspace to remove
          </div>
        </div>
      </div>
    </>
  );
}
