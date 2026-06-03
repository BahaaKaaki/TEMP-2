import { useEffect, useState, useRef, useCallback, lazy, Suspense } from 'react';
import Canvas from './Canvas';
import NodePalette from './NodePalette';
import NodeConfigPanel from './NodeConfigPanel';

const ChatView = lazy(() => import('../chat/ChatView'));
import { useWorkflow } from '@/context/WorkflowContext';
import { useAuth } from '@/context/AuthContext';
import { APP_DATA } from '@/data/appData';
import { ensureDefaultChatNode } from '@/utils/ensureDefaultChatNode';
import { buildWorkflowGraphFromCanvas } from '@/utils/workflowGraph';
import { buildCanvasPayloadFromWorkflow } from '@/utils/hydrateWorkflowCanvas';
import { createWorkflow, updateWorkflow, publishWorkflow, createChatSession, deleteChatSession, uploadWorkflowIcon, deleteWorkflowIcon, getWorkflow } from '@/api/client';
import AlertModal from '../ui/AlertModal';
import Toast from '../ui/Toast';
import ConfirmModal from '../ui/ConfirmModal';
import PromptModal from '../ui/PromptModal';
import WorkflowDescriptionModal from './WorkflowDescriptionModal';
import WorkflowIconPicker from '../ui/WorkflowIconPicker';
import FeedbackModal from '../ui/FeedbackModal';
import VersionHistoryPanel from './VersionHistoryPanel';
import { COLOR, FONT, TOP_BAR, NAVBAR, BACKGROUND } from './figmaSpec';
import { useFigmaPx } from './useFigmaScale';
import AppIcon from '../ui/AppIcon';

// Figma 86:2447 — the entire workflow-builder frame sits on a black canvas
// with the editor's faint dotted grid showing through.  Render it once at the
// root so the dots appear BEHIND the top bar (Apex OS / Feedback / MH) and
// behind the navbar chip — exactly like Figma where Apex OS sits directly on
// the dotted canvas.  Opacity stays low (~18%) so the grid is "barely there".
const ROOT_DOT_GRID = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='${BACKGROUND.tile}' height='${BACKGROUND.tile}'><circle cx='${BACKGROUND.tile / 2}' cy='${BACKGROUND.tile / 2}' r='${BACKGROUND.dotRadius}' fill='white' fill-opacity='0.18'/></svg>")`;

// Figma 86:2462/2463 (Test/Save/launch) — height 48, pl 12, pr 16, py 8, gap 4.
// Toolbar uses 10px radius (less pill-like); Publish stays rose primary CTA.
// Returned as a factory so the dimensions get rescaled for the viewport.
// `box-sizing: border-box` guarantees all three pills (Test / Save / launch)
// resolve to *identical* outer dimensions regardless of any global CSS reset.
const makePillStyle = (px) => ({
  boxSizing: 'border-box',
  height: px(NAVBAR.button.height),
  paddingLeft: px(NAVBAR.button.paddingLeft),
  paddingRight: px(NAVBAR.button.paddingRight),
  paddingTop: px(NAVBAR.button.paddingY),
  paddingBottom: px(NAVBAR.button.paddingY),
  gap: px(NAVBAR.button.gap),
  borderRadius: px(NAVBAR.button.radius),
  flexShrink: 0,
});
const makeSecondaryPillStyle = (px) => ({
  ...makePillStyle(px),
  backgroundColor: NAVBAR.secondaryButton.bg,
  color: NAVBAR.secondaryButton.text,
  border: `${px(1)}px solid ${NAVBAR.secondaryButton.border}`,
  boxShadow: NAVBAR.secondaryButton.shadow,
});
const applySecondaryPillHover = (el, hovered) => {
  const s = NAVBAR.secondaryButton;
  el.style.backgroundColor = hovered ? s.bgHover : s.bg;
  el.style.borderColor = hovered ? s.borderHover : s.border;
  el.style.boxShadow = hovered ? s.shadowHover : s.shadow;
};
const makePillLabel = (px) => ({
  fontSize: px(FONT.button.size),
  lineHeight: `${px(FONT.button.height)}px`,
  fontWeight: FONT.button.weight,
});
const makeToolbarIconStyle = (px) => ({
  width: px(NAVBAR.button.iconSize),
  height: px(NAVBAR.button.iconSize),
  flexShrink: 0,
  objectFit: 'contain',
});

export default function BuilderView() {
  const { state, dispatch, ACTIONS, flushPendingNodeConfig } = useWorkflow();
  const { user, logout } = useAuth();
  const workflowAccess =
    state.selectedWorkflow?.shareAccess
    || (state.selectedWorkflow?.permission === 'write'
      ? 'write'
      : state.selectedWorkflow?.permission === 'read'
        ? 'read'
        : 'owner');
  const isReadOnly = workflowAccess === 'read';
  const [showFeedback, setShowFeedback] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const [showSavePrompt, setShowSavePrompt] = useState(false);
  const [showPublishConfirm, setShowPublishConfirm] = useState(false);
  const [showEmptyWorkflowAlert, setShowEmptyWorkflowAlert] = useState(false);
  
  // Modal state
  const [alertModal, setAlertModal] = useState({ isOpen: false, title: '', message: '', variant: 'error' });
  const [showSaveFirstAlert, setShowSaveFirstAlert] = useState(false);
  const [showPublishEmptyAlert, setShowPublishEmptyAlert] = useState(false);
  const [showSaveErrorAlert, setShowSaveErrorAlert] = useState(false);
  const [saveErrorMessage, setSaveErrorMessage] = useState('');
  const [saveToast, setSaveToast] = useState(null);
  const [showPublishSuccessAlert, setShowPublishSuccessAlert] = useState(false);
  const [showPublishErrorAlert, setShowPublishErrorAlert] = useState(false);
  const [publishErrorMessage, setPublishErrorMessage] = useState('');
  const [showReplacePendingConfirm, setShowReplacePendingConfirm] = useState(false);
  const [showUnconnectedNodesAlert, setShowUnconnectedNodesAlert] = useState(false);
  const [unconnectedNodesList, setUnconnectedNodesList] = useState('');
  const [showMissingSchemaAlert, setShowMissingSchemaAlert] = useState(false);
  const [missingSchemaNodesList, setMissingSchemaNodesList] = useState('');
  const [showDescriptionModal, setShowDescriptionModal] = useState(false);
  const [workflowDescription, setWorkflowDescription] = useState(null);
  const [workflowIcon, setWorkflowIcon] = useState(null);
  const [showVersionHistory, setShowVersionHistory] = useState(false);
  const [showSettingsMenu, setShowSettingsMenu] = useState(false);

  // Test chat state
  const [showTestChat, setShowTestChat] = useState(false);
  const [testSessionId, setTestSessionId] = useState(null);
  const testSessionIdRef = useRef(null);
  const testSessionObjRef = useRef(null);
  const testCanvasSnapshotRef = useRef(null);
  const isSavingFromCleanupRef = useRef(false);
  const lastSavedSnapshotRef = useRef(null);

  /** Canvas map with pending config-panel edits applied (no waiting on React state). */
  const canvasNodesForSave = (pendingFlush) => {
    const nodes = new Map(state.canvasNodes);
    if (pendingFlush?.nodeId) {
      const node = nodes.get(pendingFlush.nodeId);
      if (node) {
        nodes.set(pendingFlush.nodeId, { ...node, config: pendingFlush.config });
      }
    }
    return nodes;
  };

  const nodeConfigForSave = (nodeId, node) => node.config;

  const handleSave = async (silent = false, force = false) => {
    if (isReadOnly) {
      if (!silent) {
        setAlertModal({
          isOpen: true,
          title: 'View only',
          message: 'You have read-only access to this workflow.',
          variant: 'warning',
        });
      }
      return;
    }
    if (state.canvasNodes.size === 0) {
      if (!silent) {
        setShowEmptyWorkflowAlert(true);
      }
      return;
    }

    try {
      setIsSaving(true);
      const pendingFlush = flushPendingNodeConfig?.() ?? null;
      const nodesMap = canvasNodesForSave(pendingFlush);
      const workflow = state.selectedWorkflow;
      const isUpdate = workflow && workflow.id;
      let workflowName;
      if (isUpdate) {
        // For existing workflows, keep the same name
        workflowName = workflow.name;
      } else if (state.newWorkflowName) {
        workflowName = state.newWorkflowName;
      } else {
        if (!silent) {
          setShowSavePrompt(true);
          setIsSaving(false);
          return;
        } else {
          setIsSaving(false);
          return; // Cannot auto-save a new workflow without a name
        }
      }

      const nodesArray = Array.from(nodesMap.entries()).map(([id, node]) => {
        const config = nodeConfigForSave(id, node);
        console.log(`🔍 SAVING Node ${id}:`, {
          type: node.type,
          modelProvider: config?.modelProvider,
          modelName: config?.modelName,
          fullConfig: config
        });
        return {
          id,
          type: node.type,
          position: { x: node.x, y: node.y },
          data: {
            label: config?.label || node.nodeType?.name || 'Node',
            config
          },
          config,
        };
      });

      const edgesArray = state.connections.map(conn => ({
        id: conn.id,
        source: conn.source,
        target: conn.target,
        sourceHandle: conn.sourceHandle || null,
        targetHandle: conn.targetHandle || null,
        conditionId: conn.conditionId || null, // Include conditionId for conditional routing
      }));

      const existingMeta = workflow?.meta ? (() => { try { return JSON.parse(workflow.meta); } catch { return {}; } })() : {};
      const nodesJson = JSON.stringify(nodesArray);
      const connectionsJson = JSON.stringify(edgesArray);

      // Skip silent saves when content hasn't changed since last save
      const fingerprint = nodesJson + connectionsJson;
      if (silent && !force && lastSavedSnapshotRef.current === fingerprint) {
        setIsSaving(false);
        return;
      }

      const workflowData = {
        name: workflowName,
        nodes: nodesJson,
        connections: connectionsJson,
        meta: JSON.stringify({ ...existingMeta, detailedDescription: workflowDescription }),
        ...(!isUpdate && state.newWorkflowDescription
          ? { description: state.newWorkflowDescription }
          : {}),
      };
      // Only mark active when builder test chat is running; never deactivate on save.
      if (testSessionIdRef.current) {
        workflowData.active = true;
      } else if (!isUpdate) {
        workflowData.active = false;
      }

      let result;
      if (isUpdate) {
        result = await updateWorkflow(workflow.id, workflowData);
        if (!silent) {
          setSaveToast({
            title: 'Saved',
            message: `Workflow "${workflowName}" saved successfully.`,
          });
        }
      } else {
        result = await createWorkflow(workflowData);
        if (!silent) {
          setSaveToast({
            title: 'Created',
            message: `Workflow "${workflowName}" created successfully.`,
          });
        }
      }

      const savedPayload = {
        name: workflowName,
        id: result.id,
        ...result,
        nodes: workflowData.nodes,
        connections: workflowData.connections,
      };
      dispatch({ type: ACTIONS.PUBLISH_WORKFLOW, payload: savedPayload });
      dispatch({ type: ACTIONS.SELECT_WORKFLOW, payload: savedPayload });
      hydrateCanvas({
        id: result.id,
        name: workflowName,
        nodes: workflowData.nodes,
        connections: workflowData.connections,
      });

      setLastSaved(new Date());
      lastSavedSnapshotRef.current = fingerprint;

      const currentSnapshot = workflowData.nodes + workflowData.connections;
      if (isSavingFromCleanupRef.current) {
        testCanvasSnapshotRef.current = currentSnapshot;
      }

      if (testSessionIdRef.current && !isSavingFromCleanupRef.current) {
        if (testCanvasSnapshotRef.current !== currentSnapshot) {
          const sid = testSessionIdRef.current;
          const wfId = state.selectedWorkflow?.id;
          if (wfId) localStorage.removeItem(`test_session_${wfId}`);
          testSessionIdRef.current = null;
          testSessionObjRef.current = null;
          testCanvasSnapshotRef.current = null;
          setTestSessionId(null);
          setShowTestChat(false);
          dispatch({ type: ACTIONS.SELECT_SESSION, payload: null });
          deleteChatSession(sid, true).catch(() => {});
        }
      }
    } catch (error) {
      if (!silent) {
        setSaveErrorMessage(error.message);
        setShowSaveErrorAlert(true);
      }
    } finally {
      setIsSaving(false);
    }
  };

  const handleIconUpload = useCallback(async (file) => {
    const workflow = state.selectedWorkflow;
    if (!workflow?.id) return;
    try {
      const { icon } = await uploadWorkflowIcon(workflow.id, file);
      setWorkflowIcon(icon);
      dispatch({ type: ACTIONS.SELECT_WORKFLOW, payload: { ...workflow, icon } });
    } catch (err) {
      console.error('Failed to upload icon:', err);
    }
  }, [state.selectedWorkflow, dispatch, ACTIONS]);

  const handleIconRemove = useCallback(async () => {
    const workflow = state.selectedWorkflow;
    if (!workflow?.id) return;
    try {
      await deleteWorkflowIcon(workflow.id);
      setWorkflowIcon(null);
      dispatch({ type: ACTIONS.SELECT_WORKFLOW, payload: { ...workflow, icon: null } });
    } catch (err) {
      console.error('Failed to remove icon:', err);
    }
  }, [state.selectedWorkflow, dispatch, ACTIONS]);

  // Debounced auto-save: fires 2 minutes after the last canvas change.
  // This avoids creating hundreds of versions from rapid edits while
  // still preserving work if the user walks away.
  const autoSaveTimerRef = useRef(null);
  useEffect(() => {
    const workflow = state.selectedWorkflow;
    if (!workflow || !workflow.id || state.canvasNodes.size === 0) return;

    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      handleSave(true);
    }, 120_000); // 2 minutes of inactivity

    return () => {
      if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    };
  }, [state.selectedWorkflow, state.canvasNodes, state.connections]);

  const validateWorkflow = () => {
    const workflow = state.selectedWorkflow;
    if (!workflow || !workflow.id) {
      setShowSaveFirstAlert(true);
      return false;
    }

    if (state.canvasNodes.size === 0) {
      setShowPublishEmptyAlert(true);
      return false;
    }

    const nodeIds = Array.from(state.canvasNodes.keys());
    const connections = state.connections;
    const unconnectedNodes = [];

    nodeIds.forEach(nodeId => {
      const node = state.canvasNodes.get(nodeId);
      if (node?.type === 'sticky-note' || node?.type === 'chat') return;
      const isConnected = connections.some(
        conn => conn.source === nodeId || conn.target === nodeId
      );
      if (!isConnected) {
        const nodeName = node?.config?.label || node?.nodeType?.name || nodeId;
        unconnectedNodes.push(nodeName);
      }
    });

    if (unconnectedNodes.length > 0) {
      setUnconnectedNodesList(unconnectedNodes.join(', '));
      setShowUnconnectedNodesAlert(true);
      return false;
    }

    const agentsWithoutSchema = [];
    nodeIds.forEach(nodeId => {
      const node = state.canvasNodes.get(nodeId);
      if (node?.type === 'agent') {
        const schema = node?.config?.outputSchema;
        if (!schema || (typeof schema === 'string' && schema.trim() === '')) {
          const nodeName = node?.config?.label || node?.nodeType?.name || nodeId;
          agentsWithoutSchema.push(nodeName);
        }
      }
    });

    if (agentsWithoutSchema.length > 0) {
      setMissingSchemaNodesList(agentsWithoutSchema.join(', '));
      setShowMissingSchemaAlert(true);
      return false;
    }

    return true;
  };

  const handlePublish = async () => {
    if (!validateWorkflow()) return;
    setShowPublishConfirm(true);
  };

  const confirmPublish = async (force = false) => {
    const workflow = state.selectedWorkflow;
    setShowPublishConfirm(false);

    try {
      await handleSave(true);
      await publishWorkflow(workflow.id, { force });

      dispatch({
        type: ACTIONS.SELECT_WORKFLOW,
        payload: { ...workflow, isDraft: false, active: true }
      });

      setShowPublishSuccessAlert(true);
    } catch (error) {
      if (error.hasPendingSubmission) {
        setShowReplacePendingConfirm(true);
        return;
      }
      console.error('Failed to publish workflow:', error);
      setPublishErrorMessage(error.message);
      setShowPublishErrorAlert(true);
    }
  };

  const cleanupTestSession = useCallback(async () => {
    const sid = testSessionIdRef.current;
    if (sid) {
      const workflowId = state.selectedWorkflow?.id;
      if (workflowId) localStorage.removeItem(`test_session_${workflowId}`);
      try { await deleteChatSession(sid, true); } catch(e) { /* best-effort */ }
      dispatch({ type: ACTIONS.SELECT_SESSION, payload: null });
      testSessionIdRef.current = null;
      testSessionObjRef.current = null;
      testCanvasSnapshotRef.current = null;
      setTestSessionId(null);
      setShowTestChat(false);
    }
  }, [dispatch, ACTIONS, state.selectedWorkflow?.id]);

  useEffect(() => {
    const workflowId = state.selectedWorkflow?.id;
    if (!workflowId) return;
    try {
      const stored = localStorage.getItem(`test_session_${workflowId}`);
      if (stored) {
        const { _canvasSnapshot, ...sessionObj } = JSON.parse(stored);
        testSessionIdRef.current = sessionObj.id;
        testSessionObjRef.current = sessionObj;
        testCanvasSnapshotRef.current = _canvasSnapshot || null;
        setTestSessionId(sessionObj.id);
      }
    } catch (e) { /* ignore corrupt data */ }
  }, [state.selectedWorkflow?.id]);

  const handleTestChat = async () => {
    if (testSessionIdRef.current && testSessionObjRef.current) {
      dispatch({ type: ACTIONS.SELECT_SESSION, payload: testSessionObjRef.current });
      setShowTestChat(true);
      return;
    }

    if (!validateWorkflow()) return;

    try {
      flushPendingNodeConfig?.();
      isSavingFromCleanupRef.current = true;
      await handleSave(true, true);
      isSavingFromCleanupRef.current = false;
      const graph = buildWorkflowGraphFromCanvas(state.canvasNodes, state.connections);
      dispatch({
        type: ACTIONS.SELECT_WORKFLOW,
        payload: {
          ...state.selectedWorkflow,
          nodes: graph.nodes,
          connections: graph.connections,
        },
      });
      const workflowId = state.selectedWorkflow.id;
      const newSession = await createChatSession(workflowId, {
        name: `Test - ${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`,
        description: 'Test session'
      });
      testSessionIdRef.current = newSession.id;
      testSessionObjRef.current = newSession;
      setTestSessionId(newSession.id);
      localStorage.setItem(`test_session_${workflowId}`, JSON.stringify({
        ...newSession,
        _canvasSnapshot: testCanvasSnapshotRef.current,
      }));
      dispatch({ type: ACTIONS.SELECT_SESSION, payload: newSession });
      setShowTestChat(true);
    } catch (error) {
      isSavingFromCleanupRef.current = false;
      console.error('Failed to start test chat:', error);
    }
  };

  const handleCloseTestChat = () => {
    setShowTestChat(false);
  };

  const handleClearTestSession = async () => {
    await cleanupTestSession();
  };

  const handleSaveWithName = async (workflowName) => {
    setShowSavePrompt(false);
    setIsSaving(true);

    try {
      const pendingFlush = flushPendingNodeConfig?.() ?? null;
      const nodesMap = canvasNodesForSave(pendingFlush);
      const nodesArray = Array.from(nodesMap.entries()).map(([id, node]) => {
        const config = nodeConfigForSave(id, node);
        return {
          id,
          type: node.type,
          position: { x: node.x, y: node.y },
          data: {
            label: config?.label || node.nodeType?.name || 'Node',
            config
          },
          config,
        };
      });

      const edgesArray = state.connections.map(conn => ({
        id: conn.id,
        source: conn.source,
        target: conn.target,
        sourceHandle: conn.sourceHandle || null,
        targetHandle: conn.targetHandle || null,
        conditionId: conn.conditionId || null,
      }));

      const workflowData = {
        name: workflowName,
        active: !!testSessionIdRef.current,
        isDraft: true,
        nodes: JSON.stringify(nodesArray),
        connections: JSON.stringify(edgesArray),
        meta: JSON.stringify({ detailedDescription: workflowDescription }),
        ...(state.newWorkflowDescription ? { description: state.newWorkflowDescription } : {}),
      };

      const result = await createWorkflow(workflowData);
      
      const savedPayload = {
        name: workflowName,
        id: result.id,
        ...result,
        nodes: workflowData.nodes,
        connections: workflowData.connections,
      };
      dispatch({ type: ACTIONS.PUBLISH_WORKFLOW, payload: savedPayload });
      dispatch({ type: ACTIONS.SELECT_WORKFLOW, payload: savedPayload });
      hydrateCanvas({
        id: result.id,
        name: workflowName,
        nodes: workflowData.nodes,
        connections: workflowData.connections,
      });

      setLastSaved(new Date());
      lastSavedSnapshotRef.current = workflowData.nodes + workflowData.connections;
      setSaveToast({
        title: 'Created',
        message: `Workflow "${workflowName}" created successfully.`,
      });
    } catch (error) {
      setSaveErrorMessage(error.message);
      setShowSaveErrorAlert(true);
    } finally {
      setIsSaving(false);
    }
  };

  const exportWorkflowJSON = () => {
    const workflow = {
      workflow: {
        nodes: Array.from(state.canvasNodes.entries()).map(([id, node]) => ({
          id,
          type: node.type,
          position: { x: node.x, y: node.y },
          data: {
            label: node.config?.label || node.nodeType?.name || 'Node',
            config: node.config
          },
          config: node.config,
        })),
        connections: state.connections.map(conn => ({
          id: conn.id,
          source: conn.source,
          target: conn.target,
          sourceHandle: conn.sourceHandle || null,
          targetHandle: conn.targetHandle || null,
          conditionId: conn.conditionId || null, // Include conditionId for conditional routing
        })),
      }
    };

    const dataStr = JSON.stringify(workflow, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
    const exportFileDefaultName = `workflow_${Date.now()}.json`;
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
  };

  const importWorkflowJSON = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const data = JSON.parse(event.target.result);
          const workflow = data.workflow || data;
          const nodes = workflow.nodes.map(node => ({
            id: node.id,
            type: node.type,
            x: node.position?.x || node.x || 100,
            y: node.position?.y || node.y || 100,
            config: node.config || node.data?.config || {},
            nodeType: APP_DATA.nodeTypes.flatMap(cat => cat.nodes).find(n => n.id === node.type) || 
                      { id: node.type, name: node.type, icon: '❓', color: '#666' }
          }));
          const connections = (workflow.connections || workflow.edges || []).map(edge => ({
            id: edge.id || `${edge.source}-${edge.target}`,
            source: edge.source,
            target: edge.target,
            sourceHandle: edge.sourceHandle || null,
            targetHandle: edge.targetHandle || null,
            conditionId: edge.conditionId || null  // ✅ Preserve conditionId from imported files
          }));
          dispatch({ type: ACTIONS.LOAD_TEMPLATE, payload: { nodes, connections } });
        } catch (error) {
          alert(`Failed to import: ${error.message}`);
        }
      };
      reader.readAsText(file);
    };
    input.click();
  };


  const hydrateCanvas = useCallback((workflow) => {
    try {
      const payload = buildCanvasPayloadFromWorkflow(workflow);
      dispatch({
        type: ACTIONS.LOAD_TEMPLATE,
        payload,
      });

      try {
        const meta = workflow.meta ? JSON.parse(workflow.meta) : {};
        setWorkflowDescription(meta.detailedDescription || null);
      } catch {
        setWorkflowDescription(null);
      }
      setWorkflowIcon(workflow.icon?.startsWith('/') ? workflow.icon : null);
    } catch (error) {
      console.error('Failed to load workflow:', error);
    }
  }, [dispatch, ACTIONS]);

  // Load full workflow graph from API (shared-with-me cards only carry id/metadata)
  useEffect(() => {
    const wfId = state.selectedWorkflow?.id;
    if (!wfId || state.currentView !== 'builder') return;
    let cancelled = false;
    (async () => {
      try {
        const fresh = await getWorkflow(wfId);
        if (cancelled) return;
        dispatch({
          type: ACTIONS.SELECT_WORKFLOW,
          payload: { ...state.selectedWorkflow, ...fresh },
        });
        hydrateCanvas(fresh);
      } catch (err) {
        console.error('Failed to load workflow for builder:', err);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.selectedWorkflow?.id, state.currentView]);

  // Default chat node only for brand-new workflows (no DB id). Saved workflows
  // load via getWorkflow + hydrateCanvas; injecting chat here would flash stale
  // state over the API graph while the fetch is in flight.
  useEffect(() => {
    if (state.currentView !== 'builder') return;
    if (state.selectedWorkflow?.id) return;
    if (state.canvasNodes.size > 0) return;
    const { nodes, connections } = ensureDefaultChatNode([], []);
    dispatch({
      type: ACTIONS.LOAD_TEMPLATE,
      payload: { nodes, connections },
    });
  }, [state.currentView, state.selectedWorkflow?.id, state.canvasNodes.size, dispatch, ACTIONS]);

  // Seed description from "Create Workflow" modal when starting a new workflow
  useEffect(() => {
    if (!state.selectedWorkflow?.id && state.newWorkflowDescription) {
      setWorkflowDescription(state.newWorkflowDescription);
    }
  }, [state.newWorkflowDescription, state.selectedWorkflow?.id]);

  const handleVersionRestore = (restoredWorkflow) => {
    dispatch({ type: ACTIONS.SELECT_WORKFLOW, payload: restoredWorkflow });
    hydrateCanvas(restoredWorkflow);
    setShowVersionHistory(false);
  };

  // Initials for avatar (Figma 86:2448 — rose pill with "MH")
  const initials = (() => {
    if (user?.firstName && user?.lastName) {
      return `${user.firstName[0]}${user.lastName[0]}`.toUpperCase();
    }
    if (user?.firstName) return user.firstName[0].toUpperCase();
    if (user?.email) return user.email[0].toUpperCase();
    return 'U';
  })();

  const hasSavedWorkflow = !!state.selectedWorkflow?.id;
  const { px } = useFigmaPx();
  const PILL_SECONDARY = makeSecondaryPillStyle(px);
  const PILL_PRIMARY = {
    ...makePillStyle(px),
    backgroundColor: NAVBAR.primaryButton.bg,
    color: NAVBAR.primaryButton.text,
    border: 'none',
  };
  const PILL_LABEL = makePillLabel(px);
  const ICON_TOOLBAR = makeToolbarIconStyle(px);

  return (
    <div
      className="flex flex-col h-full text-white"
      style={{
        backgroundColor: BACKGROUND.bg,
        backgroundImage: ROOT_DOT_GRID,
        backgroundSize: `${BACKGROUND.tile}px ${BACKGROUND.tile}px`,
        backgroundPosition: '0 0',
        backgroundRepeat: 'repeat',
      }}
    >
      {/* ============================================================== */}
      {/* TOP BAR (Figma 86:2447 root):                                   */}
      {/*   • ApexOS logo @ left 30 / top 28, 238.65 × 54.535             */}
      {/*   • Feedback pill @ left 1701 / top 31, h 48                    */}
      {/*   • MH avatar @ left 1848 / top 31, 48 × 48                     */}
      {/* All values rescaled by useFigmaPx() so 1920px-design dims fit   */}
      {/* a 1440 / 1280 / etc. viewport without looking gigantic.         */}
      {/* ============================================================== */}
      <div
        className="flex items-center justify-between shrink-0"
        style={{
          paddingLeft: px(30),
          paddingRight: px(24),
          paddingTop: px(TOP_BAR.logo.top),
          paddingBottom: px(14),
        }}
      >
        <img
          src="/icons/apex-os-logo.svg"
          alt="Apex OS"
          style={{ width: px(TOP_BAR.logo.width), height: px(TOP_BAR.logo.height) }}
          draggable={false}
        />
        <div className="flex items-center" style={{ gap: px(16) }}>
          <button
            onClick={() => setShowFeedback(true)}
            className="flex items-center transition-colors"
            style={PILL_SECONDARY}
            onMouseEnter={(e) => applySecondaryPillHover(e.currentTarget, true)}
            onMouseLeave={(e) => applySecondaryPillHover(e.currentTarget, false)}
            title="Share feedback"
          >
            <AppIcon name="feedback" size={ICON_TOOLBAR.width} color="currentColor" weight="regular" />
            <span className="hidden sm:inline" style={PILL_LABEL}>Feedback</span>
          </button>
          <div className="relative">
            <button
              onClick={() => setShowUserMenu((v) => !v)}
              className="flex items-center justify-center hover:bg-[#c52a45] transition-colors"
              style={{
                width: px(TOP_BAR.avatar.size),
                height: px(TOP_BAR.avatar.size),
                padding: px(TOP_BAR.avatar.padding),
                borderRadius: px(TOP_BAR.avatar.radius),
                borderWidth: TOP_BAR.avatar.borderWidth,
                borderStyle: 'solid',
                borderColor: COLOR.roseLight,
                backgroundColor: COLOR.rose,
                color: COLOR.white,
                fontSize: px(FONT.body2Bold.size),
                lineHeight: `${px(FONT.body2Bold.height)}px`,
                fontWeight: FONT.body2Bold.weight,
              }}
              title={user?.email || 'User'}
            >
              {initials}
            </button>
            {showUserMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowUserMenu(false)} />
                <div className="absolute right-0 mt-2 w-64 bg-[#1a1a1a] border border-[#464646] rounded-2xl shadow-xl z-20 overflow-hidden">
                  <div className="p-4 border-b border-[#464646]">
                    <p className="font-semibold text-sm text-white">
                      {user?.firstName && user?.lastName
                        ? `${user.firstName} ${user.lastName}`
                        : user?.firstName || 'User'}
                    </p>
                    <p className="text-xs text-[#b5b5b5] mt-1">{user?.email}</p>
                  </div>
                  <div className="p-2">
                    <button
                      onClick={() => { logout(); setShowUserMenu(false); }}
                      className="w-full text-left px-3 py-2 text-sm text-[#b5b5b5] hover:text-white hover:bg-white/5 rounded-md transition-colors"
                    >
                      Sign out
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Workflow toolbar — hidden while test chat is open (test uses its own bar) */}
      {!showTestChat && (
      <div
        className="flex items-center shrink-0"
        style={{
          marginLeft: px(24),
          marginRight: px(24),
          marginTop: px(8),
          backgroundColor: COLOR.darkest,
          padding: px(NAVBAR.padding),
          gap: px(NAVBAR.gap),
          borderRadius: px(NAVBAR.radius),
        }}
      >
        <button
          onClick={() => dispatch({ type: ACTIONS.NAVIGATE_BACK })}
          className="flex items-center justify-center transition-colors shrink-0 hover:bg-[#5a5a5a]"
          style={{
            width: px(NAVBAR.back.height),
            height: px(NAVBAR.back.height),
            padding: px(NAVBAR.back.padding),
            borderRadius: px(NAVBAR.back.radius),
            backgroundColor: COLOR.darker,
          }}
          title="Back"
        >
          <AppIcon name="back" size={px(NAVBAR.back.iconSize)} color={COLOR.white} />
        </button>

        <WorkflowIconPicker
          iconUrl={workflowIcon}
          onUpload={handleIconUpload}
          onRemove={handleIconRemove}
          size={px(36)}
          disabled={!state.selectedWorkflow?.id}
        />

        <div className="flex-1 min-w-0">
          <h2
            className="truncate"
            style={{
              color: COLOR.white,
              fontSize: px(FONT.subhead2Bold.size),
              lineHeight: `${px(FONT.subhead2Bold.height)}px`,
              fontWeight: FONT.subhead2Bold.weight,
            }}
          >
            {state.selectedWorkflow?.name || 'Workflow builder'}
          </h2>
        </div>

        {isSaving && (
          <span className="flex items-center gap-1" style={{ color: COLOR.medium, fontSize: px(12) }}>
            <span className="animate-spin">⏳</span> Saving...
          </span>
        )}
        {lastSaved && !isSaving && (
          <span style={{ color: COLOR.medium, fontSize: px(12) }}>
            Saved {new Date(lastSaved).toLocaleTimeString()}
          </span>
        )}

        {/* Guide pill — rose-dark style matching Test / Save */}
        <button
          onClick={() => setShowDescriptionModal(true)}
          className="flex items-center transition-colors"
          style={PILL_SECONDARY}
          onMouseEnter={(e) => applySecondaryPillHover(e.currentTarget, true)}
          onMouseLeave={(e) => applySecondaryPillHover(e.currentTarget, false)}
          title="Guide"
        >
          <AppIcon name="guide" size={ICON_TOOLBAR.width} color={COLOR.rose} weight="regular" />
          <span style={PILL_LABEL}>Guide</span>
          {workflowDescription && <span style={{ width: px(8), height: px(8), borderRadius: '50%', backgroundColor: COLOR.rose }} />}
        </button>

        {/* Settings dropdown — Import / Export / Versions */}
        <div className="relative">
          <button
            onClick={() => setShowSettingsMenu((v) => !v)}
            className="flex items-center transition-colors"
            style={PILL_SECONDARY}
            onMouseEnter={(e) => applySecondaryPillHover(e.currentTarget, true)}
            onMouseLeave={(e) => applySecondaryPillHover(e.currentTarget, false)}
            title="Settings"
          >
            <AppIcon name="settings" size={ICON_TOOLBAR.width} color={COLOR.rose} weight="regular" />
            <span style={PILL_LABEL}>Settings</span>
          </button>
          {showSettingsMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowSettingsMenu(false)} />
              <div
                className="absolute right-0 z-20 overflow-hidden"
                style={{
                  marginTop: px(8),
                  width: px(180),
                  backgroundColor: '#1a1a1a',
                  border: '1px solid #464646',
                  borderRadius: px(12),
                  boxShadow: '0 8px 24px rgba(0,0,0,.6)',
                  padding: px(6),
                }}
              >
                <button
                  onClick={() => { setShowSettingsMenu(false); importWorkflowJSON(); }}
                  className="w-full text-left hover:bg-white/5 transition-colors flex items-center"
                  style={{
                    color: COLOR.medium,
                    fontSize: px(14),
                    padding: `${px(10)}px ${px(14)}px`,
                    borderRadius: px(8),
                    gap: px(8),
                  }}
                >
                  <AppIcon
                    name="download"
                    size={px(16)}
                    color={COLOR.medium}
                    weight="regular"
                    style={{ flexShrink: 0 }}
                  />
                  Import
                </button>
                <button
                  onClick={() => { setShowSettingsMenu(false); exportWorkflowJSON(); }}
                  className="w-full text-left hover:bg-white/5 transition-colors flex items-center"
                  style={{
                    color: COLOR.medium,
                    fontSize: px(14),
                    padding: `${px(10)}px ${px(14)}px`,
                    borderRadius: px(8),
                    gap: px(8),
                  }}
                >
                  <AppIcon
                    name="exportFile"
                    size={px(16)}
                    color={COLOR.medium}
                    weight="regular"
                    style={{ flexShrink: 0 }}
                  />
                  Export
                </button>
                {state.selectedWorkflow?.id && (
                  <button
                    onClick={() => { setShowSettingsMenu(false); setShowVersionHistory(true); }}
                    className="w-full text-left hover:bg-white/5 transition-colors flex items-center"
                    style={{
                      color: showVersionHistory ? COLOR.rose : COLOR.medium,
                      fontSize: px(14),
                      padding: `${px(10)}px ${px(14)}px`,
                      borderRadius: px(8),
                      gap: px(8),
                    }}
                  >
                    <svg style={{ width: px(16), height: px(16), flexShrink: 0 }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Versions
                  </button>
                )}
              </div>
            </>
          )}
        </div>

        {/* Test */}
        {hasSavedWorkflow && (
          <button
            onClick={showTestChat ? handleCloseTestChat : handleTestChat}
            className="flex items-center transition-colors"
            style={PILL_SECONDARY}
            onMouseEnter={(e) => applySecondaryPillHover(e.currentTarget, true)}
            onMouseLeave={(e) => applySecondaryPillHover(e.currentTarget, false)}
            title="Test workflow"
          >
            {testSessionId && <span className="rounded-full animate-pulse" style={{ width: px(8), height: px(8), backgroundColor: COLOR.rose }} />}
            <AppIcon name="test" size={ICON_TOOLBAR.width} color="currentColor" weight="regular" />
            <span style={PILL_LABEL}>{showTestChat ? 'Testing' : testSessionId ? 'Resume' : 'Test'}</span>
          </button>
        )}
        {hasSavedWorkflow && testSessionId && !showTestChat && (
          <button
            onClick={handleClearTestSession}
            className="flex items-center justify-center hover:bg-white/5 transition-colors"
            style={{ width: px(48), height: px(48), borderRadius: px(NAVBAR.button.radius), color: COLOR.medium }}
            title="Clear test session"
          >
            <AppIcon name="trash" size={ICON_TOOLBAR.width} color={COLOR.medium} weight="regular" />
          </button>
        )}

        {!isReadOnly && (
          <button
            onClick={() => handleSave(false)}
            className="flex items-center transition-colors"
            style={PILL_SECONDARY}
            onMouseEnter={(e) => applySecondaryPillHover(e.currentTarget, true)}
            onMouseLeave={(e) => applySecondaryPillHover(e.currentTarget, false)}
          >
            <AppIcon name="save" size={ICON_TOOLBAR.width} color="currentColor" weight="regular" />
            <span style={PILL_LABEL}>Save</span>
          </button>
        )}

        {!isReadOnly && hasSavedWorkflow && (
          <button
            onClick={handlePublish}
            className="flex items-center transition-colors"
            style={PILL_PRIMARY}
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = NAVBAR.primaryButton.bgHover; }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = NAVBAR.primaryButton.bg; }}
          >
            <AppIcon name="publish" size={ICON_TOOLBAR.width} color={COLOR.white} weight="bold" />
            <span style={PILL_LABEL}>Publish</span>
          </button>
        )}
      </div>
      )}

      {/* ============================================================== */}
      {/* MAIN BUILDER AREA — transparent so the root's dotted grid shows */}
      {/* ============================================================== */}
      <div className="flex flex-1 overflow-hidden relative">
        {showTestChat ? (
          <Suspense fallback={<div className="flex-1 flex items-center justify-center"><div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-600" /></div>}>
            <ChatView testMode onClose={handleCloseTestChat} />
          </Suspense>
        ) : (
          <>
            <NodePalette />
            <Canvas readOnly={isReadOnly} />
            {state.selectedNodeIds?.length > 0 && <NodeConfigPanel key={state.selectedNodeIds[0]} />}
          </>
        )}
      </div>

      {/* Feedback modal */}
      <FeedbackModal isOpen={showFeedback} onClose={() => setShowFeedback(false)} />

      {/* Version history panel */}
      {showVersionHistory && state.selectedWorkflow?.id && (
        <VersionHistoryPanel
          workflowId={state.selectedWorkflow.id}
          workflowMeta={state.selectedWorkflow.meta}
          onRestore={handleVersionRestore}
          onClose={() => setShowVersionHistory(false)}
        />
      )}

      {/* Custom Modals */}
      <PromptModal
        isOpen={showSavePrompt}
        title="Save Workflow"
        message="Enter a name for your workflow:"
        placeholder="My Workflow"
        defaultValue={state.newWorkflowName || ''}
        confirmText="Save"
        cancelText="Cancel"
        onConfirm={handleSaveWithName}
        onCancel={() => setShowSavePrompt(false)}
      />

      <ConfirmModal
        isOpen={showPublishConfirm}
        title="Publish Workflow"
        message={`Are you sure you want to publish "${state.selectedWorkflow?.name}"? Published workflows are read-only.`}
        confirmText="Publish"
        cancelText="Cancel"
        variant="default"
        onConfirm={() => confirmPublish(false)}
        onCancel={() => setShowPublishConfirm(false)}
      />

      <ConfirmModal
        isOpen={showEmptyWorkflowAlert}
        title="Empty Workflow"
        message="Cannot save empty workflow. Add some nodes first."
        confirmText="OK"
        onConfirm={() => setShowEmptyWorkflowAlert(false)}
        onCancel={() => setShowEmptyWorkflowAlert(false)}
      />

      <ConfirmModal
        isOpen={showSaveFirstAlert}
        title="Save Required"
        message="Please save the workflow first before publishing."
        confirmText="OK"
        onConfirm={() => setShowSaveFirstAlert(false)}
        onCancel={() => setShowSaveFirstAlert(false)}
      />

      <ConfirmModal
        isOpen={showPublishEmptyAlert}
        title="Empty Workflow"
        message="Cannot publish an empty workflow. Please add at least one node before publishing."
        confirmText="OK"
        onConfirm={() => setShowPublishEmptyAlert(false)}
        onCancel={() => setShowPublishEmptyAlert(false)}
      />

      <Toast
        isOpen={Boolean(saveToast)}
        title={saveToast?.title}
        message={saveToast?.message ?? ''}
        variant="success"
        onClose={() => setSaveToast(null)}
      />

      <ConfirmModal
        isOpen={showSaveErrorAlert}
        title="Save Failed"
        message={`Failed to save workflow: ${saveErrorMessage}`}
        confirmText="OK"
        variant="danger"
        onConfirm={() => setShowSaveErrorAlert(false)}
        onCancel={() => setShowSaveErrorAlert(false)}
      />

      <ConfirmModal
        isOpen={showPublishSuccessAlert}
        title="Success"
        message={`Workflow "${state.selectedWorkflow?.name}" published successfully!`}
        confirmText="OK"
        onConfirm={() => setShowPublishSuccessAlert(false)}
        onCancel={() => setShowPublishSuccessAlert(false)}
      />

      <ConfirmModal
        isOpen={showPublishErrorAlert}
        title="Publish Failed"
        message={`Failed to publish workflow: ${publishErrorMessage}`}
        confirmText="OK"
        variant="danger"
        onConfirm={() => setShowPublishErrorAlert(false)}
        onCancel={() => setShowPublishErrorAlert(false)}
      />

      <ConfirmModal
        isOpen={showReplacePendingConfirm}
        title="Pending Approval in Progress"
        message="This workflow already has a pending admin approval (marketplace or shared access). Publishing now will replace that submission with your latest changes. Do you want to proceed?"
        confirmText="Replace & Publish"
        cancelText="Cancel"
        variant="warning"
        onConfirm={() => { setShowReplacePendingConfirm(false); confirmPublish(true); }}
        onCancel={() => setShowReplacePendingConfirm(false)}
      />

      <AlertModal
        isOpen={showUnconnectedNodesAlert}
        onClose={() => setShowUnconnectedNodesAlert(false)}
        title="Unconnected Nodes"
        message={`All nodes must be connected to at least one other node. The following nodes are not connected: ${unconnectedNodesList}`}
        variant="warning"
      />

      <AlertModal
        isOpen={showMissingSchemaAlert}
        onClose={() => setShowMissingSchemaAlert(false)}
        title="Missing Output Schema"
        message={`All agent nodes must have an Output Schema defined before publishing. The following agents are missing one: ${missingSchemaNodesList}`}
        variant="warning"
      />

      <WorkflowDescriptionModal
        isOpen={showDescriptionModal}
        onClose={() => setShowDescriptionModal(false)}
        onSave={setWorkflowDescription}
        initialData={workflowDescription}
      />

    </div>
  );
}
