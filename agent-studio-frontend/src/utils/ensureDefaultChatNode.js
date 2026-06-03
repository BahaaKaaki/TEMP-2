import { APP_DATA, getDefaultConfig, getNodeInfo } from '@/data/appData';

const DEFAULT_CHAT_X = 80;
const DEFAULT_CHAT_Y = 200;

/**
 * Ensures every workflow canvas has exactly one chat initiator node.
 * Mutates nothing — returns a new nodes array when a chat node is added.
 *
 * @param {Array<{ id: string, type: string, x?: number, y?: number, config?: object, nodeType?: object }>} nodes
 * @param {Array} connections
 * @returns {{ nodes: Array, connections: Array, chatNodeId: string|null, added: boolean }}
 */
export function ensureDefaultChatNode(nodes = [], connections = []) {
  const existingChat = nodes.find((n) => n.type === 'chat');
  if (existingChat) {
    return {
      nodes,
      connections,
      chatNodeId: existingChat.id,
      added: false,
    };
  }

  const chatNodeType = APP_DATA.nodeTypes
    .flatMap((cat) => cat.nodes)
    .find((n) => n.id === 'chat');

  const nodeInfo = getNodeInfo('chat');
  const chatNodeId = `node_chat_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  const chatNode = {
    id: chatNodeId,
    type: 'chat',
    x: DEFAULT_CHAT_X,
    y: DEFAULT_CHAT_Y,
    config: getDefaultConfig('chat'),
    nodeType: chatNodeType || {
      id: 'chat',
      name: nodeInfo?.name || 'Start',
      icon: nodeInfo?.icon || '/icons/chat.svg',
      color: nodeInfo?.color || '#166ac5',
      description: nodeInfo?.description || 'Interactive conversational AI',
    },
  };

  return {
    nodes: [chatNode, ...nodes],
    connections,
    chatNodeId,
    added: true,
  };
}

export function isChatNode(node) {
  return node?.type === 'chat';
}
