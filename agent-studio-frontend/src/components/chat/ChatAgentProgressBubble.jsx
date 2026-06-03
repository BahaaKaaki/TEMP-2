import { getNodeInfo } from '@/data/appData';
import { getMessageBubbleGradient } from '../builder/nodeCategoryStyles';
import { AgentReplySpinner, TraceActivityLine } from './ChatLiveActivity';
import AgentMessageKbSources from './AgentMessageKbSources';
import ChatMessageBubble from './ChatMessageBubble';

/**
 * In-reply progress surface: shows the current trace step inside an agent bubble.
 */
export default function ChatAgentProgressBubble({
  agentLabel = 'Assistant',
  agentType = 'agent',
  kbNames,
  traceLine,
  executionId,
}) {
  const nodeInfo = agentType ? getNodeInfo(agentType) : null;

  return (
    <div className="flex w-full max-w-full min-w-0 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="min-w-0 max-w-[85%] flex-1">
        <ChatMessageBubble
          variant="agent"
          background={getMessageBubbleGradient(agentType)}
          agentLabel={agentLabel}
          nodeInfo={nodeInfo}
          agentType={agentType}
        >
          <div className="flex w-full min-w-0 items-start gap-2.5">
            <AgentReplySpinner embedded size={18} />
            <div className="min-w-0 flex-1">
              <TraceActivityLine line={traceLine} executionId={executionId} />
            </div>
          </div>
          <AgentMessageKbSources kbNames={kbNames} />
        </ChatMessageBubble>
      </div>
    </div>
  );
}
