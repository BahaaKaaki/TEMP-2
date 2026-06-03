/**
 * Reusable AD group / email sharing targets (used for external tool submit & admin approve).
 */
import { useEffect, useState } from 'react';
import { searchAdGroups, searchUsers } from '../../api/sharing';

const THEMES = {
  dark: {
    border: '#464646',
    surface: '#1a1a1a',
    text: '#ffffff',
    textSecondary: '#b5b5b5',
    textMuted: '#6b6b6b',
    chipBg: '#222',
  },
  light: {
    border: '#d1d5db',
    surface: '#ffffff',
    text: '#111827',
    textSecondary: '#374151',
    textMuted: '#6b7280',
    chipBg: '#f3f4f6',
  },
};

export default function SharingTargetsFields({
  isPublic,
  onIsPublicChange,
  selectedGroups,
  onSelectedGroupsChange,
  selectedEmails,
  onSelectedEmailsChange,
  variant = 'dark',
}) {
  const C = THEMES[variant] || THEMES.dark;
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
    backgroundColor: C.chipBg,
    color: C.textSecondary,
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

  const [groupQuery, setGroupQuery] = useState('');
  const [groupResults, setGroupResults] = useState([]);
  const [emailQuery, setEmailQuery] = useState('');
  const [emailResults, setEmailResults] = useState([]);

  useEffect(() => {
    if (!groupQuery.trim() || groupQuery.length < 2) {
      setGroupResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const results = await searchAdGroups(groupQuery);
        setGroupResults(results.groups || results || []);
      } catch {
        setGroupResults([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [groupQuery]);

  useEffect(() => {
    if (!emailQuery.trim() || emailQuery.length < 2) {
      setEmailResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const results = await searchUsers(emailQuery);
        setEmailResults(results.users || results || []);
      } catch {
        setEmailResults([]);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [emailQuery]);

  const addGroup = (group) => {
    if (!selectedGroups.find((g) => g.id === group.id)) {
      onSelectedGroupsChange([...selectedGroups, group]);
    }
    setGroupQuery('');
    setGroupResults([]);
  };

  const addEmail = (user) => {
    if (!selectedEmails.find((u) => u.id === user.id)) {
      onSelectedEmailsChange([...selectedEmails, user]);
    }
    setEmailQuery('');
    setEmailResults([]);
  };

  return (
    <>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={isPublic}
          onChange={(e) => onIsPublicChange(e.target.checked)}
          style={{ width: 16, height: 16 }}
        />
        <span style={{ color: C.textSecondary, fontSize: 13 }}>
          Share with everyone on the Storefront (public)
        </span>
      </label>

      {!isPublic && (
        <>
          <div style={{ marginBottom: 16 }}>
            <span style={{ color: C.textSecondary, fontSize: 13, display: 'block', marginBottom: 4 }}>
              AD groups
            </span>
            <div style={{ position: 'relative' }}>
              <input
                type="text"
                value={groupQuery}
                onChange={(e) => setGroupQuery(e.target.value)}
                placeholder="Search AD groups..."
                style={inputStyle}
              />
              {groupResults.length > 0 && (
                <div style={dropdownStyle}>
                  {groupResults.slice(0, 8).map((g) => (
                    <div key={g.id} onClick={() => addGroup(g)} style={dropdownItemStyle}>
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
                      onClick={() =>
                        onSelectedGroupsChange(selectedGroups.filter((x) => x.id !== g.id))
                      }
                      style={chipRemoveStyle}
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div style={{ marginBottom: 8 }}>
            <span style={{ color: C.textSecondary, fontSize: 13, display: 'block', marginBottom: 4 }}>
              Users (by email)
            </span>
            <div style={{ position: 'relative' }}>
              <input
                type="text"
                value={emailQuery}
                onChange={(e) => setEmailQuery(e.target.value)}
                placeholder="Search by email..."
                style={inputStyle}
              />
              {emailResults.length > 0 && (
                <div style={dropdownStyle}>
                  {emailResults.slice(0, 8).map((u) => (
                    <div key={u.id} onClick={() => addEmail(u)} style={dropdownItemStyle}>
                      {u.email}
                      {u.firstName ? ` (${u.firstName} ${u.lastName || ''})` : ''}
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
                      onClick={() =>
                        onSelectedEmailsChange(selectedEmails.filter((x) => x.id !== u.id))
                      }
                      style={chipRemoveStyle}
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
