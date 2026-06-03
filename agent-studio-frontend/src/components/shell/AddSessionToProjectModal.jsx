import { useState, useMemo } from 'react';
import Modal from '../ui/Modal';
import Button from '../ui/Button';

/**
 * Modal for adding unassigned sessions to a project.
 *
 * Props:
 *   isOpen          – visibility flag
 *   onClose         – close handler
 *   sessions        – full flat list of { session, workflow } items
 *   projectId       – the target project to add sessions to
 *   projectName     – display name shown in title
 *   onConfirm(ids)  – called with array of session IDs to assign
 */
export default function AddSessionToProjectModal({
  isOpen,
  onClose,
  sessions = [],
  projectId,
  projectName,
  onConfirm,
}) {
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState('');

  const unassigned = useMemo(() => {
    let list = sessions.filter(
      ({ session }) => !session.projectId || session.projectId === projectId,
    );
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        ({ session, workflow }) =>
          (session.name || '').toLowerCase().includes(q) ||
          (workflow?.name || '').toLowerCase().includes(q) ||
          (workflow?.marketplaceName || '').toLowerCase().includes(q),
      );
    }
    return list;
  }, [sessions, projectId, search]);

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleConfirm = async () => {
    if (selected.size === 0 || busy) return;
    setBusy(true);
    try {
      await onConfirm([...selected]);
      setSelected(new Set());
      setSearch('');
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const handleClose = () => {
    setSelected(new Set());
    setSearch('');
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={`Add session to ${projectName || 'project'}`}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={selected.size === 0 || busy}>
            {busy ? 'Adding…' : `Add ${selected.size || ''} session${selected.size !== 1 ? 's' : ''}`}
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search sessions…"
          style={{
            width: '100%',
            padding: '8px 12px',
            borderRadius: 8,
            border: '1px solid #464646',
            backgroundColor: '#1a1a1a',
            color: '#ffffff',
            fontSize: 14,
            outline: 'none',
          }}
        />

        <div
          style={{
            maxHeight: 320,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          {unassigned.length === 0 && (
            <div style={{ padding: 16, color: '#6b6b6b', textAlign: 'center', fontSize: 14 }}>
              No sessions available to add.
            </div>
          )}
          {unassigned.map(({ session, workflow }) => {
            const isAlready = session.projectId === projectId;
            const checked = selected.has(session.id);
            return (
              <button
                key={session.id}
                type="button"
                onClick={() => !isAlready && toggle(session.id)}
                disabled={isAlready}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 12px',
                  borderRadius: 8,
                  border: 'none',
                  backgroundColor: checked ? 'rgba(217,56,84,0.15)' : 'transparent',
                  color: isAlready ? '#6b6b6b' : '#ffffff',
                  cursor: isAlready ? 'default' : 'pointer',
                  textAlign: 'left',
                  width: '100%',
                  fontSize: 14,
                }}
              >
                <span
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: 4,
                    border: `2px solid ${checked ? '#d93854' : '#464646'}`,
                    backgroundColor: checked ? '#d93854' : 'transparent',
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {checked && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  )}
                </span>
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {session.name || 'Untitled'}
                </span>
                <span style={{ color: '#6b6b6b', fontSize: 12, flexShrink: 0 }}>
                  {workflow?.marketplaceName || workflow?.name || ''}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
