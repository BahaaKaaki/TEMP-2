import { createContext, useContext, useReducer, useEffect, useMemo, useRef, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { isChatCompatibleNode } from '@/data/appData';
import { ensureDefaultChatNode } from '@/utils/ensureDefaultChatNode';

const NAV_STATE_KEY = 'agentkit_nav_state';
const CANVAS_STATE_KEY = 'agentkit_workflow_canvas';
const LEGACY_CANVAS_STATE_KEY = 'agentkit_workflow_state';

/** Default landing: Apex OS storefront tab. */
function homeNavSnapshot() {
  return {
    currentView: 'workspace',
    activeTab: 'storefront',
    selectedWorkflow: null,
    selectedSession: null,
    selectedKB: null,
    navHistory: [],
  };
}

function persistHomeNavState() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(NAV_STATE_KEY, JSON.stringify(homeNavSnapshot()));
  } catch {
    try {
      window.localStorage.removeItem(NAV_STATE_KEY);
    } catch {
      // ignore
    }
  }
}

const WorkflowContext = createContext();

// Action types
const ACTIONS = {
  ADD_NODE: 'ADD_NODE',
  REMOVE_NODE: 'REMOVE_NODE',
  REMOVE_NODES: 'REMOVE_NODES',
  UPDATE_NODE: 'UPDATE_NODE',
  MOVE_NODE: 'MOVE_NODE',
  MOVE_NODES: 'MOVE_NODES',
  SELECT_NODE: 'SELECT_NODE',
  SELECT_NODES: 'SELECT_NODES',
  TOGGLE_NODE_SELECTION: 'TOGGLE_NODE_SELECTION',
  SELECT_ALL_NODES: 'SELECT_ALL_NODES',
  ADD_CONNECTION: 'ADD_CONNECTION',
  REMOVE_CONNECTION: 'REMOVE_CONNECTION',
  START_CONNECTION: 'START_CONNECTION',
  END_CONNECTION: 'END_CONNECTION',
  CANCEL_CONNECTION: 'CANCEL_CONNECTION',
  UPDATE_TEMP_CONNECTION: 'UPDATE_TEMP_CONNECTION',
  CLEAR_CANVAS: 'CLEAR_CANVAS',
  LOAD_TEMPLATE: 'LOAD_TEMPLATE',
  SET_ZOOM: 'SET_ZOOM',
  SET_CANVAS_OFFSET: 'SET_CANVAS_OFFSET',
  SET_VIEW: 'SET_VIEW',
  SELECT_WORKFLOW: 'SELECT_WORKFLOW',
  SELECT_SESSION: 'SELECT_SESSION',
  SELECT_KB: 'SELECT_KB',
  SAVE_DRAFT: 'SAVE_DRAFT',
  PUBLISH_WORKFLOW: 'PUBLISH_WORKFLOW',
  DUPLICATE_NODES: 'DUPLICATE_NODES',
  UNDO: 'UNDO',
  REDO: 'REDO',
  // Navigation actions (push/pop history, remember active tab)
  NAVIGATE: 'NAVIGATE',
  NAVIGATE_BACK: 'NAVIGATE_BACK',
  SET_ACTIVE_TAB: 'SET_ACTIVE_TAB',
  HYDRATE_NAV: 'HYDRATE_NAV',
  RESET_HOME: 'RESET_HOME',
};

// Initial state
const initialState = {
  currentView: 'workspace', // 'workspace' (= ApexShell), 'builder', 'chat', 'kb-detail'
  activeTab: 'storefront', // ApexShell tab: 'storefront', 'sessions', 'mytools', 'approval'
  navHistory: [], // Navigation history stack for "go back" behavior
  canvasNodes: new Map(),
  connections: [],
  selectedNodeIds: [], // Changed from selectedNodeId to support multi-selection
  zoomLevel: 1,
  canvasOffset: { x: 0, y: 0 },
  currentWorkflow: null,
  selectedWorkflow: null, // For chat with existing workflows
  selectedSession: null, // Currently selected chat session
  selectedKB: null, // Currently selected knowledge base
  newWorkflowName: null, // Pre-filled name when creating from My Tools
  newWorkflowDescription: null, // Pre-filled description when creating from My Tools
  publishedWorkflows: [],
  drafts: [],
  history: [],
  historyIndex: -1,
  // Connection state
  isConnecting: false,
  connectionStart: null, // { nodeId, port: 'output' }
  tempConnectionEnd: null, // { x, y } for drawing temporary line
};

// Max entries kept in the navigation history stack (caps memory/storage usage)
const MAX_NAV_HISTORY = 30;

// Capture the current navigation snapshot (for pushing onto history stack)
function snapshotNav(state) {
  return {
    view: state.currentView,
    activeTab: state.activeTab,
    selectedWorkflow: state.selectedWorkflow,
    selectedSession: state.selectedSession,
    selectedKB: state.selectedKB,
  };
}

// Helper to save state to history
function saveToHistory(state) {
  const snapshot = {
    canvasNodes: new Map(state.canvasNodes),
    connections: [...state.connections],
    selectedNodeIds: [...state.selectedNodeIds],
  };

  const newHistory = state.history.slice(0, state.historyIndex + 1);
  newHistory.push(snapshot);

  // Limit history to 50 states
  if (newHistory.length > 50) {
    newHistory.shift();
  }

  return {
    history: newHistory,
    historyIndex: newHistory.length - 1,
  };
}

// Reducer function
function workflowReducer(state, action) {
  switch (action.type) {
    case ACTIONS.ADD_NODE: {
      const newNodes = new Map(state.canvasNodes);
      const nodeId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      newNodes.set(nodeId, {
        ...action.payload,
        id: nodeId,
      });
      const historyState = saveToHistory(state);
      return {
        ...state,
        canvasNodes: newNodes,
        ...historyState,
      };
    }

    case ACTIONS.REMOVE_NODE: {
      const nodeToRemove = state.canvasNodes.get(action.payload);
      if (nodeToRemove?.type === 'chat') {
        return state;
      }
      const newNodes = new Map(state.canvasNodes);
      newNodes.delete(action.payload);
      const newConnections = state.connections.filter(
        conn => conn.source !== action.payload && conn.target !== action.payload
      );
      const historyState = saveToHistory(state);
      return {
        ...state,
        canvasNodes: newNodes,
        connections: newConnections,
        selectedNodeIds: state.selectedNodeIds.filter(id => id !== action.payload),
        ...historyState,
      };
    }

    case ACTIONS.REMOVE_NODES: {
      const nodeIdsToRemove = new Set(
        action.payload.filter((nodeId) => state.canvasNodes.get(nodeId)?.type !== 'chat')
      );
      const newNodes = new Map(state.canvasNodes);
      nodeIdsToRemove.forEach(nodeId => newNodes.delete(nodeId));
      const newConnections = state.connections.filter(
        conn => !nodeIdsToRemove.has(conn.source) && !nodeIdsToRemove.has(conn.target)
      );
      const historyState = saveToHistory(state);
      return {
        ...state,
        canvasNodes: newNodes,
        connections: newConnections,
        selectedNodeIds: [],
        ...historyState,
      };
    }

    case ACTIONS.UPDATE_NODE: {
      const newNodes = new Map(state.canvasNodes);
      const node = newNodes.get(action.payload.nodeId);
      if (node) {
        const incomingConfig = action.payload.config;
        newNodes.set(action.payload.nodeId, {
          ...node,
          config: action.payload.replace
            ? { ...incomingConfig }
            : { ...node.config, ...incomingConfig },
        });
      }
      const historyState = saveToHistory(state);
      return {
        ...state,
        canvasNodes: newNodes,
        ...historyState,
      };
    }

    case ACTIONS.MOVE_NODE: {
      const newNodes = new Map(state.canvasNodes);
      const node = newNodes.get(action.payload.nodeId);
      if (node) {
        newNodes.set(action.payload.nodeId, {
          ...node,
          x: action.payload.x,
          y: action.payload.y,
        });
      }
      // Only save to history when explicitly requested (e.g., at end of drag)
      const historyState = action.payload.saveToHistory ? saveToHistory(state) : {};
      return {
        ...state,
        canvasNodes: newNodes,
        ...historyState,
      };
    }

    case ACTIONS.MOVE_NODES: {
      const newNodes = new Map(state.canvasNodes);
      const { nodeIds, deltaX, deltaY, saveToHistory: shouldSaveToHistory } = action.payload;
      nodeIds.forEach(nodeId => {
        const node = newNodes.get(nodeId);
        if (node) {
          newNodes.set(nodeId, {
            ...node,
            x: Math.max(0, node.x + deltaX),
            y: Math.max(0, node.y + deltaY),
          });
        }
      });
      // Only save to history when explicitly requested (e.g., at end of drag)
      const historyState = shouldSaveToHistory ? saveToHistory(state) : {};
      return {
        ...state,
        canvasNodes: newNodes,
        ...historyState,
      };
    }

    case ACTIONS.SELECT_NODE:
      return {
        ...state,
        selectedNodeIds: action.payload ? [action.payload] : [],
      };

    case ACTIONS.SELECT_NODES:
      return {
        ...state,
        selectedNodeIds: action.payload || [],
      };

    case ACTIONS.TOGGLE_NODE_SELECTION: {
      const nodeId = action.payload;
      const isSelected = state.selectedNodeIds.includes(nodeId);
      return {
        ...state,
        selectedNodeIds: isSelected
          ? state.selectedNodeIds.filter(id => id !== nodeId)
          : [...state.selectedNodeIds, nodeId],
      };
    }

    case ACTIONS.SELECT_ALL_NODES:
      return {
        ...state,
        selectedNodeIds: Array.from(state.canvasNodes.keys()),
      };

    case ACTIONS.DUPLICATE_NODES: {
      const nodeIdsToDuplicate = action.payload || state.selectedNodeIds;
      if (nodeIdsToDuplicate.length === 0) return state;

      const newNodes = new Map(state.canvasNodes);
      const idMapping = new Map();
      const newSelectedIds = [];

      for (const oldId of nodeIdsToDuplicate) {
        const original = state.canvasNodes.get(oldId);
        if (!original || original.type === 'chat') continue;

        const newId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        idMapping.set(oldId, newId);

        newNodes.set(newId, {
          ...original,
          id: newId,
          x: (original.x || 0) + 30,
          y: (original.y || 0) + 30,
          config: original.config ? JSON.parse(JSON.stringify(original.config)) : {},
        });
        newSelectedIds.push(newId);
      }

      const duplicatedConnections = state.connections
        .filter((c) => idMapping.has(c.source) && idMapping.has(c.target))
        .map((c) => ({
          ...c,
          id: `${idMapping.get(c.source)}-${idMapping.get(c.target)}`,
          source: idMapping.get(c.source),
          target: idMapping.get(c.target),
        }));

      const historyState = saveToHistory(state);
      return {
        ...state,
        canvasNodes: newNodes,
        connections: [...state.connections, ...duplicatedConnections],
        selectedNodeIds: newSelectedIds,
        ...historyState,
      };
    }

    case ACTIONS.ADD_CONNECTION: {
      const sourceNode = state.canvasNodes.get(state.connectionStart.nodeId);
      const isConditionNode = sourceNode?.type === 'condition';

      if (!isConditionNode) {
        const hasExistingOutput = state.connections.some(
          conn => conn.source === state.connectionStart.nodeId
        );

        if (hasExistingOutput) {
          console.log('Warning: source node already has an outgoing connection; only condition nodes can branch.');
          return {
            ...state,
            isConnecting: false,
            connectionStart: null,
            tempConnectionEnd: null,
          };
        }
      }

      const newConnection = {
        id: `${action.payload.source}-${action.payload.target}`,
        source: action.payload.source,
        target: action.payload.target,
        sourceHandle: action.payload.sourceHandle || null,
        targetHandle: action.payload.targetHandle || null,
      };
      const historyState = saveToHistory(state);
      return {
        ...state,
        connections: [...state.connections, newConnection],
        isConnecting: false,
        connectionStart: null,
        tempConnectionEnd: null,
        ...historyState,
      };
    }

    case ACTIONS.REMOVE_CONNECTION: {
      const historyState = saveToHistory(state);
      return {
        ...state,
        connections: state.connections.filter(
          (conn) => conn.id !== action.payload
        ),
        ...historyState,
      };
    }

    case ACTIONS.START_CONNECTION:
      return {
        ...state,
        isConnecting: true,
        connectionStart: action.payload, // { nodeId, port }
        tempConnectionEnd: null,
      };

    case ACTIONS.END_CONNECTION: {
      if (!state.connectionStart) return state;

      // Debug logging
      console.log('🔍 END_CONNECTION Debug:');
      console.log('  connectionStart.nodeId:', state.connectionStart.nodeId);
      console.log('  connectionStart.port:', state.connectionStart.port);
      console.log('  connectionStart.conditionId:', state.connectionStart.conditionId);
      console.log('  payload.nodeId:', action.payload.nodeId);
      console.log('  payload.conditionId:', action.payload.conditionId);

      // Check if connection already exists
      const connectionExists = state.connections.some(
        conn => conn.source === state.connectionStart.nodeId &&
                conn.target === action.payload.nodeId &&
                conn.conditionId === state.connectionStart.conditionId
      );

      if (connectionExists) {
        console.log('⚠️ Connection already exists, skipping');
        return {
          ...state,
          isConnecting: false,
          connectionStart: null,
          tempConnectionEnd: null,
        };
      }

      const newConnection = {
        id: `${state.connectionStart.nodeId}-${action.payload.nodeId}-${state.connectionStart.conditionId || 'default'}`,
        source: state.connectionStart.nodeId,
        target: action.payload.nodeId,
        sourceHandle: null,
        targetHandle: null,
        conditionId: state.connectionStart.conditionId || null, // Store which condition this connection is for
      };
      
      console.log('✅ Creating new connection with conditionId:', newConnection.conditionId);
      console.log('   Connection ID:', newConnection.id);
      const historyState = saveToHistory(state);
      return {
        ...state,
        connections: [...state.connections, newConnection],
        isConnecting: false,
        connectionStart: null,
        tempConnectionEnd: null,
        ...historyState,
      };
    }

    case ACTIONS.CANCEL_CONNECTION:
      return {
        ...state,
        isConnecting: false,
        connectionStart: null,
        tempConnectionEnd: null,
      };

    case ACTIONS.UPDATE_TEMP_CONNECTION:
      return {
        ...state,
        tempConnectionEnd: action.payload, // { x, y }
      };

    case ACTIONS.CLEAR_CANVAS: {
      const { nodes: chatNodes } = ensureDefaultChatNode([], []);
      const newNodes = new Map();
      chatNodes.forEach((nodeData) => {
        newNodes.set(nodeData.id, { ...nodeData });
      });
      return {
        ...state,
        canvasNodes: newNodes,
        connections: [],
        selectedNodeIds: [],
        currentWorkflow: null,
      };
    }

    case ACTIONS.LOAD_TEMPLATE: {
      const template = action.payload;
      const newNodes = new Map();

      const { nodes: templateNodes, connections: templateConnections } = ensureDefaultChatNode(
        template.nodes || [],
        template.connections || []
      );
      
      // Check if this is a saved workflow (has id) or a template
      const isLoadingSavedWorkflow = template.id;
      
      console.log('🔍 LOAD_TEMPLATE Debug:');
      console.log('  template.id:', template.id);
      console.log('  isLoadingSavedWorkflow:', isLoadingSavedWorkflow);
      console.log('  template.nodes count:', templateNodes.length);
      console.log('  template.connections count:', templateConnections.length);
      console.log('  First node ID:', templateNodes[0]?.id);
      console.log('  First connection:', templateConnections[0]);

      templateNodes.forEach(nodeData => {
        // For saved workflows, keep original IDs. For templates, generate new ones.
        const nodeId = isLoadingSavedWorkflow 
          ? nodeData.id 
          : `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        newNodes.set(nodeId, {
          ...nodeData,
          id: nodeId,
          templateNodeId: nodeData.id,
        });
      });

      // Map template connections to new node IDs
      const nodeIdMap = new Map();
      let index = 0;
      for (const [newId, node] of newNodes.entries()) {
        nodeIdMap.set(node.templateNodeId, newId);
      }

      const newConnections = templateConnections.map(conn => ({
        id: `${nodeIdMap.get(conn.source)}-${nodeIdMap.get(conn.target)}${conn.conditionId ? `-${conn.conditionId}` : ''}`,
        source: nodeIdMap.get(conn.source),
        target: nodeIdMap.get(conn.target),
        sourceHandle: null,
        targetHandle: null,
        conditionId: conn.conditionId || null,
      }));

      return {
        ...state,
        canvasNodes: newNodes,
        connections: newConnections,
        selectedNodeIds: [],
        currentWorkflow: template,
      };
    }

    case ACTIONS.SET_ZOOM:
      return {
        ...state,
        zoomLevel: action.payload,
      };

    case ACTIONS.SET_CANVAS_OFFSET:
      return {
        ...state,
        canvasOffset: action.payload,
      };

    case ACTIONS.SET_VIEW:
      return {
        ...state,
        currentView: action.payload,
      };

    case ACTIONS.NAVIGATE: {
      // Push current location onto history, then apply the new location.
      // Pass only the fields you want to change; others persist.
      const payload = action.payload || {};
      const snapshot = snapshotNav(state);
      const newHistory = [...state.navHistory, snapshot];
      if (newHistory.length > MAX_NAV_HISTORY) newHistory.shift();
      return {
        ...state,
        currentView: payload.view !== undefined ? payload.view : state.currentView,
        activeTab: payload.activeTab !== undefined ? payload.activeTab : state.activeTab,
        selectedWorkflow: payload.selectedWorkflow !== undefined ? payload.selectedWorkflow : state.selectedWorkflow,
        selectedSession: payload.selectedSession !== undefined ? payload.selectedSession : state.selectedSession,
        selectedKB: payload.selectedKB !== undefined ? payload.selectedKB : state.selectedKB,
        newWorkflowName: payload.newWorkflowName || null,
        newWorkflowDescription: payload.newWorkflowDescription || null,
        navHistory: newHistory,
      };
    }

    case ACTIONS.NAVIGATE_BACK: {
      if (state.navHistory.length === 0) {
        // Fallback: go home (workspace with workflows tab) — better than getting stuck.
        return {
          ...state,
          currentView: 'workspace',
          activeTab: state.activeTab || 'workflows',
        };
      }
      const prev = state.navHistory[state.navHistory.length - 1];
      return {
        ...state,
        currentView: prev.view,
        activeTab: prev.activeTab,
        selectedWorkflow: prev.selectedWorkflow,
        selectedSession: prev.selectedSession,
        selectedKB: prev.selectedKB,
        navHistory: state.navHistory.slice(0, -1),
      };
    }

    case ACTIONS.SET_ACTIVE_TAB:
      // Switch tabs within workspace without polluting the nav-history stack.
      return {
        ...state,
        activeTab: action.payload,
      };

    case ACTIONS.HYDRATE_NAV: {
      // Restore navigation state from localStorage on mount.
      const p = action.payload || {};
      return {
        ...state,
        currentView: p.currentView || state.currentView,
        activeTab: p.activeTab || state.activeTab,
        selectedWorkflow: p.selectedWorkflow !== undefined ? p.selectedWorkflow : state.selectedWorkflow,
        selectedSession: p.selectedSession !== undefined ? p.selectedSession : state.selectedSession,
        selectedKB: p.selectedKB !== undefined ? p.selectedKB : state.selectedKB,
        navHistory: Array.isArray(p.navHistory) ? p.navHistory : state.navHistory,
      };
    }

    case ACTIONS.RESET_HOME: {
      const home = homeNavSnapshot();
      return {
        ...state,
        ...home,
        newWorkflowName: null,
        newWorkflowDescription: null,
      };
    }

    case ACTIONS.SELECT_WORKFLOW:
      return {
        ...state,
        selectedWorkflow: action.payload,
      };

    case ACTIONS.SELECT_SESSION:
      return {
        ...state,
        selectedSession: action.payload,
      };

    case ACTIONS.SELECT_KB:
      return {
        ...state,
        selectedKB: action.payload,
      };

    case ACTIONS.SAVE_DRAFT: {
      const draft = {
        id: `draft_${Date.now()}`,
        name: action.payload.name || `Draft ${new Date().toLocaleDateString()}`,
        nodes: Array.from(state.canvasNodes.entries()),
        connections: state.connections,
        created: new Date().toISOString(),
      };
      return {
        ...state,
        drafts: [...state.drafts, draft],
      };
    }

    case ACTIONS.PUBLISH_WORKFLOW: {
      const workflow = {
        id: action.payload.id || `published_${Date.now()}`,
        name: action.payload.name,
        nodes: Array.from(state.canvasNodes.entries()),
        connections: state.connections,
        published: new Date().toISOString(),
        ...action.payload, // Include any additional data from API response
      };
      return {
        ...state,
        currentWorkflow: workflow, // Store as current workflow for future updates
        publishedWorkflows: [...state.publishedWorkflows, workflow],
      };
    }

    case ACTIONS.UNDO: {
      if (state.historyIndex <= 0) return state;

      const previousState = state.history[state.historyIndex - 1];
      return {
        ...state,
        canvasNodes: new Map(previousState.canvasNodes),
        connections: [...previousState.connections],
        selectedNodeIds: [...previousState.selectedNodeIds],
        historyIndex: state.historyIndex - 1,
      };
    }

    case ACTIONS.REDO: {
      if (state.historyIndex >= state.history.length - 1) return state;

      const nextState = state.history[state.historyIndex + 1];
      return {
        ...state,
        canvasNodes: new Map(nextState.canvasNodes),
        connections: [...nextState.connections],
        selectedNodeIds: [...nextState.selectedNodeIds],
        historyIndex: state.historyIndex + 1,
      };
    }

    default:
      return state;
  }
}

// Synchronously restore the last known navigation state from localStorage so
// the very first render already shows the correct view/tab instead of flashing
// the default (workspace / marketplace) and being overwritten by the
// persistence effect before hydration completes.
function initNavState(init) {
  if (typeof window === 'undefined') return init;
  try {
    const savedNav = window.localStorage.getItem(NAV_STATE_KEY);
    if (!savedNav) return init;
    const parsed = JSON.parse(savedNav);
    return {
      ...init,
      currentView: parsed.currentView || init.currentView,
      activeTab: parsed.activeTab || init.activeTab,
      selectedWorkflow:
        parsed.selectedWorkflow !== undefined ? parsed.selectedWorkflow : init.selectedWorkflow,
      selectedSession:
        parsed.selectedSession !== undefined ? parsed.selectedSession : init.selectedSession,
      selectedKB: parsed.selectedKB !== undefined ? parsed.selectedKB : init.selectedKB,
      navHistory: Array.isArray(parsed.navHistory) ? parsed.navHistory : init.navHistory,
    };
  } catch (e) {
    console.error('Failed to hydrate saved navigation state:', e);
    return init;
  }
}

// Provider component
/** @returns {{ nodeId: string, config: object } | null} */
const noopFlush = () => null;

export function WorkflowProvider({ children }) {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const [state, dispatch] = useReducer(workflowReducer, initialState, initNavState);
  const hasHydrated = useRef(false);
  const nodeConfigFlushRef = useRef(noopFlush);
  const prevAuthenticatedRef = useRef(null);

  const resetToHome = useCallback(() => {
    persistHomeNavState();
    dispatch({ type: ACTIONS.RESET_HOME });
  }, []);

  // After logout or login, land on the storefront instead of the last view.
  // A refresh while still signed in keeps the saved page (prevAuth stays null → true).
  useEffect(() => {
    if (authLoading) return;

    const prevAuth = prevAuthenticatedRef.current;
    prevAuthenticatedRef.current = isAuthenticated;

    if (prevAuth === null) {
      if (!isAuthenticated) resetToHome();
      return;
    }

    if (prevAuth !== isAuthenticated) {
      resetToHome();
    }
  }, [isAuthenticated, authLoading, resetToHome]);

  const registerNodeConfigFlush = useCallback((flushFn) => {
    nodeConfigFlushRef.current = flushFn || noopFlush;
  }, []);

  /** Flush unsaved node-config panel edits before workflow save. */
  const flushPendingNodeConfig = useCallback(() => {
    return nodeConfigFlushRef.current();
  }, []);

  // Check if workflow has a chat-compatible trigger node
  const isChatEnabled = useMemo(() => {
    // Check if any node in the canvas is a chat-compatible trigger
    for (const [nodeId, node] of state.canvasNodes) {
      if (isChatCompatibleNode(node.type)) {
        return true;
      }
    }
    return false;
  }, [state.canvasNodes]);

  // Restore canvas from localStorage only for unsaved (no id) builder drafts.
  // Saved workflows always load from the API in BuilderView so stale local cache
  // cannot overwrite DB-backed node configs after a refresh.
  useEffect(() => {
    const savedWorkflowId = state.selectedWorkflow?.id ?? null;
    if (savedWorkflowId) {
      hasHydrated.current = true;
      return;
    }

    const raw =
      localStorage.getItem(CANVAS_STATE_KEY)
      || localStorage.getItem(LEGACY_CANVAS_STATE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed.workflowId) {
          // Belongs to a saved workflow — ignore; API is source of truth.
        } else if (parsed.canvasNodes) {
          dispatch({
            type: ACTIONS.LOAD_TEMPLATE,
            payload: {
              nodes: parsed.canvasNodes.map(([id, node]) => node),
              connections: parsed.connections || [],
            },
          });
        }
      } catch (e) {
        console.error('Failed to load saved canvas draft:', e);
      }
    }

    hasHydrated.current = true;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist canvas state — skip until initial hydration is done
  useEffect(() => {
    if (!hasHydrated.current) return;
    const workflowId = state.selectedWorkflow?.id ?? null;
    const stateToSave = {
      workflowId,
      canvasNodes: Array.from(state.canvasNodes.entries()),
      connections: state.connections,
    };
    try {
      localStorage.setItem(CANVAS_STATE_KEY, JSON.stringify(stateToSave));
      localStorage.removeItem(LEGACY_CANVAS_STATE_KEY);
    } catch (e) {
      console.warn('Failed to persist workflow canvas (storage quota exceeded). Clearing stale data and retrying.');
      try {
        localStorage.removeItem(CANVAS_STATE_KEY);
        localStorage.removeItem(LEGACY_CANVAS_STATE_KEY);
        localStorage.setItem(CANVAS_STATE_KEY, JSON.stringify(stateToSave));
      } catch {
        // Storage is truly full — nothing more we can do, but the app keeps running.
      }
    }
  }, [state.canvasNodes, state.connections, state.selectedWorkflow?.id]);

  // Persist navigation state (view, tab, selections, history) so refresh
  // and the back button both keep the user where they were. Nav state is
  // hydrated synchronously in the useReducer initializer, so we persist from
  // the very first render — no hasHydrated guard needed here.
  useEffect(() => {
    const navToSave = {
      currentView: state.currentView,
      activeTab: state.activeTab,
      selectedWorkflow: state.selectedWorkflow,
      selectedSession: state.selectedSession,
      selectedKB: state.selectedKB,
      navHistory: state.navHistory,
    };
    try {
      localStorage.setItem(NAV_STATE_KEY, JSON.stringify(navToSave));
    } catch (e) {
      // Selected workflow objects can be big; fall back to a minimal snapshot so
      // at least the view + tab survive a refresh.
      console.warn('Failed to persist full navigation state, saving minimal fallback:', e?.message);
      try {
        localStorage.setItem(NAV_STATE_KEY, JSON.stringify({
          currentView: state.currentView,
          activeTab: state.activeTab,
          navHistory: [],
        }));
      } catch {
        // Storage is full — leave it, app still works.
      }
    }
  }, [
    state.currentView,
    state.activeTab,
    state.selectedWorkflow,
    state.selectedSession,
    state.selectedKB,
    state.navHistory,
  ]);

  // Hook the browser Back button (and back gesture) to our nav history so it
  // behaves like the in-app back button instead of leaving the app.
  useEffect(() => {
    // Seed the session with an initial history entry so popstate has something to pop.
    try {
      window.history.replaceState({ apexosNav: true }, '');
    } catch {
      // ignore
    }
    // Push a sentinel entry — the first browser Back will pop this and fire popstate.
    try {
      window.history.pushState({ apexosNav: true, sentinel: true }, '');
    } catch {
      // ignore
    }

    const handlePopState = () => {
      // Treat any browser-back as an in-app back.
      dispatch({ type: ACTIONS.NAVIGATE_BACK });
      // Re-push the sentinel so subsequent browser-backs keep working.
      try {
        window.history.pushState({ apexosNav: true, sentinel: true }, '');
      } catch {
        // ignore
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const contextValue = useMemo(
    () => ({
      state,
      dispatch,
      ACTIONS,
      isChatEnabled,
      registerNodeConfigFlush,
      flushPendingNodeConfig,
    }),
    [state, isChatEnabled, registerNodeConfigFlush, flushPendingNodeConfig]
  );

  return (
    <WorkflowContext.Provider value={contextValue}>
      {children}
    </WorkflowContext.Provider>
  );
}

// Custom hook
export function useWorkflow() {
  const context = useContext(WorkflowContext);
  if (!context) {
    throw new Error('useWorkflow must be used within a WorkflowProvider');
  }
  return context;
}
