import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchAdminSharingOverview } from '../../../api/admin';
import {
  fetchAllSharedTools,
  deleteSharedTool,
  uploadSharedToolsCsv,
  fetchSharedToolAuditLog,
  updateSharedTool,
} from '../../../api/shared-tools';
import { downloadSharedToolsCsvTemplate } from '../../../utils/sharedToolsCsvTemplate';
import SharingTargetsFields from '../../sharing/SharingTargetsFields';

const CHANNEL_LABELS = {
  marketplace: 'Marketplace',
  ad_group: 'AD group',
  user: 'User',
};

function ChannelBadges({ channels }) {
  if (!channels?.length) {
    return <span className="text-gray-500">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {channels.map((c) => (
        <span
          key={c}
          className="inline-block px-2 py-0.5 rounded text-xs font-medium"
          style={{
            backgroundColor:
              c === 'marketplace'
                ? 'rgba(234, 88, 12, 0.25)'
                : c === 'ad_group'
                  ? 'rgba(59, 130, 246, 0.2)'
                  : 'rgba(34, 197, 94, 0.2)',
            color: c === 'marketplace' ? '#fb923c' : c === 'ad_group' ? '#93c5fd' : '#86efac',
          }}
        >
          {CHANNEL_LABELS[c] || c}
        </span>
      ))}
    </div>
  );
}

function SharesList({ shares }) {
  if (!shares?.length) {
    return <span className="text-gray-500 text-xs">—</span>;
  }
  return (
    <ul className="text-xs text-gray-300 space-y-0.5">
      {shares.map((s) => (
        <li key={s.id}>
          <span className="text-gray-500">{s.principal_type === 'group' ? 'Group' : 'User'}:</span>{' '}
          {s.principal_display_name || s.principal_id}
          {s.principal_email ? ` (${s.principal_email})` : ''}
          <span className="text-gray-500"> · {s.permission}</span>
        </li>
      ))}
    </ul>
  );
}

function VersionCell({ current, approved, isDraft }) {
  const parts = [];
  if (current != null) {
    parts.push(`Current v${current}`);
  }
  if (approved != null) {
    parts.push(`Marketplace v${approved}`);
  }
  if (!parts.length) {
    return <span className="text-gray-500">—</span>;
  }
  return (
    <div className="text-xs">
      {parts.map((p) => (
        <div key={p}>{p}</div>
      ))}
      {isDraft && <div className="text-amber-400/80 mt-0.5">Draft</div>}
    </div>
  );
}

function ResourceTable({ title, description, rows, type }) {
  const isWorkflow = type === 'workflow';

  return (
    <section className="mb-10">
      <h3 className="text-lg font-semibold mb-1">{title}</h3>
      <p className="text-sm text-gray-400 mb-4">{description}</p>
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">No shared {isWorkflow ? 'workflows' : 'knowledge bases'}.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-left">
              <tr>
                <th className="p-3">Name</th>
                <th className="p-3">Owner</th>
                <th className="p-3">Sharing</th>
                <th className="p-3">{isWorkflow ? 'Version' : 'Status'}</th>
                <th className="p-3">Grants</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-gray-800 align-top">
                  <td className="p-3">
                    <div className="font-medium">{row.marketplace_name || row.name}</div>
                    {row.marketplace_name && row.marketplace_name !== row.name && (
                      <div className="text-xs text-gray-500">{row.name}</div>
                    )}
                    <div className="text-xs text-gray-600 font-mono mt-0.5">{row.id}</div>
                  </td>
                  <td className="p-3 text-gray-300">
                    <div>{row.owner_name || '—'}</div>
                    {row.owner_email && (
                      <div className="text-xs text-gray-500">{row.owner_email}</div>
                    )}
                  </td>
                  <td className="p-3">
                    <ChannelBadges channels={row.share_channels} />
                  </td>
                  <td className="p-3">
                    {isWorkflow ? (
                      <VersionCell
                        current={row.current_version_number}
                        approved={row.approved_version_number}
                        isDraft={row.is_draft}
                      />
                    ) : (
                      <div className="text-xs">
                        <div>{row.status || '—'}</div>
                        {row.document_count != null && (
                          <div className="text-gray-500">{row.document_count} docs</div>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="p-3 max-w-xs">
                    <SharesList shares={row.shares} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ─── Audit Log Viewer ──────────────────────────────────────────────────────
function AuditLogViewer() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchSharedToolAuditLog(50, 0);
        setEntries(data.items || []);
      } catch { /* ignore */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-gray-500 text-xs py-2">Loading audit log...</div>;
  if (entries.length === 0) return <div className="text-gray-500 text-xs py-2">No audit entries yet.</div>;

  return (
    <div className="overflow-x-auto rounded border border-gray-700 max-h-64 overflow-y-auto">
      <table className="w-full text-xs">
        <thead className="bg-gray-900 text-left sticky top-0">
          <tr>
            <th className="p-2">Time</th>
            <th className="p-2">Action</th>
            <th className="p-2">Performed By</th>
            <th className="p-2">Details</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className="border-t border-gray-800">
              <td className="p-2 whitespace-nowrap text-gray-400">
                {e.performed_at ? new Date(e.performed_at).toLocaleString() : '—'}
              </td>
              <td className="p-2">
                <span
                  className="px-1.5 py-0.5 rounded text-xs"
                  style={{
                    backgroundColor:
                      e.action === 'created' ? 'rgba(34,197,94,0.15)' :
                      e.action === 'deleted' ? 'rgba(239,68,68,0.15)' :
                      e.action === 'csv_uploaded' ? 'rgba(59,130,246,0.15)' :
                      'rgba(234,179,8,0.15)',
                    color:
                      e.action === 'created' ? '#86efac' :
                      e.action === 'deleted' ? '#fca5a5' :
                      e.action === 'csv_uploaded' ? '#93c5fd' :
                      '#fde047',
                  }}
                >
                  {e.action}
                </span>
              </td>
              <td className="p-2 text-gray-300">{e.performer_display || e.performed_by}</td>
              <td className="p-2 text-gray-500 max-w-[300px] truncate">
                {e.details ? (
                  typeof e.details === 'object'
                    ? JSON.stringify(e.details).slice(0, 120)
                    : String(e.details).slice(0, 120)
                ) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function permissionsToSharingState(permissions) {
  const selectedGroups = [];
  const selectedEmails = [];
  for (const p of permissions || []) {
    if (p.principal_type === 'group') {
      selectedGroups.push({
        id: p.principal_id,
        displayName: p.display_name || p.principal_id,
      });
    } else if (p.principal_type === 'user') {
      selectedEmails.push({
        id: p.principal_id,
        email: p.display_name || p.principal_id,
      });
    }
  }
  return { selectedGroups, selectedEmails };
}

function EditSharedToolModal({ tool, onClose, onSaved }) {
  const [toolName, setToolName] = useState(tool.tool_name || '');
  const [description, setDescription] = useState(tool.description || '');
  const [url, setUrl] = useState(tool.url || '');
  const [isPublic, setIsPublic] = useState(!!tool.is_public);
  const [selectedGroups, setSelectedGroups] = useState([]);
  const [selectedEmails, setSelectedEmails] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    const { selectedGroups: groups, selectedEmails: emails } = permissionsToSharingState(
      tool.permissions
    );
    setSelectedGroups(groups);
    setSelectedEmails(emails);
  }, [tool]);

  const handleSave = async () => {
    const name = toolName.trim();
    const link = url.trim();
    if (!name) {
      setSaveError('Name is required');
      return;
    }
    if (!link) {
      setSaveError('URL is required');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const payload = {
        tool_name: name,
        description: description.trim() || null,
        url: link,
        is_public: isPublic,
        ad_group_names: isPublic
          ? []
          : selectedGroups.map((g) => g.displayName || g.name).filter(Boolean),
        emails: isPublic ? [] : selectedEmails.map((u) => u.email).filter(Boolean),
      };
      const updated = await updateSharedTool(tool.id, payload);
      onSaved(updated);
      onClose();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-lg border border-gray-700 p-6 shadow-xl"
        style={{ backgroundColor: '#1a1a1a', color: '#e5e5e5' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold mb-1">Edit shared external tool</h3>
        <p className="text-sm text-gray-400 mb-4">
          Update name, URL, description, and who can see this tool on the Storefront.
        </p>

        <label className="block text-sm text-gray-400 mb-1">Name</label>
        <input
          type="text"
          value={toolName}
          onChange={(e) => setToolName(e.target.value)}
          className="w-full mb-4 px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm"
        />

        <label className="block text-sm text-gray-400 mb-1">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full mb-4 px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm resize-none"
        />

        <label className="block text-sm text-gray-400 mb-1">URL</label>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="w-full mb-4 px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm"
        />

        <SharingTargetsFields
          variant="dark"
          isPublic={isPublic}
          onIsPublicChange={setIsPublic}
          selectedGroups={selectedGroups}
          onSelectedGroupsChange={setSelectedGroups}
          selectedEmails={selectedEmails}
          onSelectedEmailsChange={setSelectedEmails}
        />

        {saveError && (
          <div className="mt-4 p-3 rounded bg-red-900/40 text-red-200 text-sm">{saveError}</div>
        )}

        <div className="flex justify-end gap-3 mt-6">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 rounded text-sm border border-gray-600 hover:border-gray-400 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 rounded text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: 'rgba(234, 88, 12, 0.85)', color: '#fff' }}
          >
            {saving ? 'Saving...' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Shared Tools Section ──────────────────────────────────────────────────
function SharedToolsSection() {
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [csvResult, setCsvResult] = useState(null);
  const [csvUploading, setCsvUploading] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [editingTool, setEditingTool] = useState(null);
  const [showAuditLog, setShowAuditLog] = useState(false);
  const fileInputRef = useRef(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchAllSharedTools();
      setTools(data.items || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCsvUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvUploading(true);
    setCsvResult(null);
    try {
      const result = await uploadSharedToolsCsv(file);
      setCsvResult(result);
      await load();
    } catch (err) {
      setCsvResult({ error: err.message });
    } finally {
      setCsvUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (toolId) => {
    if (!window.confirm('Delete this shared tool?')) return;
    setDeleting(toolId);
    try {
      await deleteSharedTool(toolId);
      setTools(tools.filter((t) => t.id !== toolId));
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <section className="mb-10">
      <h3 className="text-lg font-semibold mb-1">Shared External Tools</h3>
      <p className="text-sm text-gray-400 mb-4">
        External tool links shared with users via the Storefront. Upload a CSV, edit existing tools, or
        delete individually.
      </p>

      {editingTool && (
        <EditSharedToolModal
          tool={editingTool}
          onClose={() => setEditingTool(null)}
          onSaved={() => load()}
        />
      )}

      {/* CSV Upload */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <button
          type="button"
          onClick={() => downloadSharedToolsCsvTemplate()}
          className="px-4 py-2 rounded text-sm border border-gray-600 hover:border-gray-400 transition-colors"
          style={{ color: '#e5e5e5' }}
        >
          Download CSV template
        </button>
        <label
          className="px-4 py-2 rounded text-sm border border-gray-600 cursor-pointer hover:border-gray-400 transition-colors"
          style={{ color: '#e5e5e5' }}
        >
          {csvUploading ? 'Uploading...' : 'Upload CSV'}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleCsvUpload}
            disabled={csvUploading}
            style={{ display: 'none' }}
          />
        </label>
        <span className="text-xs text-gray-500">
          Columns: tool_name, description, url, is_public, ad_group_csv, email_csv
        </span>
      </div>

      {csvResult && (
        <div
          className="mb-4 p-3 rounded text-sm"
          style={{
            backgroundColor: csvResult.error ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
            color: csvResult.error ? '#fca5a5' : '#86efac',
          }}
        >
          {csvResult.error ? (
            <span>{csvResult.error}</span>
          ) : (
            <span>
              Created: {csvResult.created} | Skipped: {csvResult.skipped}
              {csvResult.skipped_details?.length > 0 && (
                <span className="block text-xs mt-1 text-gray-400">
                  Skipped: {csvResult.skipped_details.map((s) => s.tool_name).join(', ')}
                </span>
              )}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 rounded bg-red-900/40 text-red-200 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-gray-400 text-sm">Loading shared tools...</div>
      ) : tools.length === 0 ? (
        <p className="text-sm text-gray-500">No shared external tools yet.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-left">
              <tr>
                <th className="p-3">Name</th>
                <th className="p-3">URL</th>
                <th className="p-3">Visibility</th>
                <th className="p-3">Permissions</th>
                <th className="p-3">Status</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tools.map((tool) => (
                <tr key={tool.id} className="border-t border-gray-800 align-top">
                  <td className="p-3">
                    <div className="font-medium">{tool.tool_name}</div>
                    {tool.description && (
                      <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{tool.description}</div>
                    )}
                  </td>
                  <td className="p-3 max-w-[200px]">
                    <a
                      href={tool.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-400 hover:underline text-xs break-all"
                    >
                      {tool.url}
                    </a>
                  </td>
                  <td className="p-3">
                    {tool.is_public ? (
                      <span className="text-xs px-2 py-0.5 rounded bg-green-900/40 text-green-300">Public</span>
                    ) : (
                      <span className="text-xs px-2 py-0.5 rounded bg-blue-900/40 text-blue-300">Restricted</span>
                    )}
                  </td>
                  <td className="p-3 max-w-[180px]">
                    {tool.permissions?.length > 0 ? (
                      <ul className="text-xs text-gray-300 space-y-0.5">
                        {tool.permissions.map((p) => (
                          <li key={p.id}>
                            <span className="text-gray-500">{p.principal_type === 'group' ? 'Group' : 'User'}:</span>{' '}
                            {p.display_name || p.principal_id}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-gray-500 text-xs">—</span>
                    )}
                  </td>
                  <td className="p-3">
                    <span
                      className="text-xs px-2 py-0.5 rounded"
                      style={{
                        backgroundColor: tool.status === 'approved' ? 'rgba(34,197,94,0.15)' : 'rgba(234,179,8,0.15)',
                        color: tool.status === 'approved' ? '#86efac' : '#fde047',
                      }}
                    >
                      {tool.status}
                    </span>
                  </td>
                  <td className="p-3">
                    <div className="flex flex-col gap-1.5 items-start">
                      <button
                        type="button"
                        onClick={() => setEditingTool(tool)}
                        className="text-xs text-orange-400 hover:text-orange-300"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(tool.id)}
                        disabled={deleting === tool.id}
                        className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
                      >
                        {deleting === tool.id ? '...' : 'Delete'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Audit Log */}
      <div className="mt-6">
        <button
          type="button"
          onClick={() => setShowAuditLog(!showAuditLog)}
          className="text-sm text-gray-400 hover:text-gray-200 transition-colors"
        >
          {showAuditLog ? '▾ Hide Audit Log' : '▸ Show Audit Log'}
        </button>
        {showAuditLog && (
          <div className="mt-3">
            <AuditLogViewer />
          </div>
        )}
      </div>
    </section>
  );
}

// ─── Main Tab ──────────────────────────────────────────────────────────────
export default function SharedResourcesTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const overview = await fetchAdminSharingOverview();
        setData(overview);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const filterFn = (row) => {
    if (filter === 'all') return true;
    if (filter === 'marketplace') return row.share_channels?.includes('marketplace');
    if (filter === 'ad_group') return row.share_channels?.includes('ad_group');
    if (filter === 'user') return row.share_channels?.includes('user');
    return true;
  };

  const workflows = useMemo(
    () => (data?.workflows || []).filter(filterFn),
    [data, filter]
  );
  const knowledgeBases = useMemo(
    () => (data?.knowledge_bases || []).filter(filterFn),
    [data, filter]
  );

  if (loading) {
    return <div className="p-8 text-gray-400">Loading shared resources…</div>;
  }

  return (
    <div className="p-6 overflow-auto h-full" style={{ color: '#e5e5e5' }}>
      <h2 className="text-xl font-semibold mb-2">Shared resources</h2>
      <p className="text-sm text-gray-400 mb-4">
        Workflows and knowledge bases on the marketplace or shared with AD groups or individual
        users. Workflow rows show current and marketplace-approved version numbers.
      </p>

      {data?.summary && (
        <p className="text-sm text-gray-500 mb-4">
          {data.summary.workflow_count} workflow
          {data.summary.workflow_count === 1 ? '' : 's'},{' '}
          {data.summary.knowledge_base_count} knowledge base
          {data.summary.knowledge_base_count === 1 ? '' : 's'} total
        </p>
      )}

      <div className="flex flex-wrap gap-2 mb-6">
        {[
          { id: 'all', label: 'All' },
          { id: 'marketplace', label: 'Marketplace' },
          { id: 'ad_group', label: 'AD groups' },
          { id: 'user', label: 'Users' },
        ].map((opt) => (
          <button
            key={opt.id}
            type="button"
            onClick={() => setFilter(opt.id)}
            className="px-3 py-1.5 rounded text-sm border transition-colors"
            style={{
              borderColor: filter === opt.id ? 'rgba(234, 88, 12, 0.5)' : '#404040',
              backgroundColor: filter === opt.id ? 'rgba(234, 88, 12, 0.15)' : 'transparent',
              color: filter === opt.id ? '#fb923c' : '#a3a3a3',
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 rounded bg-red-900/40 text-red-200 text-sm">{error}</div>
      )}

      <SharedToolsSection />

      <ResourceTable
        title="Workflows"
        description="Includes marketplace listings and direct shares."
        rows={workflows}
        type="workflow"
      />
      <ResourceTable
        title="Knowledge bases"
        description="KBs do not use workflow-style versioning; status and document count are shown instead."
        rows={knowledgeBases}
        type="kb"
      />
    </div>
  );
}
