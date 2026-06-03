import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchAdminUsers,
  grantAdminUser,
  revokeAdminUser,
  searchAdminUsers,
} from '../../../api/admin';

function displayName(user) {
  const parts = [user.firstName, user.lastName].filter(Boolean);
  if (parts.length) return parts.join(' ');
  return user.email;
}

export default function AdminsTab() {
  const [admins, setAdmins] = useState([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [revokingId, setRevokingId] = useState(null);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);
  const debounceRef = useRef(null);

  const loadAdmins = useCallback(async () => {
    const rows = await fetchAdminUsers();
    setAdmins(rows);
    return rows;
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        setError(null);
        await loadAdmins();
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [loadAdmins]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.length < 2) {
      setResults([]);
      return undefined;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const out = await searchAdminUsers(query, 20);
        setResults(out || []);
      } catch {
        setResults([]);
      }
    }, 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  const handleGrant = async (candidate) => {
    if (candidate.isAdmin) {
      setMessage(`${candidate.displayName || candidate.email} is already an admin.`);
      setQuery('');
      setResults([]);
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      setMessage(null);
      const result = await grantAdminUser({
        userId: candidate.id,
        email: candidate.email,
      });
      setQuery('');
      setResults([]);
      await loadAdmins();
      setMessage(
        result.status === 'already_admin'
          ? `${candidate.email} is already an admin.`
          : `Admin access granted to ${candidate.displayName || candidate.email}.`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (user) => {
    if (!window.confirm(`Remove admin access for ${user.email}?`)) return;
    try {
      setRevokingId(user.id);
      setError(null);
      setMessage(null);
      await revokeAdminUser(user.id);
      await loadAdmins();
      setMessage(`Admin access removed for ${user.email}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <div className="h-full overflow-auto p-6" style={{ backgroundColor: '#0a0a0a' }}>
      <h2 className="text-xl font-semibold text-white mb-1">App admins</h2>
      <p className="text-sm text-gray-400 mb-6">
        Users with app admin access can use this portal and manage marketplace approvals.
        Search by name or email — users must have signed in at least once.
      </p>

      <div className="mb-8 max-w-xl">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400 uppercase tracking-wide">
            Add admin — search by name or email
          </span>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search users…"
            className="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white"
            disabled={submitting}
            autoComplete="off"
          />
        </label>

        {query.length > 0 && query.length < 2 && (
          <p className="text-xs text-gray-500 mt-2">Type at least 2 characters to search.</p>
        )}

        {results.length > 0 && (
          <ul
            className="mt-2 max-h-56 overflow-y-auto rounded border border-gray-700 divide-y divide-gray-800"
            role="listbox"
          >
            {results.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => handleGrant(item)}
                  disabled={submitting}
                  className="w-full text-left px-3 py-2 hover:bg-gray-800/80 disabled:opacity-50 flex items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <div className="text-sm text-white truncate">
                      {item.displayName || item.email}
                    </div>
                    <div className="text-xs text-gray-500 truncate">{item.email}</div>
                  </div>
                  <span
                    className="text-xs font-medium shrink-0"
                    style={{ color: item.isAdmin ? '#a3a3a3' : '#fb923c' }}
                  >
                    {item.isAdmin ? 'Already admin' : submitting ? '…' : 'Add admin'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {query.length >= 2 && results.length === 0 && !submitting && (
          <p className="text-xs text-gray-500 mt-2">No users found. They must sign in once before you can add them.</p>
        )}
      </div>

      {error && (
        <p className="text-sm text-red-400 mb-4" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="text-sm text-green-400 mb-4" role="status">
          {message}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-gray-500">Loading admins…</p>
      ) : admins.length === 0 ? (
        <p className="text-sm text-gray-500">No admins found.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-gray-700 max-w-4xl">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-left">
              <tr>
                <th className="p-3">Name</th>
                <th className="p-3">Email</th>
                <th className="p-3">Role</th>
                <th className="p-3">Last active</th>
                <th className="p-3 w-28" />
              </tr>
            </thead>
            <tbody>
              {admins.map((user) => (
                <tr key={user.id} className="border-t border-gray-800">
                  <td className="p-3 text-white">{displayName(user)}</td>
                  <td className="p-3 text-gray-300">{user.email}</td>
                  <td className="p-3 text-gray-400 font-mono text-xs">{user.roleSlug}</td>
                  <td className="p-3 text-gray-500 text-xs">
                    {user.lastActiveAt
                      ? new Date(user.lastActiveAt).toLocaleString()
                      : '—'}
                  </td>
                  <td className="p-3">
                    <button
                      type="button"
                      onClick={() => handleRevoke(user)}
                      disabled={revokingId === user.id}
                      className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
                    >
                      {revokingId === user.id ? 'Removing…' : 'Remove'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
