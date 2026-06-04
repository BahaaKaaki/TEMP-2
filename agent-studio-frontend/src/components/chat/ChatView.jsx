import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import QuestionsCard from './QuestionsCard';
import Button from '../ui/Button';
import Select from '../ui/Select';
import { APP_DATA, getNodeInfo } from '@/data/appData';
import { useWorkflow } from '@/context/WorkflowContext';
import { parseCitations } from '@/utils/citationParser';
import { 
  getChatSession, 
  sendMessageToSession, 
  createChatSession, 
  updateChatSession,
  getSessionDeliverables,
  approveDeliverable,
  rejectDeliverable,
  uploadFileToSession,
  listSessionFiles,
  deleteFile,
  getSessionCheckpoints,
  revertToCheckpoint,
  API_BASE_URL,
} from '@/api/client';
import { getKBAssets, getStructuredTablePreview, searchDocumentChunks } from '@/api/kb-client';
import { listProjects } from '@/api/project-client';
import DeliverableReview from './DeliverableReview';
import QueryDetails from './QueryDetails';
import nodePaletteConfig from '@/data/nodePaletteConfig.json';
import AlertModal from '../ui/AlertModal';
import ConfirmModal from '../ui/ConfirmModal';
import { safeLog, safeError, safeWarn } from '../../utils/safeLogger';
import { useAuth } from '../../context/AuthContext';
import WorkflowDescriptionViewer from '../ui/WorkflowDescriptionViewer';
import ProjectPickerModal from '../shell/ProjectPickerModal';
import TraceSidePanel from './TraceSidePanel';
import { AgentReplySpinner, useExecutionTraceLine, TraceActivityLine } from './ChatLiveActivity';
import ChatAgentProgressBubble from './ChatAgentProgressBubble';
import AgentMessageKbSources from './AgentMessageKbSources';
import { buildAgentKbNamesByNodeId } from './chatAgentKbUtils';
import ChatMessageAttachments from './ChatMessageAttachments';
import { buildMessageAttachmentMap } from './chatAttachmentUtils';
import {
  CHAT_GHOST_BTN,
  CHAT_GHOST_ICON_BTN,
  CHAT_ICON_BTN,
  CHAT_SECONDARY_BTN,
  CHAT_SEND_BTN,
  CHAT_TEXT_BTN,
  CHAT_TOOLBAR_BTN,
} from './chatButtonStyles';
import ChatMessageBubble from './ChatMessageBubble';
import { getAccessToken } from '@/api/auth-client';
import {
  getMessageBubbleGradient,
  getSystemMessageBubbleGradient,
  getUserMessageBubbleGradient,
} from '../builder/nodeCategoryStyles';
import OpenUIMessage from '@/openui/OpenUIMessage';
import {
  getDeliverableName,
  getDeliverableSections,
  getDeliverableSummary,
  hasRenderableOpenUI,
  readDeliverableOpenUILang,
  requiresOpenUI,
} from '@/openui/resolveOpenUILang';
import { renderTextWithCitations } from '@/openui/citationText';

// Tracks sessions with active workflow executions.
// Maps sessionId → cached messages array (preserves chat across switches).
// Module-level so it survives component unmount/remount (e.g. page navigation).
const _pendingSessionWorkflows = new Map();

function formatConversationMessage(msg) {
  return {
    message_id: msg.message_id,
    role: msg.role,
    content: msg.content || '',
    type: msg.role === 'user' ? 'user' : 'agent',
    agent_id: msg.agent_id || null,
    agent_type: msg.agent_type || null,
    agent_label: msg.agent_label || null,
    citations: msg.citations || null,
    structured_queries: msg.structured_queries || null,
    questions: msg.questions || null,
    answered_at: msg.answered_at || null,
    edwin_url: msg.edwin_url || null,
    edwin_handoff_id: msg.edwin_handoff_id || null,
    timestamp: msg.timestamp || null,
    attached_files: msg.attached_files || null,
    // When "openui", content is OpenUI Lang (sandbox/legacy). Deliverables use runtime translate.
    format: msg.format || null,
  };
}

function deduplicateMessages(formatted) {
  const seen = new Set();
  return formatted.filter(msg => {
    if (seen.has(msg.message_id)) return false;
    seen.add(msg.message_id);
    return true;
  });
}

// Recursive dark-themed content renderer for deliverable sections
function RenderSectionContent({ data, depth = 0 }) {
  if (data === null || data === undefined) return null;

  if (typeof data === 'string') {
    return <p className="text-sm text-white/90 leading-relaxed mb-1 last:mb-0 whitespace-pre-wrap" style={{ wordBreak: 'break-word' }}>{data}</p>;
  }
  if (typeof data === 'number' || typeof data === 'boolean') {
    return <span className="text-sm text-white font-mono">{String(data)}</span>;
  }
  if (Array.isArray(data)) {
    return (
      <div className={`space-y-1 ${depth > 0 ? 'ml-4' : 'ml-1'}`}>
        {data.map((item, idx) => (
          <div key={idx} className="flex items-start gap-2">
            <span className="text-[#d93854] text-xs mt-1.5 flex-shrink-0">•</span>
            <div className="flex-1"><RenderSectionContent data={item} depth={depth + 1} /></div>
          </div>
        ))}
      </div>
    );
  }
  if (typeof data === 'object') {
    return (
      <div className={`space-y-3 ${depth > 0 ? 'ml-4 pl-3 border-l border-[#464646]' : ''}`}>
        {Object.entries(data).filter(([key]) => key !== '_citations').map(([key, value]) => {
          const label = key.replace(/([A-Z])/g, ' $1').replace(/_/g, ' ').trim();
          const isSimple = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean';
          return (
            <div key={key}>
              {isSimple ? (
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="text-xs font-bold text-[#d93854] uppercase tracking-wider flex-shrink-0">{label}:</span>
                  <span className="text-sm text-white/90" style={{ wordBreak: 'break-word' }}>{String(value)}</span>
                </div>
              ) : (
                <>
                  <p className="text-xs font-bold text-[#d93854] uppercase tracking-wider mb-1">{label}:</p>
                  <RenderSectionContent data={value} depth={depth + 1} />
                </>
              )}
            </div>
          );
        })}
      </div>
    );
  }
  return <span className="text-sm text-white">{String(data)}</span>;
}

const chatMarkdownComponents = {
  a: ({ ...props }) => (
    <a
      {...props}
      className="text-[#d93854] hover:underline break-all"
      target="_blank"
      rel="noopener noreferrer"
    />
  ),
  p: ({ ...props }) => (
    <p
      {...props}
      className="text-sm text-white/90 leading-relaxed mb-2 last:mb-0"
      style={{ wordBreak: 'break-word' }}
    />
  ),
  h1: ({ ...props }) => <h1 {...props} className="text-lg font-bold text-white mt-3 mb-1" />,
  h2: ({ ...props }) => <h2 {...props} className="text-base font-semibold text-white mt-3 mb-1" />,
  h3: ({ ...props }) => <h3 {...props} className="text-sm font-semibold text-white/95 mt-2 mb-1" />,
  ul: ({ ...props }) => <ul {...props} className="list-disc list-inside text-sm text-white/90 space-y-0.5 ml-1" />,
  ol: ({ ...props }) => <ol {...props} className="list-decimal list-inside text-sm text-white/90 space-y-0.5 ml-1" />,
  li: ({ ...props }) => <li {...props} className="text-sm text-white/90" />,
  strong: ({ ...props }) => <strong {...props} className="font-semibold text-white" />,
  code: ({ inline, ...props }) =>
    inline ? (
      <code {...props} className="px-1 py-0.5 rounded bg-[#464646] text-white/90 font-mono text-xs" />
    ) : (
      <code
        {...props}
        className="block px-3 py-2 rounded bg-[#464646] text-white/90 font-mono text-xs my-2 overflow-x-auto whitespace-pre-wrap"
      />
    ),
  blockquote: ({ ...props }) => (
    <blockquote {...props} className="border-l-2 border-[#6b6b6b] pl-3 italic text-sm text-white/70 my-2" />
  ),
};

function AgentMessageContent({ message }) {
  const text = message.content || '';
  if (message.format === 'openui') {
    return <OpenUIMessage content={text} isStreaming={Boolean(message.is_streaming)} />;
  }
  if (message.citations?.length) {
    return parseCitations(text, message.citations, chatMarkdownComponents);
  }
  return <ReactMarkdown components={chatMarkdownComponents}>{text}</ReactMarkdown>;
}

function normalizeDeliverablePreviewText(value) {
  return String(value || '')
    .replace(/\s*\[\d+\]/g, '')
    .replace(/\s+([.,;:!?])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function OutputStepMessage({ step, stepTitle, stepNodeInfo, categoryColor, agentType, onExpand, hasHitl, previewMessage }) {
  const bubbleGradient = getMessageBubbleGradient(agentType);
  const isCodeExecutor = step.agentType === 'code-executor';
  const status = step.status;
  const summary = getDeliverableSummary(step);
  const previewText = (previewMessage?.content || '').trim();
  // Show the deliverable's own name rather than the producing agent's label.
  const headerLabel = getDeliverableName(step);
  const needsReview = hasHitl && status === 'pending' && step.agentType !== 'code-executor';
  const sectionCount = (getDeliverableSections(step) || []).length;
  const statusPill =
    status === 'approved' ? { cls: 'border-emerald-900/60 bg-emerald-900/30 text-emerald-300', txt: 'Approved' }
      : status === 'rejected' ? { cls: 'border-red-900/60 bg-red-900/40 text-red-300', txt: 'Rejected' }
        : (status === 'pending' && !needsReview) ? { cls: 'border-yellow-900/60 bg-yellow-900/30 text-yellow-300', txt: 'Pending' }
          : null;
  if (isCodeExecutor) {
    return (
      <div className="flex gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
        <div className="max-w-[85%] min-w-0">
          <button
            type="button"
            onClick={onExpand}
            className="group flex w-full items-center gap-3 rounded-2xl px-5 py-3 text-left ring-1 ring-white/5 transition-all duration-200 hover:ring-[#d93854]/35"
            style={{ background: bubbleGradient }}
          >
            {stepNodeInfo?.icon && (
              <span
                className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg"
                style={{ background: categoryColor ? `${categoryColor}40` : 'rgba(255,255,255,0.08)' }}
              >
                {stepNodeInfo.icon.startsWith('/') ? (
                  <img src={stepNodeInfo.icon} alt={stepNodeInfo.name} className="h-5 w-5 brightness-0 invert" />
                ) : (
                  <span className="text-base">{stepNodeInfo.icon}</span>
                )}
              </span>
            )}
            <div className="flex min-w-0 flex-1 flex-col items-start gap-0.5">
              <span className="text-sm font-semibold text-white">{stepTitle}</span>
              <span className="text-[11px] text-[#b5b5b5]">Click to view output</span>
            </div>
            <svg className="ml-2 h-4 w-4 flex-shrink-0 text-[#6b6b6b] transition-colors group-hover:text-[#d93854]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="min-w-0 max-w-[85%] flex-1">
        <div
          role="button"
          tabIndex={0}
          onClick={() => onExpand()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onExpand();
            }
          }}
          className="group cursor-pointer overflow-hidden rounded-2xl border border-[#464646] bg-[#202020] shadow-[0_8px_24px_rgba(0,0,0,0.16)] transition-all hover:border-[#d93854]/55 hover:bg-[#262626] hover:shadow-[0_12px_34px_rgba(0,0,0,0.30)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#d93854]/60"
        >
          {needsReview && (
            <div className="flex items-center gap-2 border-b border-[#d93854]/30 bg-[#d93854]/12 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-[#ff8ba0]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#ff8ba0] animate-pulse" />
              Needs your review
            </div>
          )}
          <div className="flex items-start gap-3 px-4 pt-4">
            <span
              className="flex h-10 w-10 flex-none items-center justify-center rounded-xl"
              style={{ background: `${categoryColor || '#d93854'}2e` }}
            >
              <svg className="h-5 w-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#8b8b8b]">Deliverable</span>
                {statusPill && (
                  <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${statusPill.cls}`}>{statusPill.txt}</span>
                )}
              </div>
              <div className="mt-0.5 truncate text-base font-semibold text-white" title={headerLabel}>{headerLabel}</div>
              {summary ? (
                <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-white/70">
                  {renderTextWithCitations(summary, step?.deliverable?._citations)}
                </p>
              ) : (
                <p className="mt-1.5 text-sm italic leading-relaxed text-white/45">Open to explore this deliverable.</p>
              )}
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 border-t border-white/[0.07] px-4 py-2.5">
            <span className="min-w-0 truncate text-[11px] text-[#8b8b8b]">
              {step.agentLabel}{sectionCount > 1 ? ` · ${sectionCount} sections` : ''}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExpand();
              }}
              className={`inline-flex flex-none items-center gap-1.5 rounded-[10px] px-3.5 py-2 text-xs font-semibold transition-colors ${
                needsReview
                  ? 'bg-[#d93854] text-white hover:bg-[#c42f48]'
                  : 'border border-[#5a5a5a] bg-[#2c2c2c] text-white hover:border-[#d93854]/60 hover:bg-[#332227]'
              }`}
            >
              {needsReview ? 'Review deliverable' : 'Open deliverable'}
              <svg className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ChatView({ testMode = false, onClose = null }) {
  const { state, dispatch, ACTIONS, isChatEnabled } = useWorkflow();
  const { user } = useAuth();
  const containerRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const currentSessionIdRef = useRef(null); // Track current session to prevent stale updates
  const pollingIntervalRef = useRef(null); // Track polling interval
  const isPollingRef = useRef(false); // Track if background polling is active
  const executionStreamRef = useRef(null); // Live token stream for chat deltas
  const executionStreamIdRef = useRef(null);
  const executionStreamEventIdsRef = useRef(new Set());
  const hasActiveChatDeltaRef = useRef(false);
  /** Execution id before the current send; used to attach live trace to the new run, not the previous one. */
  const executionIdBeforeSendRef = useRef(null);
  const hasAutoNamedRef = useRef(null); // Session ID that was already auto-named
  const parsingPollingIntervalRef = useRef(null); // Track file parsing polling interval
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [attachedFile, setAttachedFile] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [activeStepTab, setActiveStepTab] = useState(0);
  const [isEditingName, setIsEditingName] = useState(false);
  const [editedName, setEditedName] = useState('');
  const [deliverables, setDeliverables] = useState([]);
  const hasPendingOpenUIRef = useRef(false);
  const [activeExecutionId, setActiveExecutionId] = useState(null);
  /** Execution id for the in-flight trace snippet only (avoids showing stale trace during send). */
  const [liveTraceExecutionId, setLiveTraceExecutionId] = useState(null);
  const [isProcessingDeliverable, setIsProcessingDeliverable] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  /** File ids uploaded but not yet sent with a user message */
  const [pendingFileIds, setPendingFileIds] = useState([]);
  /** message_id → files[] for attachments shown on sent user bubbles */
  const [messageAttachments, setMessageAttachments] = useState({});
  const attachmentsSyncedForSessionRef = useRef(null);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const [hasPendingParsing, setHasPendingParsing] = useState(false);
  const [isWorkflowEnded, setIsWorkflowEnded] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef(null);
  const [showNameModal, setShowNameModal] = useState(false);
  const [newChatName, setNewChatName] = useState('');
  const [showCreateError, setShowCreateError] = useState(false);
  const [showChatProjectPicker, setShowChatProjectPicker] = useState(false);
  const hasProjectsForChatRef = useRef(false);
  const pendingChatNameRef = useRef('');
  const [showUploadError, setShowUploadError] = useState(false);
  const [uploadErrorMsg, setUploadErrorMsg] = useState('');
  const [showDeleteFileConfirm, setShowDeleteFileConfirm] = useState(false);
  const [fileToDelete, setFileToDelete] = useState(null);
  const [showDeleteFileError, setShowDeleteFileError] = useState(false);
  const [deleteFileErrorMsg, setDeleteFileErrorMsg] = useState('');
  const [showRenameError, setShowRenameError] = useState(false);
  const [showApproveError, setShowApproveError] = useState(false);
  const [approveErrorMsg, setApproveErrorMsg] = useState('');
  const [showRejectError, setShowRejectError] = useState(false);
  const [rejectErrorMsg, setRejectErrorMsg] = useState('');
  const [checkpoints, setCheckpoints] = useState([]);
  const [isReverting, setIsReverting] = useState(false);
  const [showRevertConfirm, setShowRevertConfirm] = useState(false);
  const [revertTarget, setRevertTarget] = useState(null);
  const [showRevertError, setShowRevertError] = useState(false);
  const [revertErrorMsg, setRevertErrorMsg] = useState('');
  const [editingRevertMessage, setEditingRevertMessage] = useState(null);
  const revertInputRef = useRef(null);
  const [splitPosition, setSplitPosition] = useState(50);
  const [isDraggingSplit, setIsDraggingSplit] = useState(false);
  const [isFocusMode, setIsFocusMode] = useState(false);
  const [showWorkflowGuide, setShowWorkflowGuide] = useState(false);
  const [workflowGuideData, setWorkflowGuideData] = useState(null);
  const [showOutputPanel, setShowOutputPanel] = useState(false);
  const [showTracePanel, setShowTracePanel] = useState(false);
  const splitContainerRef = useRef(null);
  const isDraggingRef = useRef(false);
  const messagesEndRef = useRef(null);
  const prevDeliverablesLengthRef = useRef(0);
  const openedEdwinHandoffIdsRef = useRef(new Set());

  // KB preview & @ mention state
  const [kbAssets, setKbAssets] = useState([]);
  const [kbAssetsLoading, setKbAssetsLoading] = useState(false);
  const [showKbPreview, setShowKbPreview] = useState(false);
  const [kbPreviewDoc, setKbPreviewDoc] = useState(null);
  const [kbPreviewTable, setKbPreviewTable] = useState(null);
  const [kbPreviewData, setKbPreviewData] = useState(null);
  const [kbPreviewPage, setKbPreviewPage] = useState(1);
  const [kbPreviewLoading, setKbPreviewLoading] = useState(false);
  const [kbPreviewExpanded, setKbPreviewExpanded] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [mentionStartIdx, setMentionStartIdx] = useState(-1);
  const [mentionHighlight, setMentionHighlight] = useState(0);
  const mentionRef = useRef(null);
  const [kbChunksData, setKbChunksData] = useState(null);
  const [kbChunksPage, setKbChunksPage] = useState(1);
  const [kbChunksSearch, setKbChunksSearch] = useState('');
  const [kbChunksLoading, setKbChunksLoading] = useState(false);
  const chunkSearchTimerRef = useRef(null);

  // Deliverables modal state — which deliverable tab is open (null = closed)
  const [expandedDeliverableId, setExpandedDeliverableId] = useState(null);
  // Section index the expanded view should open on (deep-link from the Output
  // panel or the inline card's currently-selected tab).
  const [expandedInitialSection, setExpandedInitialSection] = useState(0);

  // Open the expanded deliverable modal focused on a specific section tab and
  // close the Output side panel so the modal is unobstructed.
  const openExpandedDeliverable = useCallback((stepId, sectionIndex = 0) => {
    const idx = Number.isInteger(sectionIndex) ? sectionIndex : 0;
    setExpandedInitialSection(idx < 0 ? 0 : idx);
    setExpandedDeliverableId(stepId);
    setShowOutputPanel(false);
  }, []);

  // Only update messages when content actually changed to avoid re-render flicker.
  const setMessagesIfChanged = useCallback((newMsgs) => {
    setMessages(prev => {
      if (prev.length === newMsgs.length && prev.length > 0) {
        const pLast = prev[prev.length - 1];
        const nLast = newMsgs[newMsgs.length - 1];
        if (pLast?.message_id === nLast?.message_id && pLast?.content === nLast?.content && pLast?.agent_id === nLast?.agent_id) {
          return prev;
        }
      }
      return newMsgs;
    });
  }, []);

  // Only update deliverables when content actually changed to avoid
  // re-rendering DeliverableReview (and rebuilding its visualizations) on
  // every poll tick.  We compare a stable signature built from each
  // deliverable's id, updatedAt, status, iteration and userResponse version.
  const getDeliverablesSignature = (arr) => {
    if (!Array.isArray(arr) || arr.length === 0) return '';
    return arr
      .map(d => {
        const id = d?.id || '';
        const updatedAt = d?.updatedAt || d?.updated_at || '';
        const status = d?.status || '';
        const iteration = d?.iteration ?? 0;
        const userResp = d?.userResponse ? 'r' : '';
        const openUi = requiresOpenUI(d)
          ? (hasRenderableOpenUI(d) ? 'ready' : 'pending')
          : 'na';
        const langLen = readDeliverableOpenUILang(d).length;
        return `${id}:${updatedAt}:${status}:${iteration}:${userResp}:${openUi}:${langLen}`;
      })
      .sort()
      .join('|');
  };

  const setDeliverablesIfChanged = useCallback((newDeliverables) => {
    setDeliverables(prev => {
      if (getDeliverablesSignature(prev) === getDeliverablesSignature(newDeliverables)) {
        return prev;
      }
      return newDeliverables;
    });
  }, []);

  const hasPendingOpenUIDeliverables = useMemo(
    () => deliverables.some((d) => requiresOpenUI(d) && !hasRenderableOpenUI(d)),
    [deliverables],
  );

  useEffect(() => {
    hasPendingOpenUIRef.current = hasPendingOpenUIDeliverables;
  }, [hasPendingOpenUIDeliverables]);

  useEffect(() => {
    const sessionId = currentSessionIdRef.current;
    if (!sessionId || !hasPendingOpenUIDeliverables) return undefined;

    const intervalId = setInterval(async () => {
      try {
        const deliverablesData = await getSessionDeliverables(sessionId);
        if (currentSessionIdRef.current === sessionId && deliverablesData?.deliverables) {
          setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
        }
      } catch {
        // ignore transient fetch errors while waiting for openuiLang
      }
    }, 1500);

    const stopId = setTimeout(() => clearInterval(intervalId), 240000);
    return () => {
      clearInterval(intervalId);
      clearTimeout(stopId);
    };
  }, [hasPendingOpenUIDeliverables, setDeliverablesIfChanged]);

  useEffect(() => {
    const sessionId = currentSessionIdRef.current;
    if (!expandedDeliverableId || !sessionId) return undefined;

    let cancelled = false;
    (async () => {
      try {
        const deliverablesData = await getSessionDeliverables(sessionId);
        if (cancelled || currentSessionIdRef.current !== sessionId) return;
        if (deliverablesData?.deliverables) {
          setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
        }
      } catch (err) {
        safeError('Failed to refresh deliverable for full view:', err);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [expandedDeliverableId, setDeliverablesIfChanged]);

  const openEdwinHandoffIfNew = useCallback((url, handoffId) => {
    if (!url || !handoffId || openedEdwinHandoffIdsRef.current.has(handoffId)) return;
    openedEdwinHandoffIdsRef.current.add(handoffId);
    const opened = window.open(url, `edwin_${handoffId}`, 'noopener,noreferrer');
    if (!opened) {
      safeWarn('Edwin tab may have been blocked by the browser popup blocker:', url);
    }
  }, []);

  useEffect(() => {
    deliverables.forEach((d) => {
      if (d.agentType !== 'powerpoint-generator') return;
      const raw = d.deliverable || {};
      const url = raw.edwin_url || raw.edwinUrl;
      const handoffId = raw.edwin_handoff_id || raw.edwinHandoffId || d.id;
      openEdwinHandoffIfNew(url, handoffId);
    });
    messages.forEach((msg) => {
      if (msg.agent_type !== 'powerpoint-generator') return;
      const url = msg.edwin_url;
      const handoffId = msg.edwin_handoff_id || msg.message_id;
      openEdwinHandoffIfNew(url, handoffId);
    });
  }, [deliverables, messages, openEdwinHandoffIfNew]);

  const appendChatDelta = useCallback((executionId, sessionId, data) => {
    const delta = typeof data?.delta === 'string' ? data.delta : '';
    if (!delta) return;
    if (currentSessionIdRef.current !== sessionId) return;

    const nodeKey = data.node_id || data.span_id || 'assistant';
    const messageId = `stream-${executionId}-${nodeKey}`;

    hasActiveChatDeltaRef.current = true;
    setIsTyping(false);
    setMessages(prev => {
      const next = [...prev];
      const existingIndex = next.findIndex(msg => msg.message_id === messageId);

      if (existingIndex >= 0) {
        next[existingIndex] = {
          ...next[existingIndex],
          content: `${next[existingIndex].content || ''}${delta}`,
          // Lock in the format on the first delta that carries it; later
          // deltas may omit the flag.
          format: next[existingIndex].format || data.format || null,
        };
      } else {
        const lastUserIndex = next.reduce(
          (last, msg, idx) => (msg.type === 'user' || msg.role === 'user' ? idx : last),
          -1
        );
        const hasPersistedAgentMessage = next.some((msg, idx) => (
          idx > lastUserIndex
          && (msg.type === 'agent' || msg.role === 'assistant')
          && msg.agent_id === data.node_id
          && !msg.is_streaming
        ));
        if (hasPersistedAgentMessage) return prev;

        next.push({
          message_id: messageId,
          role: 'assistant',
          type: 'agent',
          content: delta,
          agent_id: data.node_id || null,
          agent_label: data.node_label || 'Assistant',
          agent_type: data.node_type || 'agent',
          format: data.format || null,
          is_streaming: true,
        });
      }

      _pendingSessionWorkflows.set(sessionId, next);
      return next;
    });
  }, []);

  const closeExecutionStream = useCallback(() => {
    if (executionStreamRef.current) {
      executionStreamRef.current.close();
      executionStreamRef.current = null;
    }
    executionStreamIdRef.current = null;
    executionStreamEventIdsRef.current = new Set();
    hasActiveChatDeltaRef.current = false;
  }, []);

  const startExecutionStream = useCallback((executionId, sessionId) => {
    if (!executionId || !sessionId) return;
    const executionKey = String(executionId);
    if (executionStreamRef.current && executionStreamIdRef.current === executionKey) {
      return;
    }

    closeExecutionStream();

    const accessToken = getAccessToken();
    if (!accessToken) return;

    const qs = `?token=${encodeURIComponent(accessToken)}`;
    const es = new EventSource(`${API_BASE_URL}/api/executions/${executionKey}/stream${qs}`, {
      withCredentials: true,
    });

    executionStreamRef.current = es;
    executionStreamIdRef.current = executionKey;
    executionStreamEventIdsRef.current = new Set();
    hasActiveChatDeltaRef.current = false;

    es.addEventListener('chat.delta', (event) => {
      try {
        if (event.lastEventId) {
          if (executionStreamEventIdsRef.current.has(event.lastEventId)) return;
          executionStreamEventIdsRef.current.add(event.lastEventId);
        }
        appendChatDelta(executionKey, sessionId, JSON.parse(event.data));
      } catch (err) {
        safeWarn('Failed to parse chat stream delta:', err);
      }
    });

    es.onerror = () => {
      safeWarn('Chat stream disconnected; browser will retry.');
    };
  }, [appendChatDelta, closeExecutionStream]);

  useEffect(() => {
    const currentLength = deliverables?.length || 0;
    if (currentLength > prevDeliverablesLengthRef.current && currentLength > 0) {
      setActiveStepTab(currentLength - 1);
    } else if (currentLength > 0) {
      setActiveStepTab((prev) => Math.min(prev, currentLength - 1));
    } else {
      setActiveStepTab(0);
    }
    prevDeliverablesLengthRef.current = currentLength;
  }, [deliverables]);

  // Reset tab to 0 when switching sessions to avoid stale index
  useEffect(() => {
    setActiveStepTab(0);
    prevDeliverablesLengthRef.current = 0;
  }, [state.selectedSession?.id]);
  
  const isReviewableDeliverable = useCallback((deliverable) => {
    if (!deliverable || deliverable.status !== 'pending' || deliverable.agentType === 'code-executor') {
      return false;
    }
    return !requiresOpenUI(deliverable) || hasRenderableOpenUI(deliverable);
  }, []);

  const isPendingReviewBlockedOnOpenUI = useCallback((deliverable) => (
    deliverable?.status === 'pending'
    && deliverable.agentType !== 'code-executor'
    && requiresOpenUI(deliverable)
    && !hasRenderableOpenUI(deliverable)
  ), []);

  // A pending HITL deliverable should only say "review" once the review UI is
  // actually available. OpenUI deliverables remain blocked silently while their
  // Lang is being generated so users are never sent to a hidden/non-openable card.
  const hasPendingDeliverables = useMemo(
    () => deliverables.some(isReviewableDeliverable),
    [deliverables, isReviewableDeliverable]
  );

  const reviewableDeliverable = useMemo(
    () => deliverables.find(isReviewableDeliverable) || null,
    [deliverables, isReviewableDeliverable]
  );

  const hasPendingReviewWaitingForOpenUI = useMemo(
    () => deliverables.some(isPendingReviewBlockedOnOpenUI),
    [deliverables, isPendingReviewBlockedOnOpenUI]
  );

  const isComposerBlockedByDeliverable = hasPendingDeliverables || hasPendingReviewWaitingForOpenUI;

  const pendingAttachmentFiles = useMemo(
    () => uploadedFiles.filter((f) => pendingFileIds.includes(f.id)),
    [uploadedFiles, pendingFileIds],
  );

  const checkpointByMessageId = useMemo(() => {
    const map = new Map();
    for (const cp of checkpoints) {
      if (cp.user_message_id) map.set(cp.user_message_id, cp);
    }
    return map;
  }, [checkpoints]);

  const hasStreamingAssistant = useMemo(
    () => messages.some((m) => m.is_streaming),
    [messages]
  );

  const liveActivityVisible = Boolean(isTyping || hasStreamingAssistant);

  const traceExecutionIdForLive = useMemo(() => {
    const id = liveTraceExecutionId ?? activeExecutionId;
    return id != null && id !== '' ? String(id) : null;
  }, [liveTraceExecutionId, activeExecutionId]);

  const traceLine = useExecutionTraceLine(traceExecutionIdForLive);

  const replyProgressAgent = useMemo(() => {
    const streaming = messages.find((m) => m.is_streaming);
    if (streaming) return streaming;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].type === 'agent') return messages[i];
    }
    return { agent_label: 'Assistant', agent_type: 'agent' };
  }, [messages]);

  // Any deliverable whose OpenUI is still translating -- represented by the
  // single progress bubble until its card can render. Pending HITL ones are
  // included: the card only appears once the OpenUI is ready to review.
  const pendingOpenUIDeliverable = useMemo(
    () => deliverables.find(
      (d) => requiresOpenUI(d) && !hasRenderableOpenUI(d),
    ),
    [deliverables],
  );

  const showPendingReplyProgress =
    (liveActivityVisible && !hasStreamingAssistant) || Boolean(pendingOpenUIDeliverable);

  const applySessionExecutionIds = useCallback((sessionData, sessionId) => {
    const execStatus = sessionData.execution_status;
    const execId =
      sessionData.execution_id != null && sessionData.execution_id !== ''
        ? String(sessionData.execution_id)
        : null;
    if (!execId) return;

    setActiveExecutionId(execId);

    const hasPendingSend = _pendingSessionWorkflows.has(sessionId);
    const beforeSend = executionIdBeforeSendRef.current;
    const isNewRunningExecution =
      execStatus === 'running' && (!beforeSend || execId !== beforeSend);

    if (isNewRunningExecution) {
      setLiveTraceExecutionId(execId);
    } else if (!hasPendingSend) {
      setLiveTraceExecutionId(execId);
    }

    if (execStatus === 'running') {
      startExecutionStream(execId, sessionId);
    }
  }, [startExecutionStream]);

  const syncTraceExecutionFromSession = useCallback(async (sessionId) => {
    if (!sessionId || currentSessionIdRef.current !== sessionId) return;
    try {
      const sessionData = await getChatSession(sessionId);
      if (currentSessionIdRef.current !== sessionId) return;
      applySessionExecutionIds(sessionData, sessionId);
    } catch (err) {
      safeWarn('Failed to sync execution id for live trace:', err);
    }
  }, [applySessionExecutionIds]);

  useEffect(() => {
    const onFsChange = () => {
      if (!document.fullscreenElement) setIsFocusMode(false);
    };
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  const toggleFocusMode = useCallback(() => {
    if (isFocusMode) {
      if (document.fullscreenElement) document.exitFullscreen();
      setIsFocusMode(false);
    } else {
      setIsFocusMode(true);
      containerRef.current?.requestFullscreen?.().catch(() => {});
    }
  }, [isFocusMode]);

  // Get the selected workflow and session
  const workflow = state.selectedWorkflow;
  const session = state.selectedSession;

  useEffect(() => {
    if (!session?.id) {
      attachmentsSyncedForSessionRef.current = null;
      setMessageAttachments({});
      setPendingFileIds([]);
    }
  }, [session?.id]);

  useEffect(() => {
    if (!session?.id || isLoading) return;
    if (attachmentsSyncedForSessionRef.current === session.id) return;

    const { map, pending } = buildMessageAttachmentMap(messages, uploadedFiles);
    setMessageAttachments(Object.fromEntries(map));
    setPendingFileIds(Array.from(pending));
    attachmentsSyncedForSessionRef.current = session.id;
  }, [session?.id, isLoading, messages, uploadedFiles]);

  // While the activity strip is visible but we lack an execution id, poll quickly
  // (send may still be in flight, or deep-research returns before the run is linked).
  useEffect(() => {
    if (!liveActivityVisible || !session?.id || traceExecutionIdForLive) return undefined;

    const sessionId = session.id;
    let cancelled = false;

    const tick = () => {
      if (!cancelled) syncTraceExecutionFromSession(sessionId);
    };

    tick();
    const interval = setInterval(tick, 1000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [liveActivityVisible, session?.id, traceExecutionIdForLive, syncTraceExecutionFromSession]);

  useEffect(() => {
    if (!workflow) { setWorkflowGuideData(null); return; }
    try {
      const meta = workflow.meta ? JSON.parse(workflow.meta) : {};
      setWorkflowGuideData(meta.detailedDescription || null);
    } catch {
      setWorkflowGuideData(null);
    }
  }, [workflow]);

  const userInitials = useMemo(() => {
    if (user?.firstName && user?.lastName) return `${user.firstName[0]}${user.lastName[0]}`.toUpperCase();
    if (user?.firstName) return user.firstName[0].toUpperCase();
    if (user?.email) return user.email[0].toUpperCase();
    return 'U';
  }, [user]);

  const parseWorkflowGraph = useCallback(() => {
    if (!workflow) return { nodes: [], edges: [] };

    let nodes = [];
    let edges = [];

    try {
      if (Array.isArray(workflow.nodes)) {
        nodes = workflow.nodes;
      } else if (typeof workflow.nodes === 'string') {
        nodes = JSON.parse(workflow.nodes || '[]');
      }
    } catch (e) {
      safeWarn('Failed to parse workflow nodes:', e);
      nodes = [];
    }

    try {
      const rawEdges = workflow.connections ?? workflow.edges ?? [];
      if (Array.isArray(rawEdges)) {
        edges = rawEdges;
      } else if (typeof rawEdges === 'string') {
        edges = JSON.parse(rawEdges || '[]');
      }
    } catch (e) {
      safeWarn('Failed to parse workflow edges:', e);
      edges = [];
    }

    return { nodes, edges };
  }, [workflow]);

  const shouldLockEndedWorkflow = useCallback((history) => {
    if (!Array.isArray(history) || history.length === 0) return false;

    const { nodes, edges } = parseWorkflowGraph();
    if (!nodes.length) return false;

    const lastAssistantMessage = [...history].reverse().find(msg => msg.role === 'assistant');
    if (!lastAssistantMessage?.agent_id) return false;

    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const currentNode = nodeById.get(lastAssistantMessage.agent_id);
    if (!currentNode) return false;

    const currentConfig = currentNode.data?.config || currentNode.config || {};
    if (currentConfig.agentMode === 'chat') return false;

    const outgoing = edges.filter(e => e.source === currentNode.id);
    if (currentNode.type === 'end' || outgoing.length === 0) {
      return true;
    }

    const hitlTypes = new Set(['human-in-the-loop', 'hitl', 'human']);

    const isTerminalNode = (node) => {
      if (node.type === 'end') return true;
      if (hitlTypes.has(node.type)) {
        const hitlOut = edges.filter(e => e.source === node.id);
        const hitlTargets = hitlOut.map(e => nodeById.get(e.target)).filter(Boolean);
        return hitlTargets.length === 0 || hitlTargets.every(t => t.type === 'end');
      }
      return false;
    };

    const targets = outgoing
      .map(e => nodeById.get(e.target))
      .filter(Boolean);

    if (targets.length === 0) return false;
    return targets.every(isTerminalNode);
  }, [parseWorkflowGraph]);

  const activeAgentNodeId = useMemo(() => {
    if (!workflow) return null;
    const { nodes, edges } = parseWorkflowGraph();
    if (!nodes.length) return null;

    const lastAgent = [...messages].reverse().find(m => m.role === 'assistant' && m.agent_id);
    if (lastAgent?.agent_id) return lastAgent.agent_id;

    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const chatNode = nodes.find(n => n.type === 'chat' || n.type === 'start');
    if (!chatNode) return nodes.find(n => n.type === 'agent')?.id || null;

    const firstEdge = edges.find(e => e.source === chatNode.id);
    if (!firstEdge) return null;
    const target = nodeById.get(firstEdge.target);
    return target?.type === 'agent' ? target.id : null;
  }, [workflow, parseWorkflowGraph, messages]);

  // Compute which agent node IDs have a HITL node as a direct successor.
  // Only those agents should show Approved/Rejected/Pending status badges.
  const agentsWithHitlFollowing = useMemo(() => {
    const { nodes, edges } = parseWorkflowGraph();
    if (!nodes.length) return new Set();
    const hitlTypes = new Set(['human-in-the-loop', 'hitl', 'human']);
    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const result = new Set();
    for (const node of nodes) {
      const outgoing = edges.filter(e => e.source === node.id);
      const targets = outgoing.map(e => nodeById.get(e.target)).filter(Boolean);
      if (targets.some(t => hitlTypes.has(t.type))) {
        result.add(node.id);
      }
    }
    return result;
  }, [parseWorkflowGraph]);

  // Load ALL KB assets from every agent node (used by KB Data panel)
  useEffect(() => {
    if (!workflow) { setKbAssets([]); return; }
    const { nodes } = parseWorkflowGraph();

    const kbIds = new Set();
    for (const n of nodes) {
      const cfg = n.data?.config || n.config || {};
      const ids = cfg.knowledgeBaseId || cfg.knowledgeBaseIds || cfg.knowledge_base_id;
      if (Array.isArray(ids)) ids.forEach(id => id && kbIds.add(id));
      else if (ids) kbIds.add(ids);
    }
    if (kbIds.size === 0) { setKbAssets([]); return; }

    let cancelled = false;
    setKbAssetsLoading(true);
    Promise.all([...kbIds].map(id => getKBAssets(id).catch(() => null)))
      .then(results => {
        if (cancelled) return;
        setKbAssets(results.filter(Boolean));
      })
      .finally(() => !cancelled && setKbAssetsLoading(false));
    return () => { cancelled = true; };
  }, [workflow, parseWorkflowGraph]);

  // KB IDs belonging to the currently active agent (for @ mention filtering)
  const activeKbIds = useMemo(() => {
    if (!workflow || !activeAgentNodeId) return null;
    const { nodes } = parseWorkflowGraph();
    const agentNode = nodes.find(n => n.id === activeAgentNodeId);
    if (!agentNode) return null;

    const cfg = agentNode.data?.config || agentNode.config || {};
    const ids = cfg.knowledgeBaseId || cfg.knowledgeBaseIds || cfg.knowledge_base_id;
    const result = new Set();
    if (Array.isArray(ids)) ids.forEach(id => id && result.add(id));
    else if (ids) result.add(ids);
    return result.size > 0 ? result : null;
  }, [workflow, parseWorkflowGraph, activeAgentNodeId]);

  const agentKbNamesByNodeId = useMemo(() => {
    if (!workflow) return new Map();
    const { nodes } = parseWorkflowGraph();
    return buildAgentKbNamesByNodeId(nodes, kbAssets);
  }, [workflow, parseWorkflowGraph, kbAssets]);

  // Build flat mention items filtered to the active agent's KBs
  const mentionItems = useMemo(() => {
    const STRUCT_EXT = ['csv', 'xlsx', 'xls'];
    const items = [];
    const sourceKbs = activeKbIds
      ? kbAssets.filter(kb => activeKbIds.has(kb.kb_id))
      : kbAssets;
    for (const kb of sourceKbs) {
      for (const doc of (kb.documents || [])) {
        const ext = (doc.file_name || '').split('.').pop()?.toLowerCase();
        if (STRUCT_EXT.includes(ext)) continue;
        items.push({ type: 'document', label: doc.file_name, kbName: kb.kb_name, id: doc.id, detail: `${doc.chunk_count || 0} chunks` });
      }
      for (const tbl of (kb.structured_tables || [])) {
        items.push({ type: 'table', label: tbl.display_name || tbl.table_name, kbName: kb.kb_name, id: tbl.id, detail: `${(tbl.columns || []).length} cols` });
      }
    }
    return items;
  }, [kbAssets, activeKbIds]);

  const filteredMentions = useMemo(() => {
    if (!mentionFilter) return mentionItems;
    const lf = mentionFilter.toLowerCase();
    return mentionItems.filter(m => m.label.toLowerCase().includes(lf) || m.kbName.toLowerCase().includes(lf));
  }, [mentionItems, mentionFilter]);

  const closeMention = useCallback(() => {
    setMentionOpen(false);
    setMentionFilter('');
    setMentionStartIdx(-1);
    setMentionHighlight(0);
  }, []);

  const insertMention = useCallback((item) => {
    const before = inputValue.slice(0, mentionStartIdx);
    const after = inputValue.slice(textareaRef.current?.selectionStart ?? inputValue.length);
    const tag = `[${item.label}] `;
    setInputValue(before + tag + after);
    closeMention();
    setTimeout(() => textareaRef.current?.focus(), 0);
  }, [inputValue, mentionStartIdx, closeMention]);

  // Load table preview data for KB preview modal
  const loadTablePreview = useCallback(async (docId, sheetTableId = null, page = 1) => {
    setKbPreviewLoading(true);
    try {
      const data = await getStructuredTablePreview(docId, { page, pageSize: 50, sheetTableId });
      setKbPreviewData(data);
      setKbPreviewPage(page);
    } catch (e) {
      safeError('Failed to load table preview:', e);
    } finally {
      setKbPreviewLoading(false);
    }
  }, []);

  // Load paginated chunks for unstructured docs
  const loadChunks = useCallback(async (kbId, docId, page = 1, search = '') => {
    setKbChunksLoading(true);
    try {
      const data = await searchDocumentChunks(kbId, docId, { page, pageSize: 20, q: search });
      setKbChunksData(data);
      setKbChunksPage(page);
    } catch (e) {
      safeError('Failed to load chunks:', e);
    } finally {
      setKbChunksLoading(false);
    }
  }, []);

  // Start polling for execution updates
  const startPolling = (sessionId) => {
    // Clear any existing polling
    stopPolling();
    // Mark polling as active AFTER stopPolling clears it
    isPollingRef.current = true;
    // NOTE: Do NOT plant a `_pendingSessionWorkflows` entry here.  That map
    // exclusively tracks "a user message was just sent and we're waiting for
    // the new execution to appear" so the poll can ignore a stale `completed`
    // status from the previous execution.  Polling is also triggered by
    // auto-start and by re-opening a running session — in those cases there
    // is no pending send and we must let the backend's authoritative status
    // (including `paused` / `pending_review`) stop the poll and clear the
    // typing indicator.
    if (currentSessionIdRef.current === sessionId) {
      setIsTyping(true);
    }
    
    safeLog('🔄 Starting polling for session:', sessionId, 'Current session:', currentSessionIdRef.current);
    
    // Poll every 3 seconds
    pollingIntervalRef.current = setInterval(async () => {
      try {
        // Only poll if still on same session
        if (currentSessionIdRef.current !== sessionId) {
          safeLog('⚠️ Session changed during poll (current:', currentSessionIdRef.current, 'polling:', sessionId, '), stopping');
          stopPolling();
          return;
        }
        
        safeLog('📡 Polling session:', sessionId, '| Current ref:', currentSessionIdRef.current, '| isTyping:', isTyping);
        const sessionData = await getChatSession(sessionId);
        const execStatus = sessionData.execution_status;
        const hasPendingSend = _pendingSessionWorkflows.has(sessionId);
        if (sessionData.execution_id) {
          applySessionExecutionIds(sessionData, sessionId);
        }
        safeLog('📡 Poll response - messages:', sessionData.conversation_history?.length, '| execution_status:', execStatus);
        
        // Check if still on same session before updating
        if (currentSessionIdRef.current !== sessionId) {
          return;
        }
        
        // Update messages from the backend response, but prefer cached
        // messages when the backend is stale (e.g. execution not yet linked).
        if (sessionData.conversation_history && sessionData.conversation_history.length > 0) {
          const uniqueMessages = deduplicateMessages(
            sessionData.conversation_history.map(formatConversationMessage)
          );
          
          const cached = _pendingSessionWorkflows.get(sessionId);
          if (Array.isArray(cached) && cached.length > uniqueMessages.length) {
            safeLog('📦 Poll: backend stale (%d msgs), keeping cached (%d msgs)', uniqueMessages.length, cached.length);
            setMessagesIfChanged(cached);
          } else {
            setMessagesIfChanged(uniqueMessages);
            if (_pendingSessionWorkflows.has(sessionId)) {
              _pendingSessionWorkflows.set(sessionId, uniqueMessages);
            }
          }
          
          // Fetch deliverables on every poll cycle so they appear
          // progressively as each agent completes its deliverable.
          let pendingOpenUI = false;
          let nextDeliverables = [];
          try {
            const deliverablesData = await getSessionDeliverables(sessionId);
            if (currentSessionIdRef.current === sessionId && deliverablesData?.deliverables) {
              nextDeliverables = dedupeDeliverables(deliverablesData.deliverables);
              setDeliverablesIfChanged(nextDeliverables);
              pendingOpenUI = nextDeliverables.some(
                (d) => requiresOpenUI(d) && !hasRenderableOpenUI(d),
              );
              hasPendingOpenUIRef.current = pendingOpenUI;
            }
          } catch (_) { /* deliverables may not exist yet */ }

          // Use the authoritative execution_status from the backend to
          // decide whether the workflow is still running.
          // IMPORTANT: If a message was just sent (_pendingSessionWorkflows),
          // ignore a stale "completed" status from a previous execution —
          // the new execution hasn't been created yet.
          const isDone = execStatus === 'completed' || execStatus === 'failed' || execStatus === 'cancelled';
          const isWaiting = execStatus === 'pending_review' || execStatus === 'paused';
          // openuiLang is filled async after the row exists; keep polling until it is renderable.
          const awaitingDeliverableRow = isWaiting && nextDeliverables.length === 0;
          const keepPollingForOpenUI =
            !hasPendingSend && (pendingOpenUI || awaitingDeliverableRow);

          if ((isDone || isWaiting) && keepPollingForOpenUI) {
            safeLog(
              '⏳ Waiting for deliverable/OpenUI (pendingOpenUI=%s, awaitingRow=%s)',
              pendingOpenUI,
              awaitingDeliverableRow,
            );
            setIsTyping(false);
            if (isWaiting) {
              setIsWorkflowEnded(false);
            }
          } else if (isDone && !hasPendingSend) {
            safeLog('✅ Execution finished:', execStatus, '— stopping polling');
            setIsWorkflowEnded(shouldLockEndedWorkflow(sessionData.conversation_history || []));
            setIsTyping(false);
            stopPolling();

            try {
              const checkpointData = await getSessionCheckpoints(sessionId);
              setCheckpoints(checkpointData?.checkpoints || []);
            } catch (err) {
              safeError('Failed to reload checkpoints:', err);
            }
          } else if (isWaiting && !hasPendingSend && !keepPollingForOpenUI) {
            safeLog('⏸️ Execution waiting (%s) — stopping polling, workflow NOT ended', execStatus);
            setIsWorkflowEnded(false);
            setIsTyping(false);
            stopPolling();
            try {
              const deliverablesData = await getSessionDeliverables(sessionId);
              if (currentSessionIdRef.current === sessionId && deliverablesData?.deliverables) {
                setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
              }
            } catch {
              // deliverables may not be available yet
            }
          } else if (isWaiting && !hasPendingSend && keepPollingForOpenUI) {
            safeLog('⏳ HITL pause — still waiting for OpenUI Lang');
            setIsWorkflowEnded(false);
            setIsTyping(false);
          } else {
            safeLog('🔄 Execution still running (or pending send), continuing polling...');
            setIsTyping(!hasActiveChatDeltaRef.current);
          }
        }
      } catch (error) {
        safeError('Polling error:', error);
        // Don't stop polling on error, might be temporary
      }
    }, 3000); // Poll every 3 seconds
  };

  // Stop polling
  const stopPolling = () => {
    isPollingRef.current = false;
    closeExecutionStream();
    if (pollingIntervalRef.current) {
      safeLog('🛑 Stopping polling');
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    // Also stop parsing polling when session changes
    if (parsingPollingIntervalRef.current) {
      safeLog('🛑 Stopping parsing polling');
      clearInterval(parsingPollingIntervalRef.current);
      parsingPollingIntervalRef.current = null;
      setHasPendingParsing(false);
    }
  };

  const doCreateChat = async (chatName, projectId) => {
    try {
      setIsLoading(true);
      const newSession = await createChatSession(workflow.id, {
        name: chatName,
        description: 'New conversation',
        project_id: projectId || undefined,
      });
      dispatch({ type: ACTIONS.SELECT_SESSION, payload: newSession });
    } catch (error) {
      safeError('Failed to create chat session:', error);
      setShowCreateError(true);
      setIsLoading(false);
    }
  };

  const handleCreateChat = async () => {
    if (!newChatName.trim() || !workflow) return;
    setShowNameModal(false);

    if (hasProjectsForChatRef.current) {
      pendingChatNameRef.current = newChatName.trim();
      setShowChatProjectPicker(true);
    } else {
      await doCreateChat(newChatName.trim(), null);
    }
  };

  const handleChatProjectSelected = async (projectId) => {
    setShowChatProjectPicker(false);
    const chatName = pendingChatNameRef.current;
    pendingChatNameRef.current = '';
    if (chatName && workflow) {
      await doCreateChat(chatName, projectId);
    }
  };

  const categoryColorMap = useMemo(() => {
    const map = new Map();
    for (const category of nodePaletteConfig.categories) {
      for (const el of category.elements) {
        map.set(el.id, category.color);
      }
    }
    return map;
  }, []);

  const getCategoryColor = (agentType) => categoryColorMap.get(agentType) || '#93C5FD';

  const dedupeDeliverables = (items) => {
    if (!Array.isArray(items)) return [];
    const byAgent = new Map();
    const order = [];
    for (const item of items) {
      const key = item?.agentId || item?.agent_id;
      if (!key) continue;
      if (!byAgent.has(key)) {
        order.push(key);
      }
      byAgent.set(key, item);
    }
    return order.map(k => byAgent.get(k));
  };

  // Load session conversation history and deliverables when session is selected
  useEffect(() => {
    safeLog('🔄🔄🔄 useEffect triggered - Session:', session?.id, 'Workflow:', workflow?.id);
    
    // Stop any active polling from previous session
    stopPolling();
    setIsTyping(false);
    setLiveTraceExecutionId(null);

    // Update current session ID ref to track active session
    currentSessionIdRef.current = session?.id || null;
    setIsWorkflowEnded(false);

    // Clear revert-related state from the previous session
    setEditingRevertMessage(null);
    setIsReverting(false);
    setRevertTarget(null);
    
    safeLog('🔄 Session changed to:', session?.id, '| Polling stopped, ref updated');
    
    const loadSessionHistory = async () => {
      try {
        safeLog('=== CHAT VIEW LOADING SESSION ===');
        safeLog('Workflow:', workflow);
        safeLog('Session:', session);
        setLoadError(null);

        // If we have cached messages for a pending session, restore them
        // immediately and skip the loading spinner to avoid a UI flash.
        const cached = session?.id ? _pendingSessionWorkflows.get(session.id) : null;
        if (Array.isArray(cached) && cached.length > 0) {
          setMessages(cached);
          setIsLoading(false);
        } else {
          setIsLoading(true);
        }
        
        if (session && session.id) {
          safeLog('Loading session:', session.id);
          
          // Load conversation history
          const sessionData = await getChatSession(session.id);
          safeLog('Session data:', sessionData);
          safeLog('🔍 RAW conversation_history from API:', sessionData.conversation_history);
          
          // Use authoritative execution_status to decide whether to poll
          const execStatus = sessionData.execution_status;
          if (sessionData.execution_id) {
            applySessionExecutionIds(sessionData, session.id);
          } else {
            setLiveTraceExecutionId(null);
          }
          const isKnownPending = _pendingSessionWorkflows.has(session.id);
          safeLog('🔍 Checking execution status:', {
            execution_status: execStatus,
            execution_id: sessionData.execution_id,
            total_messages: sessionData.conversation_history?.length,
            execution_count: sessionData.execution_count,
            knownPending: isKnownPending
          });

          if (execStatus === 'running' || isKnownPending) {
            safeLog('🔄 Execution still running, starting polling');
            setIsTyping(true);
            setIsWorkflowEnded(false);
            startPolling(session.id);
          } else if (execStatus === 'pending_review' || execStatus === 'paused') {
            safeLog('⏸️ Execution waiting (%s), workflow NOT ended', execStatus);
            setIsTyping(false);
            setIsWorkflowEnded(false);
          } else if (execStatus === 'completed' || execStatus === 'failed' || execStatus === 'cancelled') {
            safeLog('✅ Execution finished (%s)', execStatus);
            setIsTyping(false);
            setIsWorkflowEnded(shouldLockEndedWorkflow(sessionData.conversation_history || []));
          } else {
            // No execution_status means no execution has ever run (or all
            // were reverted).  The workflow has NOT ended — the user still
            // needs to send their first message.
            safeLog('⚠️ No execution status — workflow not started yet, keeping open');
            setIsTyping(false);
            setIsWorkflowEnded(false);
          }
          
          if (sessionData.conversation_history && sessionData.conversation_history.length > 0) {
            const uniqueMessages = deduplicateMessages(
              sessionData.conversation_history.map(formatConversationMessage)
            );

            // If this session already has user messages, mark it so we skip auto-naming
            if (sessionData.conversation_history.some((m) => m.role === 'user')) {
              hasAutoNamedRef.current = session.id;
            }

            const cached = _pendingSessionWorkflows.get(session.id);
            if (Array.isArray(cached) && cached.length > uniqueMessages.length) {
              safeLog('📦 Backend stale (%d msgs), restoring cached messages (%d msgs)', uniqueMessages.length, cached.length);
              setMessagesIfChanged(cached);
            } else {
              setMessagesIfChanged(uniqueMessages);
              if (_pendingSessionWorkflows.has(session.id)) {
                _pendingSessionWorkflows.set(session.id, uniqueMessages);
              }
            }
          } else {
            const cached = _pendingSessionWorkflows.get(session.id);
            if (Array.isArray(cached) && cached.length > 0) {
              safeLog('📦 No backend history but session is pending, restoring cached messages');
              setMessagesIfChanged(cached);
            } else {
              safeLog('No messages in session, starting fresh');
              setMessages([]);
            }
          }

          // Load deliverables
          try {
            const deliverablesData = await getSessionDeliverables(session.id);
            safeLog('Deliverables data:', deliverablesData);
            if (deliverablesData && deliverablesData.deliverables) {
              setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
            } else {
              setDeliverables([]);
            }
          } catch (deliverableError) {
            safeError('Failed to load deliverables:', deliverableError);
            setDeliverables([]);
          }

          // Load checkpoints (for revert buttons on user messages)
          try {
            const checkpointData = await getSessionCheckpoints(session.id);
            if (checkpointData && checkpointData.checkpoints) {
              setCheckpoints(checkpointData.checkpoints);
            } else {
              setCheckpoints([]);
            }
          } catch (checkpointError) {
            safeError('Failed to load checkpoints:', checkpointError);
            setCheckpoints([]);
          }
          
          // Load uploaded files for this session
          try {
            const filesData = await listSessionFiles(session.id);
            safeLog('Loaded files for session:', filesData);
            if (filesData && filesData.files) {
              setUploadedFiles(filesData.files);
              
              // Check if any files are pending and start polling
              const hasPending = filesData.files.some(f => f.parsing_status === 'pending');
              setHasPendingParsing(hasPending);
              if (hasPending) {
                startParsingStatusPolling(session.id);
              }
            }
          } catch (fileError) {
            safeError('Failed to load files:', fileError);
            setUploadedFiles([]);
          }
        } else if (workflow) {
          if (testMode) {
            const defaultName = `Test - ${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
            try {
              const newSession = await createChatSession(workflow.id, {
                name: defaultName,
                description: 'Test session'
              });
              dispatch({ type: ACTIONS.SELECT_SESSION, payload: newSession });
            } catch (error) {
              safeError('Failed to create test session:', error);
              setShowCreateError(true);
            }
            setIsWorkflowEnded(false);
            setIsLoading(false);
            return;
          }
          safeLog('No session selected, prompting for chat name for workflow:', workflow.id);
          const defaultName = `${workflow.name || 'Chat'} - ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
          setNewChatName(defaultName);
          // Pre-check if user has projects (non-blocking)
          listProjects().then((res) => {
            hasProjectsForChatRef.current = (res?.items?.length || 0) > 0;
          }).catch(() => {});
          setShowNameModal(true);
          setIsWorkflowEnded(false);
          setIsLoading(false);
          return;
        } else {
          // No workflow or session selected
          safeLog('No workflow or session selected, clearing messages');
          setMessages([]);
          setDeliverables([]);
          setUploadedFiles([]);
          setIsWorkflowEnded(false);
        }
        safeLog('=== LOADING COMPLETE ===');
      } catch (error) {
        safeError('❌ FAILED TO LOAD SESSION:', error);
        safeError('Error stack:', error.stack);
        setLoadError(error.message || 'Unknown error');
        setMessages([]);
        setDeliverables([]);
        setUploadedFiles([]);
      } finally {
        safeLog('Setting isLoading to false');
        setIsLoading(false);
      }
    };
    loadSessionHistory();
    
    // Cleanup function - stop polling when session changes or component unmounts
    return () => {
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.id, workflow?.id]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);


  // Core upload routine — works for files coming from the file input,
  // a paste event, or a drag-and-drop. Sequentially uploads each file
  // through the existing /api/chat/sessions/{id}/files endpoint so the
  // backend can parse / OCR them and stamp them with the active agent.
  const uploadFiles = async (files) => {
    if (!session?.id) {
      safeLog('No session — ignoring upload');
      return;
    }
    const list = Array.from(files || []).filter(Boolean);
    if (list.length === 0) return;
    
    setIsUploadingFile(true);
    let anyPending = false;
    let anyError = null;
    const uploadedBatchIds = [];
    
    for (const file of list) {
      try {
        safeLog('📎 Uploading:', file.name, file.type, file.size);
        const uploadResult = await uploadFileToSession(session.id, file, {
          description: `Uploaded: ${file.name}`
        });
        safeLog('File uploaded:', uploadResult);
        if (uploadResult?.file_id) {
          uploadedBatchIds.push(uploadResult.file_id);
        }
        if (uploadResult?.parsing_status === 'pending') {
          anyPending = true;
        }
      } catch (uploadError) {
        safeError('❌ Failed to upload file:', file.name, uploadError);
        anyError = uploadError;
      }
    }
    
    try {
      const filesData = await listSessionFiles(session.id);
      if (filesData && filesData.files) {
        setUploadedFiles(filesData.files);
        if (uploadedBatchIds.length > 0) {
          const newPending = filesData.files
            .filter((f) => uploadedBatchIds.includes(f.id))
            .map((f) => f.id);
          setPendingFileIds((prev) => [...new Set([...prev, ...newPending])]);
        }
      }
    } catch (refreshErr) {
      safeError('Failed to refresh file list:', refreshErr);
    }
    
    if (anyPending) {
      startParsingStatusPolling(session.id);
    }
    
    setIsUploadingFile(false);
    
    if (anyError) {
      setUploadErrorMsg(anyError.message);
      setShowUploadError(true);
    }
  };
  
  const handleFileUpload = async (e) => {
    const files = e.target.files;
    await uploadFiles(files);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };
  
  // Pasted clipboard items can include images (screenshot) or files
  // copied from the OS file manager. We scan e.clipboardData.items for
  // anything of kind === 'file' and forward it to uploadFiles. Plain
  // text pastes are NOT intercepted — they fall through to the textarea.
  const handlePasteOnInput = async (e) => {
    if (!session?.id) return;
    if (isWorkflowEnded || isComposerBlockedByDeliverable || isUploadingFile) return;
    
    const items = e.clipboardData?.items;
    if (!items || items.length === 0) return;
    
    const pastedFiles = [];
    for (const item of items) {
      if (item.kind === 'file') {
        const f = item.getAsFile();
        if (f) pastedFiles.push(f);
      }
    }
    
    if (pastedFiles.length === 0) {
      // Pure text paste — let the textarea handle it natively.
      return;
    }
    
    // Some OSes also drop a text fragment with a screenshot — when we
    // detect a file we suppress the default to avoid pasting the OS
    // alt-text / file path into the textarea.
    e.preventDefault();
    
    // Pasted screenshots come through with a generic name like
    // "image.png" — rename with a timestamp so the file list shows
    // something less ambiguous.
    const stamped = pastedFiles.map((f) => {
      if (!f.name || /^image\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name)) {
        const ext = (f.type && f.type.split('/')[1]) || 'png';
        const ts = new Date().toISOString().replace(/[:.]/g, '-');
        return new File([f], `pasted-${ts}.${ext}`, { type: f.type || 'image/png' });
      }
      return f;
    });
    
    await uploadFiles(stamped);
  };
  
  const [isDragOver, setIsDragOver] = useState(false);
  
  const handleDragOver = (e) => {
    if (!session?.id) return;
    if (isWorkflowEnded || isComposerBlockedByDeliverable || isUploadingFile) return;
    if (!e.dataTransfer?.types?.includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };
  
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  };
  
  const handleDrop = async (e) => {
    if (!session?.id) return;
    if (isWorkflowEnded || isComposerBlockedByDeliverable || isUploadingFile) {
      setIsDragOver(false);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      await uploadFiles(files);
    }
  };

  const startParsingStatusPolling = (sessionId) => {
    // Clear any existing parsing polling
    if (parsingPollingIntervalRef.current) {
      clearInterval(parsingPollingIntervalRef.current);
      parsingPollingIntervalRef.current = null;
    }
    
    let pollCount = 0;
    const maxPolls = 60; // Poll for max 60 seconds (every 1 second)
    
    safeLog('🔄 Starting file parsing polling for session:', sessionId);
    
    parsingPollingIntervalRef.current = setInterval(async () => {
      try {
        pollCount++;
        
        // Check if session is still active
        if (currentSessionIdRef.current !== sessionId) {
          safeLog('⚠️ Session changed, stopping parsing polling');
          clearInterval(parsingPollingIntervalRef.current);
          parsingPollingIntervalRef.current = null;
          return;
        }
        
        // Fetch updated file list
        const filesData = await listSessionFiles(sessionId);
        if (filesData && filesData.files) {
          setUploadedFiles(filesData.files);
          
          // Check if any files are still pending
          const hasPending = filesData.files.some(f => f.parsing_status === 'pending');
          setHasPendingParsing(hasPending);
          
          // Stop polling if no pending files or max polls reached
          if (!hasPending || pollCount >= maxPolls) {
            clearInterval(parsingPollingIntervalRef.current);
            parsingPollingIntervalRef.current = null;
            safeLog('✅ Parsing status polling stopped');
          }
        }
      } catch (error) {
        safeError('Error polling file status:', error);
        clearInterval(parsingPollingIntervalRef.current);
        parsingPollingIntervalRef.current = null;
      }
    }, 1000); // Poll every 1 second
  };
  
  const handleRemoveFile = () => {
    setAttachedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };
  
  const handleDeleteFile = (fileId, fileName) => {
    setFileToDelete({ id: fileId, name: fileName });
    setShowDeleteFileConfirm(true);
  };

  const confirmDeleteFile = async () => {
    if (!fileToDelete) return;
    setShowDeleteFileConfirm(false);
    
    try {
      safeLog('Deleting file:', fileToDelete.id);
      await deleteFile(fileToDelete.id);
      
      // Reload files list
      const filesData = await listSessionFiles(session.id);
      if (filesData && filesData.files) {
        setUploadedFiles(filesData.files);
      }

      setPendingFileIds((prev) => prev.filter((id) => id !== fileToDelete.id));
      setMessageAttachments((prev) => {
        const next = { ...prev };
        for (const [msgId, list] of Object.entries(next)) {
          const filtered = list.filter((f) => f.id !== fileToDelete.id);
          if (filtered.length) next[msgId] = filtered;
          else delete next[msgId];
        }
        return next;
      });
      
      safeLog('File deleted successfully');
      setFileToDelete(null);
    } catch (error) {
      safeError('Failed to delete file:', error);
      setDeleteFileErrorMsg(error.message);
      setShowDeleteFileError(true);
      setFileToDelete(null);
    }
  };

  // Submit answers from an inline QuestionsCard. Builds the same Q/A
  // summary string the backend would render, posts it as a normal user
  // message, and tags the request with the source question_message_id +
  // structured answers so the backend can stamp `answered_at` on the
  // agent's question message and persist the structured response.
  const handleQuestionsSubmit = async ({ questionMessageId, summary, answers }) => {
    if (!summary || !summary.trim()) return;

    // Optimistic: stamp the message locally so the QuestionsCard
    // collapses to "Answered" right away, before the API round-trip.
    if (questionMessageId) {
      const stampedAt = new Date().toISOString();
      setMessages((prev) =>
        prev.map((m) =>
          m.message_id === questionMessageId
            ? { ...m, answered_at: stampedAt }
            : m,
        ),
      );
    }

    await handleSend(summary, {
      question_message_id: questionMessageId || undefined,
      question_response: answers || undefined,
    });
  };

  const handleSend = async (overrideMessage, sendOptions = {}) => {
    const rawMessage = overrideMessage ?? inputValue;
    if (!rawMessage.trim() || !session || !session.id || isComposerBlockedByDeliverable || isWorkflowEnded || isUploadingFile || hasPendingParsing) {
      safeLog(
        'Cannot send - message:',
        rawMessage,
        'session:',
        session,
        'isComposerBlockedByDeliverable:',
        isComposerBlockedByDeliverable,
        'isWorkflowEnded:',
        isWorkflowEnded,
        'isUploadingFile:',
        isUploadingFile,
        'hasPendingParsing:',
        hasPendingParsing
      );
      return;
    }

    const messageToSend = rawMessage.trim();
    const sessionIdAtStart = session.id;
    const isFirstUserMessage = hasAutoNamedRef.current !== sessionIdAtStart;
    safeLog('Sending message:', messageToSend, 'to session:', sessionIdAtStart,
      'isFirstUserMessage:', isFirstUserMessage, 'hasAutoNamedRef:', hasAutoNamedRef.current);
    
    // Auto-name chat immediately on first user message (fire-and-forget, runs
    // in parallel with the workflow so it doesn't depend on sendMessageToSession)
    if (isFirstUserMessage && !testMode) {
      hasAutoNamedRef.current = sessionIdAtStart;
      const capturedSession = session;
      (async () => {
        try {
          const words = messageToSend.split(/\s+/);
          const autoName = words.length <= 8
            ? messageToSend
            : words.slice(0, 8).join(' ') + '...';
          safeLog('Auto-naming session', sessionIdAtStart, 'to:', autoName);
          const updated = await updateChatSession(sessionIdAtStart, { name: autoName });
          safeLog('Auto-name API response:', updated);
          if (currentSessionIdRef.current === sessionIdAtStart) {
            dispatch({
              type: ACTIONS.SELECT_SESSION,
              payload: { ...capturedSession, ...updated, name: autoName },
            });
          }
        } catch (err) {
          safeError('Auto-name failed:', err);
        }
      })();
    }

    const attachedForSend = uploadedFiles.filter((f) => pendingFileIds.includes(f.id));
    const attachedIds = attachedForSend.map((f) => f.id);

    // Add user message locally (temporary, will be replaced by API response)
    const userMessage = {
      role: 'user',
      content: messageToSend,
      type: 'user',
      message_id: null,
      attached_files: attachedForSend.length > 0 ? attachedForSend : null,
    };
    safeLog('Adding temporary user message:', userMessage);
    setMessages((prev) => [...prev, userMessage]);
    if (attachedIds.length > 0) {
      setPendingFileIds((prev) => prev.filter((id) => !attachedIds.includes(id)));
    }
    setInputValue('');
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = '44px';
    }
    
    setIsTyping(true);
    executionIdBeforeSendRef.current = activeExecutionId ? String(activeExecutionId) : null;
    setLiveTraceExecutionId(null);
    _pendingSessionWorkflows.set(sessionIdAtStart, [...messages, userMessage]);

    // Start polling immediately so intermediate state saved after each
    // workflow node is picked up while the HTTP call is still in flight.
    if (currentSessionIdRef.current === sessionIdAtStart) {
      startPolling(sessionIdAtStart);
      void syncTraceExecutionFromSession(sessionIdAtStart);
    }

    try {
      // Send message to session (sendOptions carries question_message_id /
      // question_response when the user is responding to a QuestionsCard;
      // empty object on a normal send).
      const response = await sendMessageToSession(sessionIdAtStart, messageToSend, sendOptions);
      safeLog('Full chat response:', response);
      if (response.execution_id != null && response.execution_id !== '') {
        const execId = String(response.execution_id);
        setActiveExecutionId(execId);
        setLiveTraceExecutionId(execId);
        if (response.status === 'running') {
          startExecutionStream(execId, sessionIdAtStart);
        }
      } else if (
        response.status === 'running'
        && currentSessionIdRef.current === sessionIdAtStart
      ) {
        void syncTraceExecutionFromSession(sessionIdAtStart);
      }
      
      // The new execution now exists — clear the pending-send flag so
      // polling can rely on the real execution_status from here on.
      _pendingSessionWorkflows.delete(sessionIdAtStart);

      if (response.status === 'running' || response.status === 'pending_review' || response.status === 'paused') {
        setIsWorkflowEnded(false);
      } else if (response.status === 'completed' || response.status === 'failed' || response.status === 'cancelled') {
        setIsWorkflowEnded(shouldLockEndedWorkflow(response.conversation_history || []));
        setIsTyping(false);
        stopPolling();
      }

      // Check if we're still on the same session (prevent stale updates)
      if (currentSessionIdRef.current !== sessionIdAtStart) {
        safeLog('⚠️ Session changed during API call, discarding response from session:', sessionIdAtStart);
        return;
      }

      if (response.conversation_history && Array.isArray(response.conversation_history)) {
        const formatted = deduplicateMessages(
          response.conversation_history.map(formatConversationMessage)
        );
        setMessages(formatted);

        if (attachedForSend.length > 0) {
          for (let i = formatted.length - 1; i >= 0; i -= 1) {
            const m = formatted[i];
            if (m.type === 'user' && (m.content || '').trim() === messageToSend) {
              setMessageAttachments((prev) => ({
                ...prev,
                [m.message_id]: attachedForSend,
              }));
              break;
            }
          }
        }
      }

      // Reload deliverables after sending message (in case agent produced a new one)
      try {
        // Double-check session hasn't changed
        if (currentSessionIdRef.current !== sessionIdAtStart) {
          safeLog('⚠️ Session changed, skipping deliverables reload');
          return;
        }
        
        const deliverablesData = await getSessionDeliverables(sessionIdAtStart);
        safeLog('Reloaded deliverables after send:', deliverablesData);
        
        // Final check before updating state
        if (currentSessionIdRef.current === sessionIdAtStart && deliverablesData && deliverablesData.deliverables) {
          setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
        }
      } catch (deliverableError) {
        safeError('Failed to reload deliverables:', deliverableError);
      }

      // Reload checkpoints so revert buttons appear for the new message
      try {
        if (currentSessionIdRef.current === sessionIdAtStart) {
          const checkpointData = await getSessionCheckpoints(sessionIdAtStart);
          setCheckpoints(checkpointData?.checkpoints || []);
        }
      } catch (cpErr) {
        safeError('Failed to reload checkpoints after send:', cpErr);
      }
    } catch (error) {
      safeError('Chat error:', error);
      _pendingSessionWorkflows.delete(sessionIdAtStart);
      
      // Only show error if still on same session
      if (currentSessionIdRef.current === sessionIdAtStart) {
        setMessages((prev) => [
          ...prev,
          {
            type: 'agent',
            role: 'assistant',
            content: `Error: ${error.message}`,
          },
        ]);
      }
    } finally {
      // Only reset typing if still on same session AND not background polling
      if (currentSessionIdRef.current === sessionIdAtStart && !isPollingRef.current) {
        _pendingSessionWorkflows.delete(sessionIdAtStart);
        setIsTyping(false);
      }
    }
  };

  const handleDeliverNow = async () => {
    if (!session || !session.id || isComposerBlockedByDeliverable || isWorkflowEnded) return;

    const sessionIdAtStart = session.id;
    const messageToSend = inputValue.trim() || 'Please produce your deliverable now.';

    const deliverUserMsg = { role: 'user', content: messageToSend, type: 'user', message_id: null };
    setMessages((prev) => [...prev, deliverUserMsg]);
    setInputValue('');
    if (textareaRef.current) textareaRef.current.style.height = '44px';

    setIsTyping(true);
    executionIdBeforeSendRef.current = activeExecutionId ? String(activeExecutionId) : null;
    setLiveTraceExecutionId(null);
    _pendingSessionWorkflows.set(
      sessionIdAtStart,
      [...messages, deliverUserMsg]
    );

    // Start polling immediately so intermediate state saved after each
    // workflow node is picked up while the HTTP call is still in flight.
    if (currentSessionIdRef.current === sessionIdAtStart) {
      startPolling(sessionIdAtStart);
      void syncTraceExecutionFromSession(sessionIdAtStart);
    }

    try {
      const response = await sendMessageToSession(sessionIdAtStart, messageToSend, { force_deliver: true });
      if (response.execution_id != null && response.execution_id !== '') {
        const execId = String(response.execution_id);
        setActiveExecutionId(execId);
        setLiveTraceExecutionId(execId);
        if (response.status === 'running') {
          startExecutionStream(execId, sessionIdAtStart);
        }
      } else if (
        response.status === 'running'
        && currentSessionIdRef.current === sessionIdAtStart
      ) {
        void syncTraceExecutionFromSession(sessionIdAtStart);
      }
      _pendingSessionWorkflows.delete(sessionIdAtStart);

      if (response.status === 'running' || response.status === 'pending_review' || response.status === 'paused') {
        setIsWorkflowEnded(false);
      } else if (response.status === 'completed' || response.status === 'failed' || response.status === 'cancelled') {
        setIsWorkflowEnded(shouldLockEndedWorkflow(response.conversation_history || []));
        setIsTyping(false);
        stopPolling();
      }
      if (currentSessionIdRef.current !== sessionIdAtStart) return;
      if (response.conversation_history && Array.isArray(response.conversation_history)) {
        setMessages(deduplicateMessages(
          response.conversation_history.map(formatConversationMessage)
        ));
      }
      if (currentSessionIdRef.current === sessionIdAtStart) {
        try {
          const deliverablesData = await getSessionDeliverables(sessionIdAtStart);
          if (currentSessionIdRef.current === sessionIdAtStart && deliverablesData?.deliverables) {
            setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
          }
        } catch (e) { /* ignore deliverable reload errors */ }
        try {
          const cpData = await getSessionCheckpoints(sessionIdAtStart);
          if (currentSessionIdRef.current === sessionIdAtStart) {
            setCheckpoints(cpData?.checkpoints || []);
          }
        } catch (e) { /* ignore checkpoint reload errors */ }
      }
    } catch (error) {
      _pendingSessionWorkflows.delete(sessionIdAtStart);
      if (currentSessionIdRef.current === sessionIdAtStart) {
        setMessages((prev) => [...prev, { type: 'agent', role: 'assistant', content: `Error: ${error.message}` }]);
      }
    } finally {
      if (currentSessionIdRef.current === sessionIdAtStart && !isPollingRef.current) {
        _pendingSessionWorkflows.delete(sessionIdAtStart);
        setIsTyping(false);
      }
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleListening = useCallback(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert('Speech recognition is not supported in this browser. Please use Chrome or Edge.');
      return;
    }

    if (isListening) {
      recognitionRef.current?.stop();
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.interimResults = true;
    recognition.continuous = true;

    const baseText = inputValue;

    recognition.onresult = (event) => {
      let full = '';
      for (let i = 0; i < event.results.length; i++) {
        full += event.results[i][0].transcript;
      }
      const separator = baseText && !baseText.endsWith(' ') ? ' ' : '';
      setInputValue(baseText + separator + full);
    };

    recognition.onend = () => {
      setIsListening(false);
      recognitionRef.current = null;
    };

    recognition.onerror = (event) => {
      if (event.error !== 'aborted') {
        safeError('Speech recognition error:', event.error);
      }
      setIsListening(false);
      recognitionRef.current = null;
    };

    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, [isListening, inputValue]);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
    };
  }, []);

  const startEditingName = () => {
    if (session) {
      setEditedName(session.name || '');
      setIsEditingName(true);
    }
  };

  const cancelEditName = () => {
    setIsEditingName(false);
    setEditedName('');
  };

  const saveSessionName = async () => {
    if (!session || !editedName.trim()) return;

    try {
      const updated = await updateChatSession(session.id, { name: editedName.trim() });
      // Update the session in context
      dispatch({ type: ACTIONS.SELECT_SESSION, payload: updated });
      setIsEditingName(false);
    } catch (error) {
      safeError('Failed to rename session:', error);
      setShowRenameError(true);
    }
  };

  const handleNameKeyPress = (e) => {
    if (e.key === 'Enter') {
      saveSessionName();
    } else if (e.key === 'Escape') {
      cancelEditName();
    }
  };

  const handleApproveDeliverable = async (deliverableId, editedContent) => {
    setIsProcessingDeliverable(true);
    try {
      const approvalData = editedContent ? { edited_deliverable: editedContent } : {};
      const response = await approveDeliverable(deliverableId, approvalData);
      safeLog('Approval response:', response);

      if (session && session.id) {
        const deliverablesData = await getSessionDeliverables(session.id);
        if (deliverablesData && deliverablesData.deliverables) {
          setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
        }

        const sessionData = await getChatSession(session.id);
        if (sessionData.conversation_history) {
          setMessages(sessionData.conversation_history.map(formatConversationMessage));
        }

        // Re-evaluate workflow state based on authoritative execution_status
        const execStatus = sessionData.execution_status;
        if (sessionData.execution_id) {
          setActiveExecutionId(sessionData.execution_id);
          setLiveTraceExecutionId(sessionData.execution_id);
        }
        if (execStatus === 'running') {
          setIsTyping(true);
          setIsWorkflowEnded(false);
          startPolling(session.id);
          if (sessionData.execution_id) {
            startExecutionStream(sessionData.execution_id, session.id);
          }
        } else if (execStatus === 'completed' || execStatus === 'failed' || execStatus === 'cancelled') {
          setIsTyping(false);
          setIsWorkflowEnded(shouldLockEndedWorkflow(sessionData.conversation_history || []));
        }
      }
    } catch (error) {
      safeError('Failed to approve deliverable:', error);
      setApproveErrorMsg(error.message);
      setShowApproveError(true);
    } finally {
      setIsProcessingDeliverable(false);
    }
  };

  // Called after a widget response POST resolves.  `respondResult` is
  // the JSON body returned by POST /api/chat/deliverables/{id}/respond —
  // the backend now embeds a post-resume snapshot (updated_deliverables
  // + execution_status) in that response so we can update the
  // deliverables pane synchronously for chained output.ask() sequences
  // without a separate GET.  The old code relied on a setTimeout + GET
  // after the POST, which raced with React's re-render cycle and meant
  // the next ask often didn't appear until the user refreshed.
  const handleWidgetRespond = async (respondResult) => {
    try {
      if (!session || !session.id) return;
      const sessionId = session.id;

      // Preferred path: use the snapshot returned by the backend.  This
      // is race-free because the backend awaited the workflow resume
      // before returning, so any follow-up ask is already persisted.
      if (respondResult && Array.isArray(respondResult.updated_deliverables)) {
        if (currentSessionIdRef.current === sessionId) {
          setDeliverablesIfChanged(dedupeDeliverables(respondResult.updated_deliverables));
        }

        const execStatus = respondResult.execution_status;
        if (respondResult.execution_id) {
          setActiveExecutionId(respondResult.execution_id);
          setLiveTraceExecutionId(respondResult.execution_id);
          if (execStatus === 'running') {
            startExecutionStream(respondResult.execution_id, sessionId);
          }
        }

        if (execStatus === 'running' || execStatus === 'paused' || execStatus === 'pending_review') {
          setIsTyping(true);
          setIsWorkflowEnded(false);
          // Keep polling alive so later non-interactive output, progress,
          // or a final completion status reaches the UI.
          startPolling(sessionId);
        } else if (execStatus === 'completed' || execStatus === 'failed' || execStatus === 'cancelled') {
          setIsTyping(false);
          try {
            const sessionData = await getChatSession(sessionId);
            if (currentSessionIdRef.current === sessionId && sessionData?.conversation_history) {
              setMessages(sessionData.conversation_history.map(formatConversationMessage));
              setIsWorkflowEnded(shouldLockEndedWorkflow(sessionData.conversation_history || []));
            }
          } catch (err) {
            safeError('Failed to reload session after widget terminal status:', err);
          }
        }
        return;
      }

      // Fallback (older backend build without the snapshot): do a
      // direct fetch.  We intentionally skip the 1.5s setTimeout that
      // used to live here — by the time POST /respond returns, the
      // workflow resume is already complete on the server, so the data
      // is immediately available.
      const [deliverablesData, sessionData] = await Promise.all([
        getSessionDeliverables(sessionId).catch(() => null),
        getChatSession(sessionId).catch(() => null),
      ]);

      if (currentSessionIdRef.current !== sessionId) return;

      if (deliverablesData?.deliverables) {
        setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
      }
      if (sessionData?.conversation_history) {
        setMessages(sessionData.conversation_history.map(formatConversationMessage));
      }

      const execStatus = sessionData?.execution_status;
      if (sessionData?.execution_id) {
        setActiveExecutionId(sessionData.execution_id);
        setLiveTraceExecutionId(sessionData.execution_id);
        if (execStatus === 'running') {
          startExecutionStream(sessionData.execution_id, sessionId);
        }
      }
      if (execStatus === 'running' || execStatus === 'paused' || execStatus === 'pending_review') {
        setIsTyping(true);
        setIsWorkflowEnded(false);
        startPolling(sessionId);
      } else if (execStatus === 'completed' || execStatus === 'failed' || execStatus === 'cancelled') {
        setIsTyping(false);
        setIsWorkflowEnded(shouldLockEndedWorkflow(sessionData?.conversation_history || []));
      }
    } catch (error) {
      safeError('Failed to refresh after widget response:', error);
    }
  };

  const handleRejectDeliverable = async (deliverableId, rejectionNotes) => {
    setIsProcessingDeliverable(true);
    try {
      const response = await rejectDeliverable(deliverableId, { review_notes: rejectionNotes });
      safeLog('Rejection response:', response);

      if (session && session.id) {
        const sessionData = await getChatSession(session.id);
        if (sessionData && sessionData.conversation_history) {
          setMessages(sessionData.conversation_history.map(formatConversationMessage));
        }

        const deliverablesData = await getSessionDeliverables(session.id);
        if (deliverablesData && deliverablesData.deliverables) {
          setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
        }

        // Re-evaluate workflow state based on authoritative execution_status
        const execStatus = sessionData.execution_status;
        if (sessionData.execution_id) {
          setActiveExecutionId(sessionData.execution_id);
          setLiveTraceExecutionId(sessionData.execution_id);
        }
        if (execStatus === 'running') {
          setIsTyping(true);
          setIsWorkflowEnded(false);
          startPolling(session.id);
          if (sessionData.execution_id) {
            startExecutionStream(sessionData.execution_id, session.id);
          }
        } else if (execStatus === 'completed' || execStatus === 'failed' || execStatus === 'cancelled') {
          setIsTyping(false);
          setIsWorkflowEnded(shouldLockEndedWorkflow(sessionData.conversation_history || []));
        }
      }
    } catch (error) {
      safeError('Failed to reject deliverable:', error);
      setRejectErrorMsg(error.message);
      setShowRejectError(true);
    } finally {
      setIsProcessingDeliverable(false);
    }
  };

  const handleRevertClick = (checkpointId, messageContent) => {
    setRevertTarget({ checkpointId, messageContent });
    setShowRevertConfirm(true);
  };

  const handleRevertConfirm = async () => {
    if (!revertTarget || !session) return;
    setShowRevertConfirm(false);
    setIsReverting(true);

    // Stop any active polling before reverting
    stopPolling();

    try {
      const result = await revertToCheckpoint(session.id, revertTarget.checkpointId);

      if (result.conversation_history) {
        setMessages(result.conversation_history.map(formatConversationMessage));
      } else {
        setMessages([]);
      }

      // Show inline editable message for the reverted text
      if (result.prefill_message) {
        setEditingRevertMessage(result.prefill_message);
      }

      // Reset deliverable tab selection
      setActiveStepTab(0);

      // Reload deliverables from server (freshly restored)
      try {
        const deliverablesData = await getSessionDeliverables(session.id);
        if (deliverablesData && deliverablesData.deliverables) {
          setDeliverablesIfChanged(dedupeDeliverables(deliverablesData.deliverables));
        } else {
          setDeliverables([]);
        }
      } catch (err) {
        safeError('Failed to reload deliverables after revert:', err);
        setDeliverables([]);
      }

      // Reload checkpoints (future ones were deleted)
      try {
        const checkpointData = await getSessionCheckpoints(session.id);
        setCheckpoints(checkpointData?.checkpoints || []);
      } catch (err) {
        safeError('Failed to reload checkpoints after revert:', err);
      }

      // Reset workflow-ended state since we reverted
      setIsWorkflowEnded(false);
      if (session?.id) _pendingSessionWorkflows.delete(session.id);
      setIsTyping(false);

    } catch (error) {
      safeError('Failed to revert:', error);
      setRevertErrorMsg(error.message);
      setShowRevertError(true);
    } finally {
      setIsReverting(false);
      setRevertTarget(null);
    }
  };

  const handleRevertEditSubmit = () => {
    if (!editingRevertMessage || !editingRevertMessage.trim()) return;
    const msg = editingRevertMessage.trim();
    setEditingRevertMessage(null);
    handleSend(msg);
  };

  const handleRevertEditKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleRevertEditSubmit();
    }
    if (e.key === 'Escape') {
      setEditingRevertMessage(null);
    }
  };

  const handleSeparatorMouseDown = useCallback((e) => {
    e.preventDefault();
    isDraggingRef.current = true;
    setIsDraggingSplit(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (moveEvent) => {
      if (!isDraggingRef.current || !splitContainerRef.current) return;
      const rect = splitContainerRef.current.getBoundingClientRect();
      const x = moveEvent.clientX - rect.left;
      const percentage = (x / rect.width) * 100;
      setSplitPosition(Math.min(80, Math.max(20, percentage)));
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      setIsDraggingSplit(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, []);

  const handleSeparatorDoubleClick = useCallback(() => {
    setSplitPosition(50);
  }, []);

  const outputSteps = deliverables || [];

  const hiddenDeliverableAgentIds = useMemo(() => {
    const { nodes } = parseWorkflowGraph();
    const hidden = new Set();
    for (const n of nodes) {
      const cfg = n.data?.config || n.config || {};
      if (cfg.hideDeliverable || n.type === 'powerpoint-generator') {
        hidden.add(n.id);
      }
    }
    return hidden;
  }, [parseWorkflowGraph]);

  // Build an interleaved stream: each deliverable is placed relative to
  // chat messages. Agents that produce messages get their deliverable after
  // the last message. Nodes that produce NO messages (e.g. code-executor)
  // use the workflow graph: their deliverable is placed BEFORE the first
  // message from the next node in the graph.
  const interleavedItems = useMemo(() => {
    if (!messages.length && !outputSteps.length) return [];

    const deliverableByAgent = new Map();
    for (const step of outputSteps) {
      const key = step?.agentId || step?.agent_id;
      if (key) deliverableByAgent.set(key, step);
    }

    const agentIdsWithMessages = new Set();
    for (const msg of messages) {
      if (msg.agent_id) agentIdsWithMessages.add(msg.agent_id);
    }

    // For nodes WITH messages: place deliverable after their last message
    const lastMsgIndexByAgent = new Map();
    for (let i = 0; i < messages.length; i++) {
      const agentId = messages[i].agent_id;
      if (agentId && deliverableByAgent.has(agentId)) {
        lastMsgIndexByAgent.set(agentId, i);
      }
    }

    // For nodes WITHOUT messages (code-executor etc): use workflow graph
    // to find the successor node, then place BEFORE that successor's first message.
    const { nodes: wfNodes, edges: wfEdges } = parseWorkflowGraph();
    const successorMap = new Map();
    for (const edge of wfEdges) {
      if (!successorMap.has(edge.source)) successorMap.set(edge.source, []);
      successorMap.get(edge.source).push(edge.target);
    }

    const beforeMsgIndexByAgent = new Map();
    for (const [agentId, step] of deliverableByAgent) {
      if (agentIdsWithMessages.has(agentId)) continue;
      const successors = successorMap.get(agentId) || [];
      let earliestIdx = null;
      for (const succId of successors) {
        for (let i = 0; i < messages.length; i++) {
          if (messages[i].agent_id === succId) {
            if (earliestIdx === null || i < earliestIdx) earliestIdx = i;
            break;
          }
        }
      }
      if (earliestIdx !== null) {
        beforeMsgIndexByAgent.set(agentId, earliestIdx);
      }
    }

    // Detect "Task complete" completion messages that should merge into deliverable
    const deliverableCompletionPattern = /^(Task complete|Research complete|Deep research complete|Task completed|Here is the deliverable)[.]?\s*(Here is the structured deliverable[.]?)?$/i;
    const suppressedMessageIndices = new Set();
    const deliverablePreviewMessageMap = new Map();

    for (let i = 0; i < messages.length; i += 1) {
      const msg = messages[i];
      if (msg.type !== 'agent') continue;

      const agentKey = msg.agent_id || msg.agentId;
      const step = agentKey ? deliverableByAgent.get(agentKey) : null;
      // One rule: if an agent owns a deliverable, drop its redundant
      // completion/summary text bubble (the deliverable card replaces it).
      if (!step) continue;

      const msgText = (msg.content || '').trim();
      const summary = getDeliverableSummary(step);
      const isCompletionBubble = Boolean(msgText) && deliverableCompletionPattern.test(msgText);
      const isLastAgentMessage = agentKey && lastMsgIndexByAgent.get(agentKey) === i;
      const normalizedMsg = normalizeDeliverablePreviewText(msgText);
      const normalizedSummary = normalizeDeliverablePreviewText(summary);
      const isSummaryBubble = Boolean(normalizedMsg && normalizedSummary && normalizedMsg === normalizedSummary);
      const isRedundant = !msgText || isCompletionBubble || isSummaryBubble || isLastAgentMessage;

      if (isRedundant) {
        suppressedMessageIndices.add(i);
        if (isCompletionBubble || isSummaryBubble || isLastAgentMessage) {
          deliverablePreviewMessageMap.set(agentKey, msg);
        }
      }
    }

    const result = [];
    const placedDeliverables = new Set();
    for (let i = 0; i < messages.length; i++) {
      // Insert any no-message deliverables that belong BEFORE this message
      for (const [agentId, beforeIdx] of beforeMsgIndexByAgent) {
        if (beforeIdx === i && !placedDeliverables.has(agentId)) {
          placedDeliverables.add(agentId);
          result.push({ type: 'deliverable', data: deliverableByAgent.get(agentId), agentId });
        }
      }

      if (!suppressedMessageIndices.has(i)) {
        result.push({ type: 'message', data: messages[i], index: i });
      }

      // Insert deliverables that go AFTER this message (their last message)
      for (const [agentId, lastIdx] of lastMsgIndexByAgent) {
        if (lastIdx === i && !placedDeliverables.has(agentId)) {
          placedDeliverables.add(agentId);
          result.push({
            type: 'deliverable',
            data: deliverableByAgent.get(agentId),
            agentId,
            previewMessage: deliverablePreviewMessageMap.get(agentId) || null,
          });
        }
      }
    }

    // Any deliverables still not placed (no messages, no graph match)
    for (const step of outputSteps) {
      const key = step?.agentId || step?.agent_id;
      if (key && !placedDeliverables.has(key)) {
        result.push({ type: 'deliverable', data: step, agentId: key });
      }
    }

    return result;
  }, [messages, outputSteps, parseWorkflowGraph]);

  // Show empty state if no workflow selected and chat is not enabled
  if (!workflow && !isChatEnabled) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full bg-canvas p-6">
        <div className="text-center space-y-6">
          <div className="w-24 h-24 mx-auto bg-[#1a1a1a] rounded-2xl flex items-center justify-center text-5xl">
            🔒
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-bold text-white">Chat Not Available</h2>
            <p className="text-base text-[#b5b5b5] max-w-md mx-auto">
              Select a workflow from the workflows list or add a chat trigger to your workflow
            </p>
          </div>
          <div className="flex gap-3 justify-center">
            <Button onClick={() => dispatch({ type: ACTIONS.NAVIGATE, payload: { view: 'workspace', activeTab: 'workflows' } })}>
              View Workflows
            </Button>
            <Button variant="outline" onClick={() => dispatch({ type: ACTIONS.NAVIGATE, payload: { view: 'builder' } })}>
              Go to Builder
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Show loading state
  if (isLoading) {
    return (
      <div className="flex flex-col h-full w-full items-center justify-center bg-canvas p-6">
        <div className="mb-4">
          <svg width="80" height="80" viewBox="0 0 80 80">
            {/* Red ring background */}
            <circle cx="40" cy="40" r="34" fill="none" stroke="#b91c1c" strokeWidth="6" />
            {/* Black fill that sweeps around the ring */}
            <circle
              cx="40"
              cy="40"
              r="34"
              fill="none"
              stroke="black"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 34}`}
              strokeDashoffset={`${2 * Math.PI * 34}`}
              transform="rotate(-90 40 40)"
              style={{
                animation: 'loadRing 2s ease-in-out infinite',
              }}
            />
            <style>{`
              @keyframes loadRing {
                0% { stroke-dashoffset: ${2 * Math.PI * 34}; }
                50% { stroke-dashoffset: 0; }
                100% { stroke-dashoffset: -${2 * Math.PI * 34}; }
              }
            `}</style>
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-white mb-2">Loading Chat...</h3>
        <p className="text-sm text-[#b5b5b5]">Please wait while we load your conversation</p>
      </div>
    );
  }

  // Show error state
  if (loadError) {
    return (
      <div className="flex flex-col h-full w-full bg-canvas items-center justify-center p-6">
        <div className="text-6xl mb-4">⚠️</div>
        <h3 className="text-lg font-semibold text-white mb-2">Failed to Load Chat</h3>
        <p className="text-sm text-[#b5b5b5] mb-4">{loadError}</p>
        <button
          onClick={() => window.location.reload()}
          className={`px-4 py-2 rounded-[10px] ${CHAT_SECONDARY_BTN}`}
        >
          Reload Page
        </button>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`flex flex-col w-full h-full bg-canvas ${
        isFocusMode ? 'p-0' : testMode ? 'px-6 pb-6 pt-2 gap-3' : 'p-6 gap-4'
      }`}
    >
      {/* Top Bar: ApexOS Logo + Feedback + Avatar (hidden in builder test — BuilderView already shows it) */}
      {!isFocusMode && !testMode && (
        <div className="flex items-center justify-between flex-shrink-0">
          <img src="/icons/apex-os-logo.svg" alt="Apex OS" draggable={false} className="h-11 flex-shrink-0" />
          <div className="flex items-center gap-3">
            <button className={`flex items-center gap-1 h-12 pl-3 pr-4 rounded-[10px] text-base ${CHAT_TOOLBAR_BTN}`}>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
              Feedback
            </button>
            <div
              className="w-12 h-12 rounded-full bg-[#d93854] border-2 border-[#e27588] flex items-center justify-center text-white text-base font-bold flex-shrink-0"
              title={user?.email || 'Account'}
            >
              {userInitials}
            </div>
          </div>
        </div>
      )}

      {/* Single-surface chat thread: header + messages + composer */}
      <div
        className={`chat-thread flex flex-1 flex-col min-h-0 overflow-hidden ${
          isFocusMode ? '' : 'rounded-2xl ring-1 ring-white/5'
        }`}
      >
        <div className="chat-thread__header sticky top-0 z-10 flex flex-shrink-0 items-center gap-3 bg-canvas px-4 py-3">
        {testMode ? (
          <button
            type="button"
            onClick={() => onClose?.()}
            className={CHAT_GHOST_ICON_BTN}
            title="Close test chat"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        ) : (
          <button
            type="button"
            onClick={() => dispatch({ type: ACTIONS.NAVIGATE_BACK })}
            className={CHAT_GHOST_ICON_BTN}
            title="Back"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
          </button>
        )}

        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white/10">
          {workflow?.icon && workflow.icon.startsWith('/') ? (
            <img src={`${API_BASE_URL}${workflow.icon}`} alt="" className="w-full h-full object-cover" />
          ) : (
            <img src="/icons/workflow.svg" alt="Workflow" className="w-7 h-7" />
          )}
        </div>

        {workflow && session ? (
          <div className="flex-1 min-w-0">
            {!testMode && isEditingName ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={editedName}
                  onChange={(e) => setEditedName(e.target.value)}
                  onKeyDown={handleNameKeyPress}
                  onBlur={saveSessionName}
                  autoFocus
                  className="px-2 py-1 text-base font-bold bg-[#464646] border border-[#6b6b6b] rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-[#d93854]"
                />
                <button onClick={saveSessionName} className={`text-xs px-2 py-1 rounded-[6px] ${CHAT_SECONDARY_BTN}`}>✓</button>
                <button onClick={cancelEditName} className="text-xs px-2 py-1 bg-[#464646] text-white rounded hover:bg-[#555]">✕</button>
              </div>
            ) : (
              <h3
                className={`text-2xl font-bold text-white truncate ${testMode ? '' : 'cursor-pointer hover:text-[#dadada]'} transition-colors`}
                onDoubleClick={testMode ? undefined : startEditingName}
                title={testMode ? undefined : 'Double-click to rename'}
              >
                {testMode ? `Testing: ${workflow.name}` : (session.name || workflow.name)}
              </h3>
            )}
          </div>
        ) : (
          <div className="flex-1 min-w-0">
            <h3 className="text-2xl font-bold text-white">{testMode ? 'Initializing test...' : 'Select a chat session'}</h3>
          </div>
        )}

        {workflow && session && kbAssets.length > 0 && (
          <button
            type="button"
            onClick={() => setShowKbPreview(true)}
            className={CHAT_GHOST_BTN}
            title="View Knowledge Base data"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
            </svg>
            KB Data
          </button>
        )}

        <button
          type="button"
          onClick={() => setShowWorkflowGuide(true)}
          className={CHAT_GHOST_BTN}
          title="View workflow guide"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
          Guide
          {workflowGuideData && <span className="w-2 h-2 rounded-full bg-[#d93854]" />}
        </button>

        {outputSteps.length > 0 && (
          <button
            type="button"
            onClick={() => setShowOutputPanel(prev => !prev)}
            className={CHAT_GHOST_BTN}
            title="View all deliverables"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Output
          </button>
        )}

        {activeExecutionId && (
          <button
            type="button"
            onClick={() => setShowTracePanel(prev => !prev)}
            className={CHAT_GHOST_BTN}
            title="View execution trace"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 6h5l2 4h4l2 4h5M3 18h5l2-4h4l2-4h5" />
            </svg>
            Trace
          </button>
        )}

          <button
            type="button"
            onClick={() => {
              if (isFocusMode) {
                if (document.fullscreenElement) document.exitFullscreen();
                setIsFocusMode(false);
              } else {
                setIsFocusMode(true);
                containerRef.current?.requestFullscreen?.().catch(() => {});
              }
            }}
            className={`${CHAT_GHOST_ICON_BTN} ml-auto`}
            title={isFocusMode ? 'Exit fullscreen' : 'Expand to fullscreen'}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {isFocusMode ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
              )}
            </svg>
          </button>
        </div>

          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 scrollbar-dark min-h-0">
          {messages.length === 0 && !outputSteps.length && (
            <div className="text-center py-12">
              <div className="text-5xl mb-4 opacity-40">💬</div>
              <h3 className="text-lg font-semibold text-white mb-2">Start a conversation</h3>
              <p className="text-sm text-[#b5b5b5]">Send a message to begin chatting with this workflow</p>
            </div>
          )}

          {interleavedItems.map((item, idx) => {
            if (item.type === 'deliverable') {
              const step = item.data;
              const stepAgentId = step.agentId || step.agent_id;
              if (hiddenDeliverableAgentIds.has(stepAgentId)) return null;
              // Never surface an OpenUI deliverable card until its OpenUI is
              // ready -- including pending HITL ones, since approve/reject
              // happens in the expanded view after seeing the OpenUI. While it
              // translates, the single progress bubble represents it; the
              // status-driven review banner still blocks the composer.
              if (requiresOpenUI(step) && !hasRenderableOpenUI(step)) return null;
              const stepTitle = step.agentLabel || step.title || `Deliverable`;
              const stepNodeInfo = step.agentType ? getNodeInfo(step.agentType) : null;
              const stepCategoryColor = step.agentType ? getCategoryColor(step.agentType) : null;
              return (
                <OutputStepMessage
                  key={`del-${step.id || item.agentId}-${readDeliverableOpenUILang(step).length}`}
                  step={step}
                  stepTitle={stepTitle}
                  stepNodeInfo={stepNodeInfo}
                  categoryColor={stepCategoryColor}
                  agentType={step.agentType}
                  hasHitl={agentsWithHitlFollowing.has(stepAgentId)}
                  previewMessage={item.previewMessage}
                  onExpand={(secIdx) => openExpandedDeliverable(step.id || item.agentId, secIdx)}
                />
              );
            }

            const message = item.data;
            const index = item.index;
            const nodeInfo = message.type === 'agent' && message.agent_type ? getNodeInfo(message.agent_type) : null;
            const categoryColor = message.type === 'agent' && message.agent_type ? getCategoryColor(message.agent_type) : null;
            
            const matchingCheckpoint = message.type === 'user' && message.message_id
              ? checkpointByMessageId.get(message.message_id) || null
              : null;
            const messageKbNames = message.type === 'agent' && message.agent_id
              ? agentKbNamesByNodeId.get(message.agent_id)
              : null;
            const isEmptyStreaming = Boolean(
              message.is_streaming && !(message.content || '').trim()
            );
            const showAgentReplySpinner = message.type === 'agent' && Boolean(message.is_streaming);
            const messageBubbleGradient =
              message.type === 'user'
                ? getUserMessageBubbleGradient()
                : message.type === 'system'
                  ? getSystemMessageBubbleGradient()
                  : getMessageBubbleGradient(message.agent_type);
            const userMessageFiles = message.type === 'user'
              ? (
                message.attached_files
                || (message.message_id ? messageAttachments[message.message_id] : null)
                || []
              )
              : [];

            return (
            <div
              key={message.message_id || `${message.type}-${index}`}
              className={`flex gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300 ${
                message.type === 'user' ? 'flex-row-reverse items-end' : message.type === 'system' ? 'justify-center' : 'items-start'
              }`}
            >
              {matchingCheckpoint && !isReverting && !isTyping && !editingRevertMessage && (
                <button
                  onClick={() => handleRevertClick(matchingCheckpoint.id, message.content)}
                  className="self-center p-1.5 rounded-lg hover:bg-[#464646] text-[#6b6b6b] hover:text-white transition-colors duration-150 flex-shrink-0"
                  title="Revert to before this message"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a5 5 0 015 5v2M3 10l4-4M3 10l4 4" />
                  </svg>
                </button>
              )}

              <div
                className={
                  message.type === 'system'
                    ? 'max-w-[85%] min-w-0'
                    : message.type === 'user'
                      ? 'flex-1 min-w-0 flex justify-end'
                      : 'flex-1 max-w-[85%] min-w-0'
                }
              >
                <ChatMessageBubble
                  variant={
                    message.type === 'user'
                      ? 'user'
                      : message.type === 'system'
                        ? 'system'
                        : 'agent'
                  }
                  background={messageBubbleGradient}
                  agentLabel={message.type === 'agent' ? message.agent_label : undefined}
                  nodeInfo={nodeInfo}
                  agentType={message.agent_type}
                >
                  {message.type === 'user' && userMessageFiles.length > 0 && (
                    <ChatMessageAttachments
                      variant="message"
                      files={userMessageFiles}
                      onDelete={handleDeleteFile}
                      compact={!(message.content || '').trim()}
                    />
                  )}

                  {isEmptyStreaming ? (
                    <div className="flex w-full min-w-0 items-start gap-2.5">
                      {showAgentReplySpinner && <AgentReplySpinner embedded size={18} />}
                      <div className="min-w-0 flex-1">
                        <TraceActivityLine
                          line={traceLine}
                          executionId={traceExecutionIdForLive}
                        />
                      </div>
                    </div>
                  ) : message.questions && !(message.content || '').trim() ? null
                   : (message.type === 'agent' || message.type === 'system') ? (
                    <div className="flex w-full min-w-0 items-start gap-2.5">
                      {showAgentReplySpinner && <AgentReplySpinner embedded size={18} />}
                      <div
                        className="markdown-content min-w-0 flex-1 overflow-hidden text-white"
                        style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}
                      >
                        <AgentMessageContent message={message} />
                      </div>
                    </div>
                   ) : (message.content ?? '').length > 0 ? (
                    <span
                      className="whitespace-pre-wrap break-words"
                      style={{ wordBreak: 'break-word' }}
                    >
                      {message.content}
                    </span>
                  ) : null}

                  {message.type === 'agent' && message.structured_queries?.length > 0 && (
                    <QueryDetails queries={message.structured_queries} />
                  )}

                  {message.type === 'agent' && message.questions && (
                    <QuestionsCard
                      payload={message.questions}
                      isAnswered={Boolean(message.answered_at)}
                      embedded={!(message.content || '').trim()}
                      onSubmit={(summary, answers) =>
                        handleQuestionsSubmit({
                          questionMessageId: message.message_id,
                          summary,
                          answers,
                        })
                      }
                    />
                  )}

                  {messageKbNames?.length > 0 && (
                    <AgentMessageKbSources kbNames={messageKbNames} />
                  )}
                </ChatMessageBubble>
              </div>
            </div>
            );
          })}

          {/* Inline edit after revert */}
          {editingRevertMessage !== null && (
            <div className="flex gap-2 flex-row-reverse animate-in fade-in slide-in-from-bottom-2 duration-300">
              <button
                onClick={handleRevertEditSubmit}
                disabled={!editingRevertMessage.trim()}
                className={`${CHAT_SEND_BTN} self-end`}
                title="Send message"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </button>
              <div className="flex-1 max-w-[75%] min-w-0">
                <ChatMessageBubble
                  variant="user"
                  background={getUserMessageBubbleGradient()}
                >
                  <textarea
                    ref={revertInputRef}
                    value={editingRevertMessage}
                    onChange={(e) => {
                      setEditingRevertMessage(e.target.value);
                      e.target.style.height = 'auto';
                      e.target.style.height = e.target.scrollHeight + 'px';
                    }}
                    onKeyDown={handleRevertEditKeyDown}
                    className="w-full !text-white bg-transparent resize-none text-sm leading-relaxed caret-white [color:white!important]"
                    rows={1}
                    style={{ overflow: 'hidden', outline: 'none', border: 'none', boxShadow: 'none' }}
                    autoFocus
                    onFocus={(e) => { e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px'; }}
                  />
                </ChatMessageBubble>
              </div>
            </div>
          )}

          {/* Agent reply in progress (trace step inside the reply bubble) */}
          {showPendingReplyProgress && (
            <ChatAgentProgressBubble
              agentLabel={
                pendingOpenUIDeliverable?.agentLabel
                || replyProgressAgent.agent_label
                || 'Assistant'
              }
              agentType={
                pendingOpenUIDeliverable?.agentType
                || replyProgressAgent.agent_type
                || 'agent'
              }
              kbNames={
                (pendingOpenUIDeliverable?.agentId || pendingOpenUIDeliverable?.agent_id)
                  ? agentKbNamesByNodeId.get(
                    pendingOpenUIDeliverable.agentId || pendingOpenUIDeliverable.agent_id,
                  )
                  : replyProgressAgent.agent_id
                    ? agentKbNamesByNodeId.get(replyProgressAgent.agent_id)
                    : null
              }
              traceLine={traceLine}
              executionId={traceExecutionIdForLive}
            />
          )}

          <div ref={messagesEndRef} />
        </div>

        <div className="chat-thread__composer flex-shrink-0 px-4 py-3">
        {isWorkflowEnded && (
          <div className="chat-thread__alert chat-thread__alert--muted mb-2">
            This workflow has ended. Start a new chat session to continue.
          </div>
        )}

          {/* Pending attachments — above input until sent */}
          {(pendingAttachmentFiles.length > 0 || isUploadingFile) && (
            <div className="mb-3">
              {isUploadingFile && pendingAttachmentFiles.length === 0 ? (
                <p className="text-sm text-[#b5b5b5]">Uploading file…</p>
              ) : (
                <ChatMessageAttachments
                  variant="composer"
                  files={pendingAttachmentFiles}
                  onDelete={handleDeleteFile}
                />
              )}
            </div>
          )}

          {/* Input Row */}
          <div
            className={`relative ${
              isDragOver ? 'rounded-xl ring-2 ring-[#d93854]/50' : ''
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {isDragOver && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-[#d93854]/40 bg-[#d93854]/5">
                <span className="text-sm font-medium text-[#d93854]">
                  Drop files to upload
                </span>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileUpload}
              className="hidden"
              accept=".pdf,.txt,.xml,.json,.csv,.md,.docx,.doc,.html,.htm,.rtf,.xlsx,.pptx,.png,.jpg,.jpeg,.gif,.webp,.bmp,image/*"
              multiple
              disabled={isUploadingFile || isComposerBlockedByDeliverable || isWorkflowEnded}
            />
            <div className="chat-thread__composer-shell flex w-full min-w-[240px] items-center gap-2 px-3 py-2">
              {/* Attach button */}
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isWorkflowEnded || isComposerBlockedByDeliverable || isUploadingFile}
                className="w-6 h-6 flex items-center justify-center flex-shrink-0 text-[#b5b5b5] hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title={
                  isUploadingFile
                    ? "Uploading..."
                    : isWorkflowEnded
                      ? "Workflow completed. Start a new chat session."
                      : hasPendingDeliverables
                        ? "Please review pending deliverable first"
                        : "Upload file (uploads immediately)"
                }
              >
                {isUploadingFile ? (
                  <span className="text-base">⏳</span>
                ) : (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                  </svg>
                )}
              </button>

              {/* Text Input with @ mention */}
              <div className="flex-1 min-w-0 relative">
                <textarea
                  ref={textareaRef}
                  placeholder={
                    isWorkflowEnded
                      ? "Workflow completed. Start a new chat session to continue..."
                      : hasPendingDeliverables
                        ? "Review pending deliverable to continue..."
                        : isUploadingFile
                          ? "Uploading file..."
                          : "Type your prompt"
                  }
                  value={inputValue}
                onChange={(e) => {
                  const val = e.target.value;
                  const pos = e.target.selectionStart;
                  setInputValue(val);
                  e.target.style.height = 'auto';
                  e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';

                  if (mentionItems.length > 0) {
                    const charBefore = val[pos - 1];
                    const charTwoBefore = val[pos - 2];
                    if (charBefore === '@' && (!charTwoBefore || /\s/.test(charTwoBefore))) {
                      setMentionOpen(true);
                      setMentionStartIdx(pos);
                      setMentionFilter('');
                      setMentionHighlight(0);
                    } else if (mentionOpen) {
                      const textAfterAt = val.slice(mentionStartIdx);
                      const spaceIdx = textAfterAt.indexOf(' ');
                      if (pos < mentionStartIdx || (spaceIdx !== -1 && spaceIdx < pos - mentionStartIdx)) {
                        closeMention();
                      } else {
                        setMentionFilter(textAfterAt.slice(0, pos - mentionStartIdx));
                      }
                    }
                  }
                }}
                onKeyDown={(e) => {
                  if (mentionOpen && filteredMentions.length > 0) {
                    if (e.key === 'ArrowDown') {
                      e.preventDefault();
                      setMentionHighlight(h => (h + 1) % filteredMentions.length);
                    } else if (e.key === 'ArrowUp') {
                      e.preventDefault();
                      setMentionHighlight(h => (h - 1 + filteredMentions.length) % filteredMentions.length);
                    } else if (e.key === 'Enter' || e.key === 'Tab') {
                      e.preventDefault();
                      insertMention(filteredMentions[mentionHighlight]);
                      return;
                    } else if (e.key === 'Escape') {
                      closeMention();
                      return;
                    }
                  }
                  if (e.key === 'Enter' && !e.shiftKey && !mentionOpen) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                onPaste={handlePasteOnInput}
                rows={1}
                disabled={isWorkflowEnded || isComposerBlockedByDeliverable || isUploadingFile || hasPendingParsing}
                className="w-full text-base bg-transparent resize-none transition-all duration-200 focus:outline-none placeholder:text-[#b5b5b5] disabled:opacity-60 disabled:cursor-not-allowed overflow-y-auto caret-white force-white-text"
                style={{ minHeight: '24px', maxHeight: '200px' }}
              />

              {/* @ Mention dropdown */}
              {mentionOpen && filteredMentions.length > 0 && (
                <div
                  ref={mentionRef}
                  className="absolute bottom-full left-0 mb-2 w-80 max-h-64 overflow-y-auto bg-[#1a1a1a] border border-[#464646] rounded-xl shadow-2xl z-50"
                >
                  <div className="px-3 py-2 border-b border-[#464646] text-[10px] font-semibold text-[#6b6b6b] uppercase tracking-wider">Mention a document or table</div>
                  {filteredMentions.map((item, idx) => (
                    <button
                      key={`${item.type}-${item.id}`}
                      onClick={() => insertMention(item)}
                      onMouseEnter={() => setMentionHighlight(idx)}
                      className={`w-full text-left px-3 py-2 flex items-center gap-2.5 text-sm transition-colors ${
                        idx === mentionHighlight ? 'bg-[#d93854]/10 text-[#d93854]' : 'text-[#dadada] hover:bg-[#464646]/50'
                      }`}
                    >
                      <span className={`flex-shrink-0 w-6 h-6 rounded-md flex items-center justify-center text-xs ${
                        item.type === 'table'
                          ? 'bg-purple-900/50 text-purple-300'
                          : 'bg-blue-900/50 text-blue-300'
                      }`}>
                        {item.type === 'table' ? (
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18M3 6h18M3 18h18M8 6v12M16 6v12" /></svg>
                        ) : (
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
                        )}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{item.label}</div>
                        <div className="text-[10px] text-[#6b6b6b]">{item.kbName} &middot; {item.detail}</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
              </div>

              {/* Deliver Now — secondary action, inside the bar */}
              {!isWorkflowEnded && !isComposerBlockedByDeliverable && session && messages.length > 0 && (
                <button
                  type="button"
                  onClick={handleDeliverNow}
                  disabled={isTyping || isUploadingFile}
                  className={`${CHAT_GHOST_BTN} whitespace-nowrap`}
                  title="Force the agent to produce its deliverable now"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Deliver Now
                </button>
              )}

              {/* Send / Mic combo — primary action, far right */}
              {inputValue.trim() ? (
                <button
                  type="button"
                  onClick={() => handleSend()}
                  disabled={!session || isWorkflowEnded || isComposerBlockedByDeliverable || isUploadingFile || hasPendingParsing}
                  className={CHAT_SEND_BTN}
                  title="Send message"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={toggleListening}
                  disabled={isWorkflowEnded || isComposerBlockedByDeliverable || isUploadingFile}
                  className={`flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl transition-all duration-200 ${
                    isListening
                      ? 'animate-pulse border border-red-400 bg-red-500 text-white disabled:cursor-not-allowed disabled:opacity-40'
                      : CHAT_GHOST_ICON_BTN
                  }`}
                  title={isListening ? 'Stop recording' : 'Voice input'}
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    {isListening ? (
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0zM9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
                    ) : (
                      <>
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-14 0" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 18v3m0-3a4 4 0 01-4-4V7a4 4 0 118 0v7a4 4 0 01-4 4z" />
                      </>
                    )}
                  </svg>
                </button>
              )}
            </div>
          </div>
          <div className="mt-1.5 flex items-center justify-between px-2 text-xs text-[#6b6b6b]">
            <span>@ to mention a database, Shift+Enter for new line</span>
            <span>{inputValue.length}/2000</span>
          </div>
        </div>
      </div>

      {/* Chat Name Modal */}
      {showNameModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowNameModal(false)}>
          <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-foreground mb-4">Create New Chat</h3>
            <p className="text-sm text-muted-foreground mb-4">Give your chat session a name to help you identify it later.</p>
            <input
              type="text"
              value={newChatName}
              onChange={(e) => setNewChatName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newChatName.trim()) {
                  handleCreateChat();
                } else if (e.key === 'Escape') {
                  setShowNameModal(false);
                }
              }}
              placeholder="e.g., Banking Project Discussion"
              autoFocus
              className="w-full px-4 py-2 bg-white border border-gray-300 rounded-lg text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary mb-4"
            />
            <div className="flex gap-3 justify-end">
              <button
                onClick={handleCreateChat}
                disabled={!newChatName.trim()}
                className="px-4 py-2 bg-primary text-white border border-primary rounded-lg hover:bg-primary-hover transition-colors font-medium"
              >
                Create
              </button>
              <button
                onClick={() => setShowNameModal(false)}
                className="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}


      <AlertModal
        isOpen={showCreateError}
        title="Create Session Failed"
        message="Failed to create chat session. Please try again."
        variant="error"
        onClose={() => setShowCreateError(false)}
      />
      
      <AlertModal
        isOpen={showUploadError}
        title="Upload Failed"
        message={`Failed to upload file: ${uploadErrorMsg}`}
        variant="error"
        onClose={() => setShowUploadError(false)}
      />
      
      <ConfirmModal
        isOpen={showDeleteFileConfirm}
        title="Delete File"
        message={`Are you sure you want to delete "${fileToDelete?.name}"? This action cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
        onConfirm={confirmDeleteFile}
        onCancel={() => {
          setShowDeleteFileConfirm(false);
          setFileToDelete(null);
        }}
      />
      
      <AlertModal
        isOpen={showDeleteFileError}
        title="Delete Failed"
        message={`Failed to delete file: ${deleteFileErrorMsg}`}
        variant="error"
        onClose={() => setShowDeleteFileError(false)}
      />
      
      <AlertModal
        isOpen={showRenameError}
        title="Rename Failed"
        message="Failed to rename session. Please try again."
        variant="error"
        onClose={() => setShowRenameError(false)}
      />
      
      <AlertModal
        isOpen={showApproveError}
        title="Approve Failed"
        message={`Failed to approve deliverable: ${approveErrorMsg}`}
        variant="error"
        onClose={() => setShowApproveError(false)}
      />
      
      <AlertModal
        isOpen={showRejectError}
        title="Reject Failed"
        message={`Failed to reject deliverable: ${rejectErrorMsg}`}
        variant="error"
        onClose={() => setShowRejectError(false)}
      />

      <ConfirmModal
        isOpen={showRevertConfirm}
        title="Revert Conversation"
        message="This will revert the conversation, deliverables, and all context to the state before this message was sent. Everything after this point will be removed. Continue?"
        confirmText="Revert"
        cancelText="Cancel"
        variant="danger"
        onConfirm={handleRevertConfirm}
        onCancel={() => { setShowRevertConfirm(false); setRevertTarget(null); }}
      />

      <AlertModal
        isOpen={showRevertError}
        title="Revert Failed"
        message={`Failed to revert conversation: ${revertErrorMsg}`}
        variant="error"
        onClose={() => setShowRevertError(false)}
      />

      {/* KB Preview Modal */}
      {showKbPreview && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6">
          <div className="bg-[#1a1a1a] border-2 border-[#6b6b6b] rounded-2xl shadow-2xl flex flex-col w-full h-full max-w-[94vw] max-h-[90vh] overflow-hidden">
            {/* Modal Header */}
            <div className="px-6 py-5 flex items-start justify-between flex-shrink-0 border-b border-[#464646]">
              <div className="flex-1 min-w-0">
                <h3 className="text-2xl font-bold text-white truncate">{workflow?.name || 'Knowledge Base'}</h3>
                <p className="text-base text-[#dadada] mt-1">{kbAssets.length} knowledge base{kbAssets.length !== 1 ? 's' : ''} connected</p>
              </div>
              <button
                onClick={() => { setShowKbPreview(false); setKbPreviewDoc(null); setKbPreviewTable(null); setKbPreviewData(null); setKbPreviewExpanded(false); setKbChunksData(null); setKbChunksSearch(''); }}
                className={`w-12 h-12 rounded-[10px] ${CHAT_ICON_BTN} ml-4`}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex flex-1 overflow-hidden">
              {/* Left sidebar */}
              <div className="w-72 bg-[#1a1a1a] rounded-2xl m-4 mr-0 overflow-y-auto flex-shrink-0 scrollbar-dark p-4 flex flex-col gap-3">
                {kbAssets.map((kb) => {
                  const STRUCT_EXT = ['csv', 'xlsx', 'xls'];
                  const unstructuredDocs = (kb.documents || []).filter(d => {
                    if (d.status !== 'completed') return false;
                    const ext = (d.file_name || '').split('.').pop()?.toLowerCase();
                    return !STRUCT_EXT.includes(ext);
                  });
                  const tables = kb.structured_tables || [];

                  return (
                    <div key={kb.kb_id}>
                      <div className="text-xs font-semibold text-[#6b6b6b] uppercase tracking-wider mb-2">{kb.kb_name}</div>

                      {unstructuredDocs.length > 0 && (
                        <>
                          <p className="text-xs font-bold text-white mb-2">Documents</p>
                          <div className="flex flex-col gap-2 mb-3">
                            {unstructuredDocs.map((doc) => (
                              <button
                                key={doc.id}
                                onClick={() => {
                                  setKbPreviewDoc({ ...doc, _kbId: kb.kb_id });
                                  setKbPreviewTable(null);
                                  setKbPreviewData(null);
                                  setKbChunksData(null);
                                  setKbChunksSearch('');
                                  loadChunks(kb.kb_id, doc.id, 1, '');
                                }}
                                className={`w-full text-left px-3 py-2 flex items-center gap-2 rounded-xl text-sm transition-colors ${
                                  kbPreviewDoc?.id === doc.id
                                    ? 'bg-[#3b1c21] border border-[#d93854] text-white'
                                    : 'text-[#b5b5b5] hover:bg-[#464646]/50'
                                }`}
                              >
                                <span className="flex-shrink-0 w-6 h-6 rounded-md flex items-center justify-center">
                                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
                                </span>
                                <span className="truncate">{doc.file_name}</span>
                              </button>
                            ))}
                          </div>
                        </>
                      )}

                      {tables.length > 0 && (
                        <>
                          <p className="text-xs font-bold text-white mb-2">Tables</p>
                          <div className="flex flex-col gap-2">
                            {tables.map((tbl) => (
                              <button
                                key={tbl.id}
                                onClick={() => {
                                  setKbPreviewTable(tbl);
                                  setKbPreviewDoc(null);
                                  setKbChunksData(null);
                                  setKbChunksSearch('');
                                  if (tbl.document_id) loadTablePreview(tbl.document_id, tbl.id);
                                }}
                                className={`w-full text-left px-3 py-2 flex items-center gap-2 rounded-xl text-sm transition-colors ${
                                  kbPreviewTable?.id === tbl.id
                                    ? 'bg-[#3b1c21] border border-[#d93854] text-white'
                                    : 'text-[#b5b5b5] hover:bg-[#464646]/50'
                                }`}
                              >
                                <span className="flex-shrink-0 w-6 h-6 rounded-md flex items-center justify-center">
                                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18M3 6h18M3 18h18M8 6v12M16 6v12" /></svg>
                                </span>
                                <span className="truncate">{tbl.display_name || tbl.table_name}</span>
                              </button>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Right content area */}
              <div className="flex-1 flex flex-col overflow-hidden m-4">
                {/* ---- Unstructured doc: chunk view ---- */}
                {kbPreviewDoc && !kbPreviewTable ? (
                  <>
                    {/* Header with doc name + search */}
                    <div className="flex items-center justify-between gap-4 mb-4 flex-shrink-0">
                      <div className="min-w-0 flex-1">
                        <h4 className="text-2xl font-bold text-white truncate">{kbPreviewDoc.file_name}</h4>
                        <p className="text-base text-[#b5b5b5]">{kbChunksData?.total ?? kbPreviewDoc.chunk_count ?? 0} chunks total</p>
                      </div>
                      <div className="relative w-72 flex-shrink-0">
                        <svg className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[#6b6b6b]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
                        <input
                          type="text"
                          placeholder="Search Chunks"
                          value={kbChunksSearch}
                          onChange={(e) => {
                            const val = e.target.value;
                            setKbChunksSearch(val);
                            if (chunkSearchTimerRef.current) clearTimeout(chunkSearchTimerRef.current);
                            chunkSearchTimerRef.current = setTimeout(() => {
                              loadChunks(kbPreviewDoc._kbId, kbPreviewDoc.id, 1, val);
                            }, 400);
                          }}
                          className="w-full pl-12 pr-4 py-3 text-base bg-[#1a1a1a] border border-[#6b6b6b] rounded-2xl text-white placeholder:text-[#6b6b6b] focus:outline-none focus:border-[#d93854]"
                        />
                      </div>
                    </div>

                    {/* Chunks list */}
                    {kbChunksLoading ? (
                      <div className="flex-1 flex items-center justify-center">
                        <div className="w-8 h-8 border-2 border-[#d93854] border-t-transparent rounded-full animate-spin" />
                      </div>
                    ) : kbChunksData && (kbChunksData.chunks || []).length > 0 ? (
                      <div className="flex-1 overflow-y-auto space-y-3 scrollbar-dark">
                        {kbChunksData.chunks.map((chunk) => (
                          <div key={chunk.chunk_id} className="bg-[rgba(70,70,70,0.5)] border border-[#6b6b6b] rounded-2xl p-4 overflow-hidden">
                            <div className="flex items-center justify-between mb-3">
                              <span className="text-sm text-[#b5b5b5]">Chunk #{chunk.chunk_index + 1}</span>
                              <span className="text-sm text-[#b5b5b5]">{chunk.chunk_size} chars</span>
                            </div>
                            <p className="text-sm text-white whitespace-pre-wrap leading-relaxed max-h-32 overflow-y-auto scrollbar-dark">{chunk.chunk_text}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex-1 flex items-center justify-center text-center">
                        <p className="text-base text-[#6b6b6b]">{kbChunksSearch ? 'No chunks match your search' : 'No chunks available'}</p>
                      </div>
                    )}

                    {/* Pagination */}
                    {kbChunksData && kbChunksData.total_pages > 1 && (
                      <div className="pt-3 flex items-center justify-between text-sm text-[#b5b5b5] flex-shrink-0">
                        <span>{kbChunksData.total} chunks &middot; Page {kbChunksPage} of {kbChunksData.total_pages}</span>
                        <div className="flex gap-2">
                          <button
                            onClick={() => loadChunks(kbPreviewDoc._kbId, kbPreviewDoc.id, kbChunksPage - 1, kbChunksSearch)}
                            disabled={kbChunksPage <= 1 || kbChunksLoading}
                            className="px-4 py-2 rounded-xl bg-[#464646] hover:bg-[#555] text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >Prev</button>
                          <button
                            onClick={() => loadChunks(kbPreviewDoc._kbId, kbPreviewDoc.id, kbChunksPage + 1, kbChunksSearch)}
                            disabled={kbChunksPage >= kbChunksData.total_pages || kbChunksLoading}
                            className="px-4 py-2 rounded-xl bg-[#464646] hover:bg-[#555] text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >Next</button>
                        </div>
                      </div>
                    )}
                  </>

                ) : (kbPreviewLoading) ? (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="w-10 h-10 border-2 border-[#d93854] border-t-transparent rounded-full animate-spin" />
                  </div>

                ) : kbPreviewData && kbPreviewTable ? (
                  /* ---- Structured table view ---- */
                  <>
                    <div className="mb-4 flex-shrink-0">
                      <h4 className="text-2xl font-bold text-white">
                        {kbPreviewData.table?.display_name || kbPreviewData.table?.table_name || 'Table'}
                      </h4>
                      {kbPreviewData.table?.description && (
                        <p className="text-base text-[#b5b5b5] mt-1">{kbPreviewData.table.description}</p>
                      )}
                    </div>

                    {(kbPreviewData.tables || []).length > 1 && (
                      <div className="flex flex-wrap gap-2 mb-4 flex-shrink-0">
                        {kbPreviewData.tables.map((t) => (
                          <button
                            key={t.id}
                            onClick={() => loadTablePreview(kbPreviewTable?.document_id, t.id)}
                            className={`px-4 py-2 text-sm font-medium rounded-xl transition-all ${
                              kbPreviewData.table?.id === t.id
                                ? 'bg-[#3b1c21] border border-[#d93854] text-white'
                                : 'bg-[#464646] text-[#b5b5b5] hover:bg-[#555] hover:text-white'
                            }`}
                          >
                            {t.display_name || t.table_name} <span className="text-xs text-[#6b6b6b]">({t.row_count ?? '?'})</span>
                          </button>
                        ))}
                      </div>
                    )}

                    <div className="flex-1 overflow-auto rounded-2xl border border-[#6b6b6b] scrollbar-dark">
                      <table className="min-w-full text-sm">
                        <thead className="sticky top-0 z-10">
                          <tr className="bg-[#1a1a1a] border-b border-[#6b6b6b]">
                            {(kbPreviewData.table?.columns || []).map((col, i) => (
                              <th key={i} className="px-4 py-3 text-left font-medium text-white whitespace-nowrap">
                                <span className="mr-1">{col.display_name || col.column_name}</span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded font-normal ${
                                  col.data_type === 'integer' ? 'bg-blue-900/40 text-blue-300' :
                                  col.data_type === 'numeric' ? 'bg-purple-900/40 text-purple-300' :
                                  col.data_type === 'date' || col.data_type === 'datetime' ? 'bg-green-900/40 text-green-300' :
                                  col.data_type === 'boolean' ? 'bg-amber-900/40 text-amber-300' :
                                  'bg-[#464646] text-[#b5b5b5]'
                                }`}>{col.data_type || 'text'}</span>
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {(kbPreviewData.rows || []).map((row, ri) => (
                            <tr key={ri} className="border-b border-[#464646] hover:bg-[#1a1a1a]">
                              {(kbPreviewData.table?.columns || []).map((col, ci) => (
                                <td key={ci} className="px-4 py-2 text-[#dadada] whitespace-nowrap max-w-[250px] truncate">
                                  {Array.isArray(row) ? (row[ci] != null ? String(row[ci]) : '') : (row[col.column_name] != null ? String(row[col.column_name]) : '')}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    <div className="pt-3 flex items-center justify-between text-sm text-[#b5b5b5] flex-shrink-0">
                      <span>{kbPreviewData.total_rows ?? 0} rows &middot; Page {kbPreviewPage} of {kbPreviewData.total_pages || 1}</span>
                      <div className="flex gap-2">
                        <button
                          onClick={() => loadTablePreview(kbPreviewTable?.document_id, kbPreviewData.table?.id, kbPreviewPage - 1)}
                          disabled={kbPreviewPage <= 1}
                          className="px-4 py-2 rounded-xl bg-[#464646] hover:bg-[#555] text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >Prev</button>
                        <button
                          onClick={() => loadTablePreview(kbPreviewTable?.document_id, kbPreviewData.table?.id, kbPreviewPage + 1)}
                          disabled={kbPreviewPage >= (kbPreviewData.total_pages || 1)}
                          className="px-4 py-2 rounded-xl bg-[#464646] hover:bg-[#555] text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >Next</button>
                      </div>
                    </div>
                  </>

                ) : (
                  <div className="flex-1 flex items-center justify-center text-center">
                    <div>
                      <svg className="w-16 h-16 text-[#464646] mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <p className="text-base text-[#6b6b6b]">Select a document or table to preview</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {isReverting && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 shadow-lg flex items-center gap-3">
            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="text-sm font-medium text-foreground">Reverting conversation...</span>
          </div>
        </div>
      )}

      {/* Deliverables Expanded Modal */}
      {expandedDeliverableId && outputSteps.length > 0 && (() => {
        const activeStep = outputSteps.find(s => (s.id || s.agentId || s.agent_id) === expandedDeliverableId);
        const activeLabel = getDeliverableName(activeStep);
        const activeColor = activeStep?.agentType ? getCategoryColor(activeStep.agentType) : '#464646';
        const activeAgentKey = activeStep?.agentId || activeStep?.agent_id;
        const activeHasHitl = activeAgentKey ? agentsWithHitlFollowing.has(activeAgentKey) : false;
        const isCodeExecutorDeliverable = activeStep?.agentType === 'code-executor';
        return (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6">
          <div className="bg-[#2a2a2a] border-2 border-[#6b6b6b] rounded-2xl shadow-2xl flex flex-col w-full h-full max-w-[94vw] max-h-[90vh] overflow-hidden">
            {/* Header with title and close */}
            <div className="flex items-center gap-3 px-6 pt-5 pb-3 flex-shrink-0">
              <div
                className="flex items-center gap-2 px-4 py-2 rounded-xl"
                style={{ background: `linear-gradient(to right, ${activeColor}40, transparent)` }}
              >
                <span className="text-sm font-bold text-white">{activeLabel}</span>
                {activeHasHitl && activeStep?.status && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                    activeStep.status === 'approved' ? 'bg-green-900/50 text-green-300' :
                    activeStep.status === 'rejected' ? 'bg-red-900/50 text-red-300' :
                    'bg-yellow-900/50 text-yellow-300'
                  }`}>
                    {activeStep.status === 'approved' ? '✓ Approved' : activeStep.status === 'rejected' ? '✕ Rejected' : '⏳ Pending'}
                  </span>
                )}
              </div>
              <div className="flex-1" />
              <button
                onClick={() => setExpandedDeliverableId(null)}
                className={`w-10 h-10 rounded-[10px] ${CHAT_ICON_BTN}`}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            {/* Active deliverable content — white canvas for code-executor HTML/widgets only */}
            <div
              className={
                isCodeExecutorDeliverable
                  ? 'flex-1 overflow-auto bg-white mx-6 mb-6 rounded-2xl border border-gray-200 p-6'
                  : 'flex-1 overflow-auto bg-[#2a2a2a] mx-6 mb-6 rounded-2xl border border-[#6b6b6b] p-6 scrollbar-dark deliverable-dark-theme'
              }
            >
              {!activeStep ? (
                <div className="flex items-center justify-center text-[#6b6b6b] h-full">No deliverable selected</div>
              ) : (
                <DeliverableReview
                  deliverable={activeStep}
                  executionId={activeExecutionId}
                  onApprove={handleApproveDeliverable}
                  onReject={handleRejectDeliverable}
                  onWidgetRespond={handleWidgetRespond}
                  isProcessing={isProcessingDeliverable}
                  initialSectionIndex={expandedInitialSection}
                  templateId={(() => { const aid = activeStep.agentId || activeStep.agent_id; if (!aid || !workflow) return null; const { nodes } = parseWorkflowGraph(); const n = nodes.find(nd => nd.id === aid); return n?.config?.templateId || null; })()}
                />
              )}
            </div>
          </div>
        </div>
        );
      })()}

      {/* Output Side Panel */}
      {showOutputPanel && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/30"
            onClick={() => setShowOutputPanel(false)}
          />
          <div className="fixed top-0 right-0 h-full w-[500px] max-w-[94vw] z-40 bg-[#1a1a1a] border-l border-[#464646] shadow-2xl flex flex-col output-panel-slide">
            {/* Panel Header */}
            <div className="flex items-center justify-between px-6 pt-6 pb-4 flex-shrink-0">
              <div>
                <h2 className="text-2xl font-bold text-white">Output</h2>
                <div className="mt-1 text-xs text-[#8b8b8b]">
                  {(() => {
                    const n = outputSteps.filter((s) => !hiddenDeliverableAgentIds.has(s.agentId || s.agent_id)).length;
                    return n === 1 ? '1 deliverable' : `${n} deliverables`;
                  })()}
                </div>
              </div>
              <button
                onClick={() => setShowOutputPanel(false)}
                className={`w-9 h-9 rounded-[10px] ${CHAT_ICON_BTN}`}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            {/* Tree content */}
            <div className="flex-1 overflow-y-auto px-6 pb-6 scrollbar-dark">
              {outputSteps.filter(s => !hiddenDeliverableAgentIds.has(s.agentId || s.agent_id)).length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <svg className="w-12 h-12 text-[#464646] mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <p className="text-sm text-[#6b6b6b]">No deliverables yet</p>
                </div>
              ) : (
                <div className="relative pl-4">
                  {/* Vertical connector line */}
                  <div className="absolute left-[7px] top-6 bottom-6 w-px bg-[#353535]" />

                  <div className="space-y-6">
                    {outputSteps.filter(s => !hiddenDeliverableAgentIds.has(s.agentId || s.agent_id)).map((step, stepIdx) => {
                      const stepId = step.id || step.agentId || step.agent_id;
                      const stepLabel = getDeliverableName(step);
                      const stepNodeInfo = step.agentType ? getNodeInfo(step.agentType) : null;
                      const stepColor = step.agentType ? getCategoryColor(step.agentType) : '#464646';
                      const isCodeExecutor = step.agentType === 'code-executor';
                      // Don't let the panel open a deliverable whose OpenUI is
                      // still translating -- it would show an empty expanded view.
                      const openUINotReady = requiresOpenUI(step) && !hasRenderableOpenUI(step);

                      // Parse sections for sub-items
                      let sections = [];
                      if (!isCodeExecutor && step.deliverable) {
                        let content = step.deliverable;
                        if (typeof content === 'string') {
                          try { content = JSON.parse(content); } catch { content = null; }
                        }
                        if (content?.sections && Array.isArray(content.sections)) {
                          sections = content.sections;
                        } else if (typeof content === 'object' && content !== null) {
                          sections = [{ section_title: content.title || 'Output' }];
                        }
                      }
                      const showSections = sections.length > 1;
                      const statusPill =
                        step.status === 'approved' ? { cls: 'border-emerald-900/60 bg-emerald-900/30 text-emerald-300', txt: 'Approved' }
                          : step.status === 'rejected' ? { cls: 'border-red-900/60 bg-red-900/40 text-red-300', txt: 'Rejected' }
                            : step.status === 'pending' ? { cls: 'border-yellow-900/60 bg-yellow-900/30 text-yellow-300', txt: 'Pending' }
                              : null;

                      return (
                        <div key={stepId || stepIdx} className="relative">
                          {/* Dot on the connector line (category-colored, trace style) */}
                          <div className="absolute -left-3 top-4 w-[7px] h-[7px] rounded-full border-2 z-10" style={{ borderColor: stepColor, background: '#1a1a1a' }} />

                          {/* Deliverable card (trace-style) */}
                          <button
                            onClick={() => !openUINotReady && openExpandedDeliverable(stepId, 0)}
                            disabled={openUINotReady}
                            title={openUINotReady ? 'Generating view...' : undefined}
                            className="w-full flex items-center gap-3 rounded-xl border border-[#464646] bg-[#202020] px-4 py-3 text-left shadow-[0_8px_24px_rgba(0,0,0,0.16)] transition-all hover:border-[#6b6b6b] hover:bg-[#262626] group disabled:opacity-50 disabled:cursor-default disabled:hover:bg-[#202020]"
                          >
                            {stepNodeInfo?.icon && (
                              <span className="flex h-7 w-7 items-center justify-center rounded-lg flex-shrink-0" style={{ background: `${stepColor}33` }}>
                                {stepNodeInfo.icon.startsWith('/') ? (
                                  <img src={stepNodeInfo.icon} alt={stepNodeInfo.name} className="h-4 w-4 brightness-0 invert" />
                                ) : (
                                  <span className="text-sm">{stepNodeInfo.icon}</span>
                                )}
                              </span>
                            )}
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-semibold text-white">{stepLabel}</div>
                              <div className="mt-0.5 truncate text-[11px] text-[#8b8b8b]">
                                {step.agentLabel}{showSections ? ` · ${sections.length} sections` : ''}
                              </div>
                            </div>
                            {statusPill && (
                              <span className={`flex-shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${statusPill.cls}`}>{statusPill.txt}</span>
                            )}
                            {openUINotReady ? (
                              <svg className="animate-spin w-4 h-4 text-white/60 flex-shrink-0" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                              </svg>
                            ) : (
                              <svg className="w-4 h-4 text-[#6b6b6b] group-hover:text-white transition-colors flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 17l9.2-9.2M17 17V7H7" />
                              </svg>
                            )}
                          </button>

                          {/* Section sub-items */}
                          {showSections && !openUINotReady && (
                            <div className="relative ml-8 mt-2 space-y-1">
                              {/* Section connector line */}
                              <div className="absolute left-[7px] top-2 bottom-2 w-px bg-[#353535]" />

                              {sections.map((section, secIdx) => (
                                <button
                                  key={secIdx}
                                  onClick={() => openExpandedDeliverable(stepId, secIdx)}
                                  className="relative w-full flex items-center gap-2.5 pl-5 pr-3 py-2 rounded-lg hover:bg-[#2a2a2a] transition-colors group"
                                >
                                  {/* Sub-item dot */}
                                  <div className="absolute left-[5px] top-1/2 -translate-y-1/2 w-[5px] h-[5px] rounded-full bg-[#6b6b6b]" />
                                  <svg className="w-4 h-4 text-[#6b6b6b] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                                  </svg>
                                  <span className="flex-1 text-xs text-[#b5b5b5] group-hover:text-white text-left truncate transition-colors">
                                    {section.section_title || `Section ${secIdx + 1}`}
                                  </span>
                                  <svg className="w-3.5 h-3.5 text-[#6b6b6b] group-hover:text-white transition-colors flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 17l9.2-9.2M17 17V7H7" />
                                  </svg>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {showTracePanel && (
        <TraceSidePanel
          executionId={activeExecutionId}
          onClose={() => setShowTracePanel(false)}
        />
      )}

      {/* Workflow Guide Modal */}
      <WorkflowDescriptionViewer
        isOpen={showWorkflowGuide}
        onClose={() => setShowWorkflowGuide(false)}
        data={workflowGuideData}
      />

      {/* Project picker shown after naming a new chat */}
      <ProjectPickerModal
        isOpen={showChatProjectPicker}
        onClose={() => {
          setShowChatProjectPicker(false);
          pendingChatNameRef.current = '';
        }}
        onSelect={handleChatProjectSelected}
      />
    </div>
  );
}
