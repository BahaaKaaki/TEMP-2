import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { getCitationPageImage } from '../../api/client';

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

function formatMetadataKey(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function OpenUICitationReference({ citationNumber, citationData }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [tooltipPos, setTooltipPos] = useState({ top: 0, left: 0, flipped: false });
  const badgeRef = useRef(null);

  const chunkId = citationData?.chunk_id;
  const kbId = citationData?.kb_id;
  const pageNumber =
    citationData?.chunk_metadata?.page_number ?? citationData?.page_number ?? null;
  const couldHavePageImage = Boolean(chunkId && pageNumber != null);

  const [pageImageUrl, setPageImageUrl] = useState(null);
  // idle | loading | loaded | none
  const [pageImageStatus, setPageImageStatus] = useState('idle');
  const objectUrlRef = useRef(null);
  const fetchStartedRef = useRef(false);
  const mountedRef = useRef(true);

  // Track mount so an async result never updates a unmounted component, and
  // revoke the object URL on unmount. (Reset the flag in the body so React
  // StrictMode's mount/unmount/mount cycle leaves it `true`.)
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, []);

  // Fetch the page snapshot once, on demand (when the modal opens). Triggering
  // from the click handler — not a status-keyed effect — avoids the effect
  // cancelling its own in-flight request and getting stuck on "loading".
  const loadPageImage = () => {
    if (!couldHavePageImage || fetchStartedRef.current) return;
    fetchStartedRef.current = true;
    setPageImageStatus('loading');
    getCitationPageImage(chunkId, kbId)
      .then((url) => {
        if (!mountedRef.current) {
          if (url) URL.revokeObjectURL(url);
          return;
        }
        if (url) {
          objectUrlRef.current = url;
          setPageImageUrl(url);
          setPageImageStatus('loaded');
        } else {
          setPageImageStatus('none');
        }
      })
      .catch(() => {
        if (mountedRef.current) setPageImageStatus('none');
      });
  };

  if (!citationData) {
    return <span className="text-cyan-200">[{citationNumber}]</span>;
  }

  const isWeb = citationData.type === 'web' && citationData.url;
  const title = sourceName(citationData);
  const location = sourceLocation(citationData);
  const metadata = citationData.chunk_metadata && typeof citationData.chunk_metadata === 'object'
    ? citationData.chunk_metadata
    : null;
  const hasImageArea = couldHavePageImage && pageImageStatus !== 'none';

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
    loadPageImage();
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
          <div className="mt-2 border-t border-[#464646] pt-2 text-[#9d9d9d]">
            {isWeb
              ? 'Click to open source'
              : couldHavePageImage
                ? 'Click to view the source page'
                : 'Click for source details'}
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
            className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[#464646] bg-[#111111] shadow-2xl"
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
                className="flex-none rounded-lg border border-[#464646] px-3 py-1.5 text-sm text-[#dadada] transition hover:border-[#d93854]/60 hover:text-white"
              >
                Close
              </button>
            </div>

            <div className="overflow-y-auto px-5 py-4">
              {/* Hero: the actual source page snapshot */}
              {hasImageArea && pageImageStatus === 'loading' && (
                <div className="mb-4 flex h-56 w-full animate-pulse items-center justify-center rounded-xl border border-[#464646] bg-[#1d1d1d] text-xs text-[#6b6b6b]">
                  Loading source page…
                </div>
              )}
              {pageImageStatus === 'loaded' && pageImageUrl && (
                <figure className="mb-4">
                  <div className="overflow-hidden rounded-xl border border-[#464646] bg-black/40">
                    <img
                      src={pageImageUrl}
                      alt={`Source page${pageNumber != null ? ` ${pageNumber}` : ''}`}
                      className="mx-auto block max-h-[60vh] w-auto"
                    />
                  </div>
                  <figcaption className="mt-1.5 text-center text-[11px] text-[#6b6b6b]">
                    {`The exact ${location && /slide/i.test(location) ? 'slide' : 'page'} this answer was drawn from`}
                  </figcaption>
                </figure>
              )}

              {/* The cited passage, shown plainly */}
              <div className="rounded-xl border border-[#464646] bg-[#1a1a1a] p-4">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#9d9d9d]">
                  Referenced text
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#dadada]">
                  {citationData.chunk_text || 'No source text is available for this citation.'}
                </p>
              </div>

              {metadata && Object.keys(metadata).length > 0 && (
                <details className="mt-4 rounded-xl border border-[#464646] bg-[#1a1a1a] p-4">
                  <summary className="cursor-pointer select-none text-sm font-semibold text-white">Details</summary>
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
