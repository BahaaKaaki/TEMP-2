/**
 * MySessionsView — flat list of all chat sessions across the user's
 * workflows, plus a static "Projects" sidebar (Figma 142:1364).
 *
 * Layout (1920×1080 reference):
 *   ┌──────────── Top bar (rendered by ApexShell) ─────────────┐
 *   │ ┌── Left panel ──┐ ┌────── Main content ──────────────┐  │
 *   │ │ All projects   │ │ "All projects" title             │  │
 *   │ │ Projects list  │ │ Search bar  + filter pill        │  │
 *   │ │ + New project  │ │ Sessions list (chat items)       │  │
 *   │ │ Tools list     │ │                                    │  │
 *   │ └────────────────┘ └────────────────────────────────────┘  │
 *   │ x:24, w:281, top:144  x:329, y:144, w:1539                 │
 *   └────────────────────────────────────────────────────────────┘
 *
 * Per the user's answers:
 *   - Sessions are aggregated from the existing per-workflow API by
 *     looping over the workflows the user has access to. We sort by
 *     last_used desc.
 *   - The Projects list on the left is fully static dummy data.
 *   - The Tools list on the left is grouped from real session data —
 *     workflows the user has actually chatted with, sorted by usage.
 *   - Status badges are deferred ("forget about it now") — we render
 *     a simple time stamp on the right instead.
 */

import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { useWorkflow } from '../../context/WorkflowContext';
import { listAllMySessions, getWorkflow, toggleSessionPin, API_BASE_URL } from '../../api/client';
import {
  listProjects,
  createProject,
  updateProject,
  deleteProject,
  addSessionToProject,
  removeSessionFromProject,
} from '../../api/project-client';
import { safeError } from '../../utils/safeLogger';
import CreateProjectModal from './CreateProjectModal';
import AddSessionToProjectModal from './AddSessionToProjectModal';

import { useFigmaPx } from '../builder/useFigmaScale';
import {
  COLOR,
  FONT,
  SEARCH,
  SESSIONS_PANEL,
  CHAT_ITEM,
  LAYOUT,
  SHELL_SECONDARY_BUTTON,
  applyShellSecondaryButtonHover,
  shellSecondaryButtonStyle,
  colorForName,
  initialsForName,
} from './apexShellSpec';
import { ApexSessionListLoading, ApexShellEmpty } from './ApexShellStates';
import AppIcon from '../ui/AppIcon';

// Static projects removed — now loaded from API.

function formatRelative(timestamp) {
  if (!timestamp) return '';
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();
  if (sameDay) return `Today · ${time}`;
  if (isYesterday) return `Yesterday · ${time}`;
  const month = d.toLocaleString([], { month: 'short' });
  const day = d.getDate();
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

// ────── Left panel ──────────────────────────────────────────────────────
function LeftPanelItem({ label, iconUrl, count, active, onClick }) {
  const { px } = useFigmaPx();
  const [hover, setHover] = useState(false);
  const bg = active
    ? SESSIONS_PANEL.itemActiveBg
    : hover
    ? SESSIONS_PANEL.itemHoverBg
    : 'transparent';
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="flex items-center justify-between"
      style={{
        width: '100%',
        height: px(SESSIONS_PANEL.itemHeight),
        paddingLeft: px(SESSIONS_PANEL.itemPaddingX),
        paddingRight: px(SESSIONS_PANEL.itemPaddingX),
        borderRadius: px(SESSIONS_PANEL.itemRadius),
        border: active ? `1px solid ${SESSIONS_PANEL.itemActiveBorder}` : '1px solid transparent',
        backgroundColor: bg,
        color: active ? COLOR.white : COLOR.medium,
        fontFamily: FONT.family,
        fontSize: px(FONT.body2.size),
        lineHeight: `${px(FONT.body2.height)}px`,
        fontWeight: 400,
        textAlign: 'left',
        cursor: 'pointer',
        transition: 'background-color 150ms, border-color 150ms',
      }}
    >
      <span
        style={{
          flex: '1 1 0',
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          display: 'flex',
          alignItems: 'center',
          gap: px(6),
        }}
      >
        {iconUrl && <img src={`${API_BASE_URL}${iconUrl}`} alt="" style={{ flexShrink: 0, width: px(16), height: px(16), borderRadius: px(4), objectFit: 'cover' }} />}
        {label}
      </span>
      {count != null && (
        <span
          className="flex items-center justify-center"
          style={{
            backgroundColor: active ? COLOR.rose : COLOR.darker,
            color: active ? COLOR.white : COLOR.light,
            paddingLeft: px(6),
            paddingRight: px(6),
            paddingTop: px(3),
            paddingBottom: px(3),
            borderRadius: 100,
            minWidth: px(20),
            fontSize: px(12),
            lineHeight: `${px(14)}px`,
            fontWeight: 600,
            marginLeft: px(8),
            flexShrink: 0,
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
}

function LeftPanel({
  totalCount,
  selectedFilter,
  onSelectFilter,
  recentTools,
  projects,
  onNewProject,
  onRenameProject,
  onDeleteProject,
}) {
  const { px } = useFigmaPx();
  const [ctxMenu, setCtxMenu] = useState(null); // { id, x, y }
  const [renaming, setRenaming] = useState(null); // project id being renamed
  const [renameVal, setRenameVal] = useState('');
  const ctxRef = useRef(null);

  // Close context menu on outside click
  useEffect(() => {
    if (!ctxMenu) return;
    const close = (e) => {
      if (ctxRef.current && !ctxRef.current.contains(e.target)) setCtxMenu(null);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [ctxMenu]);

  const handleContextMenu = (e, projectId) => {
    e.preventDefault();
    setCtxMenu({ id: projectId, x: e.clientX, y: e.clientY });
  };

  const startRename = (p) => {
    setCtxMenu(null);
    setRenaming(p.id);
    setRenameVal(p.name);
  };

  const commitRename = (id) => {
    if (renameVal.trim() && renameVal.trim() !== (projects.find((p) => p.id === id)?.name || '')) {
      onRenameProject(id, renameVal.trim());
    }
    setRenaming(null);
  };

  return (
    <aside
      style={{
        width: px(SESSIONS_PANEL.width),
        flexShrink: 0,
        padding: px(SESSIONS_PANEL.paddingX),
        borderRadius: px(SESSIONS_PANEL.radius),
        backgroundColor: SESSIONS_PANEL.bg,
        height: 'fit-content',
        maxHeight: '100%',
        overflowY: 'auto',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: px(SESSIONS_PANEL.itemGap) }}>
        <LeftPanelItem
          label="All Sessions"
          count={totalCount}
          active={selectedFilter === 'all'}
          onClick={() => onSelectFilter('all')}
        />
      </div>

      <div style={{ marginTop: px(24) }}>
        <h3
          style={{
            color: COLOR.white,
            fontSize: px(FONT.body1Bold.size),
            lineHeight: `${px(FONT.body1Bold.height)}px`,
            fontWeight: FONT.body1Bold.weight,
            fontFamily: FONT.family,
            margin: 0,
            marginBottom: px(12),
            paddingLeft: px(SESSIONS_PANEL.itemPaddingX),
          }}
        >
          Projects
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: px(SESSIONS_PANEL.itemGap) }}>
        <button
            type="button"
            style={shellSecondaryButtonStyle(px, { width: '100%', marginTop: px(8) })}
            onClick={onNewProject}
            onMouseEnter={(e) => applyShellSecondaryButtonHover(e.currentTarget, true)}
            onMouseLeave={(e) => applyShellSecondaryButtonHover(e.currentTarget, false)}
          >
            <AppIcon name="plus" size={px(20)} color={SHELL_SECONDARY_BUTTON.icon} weight="bold" />
            New project
          </button>
          {projects.map((p) => (
            <div key={p.id} onContextMenu={(e) => handleContextMenu(e, p.id)}>
              {renaming === p.id ? (
                <input
                  autoFocus
                  type="text"
                  value={renameVal}
                  onChange={(e) => setRenameVal(e.target.value)}
                  onBlur={() => commitRename(p.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(p.id);
                    if (e.key === 'Escape') setRenaming(null);
                  }}
                  style={{
                    width: '100%',
                    height: px(SESSIONS_PANEL.itemHeight),
                    paddingLeft: px(SESSIONS_PANEL.itemPaddingX),
                    paddingRight: px(SESSIONS_PANEL.itemPaddingX),
                    borderRadius: px(SESSIONS_PANEL.itemRadius),
                    border: `1px solid ${COLOR.rose}`,
                    backgroundColor: SESSIONS_PANEL.itemActiveBg,
                    color: COLOR.white,
                    fontFamily: FONT.family,
                    fontSize: px(FONT.body2.size),
                    outline: 'none',
                  }}
                />
              ) : (
                <LeftPanelItem
                  label={p.name}
                  count={p.sessionCount}
                  active={selectedFilter === `project:${p.id}`}
                  onClick={() => onSelectFilter(`project:${p.id}`)}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      {recentTools.length > 0 && (
        <div style={{ marginTop: px(24) }}>
          <h3
            style={{
              color: COLOR.white,
              fontSize: px(FONT.body1Bold.size),
              lineHeight: `${px(FONT.body1Bold.height)}px`,
              fontWeight: FONT.body1Bold.weight,
              fontFamily: FONT.family,
              margin: 0,
              marginBottom: px(12),
              paddingLeft: px(SESSIONS_PANEL.itemPaddingX),
            }}
          >
            Tools
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: px(SESSIONS_PANEL.itemGap) }}>
            {recentTools.slice(0, 6).map((t) => (
              <LeftPanelItem
                key={t.id}
                label={t.name}
                iconUrl={t.icon?.startsWith('/') ? t.icon : undefined}
                count={t.count}
                active={selectedFilter === `tool:${t.id}`}
                onClick={() => onSelectFilter(`tool:${t.id}`)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Context menu for projects */}
      {ctxMenu && (
        <div
          ref={ctxRef}
          style={{
            position: 'fixed',
            left: ctxMenu.x,
            top: ctxMenu.y,
            zIndex: 1000,
            minWidth: 140,
            backgroundColor: '#1a1a1a',
            border: '1px solid #464646',
            borderRadius: 8,
            padding: 4,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
          }}
        >
          <button
            type="button"
            onClick={() => startRename(projects.find((p) => p.id === ctxMenu.id))}
            style={{
              display: 'block',
              width: '100%',
              padding: '8px 12px',
              textAlign: 'left',
              backgroundColor: 'transparent',
              border: 'none',
              color: '#ffffff',
              fontSize: 14,
              borderRadius: 6,
              cursor: 'pointer',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#2a2a2a'; }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
          >
            Rename
          </button>
          <button
            type="button"
            onClick={() => {
              const id = ctxMenu.id;
              setCtxMenu(null);
              onDeleteProject(id);
            }}
            style={{
              display: 'block',
              width: '100%',
              padding: '8px 12px',
              textAlign: 'left',
              backgroundColor: 'transparent',
              border: 'none',
              color: '#d93854',
              fontSize: 14,
              borderRadius: 6,
              cursor: 'pointer',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#2a2a2a'; }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
          >
            Delete
          </button>
        </div>
      )}
    </aside>
  );
}

// ────── Chat row ─────────────────────────────────────────────────────────
function ChatItem({ session, workflow, onClick, onTogglePin, projects, onAssignProject }) {
  const { px } = useFigmaPx();
  const [hover, setHover] = useState(false);
  const toolName = workflow?.marketplaceName || workflow?.name || 'Workflow';
  const sessionTitle = session.name || session.title || 'Untitled session';
  const summary = session.description || session.summary || '';
  const time = formatRelative(
    session.lastAccessedAt ||
      session.lastMessageAt ||
      session.updatedAt ||
      session.createdAt,
  );
  const iconColor = colorForName(toolName);
  const iconText = initialsForName(toolName);
  const pinned = !!session.isPinned;

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="flex items-center"
      style={{
        width: '100%',
        height: px(CHAT_ITEM.height),
        paddingLeft: px(CHAT_ITEM.paddingX),
        paddingRight: px(CHAT_ITEM.paddingX),
        paddingTop: px(CHAT_ITEM.paddingY),
        paddingBottom: px(CHAT_ITEM.paddingY),
        gap: px(CHAT_ITEM.gap),
        borderBottom: `1px solid ${CHAT_ITEM.borderColor}`,
        backgroundColor: hover ? 'rgba(255, 255, 255, 0.03)' : 'transparent',
        textAlign: 'left',
        cursor: 'pointer',
        border: 'none',
        borderBottomWidth: 1,
        borderBottomStyle: 'solid',
        borderBottomColor: CHAT_ITEM.borderColor,
        transition: 'background-color 150ms',
        position: 'relative',
      }}
    >
      {/* Tool icon — uploaded image if set, otherwise coloured initials */}
      {workflow?.icon && workflow.icon.startsWith('/') ? (
        <img
          src={`${API_BASE_URL}${workflow.icon}`}
          alt=""
          style={{
            width: px(CHAT_ITEM.iconWidth),
            height: px(CHAT_ITEM.iconSize),
            borderRadius: px(CHAT_ITEM.iconRadius),
            flexShrink: 0,
            objectFit: 'cover',
          }}
        />
      ) : (
        <div
          className="flex items-center justify-center"
          style={{
            width: px(CHAT_ITEM.iconWidth),
            height: px(CHAT_ITEM.iconSize),
            borderRadius: px(CHAT_ITEM.iconRadius),
            flexShrink: 0,
            backgroundColor: iconColor,
            color: COLOR.white,
            fontFamily: FONT.family,
            fontSize: px(28),
            fontWeight: 700,
            letterSpacing: 0.5,
          }}
        >
          {iconText}
        </div>
      )}

      {/* Title block */}
      <div className="flex flex-col" style={{ flex: '1 1 0', minWidth: 0, gap: px(4) }}>
        <span
          style={{
            color: COLOR.medium,
            fontFamily: FONT.family,
            fontSize: px(FONT.body3.size),
            lineHeight: `${px(FONT.body3.height)}px`,
            fontWeight: 400,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {toolName}
        </span>
        <span
          style={{
            color: COLOR.white,
            fontFamily: FONT.family,
            fontSize: px(FONT.body2Bold.size),
            lineHeight: `${px(FONT.body2Bold.height)}px`,
            fontWeight: FONT.body2Bold.weight,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {sessionTitle}
        </span>
        {summary && (
          <span
            style={{
              color: COLOR.white,
              fontFamily: FONT.family,
              fontSize: px(FONT.body2.size),
              lineHeight: `${px(FONT.body2.height)}px`,
              fontWeight: 400,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              opacity: 0.85,
            }}
          >
            {summary}
          </span>
        )}
      </div>

      {/* Right column — pin + project + timestamp */}
      <div
        className="flex flex-col items-end justify-start"
        style={{ flexShrink: 0, gap: px(8) }}
      >
        <span
          style={{
            color: COLOR.medium,
            fontFamily: FONT.family,
            fontSize: px(FONT.body3.size),
            lineHeight: `${px(FONT.body3.height)}px`,
            fontWeight: 400,
            whiteSpace: 'nowrap',
          }}
        >
          {time}
        </span>
        <div className="flex items-center" style={{ gap: px(4) }}>
          {/* Project assign button */}
          <ProjectAssignDropdown
            session={session}
            projects={projects}
            onAssign={onAssignProject}
            hover={hover}
            px={px}
          />
          {/* Pin button */}
          <span
            role="button"
            tabIndex={0}
            title={pinned ? 'Unpin session' : 'Pin session'}
            onClick={(e) => {
              e.stopPropagation();
              onTogglePin?.(session);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation();
                e.preventDefault();
                onTogglePin?.(session);
              }
            }}
            style={{
              width: px(24),
              height: px(24),
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: pinned ? 1 : (hover ? 0.6 : 0),
              transition: 'opacity 150ms',
            }}
          >
            <svg
              width={px(16)} height={px(16)}
              viewBox="0 0 24 24"
              fill={pinned ? 'currentColor' : 'none'}
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ color: pinned ? '#3b82f6' : COLOR.medium }}
            >
              <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
          </span>
        </div>
      </div>
    </button>
  );
}

// ────── Project assign dropdown on each session row ──────────────────────
function ProjectAssignDropdown({ session, projects, onAssign, hover, px }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const assigned = session.projectId;
  const hasProject = !!assigned;

  useEffect(() => {
    if (!open) return;
    const close = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <span ref={ref} style={{ position: 'relative' }}>
      <span
        role="button"
        tabIndex={0}
        title={hasProject ? 'Change project' : 'Add to project'}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.stopPropagation();
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        style={{
          width: px(24),
          height: px(24),
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: hasProject ? 1 : (hover ? 0.6 : 0),
          transition: 'opacity 150ms',
        }}
      >
        <svg
          width={px(16)} height={px(16)}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color: hasProject ? '#d93854' : COLOR.medium }}
        >
          <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
        </svg>
      </span>

      {open && (
        <div
          style={{
            position: 'absolute',
            right: 0,
            top: px(28),
            zIndex: 1000,
            minWidth: 180,
            maxHeight: 260,
            overflowY: 'auto',
            backgroundColor: '#1a1a1a',
            border: '1px solid #464646',
            borderRadius: 8,
            padding: 4,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
          }}
        >
          {projects.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onAssign(session.id, p.id);
                setOpen(false);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                padding: '8px 12px',
                textAlign: 'left',
                backgroundColor: assigned === p.id ? 'rgba(217,56,84,0.15)' : 'transparent',
                border: 'none',
                color: '#ffffff',
                fontSize: 13,
                borderRadius: 6,
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = assigned === p.id ? 'rgba(217,56,84,0.2)' : '#2a2a2a'; }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = assigned === p.id ? 'rgba(217,56,84,0.15)' : 'transparent'; }}
            >
              {assigned === p.id && <span style={{ color: '#d93854' }}>&#10003;</span>}
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
            </button>
          ))}
          {assigned && (
            <>
              <div style={{ height: 1, backgroundColor: '#464646', margin: '4px 0' }} />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onAssign(session.id, null);
                  setOpen(false);
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  padding: '8px 12px',
                  textAlign: 'left',
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: '#b5b5b5',
                  fontSize: 13,
                  borderRadius: 6,
                  cursor: 'pointer',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#2a2a2a'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                Remove from project
              </button>
            </>
          )}
          {projects.length === 0 && (
            <div style={{ padding: '8px 12px', color: '#6b6b6b', fontSize: 13 }}>
              No projects yet
            </div>
          )}
        </div>
      )}
    </span>
  );
}

// ────── View ─────────────────────────────────────────────────────────────
export default function MySessionsView() {
  const { px } = useFigmaPx();
  const { dispatch, ACTIONS } = useWorkflow();
  const [items, setItems] = useState([]); // [{ session, workflow }]
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');

  // Project state
  const [projects, setProjects] = useState([]);
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [showAddSessions, setShowAddSessions] = useState(false);
  const [addSessionsTarget, setAddSessionsTarget] = useState(null); // project obj

  // Load sessions + projects together
  const loadData = useCallback(async () => {
    try {
      setLoading(true);

      const [sessionsRes, projRes] = await Promise.all([
        listAllMySessions(200).catch(() => []),
        listProjects().catch(() => ({ items: [] })),
      ]);

      setProjects(projRes?.items || []);

      const rows = Array.isArray(sessionsRes) ? sessionsRes : [];
      const flat = rows.map((r) => ({
        session: r.session,
        workflow: {
          id: r.session.workflowId,
          name: r.workflowName || 'Workflow',
          marketplaceName: r.workflowMarketplaceName || null,
          icon: r.workflowIcon || null,
        },
      }));
      setItems(flat);
    } catch (e) {
      setError(e.message || 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (projects.length === 0 && filter.startsWith('project:')) {
      setFilter('all');
    }
  }, [projects.length, filter]);

  // Build the "Tools" left panel from real data
  const recentTools = useMemo(() => {
    const map = new Map();
    for (const { workflow } of items) {
      if (!workflow?.id) continue;
      const existing = map.get(workflow.id);
      if (existing) {
        existing.count += 1;
      } else {
        map.set(workflow.id, {
          id: workflow.id,
          name: workflow.marketplaceName || workflow.name || 'Workflow',
          icon: workflow.icon || null,
          count: 1,
        });
      }
    }
    return Array.from(map.values()).sort((a, b) => b.count - a.count);
  }, [items]);

  const filtered = useMemo(() => {
    let list = items;
    if (filter.startsWith('tool:')) {
      const id = filter.slice(5);
      list = list.filter(({ workflow }) => workflow?.id === id);
    }
    if (filter.startsWith('project:')) {
      const projId = filter.slice(8);
      list = list.filter(({ session }) => session.projectId === projId);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(({ session, workflow }) =>
        (session.name || '').toLowerCase().includes(q) ||
        (workflow?.name || '').toLowerCase().includes(q) ||
        (workflow?.marketplaceName || '').toLowerCase().includes(q),
      );
    }
    return list.sort((a, b) => {
      const ap = !!a.session.isPinned;
      const bp = !!b.session.isPinned;
      if (ap !== bp) return ap ? -1 : 1;
      return 0;
    });
  }, [items, filter, search]);

  const handleOpen = async ({ session, workflow }) => {
    let fullWorkflow = workflow;
    try {
      fullWorkflow = await getWorkflow(workflow.id);
    } catch {
      // Fall back to the summary we already have
    }
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: {
        view: 'chat',
        selectedWorkflow: fullWorkflow,
        selectedSession: session,
      },
    });
  };

  const handleToggleSessionPin = async (session) => {
    try {
      await toggleSessionPin(session.id, !session.isPinned);
      setItems((prev) =>
        prev.map((item) =>
          item.session.id === session.id
            ? { ...item, session: { ...item.session, isPinned: !item.session.isPinned } }
            : item,
        ),
      );
    } catch (e) {
      safeError('Failed to toggle session pin:', e);
    }
  };

  // ── Project CRUD handlers ──────────────────────────────────────────────

  const handleCreateProject = async ({ name, description }) => {
    const created = await createProject({ name, description });
    setProjects((prev) => [created, ...prev]);
  };

  const handleRenameProject = async (projectId, newName) => {
    try {
      const updated = await updateProject(projectId, { name: newName });
      setProjects((prev) => prev.map((p) => (p.id === projectId ? updated : p)));
    } catch (e) {
      safeError('Failed to rename project:', e);
    }
  };

  const handleDeleteProject = async (projectId) => {
    try {
      await deleteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
      // Unassign locally
      setItems((prev) =>
        prev.map((item) =>
          item.session.projectId === projectId
            ? { ...item, session: { ...item.session, projectId: null } }
            : item,
        ),
      );
      if (filter === `project:${projectId}`) setFilter('all');
    } catch (e) {
      safeError('Failed to delete project:', e);
    }
  };

  const handleAssignProject = async (sessionId, projectId) => {
    try {
      const currentProjectId = items.find((i) => i.session.id === sessionId)?.session?.projectId;
      if (projectId) {
        await addSessionToProject(projectId, sessionId);
      } else if (currentProjectId) {
        await removeSessionFromProject(currentProjectId, sessionId);
      }
      setItems((prev) =>
        prev.map((item) =>
          item.session.id === sessionId
            ? { ...item, session: { ...item.session, projectId } }
            : item,
        ),
      );
      // Refresh project counts
      try {
        const projRes = await listProjects();
        setProjects(projRes?.items || []);
      } catch { /* non-critical */ }
    } catch (e) {
      safeError('Failed to assign session to project:', e);
    }
  };

  const handleAddSessionsToProject = async (sessionIds) => {
    if (!addSessionsTarget) return;
    for (const sid of sessionIds) {
      try {
        await addSessionToProject(addSessionsTarget.id, sid);
        setItems((prev) =>
          prev.map((item) =>
            item.session.id === sid
              ? { ...item, session: { ...item.session, projectId: addSessionsTarget.id } }
              : item,
          ),
        );
      } catch (e) {
        safeError('Failed to add session to project:', e);
      }
    }
    try {
      const projRes = await listProjects();
      setProjects(projRes?.items || []);
    } catch { /* non-critical */ }
  };

  // ── Derived ────────────────────────────────────────────────────────────

  const activeProject = filter.startsWith('project:')
    ? projects.find((p) => p.id === filter.slice(8))
    : null;

  const canAddSessionToProject = Boolean(activeProject && projects.length > 0);

  const filterTitle =
    filter === 'all'
      ? 'All Sessions'
      : filter.startsWith('tool:')
      ? recentTools.find((t) => `tool:${t.id}` === filter)?.name || 'Tool'
      : activeProject?.name || 'Project';

  return (
    <div
      className="w-full overflow-hidden"
      style={{
        height: '100%',
        backgroundColor: LAYOUT.pageBg,
        color: COLOR.white,
        fontFamily: FONT.family,
      }}
    >
      <div
        className="flex"
        style={{
          height: '100%',
          paddingLeft: px(LAYOUT.sessions.panelLeft),
          paddingRight: px(LAYOUT.sessions.panelLeft),
          paddingTop: px(0),
          paddingBottom: px(24),
          gap: px(24),
        }}
      >
        <LeftPanel
          totalCount={items.length}
          selectedFilter={filter}
          onSelectFilter={setFilter}
          recentTools={recentTools}
          projects={projects}
          onNewProject={() => setShowCreateProject(true)}
          onRenameProject={handleRenameProject}
          onDeleteProject={handleDeleteProject}
        />

        <main
          style={{
            flex: '1 1 0',
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: px(24),
            overflow: 'hidden',
          }}
        >
          <div className="flex items-center justify-between">
            <h1
              style={{
                color: COLOR.white,
                fontSize: px(FONT.sub2Bold.size),
                lineHeight: `${px(FONT.sub2Bold.height)}px`,
                fontWeight: FONT.sub2Bold.weight,
                margin: 0,
              }}
            >
              {filterTitle}
            </h1>
            {canAddSessionToProject && (
              <button
                type="button"
                onClick={() => {
                  setAddSessionsTarget(activeProject);
                  setShowAddSessions(true);
                }}
                style={shellSecondaryButtonStyle(px, { height: px(40), paddingLeft: px(12), paddingRight: px(14) })}
                onMouseEnter={(e) => applyShellSecondaryButtonHover(e.currentTarget, true)}
                onMouseLeave={(e) => applyShellSecondaryButtonHover(e.currentTarget, false)}
              >
                <AppIcon name="plus" size={px(18)} color={SHELL_SECONDARY_BUTTON.icon} weight="bold" />
                Add session
              </button>
            )}
          </div>

          {/* Search row */}
          <div className="flex items-center" style={{ gap: px(16) }}>
            <div style={{ flex: '1 1 0', minWidth: 0, maxWidth: `min(${px(LAYOUT.storefront.leftWidth)}px, 60vw)` }}>
              <SearchInputInline value={search} onChange={setSearch} placeholder="Find a session" />
            </div>
            <button
              type="button"
              className="flex items-center justify-center"
              style={{
                width: px(48),
                height: px(48),
                borderRadius: px(SEARCH.radius),
                backgroundColor: SEARCH.bg,
                border: `1px solid ${SEARCH.border}`,
                color: COLOR.medium,
                cursor: 'pointer',
                flexShrink: 0,
                transition: 'background-color 200ms ease, border-color 200ms ease, transform 200ms ease',
              }}
              title="Filter & sort"
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
                e.currentTarget.style.borderColor = COLOR.dark;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = SEARCH.bg;
                e.currentTarget.style.borderColor = SEARCH.border;
              }}
              onMouseDown={(e) => {
                e.currentTarget.style.transform = 'scale(0.98)';
              }}
              onMouseUp={(e) => {
                e.currentTarget.style.transform = 'scale(1)';
              }}
            >
              <AppIcon name="filter" size={px(24)} color={COLOR.medium} weight="regular" />
            </button>
          </div>

          {/* List */}
          <div className="overflow-y-auto" style={{ flex: '1 1 0' }}>
            {loading && <ApexSessionListLoading />}
            {error && !loading && (
              <div style={{ padding: px(32), color: COLOR.rose }}>{error}</div>
            )}
            {!loading && !error && filtered.length === 0 && (
              <div style={{ padding: px(32) }}>
                <ApexShellEmpty
                  title={
                    filter.startsWith('project:')
                      ? 'No sessions in this project'
                      : items.length === 0
                      ? 'No sessions yet'
                      : 'No matching sessions'
                  }
                  description={
                    filter.startsWith('project:')
                      ? canAddSessionToProject
                        ? 'Click "+ Add session" to attach chats to this project.'
                        : 'Create a project in the sidebar to organize your chats.'
                      : items.length === 0
                      ? 'Open a tool from the Storefront to start your first chat.'
                      : 'Try a different search term or clear the filter.'
                  }
                />
              </div>
            )}
            {!loading && filtered.map(({ session, workflow }) => (
              <ChatItem
                key={session.id}
                session={session}
                workflow={workflow}
                onClick={() => handleOpen({ session, workflow })}
                onTogglePin={handleToggleSessionPin}
                projects={projects}
                onAssignProject={handleAssignProject}
              />
            ))}
          </div>
        </main>
      </div>

      {/* Modals */}
      <CreateProjectModal
        isOpen={showCreateProject}
        onClose={() => setShowCreateProject(false)}
        onCreated={handleCreateProject}
      />
      <AddSessionToProjectModal
        isOpen={showAddSessions}
        onClose={() => setShowAddSessions(false)}
        sessions={items}
        projectId={addSessionsTarget?.id}
        projectName={addSessionsTarget?.name}
        onConfirm={handleAddSessionsToProject}
      />
    </div>
  );
}

// Inline copy of the search input so we don't import a circular file.
function SearchInputInline({ value, onChange, placeholder }) {
  const { px } = useFigmaPx();
  const [focused, setFocused] = useState(false);
  return (
    <div
      className="kb-inline-search flex items-center"
      style={{
        width: '100%',
        height: px(SEARCH.height),
        borderRadius: px(SEARCH.radius),
        paddingLeft: px(SEARCH.paddingX),
        paddingRight: px(SEARCH.paddingX),
        gap: px(SEARCH.gap),
        backgroundColor: SEARCH.bg,
        border: `1px solid ${focused ? COLOR.rose : SEARCH.border}`,
      }}
    >
      <AppIcon name="search" size={px(SEARCH.iconSize)} color={SEARCH.iconColor} weight="regular" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          flex: 1,
          minWidth: 0,
          backgroundColor: 'transparent',
          border: 'none',
          outline: 'none',
          color: SEARCH.text,
          fontFamily: FONT.family,
          fontSize: px(FONT.body2.size),
          lineHeight: `${px(FONT.body2.height)}px`,
        }}
      />
    </div>
  );
}
