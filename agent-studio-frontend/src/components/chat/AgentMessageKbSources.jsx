import AppIcon from '../ui/AppIcon';

/**
 * Footer on agent chat bubbles listing KBs wired to that node in the workflow.
 */
export default function AgentMessageKbSources({ kbNames }) {
  if (!kbNames?.length) return null;

  return (
    <div
      className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 border-t border-white/10 pt-2.5 text-[11px] text-[#b5b5b5]"
      aria-label={`Knowledge bases: ${kbNames.join(', ')}`}
    >
      <span className="inline-flex shrink-0 items-center gap-1">
        <AppIcon name="kb" size={13} color="#b5b5b5" weight="regular" />
        <span>Knowledge bases</span>
      </span>
      <span className="text-[#dadada]">
        {kbNames.map((name, i) => (
          <span key={name}>
            {i > 0 && <span className="text-[#6b6b6b]"> · </span>}
            {name}
          </span>
        ))}
      </span>
    </div>
  );
}
