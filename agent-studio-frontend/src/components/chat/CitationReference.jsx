import { useState, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import AlertModal from '../ui/AlertModal';
import { authenticatedFetch, API_BASE_URL } from '@/api/client';
import { safeError } from '../../utils/safeLogger';

/**
 * Citation reference component with hover tooltip and click action.
 *
 * Supports two citation types:
 *   - "web"  (Deep Research): shows title + URL on hover, opens URL on click
 *   - KB     (Knowledge Base): fetches chunk details from API, shows modal on click
 *
 * Shows [N] as clickable badge for both types.
 */
export default function CitationReference({ citationNumber, citationData }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [tooltipPos, setTooltipPos] = useState({ top: 0, left: 0, flipped: false });
  const [showModal, setShowModal] = useState(false);
  const [fullCitation, setFullCitation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showNoDocIdAlert, setShowNoDocIdAlert] = useState(false);
  const [showDownloadError, setShowDownloadError] = useState(false);
  const badgeRef = useRef(null);

  const computeTooltipPosition = useCallback(() => {
    if (!badgeRef.current) return;
    const rect = badgeRef.current.getBoundingClientRect();
    const tooltipWidth = 320;
    const tooltipEstimatedHeight = 160;
    const gap = 8;

    const spaceAbove = rect.top;
    const flipped = spaceAbove < tooltipEstimatedHeight + gap;

    let top;
    if (flipped) {
      top = rect.bottom + gap;
    } else {
      top = rect.top - gap;
    }

    let left = rect.left + rect.width / 2 - tooltipWidth / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tooltipWidth - 8));

    setTooltipPos({ top, left, flipped });
  }, []);

  if (!citationData) {
    return <span className="citation-error">[{citationNumber}]</span>;
  }

  const isWeb = citationData.type === 'web';

  // ── KB-only: fetch full citation details on demand ──
  const fetchFullCitation = async () => {
    if (isWeb || fullCitation || loading) return;

    const chunkId = citationData.chunk_id;
    const kbId = citationData.kb_id;

    if (!chunkId) {
      setError('Invalid citation data');
      return;
    }

    setLoading(true);
    try {
      const url = `${API_BASE_URL}/api/citations/${chunkId}${kbId ? `?kb_id=${kbId}` : ''}`;
      const response = await authenticatedFetch(url);

      if (!response.ok) {
        throw new Error(`Failed to fetch citation: ${response.statusText}`);
      }

      const data = await response.json();
      setFullCitation(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleMouseEnter = (e) => {
    computeTooltipPosition();
    setShowTooltip(true);
    if (!isWeb) fetchFullCitation();
    e.currentTarget.style.backgroundColor = isWeb ? '#dcfce7' : '#bae6fd';
    e.currentTarget.style.transform = 'scale(1.1)';
  };

  const handleMouseLeave = (e) => {
    setShowTooltip(false);
    e.currentTarget.style.backgroundColor = isWeb ? '#f0fdf4' : '#e0f2fe';
    e.currentTarget.style.transform = 'scale(1)';
  };

  const handleClick = (e) => {
    e.stopPropagation();
    if (isWeb) {
      window.open(citationData.url, '_blank', 'noopener,noreferrer');
    } else {
      fetchFullCitation();
      setShowModal(true);
    }
  };

  const displayData = fullCitation || citationData;

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDate = (dateString) => {
    try {
      const date = new Date(dateString);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);

      if (diffMins < 1) return 'just now';
      if (diffMins < 60) return `${diffMins} min${diffMins > 1 ? 's' : ''} ago`;
      if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
      if (diffDays < 30) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
      return date.toLocaleDateString();
    } catch {
      return 'recently';
    }
  };

  const handleDownload = async () => {
    const documentId = displayData.document_id;
    const documentName = displayData.document_name;

    if (!documentId) {
      setShowNoDocIdAlert(true);
      return;
    }

    try {
      const response = await authenticatedFetch(
        `${API_BASE_URL}/api/documents/${documentId}/download`
      );

      if (!response.ok) throw new Error('Download failed');

      const blob = await response.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const safeName = (documentName || 'document').replace(/[^\w\s.\-]/g, '_');
      a.download = safeName;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(blobUrl);
      document.body.removeChild(a);
    } catch (err) {
      safeError('Failed to download document:', err);
      setShowDownloadError(true);
    }
  };

  // Truncate long URLs for display
  const shortUrl = (url) => {
    try {
      const u = new URL(url);
      const path = u.pathname.length > 30
        ? u.pathname.substring(0, 30) + '...'
        : u.pathname;
      return u.hostname + path;
    } catch {
      return url?.substring(0, 50) || '';
    }
  };

  // ── Badge style varies by type ──
  const badgeStyle = {
    position: 'relative',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '20px',
    height: '20px',
    marginLeft: '2px',
    marginRight: '2px',
    fontSize: '11px',
    fontWeight: '600',
    color: isWeb ? '#16a34a' : '#0ea5e9',
    backgroundColor: isWeb ? '#f0fdf4' : '#e0f2fe',
    border: isWeb ? '1px solid #4ade80' : '1px solid #38bdf8',
    borderRadius: '4px',
    cursor: 'pointer',
    transition: 'all 0.2s',
    userSelect: 'none',
  };

  return (
    <>
      {/* Citation Badge */}
      <span
        ref={badgeRef}
        className="citation-badge"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        style={badgeStyle}
      >
        {citationNumber}
      </span>

      {/* Hover Tooltip -- portaled to body to escape overflow:hidden ancestors */}
      {showTooltip && createPortal(
        <div
          className="citation-tooltip"
          style={{
            position: 'fixed',
            top: tooltipPos.flipped ? tooltipPos.top : undefined,
            bottom: tooltipPos.flipped ? undefined : `${window.innerHeight - tooltipPos.top}px`,
            left: tooltipPos.left,
            width: '320px',
            maxWidth: '90vw',
            padding: '12px',
            backgroundColor: 'white',
            border: '1px solid #e5e7eb',
            borderRadius: '8px',
            boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
            zIndex: 10000,
            pointerEvents: 'none',
          }}
        >
          {/* Arrow */}
          <div
            style={{
              position: 'absolute',
              ...(tooltipPos.flipped
                ? {
                    bottom: '100%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: 0, height: 0,
                    borderLeft: '6px solid transparent',
                    borderRight: '6px solid transparent',
                    borderBottom: '6px solid white',
                  }
                : {
                    top: '100%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: 0, height: 0,
                    borderLeft: '6px solid transparent',
                    borderRight: '6px solid transparent',
                    borderTop: '6px solid white',
                  }),
            }}
          />

          {/* Tooltip Content */}
          <div className="text-sm">
            {isWeb ? (
              <>
                <div className="font-semibold text-gray-900 mb-1 truncate" title={citationData.title}>
                  {citationData.title || 'Untitled source'}
                </div>
                <div className="text-xs text-green-700 truncate mb-2" title={citationData.url}>
                  {shortUrl(citationData.url)}
                </div>
                <div className="mt-2 pt-2 border-t border-gray-200 text-xs text-gray-500">
                  Click to open source
                </div>
              </>
            ) : loading ? (
              <div className="text-center py-4">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto"></div>
                <p className="text-xs text-gray-500 mt-2">Loading...</p>
              </div>
            ) : error ? (
              <div className="text-red-600 text-xs">{error}</div>
            ) : (
              <>
                <div className="font-semibold text-gray-900 mb-2 truncate" title={displayData.document_name || 'Loading...'}>
                  {displayData.document_name || 'Document'}
                </div>

                <div className="text-xs text-gray-600 mb-2">
                  {displayData.chunk_index !== undefined ? `Chunk ${displayData.chunk_index + 1}` : 'Loading...'}
                  {displayData.relevance_score && ` \u2022 Relevance: ${(displayData.relevance_score * 100).toFixed(0)}%`}
                </div>

                <div className="text-gray-700 text-xs leading-relaxed max-h-32 overflow-hidden">
                  {displayData.chunk_text?.substring(0, 200) || 'Loading content...'}
                  {displayData.chunk_text?.length > 200 && '...'}
                </div>

                <div className="mt-2 pt-2 border-t border-gray-200 text-xs text-gray-500">
                  Click for full details
                </div>
              </>
            )}
          </div>
        </div>,
        document.body
      )}

      {/* Full Details Modal (KB citations only) */}
      {!isWeb && showModal && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setShowModal(false)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl max-w-3xl w-full max-h-[80vh] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-semibold text-gray-900 truncate" title={displayData.document_name || 'Loading...'}>
                  {displayData.document_name || 'Loading...'}
                </h3>
                <p className="text-sm text-gray-500">
                  Citation [{citationNumber}] {displayData.chunk_index !== undefined && `\u2022 Chunk ${displayData.chunk_index + 1}`}
                </p>
              </div>

              <button
                onClick={() => setShowModal(false)}
                className="ml-4 p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal Body */}
            <div className="px-6 py-4 overflow-y-auto max-h-[calc(80vh-200px)]">
              {loading && !fullCitation ? (
                <div className="text-center py-8">
                  <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-400 mx-auto"></div>
                  <p className="text-gray-500 mt-4">Loading citation details...</p>
                </div>
              ) : error ? (
                <div className="text-red-600 text-center py-8">
                  <p className="font-semibold">Failed to load citation</p>
                  <p className="text-sm mt-2">{error}</p>
                </div>
              ) : (
                <>
                  {/* Relevance Score */}
                  {displayData.relevance_score && (
                    <div className="mb-4 flex items-center gap-4">
                      <div className="flex-1">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium text-gray-700">Relevance Score</span>
                          <span className="text-sm font-bold text-gray-700">
                            {(displayData.relevance_score * 100).toFixed(1)}%
                          </span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-2">
                          <div
                            className="bg-gray-500 h-2 rounded-full transition-all"
                            style={{ width: `${displayData.relevance_score * 100}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Chunk Text */}
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Chunk Content
                    </label>
                    <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                      <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                        {displayData.chunk_text || 'No content available'}
                      </p>
                    </div>
                    {displayData.chunk_size && (
                      <p className="text-xs text-gray-500 mt-1">
                        {displayData.chunk_size} characters
                      </p>
                    )}
                  </div>
                </>
              )}

              {/* Chunk Metadata (inferred fields) */}
              {(() => {
                const chunkMeta = displayData.chunk_metadata || citationData.chunk_metadata;
                if (!chunkMeta || typeof chunkMeta !== 'object' || Object.keys(chunkMeta).length === 0) return null;
                return (
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Chunk Metadata
                    </label>
                    <div className="grid grid-cols-2 gap-3 p-4 bg-blue-50 rounded-lg border border-blue-200 text-sm">
                      {Object.entries(chunkMeta).map(([key, value]) => (
                        <div key={key} className={key === 'file_name' ? 'col-span-2' : ''}>
                          <span className="text-blue-600 font-medium">{key}:</span>
                          <span className="ml-2 text-gray-900">
                            {value === null || value === undefined ? 'N/A' : String(value)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* Document Metadata (collapsed) */}
              {fullCitation && (
                <details className="mb-4">
                  <summary className="cursor-pointer text-sm font-medium text-gray-500 hover:text-gray-700 py-2">
                    Document Info
                  </summary>

                  <div className="mt-3 space-y-3 pl-4">
                    <div className="grid grid-cols-2 gap-4 text-sm text-gray-500">
                      <div>
                        <span>File Type:</span>
                        <span className="ml-2 text-gray-700">
                          {displayData.document_file_type || 'N/A'}
                        </span>
                      </div>

                      <div>
                        <span>File Size:</span>
                        <span className="ml-2 text-gray-700">
                          {displayData.file_size_bytes ? formatSize(displayData.file_size_bytes) : 'N/A'}
                        </span>
                      </div>

                      <div>
                        <span>Uploaded:</span>
                        <span className="ml-2 text-gray-700">
                          {displayData.uploaded_at ? formatDate(displayData.uploaded_at) : 'N/A'}
                        </span>
                      </div>

                      <div className="col-span-2">
                        <span>Chunk ID:</span>
                        <span className="ml-2 font-mono text-xs text-gray-600">
                          {displayData.chunk_id || citationData.chunk_id}
                        </span>
                      </div>
                    </div>
                  </div>
                </details>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between bg-gray-50">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 text-sm text-gray-700 hover:bg-gray-200 rounded-lg transition-colors"
              >
                Close
              </button>

              <button
                onClick={handleDownload}
                className="px-4 py-2 text-sm font-medium text-white bg-gray-700 hover:bg-gray-800 rounded-lg transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Download Document
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error Modals (KB only) */}
      <AlertModal
        isOpen={showNoDocIdAlert}
        title="Document Not Available"
        message="Document ID not available for this citation."
        variant="warning"
        onClose={() => setShowNoDocIdAlert(false)}
      />

      <AlertModal
        isOpen={showDownloadError}
        title="Download Failed"
        message="Failed to download document. Please try again."
        variant="error"
        onClose={() => setShowDownloadError(false)}
      />
    </>
  );
}
