import { getFileEmoji } from './chatAttachmentUtils';

/**
 * File chips for chat attachments.
 * - composer: horizontal row above the input (pending, not yet sent)
 * - message: stacked cards inside a sent user bubble
 */
export default function ChatMessageAttachments({
  files,
  onDelete,
  compact = false,
  variant = 'message',
}) {
  if (!files?.length) return null;

  if (variant === 'composer') {
    return (
      <div className="flex flex-wrap gap-2">
        {files.map((file) => (
          <ComposerFileChip key={file.id} file={file} onDelete={onDelete} />
        ))}
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-2 ${compact ? '' : 'mb-2'}`}>
      {files.map((file) => (
        <MessageFileCard key={file.id} file={file} onDelete={onDelete} />
      ))}
    </div>
  );
}

function ComposerFileChip({ file, onDelete }) {
  const scope = file.scope === 'global' ? 'global' : (file.scope === 'local' ? 'local' : null);
  const agentLabel = file.uploaded_at_agent_label;
  const scopeBadgeText = scope
    ? (agentLabel ? `${scope} · uploaded at ${agentLabel}` : scope)
    : null;
  const scopeBadgeClass = scope === 'global'
    ? 'bg-emerald-800/50 text-emerald-300 border-emerald-700'
    : 'bg-sky-800/50 text-sky-300 border-sky-700';

  return (
    <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-[#464646] rounded-[10px] border border-[#6b6b6b] hover:border-[#d93854]/40 transition-all max-w-full">
      <span className="text-sm flex-shrink-0" aria-hidden>
        {getFileEmoji(file.file_type)}
      </span>
      <span className="text-xs text-white font-medium max-w-[200px] truncate">
        {file.file_name}
      </span>
      <span className="text-xs text-[#b5b5b5] flex-shrink-0">
        {(file.file_size / 1024).toFixed(1)} KB
      </span>
      {scopeBadgeText && (
        <span
          className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full border ${scopeBadgeClass} max-w-[220px] truncate`}
          title={scopeBadgeText}
        >
          {scopeBadgeText}
        </span>
      )}
      <span className={`text-xs flex-shrink-0 ${
        file.parsing_status === 'completed' ? 'text-[#6b6b6b]' :
        file.parsing_status === 'failed' ? 'text-red-400' :
        'text-amber-400'
      }`}>
        {file.parsing_status === 'completed' ? '✓' :
         file.parsing_status === 'failed' ? '✗' :
         '⏳'}
      </span>
      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(file.id, file.file_name)}
          className="w-4 h-4 rounded-[6px] hover:bg-red-500/20 text-[#6b6b6b] hover:text-red-400 flex items-center justify-center transition-all duration-200 flex-shrink-0"
          title="Delete file"
        >
          ×
        </button>
      )}
    </div>
  );
}

function MessageFileCard({ file, onDelete }) {
  const scope = file.scope === 'global' ? 'global' : (file.scope === 'local' ? 'local' : null);
  const agentLabel = file.uploaded_at_agent_label;
  const scopeBadgeText = scope
    ? (agentLabel ? `${scope} · ${agentLabel}` : scope)
    : null;
  const scopeBadgeClass = scope === 'global'
    ? 'bg-emerald-800/50 text-emerald-300 border-emerald-700'
    : 'bg-sky-800/50 text-sky-300 border-sky-700';

  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-[#d93854]/25 bg-black/25 px-3 py-2 min-w-0">
      <span className="text-lg flex-shrink-0" aria-hidden>
        {getFileEmoji(file.file_type)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-white truncate">{file.file_name}</p>
        <p className="text-xs text-[#b5b5b5]">
          {(file.file_size / 1024).toFixed(1)} KB
          {file.parsing_status === 'pending' && ' · Parsing…'}
          {file.parsing_status === 'failed' && ' · Failed'}
        </p>
      </div>
      {scopeBadgeText && (
        <span
          className={`hidden sm:inline text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full border ${scopeBadgeClass} max-w-[140px] truncate`}
          title={scopeBadgeText}
        >
          {scopeBadgeText}
        </span>
      )}
      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(file.id, file.file_name)}
          className="w-7 h-7 rounded-[6px] hover:bg-red-500/20 text-[#6b6b6b] hover:text-red-400 flex items-center justify-center transition-colors flex-shrink-0"
          title="Remove file"
        >
          ×
        </button>
      )}
    </div>
  );
}
