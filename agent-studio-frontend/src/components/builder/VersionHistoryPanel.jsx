import { useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { listVersions, restoreVersion, updateVersionName, checkForUpdates, pullUpdate } from '@/api/versions';
import { COLOR } from './figmaSpec';
import { useFigmaPx } from './useFigmaScale';

const EVENT_LABELS = { save: 'Saved', publish: 'Published', restore: 'Restored', import_update: 'Marketplace update' };
const EVENT_COLORS = { publish: COLOR.rose, restore: '#60a5fa', import_update: '#a78bfa', save: COLOR.medium };

export default function VersionHistoryPanel({ workflowId, workflowMeta, onRestore, onClose }) {
  const { px } = useFigmaPx();
  const [versions, setVersions] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [restoring, setRestoring] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [updateInfo, setUpdateInfo] = useState(null);
  const [pulling, setPulling] = useState(false);
  const [error, setError] = useState(null);

  const pageSize = 30;

  const isMarketplaceImport = (() => {
    if (!workflowMeta) return false;
    try {
      const m = typeof workflowMeta === 'string' ? JSON.parse(workflowMeta) : workflowMeta;
      return !!m?.sourceMarketplaceId;
    } catch { return false; }
  })();

  const fetchVersions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listVersions(workflowId, { page, pageSize });
      setVersions(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [workflowId, page]);

  useEffect(() => { fetchVersions(); }, [fetchVersions]);

  useEffect(() => {
    if (!isMarketplaceImport) return;
    checkForUpdates(workflowId).then(setUpdateInfo).catch(() => {});
  }, [workflowId, isMarketplaceImport]);

  const handleRestore = async (v) => {
    setRestoring(v.versionId);
    try {
      const updated = await restoreVersion(workflowId, v.versionId);
      onRestore?.(updated);
      await fetchVersions();
    } catch (e) {
      setError(e.message);
    } finally {
      setRestoring(null);
    }
  };

  const handleSaveLabel = async (versionId) => {
    if (!editValue.trim()) { setEditingId(null); return; }
    try {
      await updateVersionName(workflowId, versionId, editValue.trim());
      setEditingId(null);
      setEditValue('');
      await fetchVersions();
    } catch (e) {
      setError(e.message);
    }
  };

  const handlePullUpdate = async () => {
    setPulling(true);
    try {
      const updated = await pullUpdate(workflowId);
      onRestore?.(updated);
      setUpdateInfo(null);
      await fetchVersions();
    } catch (e) {
      setError(e.message);
    } finally {
      setPulling(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const formatTime = (iso) => {
    const d = new Date(iso);
    const now = new Date();
    const diff = now - d;
    if (diff < 60_000) return 'just now';
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
    if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
  };

  return createPortal(
    <div className="fixed inset-0 z-[60] flex justify-end" onClick={onClose}>
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/50" />

      {/* panel */}
      <div
        className="relative h-full flex flex-col overflow-hidden animate-in slide-in-from-right"
        style={{ width: px(380), backgroundColor: '#0d0d0d', borderLeft: '1px solid rgba(255,255,255,0.08)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between shrink-0" style={{ padding: `${px(16)}px ${px(20)}px`, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div className="flex items-center" style={{ gap: px(10) }}>
            <svg style={{ width: px(18), height: px(18), color: COLOR.rose }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span style={{ fontSize: px(16), fontWeight: 600, color: COLOR.white }}>Version History</span>
            <span style={{ fontSize: px(12), color: COLOR.medium, fontWeight: 400 }}>{total} version{total !== 1 ? 's' : ''}</span>
          </div>
          <button onClick={onClose} className="hover:bg-white/5 rounded-full transition-colors" style={{ padding: px(6) }}>
            <svg style={{ width: px(16), height: px(16), color: COLOR.medium }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* marketplace update banner */}
        {updateInfo?.hasUpdate && (
          <div style={{ padding: `${px(12)}px ${px(20)}px`, backgroundColor: 'rgba(167,139,250,0.08)', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            <div className="flex items-center justify-between">
              <div className="flex items-center" style={{ gap: px(8) }}>
                <svg style={{ width: px(16), height: px(16), color: '#a78bfa' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                <span style={{ fontSize: px(13), color: '#a78bfa', fontWeight: 500 }}>Update available</span>
              </div>
              <button
                onClick={handlePullUpdate}
                disabled={pulling}
                className="hover:bg-white/10 transition-colors disabled:opacity-50"
                style={{ fontSize: px(12), color: COLOR.white, fontWeight: 600, padding: `${px(4)}px ${px(12)}px`, borderRadius: px(6), backgroundColor: 'rgba(167,139,250,0.15)' }}
              >
                {pulling ? 'Updating...' : 'Pull update'}
              </button>
            </div>
          </div>
        )}

        {/* error */}
        {error && (
          <div style={{ padding: `${px(8)}px ${px(20)}px`, fontSize: px(12), color: COLOR.rose, backgroundColor: 'rgba(225,49,80,0.06)' }}>
            {error}
          </div>
        )}

        {/* version list */}
        <div className="flex-1 overflow-y-auto" style={{ padding: `${px(8)}px 0` }}>
          {loading ? (
            <div className="flex items-center justify-center" style={{ padding: px(40), color: COLOR.medium, fontSize: px(13) }}>
              Loading...
            </div>
          ) : versions.length === 0 ? (
            <div className="flex items-center justify-center" style={{ padding: px(40), color: COLOR.medium, fontSize: px(13) }}>
              No versions yet. Versions are created when you save.
            </div>
          ) : (
            versions.map((v, idx) => {
              const isCurrent = page === 1 && idx === 0;
              return (
              <div
                key={v.versionId}
                className="group hover:bg-white/[0.03] transition-colors"
                style={{
                  padding: `${px(12)}px ${px(20)}px`,
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                  ...(isCurrent ? { backgroundColor: 'rgba(225,49,80,0.08)', borderLeft: `3px solid ${COLOR.rose}` } : {}),
                }}
              >
                {/* top row: event badge + version number + time */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center" style={{ gap: px(8) }}>
                    <span
                      style={{
                        fontSize: px(11),
                        fontWeight: 600,
                        color: EVENT_COLORS[v.event] || COLOR.medium,
                        backgroundColor: `${EVENT_COLORS[v.event] || COLOR.medium}15`,
                        padding: `${px(2)}px ${px(8)}px`,
                        borderRadius: px(4),
                        textTransform: 'uppercase',
                        letterSpacing: '0.03em',
                      }}
                    >
                      {EVENT_LABELS[v.event] || v.event}
                    </span>
                    <span style={{ fontSize: px(13), color: COLOR.white, fontWeight: 500 }}>v{v.versionNumber}</span>
                    {isCurrent && (
                      <span style={{ fontSize: px(10), fontWeight: 700, color: COLOR.white, backgroundColor: COLOR.rose, padding: `${px(1)}px ${px(6)}px`, borderRadius: px(3), textTransform: 'uppercase' }}>
                        Current
                      </span>
                    )}
                    {v.isPublishedSnapshot && !isCurrent && (
                      <span style={{ fontSize: px(10), fontWeight: 700, color: COLOR.rose, backgroundColor: `${COLOR.rose}18`, padding: `${px(1)}px ${px(6)}px`, borderRadius: px(3), textTransform: 'uppercase' }}>
                        Live
                      </span>
                    )}
                  </div>
                  <span style={{ fontSize: px(11), color: COLOR.medium }}>{formatTime(v.createdAt)}</span>
                </div>

                {/* description / label */}
                <div style={{ marginTop: px(4) }}>
                  {editingId === v.versionId ? (
                    <div className="flex items-center" style={{ gap: px(6) }}>
                      <input
                        autoFocus
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleSaveLabel(v.versionId); if (e.key === 'Escape') setEditingId(null); }}
                        placeholder="Label this version..."
                        className="flex-1 bg-white/5 border border-white/10 rounded outline-none focus:border-white/20"
                        style={{ fontSize: px(12), color: COLOR.white, padding: `${px(3)}px ${px(8)}px` }}
                      />
                      <button onClick={() => handleSaveLabel(v.versionId)} style={{ fontSize: px(11), color: COLOR.rose, fontWeight: 600 }}>Save</button>
                      <button onClick={() => setEditingId(null)} style={{ fontSize: px(11), color: COLOR.medium }}>Cancel</button>
                    </div>
                  ) : (
                    <div className="flex items-center" style={{ gap: px(6) }}>
                      {v.description ? (
                        <span style={{ fontSize: px(12), color: 'rgba(255,255,255,0.55)' }}>{v.description}</span>
                      ) : (
                        <span style={{ fontSize: px(12), color: 'rgba(255,255,255,0.25)' }}>by {v.authors}</span>
                      )}
                      <button
                        onClick={() => { setEditingId(v.versionId); setEditValue(v.description || ''); }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity hover:text-white"
                        style={{ fontSize: px(11), color: COLOR.medium }}
                      >
                        {v.description ? 'edit' : 'label'}
                      </button>
                    </div>
                  )}
                </div>

                {/* actions */}
                {!isCurrent && !v.isPublishedSnapshot && (
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity" style={{ marginTop: px(8) }}>
                    <button
                      onClick={() => handleRestore(v)}
                      disabled={restoring === v.versionId}
                      className="hover:bg-white/10 transition-colors disabled:opacity-50"
                      style={{ fontSize: px(12), color: COLOR.white, fontWeight: 500, padding: `${px(3)}px ${px(10)}px`, borderRadius: px(4), backgroundColor: 'rgba(255,255,255,0.06)' }}
                    >
                      {restoring === v.versionId ? 'Restoring...' : 'Restore this version'}
                    </button>
                  </div>
                )}
              </div>
              );
            })
          )}
        </div>

        {/* pagination */}
        {totalPages > 1 && (
          <div
            className="flex items-center justify-between shrink-0"
            style={{ padding: `${px(10)}px ${px(20)}px`, borderTop: '1px solid rgba(255,255,255,0.08)' }}
          >
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="disabled:opacity-30 hover:bg-white/5 transition-colors rounded"
              style={{ fontSize: px(12), color: COLOR.medium, padding: `${px(4)}px ${px(10)}px` }}
            >
              Newer
            </button>
            <span style={{ fontSize: px(11), color: COLOR.medium }}>
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="disabled:opacity-30 hover:bg-white/5 transition-colors rounded"
              style={{ fontSize: px(12), color: COLOR.medium, padding: `${px(4)}px ${px(10)}px` }}
            >
              Older
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
