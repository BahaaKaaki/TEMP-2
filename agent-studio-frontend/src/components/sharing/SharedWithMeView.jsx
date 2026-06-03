/**
 * SharedWithMeView
 * ----------------
 * Lists workflows + knowledge bases that the current user has access to
 * via an AD-group share or a direct user share. Excludes resources the
 * user owns (those already appear under "Workflows" / "Knowledge Bases")
 * and excludes public marketplace resources (those appear under "Marketplace").
 */
import { useEffect, useState } from 'react';
import {
  listSharedWithMeWorkflows,
  listSharedWithMeKnowledgeBases,
} from '@/api/sharing';

export default function SharedWithMeView({ onOpenWorkflow, onChatWorkflow, onOpenKB }) {
  const [innerTab, setInnerTab] = useState('workflows');
  const [workflows, setWorkflows] = useState([]);
  const [kbs, setKbs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [wfs, kbList] = await Promise.all([
          listSharedWithMeWorkflows().catch(() => []),
          listSharedWithMeKnowledgeBases().catch(() => []),
        ]);
        if (cancelled) return;
        setWorkflows(wfs || []);
        setKbs(kbList || []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const innerTabs = [
    { id: 'workflows', label: 'Workflows', count: workflows.length },
    { id: 'kbs',       label: 'Knowledge Bases', count: kbs.length },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1 border-b border-gray-200">
        {innerTabs.map(t => (
          <button
            key={t.id}
            onClick={() => setInnerTab(t.id)}
            className={`px-3 py-2 text-sm font-medium transition-colors ${
              innerTab === t.id
                ? 'text-foreground border-b-2 border-primary -mb-px'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t.label}
            <span className="ml-2 px-2 py-0.5 text-xs rounded-full bg-gray-200">
              {t.count}
            </span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-400" />
        </div>
      ) : innerTab === 'workflows' ? (
        workflows.length === 0 ? (
          <EmptyState
            title="Nothing shared with you yet"
            message="Workflows shared with read & write access appear here. Read-only shares are on the Storefront only."
            icon="🔗"
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {workflows.map(wf => (
              <SharedWorkflowCard
                key={wf.id}
                workflow={wf}
                onOpenWorkflow={onOpenWorkflow}
                onChatWorkflow={onChatWorkflow}
              />
            ))}
          </div>
        )
      ) : (
        kbs.length === 0 ? (
          <EmptyState
            title="No shared knowledge bases"
            message="Knowledge bases shared with read & write access appear here. Read-only shares are on the Storefront only."
            icon="📚"
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {kbs.map(kb => (
              <SharedKBCard key={kb.id} kb={kb} onOpenKB={onOpenKB} />
            ))}
          </div>
        )
      )}
    </div>
  );
}

function EmptyState({ title, message, icon }) {
  return (
    <div className="flex flex-col items-center justify-center h-64 text-center">
      <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
        <span className="text-3xl">{icon}</span>
      </div>
      <h3 className="text-lg font-medium text-foreground mb-2">{title}</h3>
      <p className="text-sm text-muted-foreground max-w-md">{message}</p>
    </div>
  );
}

function ViaBadge({ via, viaPrincipalDisplayName, viaPrincipalId }) {
  const label = via === 'group'
    ? `via group "${viaPrincipalDisplayName || viaPrincipalId.slice(0, 8)}"`
    : 'shared directly with you';
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-full px-2 py-0.5">
      {via === 'group' ? '👥' : '👤'} {label}
    </span>
  );
}

function PermissionBadge({ permission }) {
  return (
    <span className={`inline-flex items-center text-[11px] font-medium rounded-full px-2 py-0.5 border ${
      permission === 'write'
        ? 'text-green-700 bg-green-50 border-green-200'
        : 'text-gray-700 bg-gray-50 border-gray-200'
    }`}>
      {permission === 'write' ? 'Read & write' : 'Read only'}
    </span>
  );
}

function SharedWorkflowCard({ workflow, onOpenWorkflow, onChatWorkflow }) {
  return (
    <div className="bg-white rounded-lg border border-border p-6 hover:shadow-lg transition-shadow group">
      <div className="flex items-start justify-between mb-4">
        <div className="w-12 h-12 rounded-lg bg-gray-200 flex items-center justify-center">
          <img src="/icons/workflow.svg" alt="Workflow" className="w-7 h-7" />
        </div>
      </div>

      <h3 className="text-lg font-semibold text-foreground mb-2">
        {workflow.name || 'Untitled workflow'}
      </h3>
      <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
        {workflow.description || ''}
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-3">
        <ViaBadge
          via={workflow.via}
          viaPrincipalDisplayName={workflow.viaPrincipalDisplayName}
          viaPrincipalId={workflow.viaPrincipalId}
        />
        <PermissionBadge permission={workflow.permission} />
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground mb-4">
        <span>
          {new Date(workflow.updatedAt).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric',
          })}
        </span>
        {workflow.createdByName && (
          <span>shared by {workflow.createdByName}</span>
        )}
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onChatWorkflow?.(workflow)}
          className="flex-1 px-3 py-1.5 text-sm bg-gray-700 text-white font-medium rounded-md hover:bg-gray-800 transition-colors"
        >
          Chat
        </button>
        {workflow.permission === 'write' ? (
          <button
            onClick={() => onOpenWorkflow?.(workflow)}
            className="flex-1 px-3 py-1.5 text-sm bg-white hover:bg-gray-50 text-gray-700 font-medium rounded-md border border-gray-300 transition-colors"
          >
            Edit
          </button>
        ) : (
          <button
            onClick={() => onOpenWorkflow?.(workflow)}
            className="flex-1 px-3 py-1.5 text-sm bg-white hover:bg-gray-50 text-gray-700 font-medium rounded-md border border-gray-300 transition-colors"
          >
            View
          </button>
        )}
      </div>
    </div>
  );
}

function SharedKBCard({ kb, onOpenKB }) {
  return (
    <div className="bg-white rounded-lg border border-border p-6 hover:shadow-lg transition-shadow group">
      <div className="flex items-start justify-between mb-4">
        <div className="w-12 h-12 rounded-lg bg-gray-200 flex items-center justify-center text-2xl">
          📚
        </div>
      </div>

      <h3 className="text-lg font-semibold text-foreground mb-2">
        {kb.name}
      </h3>
      <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
        {kb.description || ''}
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <ViaBadge
          via={kb.via}
          viaPrincipalDisplayName={kb.viaPrincipalDisplayName}
          viaPrincipalId={kb.viaPrincipalId}
        />
        <PermissionBadge permission={kb.permission} />
      </div>

      <button
        onClick={() => onOpenKB?.(kb)}
        className="w-full px-3 py-1.5 text-sm bg-white hover:bg-gray-50 text-gray-700 font-medium rounded-md border border-gray-300 transition-colors"
      >
        {kb.permission === 'write' ? 'Manage' : 'View'}
      </button>
    </div>
  );
}
