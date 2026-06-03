import { useState, useEffect } from 'react';
import Modal from '../ui/Modal';
import Button from '../ui/Button';
import { listProjects, createProject } from '../../api/project-client';

/**
 * Modal shown when launching a new chat session. Lets the user pick an
 * existing project, create a new one, or skip (no project).
 *
 * Props:
 *   isOpen          – visibility flag
 *   onClose         – cancel / close handler
 *   onSelect(id)    – called with projectId (string) or null (skip)
 */
export default function ProjectPickerModal({ isOpen, onClose, onSelect }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setSelected(null);
    setShowCreate(false);
    setNewName('');
    (async () => {
      setLoading(true);
      try {
        const data = await listProjects();
        setProjects(data.items || []);
      } catch {
        setProjects([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [isOpen]);

  const handleConfirm = () => {
    onSelect(selected);
  };

  const handleSkip = () => {
    onSelect(null);
  };

  const handleCreateAndSelect = async () => {
    if (!newName.trim() || busy) return;
    setBusy(true);
    try {
      const created = await createProject({ name: newName.trim() });
      setProjects((prev) => [created, ...prev]);
      setSelected(created.id);
      setShowCreate(false);
      setNewName('');
    } catch {
      // silently fail — user can retry
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Assign to a project"
      footer={
        <>
          <Button variant="ghost" onClick={handleSkip}>
            Skip
          </Button>
          <Button onClick={handleConfirm} disabled={!selected}>
            Continue
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minHeight: 120 }}>
        {loading && (
          <div style={{ color: '#6b6b6b', fontSize: 14, padding: 16, textAlign: 'center' }}>
            Loading projects…
          </div>
        )}

        {!loading && projects.length === 0 && !showCreate && (
          <div style={{ color: '#6b6b6b', fontSize: 14, padding: 16, textAlign: 'center' }}>
            No projects yet.
          </div>
        )}

        {!loading && (
          <div style={{ maxHeight: 260, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setSelected(p.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: selected === p.id ? '1px solid #d93854' : '1px solid transparent',
                  backgroundColor: selected === p.id ? 'rgba(217,56,84,0.12)' : 'transparent',
                  color: '#ffffff',
                  cursor: 'pointer',
                  textAlign: 'left',
                  width: '100%',
                  fontSize: 14,
                }}
              >
                <span
                  style={{
                    width: 16,
                    height: 16,
                    borderRadius: '50%',
                    border: `2px solid ${selected === p.id ? '#d93854' : '#464646'}`,
                    backgroundColor: selected === p.id ? '#d93854' : 'transparent',
                    flexShrink: 0,
                  }}
                />
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.name}
                </span>
                <span style={{ color: '#6b6b6b', fontSize: 12, flexShrink: 0 }}>
                  {p.sessionCount} session{p.sessionCount !== 1 ? 's' : ''}
                </span>
              </button>
            ))}
          </div>
        )}

        {!loading && showCreate && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              autoFocus
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreateAndSelect()}
              placeholder="Project name"
              maxLength={255}
              style={{
                flex: 1,
                padding: '8px 12px',
                borderRadius: 8,
                border: '1px solid #464646',
                backgroundColor: '#1a1a1a',
                color: '#ffffff',
                fontSize: 14,
                outline: 'none',
              }}
            />
            <Button size="sm" onClick={handleCreateAndSelect} disabled={!newName.trim() || busy}>
              {busy ? '…' : 'Add'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setShowCreate(false); setNewName(''); }}>
              Cancel
            </Button>
          </div>
        )}

        {!loading && !showCreate && (
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 14px',
              borderRadius: 8,
              border: '1px dashed #464646',
              backgroundColor: 'transparent',
              color: '#b5b5b5',
              cursor: 'pointer',
              fontSize: 14,
              width: '100%',
            }}
          >
            <span style={{ fontSize: 18, lineHeight: 1 }}>+</span>
            Create new project
          </button>
        )}
      </div>
    </Modal>
  );
}
