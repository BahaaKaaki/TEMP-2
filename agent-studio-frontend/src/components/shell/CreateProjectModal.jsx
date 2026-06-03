import { useState } from 'react';
import Modal from '../ui/Modal';
import Button from '../ui/Button';

export default function CreateProjectModal({ isOpen, onClose, onCreated }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onCreated({ name: name.trim(), description: description.trim() || undefined });
      setName('');
      setDescription('');
      onClose();
    } catch (e) {
      setError(e.message || 'Failed to create project');
    } finally {
      setBusy(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="New Project"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!name.trim() || busy}>
            {busy ? 'Creating…' : 'Create'}
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <label
            style={{ display: 'block', marginBottom: 6, fontSize: 14, color: '#b5b5b5' }}
          >
            Name
          </label>
          <input
            autoFocus
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={handleKeyDown}
            maxLength={255}
            placeholder="e.g. Q2 Market Research"
            style={{
              width: '100%',
              padding: '10px 14px',
              borderRadius: 8,
              border: '1px solid #464646',
              backgroundColor: '#1a1a1a',
              color: '#ffffff',
              fontSize: 14,
              outline: 'none',
            }}
          />
        </div>
        <div>
          <label
            style={{ display: 'block', marginBottom: 6, fontSize: 14, color: '#b5b5b5' }}
          >
            Description <span style={{ color: '#6b6b6b' }}>(optional)</span>
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={512}
            rows={3}
            placeholder="What is this project about?"
            style={{
              width: '100%',
              padding: '10px 14px',
              borderRadius: 8,
              border: '1px solid #464646',
              backgroundColor: '#1a1a1a',
              color: '#ffffff',
              fontSize: 14,
              outline: 'none',
              resize: 'vertical',
            }}
          />
        </div>
        {error && (
          <div style={{ color: '#d93854', fontSize: 13 }}>{error}</div>
        )}
      </div>
    </Modal>
  );
}
