/**
 * Shared chat bubble shell — gradient fill, inline agent header (no corner tab).
 */

function HitlStatusChip({ status }) {
  if (!status) return null;
  const cls =
    status === 'approved'
      ? 'bg-green-900/50 text-green-300'
      : status === 'rejected'
        ? 'bg-red-900/50 text-red-300'
        : 'bg-yellow-900/50 text-yellow-300';
  const label =
    status === 'approved' ? '✓ Approved' : status === 'rejected' ? '✕ Rejected' : '⏳ Pending';
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded-full ${cls}`}>{label}</span>
  );
}

export default function ChatMessageBubble({
  variant = 'agent',
  background,
  agentLabel,
  nodeInfo,
  status,
  showHitlStatus = false,
  className = '',
  children,
}) {
  const isUser = variant === 'user';
  const isSystem = variant === 'system';

  return (
    <div
      className={[
        'relative rounded-2xl text-sm leading-relaxed break-words text-white px-4 py-3',
        'ring-1 ring-white/5',
        isUser ? 'ring-[#d93854]/25' : '',
        isSystem ? 'max-w-[85%]' : '',
        isUser ? 'max-w-[85%] w-fit min-w-0' : 'w-full',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ background }}
    >
      {variant === 'agent' && agentLabel && (
        <div className="flex items-center gap-1.5 flex-wrap mb-2 pb-2 border-b border-white/10">
          {nodeInfo?.icon && (
            <span className="flex items-center justify-center w-4 h-4 flex-shrink-0">
              {nodeInfo.icon.startsWith('/') ? (
                <img src={nodeInfo.icon} alt={nodeInfo.name} className="w-4 h-4 brightness-0 invert" />
              ) : (
                <span className="text-xs">{nodeInfo.icon}</span>
              )}
            </span>
          )}
          <span className="text-sm text-white font-medium truncate">{agentLabel}</span>
          {showHitlStatus && <HitlStatusChip status={status} />}
        </div>
      )}
      {children}
    </div>
  );
}

export { HitlStatusChip };
