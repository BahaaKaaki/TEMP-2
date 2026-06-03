/**
 * MyToolsView — three flat sections: Workflows, Knowledge Bases,
 * Shared with me (Figma 157:3499).
 *
 * Each section collapses to the first 8 cards by default; "See more"
 * expands and search bypasses the collapse. The 3-dot menu on owned
 * cards exposes Pin, Share, Duplicate (workflows), and Delete. Shared
 * items have no menu. Create buttons live at section level.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useWorkflow } from '../../context/WorkflowContext';
import { useAuth } from '../../context/AuthContext';
import {
  listWorkflows,
  createChatSession,
  deleteWorkflow,
  duplicateWorkflow,
  toggleWorkflowPin,
  API_BASE_URL,
} from '../../api/client';
import {
  listKnowledgeBases,
  deleteKnowledgeBase,
  createKnowledgeBase,
  toggleKBPin,
} from '../../api/kb-client';
import {
  listSharedWithMeWorkflows,
  listSharedWithMeKnowledgeBases,
} from '../../api/sharing';
import { safeError } from '../../utils/safeLogger';
import ShareDialog from '../sharing/ShareDialog';
import ConfirmModal from '../ui/ConfirmModal';
import AlertModal from '../ui/AlertModal';
import { useFigmaPx } from '../builder/useFigmaScale';
import { COLOR, FONT, SEARCH, TOOL_CARD, LAYOUT, colorForName, initialsForName } from './apexShellSpec';
import { ApexToolsGridLoading, ApexShellEmpty } from './ApexShellStates';
import AppIcon from '../ui/AppIcon';

const COLLAPSE_LIMIT = 8;

function asArray(data, ...keys) {
  if (Array.isArray(data)) return data;
  for (const key of keys) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
}

function formatDate(timestamp) {
  if (!timestamp) return '';
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return '';
  const month = d.toLocaleString([], { month: 'short' });
  const day = String(d.getDate()).padStart(2, '0');
  const year = d.getFullYear();
  return `${month} ${day}, ${year}`;
}

// ────── Avatar stack ─────────────────────────────────────────────────────
function AvatarStack({ people, label }) {
  const { px } = useFigmaPx();
  if (!people?.length && !label) return null;
  return (
    <div
      className="flex items-center"
      style={{
        gap: px(8),
        paddingLeft: px(4),
        paddingRight: px(4),
        paddingTop: px(6),
        paddingBottom: px(6),
      }}
    >
      {people?.length > 0 && (
        <div className="flex items-center" style={{ flexShrink: 0 }}>
          {people.slice(0, 3).map((p, i) => (
            <div
              key={p.id || i}
              className="flex items-center justify-center"
              style={{
                width: px(24),
                height: px(24),
                borderRadius: px(12),
                backgroundColor: colorForName(p.name),
                color: COLOR.white,
                fontFamily: FONT.family,
                fontSize: px(10),
                fontWeight: 600,
                marginLeft: i > 0 ? px(-6) : 0,
                border: `2px solid ${TOOL_CARD.bg}`,
                flexShrink: 0,
              }}
            >
              {initialsForName(p.name)}
            </div>
          ))}
        </div>
      )}
      {label && (
        <span
          style={{
            flex: '1 1 0',
            minWidth: 0,
            color: COLOR.medium,
            fontFamily: FONT.family,
            fontSize: px(FONT.body3.size),
            lineHeight: `${px(FONT.body3.height)}px`,
            fontWeight: 400,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {label}
        </span>
      )}
    </div>
  );
}

// ────── 3-dot menu ───────────────────────────────────────────────────────
function CardMenu({ items }) {
  const { px } = useFigmaPx();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const triggerRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const handleOpen = (e) => {
    e.stopPropagation();
    if (triggerRef.current) {
      const r = triggerRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
    }
    setOpen(true);
  };

  if (!items?.length) return null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label="More options"
        onClick={handleOpen}
        style={{
          position: 'absolute',
          top: px(16),
          right: px(16),
          width: px(28),
          height: px(28),
          backgroundColor: open ? 'rgba(255,255,255,0.06)' : 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: 0,
          borderRadius: px(8),
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 2,
          transition: 'background-color 150ms',
        }}
        onMouseEnter={(e) => {
          if (!open) e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.04)';
        }}
        onMouseLeave={(e) => {
          if (!open) e.currentTarget.style.backgroundColor = 'transparent';
        }}
      >
        <AppIcon name="moreVertical" size={px(20)} color={COLOR.medium} weight="bold" />
      </button>
      {open && pos &&
        createPortal(
          <>
            <div
              className="fixed inset-0"
              style={{ zIndex: 200 }}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
              }}
            />
            <div
              role="menu"
              style={{
                position: 'fixed',
                top: pos.top,
                right: pos.right,
                minWidth: 200,
                background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
                border: `1px solid ${COLOR.darker}`,
                borderRadius: 12,
                padding: 6,
                zIndex: 201,
                fontFamily: FONT.family,
                boxShadow: '0 8px 28px rgba(0,0,0,0.6)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    item.onClick?.();
                  }}
                  className="w-full flex items-center text-left"
                  style={{
                    gap: 10,
                    padding: '10px 12px',
                    borderRadius: 8,
                    backgroundColor: 'transparent',
                    color: item.danger ? COLOR.rose : COLOR.white,
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 14,
                    lineHeight: '20px',
                    fontWeight: 500,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = item.danger
                      ? 'rgba(217, 56, 84, 0.12)'
                      : '#2a2a2a';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                >
                  {item.icon && (
                    <AppIcon
                      src={item.icon}
                      size={18}
                      color={item.danger ? COLOR.rose : COLOR.medium}
                      weight="regular"
                    />
                  )}
                  {item.label}
                </button>
              ))}
            </div>
          </>,
          document.body,
        )}
    </>
  );
}

// ────── Card ─────────────────────────────────────────────────────────────
function ToolCard({
  title,
  description,
  date,
  kind, // 'workflow' | 'kb'
  showTag = true,
  people,
  shareLabel,
  primary, // { label, icon, onClick, busy }
  secondary, // { label, icon, onClick } | null
  menuItems,
  iconUrl, // optional uploaded image URL for the card
}) {
  const { px } = useFigmaPx();

  return (
    <div
      style={{
        width: '100%',
        height: px(TOOL_CARD.height),
        backgroundColor: TOOL_CARD.bg,
        borderRadius: px(TOOL_CARD.radius),
        padding: px(TOOL_CARD.padding),
        display: 'flex',
        flexDirection: 'column',
        gap: px(TOOL_CARD.gap),
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <CardMenu items={menuItems} />

      <div className="flex flex-col" style={{ flex: '1 1 0', gap: px(8), minHeight: 0 }}>
        {showTag && (
          <span
            style={{
              fontFamily: FONT.family,
              fontSize: px(11),
              lineHeight: `${px(14)}px`,
              fontWeight: 700,
              letterSpacing: 0.4,
              color: kind === 'kb' ? '#16c559' : COLOR.rose,
              textTransform: 'uppercase',
            }}
          >
            {kind === 'kb' ? 'Knowledge Base' : 'Workflow'}
          </span>
        )}

        <div className="flex items-center" style={{ gap: px(8), paddingRight: px(36) }}>
          {iconUrl && (
            <img
              src={`${API_BASE_URL}${iconUrl}`}
              alt=""
              style={{
                width: px(24),
                height: px(24),
                borderRadius: px(6),
                objectFit: 'cover',
                flexShrink: 0,
              }}
            />
          )}
          <p
            style={{
              color: COLOR.white,
              fontFamily: FONT.family,
              fontSize: px(FONT.body1Bold.size),
              lineHeight: `${px(FONT.body1Bold.height)}px`,
              fontWeight: FONT.body1Bold.weight,
              margin: 0,
              overflow: 'hidden',
              display: '-webkit-box',
              WebkitLineClamp: 1,
              WebkitBoxOrient: 'vertical',
            }}
            title={title}
          >
            {title}
          </p>
        </div>
        <p
          style={{
            color: COLOR.medium,
            fontFamily: FONT.family,
            fontSize: px(FONT.body2.size),
            lineHeight: `${px(FONT.body2.height)}px`,
            fontWeight: FONT.body2.weight,
            margin: 0,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
          title={description}
        >
          {description || '—'}
        </p>
        <span
          style={{
            color: COLOR.dark,
            fontFamily: FONT.family,
            fontSize: px(FONT.body3.size),
            lineHeight: `${px(FONT.body3.height)}px`,
          }}
        >
          {date || '—'}
        </span>
      </div>

      {people?.length > 0 && <AvatarStack people={people} label={shareLabel} />}

      <div className="flex" style={{ gap: px(TOOL_CARD.buttons.gap), width: '100%' }}>
        {primary && (
          <button
            type="button"
            onClick={primary.onClick}
            disabled={primary.busy}
            className="flex items-center justify-center"
            style={{
              flex: '1 1 0',
              minWidth: 0,
              height: px(TOOL_CARD.buttons.height),
              paddingLeft: px(TOOL_CARD.buttons.paddingLeft),
              paddingRight: px(TOOL_CARD.buttons.paddingRight),
              borderRadius: px(TOOL_CARD.buttons.radius),
              backgroundColor: TOOL_CARD.buttons.primary.bg,
              color: TOOL_CARD.buttons.primary.text,
              border: 'none',
              cursor: primary.busy ? 'wait' : 'pointer',
              gap: px(4),
              fontFamily: FONT.family,
              fontSize: px(FONT.pillButton.size),
              lineHeight: `${px(FONT.pillButton.height)}px`,
              fontWeight: FONT.pillButton.weight,
              opacity: primary.busy ? 0.6 : 1,
              transition: 'background-color 150ms',
            }}
            onMouseEnter={(e) => {
              if (!primary.busy) e.currentTarget.style.backgroundColor = TOOL_CARD.buttons.primary.bgHover;
            }}
            onMouseLeave={(e) => {
              if (!primary.busy) e.currentTarget.style.backgroundColor = TOOL_CARD.buttons.primary.bg;
            }}
          >
            {primary.icon && (
              <AppIcon
                src={primary.icon}
                size={px(TOOL_CARD.buttons.iconSize)}
                color={TOOL_CARD.buttons.primary.text}
                weight="bold"
              />
            )}
            {primary.label}
          </button>
        )}

        {secondary && (
          <button
            type="button"
            onClick={secondary.onClick}
            className="flex items-center justify-center"
            style={{
              flex: '1 1 0',
              minWidth: 0,
              height: px(TOOL_CARD.buttons.height),
              paddingLeft: px(TOOL_CARD.buttons.paddingLeft),
              paddingRight: px(TOOL_CARD.buttons.paddingRight),
              borderRadius: px(TOOL_CARD.buttons.radius),
              backgroundColor: TOOL_CARD.buttons.secondary.bg,
              color: TOOL_CARD.buttons.secondary.text,
              border: 'none',
              cursor: 'pointer',
              gap: px(4),
              fontFamily: FONT.family,
              fontSize: px(FONT.pillButton.size),
              lineHeight: `${px(FONT.pillButton.height)}px`,
              fontWeight: FONT.pillButton.weight,
              transition: 'background-color 150ms',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = TOOL_CARD.buttons.secondary.bgHover)}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = TOOL_CARD.buttons.secondary.bg)}
          >
            {secondary.icon && (
              <AppIcon
                src={secondary.icon}
                size={px(TOOL_CARD.buttons.iconSize)}
                color={TOOL_CARD.buttons.secondary.text}
                weight="regular"
              />
            )}
            {secondary.label}
          </button>
        )}
      </div>
    </div>
  );
}

// ────── Section (flat, with count + see more + optional create button) ───
function Section({
  title, count, expanded, onToggle, hasMore,
  emptyMessage, isEmpty, createLabel, onCreate, children,
}) {
  const { px } = useFigmaPx();
  return (
    <section style={{ marginTop: px(LAYOUT.mytools.rowGap) }}>
      <div className="flex items-center" style={{ gap: px(12), marginBottom: px(16) }}>
        <h2
          style={{
            color: COLOR.white,
            fontFamily: FONT.family,
            fontSize: px(FONT.sub2Bold.size),
            lineHeight: `${px(FONT.sub2Bold.height)}px`,
            fontWeight: FONT.sub2Bold.weight,
            margin: 0,
          }}
        >
          {title}
        </h2>
        {count != null && (
          <span
            className="flex items-center justify-center"
            style={{
              backgroundColor: COLOR.darker,
              color: COLOR.light,
              paddingLeft: px(8),
              paddingRight: px(8),
              paddingTop: px(2),
              paddingBottom: px(2),
              borderRadius: 100,
              minWidth: px(22),
              fontSize: px(12),
              lineHeight: `${px(14)}px`,
              fontWeight: 600,
            }}
          >
            {count}
          </span>
        )}
        {hasMore && (
          <button
            type="button"
            onClick={onToggle}
            style={{
              marginLeft: 'auto',
              backgroundColor: 'transparent',
              border: `1px solid ${COLOR.darker}`,
              borderRadius: px(TOOL_CARD.buttons.radius),
              padding: `${px(6)}px ${px(14)}px`,
              color: COLOR.rose,
              fontFamily: FONT.family,
              fontSize: px(FONT.body3.size),
              lineHeight: `${px(FONT.body3.height)}px`,
              fontWeight: 600,
              cursor: 'pointer',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(217,56,84,0.08)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            {expanded ? 'See less' : 'See more'}
          </button>
        )}
        {createLabel && onCreate && (
          <button
            type="button"
            onClick={onCreate}
            className="flex items-center justify-center"
            style={{
              marginLeft: hasMore ? 0 : 'auto',
              height: px(32),
              paddingLeft: px(12),
              paddingRight: px(16),
              borderRadius: px(TOOL_CARD.buttons.radius),
              backgroundColor: COLOR.rose,
              color: COLOR.white,
              border: 'none',
              cursor: 'pointer',
              gap: px(6),
              fontFamily: FONT.family,
              fontSize: px(FONT.body3.size),
              fontWeight: 700,
              flexShrink: 0,
              transition: 'background-color 150ms',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = COLOR.roseHover)}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = COLOR.rose)}
          >
            <AppIcon name="plus" size={px(16)} color={COLOR.white} weight="bold" />
            {createLabel}
          </button>
        )}
      </div>
      {isEmpty ? (
        <ApexShellEmpty description={emptyMessage} />
      ) : (
        children
      )}
    </section>
  );
}

function CardGrid({ children }) {
  const { px } = useFigmaPx();
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 280px), 1fr))',
        gap: px(LAYOUT.mytools.cardGap),
      }}
    >
      {children}
    </div>
  );
}

// ────── View ─────────────────────────────────────────────────────────────
export default function MyToolsView() {
  const { px } = useFigmaPx();
  const { dispatch, ACTIONS } = useWorkflow();
  const { user } = useAuth();
  const [search, setSearch] = useState('');
  const [workflows, setWorkflows] = useState([]);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [sharedWorkflows, setSharedWorkflows] = useState([]);
  const [sharedKBs, setSharedKBs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  // Section expansion (shared is a single flat section now)
  const [expanded, setExpanded] = useState({ wf: false, kb: false, shared: false });

  // Modal state
  const [shareDialog, setShareDialog] = useState({ isOpen: false, resource: null, type: 'workflow' });
  const [confirmDelete, setConfirmDelete] = useState({ isOpen: false, item: null, type: null });
  const [alertModal, setAlertModal] = useState({ isOpen: false, title: '', message: '', variant: 'error' });
  const [showCreatePrompt, setShowCreatePrompt] = useState(false);
  const [createWfFormData, setCreateWfFormData] = useState({ name: '', description: '' });
  const [showCreateKBModal, setShowCreateKBModal] = useState(false);
  const [kbFormData, setKbFormData] = useState({ name: '', description: '', embedding_model: 'azure_ada_002' });
  const [creatingKB, setCreatingKB] = useState(false);

  const fetchAll = async () => {
    try {
      setLoading(true);
      // IMPORTANT: backend `GET /api/workflows/` rejects page_size > 100
      // (422).  Using 200 silently failed every list call → empty workflows.
      const [wfRes, kbs, sharedWfs, sharedKbs] = await Promise.all([
        listWorkflows(1, 100, {}).catch(() => null),
        listKnowledgeBases().catch(() => null),
        listSharedWithMeWorkflows().catch(() => null),
        listSharedWithMeKnowledgeBases().catch(() => null),
      ]);
      const merged = asArray(wfRes, 'items', 'workflows');
      merged.sort((a, b) => {
        const pickTime = (w) =>
          new Date(
            w?.lastAccessedAt ||
              w?.updatedAt ||
              w?.createdAt ||
              w?.updated_at ||
              w?.created_at ||
              0,
          ).getTime();
        return pickTime(b) - pickTime(a);
      });
      setWorkflows(merged);
      setKnowledgeBases(asArray(kbs, 'knowledge_bases', 'items'));
      setSharedWorkflows(asArray(sharedWfs, 'items', 'workflows'));
      setSharedKBs(asArray(sharedKbs, 'items', 'knowledge_bases'));
    } catch (e) {
      setError(e.message || 'Failed to load tools');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await fetchAll();
      if (cancelled) return;
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const matchesQuery = (text) => {
    if (!search.trim()) return true;
    return (text || '').toLowerCase().includes(search.toLowerCase());
  };

  const pinFirst = (a, b, key) => {
    const ap = key === 'isPinned' ? !!a.isPinned : !!a.is_pinned;
    const bp = key === 'isPinned' ? !!b.isPinned : !!b.is_pinned;
    if (ap !== bp) return ap ? -1 : 1;
    return 0;
  };

  const filteredWorkflows = useMemo(
    () => workflows
      .filter((w) => matchesQuery(w.name) || matchesQuery(w.description))
      .sort((a, b) => pinFirst(a, b, 'isPinned')),
    [workflows, search],
  );
  const filteredKBs = useMemo(
    () => knowledgeBases
      .filter((k) => matchesQuery(k.name) || matchesQuery(k.description))
      .sort((a, b) => pinFirst(a, b, 'is_pinned')),
    [knowledgeBases, search],
  );

  const filteredSharedItems = useMemo(() => {
    const wfs = sharedWorkflows
      .filter((w) => matchesQuery(w.name) || matchesQuery(w.description))
      .map((w) => ({ ...w, _kind: 'workflow' }));
    const kbs = sharedKBs
      .filter((k) => matchesQuery(k.name) || matchesQuery(k.description))
      .map((k) => ({ ...k, _kind: 'kb' }));
    return [...wfs, ...kbs];
  }, [sharedWorkflows, sharedKBs, search]);

  const isSearching = !!search.trim();
  const limit = (list, key) =>
    isSearching || expanded[key] ? list : list.slice(0, COLLAPSE_LIMIT);

  const handleLaunchWorkflow = async (wf) => {
    if (busyId) return;
    setBusyId(wf.id);
    try {
      const session = await createChatSession(wf.id, {
        name: `Chat with ${wf.name}`,
      });
      dispatch({
        type: ACTIONS.NAVIGATE,
        payload: {
          view: 'chat',
          selectedWorkflow: wf,
          selectedSession: session,
        },
      });
    } catch (e) {
      safeError('Failed to launch workflow:', e);
      setAlertModal({
        isOpen: true,
        title: 'Launch failed',
        message: e.message || 'Could not start a chat for this workflow.',
        variant: 'error',
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleEditWorkflow = (wf) => {
    const shareAccess =
      wf.shareAccess
      || (wf.permission === 'write' ? 'write' : wf.permission === 'read' ? 'read' : null);
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: {
        view: 'builder',
        selectedWorkflow: { ...wf, shareAccess },
      },
    });
  };

  const handleEditKB = (kb) => {
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: {
        view: 'kb-detail',
        selectedKB: {
          kb_id: kb.id || kb.kb_id,
          is_shared: kb.share_access === 'read',
          share_access: kb.share_access || (kb.is_shared ? 'read' : 'owner'),
        },
      },
    });
  };

  const handleCreateWorkflow = () => {
    setCreateWfFormData({ name: '', description: '' });
    setShowCreatePrompt(true);
  };

  const handleCreateWithNameAndDesc = () => {
    const name = createWfFormData.name.trim();
    if (!name) return;
    setShowCreatePrompt(false);
    dispatch({ type: ACTIONS.CLEAR_CANVAS });
    dispatch({
      type: ACTIONS.NAVIGATE,
      payload: {
        view: 'builder',
        selectedWorkflow: null,
        newWorkflowName: name,
        newWorkflowDescription: createWfFormData.description.trim() || null,
      },
    });
  };

  const openShareDialog = (resource, type) => {
    setShareDialog({ isOpen: true, resource, type });
  };

  const requestDelete = (item, type) => {
    setConfirmDelete({ isOpen: true, item, type });
  };

  const handleConfirmDelete = async () => {
    const { item, type } = confirmDelete;
    if (!item) return;
    try {
      if (type === 'workflow') {
        await deleteWorkflow(item.id, false);
      } else if (type === 'kb') {
        await deleteKnowledgeBase(item.id || item.kb_id, false);
      }
      setConfirmDelete({ isOpen: false, item: null, type: null });
      await fetchAll();
    } catch (e) {
      safeError('Failed to delete:', e);
      setConfirmDelete({ isOpen: false, item: null, type: null });
      setAlertModal({
        isOpen: true,
        title: 'Deletion failed',
        message: e.message || 'Could not delete.',
        variant: 'error',
      });
    }
  };

  const handleDuplicate = async (wf) => {
    try {
      await duplicateWorkflow(wf);
      await fetchAll();
    } catch (e) {
      safeError('Failed to duplicate workflow:', e);
      setAlertModal({
        isOpen: true,
        title: 'Duplicate failed',
        message: e.message || 'Could not duplicate workflow.',
        variant: 'error',
      });
    }
  };

  const handleTogglePin = async (item, type) => {
    try {
      if (type === 'workflow') {
        await toggleWorkflowPin(item.id, !item.isPinned);
      } else {
        await toggleKBPin(item.kb_id || item.id, !item.is_pinned);
      }
      await fetchAll();
    } catch (e) {
      safeError('Failed to toggle pin:', e);
    }
  };

  const handleCreateKB = async () => {
    if (!kbFormData.name.trim()) return;
    try {
      setCreatingKB(true);
      const payload = {
        session_id: 'default-session',
        name: kbFormData.name.trim(),
        description: kbFormData.description.trim() || undefined,
        embedding_model: kbFormData.embedding_model,
      };
      const created = await createKnowledgeBase(payload);
      setShowCreateKBModal(false);
      setKbFormData({ name: '', description: '', embedding_model: 'azure_ada_002' });
      dispatch({
        type: ACTIONS.NAVIGATE,
        payload: {
          view: 'kb-detail',
          selectedKB: { kb_id: created?.id || created?.kb_id, is_shared: false },
        },
      });
    } catch (e) {
      safeError('Failed to create knowledge base:', e);
      setAlertModal({
        isOpen: true,
        title: 'Creation failed',
        message: e.message || 'Could not create knowledge base.',
        variant: 'error',
      });
    } finally {
      setCreatingKB(false);
    }
  };

  function sharedByLabel(item) {
    if (item.via === 'group') {
      const groupName = item.viaPrincipalDisplayName || item.viaPrincipalId?.slice(0, 8) || 'Unknown';
      return `Shared from ${groupName}`;
    }
    const personName = item.createdByName || item.viaPrincipalDisplayName || item.createdBy_name || null;
    if (personName) return `Shared by ${personName}`;
    return 'Shared with you';
  }

  // ────── Card builders ───────────────────────────────────────────────
  const renderOwnedWorkflow = (wf) => (
    <ToolCard
      key={`wf-${wf.id}`}
      kind="workflow"
      showTag={false}
      title={wf.name}
      iconUrl={wf.icon?.startsWith('/') ? wf.icon : undefined}
      description={wf.description || wf.marketplaceDescription}
      date={formatDate(wf.updatedAt || wf.createdAt || wf.updated_at || wf.created_at)}
      people={[]}
      shareLabel=""
      primary={{
        label: 'Launch',
        icon: 'launch',
        onClick: () => handleLaunchWorkflow(wf),
        busy: busyId === wf.id,
      }}
      secondary={{
        label: 'Edit',
        icon: 'edit',
        onClick: () => handleEditWorkflow(wf),
      }}
      menuItems={[
        {
          id: 'pin',
          label: wf.isPinned ? 'Unpin' : 'Pin',
          icon: 'pin',
          onClick: () => handleTogglePin(wf, 'workflow'),
        },
        {
          id: 'share',
          label: 'Share',
          icon: 'share',
          onClick: () => openShareDialog(wf, 'workflow'),
        },
        {
          id: 'duplicate',
          label: 'Duplicate',
          icon: 'copy',
          onClick: () => handleDuplicate(wf),
        },
        {
          id: 'delete',
          label: 'Delete',
          icon: 'trash',
          danger: true,
          onClick: () => requestDelete(wf, 'workflow'),
        },
      ]}
    />
  );

  const renderOwnedKB = (kb) => (
    <ToolCard
      key={`kb-${kb.id || kb.kb_id}`}
      kind="kb"
      showTag={false}
      title={kb.name}
      description={kb.description}
      date={formatDate(kb.updatedAt || kb.createdAt || kb.updated_at || kb.created_at)}
      people={[]}
      shareLabel=""
      primary={{
        label: 'Edit',
        icon: 'edit',
        onClick: () => handleEditKB(kb),
      }}
      secondary={null}
      menuItems={[
        {
          id: 'pin',
          label: kb.is_pinned ? 'Unpin' : 'Pin',
          icon: 'pin',
          onClick: () => handleTogglePin(kb, 'kb'),
        },
        {
          id: 'share',
          label: 'Share',
          icon: 'share',
          onClick: () => openShareDialog({ ...kb, id: kb.kb_id || kb.id }, 'kb'),
        },
        {
          id: 'delete',
          label: 'Delete',
          icon: 'trash',
          danger: true,
          onClick: () => requestDelete(kb, 'kb'),
        },
      ]}
    />
  );

  const renderSharedItem = (item) => {
    const isWf = item._kind === 'workflow';
    const key = isWf ? `sw-${item.id}` : `sk-${item.id || item.kb_id}`;
    const label = sharedByLabel(item);
    const ownerName = item.createdByName || item.viaPrincipalDisplayName || item.createdBy_name || 'Owner';
    return (
      <ToolCard
        key={key}
        kind={isWf ? 'workflow' : 'kb'}
        title={item.name}
        iconUrl={isWf && item.icon?.startsWith('/') ? item.icon : undefined}
        description={item.description}
        date={formatDate(item.updatedAt || item.createdAt || item.updated_at || item.created_at)}
        people={[
          {
            id: item.createdById || item.createdBy || item.viaPrincipalId || 'owner',
            name: ownerName,
          },
        ]}
        shareLabel={label}
        primary={isWf ? {
          label: 'Launch',
          icon: 'launch',
          onClick: () => handleLaunchWorkflow(item),
          busy: busyId === item.id,
        } : {
          label: item.permission === 'write' ? 'Manage' : 'View',
          icon: '/icons/edit-square.svg',
          onClick: () => handleEditKB(item),
        }}
        secondary={isWf && item.permission === 'write' ? {
          label: 'Edit',
          icon: 'edit',
          onClick: () => handleEditWorkflow(item),
        } : null}
        menuItems={null}
      />
    );
  };

  return (
    <div
      className="w-full overflow-y-auto"
      style={{
        height: '100%',
        backgroundColor: LAYOUT.pageBg,
        color: COLOR.white,
        fontFamily: FONT.family,
      }}
    >
      <div
        style={{
          paddingLeft: px(LAYOUT.mytools.paddingX),
          paddingRight: px(LAYOUT.mytools.paddingX),
          paddingTop: px(10),
          paddingBottom: px(48),
        }}
      >
        {/* Search row — capped to storefront width */}
        <div style={{ maxWidth: `min(${px(LAYOUT.storefront.leftWidth)}px, 60vw)` }}>
          <SearchInputInline value={search} onChange={setSearch} placeholder="Search Tools" />
        </div>

        {loading && <ApexToolsGridLoading />}
        {error && !loading && <div style={{ marginTop: px(40), color: COLOR.rose }}>{error}</div>}

        {!loading && (
          <>
            {/* ── Workflows ─────────────────────────────────────────── */}
            <Section
              title="Workflows"
              count={filteredWorkflows.length}
              expanded={expanded.wf}
              onToggle={() => setExpanded((s) => ({ ...s, wf: !s.wf }))}
              hasMore={filteredWorkflows.length > COLLAPSE_LIMIT}
              isEmpty={filteredWorkflows.length === 0}
              emptyMessage={
                isSearching
                  ? 'No workflows match your search.'
                  : workflows.length === 0
                  ? 'You haven\u2019t created any workflows yet.'
                  : 'No workflows in this view.'
              }
              createLabel="Create Workflow"
              onCreate={handleCreateWorkflow}
            >
              <CardGrid>{limit(filteredWorkflows, 'wf').map(renderOwnedWorkflow)}</CardGrid>
            </Section>

            {/* ── Knowledge Bases ────────────────────────────────────── */}
            <Section
              title="Knowledge Bases"
              count={filteredKBs.length}
              expanded={expanded.kb}
              onToggle={() => setExpanded((s) => ({ ...s, kb: !s.kb }))}
              hasMore={filteredKBs.length > COLLAPSE_LIMIT}
              isEmpty={filteredKBs.length === 0}
              emptyMessage={
                isSearching
                  ? 'No knowledge bases match your search.'
                  : knowledgeBases.length === 0
                  ? 'You haven\u2019t created any knowledge bases yet.'
                  : 'No knowledge bases in this view.'
              }
              createLabel="Create Knowledge Base"
              onCreate={() => setShowCreateKBModal(true)}
            >
              <CardGrid>{limit(filteredKBs, 'kb').map(renderOwnedKB)}</CardGrid>
            </Section>

            {/* ── Shared with me (flat — workflows first, then KBs) ── */}
            {filteredSharedItems.length > 0 && (
              <Section
                title="Shared with me"
                count={filteredSharedItems.length}
                expanded={expanded.shared}
                onToggle={() => setExpanded((s) => ({ ...s, shared: !s.shared }))}
                hasMore={filteredSharedItems.length > COLLAPSE_LIMIT}
              >
                <CardGrid>{limit(filteredSharedItems, 'shared').map(renderSharedItem)}</CardGrid>
              </Section>
            )}
          </>
        )}
      </div>

      {/* Share dialog */}
      {shareDialog.isOpen && shareDialog.resource && (
        <ShareDialog
          isOpen={shareDialog.isOpen}
          resourceType={shareDialog.type === 'kb' ? 'kb' : 'workflow'}
          resource={shareDialog.resource}
          onClose={() => setShareDialog({ isOpen: false, resource: null, type: 'workflow' })}
          onChanged={() => fetchAll()}
        />
      )}

      {/* Delete confirm */}
      <ConfirmModal
        isOpen={confirmDelete.isOpen}
        title={`Delete ${confirmDelete.type === 'kb' ? 'knowledge base' : 'workflow'}?`}
        message={
          confirmDelete.item
            ? `Are you sure you want to delete "${confirmDelete.item.name}"? This action cannot be undone.`
            : ''
        }
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmDelete({ isOpen: false, item: null, type: null })}
      />

      {/* Alert */}
      <AlertModal
        isOpen={alertModal.isOpen}
        title={alertModal.title}
        message={alertModal.message}
        variant={alertModal.variant}
        onClose={() => setAlertModal({ ...alertModal, isOpen: false })}
      />

      {/* Create workflow modal */}
      {showCreatePrompt && (
        <div
          className="fixed inset-0 flex items-center justify-center"
          style={{ zIndex: 50, backgroundColor: 'rgba(0,0,0,0.6)' }}
          onClick={() => setShowCreatePrompt(false)}
        >
          <div
            data-theme="apex-dark"
            style={{
              background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
              border: `1px solid ${COLOR.darker}`,
              borderRadius: px(16),
              padding: px(28),
              maxWidth: 520,
              width: '92%',
              boxShadow: '0 8px 28px rgba(0,0,0,0.6)',
              fontFamily: FONT.family,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{
              fontSize: px(FONT.body1Bold.size),
              fontWeight: FONT.body1Bold.weight,
              color: COLOR.white,
              margin: 0,
              marginBottom: px(4),
            }}>
              Create Workflow
            </h3>
            <p style={{
              fontSize: px(FONT.body3.size),
              color: COLOR.medium,
              margin: 0,
              marginBottom: px(24),
            }}>
              Give your workflow a name and an optional description.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: px(16) }}>
              <div>
                <label style={{
                  display: 'block',
                  fontSize: px(FONT.body3.size),
                  fontWeight: 600,
                  color: COLOR.light,
                  marginBottom: px(8),
                }}>
                  Name <span style={{ color: COLOR.rose }}>*</span>
                </label>
                <input
                  type="text"
                  className="force-white-text"
                  value={createWfFormData.name}
                  onChange={(e) => setCreateWfFormData((p) => ({ ...p, name: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && createWfFormData.name.trim()) handleCreateWithNameAndDesc();
                    if (e.key === 'Escape') setShowCreatePrompt(false);
                  }}
                  placeholder="e.g., Customer Support Bot"
                  autoFocus
                  style={{
                    width: '100%',
                    padding: `${px(10)}px ${px(14)}px`,
                    border: `1px solid ${COLOR.darker}`,
                    borderRadius: px(10),
                    fontSize: px(FONT.body2.size),
                    color: COLOR.white,
                    backgroundColor: COLOR.black,
                    outline: 'none',
                    boxSizing: 'border-box',
                    fontFamily: FONT.family,
                  }}
                />
              </div>

              <div>
                <label style={{
                  display: 'block',
                  fontSize: px(FONT.body3.size),
                  fontWeight: 600,
                  color: COLOR.light,
                  marginBottom: px(8),
                }}>
                  Description
                </label>
                <textarea
                  className="force-white-text"
                  value={createWfFormData.description}
                  onChange={(e) => setCreateWfFormData((p) => ({ ...p, description: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setShowCreatePrompt(false);
                  }}
                  placeholder="What does this workflow do?"
                  rows={3}
                  style={{
                    width: '100%',
                    padding: `${px(10)}px ${px(14)}px`,
                    border: `1px solid ${COLOR.darker}`,
                    borderRadius: px(10),
                    fontSize: px(FONT.body2.size),
                    color: COLOR.white,
                    backgroundColor: COLOR.black,
                    outline: 'none',
                    resize: 'none',
                    boxSizing: 'border-box',
                    fontFamily: FONT.family,
                  }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: px(10), marginTop: px(24) }}>
              <button
                type="button"
                onClick={() => setShowCreatePrompt(false)}
                style={{
                  padding: `${px(8)}px ${px(20)}px`,
                  borderRadius: px(TOOL_CARD.buttons.radius),
                  border: `1px solid ${COLOR.darker}`,
                  backgroundColor: 'transparent',
                  color: COLOR.light,
                  fontSize: px(FONT.body3.size),
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: FONT.family,
                  transition: 'background-color 150ms',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.04)')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreateWithNameAndDesc}
                disabled={!createWfFormData.name.trim()}
                style={{
                  padding: `${px(8)}px ${px(20)}px`,
                  borderRadius: px(TOOL_CARD.buttons.radius),
                  border: 'none',
                  backgroundColor: !createWfFormData.name.trim() ? COLOR.darker : COLOR.rose,
                  color: !createWfFormData.name.trim() ? COLOR.dark : COLOR.white,
                  fontSize: px(FONT.body3.size),
                  fontWeight: 700,
                  cursor: !createWfFormData.name.trim() ? 'not-allowed' : 'pointer',
                  fontFamily: FONT.family,
                  transition: 'background-color 150ms',
                }}
                onMouseEnter={(e) => {
                  if (createWfFormData.name.trim()) e.currentTarget.style.backgroundColor = COLOR.roseHover;
                }}
                onMouseLeave={(e) => {
                  if (createWfFormData.name.trim()) e.currentTarget.style.backgroundColor = COLOR.rose;
                }}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Knowledge Base modal */}
      {showCreateKBModal && (
        <div
          className="fixed inset-0 flex items-center justify-center"
          style={{ zIndex: 50, backgroundColor: 'rgba(0,0,0,0.6)' }}
          onClick={() => setShowCreateKBModal(false)}
        >
          <div
            data-theme="apex-dark"
            style={{
              background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
              border: `1px solid ${COLOR.darker}`,
              borderRadius: px(16),
              padding: px(28),
              maxWidth: 520,
              width: '92%',
              maxHeight: '90vh',
              overflowY: 'auto',
              boxShadow: '0 8px 28px rgba(0,0,0,0.6)',
              fontFamily: FONT.family,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{
              fontSize: px(FONT.body1Bold.size),
              fontWeight: FONT.body1Bold.weight,
              color: COLOR.white,
              margin: 0,
              marginBottom: px(4),
            }}>
              Create Knowledge Base
            </h3>
            <p style={{
              fontSize: px(FONT.body3.size),
              color: COLOR.medium,
              margin: 0,
              marginBottom: px(24),
            }}>
              Configure your knowledge base for document storage and retrieval.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: px(20) }}>
              <div>
                <label style={{
                  display: 'block',
                  fontSize: px(FONT.body3.size),
                  fontWeight: 600,
                  color: COLOR.light,
                  marginBottom: px(8),
                }}>
                  Name <span style={{ color: COLOR.rose }}>*</span>
                </label>
                <input
                  type="text"
                  className="force-white-text"
                  value={kbFormData.name}
                  onChange={(e) => setKbFormData({ ...kbFormData, name: e.target.value })}
                  placeholder="e.g., Research Papers"
                  autoFocus
                  style={{
                    width: '100%',
                    padding: `${px(10)}px ${px(14)}px`,
                    border: `1px solid ${COLOR.darker}`,
                    borderRadius: px(10),
                    fontSize: px(FONT.body2.size),
                    color: COLOR.white,
                    backgroundColor: COLOR.black,
                    outline: 'none',
                    boxSizing: 'border-box',
                    fontFamily: FONT.family,
                  }}
                />
              </div>

              <div>
                <label style={{
                  display: 'block',
                  fontSize: px(FONT.body3.size),
                  fontWeight: 600,
                  color: COLOR.light,
                  marginBottom: px(8),
                }}>
                  Description
                </label>
                <textarea
                  className="force-white-text"
                  value={kbFormData.description}
                  onChange={(e) => setKbFormData({ ...kbFormData, description: e.target.value })}
                  placeholder="e.g., Academic research collection"
                  rows={2}
                  style={{
                    width: '100%',
                    padding: `${px(10)}px ${px(14)}px`,
                    border: `1px solid ${COLOR.darker}`,
                    borderRadius: px(10),
                    fontSize: px(FONT.body2.size),
                    color: COLOR.white,
                    backgroundColor: COLOR.black,
                    outline: 'none',
                    resize: 'none',
                    boxSizing: 'border-box',
                    fontFamily: FONT.family,
                  }}
                />
              </div>

              <div>
                <label style={{
                  display: 'block',
                  fontSize: px(FONT.body3.size),
                  fontWeight: 600,
                  color: COLOR.light,
                  marginBottom: px(8),
                }}>
                  Embedding Model
                </label>
                <select
                  value={kbFormData.embedding_model}
                  onChange={(e) => setKbFormData({ ...kbFormData, embedding_model: e.target.value })}
                  style={{
                    width: '100%',
                    padding: `${px(10)}px ${px(14)}px`,
                    border: `1px solid ${COLOR.darker}`,
                    borderRadius: px(10),
                    fontSize: px(FONT.body2.size),
                    color: COLOR.white,
                    backgroundColor: COLOR.black,
                    outline: 'none',
                    boxSizing: 'border-box',
                    fontFamily: FONT.family,
                  }}
                >
                  <optgroup label="Azure (via GenAI Proxy)">
                    <option value="azure_ada_002">Azure Ada-002 (1536D)</option>
                  </optgroup>
                </select>
                <p style={{
                  fontSize: px(11),
                  color: COLOR.dark,
                  margin: 0,
                  marginTop: px(6),
                }}>
                  Choose embedding model (must match for indexing &amp; querying)
                </p>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: px(10), marginTop: px(28) }}>
              <button
                type="button"
                onClick={() => setShowCreateKBModal(false)}
                style={{
                  padding: `${px(8)}px ${px(20)}px`,
                  borderRadius: px(TOOL_CARD.buttons.radius),
                  border: `1px solid ${COLOR.darker}`,
                  backgroundColor: 'transparent',
                  color: COLOR.light,
                  fontSize: px(FONT.body3.size),
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: FONT.family,
                  transition: 'background-color 150ms',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.04)')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreateKB}
                disabled={!kbFormData.name.trim() || creatingKB}
                style={{
                  padding: `${px(8)}px ${px(20)}px`,
                  borderRadius: px(TOOL_CARD.buttons.radius),
                  border: 'none',
                  backgroundColor: !kbFormData.name.trim() || creatingKB ? COLOR.darker : COLOR.rose,
                  color: !kbFormData.name.trim() || creatingKB ? COLOR.dark : COLOR.white,
                  fontSize: px(FONT.body3.size),
                  fontWeight: 700,
                  cursor: !kbFormData.name.trim() || creatingKB ? 'not-allowed' : 'pointer',
                  fontFamily: FONT.family,
                  transition: 'background-color 150ms',
                }}
                onMouseEnter={(e) => {
                  if (kbFormData.name.trim() && !creatingKB)
                    e.currentTarget.style.backgroundColor = COLOR.roseHover;
                }}
                onMouseLeave={(e) => {
                  if (kbFormData.name.trim() && !creatingKB)
                    e.currentTarget.style.backgroundColor = COLOR.rose;
                }}
              >
                {creatingKB ? 'Creating\u2026' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

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
