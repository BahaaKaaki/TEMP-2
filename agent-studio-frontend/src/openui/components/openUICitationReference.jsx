import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { getCitationPageImage, authenticatedFetch, API_BASE_URL } from '../../api/client';
import { safeError } from '../../utils/safeLogger';

/**
 * Single, shared citation reference used by BOTH chat-message citations and
 * deliverable (OpenUI) citations. Renders [N] as a badge with a hover tooltip;
 * clicking opens a dark modal that consolidates everything: the source page
 * snapshot (when available), the referenced text, document info, and downloads
 * (the page image and/or the whole document). Web citations open their URL.
 */

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
    || 'Source'
  );
}

function sourceLocation(citation) {
  const page = metadataValue(citation, ['page_number', 'page', 'slide_number', 'slide']);
  const hasSlide = Boolean(metadataValue(citation, ['slide_number', 'slide']));
  const parts = [];
  if (page) parts.push(hasSlide ? `Slide ${page}` : `Page ${page}`);
  if (citation?.chunk_index !== undefined && citation?.chunk_index !== null) parts.push(`Chunk ${Number(citation.chunk_index) + 1}`);
  if (citation?.relevance_score) parts.push(`${Math.round(Number(citation.relevance_score) * 100)}% match`);
  return parts.join(' · ');
}

function formatMetadataKey(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return 'N/A';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function shortUrl(url) {
  try {
    const u = new URL(url);
    const path = u.pathname.length > 30 ? `${u.pathname.substring(0, 30)}…` : u.pathname;
    return u.hostname + path;
  } catch {
    return url?.substring(0, 50) || '';
  }
}

export default function OpenUICitationReference({ citationNumber, citationData }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [tooltipPos, setTooltipPos] = useState({ top: 0, left: 0, flipped: false });
  const badgeRef = useRef(null);

  const [pageImageUrl, setPageImageUrl] = useState(null);
  const [pageImageStatus, setPageImageStatus] = useState('idle'); // idle | loading | loaded | none
  const [fullCitation, setFullCitation] = useState(null);
  const [downloadError, setDownloadError] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const objectUrlRef = useRef(null);
  const fetchStartedRef = useRef(false);
  const mountedRef = useRef(true);

  const chunkId = citationData?.chunk_id;
  const kbId = citationData?.kb_id;
  const isWeb = citationData?.type === 'web' && Boolean(citationData?.url);
  const pageNumber =
    citationData?.chunk_metadata?.page_number ?? citationData?.page_number ?? null;
  const couldHavePageImage = Boolean(chunkId && pageNumber != null);

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

  // On open, load (in parallel) the page snapshot and the full citation details
  // (document info + document_id for download). Triggered from the click
  // handler so the request can never be cancelled by an effect re-run.
  const loadDetails = () => {
    if (isWeb || fetchStartedRef.current) return;
    fetchStartedRef.current = true;

    if (couldHavePageImage) {
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
    }

    if (chunkId) {
      const url = `${API_BASE_URL}/api/citations/${encodeURIComponent(chunkId)}${kbId ? `?kb_id=${encodeURIComponent(kbId)}` : ''}`;
      authenticatedFetch(url)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (mountedRef.current && data) setFullCitation(data);
        })
        .catch(() => {});
    }
  };

  if (!citationData) {
    return <span className="text-cyan-200">[{citationNumber}]</span>;
  }

  // Merge the on-demand details over the inline citation; keep chunk_metadata.
  const merged = { ...citationData, ...(fullCitation || {}) };
  if (!merged.chunk_metadata && citationData.chunk_metadata) merged.chunk_metadata = citationData.chunk_metadata;

  const title = sourceName(merged);
  const location = sourceLocation(merged);
  const metadata = merged.chunk_metadata && typeof merged.chunk_metadata === 'object' ? merged.chunk_metadata : null;
  const documentId = merged.document_id;
  const chunkText = merged.chunk_text || citationData.chunk_text;

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
    loadDetails();
  };

  const handleDownloadDocument = async () => {
    setDownloadError(null);
    if (!documentId) {
      setDownloadError('The source document is not available for download.');
      return;
    }
    setDownloading(true);
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/api/documents/${documentId}/download`);
      if (!response.ok) throw new Error('Download failed');
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = (title || 'document').replace(/[^\w\s.\-]/g, '_');
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      safeError('Citation document download failed:', err);
      setDownloadError('Could not download the document.');
    } finally {
      if (mountedRef.current) setDownloading(false);
    }
  };

  const pageLabel = location && /slide/i.test(location) ? 'slide' : 'page';

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
          {isWeb ? (
            <div className="mt-1 truncate text-cyan-300" title={citationData.url}>{shortUrl(citationData.url)}</div>
          ) : (
            location && <div className="mt-1 text-[#9d9d9d]">{location}</div>
          )}
          <div className="mt-2 border-t border-[#464646] pt-2 text-[#9d9d9d]">
            {isWeb
              ? 'Click to open source'
              : couldHavePageImage
                ? `Click to view the source ${pageLabel}`
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

            <div className="flex-1 overflow-y-auto px-5 py-4 scrollbar-dark">
              {/* Hero: the actual source page snapshot, when one exists */}
              {pageImageStatus === 'loading' && (
                <div className="mb-4 h-56 w-full animate-pulse rounded-xl border border-[#464646] bg-[#1d1d1d]" />
              )}
              {pageImageStatus === 'loaded' && pageImageUrl && (
                <figure className="mb-4">
                  <div className="overflow-hidden rounded-xl border border-[#464646] bg-black/40">
                    <img
                      src={pageImageUrl}
                      alt={`Source ${pageLabel}${pageNumber != null ? ` ${pageNumber}` : ''}`}
                      className="mx-auto block max-h-[58vh] w-auto"
                    />
                  </div>
                  <figcaption className="mt-1.5 text-center text-[11px] text-[#6b6b6b]">
                    {`The exact ${pageLabel} this answer was drawn from`}
                  </figcaption>
                </figure>
              )}

              {/* Referenced passage */}
              <div className="rounded-xl border border-[#464646] bg-[#1a1a1a] p-4">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#9d9d9d]">
                  Referenced text
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#dadada]">
                  {chunkText || 'No source text is available for this citation.'}
                </p>
              </div>

              {/* Document info + chunk metadata (secondary) */}
              {(documentId || (metadata && Object.keys(metadata).length > 0)) && (
                <details className="mt-4 rounded-xl border border-[#464646] bg-[#1a1a1a] p-4">
                  <summary className="cursor-pointer select-none text-sm font-semibold text-white">Source details</summary>
                  <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                    {merged.document_file_type && (
                      <div className="min-w-0 rounded-lg bg-white/[0.03] px-3 py-2">
                        <div className="text-xs text-[#9d9d9d]">File type</div>
                        <div className="mt-0.5 break-words text-[#dadada]">{merged.document_file_type}</div>
                      </div>
                    )}
                    {(merged.file_size_bytes || merged.file_size_bytes === 0) && (
                      <div className="min-w-0 rounded-lg bg-white/[0.03] px-3 py-2">
                        <div className="text-xs text-[#9d9d9d]">File size</div>
                        <div className="mt-0.5 break-words text-[#dadada]">{formatSize(merged.file_size_bytes)}</div>
                      </div>
                    )}
                    {metadata && Object.entries(metadata).map(([key, value]) => (
                      <div key={key} className="min-w-0 rounded-lg bg-white/[0.03] px-3 py-2">
                        <div className="text-xs text-[#9d9d9d]">{formatMetadataKey(key)}</div>
                        <div className="mt-0.5 break-words text-[#dadada]">{value == null ? 'N/A' : String(value)}</div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>

            {/* Footer: downloads */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#464646] bg-[#161616] px-5 py-3">
              <span className="text-xs text-[#f1a3b0]">{downloadError || ''}</span>
              <div className="flex flex-wrap items-center gap-2">
                {pageImageStatus === 'loaded' && pageImageUrl && (
                  <a
                    href={pageImageUrl}
                    download={`${(title || 'source').replace(/[^\w\s.\-]/g, '_')}-${pageLabel}-${pageNumber ?? ''}.png`}
                    className="flex items-center gap-1.5 rounded-[10px] border border-[#464646] bg-[#262626] px-3 py-1.5 text-xs text-[#e5e5e5] transition hover:border-[#d93854]/50 hover:text-white"
                  >
                    <svg className="h-4 w-4 text-[#d93854]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                    {`Download ${pageLabel}`}
                  </a>
                )}
                <button
                  type="button"
                  onClick={handleDownloadDocument}
                  disabled={downloading}
                  className="flex items-center gap-1.5 rounded-[10px] border border-emerald-400/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 transition hover:border-emerald-300/70 hover:bg-emerald-500/25 disabled:cursor-wait disabled:opacity-70"
                >
                  {downloading ? (
                    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                  )}
                  {downloading ? 'Downloading…' : 'Download document'}
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
