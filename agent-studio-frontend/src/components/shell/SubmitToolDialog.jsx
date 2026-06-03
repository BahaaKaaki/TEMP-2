/**
 * SubmitToolDialog — modal form for users to submit an external tool
 * for admin approval. Appears in the Storefront when "Submit a Tool" is clicked.
 */
import { useState, useRef, useEffect } from 'react';
import { submitToolForApproval } from '../../api/shared-tools';
import { searchAdGroups, searchUsers } from '../../api/sharing';

const C = {
  bg: '#0d0d0d',
  surface: '#1a1a1a',
  surfaceHover: '#222222',
  border: '#464646',
  text: '#ffffff',
  textSecondary: '#b5b5b5',
  textMuted: '#6b6b6b',
  rose: '#d93854',
  roseHover: '#c52a45',
  success: '#1AAB40',
  errorText: '#ef4444',
  errorBg: 'rgba(239,68,68,0.1)',
};

export default function SubmitToolDialog({ onClose }) {
  const [toolName, setToolName] = useState('');
  const [description, setDescription] = useState('');
  const [url, setUrl] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [groupQuery, setGroupQuery] = useState('');
  const [groupResults, setGroupResults] = useState([]);
  const [selectedGroups, setSelectedGroups] = useState([]);
  const [emailQuery, setEmailQuery] = useState('');
  const [emailResults, setEmailResults] = useState([]);
  const [selectedEmails, setSelectedEmails] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const backdropRef = useRef(null);

  // AD group search
  useEffect(() => {
    if (!groupQuery.trim() || groupQuery.length < 2) {
      setGroupResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const results = await searchAdGroups(groupQuery);
        setGroupResults(results.groups || results || []);
      } catch { setGroupResults([]); }
    }, 300);
    return () => clearTimeout(timer);
  }, [groupQuery]);

  // User search by email
  useEffect(() => {
    if (!emailQuery.trim() || emailQuery.length < 2) {
      setEmailResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const results = await searchUsers(emailQuery);
        setEmailResults(results.users || results || []);
      } catch { setEmailResults([]); }
    }, 300);
    return () => clearTimeout(timer);
  }, [emailQuery]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!toolName.trim() || !url.trim()) {
      setError('Tool name and URL are required.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await submitToolForApproval({
        tool_name: toolName.trim(),
        description: description.trim() || null,
        url: url.trim(),
        is_public: isPublic,
        ad_group_names: selectedGroups.map((g) => g.displayName || g.name),
        emails: selectedEmails.map((u) => u.email),
      });
      setSuccess(true);
    } catch (err) {
      setError(err.message || 'Failed to submit');
    } finally {
      setSubmitting(false);
    }
  };

  const addGroup = (group) => {
    if (!selectedGroups.find((g) => g.id === group.id)) {
      setSelectedGroups([...selectedGroups, group]);
    }
    setGroupQuery('');
    setGroupResults([]);
  };

  const addEmail = (user) => {
    if (!selectedEmails.find((u) => u.id === user.id)) {
      setSelectedEmails([...selectedEmails, user]);
    }
    setEmailQuery('');
    setEmailResults([]);
  };

  return (
    <div
      ref={backdropRef}
      onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.55)',
        WebkitBackdropFilter: 'blur(12px)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <div
        className="submit-tool-dialog"
        data-theme="apex-dark"
        style={{
          width: 520,
          maxHeight: '85vh',
          overflow: 'auto',
          backgroundColor: C.bg,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          padding: 28,
          color: C.text,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ color: C.text, margin: 0, fontSize: 18, fontWeight: 600 }}>
            Submit a Tool
          </h2>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: C.textMuted, fontSize: 22, cursor: 'pointer' }}
          >
            &times;
          </button>
        </div>

        {success ? (
          <div style={{ color: C.success, padding: '20px 0', textAlign: 'center' }}>
            <p style={{ fontSize: 16, marginBottom: 8 }}>Tool submitted for admin approval.</p>
            <button
              onClick={onClose}
              style={{
                marginTop: 12,
                padding: '8px 20px',
                borderRadius: 6,
                border: 'none',
                backgroundColor: C.rose,
                color: C.text,
                cursor: 'pointer',
                fontWeight: 500,
              }}
            >
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            {/* Tool Name */}
            <label style={{ display: 'block', marginBottom: 16 }}>
              <span style={labelStyle}>
                Tool Name *
              </span>
              <input
                type="text"
                className="force-white-text"
                value={toolName}
                onChange={(e) => setToolName(e.target.value)}
                placeholder="e.g. FDI Analyzer"
                style={inputStyle}
              />
            </label>

            {/* Description */}
            <label style={{ display: 'block', marginBottom: 16 }}>
              <span style={labelStyle}>
                Description
              </span>
              <textarea
                className="force-white-text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of the tool"
                rows={3}
                style={{ ...inputStyle, resize: 'vertical', minHeight: 60 }}
              />
            </label>

            {/* URL */}
            <label style={{ display: 'block', marginBottom: 16 }}>
              <span style={labelStyle}>
                URL *
              </span>
              <input
                type="url"
                className="force-white-text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://..."
                style={inputStyle}
              />
            </label>

            {/* Public toggle */}
            <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={isPublic}
                onChange={(e) => setIsPublic(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: C.rose }}
              />
              <span style={{ color: C.text, fontSize: 13 }}>
                Share with everyone (public)
              </span>
            </label>

            {/* AD group sharing (hidden if public) */}
            {!isPublic && (
              <div style={{ marginBottom: 16 }}>
                <span style={labelStyle}>
                  Share with AD Groups
                </span>
                <div style={{ position: 'relative' }}>
                  <input
                    type="text"
                    className="force-white-text"
                    value={groupQuery}
                    onChange={(e) => setGroupQuery(e.target.value)}
                    placeholder="Search AD groups..."
                    style={inputStyle}
                  />
                  {groupResults.length > 0 && (
                    <div style={dropdownStyle}>
                      {groupResults.slice(0, 8).map((g) => (
                        <div
                          key={g.id}
                          onClick={() => addGroup(g)}
                          style={dropdownItemStyle}
                        >
                          {g.displayName || g.name}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {selectedGroups.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                    {selectedGroups.map((g) => (
                      <span key={g.id} style={chipStyle}>
                        {g.displayName || g.name}
                        <button
                          type="button"
                          onClick={() => setSelectedGroups(selectedGroups.filter((x) => x.id !== g.id))}
                          style={chipRemoveStyle}
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Email sharing (hidden if public) */}
            {!isPublic && (
              <div style={{ marginBottom: 16 }}>
                <span style={labelStyle}>
                  Share with specific users (email)
                </span>
                <div style={{ position: 'relative' }}>
                  <input
                    type="text"
                    className="force-white-text"
                    value={emailQuery}
                    onChange={(e) => setEmailQuery(e.target.value)}
                    placeholder="Search by email..."
                    style={inputStyle}
                  />
                  {emailResults.length > 0 && (
                    <div style={dropdownStyle}>
                      {emailResults.slice(0, 8).map((u) => (
                        <div
                          key={u.id}
                          onClick={() => addEmail(u)}
                          style={dropdownItemStyle}
                        >
                          {u.email}{u.firstName ? ` (${u.firstName} ${u.lastName || ''})` : ''}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {selectedEmails.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                    {selectedEmails.map((u) => (
                      <span key={u.id} style={chipStyle}>
                        {u.email}
                        <button
                          type="button"
                          onClick={() => setSelectedEmails(selectedEmails.filter((x) => x.id !== u.id))}
                          style={chipRemoveStyle}
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {error && (
              <div style={{ color: C.errorText, backgroundColor: C.errorBg, padding: '8px 12px', borderRadius: 6, marginBottom: 12, fontSize: 13 }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              style={{
                width: '100%',
                padding: '10px 0',
                borderRadius: 6,
                border: 'none',
                backgroundColor: C.rose,
                color: C.text,
                fontSize: 14,
                fontWeight: 600,
                cursor: submitting ? 'wait' : 'pointer',
                opacity: submitting ? 0.6 : 1,
              }}
            >
              {submitting ? 'Submitting...' : 'Submit for Approval'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

const labelStyle = {
  color: C.text,
  fontSize: 13,
  display: 'block',
  marginBottom: 4,
};

const inputStyle = {
  width: '100%',
  padding: '8px 12px',
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  backgroundColor: C.surface,
  color: C.text,
  fontSize: 14,
  outline: 'none',
  boxSizing: 'border-box',
};

const dropdownStyle = {
  position: 'absolute',
  top: '100%',
  left: 0,
  right: 0,
  zIndex: 10,
  backgroundColor: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 6,
  maxHeight: 200,
  overflow: 'auto',
  marginTop: 2,
};

const dropdownItemStyle = {
  padding: '8px 12px',
  cursor: 'pointer',
  fontSize: 13,
  color: C.text,
  borderBottom: `1px solid ${C.border}`,
};

const chipStyle = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  padding: '3px 8px',
  borderRadius: 4,
  backgroundColor: C.surfaceHover,
  color: C.text,
  fontSize: 12,
};

const chipRemoveStyle = {
  background: 'none',
  border: 'none',
  color: C.textMuted,
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
  lineHeight: 1,
};
