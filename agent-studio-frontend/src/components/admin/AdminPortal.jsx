import { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useWorkflow } from '../../context/WorkflowContext';
import PublishRequestsTab from './tabs/PublishRequestsTab';
import SharedResourcesTab from './tabs/SharedResourcesTab';
import AllModelsTab from './tabs/AllModelsTab';
import ToolLlmTab from './tabs/ToolLlmTab';
import WorkflowLlmTab from './tabs/WorkflowLlmTab';
import AdminsTab from './tabs/AdminsTab';
import AnalyticsDashboardTab from './tabs/AnalyticsDashboardTab';
import { COLOR } from '../shell/apexShellSpec';

const NAV_GROUPS = [
  {
    label: 'Platform',
    sections: [
      { id: 'admins', label: 'Admins' },
      { id: 'publish-requests', label: 'Publish requests' },
      { id: 'shared-resources', label: 'Shared resources' },
    ],
  },
  {
    label: 'Model governance',
    sections: [
      { id: 'all-models', label: 'All models' },
      { id: 'tool-llm', label: 'Tool LLM' },
      { id: 'workflow-llm', label: 'Workflow LLM' },
    ],
  },
  {
    label: 'Analytics',
    sections: [
      { id: 'analytics', label: 'Analytics' },
    ],
  },
];

export default function AdminPortal() {
  const { user, logout } = useAuth();
  const { dispatch, ACTIONS } = useWorkflow();
  const isAdmin = user?.roleSlug?.toLowerCase().includes('admin') || false;
  const [section, setSection] = useState('admins');

  const initials = (() => {
    if (user?.firstName && user?.lastName) return `${user.firstName[0]}${user.lastName[0]}`.toUpperCase();
    if (user?.firstName) return user.firstName[0].toUpperCase();
    if (user?.email) return user.email[0].toUpperCase();
    return 'U';
  })();

  const exitAdmin = () => {
    dispatch({ type: ACTIONS.SET_ACTIVE_TAB, payload: 'storefront' });
  };

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center" style={{ color: COLOR.white }}>
        <p className="text-lg">Admin access required</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full" style={{ backgroundColor: COLOR.black }}>
      <header
        className="flex items-center justify-between shrink-0 border-b border-gray-800 px-5"
        style={{ height: 56, backgroundColor: '#111' }}
      >
        <img
          src="/icons/apex-os-logo.svg"
          alt="Apex OS"
          draggable={false}
          style={{ height: 28, width: 'auto' }}
        />
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={exitAdmin}
            className="text-sm font-medium transition-colors hover:text-white"
            style={{ color: '#a3a3a3' }}
          >
            ← Back to app
          </button>
          <span
            className="flex items-center justify-center"
            style={{
              width: 36,
              height: 36,
              borderRadius: '50%',
              backgroundColor: COLOR.rose,
              color: COLOR.white,
              fontSize: 13,
              fontWeight: 700,
            }}
            title={user?.email || undefined}
          >
            {initials}
          </span>
          <button
            type="button"
            onClick={logout}
            className="text-sm font-medium transition-opacity hover:opacity-80"
            style={{ color: COLOR.rose, background: 'none', border: 'none', cursor: 'pointer' }}
          >
            Sign out
          </button>
        </div>
      </header>
      <div className="flex flex-1 min-h-0 w-full">
      <nav
        className="flex flex-col shrink-0 border-r border-gray-800 py-6 px-3 gap-1"
        style={{ width: 220, backgroundColor: '#111' }}
      >
        <h1 className="text-sm font-semibold uppercase tracking-wide text-gray-500 px-3 mb-4">
          Admin Portal
        </h1>
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-4 last:mb-0">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-600 px-3 mb-2">
              {group.label}
            </h2>
            {group.sections.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSection(s.id)}
                className="text-left w-full px-3 py-2 rounded text-sm font-medium transition-colors"
                style={{
                  backgroundColor: section === s.id ? 'rgba(234, 88, 12, 0.2)' : 'transparent',
                  color: section === s.id ? '#fb923c' : '#a3a3a3',
                  border: section === s.id ? '1px solid rgba(234, 88, 12, 0.4)' : '1px solid transparent',
                }}
              >
                {s.label}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <main className="flex-1 min-w-0 min-h-0 overflow-hidden">
        {section === 'analytics' && <AnalyticsDashboardTab />}
        {section === 'publish-requests' && <PublishRequestsTab isAdmin={isAdmin} />}
        {section === 'shared-resources' && <SharedResourcesTab />}
        {section === 'admins' && <AdminsTab />}
        {section === 'all-models' && <AllModelsTab />}
        {section === 'tool-llm' && <ToolLlmTab />}
        {section === 'workflow-llm' && <WorkflowLlmTab />}
      </main>
      </div>
    </div>
  );
}
