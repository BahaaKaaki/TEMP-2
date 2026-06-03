/**
 * ShareDialog — dark-themed share modal with three tabs:
 *   1. Marketplace  – submit for marketplace approval.
 *   2. Group        – grant a Microsoft Entra ID security group access.
 *   3. Person       – grant a specific (already-registered) user access.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  shareWorkflow,
  listWorkflowShares,
  revokeWorkflowShare,
  shareKnowledgeBase,
  listKnowledgeBaseShares,
  revokeKnowledgeBaseShare,
  searchAdGroups,
  searchUsers,
} from '@/api/sharing';
import { submitWorkflowForApproval } from '@/api/approval';
import { unshareWorkflowFromMarketplace } from '@/api/marketplace';

const C = {
  bg: '#0d0d0d',
  surface: '#1a1a1a',
  surfaceHover: '#222222',
  border: '#464646',
  borderLight: '#333333',
  text: '#ffffff',
  textSecondary: '#b5b5b5',
  textMuted: '#6b6b6b',
  rose: '#d93854',
  roseHover: '#c52a45',
  success: '#1AAB40',
  successBg: 'rgba(26,171,64,0.12)',
  errorText: '#ef4444',
  errorBg: 'rgba(239,68,68,0.1)',
  warningText: '#eab308',
  warningBg: 'rgba(234,179,8,0.1)',
};

const TABS = [
  { id: 'marketplace', label: 'Marketplace', icon: '🛒' },
  { id: 'group', label: 'AD Group', icon: '👥' },
  { id: 'user', label: 'Person', icon: '👤' },
];

export default function ShareDialog({
  resourceType = 'workflow',
  resource,
  isOpen,
  onClose,
  onChanged,
}) {
  const [activeTab, setActiveTab] = useState('marketplace');
  const [isWorking, setIsWorking] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [okMsg, setOkMsg] = useState('');

  // Marketplace tab state
  const [marketplaceName, setMarketplaceName] = useState('');
  const [marketplaceDescription, setMarketplaceDescription] = useState('');

  // Common: existing shares
  const [shares, setShares] = useState([]);
  const [pendingGrants, setPendingGrants] = useState([]);

  // Group/User picker state
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [permission, setPermission] = useState('read');
  const debounceRef = useRef(null);

  const isWorkflow = resourceType === 'workflow';
  const canShareToMarketplace = isWorkflow; // KBs are only marketplace-shared via approval
  const resourceId = resource?.id || resource?.kb_id;

  // ----- Reset state every time the dialog opens for a new resource -----
  useEffect(() => {
    if (!isOpen) return;
    setActiveTab('marketplace');
    setIsWorking(false);
    setErrorMsg('');
    setOkMsg('');
    setMarketplaceName(resource?.marketplaceName || resource?.name || '');
    setMarketplaceDescription(resource?.marketplaceDescription || '');
    setQuery('');
    setResults([]);
    setPermission('read');
    void reloadShares();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, resourceId]);

  // ----- Search debounced -----
  useEffect(() => {
    if (!isOpen) return;
    if (activeTab !== 'group' && activeTab !== 'user') {
      setResults([]);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        if (activeTab === 'group') {
          const out = await searchAdGroups(query, 20);
          setResults(out || []);
        } else {
          const out = query.length >= 2 ? await searchUsers(query, 20) : [];
          setResults(out || []);
        }
      } catch (e) {
        // search errors are non-fatal — UI just shows nothing
        console.warn('Search failed:', e);
        setResults([]);
      }
    }, 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, activeTab, isOpen]);

  async function reloadShares() {
    if (!resourceId) return;
    try {
      if (isWorkflow) {
        const data = await listWorkflowShares(resourceId);
        setShares(data.shares || []);
        setPendingGrants(data.pendingGrants || []);
      } else {
        const list = await listKnowledgeBaseShares(resourceId);
        setShares(list || []);
        setPendingGrants([]);
      }
    } catch (e) {
      console.warn('Failed to load shares:', e);
      setShares([]);
      setPendingGrants([]);
    }
  }

  // ----- Marketplace flow -----
  async function handleSubmitToMarketplace() {
    if (!marketplaceName.trim()) return;
    setIsWorking(true); setErrorMsg(''); setOkMsg('');
    try {
      await submitWorkflowForApproval(resourceId, {
        marketplaceName: marketplaceName.trim(),
        marketplaceDescription: marketplaceDescription.trim() || null,
      });
      setOkMsg('Submitted for marketplace approval. You will be notified once it is reviewed.');
      onChanged?.();
    } catch (e) {
      setErrorMsg(e.message || 'Failed to submit for approval');
    } finally {
      setIsWorking(false);
    }
  }

  async function handleRemoveFromMarketplace() {
    setIsWorking(true); setErrorMsg(''); setOkMsg('');
    try {
      await unshareWorkflowFromMarketplace(resourceId);
      setOkMsg('Removed from marketplace.');
      onChanged?.();
    } catch (e) {
      setErrorMsg(e.message || 'Failed to remove from marketplace');
    } finally {
      setIsWorking(false);
    }
  }

  // ----- Group / User grant -----
  async function handleGrant(principal) {
    setIsWorking(true); setErrorMsg(''); setOkMsg('');
    try {
      const body = {
        principalType: activeTab,                                 // 'group' | 'user'
        principalId: principal.id,
        permission,
        ...(activeTab === 'group' && principal.displayName
          ? { displayName: principal.displayName }
          : {}),
      };
      let result;
      if (isWorkflow) {
        result = await shareWorkflow(resourceId, body);
      } else {
        result = await shareKnowledgeBase(resourceId, body);
      }
      if (result?.status === 'pending') {
        setOkMsg(
          'Submitted for admin approval. Recipients will gain access after an admin approves this share.'
        );
      } else {
        setOkMsg(
          activeTab === 'group'
            ? `Shared with group "${principal.displayName || principal.id}" (${permission}).`
            : `Shared with ${principal.email || principal.displayName} (${permission}).`
        );
      }
      setQuery('');
      setResults([]);
      await reloadShares();
      onChanged?.();
    } catch (e) {
      setErrorMsg(e.message || 'Failed to share');
    } finally {
      setIsWorking(false);
    }
  }

  async function handleRevoke(share) {
    setIsWorking(true); setErrorMsg(''); setOkMsg('');
    try {
      if (isWorkflow) {
        await revokeWorkflowShare(resourceId, share.id);
      } else {
        await revokeKnowledgeBaseShare(resourceId, share.id);
      }
      await reloadShares();
      onChanged?.();
    } catch (e) {
      setErrorMsg(e.message || 'Failed to revoke share');
    } finally {
      setIsWorking(false);
    }
  }

  const filteredShares = useMemo(
    () => shares.filter(s => s.principalType === activeTab),
    [shares, activeTab]
  );

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0,0,0,0.65)' }}
      onClick={onClose}
    >
      <div
        style={{
          background: `linear-gradient(135deg, ${C.surface} 0%, ${C.bg} 100%)`,
          border: `1px solid ${C.border}`,
          borderRadius: 16,
          boxShadow: '0 12px 40px rgba(0,0,0,0.6)',
          width: '92%',
          maxWidth: 640,
          maxHeight: '88vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          fontFamily: "'Helvetica Neue', Helvetica, Arial, sans-serif",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ padding: '20px 24px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <h3 style={{ fontSize: 18, fontWeight: 600, color: C.text, margin: 0 }}>
              Share {isWorkflow ? 'workflow' : 'knowledge base'}
            </h3>
            <p style={{ fontSize: 13, color: C.textMuted, marginTop: 4 }}>
              {resource?.name || resource?.marketplaceName || 'Untitled'}
            </p>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: C.textMuted, fontSize: 22, cursor: 'pointer', padding: 4, lineHeight: 1 }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Tabs */}
        <div style={{ padding: '12px 24px 0', borderBottom: `1px solid ${C.border}`, display: 'flex', gap: 4 }}>
          {TABS.filter(t => t.id !== 'marketplace' || canShareToMarketplace).map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                padding: '8px 16px',
                fontSize: 14,
                fontWeight: 500,
                borderRadius: '8px 8px 0 0',
                border: 'none',
                cursor: 'pointer',
                transition: 'all 0.15s',
                background: activeTab === tab.id ? C.surfaceHover : 'transparent',
                color: activeTab === tab.id ? C.text : C.textMuted,
                borderBottom: activeTab === tab.id ? `2px solid ${C.rose}` : '2px solid transparent',
                marginBottom: -1,
              }}
            >
              <span style={{ marginRight: 8 }}>{tab.icon}</span>{tab.label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          {errorMsg && (
            <div style={{ fontSize: 13, color: C.errorText, background: C.errorBg, border: `1px solid ${C.errorText}33`, borderRadius: 8, padding: '8px 12px', marginBottom: 12 }}>
              {errorMsg}
            </div>
          )}
          {okMsg && (
            <div style={{ fontSize: 13, color: C.success, background: C.successBg, border: `1px solid ${C.success}33`, borderRadius: 8, padding: '8px 12px', marginBottom: 12 }}>
              {okMsg}
            </div>
          )}

          {activeTab === 'marketplace' && canShareToMarketplace && (
            <MarketplacePane
              resource={resource}
              marketplaceName={marketplaceName}
              setMarketplaceName={setMarketplaceName}
              marketplaceDescription={marketplaceDescription}
              setMarketplaceDescription={setMarketplaceDescription}
              isWorking={isWorking}
              onSubmit={handleSubmitToMarketplace}
              onRemove={handleRemoveFromMarketplace}
            />
          )}

          {(activeTab === 'group' || activeTab === 'user') && (
            <GranteePane
              kind={activeTab}
              query={query}
              setQuery={setQuery}
              results={results}
              permission={permission}
              setPermission={setPermission}
              onGrant={handleGrant}
              isWorking={isWorking}
              shares={filteredShares}
              pendingGrants={pendingGrants}
              onRevoke={handleRevoke}
            />
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 24px', borderTop: `1px solid ${C.border}`, display: 'flex', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            disabled={isWorking}
            style={{
              padding: '8px 20px',
              fontSize: 14,
              fontWeight: 500,
              borderRadius: 8,
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: C.textSecondary,
              cursor: 'pointer',
              opacity: isWorking ? 0.5 : 1,
            }}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Sub-panes
// ===========================================================================

const inputStyle = {
  width: '100%',
  padding: '8px 12px',
  fontSize: 14,
  color: C.text,
  background: C.bg,
  border: `1px solid ${C.border}`,
  borderRadius: 8,
  outline: 'none',
  fontFamily: 'inherit',
};

function MarketplacePane({
  resource,
  marketplaceName,
  setMarketplaceName,
  marketplaceDescription,
  setMarketplaceDescription,
  isWorking,
  onSubmit,
  onRemove,
}) {
  const isPublic = !!resource?.isPublic;
  const submissionStatus = resource?._submissionStatus;

  if (isPublic) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ fontSize: 13, color: C.warningText, background: C.warningBg, border: `1px solid ${C.warningText}33`, borderRadius: 8, padding: 12 }}>
          <strong>Already published.</strong> This workflow is currently
          available to everyone via the marketplace as
          <span style={{ fontWeight: 500 }}> "{resource.marketplaceName || resource.name}"</span>.
        </div>
        <p style={{ fontSize: 12, color: C.textMuted }}>
          Removing it will keep your copy intact but hide it from the marketplace.
        </p>
        <button
          onClick={onRemove}
          disabled={isWorking}
          style={{
            padding: '8px 16px', fontSize: 13, fontWeight: 500, borderRadius: 8,
            border: `1px solid ${C.warningText}66`, background: C.warningBg,
            color: C.warningText, cursor: 'pointer', opacity: isWorking ? 0.5 : 1,
          }}
        >
          {isWorking ? 'Removing…' : 'Remove from marketplace'}
        </button>
      </div>
    );
  }

  if (submissionStatus?.status === 'pending') {
    return (
      <div style={{ fontSize: 13, color: C.warningText, background: C.warningBg, border: `1px solid ${C.warningText}33`, borderRadius: 8, padding: 12 }}>
        <strong>Pending approval.</strong> An administrator is reviewing your
        submission. You'll be notified once a decision is made.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ fontSize: 13, color: C.textSecondary }}>
        Submit for admin review to share with everyone on the Storefront.
        Use the AD Group or Person tabs to limit visibility instead.
      </div>
      <div>
        <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: C.text, marginBottom: 8 }}>
          Display name <span style={{ color: C.rose }}>*</span>
        </label>
        <input
          type="text"
          value={marketplaceName}
          onChange={(e) => setMarketplaceName(e.target.value)}
          placeholder="e.g., Customer Support Assistant"
          style={inputStyle}
        />
      </div>
      <div>
        <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: C.text, marginBottom: 8 }}>
          Description
        </label>
        <textarea
          value={marketplaceDescription}
          onChange={(e) => setMarketplaceDescription(e.target.value)}
          placeholder="Describe what your workflow does and how others can use it…"
          rows={3}
          style={{ ...inputStyle, resize: 'none' }}
        />
      </div>
      {submissionStatus?.status === 'rejected' && (
        <div style={{ fontSize: 13, color: C.errorText, background: C.errorBg, border: `1px solid ${C.errorText}33`, borderRadius: 8, padding: '8px 12px' }}>
          <strong>Previously rejected:</strong>{' '}
          {submissionStatus.rejectionReason || 'no reason provided.'}
          {' '}You can edit and resubmit below.
        </div>
      )}
      <button
        onClick={onSubmit}
        disabled={!marketplaceName.trim() || isWorking}
        style={{
          padding: '10px 20px', fontSize: 14, fontWeight: 600, borderRadius: 8,
          border: 'none', background: C.rose, color: C.text, cursor: 'pointer',
          opacity: (!marketplaceName.trim() || isWorking) ? 0.5 : 1,
          alignSelf: 'flex-start',
        }}
      >
        {isWorking
          ? 'Submitting…'
          : submissionStatus?.status === 'rejected'
            ? 'Resubmit for approval'
            : 'Submit for marketplace approval'}
      </button>
    </div>
  );
}

function formatPendingGrant(p) {
  if (p.submissionType === 'workflow_share_version') {
    return 'Version republish (awaiting admin approval)';
  }
  const m = p.meta || {};
  if (m.principalType === 'group') {
    return `AD group: ${m.displayName || m.principalId} (${m.permission || 'read'})`;
  }
  if (m.principalType === 'user') {
    return `User share (${m.permission || 'read'}) — pending approval`;
  }
  return p.marketplaceName || 'Pending share';
}

function GranteePane({
  kind,
  query,
  setQuery,
  results,
  permission,
  setPermission,
  onGrant,
  isWorking,
  shares,
  pendingGrants,
  onRevoke,
}) {
  const placeholder = kind === 'group'
    ? 'Search Microsoft Entra ID groups…'
    : 'Search users by email or name…';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: C.text, marginBottom: 8 }}>
          {kind === 'group' ? 'Add an AD group' : 'Add a person'}
        </label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            style={{ ...inputStyle, flex: 1 }}
            autoFocus
          />
          <select
            value={permission}
            onChange={(e) => setPermission(e.target.value)}
            style={{ ...inputStyle, width: 'auto', cursor: 'pointer', WebkitAppearance: 'auto' }}
          >
            <option value="read">Read (Storefront only)</option>
            <option value="write">Read &amp; write (Storefront + My Tools)</option>
          </select>
        </div>
        <p style={{ fontSize: 12, color: C.textMuted, marginTop: 8 }}>
          Read: Storefront only for this {kind === 'group' ? 'group' : 'person'}.
          Read &amp; write: Storefront plus My Tools (editable).
        </p>

        {results.length > 0 && (
          <div style={{ marginTop: 8, maxHeight: 224, overflowY: 'auto', border: `1px solid ${C.border}`, borderRadius: 8 }}>
            {results.map((item, idx) => (
              <button
                key={item.id}
                onClick={() => onGrant(item)}
                disabled={isWorking}
                style={{
                  width: '100%', textAlign: 'left', padding: '8px 12px',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  background: 'transparent', border: 'none', cursor: 'pointer',
                  borderTop: idx > 0 ? `1px solid ${C.borderLight}` : 'none',
                  fontFamily: 'inherit',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = C.surfaceHover; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
              >
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: C.text }}>
                    {item.displayName || item.email || item.id}
                  </div>
                  <div style={{ fontSize: 12, color: C.textMuted }}>
                    {kind === 'group' ? (item.description || 'AD security group') : item.email}
                  </div>
                </div>
                <span style={{ fontSize: 12, color: C.rose, fontWeight: 500 }}>+ Add</span>
              </button>
            ))}
          </div>
        )}
        {kind === 'user' && query.length > 0 && query.length < 2 && (
          <p style={{ fontSize: 12, color: C.textMuted, marginTop: 8 }}>
            Type at least 2 characters to search.
          </p>
        )}
        {results.length === 0 && query.length >= 2 && (
          <p style={{ fontSize: 12, color: C.textMuted, marginTop: 8 }}>
            No matches.
          </p>
        )}
      </div>

      {pendingGrants?.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: C.text, marginBottom: 8 }}>
            Pending admin approval
          </label>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, border: `1px solid ${C.warningText}33`, borderRadius: 8, background: C.warningBg }}>
            {pendingGrants
              .filter((p) => p.submissionType === 'workflow_share_grant' || p.submissionType === 'workflow_share_version')
              .map((p, idx) => (
                <li key={p.submissionId} style={{
                  padding: '8px 12px',
                  fontSize: 12,
                  color: C.warningText,
                  borderTop: idx > 0 ? `1px solid ${C.borderLight}` : 'none',
                }}>
                  {formatPendingGrant(p)}
                </li>
              ))}
          </ul>
        </div>
      )}

      <div>
        <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: C.text, marginBottom: 8 }}>
          Currently shared with
        </label>
        {shares.length === 0 ? (
          <p style={{ fontSize: 12, color: C.textMuted }}>
            Not shared with any {kind === 'group' ? 'AD groups' : 'people'} yet.
          </p>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, border: `1px solid ${C.border}`, borderRadius: 8 }}>
            {shares.map((s, idx) => (
              <li key={s.id} style={{
                padding: '8px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                borderTop: idx > 0 ? `1px solid ${C.borderLight}` : 'none',
              }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: C.text }}>
                    {s.principalDisplayName || s.principalEmail || s.principalId}
                  </div>
                  <div style={{ fontSize: 12, color: C.textMuted }}>
                    {s.permission === 'write' ? 'Read & write' : 'Read only'}
                    {s.principalEmail && ` · ${s.principalEmail}`}
                  </div>
                </div>
                <button
                  onClick={() => onRevoke(s)}
                  disabled={isWorking}
                  style={{
                    fontSize: 12, color: C.errorText, background: 'none', border: 'none',
                    cursor: 'pointer', fontWeight: 500, opacity: isWorking ? 0.5 : 1,
                  }}
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
