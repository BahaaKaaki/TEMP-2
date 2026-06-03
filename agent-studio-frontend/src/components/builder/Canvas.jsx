import { useRef, useState, useEffect } from 'react';
import { useWorkflow } from '@/context/WorkflowContext';
import { getDefaultConfig, APP_DATA } from '@/data/appData';
import CanvasNode from './CanvasNode';
import ConnectionLine from './ConnectionLine';
import EdgeInspector from './EdgeInspector';
import { getNodeStyle } from './nodeCategoryStyles';
import Button from '../ui/Button';
import { createWorkflow, updateWorkflow } from '@/api/client';
import ConfirmModal from '../ui/ConfirmModal';
import AlertModal from '../ui/AlertModal';
import { safeLog, safeError, safeWarn } from '../../utils/safeLogger';
import { COLOR, FONT, ZOOM, EDGE } from './figmaSpec';
import { useFigmaPx } from './useFigmaScale';
import AppIcon from '../ui/AppIcon';

export default function Canvas({ readOnly = false }) {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const { px } = useFigmaPx();
  const canvasRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionBox, setSelectionBox] = useState({ startX: 0, startY: 0, endX: 0, endY: 0 });
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [nodesToDelete, setNodesToDelete] = useState([]);
  const [showInitiatorAlert, setShowInitiatorAlert] = useState(false);
  const [existingInitiatorName, setExistingInitiatorName] = useState('');
  const [contextMenu, setContextMenu] = useState(null);
  const clipboardRef = useRef(null);

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (readOnly) {
        if (e.key === 'Escape' && state.selectedNodeIds.length > 0) {
          dispatch({ type: ACTIONS.SELECT_NODES, payload: [] });
        }
        return;
      }
      // Check if user is typing in an input field.  Monaco wraps its
      // internal <textarea> in several divs; during/just-after mount the
      // keydown target can be one of those wrapper divs, so we also bail
      // if the event originates anywhere inside a .monaco-editor subtree.
      // Otherwise our Cmd+V node-paste shortcut swallows paste into Monaco.
      const inMonaco =
        e.target?.closest && e.target.closest('.monaco-editor') !== null;
      const isTyping = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) ||
                       e.target.isContentEditable ||
                       inMonaco;

      // Delete selected nodes with confirmation (only if not typing)
      if ((e.key === 'Delete' || e.key === 'Backspace') && state.selectedNodeIds.length > 0 && !isTyping) {
        const deletableIds = state.selectedNodeIds.filter(
          (id) => state.canvasNodes.get(id)?.type !== 'chat'
        );
        if (deletableIds.length === 0) return;
        e.preventDefault();
        setNodesToDelete(deletableIds);
        setShowDeleteConfirm(true);
      }

      // Select all nodes with Ctrl/Cmd+A (only if not typing)
      if ((e.ctrlKey || e.metaKey) && e.key === 'a' && !isTyping) {
        e.preventDefault();
        dispatch({ type: ACTIONS.SELECT_ALL_NODES });
      }

      // Duplicate selected nodes with Ctrl/Cmd+D (only if not typing)
      if ((e.ctrlKey || e.metaKey) && e.key === 'd' && state.selectedNodeIds.length > 0 && !isTyping) {
        e.preventDefault();
        dispatch({ type: ACTIONS.DUPLICATE_NODES, payload: state.selectedNodeIds });
      }

      // Copy selected nodes with Ctrl/Cmd+C (only if not typing)
      if ((e.ctrlKey || e.metaKey) && e.key === 'c' && state.selectedNodeIds.length > 0 && !isTyping) {
        clipboardRef.current = state.selectedNodeIds.map((id) => {
          const node = state.canvasNodes.get(id);
          return node ? { ...node, config: JSON.parse(JSON.stringify(node.config || {})) } : null;
        }).filter(Boolean);
      }

      // Paste copied nodes with Ctrl/Cmd+V (only if not typing)
      if ((e.ctrlKey || e.metaKey) && e.key === 'v' && clipboardRef.current?.length > 0 && !isTyping) {
        e.preventDefault();
        const pastedIds = [];
        for (const original of clipboardRef.current) {
          if (original.type === 'chat') continue;
          const newId = `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
          dispatch({
            type: ACTIONS.ADD_NODE,
            payload: {
              type: original.type,
              x: (original.x || 0) + 50,
              y: (original.y || 0) + 50,
              config: JSON.parse(JSON.stringify(original.config || {})),
              nodeType: original.nodeType,
            },
          });
          pastedIds.push(newId);
        }
        clipboardRef.current = clipboardRef.current.map((n) => ({
          ...n,
          x: (n.x || 0) + 50,
          y: (n.y || 0) + 50,
        }));
      }

      // Cancel connection with Escape (works even when typing)
      if (e.key === 'Escape' && state.isConnecting) {
        dispatch({ type: ACTIONS.CANCEL_CONNECTION });
      }

      // Cancel selection with Escape (works even when typing)
      if (e.key === 'Escape' && state.selectedNodeIds.length > 0) {
        dispatch({ type: ACTIONS.SELECT_NODES, payload: [] });
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [state.selectedNodeIds, state.isConnecting, dispatch, ACTIONS, readOnly]);
  const confirmDelete = () => {
    if (nodesToDelete.length === 1) {
      dispatch({ type: ACTIONS.REMOVE_NODE, payload: nodesToDelete[0] });
    } else {
      dispatch({ type: ACTIONS.REMOVE_NODES, payload: nodesToDelete });
    }
    setShowDeleteConfirm(false);
    setNodesToDelete([]);
  };
  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    if (e.target === canvasRef.current) {
      setIsDragging(false);
    }
  };

  const handleDrop = (e) => {
    if (readOnly) return;
    e.preventDefault();
    setIsDragging(false);

    try {
      const nodeType = JSON.parse(e.dataTransfer.getData('application/json'));

      if (!nodeType) {
        safeError('No node type found in drag data');
        return;
      }

      // Check if node is an initiator type
      const initiatorTypes = ['chat', 'scheduled-start', 'webhook'];
      const isInitiator = initiatorTypes.includes(nodeType.id);

      // If it's an initiator, check if one already exists on canvas
      if (isInitiator) {
        const existingInitiator = Array.from(state.canvasNodes.values()).find(
          node => initiatorTypes.includes(node.type)
        );

        if (existingInitiator) {
          const initiatorName = existingInitiator.config?.label || existingInitiator.nodeType?.name || 'Initiator';
          setExistingInitiatorName(initiatorName);
          setShowInitiatorAlert(true);
          return; // Prevent adding the node
        }
      }

      const canvasRect = canvasRef.current.getBoundingClientRect();
      const x = (e.clientX - canvasRect.left - state.canvasOffset.x) / state.zoomLevel - 90;
      const y = (e.clientY - canvasRect.top - state.canvasOffset.y) / state.zoomLevel - 40;

      dispatch({
        type: ACTIONS.ADD_NODE,
        payload: {
          type: nodeType.id,
          x: Math.max(0, x),
          y: Math.max(0, y),
          config: getDefaultConfig(nodeType.id),
          nodeType: nodeType,
        },
      });
    } catch (error) {
      safeError('Error dropping node:', error);
    }
  };

  const handleCanvasClick = (e) => {
    setContextMenu(null);

    if (e.target === canvasRef.current || e.target.classList.contains('canvas-overlay')) {
      if (!e.ctrlKey && !e.metaKey) {
        dispatch({ type: ACTIONS.SELECT_NODES, payload: [] });
      }

      if (state.isConnecting) {
        dispatch({ type: ACTIONS.CANCEL_CONNECTION });
      }
    }
  };

  const handleCanvasMouseDown = (e) => {
    safeLog('Canvas mousedown:', {
      button: e.button,
      target: e.target,
      targetClass: e.target.className,
      isCanvas: e.target === canvasRef.current,
      hasOverlayClass: e.target.classList?.contains('canvas-overlay')
    });

    // Right-click for panning
    if (e.button === 2) {
      e.preventDefault();
      setIsPanning(true);
      setPanStart({ x: e.clientX - state.canvasOffset.x, y: e.clientY - state.canvasOffset.y });
      return;
    }

    // Left-click on empty canvas
    if (e.button === 0 && (e.target === canvasRef.current || e.target.classList.contains('canvas-overlay'))) {
      // Shift key = selection rectangle, otherwise = pan
      if (e.shiftKey) {
        safeLog('Starting selection box...');
        const canvasRect = canvasRef.current.getBoundingClientRect();
        const x = (e.clientX - canvasRect.left - state.canvasOffset.x) / state.zoomLevel;
        const y = (e.clientY - canvasRect.top - state.canvasOffset.y) / state.zoomLevel;

        setIsSelecting(true);
        setSelectionBox({ startX: x, startY: y, endX: x, endY: y });
        safeLog('Selection started at:', x, y);
      } else {
        // Left-click panning on background
        e.preventDefault();
        setIsPanning(true);
        setPanStart({ x: e.clientX - state.canvasOffset.x, y: e.clientY - state.canvasOffset.y });
      }
    } else {
      safeLog('No canvas interaction - condition failed');
    }
  };

  const handleCanvasMouseMove = (e) => {
    // Handle canvas panning
    if (isPanning) {
      const newOffset = {
        x: e.clientX - panStart.x,
        y: e.clientY - panStart.y,
      };
      dispatch({ type: ACTIONS.SET_CANVAS_OFFSET, payload: newOffset });
      return;
    }

    // Handle selection rectangle
    if (isSelecting) {
      const canvasRect = canvasRef.current.getBoundingClientRect();
      const x = (e.clientX - canvasRect.left - state.canvasOffset.x) / state.zoomLevel;
      const y = (e.clientY - canvasRect.top - state.canvasOffset.y) / state.zoomLevel;

      safeLog('Selection box dragging to:', x, y);
      setSelectionBox(prev => ({ ...prev, endX: x, endY: y }));
    }
  };

  const handleCanvasMouseUp = (e) => {
    // End panning
    if (isPanning) {
      setIsPanning(false);
      return;
    }

    // End selection and select nodes in rectangle
    if (isSelecting) {
      setIsSelecting(false);

      const minX = Math.min(selectionBox.startX, selectionBox.endX);
      const maxX = Math.max(selectionBox.startX, selectionBox.endX);
      const minY = Math.min(selectionBox.startY, selectionBox.endY);
      const maxY = Math.max(selectionBox.startY, selectionBox.endY);

      // Only select if selection box is large enough (avoid accidental clicks)
      const width = maxX - minX;
      const height = maxY - minY;

      safeLog('Selection box size:', width, 'x', height);

      if (width > 3 || height > 3) {
        const selectedIds = [];
        for (const [nodeId, node] of state.canvasNodes) {
          const nodeRight = node.x + 200; // node width
          const nodeBottom = node.y + 90; // node min height

          // Check if node intersects with selection box
          if (node.x < maxX && nodeRight > minX && node.y < maxY && nodeBottom > minY) {
            selectedIds.push(nodeId);
          }
        }

        safeLog('Nodes in selection box:', selectedIds);

        if (selectedIds.length > 0) {
          if (e.ctrlKey || e.metaKey) {
            // Add to selection
            const newSelection = [...new Set([...state.selectedNodeIds, ...selectedIds])];
            safeLog('Adding to selection:', newSelection);
            dispatch({ type: ACTIONS.SELECT_NODES, payload: newSelection });
          } else {
            // Replace selection
            safeLog('Replacing selection with:', selectedIds);
            dispatch({ type: ACTIONS.SELECT_NODES, payload: selectedIds });
          }
        } else {
          safeLog('No nodes found in selection box');
        }
      }

      setSelectionBox({ startX: 0, startY: 0, endX: 0, endY: 0 });
    }
  };

  const handleContextMenu = (e) => {
    e.preventDefault();
    if (readOnly) return;

    if (state.selectedNodeIds.length > 0) {
      setContextMenu({ x: e.clientX, y: e.clientY });
    } else {
      setContextMenu(null);
    }
  };

  // Add mouse move and up listeners when panning or selecting
  useEffect(() => {
    if (isPanning || isSelecting) {
      window.addEventListener('mousemove', handleCanvasMouseMove);
      window.addEventListener('mouseup', handleCanvasMouseUp);

      return () => {
        window.removeEventListener('mousemove', handleCanvasMouseMove);
        window.removeEventListener('mouseup', handleCanvasMouseUp);
      };
    }
  }, [isPanning, isSelecting, panStart, selectionBox, state.canvasNodes, state.selectedNodeIds, state.canvasOffset, state.zoomLevel]);

  // Handle wheel events for scroll and trackpad
  const handleWheel = (e) => {
    e.preventDefault();

    // Pinch zoom (Ctrl key set by browser for trackpad pinch)
    if (e.ctrlKey) {
      const canvasRect = canvasRef.current.getBoundingClientRect();
      const mouseX = e.clientX - canvasRect.left;
      const mouseY = e.clientY - canvasRect.top;

      const zoomDelta = e.deltaY > 0 ? 0.95 : 1.05;
      const newZoom = Math.min(Math.max(state.zoomLevel * zoomDelta, 0.3), 3);

      // Zoom centered on cursor position
      const pointBeforeZoomX = (mouseX - state.canvasOffset.x) / state.zoomLevel;
      const pointBeforeZoomY = (mouseY - state.canvasOffset.y) / state.zoomLevel;
      const pointAfterZoomX = pointBeforeZoomX * newZoom;
      const pointAfterZoomY = pointBeforeZoomY * newZoom;

      const newOffsetX = mouseX - pointAfterZoomX;
      const newOffsetY = mouseY - pointAfterZoomY;

      dispatch({ type: ACTIONS.SET_ZOOM, payload: newZoom });
      dispatch({ type: ACTIONS.SET_CANVAS_OFFSET, payload: { x: newOffsetX, y: newOffsetY } });
      return;
    }

    // Mouse wheel: Large jumps (>= 40) with no horizontal movement
    // Trackpad: Small increments or any horizontal movement
    const isMouseWheel = Math.abs(e.deltaY) >= 40 && e.deltaX === 0;

    if (isMouseWheel) {
      // ZOOM for mouse wheel
      const canvasRect = canvasRef.current.getBoundingClientRect();
      const mouseX = e.clientX - canvasRect.left;
      const mouseY = e.clientY - canvasRect.top;

      const zoomDelta = e.deltaY > 0 ? 0.9 : 1.1;
      const newZoom = Math.min(Math.max(state.zoomLevel * zoomDelta, 0.3), 3);

      // Zoom centered on cursor position
      const pointBeforeZoomX = (mouseX - state.canvasOffset.x) / state.zoomLevel;
      const pointBeforeZoomY = (mouseY - state.canvasOffset.y) / state.zoomLevel;
      const pointAfterZoomX = pointBeforeZoomX * newZoom;
      const pointAfterZoomY = pointBeforeZoomY * newZoom;

      const newOffsetX = mouseX - pointAfterZoomX;
      const newOffsetY = mouseY - pointAfterZoomY;

      dispatch({ type: ACTIONS.SET_ZOOM, payload: newZoom });
      dispatch({ type: ACTIONS.SET_CANVAS_OFFSET, payload: { x: newOffsetX, y: newOffsetY } });
    } else {
      // PAN for trackpad
      const newOffset = {
        x: state.canvasOffset.x - e.deltaX,
        y: state.canvasOffset.y - e.deltaY,
      };
      dispatch({ type: ACTIONS.SET_CANVAS_OFFSET, payload: newOffset });
    }
  };

  // Add wheel event listener with passive: false to allow preventDefault
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.addEventListener('wheel', handleWheel, { passive: false });
      return () => {
        canvas.removeEventListener('wheel', handleWheel);
      };
    }
  }, [state.zoomLevel, state.canvasOffset]);

  const handleZoomIn = () => {
    dispatch({ type: ACTIONS.SET_ZOOM, payload: Math.min(state.zoomLevel * 1.2, 3) });
  };

  const handleZoomOut = () => {
    dispatch({ type: ACTIONS.SET_ZOOM, payload: Math.max(state.zoomLevel / 1.2, 0.3) });
  };

  const handleFitScreen = () => {
    dispatch({ type: ACTIONS.SET_ZOOM, payload: 1 });
  };

  const handleUndo = () => {
    dispatch({ type: ACTIONS.UNDO });
  };

  const handleRedo = () => {
    dispatch({ type: ACTIONS.REDO });
  };

  const handleTest = () => {
    // TODO: Open test modal
    safeLog('Test clicked');
  };

  const handleSaveDraft = () => {
    const name = prompt('Enter draft name:');
    if (name) {
      dispatch({ type: ACTIONS.SAVE_DRAFT, payload: { name } });
      alert('Draft saved!');
    }
  };

  const handlePublish = async () => {
    if (state.canvasNodes.size === 0) {
      alert('Cannot publish empty workflow. Add some nodes first.');
      return;
    }

    try {
      // Determine if we're creating or updating
      const isUpdate = state.currentWorkflow && state.currentWorkflow.id;
      
      // Get workflow name
      let workflowName;
      if (isUpdate) {
        workflowName = prompt('Update workflow name:', state.currentWorkflow.name);
        if (!workflowName) return; // User cancelled
      } else {
        workflowName = prompt('Enter workflow name:');
        if (!workflowName) return; // User cancelled
      }

      // Build nodes array (convert Map to array)
      const nodesArray = Array.from(state.canvasNodes.entries()).map(([id, node]) => ({
        id,
        type: node.type,
        position: { x: node.x, y: node.y },
        data: {
          label: node.config?.label || node.nodeType?.name || 'Node',
          config: node.config
        },
        config: node.config,
      }));

      // Build connections/edges array
      safeLog('💾 PUBLISHING - state.connections:', state.connections);
      state.connections.forEach((conn, idx) => {
        safeLog(`  Connection ${idx}: id="${conn.id}", conditionId="${conn.conditionId}"`);
      });
      
      const edgesArray = state.connections.map(conn => ({
        id: conn.id,
        source: conn.source,
        target: conn.target,
        sourceHandle: conn.sourceHandle || null,
        targetHandle: conn.targetHandle || null,
        conditionId: conn.conditionId || null, // Include conditionId for conditional routing
      }));

      safeLog('💾 edgesArray being saved:');
      edgesArray.forEach((edge, idx) => {
        safeLog(`  Edge ${idx}: id="${edge.id}", conditionId="${edge.conditionId}"`);
      });

      // Prepare workflow data for API
      const workflowData = {
        name: workflowName,
        active: true,
        nodes: JSON.stringify(nodesArray),
        connections: JSON.stringify(edgesArray),
      };

      // If updating, include the ID
      if (isUpdate) {
        workflowData.id = state.currentWorkflow.id;
      }

      safeLog('💾 Sending to API:', isUpdate ? 'UPDATE' : 'CREATE');
      safeLog('💾 connections JSON:', workflowData.connections);

      // Call API
      let result;
      if (isUpdate) {
        result = await updateWorkflow(state.currentWorkflow.id, workflowData);
        alert(`Workflow "${workflowName}" updated successfully.`);
      } else {
        result = await createWorkflow(workflowData);
        alert(`Workflow "${workflowName}" published successfully.`);
      }

      safeLog('Publish result:', result);

      // Update state with workflow info
      dispatch({ 
        type: ACTIONS.PUBLISH_WORKFLOW, 
        payload: { 
          name: workflowName,
          id: result.id,
          ...result
        } 
      });

    } catch (error) {
      safeError('Failed to publish workflow:', error);
      alert(`Failed to publish workflow: ${error.message}`);
    }
  };

  const exportWorkflowJSON = () => {
    // Debug: Log connections before export
    safeLog('📤 EXPORTING - state.connections:', state.connections);
    state.connections.forEach((conn, idx) => {
      safeLog(`  Connection ${idx}: conditionId =`, conn.conditionId);
    });
    
    const workflow = {
      workflow: {
        nodes: Array.from(state.canvasNodes.entries()).map(([id, node]) => ({
          id,
          type: node.type || 'custom',
          position: {
            x: node.x,
            y: node.y
          },
          config: {
            label: node.nodeType?.name || 'Unknown',
            kind: node.type,
            ...node.config
          }
        })),
        edges: state.connections.map(conn => ({
          id: conn.id,
          source: conn.source,
          target: conn.target,
          sourceHandle: conn.sourceHandle,
          targetHandle: conn.targetHandle,
          conditionId: conn.conditionId || null // Include conditionId for conditional routing
        }))
      },
      version: '1.0',
      created: new Date().toISOString()
    };

    // Download JSON file
    const blob = new Blob([JSON.stringify(workflow, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `workflow-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const importWorkflowJSON = () => {
    // Create a file input element
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    
    input.onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const imported = JSON.parse(event.target.result);
          
          // Support multiple JSON formats:
          // 1. Frontend export format: { workflow: { nodes: [...], edges: [...] } }
          // 2. Backend format: { nodes: [...], edges: [...] }
          let nodesData, edgesData;
          
          if (imported.workflow) {
            // Frontend export format
            nodesData = imported.workflow.nodes;
            edgesData = imported.workflow.edges;
          } else if (imported.nodes) {
            // Backend format
            nodesData = imported.nodes;
            edgesData = imported.edges;
          } else {
            alert('Invalid workflow JSON format. Expected either "workflow.nodes" or "nodes" property.');
            return;
          }

          if (!nodesData || !Array.isArray(nodesData)) {
            alert('Invalid workflow JSON format. Nodes must be an array.');
            return;
          }

          // Transform imported nodes to match internal format
          const nodes = nodesData.map(node => {
            // Extract node type from various possible locations
            const nodeType = node.type || node.data?.config?.type || node.config?.kind;
            
            // Extract config from various possible locations
            const nodeConfig = {
              ...(node.config || {}),
              ...(node.data?.config || {}),
              label: node.data?.label || node.config?.label || node.label
            };
            
            // Find the matching node type definition from APP_DATA
            const nodeTypeDef = APP_DATA.nodeTypes
              .flatMap(cat => cat.nodes)
              .find(n => n.id === nodeType);

            return {
              id: node.id,
              type: nodeType || 'custom',
              x: node.position?.x || node.x || 0,
              y: node.position?.y || node.y || 0,
              config: nodeConfig,
              nodeType: nodeTypeDef || {
                id: nodeType,
                name: nodeConfig.label || 'Unknown',
                icon: '📦',
                color: '#7D7D7D',
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

          // Confirm before loading
          const confirmLoad = confirm(
            `Import workflow with ${nodes.length} nodes and ${connections.length} connections?\n\nThis will replace your current canvas.`
          );

          if (confirmLoad) {
            dispatch({
              type: ACTIONS.LOAD_TEMPLATE,
              payload: {
                nodes: nodes,
                connections: connections
              }
            });
            alert('Workflow imported successfully!');
          }
        } catch (error) {
          safeError('Error importing workflow:', error);
          alert(`Failed to import workflow: ${error.message}`);
        }
      };

      reader.onerror = () => {
        alert('Failed to read file');
      };

      reader.readAsText(file);
    };

    // Trigger file selection
    input.click();
  };

  return (
    <main className="flex-1 flex flex-col relative min-w-0">
      {/* Canvas Container — transparent: the dotted grid is rendered once
          on the BuilderView root so the same dots appear behind Apex OS,
          the navbar, the palette, the canvas and the config panel. */}
      <div
        ref={canvasRef}
        className={`flex-1 relative overflow-hidden ${
          isDragging ? 'ring-2 ring-[#d93854] ring-inset' : ''
        } ${isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
        style={{ backgroundColor: 'transparent' }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleCanvasClick}
        onMouseDown={handleCanvasMouseDown}
        onContextMenu={handleContextMenu}
      >
        {/* Canvas Overlay for Nodes and Connections */}
        <div
          className="canvas-overlay absolute inset-0 pointer-events-none"
          style={{
            transform: `translate(${state.canvasOffset.x}px, ${state.canvasOffset.y}px) scale(${state.zoomLevel})`,
            transformOrigin: 'top left',
          }}
        >
          {/* Render Connections - Below nodes */}
          <svg
            key={`svg-${state.connections.length}-${state.connections.map(c => c.id).join(',')}`}
            className="absolute pointer-events-none"
            style={{
              zIndex: 1,
              overflow: 'visible',
              left: 0,
              top: 0,
              width: '100%',
              height: '100%',
              minWidth: '4000px',
              minHeight: '4000px'
            }}>
            {/* Existing Connections */}
            {state.connections.map((connection, idx) => {
              const sourceNode = state.canvasNodes.get(connection.source);
              const targetNode = state.canvasNodes.get(connection.target);

              if (!sourceNode || !targetNode) return null;

              // Get actual node elements to calculate dimensions
              const sourceEl = document.querySelector(`[data-node-id="${connection.source}"]`);
              const targetEl = document.querySelector(`[data-node-id="${connection.target}"]`);
              
              const sourceWidth = sourceEl?.offsetWidth || 160;
              const sourceHeight = sourceEl?.offsetHeight || 80;
              const targetHeight = targetEl?.offsetHeight || 80;

              // Calculate source position - handle multiple output ports for condition/branches nodes
              let sourceY = sourceNode.y + sourceHeight / 2;
              if ((sourceNode.type === 'condition' || sourceNode.type === 'branches') && connection.conditionId && sourceNode.config?.conditions) {
                const conditionIndex = sourceNode.config.conditions.findIndex(c => c.id === connection.conditionId);
                if (conditionIndex >= 0) {
                  const totalConditions = sourceNode.config.conditions.length;
                  const portSpacing = 100 / (totalConditions + 1);
                  const topPosition = portSpacing * (conditionIndex + 1);
                  sourceY = sourceNode.y + (sourceHeight * topPosition / 100);
                }
              }

              const from = {
                x: sourceNode.x + sourceWidth,
                y: sourceY,
              };
              const to = {
                x: targetNode.x,
                y: targetNode.y + targetHeight / 2,
              };

              // Calculate bezier control points for smooth curves
              const dx = to.x - from.x;
              const cx1 = from.x + Math.min(150, Math.abs(dx) * 0.6);
              const cy1 = from.y;
              const cx2 = to.x - Math.min(150, Math.abs(dx) * 0.6);
              const cy2 = to.y;

              const path = `M ${from.x} ${from.y} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${to.x} ${to.y}`;

              const sourceStyle = getNodeStyle(sourceNode.type);
              const targetStyle = getNodeStyle(targetNode.type);
              const gradientId = `conn-grad-${connection.id}`;

              return (
                <g key={connection.id} className="connection-group">
                  <defs>
                    <linearGradient
                      id={gradientId}
                      gradientUnits="userSpaceOnUse"
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                    >
                      <stop offset="0%" stopColor={sourceStyle.accent} />
                      <stop offset="100%" stopColor={targetStyle.accent} />
                    </linearGradient>
                    <marker
                      id={`perm-arrow-${connection.id}`}
                      viewBox="0 0 10 10"
                      refX={EDGE.arrowMarker.refX}
                      refY={EDGE.arrowMarker.refY}
                      markerWidth={EDGE.arrowMarker.width}
                      markerHeight={EDGE.arrowMarker.height}
                      orient="auto-start-reverse"
                    >
                      <path d="M 0 0 L 10 5 L 0 10 z" fill={targetStyle.accent} />
                    </marker>
                  </defs>

                  {/* Wider invisible path for better click detection */}
                  <path
                    d={path}
                    fill="none"
                    stroke="transparent"
                    strokeWidth="24"
                    className="cursor-pointer pointer-events-auto"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (e.shiftKey || e.ctrlKey) {
                        dispatch({ type: ACTIONS.REMOVE_CONNECTION, payload: connection.id });
                      } else {
                        setSelectedEdge({
                          edge: connection,
                          sourceNode: sourceNode,
                          targetNode: targetNode
                        });
                      }
                    }}
                  />

                  <path
                    d={path}
                    fill="none"
                    stroke={`url(#${gradientId})`}
                    strokeWidth={EDGE.strokeWidth}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    markerEnd={`url(#perm-arrow-${connection.id})`}
                    className="pointer-events-none connection-line"
                  />
                  <circle
                    cx={from.x}
                    cy={from.y}
                    r={EDGE.startDotRadius}
                    fill={COLOR.white}
                    stroke={sourceStyle.accent}
                    strokeWidth={EDGE.startDotStrokeWidth}
                    className="pointer-events-none"
                  />
                </g>
              );
            })}

          </svg>

          {/* Render Nodes on top of connections */}
          {Array.from(state.canvasNodes.entries()).map(([nodeId, nodeData]) => (
            <CanvasNode key={nodeId} nodeId={nodeId} nodeData={nodeData} readOnly={readOnly} />
          ))}

          {/* Temporary Connection Line - Above everything */}
          {state.isConnecting && state.connectionStart && state.tempConnectionEnd && (() => {
            const sourceNode = state.canvasNodes.get(state.connectionStart.nodeId);
            if (!sourceNode) return null;

            // Get actual node element to calculate dimensions
            const sourceEl = document.querySelector(`[data-node-id="${state.connectionStart.nodeId}"]`);
            const sourceWidth = sourceEl?.offsetWidth || 160;
            const sourceHeight = sourceEl?.offsetHeight || 80;

            // Calculate source position - handle multiple output ports for condition/branches nodes
            let sourceY = sourceNode.y + sourceHeight / 2;
            if ((sourceNode.type === 'condition' || sourceNode.type === 'branches') && state.connectionStart.conditionId && sourceNode.config?.conditions) {
              const conditionIndex = sourceNode.config.conditions.findIndex(c => c.id === state.connectionStart.conditionId);
              if (conditionIndex >= 0) {
                const totalConditions = sourceNode.config.conditions.length;
                const portSpacing = 100 / (totalConditions + 1);
                const topPosition = portSpacing * (conditionIndex + 1);
                sourceY = sourceNode.y + (sourceHeight * topPosition / 100);
              }
            }

            const from = {
              x: sourceNode.x + sourceWidth,
              y: sourceY,
            };
            const to = state.tempConnectionEnd;

            const dx = to.x - from.x;
            const cx1 = from.x + Math.min(100, Math.abs(dx) * 0.5);
            const cy1 = from.y;
            const cx2 = to.x - Math.min(100, Math.abs(dx) * 0.5);
            const cy2 = to.y;

            const path = `M ${from.x} ${from.y} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${to.x} ${to.y}`;
            const sourceStyle = getNodeStyle(sourceNode.type);

            return (
              <svg
                key="temp-connection"
                className="absolute inset-0 pointer-events-none"
                style={{
                  zIndex: 1000,
                  width: '100%',
                  height: '100%',
                  position: 'absolute',
                  top: 0,
                  left: 0
                }}
              >
                <defs>
                  <linearGradient
                    id="temp-connection-gradient"
                    gradientUnits="userSpaceOnUse"
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                  >
                    <stop offset="0%" stopColor={sourceStyle.accent} />
                    <stop offset="100%" stopColor={COLOR.medium} />
                  </linearGradient>
                </defs>

                <path
                  d={path}
                  fill="none"
                  stroke="url(#temp-connection-gradient)"
                  strokeWidth={EDGE.strokeWidth}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray="10,6"
                  opacity="0.85"
                >
                  <animate
                    attributeName="stroke-dashoffset"
                    values="16;0"
                    dur="0.8s"
                    repeatCount="indefinite"
                  />
                </path>
                <circle
                  cx={from.x}
                  cy={from.y}
                  r={EDGE.startDotRadius}
                  fill={COLOR.white}
                  stroke={sourceStyle.accent}
                  strokeWidth={EDGE.startDotStrokeWidth}
                />
              </svg>
            );
          })()}

          {/* Selection Rectangle */}
          {isSelecting && (() => {
            const minX = Math.min(selectionBox.startX, selectionBox.endX);
            const minY = Math.min(selectionBox.startY, selectionBox.endY);
            const width = Math.abs(selectionBox.endX - selectionBox.startX);
            const height = Math.abs(selectionBox.endY - selectionBox.startY);

            return (
              <div
                className="absolute pointer-events-none border-2 border-primary bg-primary/20 rounded-sm"
                style={{
                  left: `${minX}px`,
                  top: `${minY}px`,
                  width: `${width}px`,
                  height: `${height}px`,
                  zIndex: 1000,
                  boxShadow: '0 0 0 1px rgba(var(--color-primary), 0.5)',
                }}
              />
            );
          })()}
        </div>

        {/* Empty State */}
        {state.canvasNodes.size === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center">
              <div className="text-6xl mb-4 opacity-50">🎨</div>
              <h3 className="text-xl font-semibold mb-2 text-white">Start Building Your Workflow</h3>
              <p className="text-[#b5b5b5]">
                Drag nodes from the palette to get started
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Edge Inspector Modal */}
      {selectedEdge && (
        <EdgeInspector
          edge={selectedEdge.edge}
          sourceNode={selectedEdge.sourceNode}
          targetNode={selectedEdge.targetNode}
          onClose={() => setSelectedEdge(null)}
          onDelete={
            readOnly
              ? undefined
              : () => {
                  dispatch({ type: ACTIONS.REMOVE_CONNECTION, payload: selectedEdge.edge.id });
                  setSelectedEdge(null);
                }
          }
        />
      )}

      {/* Right-click context menu */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[160px]"
          style={{ top: contextMenu.y, left: contextMenu.x }}
        >
          <button
            className="w-full px-3 py-2 text-sm text-left text-gray-700 hover:bg-gray-100 flex items-center gap-2"
            onClick={() => {
              dispatch({ type: ACTIONS.DUPLICATE_NODES, payload: state.selectedNodeIds });
              setContextMenu(null);
            }}
          >
            <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            Duplicate
            <span className="ml-auto text-xs text-gray-400">{navigator.platform.includes('Mac') ? '⌘D' : 'Ctrl+D'}</span>
          </button>
          <button
            className="w-full px-3 py-2 text-sm text-left text-gray-700 hover:bg-gray-100 flex items-center gap-2"
            onClick={() => {
              clipboardRef.current = state.selectedNodeIds.map((id) => {
                const node = state.canvasNodes.get(id);
                return node ? { ...node, config: JSON.parse(JSON.stringify(node.config || {})) } : null;
              }).filter(Boolean);
              setContextMenu(null);
            }}
          >
            <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            Copy
            <span className="ml-auto text-xs text-gray-400">{navigator.platform.includes('Mac') ? '⌘C' : 'Ctrl+C'}</span>
          </button>
          {clipboardRef.current?.length > 0 && (
            <button
              className="w-full px-3 py-2 text-sm text-left text-gray-700 hover:bg-gray-100 flex items-center gap-2"
              onClick={() => {
                for (const original of clipboardRef.current) {
                  if (original.type === 'chat') continue;
                  dispatch({
                    type: ACTIONS.ADD_NODE,
                    payload: {
                      type: original.type,
                      x: (original.x || 0) + 50,
                      y: (original.y || 0) + 50,
                      config: JSON.parse(JSON.stringify(original.config || {})),
                      nodeType: original.nodeType,
                    },
                  });
                }
                clipboardRef.current = clipboardRef.current.map((n) => ({
                  ...n,
                  x: (n.x || 0) + 50,
                  y: (n.y || 0) + 50,
                }));
                setContextMenu(null);
              }}
            >
              <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
              </svg>
              Paste
              <span className="ml-auto text-xs text-gray-400">{navigator.platform.includes('Mac') ? '⌘V' : 'Ctrl+V'}</span>
            </button>
          )}
          <div className="border-t border-gray-100 my-1" />
          <button
            className="w-full px-3 py-2 text-sm text-left text-red-600 hover:bg-red-50 flex items-center gap-2"
            onClick={() => {
              const deletableIds = state.selectedNodeIds.filter(
                (id) => state.canvasNodes.get(id)?.type !== 'chat'
              );
              if (deletableIds.length === 0) {
                setContextMenu(null);
                return;
              }
              setNodesToDelete(deletableIds);
              setShowDeleteConfirm(true);
              setContextMenu(null);
            }}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Delete
            <span className="ml-auto text-xs text-gray-400">Del</span>
          </button>
        </div>
      )}

      {/* Zoom controls — Figma 86:2494: bg #1a1a1a, padding 16, gap 24, rounded 16.
          Each glyph slot is 32×32 (the SVG mask itself is 24×24).  The "90%"
          reading is Body 1 Bold (20/28). All sizes scaled via useFigmaPx. */}
      <div
        className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center shadow-xl"
        style={{
          backgroundColor: COLOR.darkest,
          padding: px(ZOOM.padding),
          gap: px(ZOOM.gap),
          borderRadius: px(16),
        }}
      >
        <button
          onClick={handleZoomOut}
          className="flex items-center justify-center rounded-md hover:bg-white/5 transition-colors"
          style={{ width: px(ZOOM.iconSize), height: px(ZOOM.iconSize) }}
          title="Zoom out"
        >
          <AppIcon name="zoomOut" size={px(24)} color={COLOR.white} />
        </button>
        <span
          className="text-center"
          style={{
            color: COLOR.medium,
            fontSize: px(FONT.body1Bold.size),
            lineHeight: `${px(FONT.body1Bold.height)}px`,
            fontWeight: FONT.body1Bold.weight,
            minWidth: px(44),
          }}
        >
          {Math.round(state.zoomLevel * 100)}%
        </span>
        <button
          onClick={handleZoomIn}
          className="flex items-center justify-center rounded-md hover:bg-white/5 transition-colors"
          style={{ width: px(ZOOM.iconSize), height: px(ZOOM.iconSize) }}
          title="Zoom in"
        >
          <AppIcon name="zoomIn" size={px(24)} color={COLOR.white} />
        </button>
        <button
          onClick={handleFitScreen}
          className="flex items-center justify-center rounded-md hover:bg-white/5 transition-colors hover:text-white"
          style={{ width: px(ZOOM.iconSize), height: px(ZOOM.iconSize), color: COLOR.medium }}
          title="Fit to screen"
        >
          <AppIcon name="fitScreen" size={px(20)} color="currentColor" />
        </button>
      </div>

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteConfirm}
        title="Delete Node"
        message={nodesToDelete.length === 1 
          ? 'Are you sure you want to delete this node?' 
          : `Are you sure you want to delete ${nodesToDelete.length} nodes?`}
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => {
          setShowDeleteConfirm(false);
          setNodesToDelete([]);
        }}
      />

      {/* Initiator Restriction Alert */}
      <AlertModal
        isOpen={showInitiatorAlert}
        onClose={() => setShowInitiatorAlert(false)}
        title="Initiator Already Exists"
        message={`Only one initiator node is allowed per workflow. The canvas already contains "${existingInitiatorName}". Please delete it first if you want to use a different initiator.`}
        variant="warning"
      />
    </main>
  );
}