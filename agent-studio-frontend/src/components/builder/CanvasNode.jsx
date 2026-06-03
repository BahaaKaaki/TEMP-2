import { useRef, useState, useEffect } from 'react';
import { useWorkflow } from '@/context/WorkflowContext';
import { fetchAllModels } from '@/api/models';
import { getNodeStyle } from './nodeCategoryStyles';
import { COLOR, FONT, CARD, START_NODE } from './figmaSpec';
import AppIcon from '../ui/AppIcon';

export default function CanvasNode({ nodeId, nodeData, readOnly = false }) {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [isConnectingFrom, setIsConnectingFrom] = useState(false);
  const [noteText, setNoteText] = useState(nodeData.config?.content || '');
  const [noteSize, setNoteSize] = useState({
    width: nodeData.config?.width || 250,
    height: nodeData.config?.height || 200
  });
  const [isCollapsed, setIsCollapsed] = useState(nodeData.config?.isCollapsed || false);
  const [providerNames, setProviderNames] = useState({});
  const nodeRef = useRef(null);
  const dragStartPos = useRef({ x: 0, y: 0 });
  const resizeStartPos = useRef({ x: 0, y: 0, width: 0, height: 0 });
  const hasMoved = useRef(false);
  
  const isConditionNode = nodeData.type === 'condition' || nodeData.type === 'branches';
  const isStickyNote = nodeData.type === 'sticky-note';

  const isSelected = state.selectedNodeIds.includes(nodeId);
  const hasIncomingConnection = state.connections.some(conn => conn.target === nodeId);
  const hasOutgoingConnection = state.connections.some(conn => conn.source === nodeId);
  const canStartOutputConnection = isConditionNode || !hasOutgoingConnection;

  // Fetch provider names on mount
  useEffect(() => {
    const loadProviders = async () => {
      try {
        const modelsData = await fetchAllModels();
        const names = {};
        if (modelsData?.providers) {
          Object.entries(modelsData.providers).forEach(([id, data]) => {
            names[id] = data.name;
          });
        }
        setProviderNames(names);
      } catch (error) {
        console.error('Failed to load provider names:', error);
      }
    };
    loadProviders();
  }, []);

  // Update note size when config changes (e.g., when loading from saved state)
  useEffect(() => {
    if (isStickyNote && nodeData.config) {
      setNoteSize({
        width: nodeData.config.width || 250,
        height: nodeData.config.height || 200
      });
      setIsCollapsed(nodeData.config.isCollapsed || false);
    }
  }, [nodeData.config?.width, nodeData.config?.height, nodeData.config?.isCollapsed, isStickyNote]);

  // Handle sticky note text changes
  const handleNoteChange = (e) => {
    if (readOnly) return;
    const newText = e.target.value;
    setNoteText(newText);
    
    // Update config with new text
    dispatch({
      type: ACTIONS.UPDATE_NODE,
      payload: {
        nodeId,
        config: {
          ...nodeData.config,
          content: newText
        }
      }
    });
  };

  // Toggle sticky note collapse/expand
  const toggleNoteCollapse = (e) => {
    e.stopPropagation();
    e.preventDefault();
    
    const newCollapsedState = !isCollapsed;
    setIsCollapsed(newCollapsedState);
    
    // Update config with collapsed state
    dispatch({
      type: ACTIONS.UPDATE_NODE,
      payload: {
        nodeId,
        config: {
          ...nodeData.config,
          isCollapsed: newCollapsedState
        }
      }
    });
  };

  // Handle resize start
  const handleResizeMouseDown = (e) => {
    if (readOnly) return;
    e.stopPropagation();
    e.preventDefault();

    setIsResizing(true);
    
    resizeStartPos.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      width: noteSize.width,
      height: noteSize.height
    };

    document.addEventListener('mousemove', handleResizeMouseMove);
    document.addEventListener('mouseup', handleResizeMouseUp);
  };

  // Handle resize move
  const handleResizeMouseMove = (e) => {
    if (!resizeStartPos.current.clientX) return;

    const scale = state.zoomLevel;
    const deltaX = (e.clientX - resizeStartPos.current.clientX) / scale;
    const deltaY = (e.clientY - resizeStartPos.current.clientY) / scale;

    const newWidth = Math.max(150, resizeStartPos.current.width + deltaX);
    const newHeight = Math.max(100, resizeStartPos.current.height + deltaY);

    setNoteSize({ width: newWidth, height: newHeight });
  };

  // Handle resize end
  const handleResizeMouseUp = () => {
    setIsResizing(false);
    
    // Save the final size to the node config
    dispatch({
      type: ACTIONS.UPDATE_NODE,
      payload: {
        nodeId,
        config: {
          ...nodeData.config,
          width: noteSize.width,
          height: noteSize.height
        }
      }
    });

    document.removeEventListener('mousemove', handleResizeMouseMove);
    document.removeEventListener('mouseup', handleResizeMouseUp);
    resizeStartPos.current = { x: 0, y: 0, width: 0, height: 0 };
  };

  const handleNodeContextMenu = (e) => {
    e.stopPropagation();
    if (!isSelected) {
      dispatch({ type: ACTIONS.SELECT_NODE, payload: nodeId });
    }
  };

  const handleMouseDown = (e) => {
    if (e.button !== 0) return;
    if (e.target.classList.contains('connection-port')) return;
    if (e.target.closest('.resize-handle')) return;
    if (isStickyNote && e.target.tagName === 'TEXTAREA') return;

    e.stopPropagation();

    hasMoved.current = false;

    dragStartPos.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      nodeX: nodeData.x,
      nodeY: nodeData.y,
      ctrlKey: e.ctrlKey,
      metaKey: e.metaKey,
    };

    // Add event listeners
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  };

  const handleMouseMove = (e) => {
    if (!dragStartPos.current.clientX) return;

    const deltaX = e.clientX - dragStartPos.current.clientX;
    const deltaY = e.clientY - dragStartPos.current.clientY;
    const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);

    // Only start dragging if moved more than 5 pixels
    if (distance > 5) {
      if (readOnly) return;
      if (!isDragging) {
        setIsDragging(true);
      }
      hasMoved.current = true;

      const scale = state.zoomLevel;
      const scaledDeltaX = deltaX / scale;
      const scaledDeltaY = deltaY / scale;

      // If multiple nodes are selected and this node is in the selection, move all selected nodes
      if (state.selectedNodeIds.length > 1 && isSelected) {
        dispatch({
          type: ACTIONS.MOVE_NODES,
          payload: {
            nodeIds: state.selectedNodeIds,
            deltaX: scaledDeltaX,
            deltaY: scaledDeltaY,
          },
        });
      } else {
        // Move only this node
        const newX = dragStartPos.current.nodeX + scaledDeltaX;
        const newY = dragStartPos.current.nodeY + scaledDeltaY;

        dispatch({
          type: ACTIONS.MOVE_NODE,
          payload: {
            nodeId,
            x: Math.max(0, newX),
            y: Math.max(0, newY),
          },
        });
      }
    }
  };

  const handleMouseUp = (e) => {
    // Remove event listeners
    document.removeEventListener('mousemove', handleMouseMove);
    document.removeEventListener('mouseup', handleMouseUp);

    // If we moved, save to history now that drag is complete
    if (hasMoved.current && isDragging) {
      if (state.selectedNodeIds.length > 1 && isSelected) {
        // For multi-node move, dispatch a final move with saveToHistory
        dispatch({
          type: ACTIONS.MOVE_NODES,
          payload: {
            nodeIds: state.selectedNodeIds,
            deltaX: 0,
            deltaY: 0,
            saveToHistory: true,
          },
        });
      } else {
        // For single node move, dispatch a final move with saveToHistory
        dispatch({
          type: ACTIONS.MOVE_NODE,
          payload: {
            nodeId,
            x: nodeData.x,
            y: nodeData.y,
            saveToHistory: true,
          },
        });
      }
    }

    // If we didn't move, treat it as a click for selection
    if (!hasMoved.current && dragStartPos.current.clientX) {
      e.stopPropagation();

      const wasCtrlOrMeta = dragStartPos.current.ctrlKey || dragStartPos.current.metaKey;

      console.log('Node clicked:', nodeId, 'Ctrl/Meta:', wasCtrlOrMeta, 'Currently selected:', isSelected);

      if (wasCtrlOrMeta) {
        // Toggle selection with Ctrl/Cmd+Click
        console.log('Toggling selection for:', nodeId);
        dispatch({ type: ACTIONS.TOGGLE_NODE_SELECTION, payload: nodeId });
      } else {
        // Regular click - select only this node
        console.log('Selecting node:', nodeId);
        dispatch({ type: ACTIONS.SELECT_NODE, payload: nodeId });
      }
    }

    setIsDragging(false);
    dragStartPos.current = { x: 0, y: 0 };
    hasMoved.current = false;
  };

  // Connection port handlers
  const handleOutputPortClick = (e) => {
    e.stopPropagation();
    if (readOnly) return;

    if (!state.isConnecting && !canStartOutputConnection) {
      alert('Only one output connection is allowed for this node. Delete the existing connection first.');
      return;
    }

    if (state.isConnecting) {
      // If already connecting, cancel it
      dispatch({ type: ACTIONS.CANCEL_CONNECTION });
      setIsConnectingFrom(false);
    } else {
      // Start a new connection
      dispatch({
        type: ACTIONS.START_CONNECTION,
        payload: { nodeId, port: 'output' }
      });
      setIsConnectingFrom(true);
    }
  };

  const handleInputPortClick = (e) => {
    e.stopPropagation();
    if (readOnly) return;

    if (state.isConnecting && state.connectionStart?.nodeId !== nodeId) {
      // Complete the connection
      dispatch({
        type: ACTIONS.END_CONNECTION,
        payload: { 
          nodeId, 
          port: 'input',
          conditionId: state.connectionStart?.conditionId  // ✅ Pass through conditionId from connection start
        }
      });
      setIsConnectingFrom(false);
    }
  };

  const handleOutputPortMouseDown = (e) => {
    if (readOnly) return;
    e.stopPropagation();
    e.preventDefault();

    if (!canStartOutputConnection) {
      alert('Only one output connection is allowed for this node. Delete the existing connection first.');
      return;
    }

    // Start drag-to-connect
    dispatch({
      type: ACTIONS.START_CONNECTION,
      payload: { nodeId, port: 'output' }
    });
    setIsConnectingFrom(true);

    const handleDragMove = (e) => {
      const canvasRect = nodeRef.current.parentElement.getBoundingClientRect();
      dispatch({
        type: ACTIONS.UPDATE_TEMP_CONNECTION,
        payload: {
          x: (e.clientX - canvasRect.left) / state.zoomLevel,
          y: (e.clientY - canvasRect.top) / state.zoomLevel
        }
      });
    };

    const handleDragEnd = (e) => {
      // Check if we're over an input port
      const element = document.elementFromPoint(e.clientX, e.clientY);
      if (element && element.classList.contains('connection-port') && element.title === 'Input') {
        // Find the node this port belongs to
        const nodeElement = element.closest('[data-node-id]');
        if (nodeElement) {
          const targetNodeId = nodeElement.dataset.nodeId;
          if (targetNodeId !== nodeId) {
            dispatch({
              type: ACTIONS.END_CONNECTION,
              payload: { nodeId: targetNodeId, port: 'input' }
            });
          }
        }
      } else {
        dispatch({ type: ACTIONS.CANCEL_CONNECTION });
      }

      setIsConnectingFrom(false);
      document.removeEventListener('mousemove', handleDragMove);
      document.removeEventListener('mouseup', handleDragEnd);
    };

    document.addEventListener('mousemove', handleDragMove);
    document.addEventListener('mouseup', handleDragEnd);
  };

  const handlePortMouseEnter = (e, portType) => {
    if (state.isConnecting && state.connectionStart?.nodeId !== nodeId && portType === 'input') {
      e.target.style.transform = 'scale(1.5)';
    }
  };

  const handlePortMouseLeave = (e) => {
    e.target.style.transform = '';
  };

  // Clear connection state when component unmounts
  useEffect(() => {
    return () => {
      if (isConnectingFrom) {
        dispatch({ type: ACTIONS.CANCEL_CONNECTION });
      }
    };
  }, []);

  const getNodePreview = () => {
    const config = nodeData.config || {};
    const nodeType = nodeData.type;

    switch (nodeType) {
      case 'condition':
        const conditions = config.conditions || [];
        const conditionCount = conditions.length;
        const conditionSummary = conditions.map(c => {
          if (c.type === 'else') return 'Else';
          return c.caseName || (c.type === 'if' ? 'If' : 'Else If');
        }).join(' → ');
        return conditionCount > 0 ? conditionSummary : 'No conditions defined';

      case 'agent':
        const modelInfo = config.modelProvider && config.modelName
          ? `${providerNames[config.modelProvider] || config.modelProvider}: ${config.modelName}`
          : 'Model not configured';
        const instructions = config.systemInstructions
          ? config.systemInstructions.substring(0, 40) + (config.systemInstructions.length > 40 ? '...' : '')
          : 'No instructions';
        return `${modelInfo} | ${instructions}`;

      case 'chat':
        const chatModel = config.modelProvider && config.modelName
          ? `${providerNames[config.modelProvider] || config.modelProvider}: ${config.modelName}`
          : 'Model not configured';
        return `Start | ${chatModel}`;

      case 'action':
        const actionType = config.actionType || 'web_search';
        if (actionType === 'web_search') {
          const query = config.config?.query || 'No query set';
          return `Web Search: ${query.substring(0, 30)}${query.length > 30 ? '...' : ''}`;
        } else if (actionType === 'api_call') {
          const endpoint = config.config?.endpoint || 'No endpoint';
          return `API: ${endpoint.substring(0, 35)}${endpoint.length > 35 ? '...' : ''}`;
        } else if (actionType === 'mcp_tool') {
          const toolName = config.config?.toolName || 'No tool';
          return `MCP Tool: ${toolName}`;
        }
        return 'Action not configured';

      case 'hitl':
        const mode = config.mode || 'review_and_edit';
        const modeLabel = mode === 'review_and_approve' ? 'Review & Approve'
          : mode === 'review_and_edit' ? 'Review & Edit'
          : 'Edit Only';
        const hitlInstructions = config.instructions
          ? config.instructions.substring(0, 30) + (config.instructions.length > 30 ? '...' : '')
          : 'No instructions';
        return `${modeLabel} | ${hitlInstructions}`;

      case 'output':
      case 'end':
        const formats = Array.isArray(config.exportFormats) && config.exportFormats.length > 0
          ? config.exportFormats.join(', ')
          : 'No format selected';
        const displayMode = config.displayMode || 'conversational';
        return `Export: ${formats} | ${displayMode}`;

      case 'start':
        return config.label || 'Workflow Start';

      case 'manual-input':
        return config.placeholder || 'Manual text entry';

      default:
        return nodeData.nodeType?.description || 'No description';
    }
  };

  // Get category color for node background - Strategy& palette
  const getCategoryColor = () => {
    const colorMap = {
      // Initiators (light blue)
      'chat': '#DBEAFE',
      'scheduled-start': '#DBEAFE',
      'webhook': '#DBEAFE',
      'start': '#DBEAFE',
      'manual-input': '#DBEAFE',
      
      // Processors (light rose)
      'agent': '#FDE8E8',
      'researcher': '#FDE8E8',
      'business-analyst': '#FDE8E8',
      'opportunity-classifier': '#FDE8E8',
      'data-classifier': '#FDE8E8',
      'financial-modeler': '#FDE8E8',
      'action': '#FDE8E8',
      'condition': '#991B1B', // Dark red for condition/logic nodes
      
      // Review (neutral gray)
      'human-in-the-loop': '#F3F4F6',
      'hitl': '#F3F4F6',
      'ai-judge': '#F3F4F6',
      
      // Generators (light mint green)
      'pdf-generator': '#D1FAE5',
      'excel-generator': '#D1FAE5',
      'output': '#D1FAE5',
      'end': '#D1FAE5',
    };
    return colorMap[nodeData.type] || 'var(--color-secondary)';
  };

  // Special rendering for sticky notes
  if (isStickyNote) {
    // Collapsed state - show small message icon
    if (isCollapsed) {
      return (
        <div
          ref={nodeRef}
          data-node-id={nodeId}
          onClick={toggleNoteCollapse}
          className={`
            group
            absolute
            w-12 h-12
            rounded-full
            cursor-pointer
            pointer-events-auto
            transition-all duration-200 ease-out
            hover:shadow-xl hover:scale-110
            flex items-center justify-center
            ${isSelected
              ? 'ring-2 ring-primary ring-offset-2 shadow-xl'
              : 'shadow-lg'
            }
            ${isDragging
              ? 'shadow-2xl opacity-80 scale-105'
              : ''
            }
          `}
          style={{
            left: `${nodeData.x}px`,
            top: `${nodeData.y}px`,
            backgroundColor: '#F4CACA',
            zIndex: isDragging ? 50 : isSelected ? 30 : 5,
          }}
          onMouseDown={handleMouseDown}
          onContextMenu={handleNodeContextMenu}
        >
          {nodeData.nodeType?.icon?.startsWith('/') ? (
            <img src={nodeData.nodeType.icon} alt="Sticky Note" className="w-6 h-6" />
          ) : (
          <span className="text-2xl">💬</span>
          )}
        </div>
      );
    }

    // Expanded state - show full note
    return (
      <div
        ref={nodeRef}
        data-node-id={nodeId}
        className={`
          group
          absolute
          rounded-lg p-4
          cursor-grab active:cursor-grabbing
          pointer-events-auto
          transition-all duration-200 ease-out
          hover:shadow-lg
          ${isSelected
            ? 'ring-2 ring-primary ring-offset-1 shadow-xl'
            : 'shadow-md'
          }
          ${isDragging
            ? 'shadow-2xl opacity-80 scale-105 cursor-grabbing'
            : ''
          }
          ${isResizing
            ? 'shadow-2xl'
            : ''
          }
        `}
        style={{
          left: `${nodeData.x}px`,
          top: `${nodeData.y}px`,
          width: `${noteSize.width}px`,
          height: `${noteSize.height}px`,
          backgroundColor: '#F4CACA',
          zIndex: isDragging || isResizing ? 50 : isSelected ? 30 : 5,
        }}
        onMouseDown={handleMouseDown}
        onContextMenu={handleNodeContextMenu}
      >
        {/* Collapse Button - Top Right */}
        <button
          onClick={toggleNoteCollapse}
          className="absolute top-2 right-2 w-6 h-6 rounded-full bg-[#A32020]/50 hover:bg-[#A32020] opacity-0 group-hover:opacity-100 transition-all flex items-center justify-center text-xs text-white"
          title="Collapse note"
        >
          ➖
        </button>

        <textarea
          value={noteText}
          onChange={handleNoteChange}
          placeholder="Type your note here..."
          className="w-full h-full resize-none bg-transparent border-none outline-none text-gray-800 text-sm font-handwriting placeholder-gray-400"
          style={{ fontFamily: '"Comic Sans MS", "Segoe Print", cursive' }}
        />
        
        {/* Resize Handle - Bottom Right Corner */}
        <div
          onMouseDown={handleResizeMouseDown}
          className="resize-handle absolute bottom-0 right-0 w-5 h-5 cursor-se-resize opacity-0 group-hover:opacity-100 transition-opacity"
          style={{
            background: 'linear-gradient(135deg, transparent 50%, rgba(163, 32, 32, 0.5) 50%)',
            borderBottomRightRadius: '0.5rem'
          }}
        >
          <div className="absolute bottom-0.5 right-0.5 w-3 h-3 border-r-2 border-b-2 border-[#A32020]/50"></div>
        </div>
      </div>
    );
  }

  // Pull category styling (Figma 86:2447 transcribed in nodeCategoryStyles.js)
  const style = getNodeStyle(nodeData.type);
  const isCondition = nodeData.type === 'condition' || nodeData.type === 'branches';
  const isChatStart = nodeData.type === 'chat';

  // Figma 86:2533 / 86:2538 / 86:2543 — every card uses the same chrome.
  // Start (chat) node is a circle for visual distinction from step cards.
  const cardStyle = {
    left: `${nodeData.x}px`,
    top: `${nodeData.y}px`,
    zIndex: isDragging ? 50 : isSelected ? 30 : 10,
    width: isCondition ? 320 : isChatStart ? START_NODE.size : CARD.width,
    height: isChatStart ? START_NODE.size : undefined,
    ...(isChatStart
      ? { padding: START_NODE.padding, gap: START_NODE.gap }
      : {
          paddingTop: CARD.paddingTop,
          paddingRight: CARD.paddingRight,
          paddingBottom: CARD.paddingBottom,
          paddingLeft: CARD.paddingLeft,
          gap: CARD.gap,
        }),
    borderRadius: isChatStart ? '50%' : CARD.radius,
    borderWidth: CARD.borderWidth,
    borderStyle: 'solid',
    borderColor: style.border,
    background: isSelected ? style.cardSolid : style.cardGradient,
    boxShadow: isSelected ? `${CARD.glow} ${style.border}` : 'none',
  };

  // Icon container — Figma 86:2544 (Chat) / 86:2539 (Agent) / 86:2534 (Human):
  // a 36×36 TRANSPARENT box.  The icon SHAPE itself is filled with the
  // category accent color (no colored square container behind it) — see
  // `colorIconStyle` below.
  const iconTileStyle = {
    width: CARD.iconTile.size,
    height: CARD.iconTile.size,
    flexShrink: 0,
    position: 'relative',
  };

  return (
    <div
      ref={nodeRef}
      data-node-id={nodeId}
      className={`
        group absolute cursor-grab active:cursor-grabbing pointer-events-auto
        transition-all duration-200 ease-out flex
        ${isChatStart ? 'flex-col items-center justify-center text-center' : isCondition ? 'items-start' : 'items-center'}
        ${isDragging ? 'opacity-90 scale-105 cursor-grabbing' : 'hover:scale-[1.02]'}
      `}
      style={cardStyle}
      onMouseDown={handleMouseDown}
      onContextMenu={handleNodeContextMenu}
      title={isCondition ? 'Condition Node' : isChatStart ? (nodeData.config?.label || 'Start') : getNodePreview()}
    >
      {/* Node Content */}
      {isChatStart ? (
        <>
          <span className="flex items-center justify-center" style={{ width: 32, height: 32 }}>
            <AppIcon name="start" size={28} color={style.accent} weight="fill" />
          </span>
          <span
            className="truncate max-w-[72px]"
            style={{
              color: COLOR.white,
              fontSize: FONT.body3.size,
              lineHeight: `${FONT.body3.height}px`,
              fontWeight: FONT.body2Bold.weight,
            }}
          >
            {nodeData.config?.label || 'Start'}
          </span>
        </>
      ) : isCondition ? (
        // Condition node — same Figma card chrome, but with inline condition list
        <>
          <span className="flex items-center justify-center mt-0.5" style={iconTileStyle}>
            {nodeData.nodeType?.icon?.startsWith('/') ? (
              <AppIcon
                src={nodeData.nodeType?.icon}
                size={CARD.iconTile.innerIcon}
                color={style.accent}
                weight="regular"
                aria-hidden={false}
                style={{ display: 'block' }}
              />
            ) : (
              <span style={{ color: style.accent, fontSize: 20 }}>{nodeData.nodeType?.icon || '❓'}</span>
            )}
          </span>

          <div className="flex flex-col flex-1 min-w-0">
            <span
              className="truncate"
              style={{
                color: COLOR.white,
                fontSize: FONT.body1.size,
                lineHeight: `${FONT.body1.height}px`,
                fontWeight: FONT.body1.weight,
              }}
            >
              {nodeData.config?.label || nodeData.nodeType?.name || 'Condition'}
            </span>
            <span
              className="truncate"
              style={{
                color: COLOR.medium,
                fontSize: FONT.body3.size,
                lineHeight: `${FONT.body3.height}px`,
                fontWeight: FONT.body3.weight,
              }}
            >
              {nodeData.nodeType?.name || 'Route'}
            </span>

            {nodeData.config?.conditions && nodeData.config.conditions.length > 0 ? (
              <div
                className="flex flex-col mt-2"
                style={{
                  minHeight: `${nodeData.config.conditions.length * 32}px`,
                  gap: nodeData.config.conditions.length > 2 ? '6px' : '8px',
                }}
              >
                {nodeData.config.conditions.map((condition) => (
                  <div
                    key={condition.id}
                    className="flex items-center gap-2 px-2 py-1.5 pr-4 bg-black/30 border border-white/10 rounded-lg"
                  >
                    {condition.type === 'else' ? (
                      <span className="text-[#b5b5b5] text-xs font-medium flex-1">Else</span>
                    ) : (
                      <span className="text-[#b5b5b5] font-mono text-[11px] truncate flex-1">
                        {condition.expression || 'No expression'}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-xs text-[#b5b5b5]/70 py-2">No conditions defined</span>
            )}
          </div>
        </>
      ) : (
        // Regular node layout — Figma 86:2538 (AI Agent / Chat / Human Review)
        // Icon is the colored shape itself, no surrounding container.
        <>
          <span className="flex items-center justify-center" style={iconTileStyle}>
            {nodeData.nodeType?.icon?.startsWith('/') ? (
              <AppIcon
                src={nodeData.nodeType?.icon}
                size={CARD.iconTile.innerIcon}
                color={style.accent}
                weight="regular"
                aria-hidden={false}
                style={{ display: 'block' }}
              />
            ) : (
              <span style={{ color: style.accent, fontSize: 20 }}>{nodeData.nodeType?.icon || '❓'}</span>
            )}
          </span>
          <div className="flex flex-col min-w-0 flex-1">
            <span
              className="truncate"
              style={{
                color: COLOR.white,
                fontSize: FONT.body1.size,
                lineHeight: `${FONT.body1.height}px`,
                fontWeight: FONT.body1.weight,
              }}
            >
              {nodeData.config?.label || nodeData.nodeType?.name || 'Unknown'}
            </span>
            <span
              className="truncate"
              style={{
                color: COLOR.medium,
                fontSize: FONT.body3.size,
                lineHeight: `${FONT.body3.height}px`,
                fontWeight: FONT.body3.weight,
              }}
            >
              {nodeData.nodeType?.name || 'Node'}
            </span>
          </div>
        </>
      )}

      {/* Input Port - hidden for chat nodes, hidden when connected unless hover */}
      {nodeData.type !== 'chat' && (
      <div
          className="connection-port absolute w-3 h-3 rounded-full bg-[#d93854] border-2 border-white/90 cursor-pointer transition-all duration-200 left-[-6px] top-1/2 -translate-y-1/2 z-20 hover:scale-150 hover:bg-[#e27588]"
        title="Input"
        onClick={(e) => handleInputPortClick(e)}
        onMouseEnter={(e) => handlePortMouseEnter(e, 'input')}
        onMouseLeave={handlePortMouseLeave}
      />
      )}

      {/* Output Ports - Multiple ports for condition / branches nodes */}
      {(nodeData.type === 'condition' || nodeData.type === 'branches') && nodeData.config?.conditions ? (
        // Multiple output ports for each condition
        nodeData.config.conditions.map((condition, index) => {
          const totalConditions = nodeData.config.conditions.length;
          const portSpacing = 100 / (totalConditions + 1);
          const topPosition = portSpacing * (index + 1);
          
          return (
            <div
              key={condition.id}
              className="connection-port absolute w-3 h-3 rounded-full bg-[#d93854] border-2 border-white/90 cursor-pointer transition-all duration-200 right-[-6px] z-20 hover:scale-150 hover:bg-[#e27588] group/port"
              style={{ top: `${topPosition}%`, transform: 'translateY(-50%)' }}
              title={condition.caseName || (condition.type === 'else' ? 'Else' : `Condition ${index + 1}`)}
              data-condition-id={condition.id}
              onMouseDown={(e) => {
                e.stopPropagation();
                e.preventDefault();
                // Start connection with condition metadata
                dispatch({
                  type: ACTIONS.START_CONNECTION,
                  payload: { 
                    nodeId, 
                    port: 'output',
                    conditionId: condition.id 
                  }
                });
                setIsConnectingFrom(true);

                const handleDragMove = (e) => {
                  const canvasRect = nodeRef.current.parentElement.getBoundingClientRect();
                  dispatch({
                    type: ACTIONS.UPDATE_TEMP_CONNECTION,
                    payload: {
                      x: (e.clientX - canvasRect.left) / state.zoomLevel,
                      y: (e.clientY - canvasRect.top) / state.zoomLevel
                    }
                  });
                };

                const handleDragEnd = (e) => {
                  const element = document.elementFromPoint(e.clientX, e.clientY);
                  if (element && element.classList.contains('connection-port') && element.title === 'Input') {
                    const nodeElement = element.closest('[data-node-id]');
                    if (nodeElement) {
                      const targetNodeId = nodeElement.dataset.nodeId;
                      if (targetNodeId !== nodeId) {
                        dispatch({
                          type: ACTIONS.END_CONNECTION,
                          payload: { 
                            nodeId: targetNodeId, 
                            port: 'input',
                            conditionId: condition.id 
                          }
                        });
                      }
                    }
                  } else {
                    dispatch({ type: ACTIONS.CANCEL_CONNECTION });
                  }

                  setIsConnectingFrom(false);
                  document.removeEventListener('mousemove', handleDragMove);
                  document.removeEventListener('mouseup', handleDragEnd);
                };

                document.addEventListener('mousemove', handleDragMove);
                document.addEventListener('mouseup', handleDragEnd);
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (state.isConnecting) {
                  dispatch({ type: ACTIONS.CANCEL_CONNECTION });
                  setIsConnectingFrom(false);
                } else {
                  dispatch({
                    type: ACTIONS.START_CONNECTION,
                    payload: { 
                      nodeId, 
                      port: 'output',
                      conditionId: condition.id 
                    }
                  });
                  setIsConnectingFrom(true);
                }
              }}
              onMouseEnter={(e) => handlePortMouseEnter(e, 'output')}
              onMouseLeave={handlePortMouseLeave}
            >
              {/* Port label on hover */}
              <div className="absolute right-full mr-2 top-1/2 -translate-y-1/2 opacity-0 group-hover/port:opacity-100 transition-opacity pointer-events-none whitespace-nowrap">
                <span className="text-xs bg-[#1a1a1a] text-white border border-[#464646] rounded px-2 py-1 shadow-sm">
                  {condition.caseName || (condition.type === 'else' ? 'Else' : condition.type === 'if' ? 'If' : 'Else If')}
                </span>
              </div>
            </div>
          );
        })
      ) : (
        // Single output port for other nodes
      <div
        className="connection-port absolute w-3 h-3 rounded-full bg-[#d93854] border-2 border-white/90 cursor-pointer transition-all duration-200 right-[-6px] top-1/2 -translate-y-1/2 z-20 hover:scale-150 hover:bg-[#e27588]"
        title="Output"
        onMouseDown={(e) => handleOutputPortMouseDown(e)}
        onClick={(e) => handleOutputPortClick(e)}
        onMouseEnter={(e) => handlePortMouseEnter(e, 'output')}
        onMouseLeave={handlePortMouseLeave}
      />
      )}

      {/* Drag indicator (visible on hover) */}
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-40 transition-opacity text-white/60 text-xs pointer-events-none">
        ⋮⋮
      </div>
    </div>
  );
}
