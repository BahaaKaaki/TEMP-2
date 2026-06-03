/**
 * ApexShell — top-level container that renders the dark Apex OS top bar
 * and the active page (Storefront / My Sessions / My Tools).
 *
 * The active tab is stored in `state.activeTab` (which previously held
 * the legacy WorkspaceView tab). We redefine the valid values as:
 *   - 'storefront'  → StorefrontView
 *   - 'sessions'    → MySessionsView
 *   - 'mytools'     → MyToolsView
 *   - 'admin'       → AdminPortal (admin only, accessible via avatar menu)
 *   - 'approval'    → legacy alias for 'admin'
 *
 * Older saved values like 'marketplace' / 'workflows' / 'drafts' /
 * 'knowledge-bases' are mapped to 'storefront' on first render so users
 * who upgrade in-place don't see a blank screen.
 */

import { useEffect, useState } from 'react';
import { useWorkflow } from '../../context/WorkflowContext';
import { useAuth } from '../../context/AuthContext';
import { listAllMySessions } from '../../api/client';
import ApexTopBar from './ApexTopBar';
import StorefrontView from './StorefrontView';
import MySessionsView from './MySessionsView';
import MyToolsView from './MyToolsView';
import AdminPortal from '../admin/AdminPortal';
import { COLOR } from './apexShellSpec';

const VALID_TABS = new Set(['storefront', 'sessions', 'mytools', 'admin']);

const LEGACY_TAB_MAP = {
  marketplace: 'storefront',
  workflows: 'mytools',
  drafts: 'mytools',
  'knowledge-bases': 'mytools',
  shared: 'mytools',
  approval: 'admin',
};

export default function ApexShell() {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const { user } = useAuth();
  const isAdmin = user?.roleSlug?.toLowerCase().includes('admin') || false;
  const [sessionCount, setSessionCount] = useState(0);

  // Normalise legacy tab values once on mount.
  useEffect(() => {
    const tab = state.activeTab;
    if (!tab || !VALID_TABS.has(tab)) {
      const mapped = LEGACY_TAB_MAP[tab] || 'storefront';
      dispatch({ type: ACTIONS.SET_ACTIVE_TAB, payload: mapped });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load session count for the "My Sessions" badge.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const sessions = await listAllMySessions(500);
        if (cancelled) return;
        setSessionCount(Array.isArray(sessions) ? sessions.length : 0);
      } catch {
        // No-op — badge simply stays at 0.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const activeTab = VALID_TABS.has(state.activeTab) ? state.activeTab : 'storefront';

  const handleTabChange = (tab) => {
    if (tab === 'admin' && !isAdmin) return;
    dispatch({ type: ACTIONS.SET_ACTIVE_TAB, payload: tab });
  };

  return (
    <div
      data-apex-shell
      className="flex flex-col"
      style={{
        height: '100dvh',
        width: '100vw',
        backgroundColor: COLOR.black,
        overflow: 'hidden',
      }}
    >
      {activeTab !== 'admin' && (
        <ApexTopBar
          activeTab={activeTab}
          onTabChange={handleTabChange}
          sessionCount={sessionCount}
        />
      )}
      <main style={{ flex: '1 1 0', minHeight: 0, overflow: 'hidden', position: 'relative' }}>
        {activeTab === 'storefront' && <StorefrontView />}
        {activeTab === 'sessions' && <MySessionsView />}
        {activeTab === 'mytools' && <MyToolsView />}
        {activeTab === 'admin' && isAdmin && <AdminPortal />}
      </main>
    </div>
  );
}
