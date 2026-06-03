import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';

function metadataValue(citation, keys) {
  const metadata = citation?.chunk_metadata || {};
  for (const key of keys) {
    if (citation?.[key] !== undefined && citation?.[key] !== null && citation?.[key] !== '') return citation[key];
    if (metadata?.[key] !== undefined && metadata?.[key] !== null && metadata?.[key] !== '') return metadata[key];
  }
  return null;
}

function sourceName(citation) {
  return (
    citation?.document_name
    || citation?.title
    || metadataValue(citation, ['document_name', 'file_name', 'filename', 'source'])
    || citation?.url
    || citation?.chunk_id
    || 'Source'
  );
}

function sourceLocation(citation) {
  const page = metadataValue(citation, ['page_number', 'page', 'slide_number', 'slide']);
  const hasSlide = Boolean(metadataValue(citation, ['slide_number', 'slide']));
  const parts = [];
  if (page) parts.push(hasSlide ? `Slide ${page}` : `Page ${page}`);
  if (citation?.chunk_index !== undefined) parts.push(`Chunk ${Number(citation.chunk_index) + 1}`);
  if (citation?.relevance_score) parts.push(`${Math.round(Number(citation.relevance_score) * 100)}% match`);
  return parts.join(' · ');
}

function sourcePreview(citation, max = 220) {
  const text = String(citation?.chunk_text || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function formatMetadataKey(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function OpenUICitationReference({ citationNumber, citationData }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [tooltipPos, setTooltipPos] = useState({ top: 0, left: 0, flipped: false });
  const badgeRef = useRef(null);

  if (!citationData) {
    return <span className="text-cyan-200">[{citationNumber}]</span>;
  }

  const isWeb = citationData.type === 'web' && citationData.url;
  const title = sourceName(citationData);
  const location = sourceLocation(citationData);
  const preview = sourcePreview(citationData);
  const metadata = citationData.chunk_metadata && typeof citationData.chunk_metadata === 'object'
    ? citationData.chunk_metadata
    : null;

  const computeTooltipPosition = () => {
    const rect = badgeRef.current?.getBoundingClientRect();
    if (!rect) return;
    const tooltipWidth = 320;
    const tooltipHeight = 140;
    const gap = 8;
    const flipped = rect.top < tooltipHeight + gap;
    const top = flipped ? rect.bottom + gap : rect.top - gap;
    let left = rect.left + rect.width / 2 - tooltipWidth / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tooltipWidth - 8));
    setTooltipPos({ top, left, flipped });
  };

  const handleClick = (event) => {
    event.stopPropagation();
    if (isWeb) {
      window.open(citationData.url, '_blank', 'noopener,noreferrer');
      return;
    }
    setShowModal(true);
  };

  return (
    <>
      <button
        ref={badgeRef}
        type="button"
        onMouseEnter={() => {
          computeTooltipPosition();
          setShowTooltip(true);
        }}
        onMouseLeave={() => setShowTooltip(false)}
        onClick={handleClick}
        title={title}
        className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-cyan-300/70 bg-cyan-400/20 px-1 text-[11px] font-bold leading-none text-cyan-100 shadow-[0_0_0_1px_rgba(34,211,238,0.12)] transition hover:scale-105 hover:bg-cyan-400/30 align-baseline"
      >
        {citationNumber}
      </button>

      {showTooltip && createPortal(
        <div
          className="fixed z-[10000] max-w-[90vw] rounded-lg border border-[#464646] bg-[#1a1a1a] p-3 text-xs text-[#dadada] shadow-2xl"
          style={{
            top: tooltipPos.flipped ? tooltipPos.top : undefined,
            bottom: tooltipPos.flipped ? undefined : `${window.innerHeight - tooltipPos.top}px`,
            left: tooltipPos.left,
            width: 320,
          }}
        >
          <div className="truncate font-semibold text-white" title={title}>{title}</div>
          {location && <div className="mt-1 text-[#9d9d9d]">{location}</div>}
          {preview && <div className="mt-2 line-clamp-3 leading-relaxed text-[#cfcfcf]">{preview}</div>}
          <div className="mt-2 border-t border-[#464646] pt-2 text-[#9d9d9d]">
            {isWeb ? 'Click to open source' : 'Click for source details'}
          </div>
        </div>,
        document.body,
      )}

      {!isWeb && showModal && createPortal(
        <div
          className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 p-4"
          onClick={() => setShowModal(false)}
        >
          <div
            className="flex max-h-[82vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[#464646] bg-[#111111] shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-[#464646] px-5 py-4">
              <div className="min-w-0">
                <div className="text-xs font-bold uppercase tracking-wide text-[#d93854]">Source {citationNumber}</div>
                <h3 className="mt-1 break-words text-lg font-semibold text-white">{title}</h3>
                {location && <p className="mt-1 text-sm text-[#9d9d9d]">{location}</p>}
              </div>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="rounded-lg border border-[#464646] px-3 py-1.5 text-sm text-[#dadada] transition hover:border-[#d93854]/60 hover:text-white"
              >
                Close
              </button>
            </div>
            <div className="overflow-y-auto px-5 py-4">
              <div className="rounded-xl border border-[#464646] bg-[#1a1a1a] p-4">
                <div className="mb-2 text-sm font-semibold text-white">Referenced chunk</div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#dadada]">
                  {citationData.chunk_text || 'No source text is available for this citation.'}
                </p>
              </div>
              {metadata && Object.keys(metadata).length > 0 && (
                <details className="mt-4 rounded-xl border border-[#464646] bg-[#1a1a1a] p-4">
                  <summary className="cursor-pointer select-none text-sm font-semibold text-white">Metadata</summary>
                  <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                    {Object.entries(metadata).map(([key, value]) => (
                      <div key={key} className="min-w-0 rounded-lg bg-white/[0.03] px-3 py-2">
                        <div className="text-xs text-[#9d9d9d]">{formatMetadataKey(key)}</div>
                        <div className="mt-0.5 break-words text-[#dadada]">{value == null ? 'N/A' : String(value)}</div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
