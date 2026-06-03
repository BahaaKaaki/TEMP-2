import { useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '@/api/client';
import { getAccessToken } from '@/api/auth-client';
import { getMessageBubbleGradient } from '../builder/nodeCategoryStyles';

const MAX_DISPLAY_CHARS = 1200;

/** Category header (uppercase in UI) for router decisions and activity rows. */
const ACTION_DISPLAY = {
  chat: { label: 'Chat', fallback: 'Continuing the conversation…' },
  search_kb: { label: 'Knowledge base', fallback: 'Searching the knowledge base…' },
  ask_user_questions: { label: 'Questions', fallback: 'Preparing your questions…' },
  deep_research: { label: 'Deep research', fallback: 'Starting deep research…' },
  simple_web_search: { label: 'Web search', fallback: 'Searching the web…' },
  query_structured_data: { label: 'Data analysis', fallback: 'Analyzing your data…' },
  submit_deliverable: { label: 'Deliverable', fallback: 'Compiling the deliverable…' },
  use_tool: { label: 'Tool', fallback: 'Running a tool…' },
  submit: { label: 'Response', fallback: 'Submitting the response…' },
};

/** Prefer human-readable string fields; never surface raw JSON in the UI. */
const DETAIL_KEYS = [
  'query',
  'question',
  'reason',
  'prompt',
  'search_query',
  'input',
  'text',
  'message',
  'description',
  'topic',
  'q',
];

const DETAIL_SKIP_KEYS = new Set([
  'action',
  'type',
  'tool',
  'tools',
  'metadata_filters',
  'document_name',
  'table_name',
]);

function clampText(s, max = MAX_DISPLAY_CHARS) {
  if (!s || typeof s !== 'string') return '';
  const t = s.trim().replace(/\s+/g, ' ');
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`;
}

function humanizeIdentifier(raw) {
  if (!raw || typeof raw !== 'string') return 'Tool';
  const spaced = raw
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/([a-z])(kb)\b/gi, '$1 $2')
    .replace(/[_\-./]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!spaced) return 'Tool';

  return spaced
    .split(' ')
    .map((word) => {
      const lower = word.toLowerCase();
      if (lower === 'kb') return 'KB';
      if (lower === 'ai') return 'AI';
      if (lower === 'om') return 'OM';
      if (/^[a-z]{1,2}$/i.test(word)) return word.toUpperCase();
      if (/^\d+$/.test(word)) return word;
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(' ');
}

function extractDetail(payload) {
  if (!payload || typeof payload !== 'object') return '';

  for (const key of DETAIL_KEYS) {
    const value = payload[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }

  const extras = [];
  if (typeof payload.document_name === 'string' && payload.document_name.trim()) {
    extras.push(`document: ${payload.document_name.trim()}`);
  }
  if (typeof payload.table_name === 'string' && payload.table_name.trim()) {
    extras.push(`table: ${payload.table_name.trim()}`);
  }

  for (const [key, value] of Object.entries(payload)) {
    if (DETAIL_SKIP_KEYS.has(key)) continue;
    if (typeof value === 'string' && value.trim()) {
      const main = value.trim();
      return extras.length ? `${main} (${extras.join(' · ')})` : main;
    }
  }

  if (extras.length) {
    return extras.join(' · ');
  }

  return '';
}

function actionSubtitle(action, type) {
  if (!action || typeof action !== 'object') return null;
  if (type === 'query_structured_data' && action.table_name) {
    return `Table: ${humanizeIdentifier(String(action.table_name))}`;
  }
  if (type === 'search_kb' && action.document_name) {
    return `Document: ${String(action.document_name).trim()}`;
  }
  if (type === 'use_tool' && action.tool) {
    return humanizeIdentifier(String(action.tool));
  }
  return null;
}

function resolveToolCategoryLabel(toolName) {
  const key = String(toolName || '').toLowerCase();
  if (key === 'deep_research' || key.includes('deep_research')) {
    return ACTION_DISPLAY.deep_research.label;
  }
  if (key === 'simple_web_search' || key.includes('web_search')) {
    return ACTION_DISPLAY.simple_web_search.label;
  }
  if (key.includes('structured') || key.startsWith('query_')) {
    return ACTION_DISPLAY.query_structured_data.label;
  }
  if (key.includes('ask_user') || key.includes('question')) {
    return ACTION_DISPLAY.ask_user_questions.label;
  }
  if (key.startsWith('search_') || key.includes('research') || key.includes('kb')) {
    return ACTION_DISPLAY.search_kb.label;
  }
  return 'Tool';
}

function formatToolCall(toolName, args) {
  const name = humanizeIdentifier(toolName);
  const detail = clampText(extractDetail(args));
  const label = resolveToolCategoryLabel(toolName);
  return {
    label,
    subtitle: name,
    text: detail || 'Running…',
  };
}

function formatAction(action) {
  if (!action || typeof action !== 'object') {
    return { label: 'Next step', subtitle: null, text: 'Choosing what to do next…' };
  }

  const type = action.action || action.type || '';
  if (type === 'use_tool' && action.tool) {
    return formatToolCall(action.tool, action);
  }

  const display = ACTION_DISPLAY[type] || {
    label: humanizeIdentifier(type),
    fallback: 'Continuing…',
  };
  const detail = clampText(extractDetail(action));
  const subtitle = actionSubtitle(action, type);

  return {
    label: display.label,
    subtitle,
    text: detail || display.fallback,
  };
}

function mergedSpanPayload(span) {
  const out = {};
  for (const ev of span.events || []) {
    Object.assign(out, ev.payload || {});
  }
  return out;
}

function formatDeepResearch(payload, phase) {
  const display = ACTION_DISPLAY.deep_research;
  const detail = clampText(extractDetail(payload));
  if (phase === 'failed') {
    return {
      label: display.label,
      subtitle: null,
      text: clampText(payload.error || 'Deep research failed'),
    };
  }
  if (phase === 'completed') {
    return {
      label: display.label,
      subtitle: null,
      text: detail || 'Deep research finished',
    };
  }
  if (phase === 'queued') {
    return {
      label: display.label,
      subtitle: null,
      text: detail || 'Queued…',
    };
  }
  return {
    label: display.label,
    subtitle: null,
    text: detail || display.fallback,
  };
}

function formatStructuredData(payload, phase) {
  const display = ACTION_DISPLAY.query_structured_data;
  const detail = clampText(payload.question || extractDetail(payload));
  const subtitle = payload.kb_name
    ? humanizeIdentifier(String(payload.kb_name))
    : (payload.table_name ? `Table: ${humanizeIdentifier(String(payload.table_name))}` : null);

  if (phase === 'failed') {
    return {
      label: display.label,
      subtitle,
      text: clampText(payload.error || 'Data analysis failed'),
    };
  }
  if (phase === 'completed') {
    return {
      label: display.label,
      subtitle,
      text: detail || 'Analysis complete',
    };
  }
  return {
    label: display.label,
    subtitle,
    text: detail || display.fallback,
  };
}

function formatKbResearch(payload, phase) {
  const display = ACTION_DISPLAY.search_kb;
  const detail = clampText(payload.question || extractDetail(payload));
  const subtitle = payload.kb_name
    ? humanizeIdentifier(String(payload.kb_name))
    : (payload.document_name ? `Document: ${payload.document_name}` : null);

  if (phase === 'failed') {
    return {
      label: display.label,
      subtitle,
      text: clampText(payload.error || 'Knowledge base search failed'),
    };
  }
  if (phase === 'completed') {
    return {
      label: display.label,
      subtitle,
      text: detail || 'Search complete',
    };
  }
  return {
    label: display.label,
    subtitle,
    text: detail || 'Searching the knowledge base…',
  };
}

function formatKbSearch(payload) {
  const count = payload.sub_query_count;
  const subtitle = count != null ? `${count} parallel searches` : null;
  return {
    label: ACTION_DISPLAY.search_kb.label,
    subtitle,
    text: 'Running knowledge base searches…',
  };
}

function formatAskQuestions(payload, phase) {
  const display = ACTION_DISPLAY.ask_user_questions;
  const detail = clampText(extractDetail(payload));
  const count = payload.question_count;
  const subtitle = count != null ? `${count} questions` : null;

  if (phase === 'completed') {
    return {
      label: display.label,
      subtitle,
      text: detail || (count ? `Prepared ${count} questions` : 'Questions ready'),
    };
  }
  return {
    label: display.label,
    subtitle,
    text: detail || display.fallback,
  };
}

function formatToolList(tools) {
  if (!Array.isArray(tools) || !tools.length) return '';
  return tools
    .slice(0, 4)
    .map((name) => humanizeIdentifier(String(name)))
    .join(', ');
}

function spanKind(span) {
  const type = span.started?.event_type || span.events[0]?.event_type || '';
  if (type.startsWith('tool_decider')) return 'tool_decider';
  if (type.startsWith('tool.')) return 'tool';
  if (type.startsWith('deep_research')) return 'deep_research';
  if (type.startsWith('structured_data')) return 'structured_data';
  if (type.startsWith('kb_research')) return 'kb_research';
  if (type.startsWith('kb_search')) return 'kb_search';
  if (type.startsWith('ask_questions')) return 'ask_questions';
  if (type.startsWith('llm')) return 'llm';
  return 'other';
}

function isRunning(span) {
  return Boolean(span.started && !span.completed && !span.failed);
}

function isToolCallerLlm(span, spans) {
  if (span.operation === 'llm.tool_calling') return true;
  const parentId = span.parent_span_id;
  if (!parentId) return false;
  const parent = spans.get(parentId);
  return parent ? spanKind(parent) === 'tool_decider' : false;
}

function runningPriority(span, spans) {
  const kind = spanKind(span);
  if (kind === 'tool' && isRunning(span)) return 500;
  if (kind === 'deep_research' && isRunning(span)) return 400;
  if (kind === 'structured_data' && isRunning(span)) return 390;
  if (kind === 'kb_research' && isRunning(span)) return 385;
  if (kind === 'kb_search' && isRunning(span)) return 375;
  if (kind === 'ask_questions' && isRunning(span)) return 370;
  if (kind === 'llm') {
    if (isRunning(span)) {
      if (span.operation === 'llm.tool_calling') return 360;
      if (span.reasoning && isToolCallerLlm(span, spans)) return 355;
      if (isToolCallerLlm(span, spans)) return 350;
      if (span.reasoning) return 340;
      if (span.operation === 'llm.structured_output') return 220;
      return 300;
    }
    if (span.reasoning && isToolCallerLlm(span, spans)) {
      const parent = spans.get(span.parent_span_id);
      if (parent && isRunning(parent)) return 345;
    }
  }
  if (kind === 'tool_decider' && isRunning(span)) return 330;
  return 0;
}

function activityTimestamp(span) {
  return (
    span.failed?.timestamp
    || span.completed?.timestamp
    || span.started?.timestamp
    || span.events[span.events.length - 1]?.timestamp
    || ''
  );
}

function lineFromParts({ tone, label, subtitle, text, key }) {
  return {
    tone,
    label,
    subtitle: subtitle || null,
    text,
    key: key || `${label}-${(subtitle || text).slice(0, 24)}`,
    at: Date.now(),
  };
}

function formatRunningSpan(span, spans) {
  const kind = spanKind(span);
  const payload = span.started?.payload || {};

  if (kind === 'tool_decider') {
    return lineFromParts({
      tone: 'decision',
      label: 'Next step',
      text: 'Choosing what to do next…',
      key: `decider-${span.span_id}`,
    });
  }

  if (kind === 'tool') {
    const formatted = formatToolCall(
      payload.tool_name || payload.label || 'tool',
      payload.args
    );
    return lineFromParts({
      tone: 'tool',
      ...formatted,
      key: `tool-${span.span_id}`,
    });
  }

  if (kind === 'deep_research') {
    const payload = mergedSpanPayload(span);
    const type = span.started?.event_type || '';
    const phase = type.endsWith('.queued') ? 'queued' : 'starting';
    return lineFromParts({
      tone: 'tool',
      ...formatDeepResearch(payload, phase),
      key: `research-${span.span_id}`,
    });
  }

  if (kind === 'structured_data') {
    return lineFromParts({
      tone: 'tool',
      ...formatStructuredData(mergedSpanPayload(span), 'running'),
      key: `structured-${span.span_id}`,
    });
  }

  if (kind === 'kb_research') {
    return lineFromParts({
      tone: 'tool',
      ...formatKbResearch(mergedSpanPayload(span), 'running'),
      key: `kb-research-${span.span_id}`,
    });
  }

  if (kind === 'kb_search') {
    return lineFromParts({
      tone: 'tool',
      ...formatKbSearch(mergedSpanPayload(span)),
      key: `kb-search-${span.span_id}`,
    });
  }

  if (kind === 'ask_questions') {
    return lineFromParts({
      tone: 'decision',
      ...formatAskQuestions(mergedSpanPayload(span), 'running'),
      key: `ask-${span.span_id}`,
    });
  }

  if (kind === 'llm') {
    const op = span.operation || payload.operation || 'llm';
    const toolCaller = isToolCallerLlm(span, spans);

    if (span.reasoning) {
      return lineFromParts({
        tone: 'reasoning',
        label: toolCaller || op === 'llm.tool_calling' ? 'Tool caller' : 'Reasoning',
        text: clampText(span.reasoning),
        key: `reasoning-${span.span_id}`,
      });
    }

    if (op === 'llm.tool_calling') {
      return lineFromParts({
        tone: 'reasoning',
        label: 'Tool model',
        text: 'Preparing tool use…',
        key: `llm-tools-${span.span_id}`,
      });
    }

    if (toolCaller) {
      return lineFromParts({
        tone: 'reasoning',
        label: 'Tool caller',
        text: 'Planning next step…',
        key: `tool-caller-${span.span_id}`,
      });
    }

    if (op === 'llm.structured_output') {
      return lineFromParts({
        tone: 'reasoning',
        label: 'Model',
        text: 'Structuring the reply…',
        key: `llm-struct-${span.span_id}`,
      });
    }

    return lineFromParts({
      tone: 'reasoning',
      label: 'Model',
      text: 'Thinking…',
      key: `llm-${span.span_id}`,
    });
  }

  return null;
}

function formatRecentSpan(span, spans) {
  const kind = spanKind(span);
  const payload = span.completed?.payload || span.failed?.payload || span.started?.payload || {};

  if (kind === 'tool_decider') {
    if (span.failed) {
      return lineFromParts({
        tone: 'error',
        label: 'Routing',
        text: clampText(payload.error || 'Tool routing failed'),
      });
    }
    if (span.completed && payload.action) {
      const formatted = formatAction(payload.action);
      return lineFromParts({
        tone: 'decision',
        ...formatted,
      });
    }
  }

  if (kind === 'tool') {
    const formatted = formatToolCall(
      payload.tool_name || payload.label || 'tool',
      payload.args
    );
    if (span.failed) {
      return lineFromParts({
        tone: 'error',
        ...formatted,
        text: clampText(
          payload.error ? `${formatted.text} — ${payload.error}` : `${formatted.text} — failed`
        ),
      });
    }
    if (span.completed) {
      return lineFromParts({
        tone: 'tool',
        ...formatted,
        text: formatted.text === 'Running…' ? 'Done' : `${formatted.text} — done`,
      });
    }
  }

  if (kind === 'deep_research') {
    const merged = mergedSpanPayload(span);
    if (span.failed) {
      return lineFromParts({ tone: 'error', ...formatDeepResearch(merged, 'failed') });
    }
    if (span.completed) {
      return lineFromParts({ tone: 'tool', ...formatDeepResearch(merged, 'completed') });
    }
  }

  if (kind === 'structured_data') {
    const merged = mergedSpanPayload(span);
    if (span.failed) {
      return lineFromParts({ tone: 'error', ...formatStructuredData(merged, 'failed') });
    }
    if (span.completed) {
      return lineFromParts({ tone: 'tool', ...formatStructuredData(merged, 'completed') });
    }
  }

  if (kind === 'kb_research') {
    const merged = mergedSpanPayload(span);
    if (span.failed) {
      return lineFromParts({ tone: 'error', ...formatKbResearch(merged, 'failed') });
    }
    if (span.completed) {
      return lineFromParts({ tone: 'tool', ...formatKbResearch(merged, 'completed') });
    }
  }

  if (kind === 'ask_questions') {
    const merged = mergedSpanPayload(span);
    if (span.failed) {
      return lineFromParts({
        tone: 'error',
        label: ACTION_DISPLAY.ask_user_questions.label,
        text: clampText(merged.error || 'Failed to prepare questions'),
      });
    }
    if (span.completed) {
      return lineFromParts({ tone: 'decision', ...formatAskQuestions(merged, 'completed') });
    }
  }

  if (kind === 'llm') {
    const op = span.operation || payload.operation || 'llm';
    const toolCaller = isToolCallerLlm(span, spans);

    if (span.reasoning && (toolCaller || op === 'llm.tool_calling')) {
      return lineFromParts({
        tone: 'reasoning',
        label: toolCaller ? 'Tool caller' : 'Tool model',
        text: clampText(span.reasoning),
        key: `reasoning-done-${span.span_id}`,
      });
    }

    if (span.completed && op === 'llm.tool_calling') {
      const toolList = formatToolList(payload.tools);
      return lineFromParts({
        tone: 'tool',
        label: 'Tool plan',
        text: toolList ? `Ready to call ${toolList}` : 'Ready to call tools',
      });
    }
  }

  return null;
}

function deriveLiveLine(spans) {
  const all = Array.from(spans.values());
  if (!all.length) return null;

  const running = all
    .filter((span) => {
      if (isRunning(span)) return true;
      if (span.reasoning && isToolCallerLlm(span, spans)) {
        const parent = spans.get(span.parent_span_id);
        return Boolean(parent && isRunning(parent));
      }
      return false;
    })
    .sort((a, b) => runningPriority(b, spans) - runningPriority(a, spans));

  for (const span of running) {
    const line = formatRunningSpan(span, spans);
    if (line) return line;
  }

  let best = null;
  let bestTs = '';
  for (const span of all) {
    const line = formatRecentSpan(span, spans);
    if (!line) continue;
    const ts = activityTimestamp(span);
    if (ts >= bestTs) {
      bestTs = ts;
      best = line;
    }
  }
  return best;
}

function ingestTraceEvent(spans, spanOps, ev) {
  const type = ev.event_type || '';
  if (type.startsWith('node.')) return;

  const spanId = ev.span_id;
  if (!spanId) return;

  let span = spans.get(spanId);
  if (!span) {
    span = {
      span_id: spanId,
      parent_span_id: ev.parent_span_id,
      events: [],
      operation: null,
      reasoning: '',
      action: null,
    };
    spans.set(spanId, span);
  }

  if (ev.parent_span_id) span.parent_span_id = ev.parent_span_id;
  span.events.push(ev);

  const payload = ev.payload || {};
  if (type.endsWith('.started')) span.started = ev;
  if (type.endsWith('.completed')) span.completed = ev;
  if (type.endsWith('.failed')) span.failed = ev;

  if (type === 'llm.started' && payload.operation) {
    span.operation = payload.operation;
    spanOps.set(spanId, payload.operation);
  }

  if (payload.reasoning_summary) {
    span.reasoning = payload.reasoning_summary;
  }

  if (type === 'tool_decider.completed' && payload.action) {
    span.action = payload.action;
  }
}

export function traceLineLabelClass(line) {
  if (!line) return 'text-[#d93854]';
  if (line.tone === 'error') return 'text-red-400';
  if (line.tone === 'decision') return 'text-amber-400/90';
  if (line.tone === 'tool') return 'text-cyan-400/90';
  return 'text-[#d93854]';
}

export function TypingIndicatorDots({ className = '' }) {
  return (
    <div className={`flex shrink-0 items-center gap-1 self-center ${className}`} aria-hidden>
      <span className="h-1.5 w-1.5 rounded-full bg-[#d93854] animate-bounce [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 rounded-full bg-[#d93854] animate-bounce [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 rounded-full bg-[#d93854] animate-bounce" />
    </div>
  );
}

/** Circular loader for an in-progress agent / LLM reply. Use `embedded` inside the bubble. */
export function AgentReplySpinner({ className = '', size = 22, embedded = false }) {
  return (
    <div
      className={`flex shrink-0 items-center justify-center ${embedded ? 'mt-0.5' : 'self-start'} ${className}`}
      style={embedded ? undefined : { marginTop: size * 0.45 }}
      role="status"
      aria-label="Generating reply"
    >
      <div
        className="rounded-full border-2 border-[#d93854]/25 border-t-[#d93854] animate-spin"
        style={{ width: size, height: size }}
        aria-hidden
      />
    </div>
  );
}

export function TraceActivityLine({ line, executionId }) {
  if (line) {
    return (
      <ActivityLine
        key={line.key}
        labelCls={traceLineLabelClass(line)}
        label={line.label}
        subtitle={line.subtitle}
        text={line.text}
      />
    );
  }
  return (
    <p className="text-[12px] text-[#9a9a9a]">
      {!executionId ? 'Getting ready…' : 'Working…'}
    </p>
  );
}

/** Subscribe to execution trace stream; returns the current live step line. */
export function useExecutionTraceLine(executionId) {
  const [line, setLine] = useState(null);
  const eventIdsRef = useRef(new Set());
  const spansRef = useRef(new Map());
  const spanOpsRef = useRef(new Map());
  const refreshRafRef = useRef(null);

  useEffect(() => {
    if (!executionId) {
      setLine(null);
      spansRef.current = new Map();
      spanOpsRef.current = new Map();
      return undefined;
    }

    setLine(null);
    eventIdsRef.current = new Set();
    spansRef.current = new Map();
    spanOpsRef.current = new Map();

    const accessToken = getAccessToken();
    if (!accessToken) return undefined;

    const scheduleRefresh = () => {
      if (refreshRafRef.current != null) return;
      refreshRafRef.current = requestAnimationFrame(() => {
        refreshRafRef.current = null;
        const next = deriveLiveLine(spansRef.current);
        if (next) {
          setLine((prev) => (
            prev?.key === next.key
              && prev?.text === next.text
              && prev?.subtitle === next.subtitle
              ? prev
              : { ...next, at: Date.now() }
          ));
        }
      });
    };

    const qs = `?token=${encodeURIComponent(accessToken)}`;
    const url = `${API_BASE_URL}/api/executions/${executionId}/trace/stream${qs}`;
    const es = new EventSource(url, { withCredentials: true });

    es.addEventListener('trace', (e) => {
      try {
        if (e.lastEventId) {
          if (eventIdsRef.current.has(e.lastEventId)) return;
          eventIdsRef.current.add(e.lastEventId);
        }
        const parsed = JSON.parse(e.data);
        ingestTraceEvent(spansRef.current, spanOpsRef.current, parsed);
        scheduleRefresh();
      } catch {
        // ignore
      }
    });

    return () => {
      if (refreshRafRef.current != null) {
        cancelAnimationFrame(refreshRafRef.current);
        refreshRafRef.current = null;
      }
      es.close();
    };
  }, [executionId]);

  return line;
}

/**
 * Compact live activity from execution trace (tool caller, LLM reasoning, tools).
 * Keeps span state so Redis replay bursts do not drop tool-caller / tool steps.
 */
export default function ChatLiveActivity({ executionId }) {
  const line = useExecutionTraceLine(executionId);

  return (
    <div className="flex gap-3 min-w-0 w-full max-w-full animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div
        className="flex min-w-0 w-full flex-1 items-center gap-3 rounded-2xl border border-[#6b6b6b] px-4 py-3 shadow-inner"
        style={{ background: getMessageBubbleGradient('agent') }}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <TraceActivityLine line={line} executionId={executionId} />
        </div>
        <TypingIndicatorDots />
      </div>
    </div>
  );
}

function ActivityLine({ labelCls, label, subtitle, text }) {
  return (
    <div className="min-w-0 w-full transition-all duration-200 ease-out">
      <div className={`text-[10px] font-bold uppercase tracking-wider ${labelCls}`}>{label}</div>
      {subtitle ? (
        <p className="text-[12px] font-medium text-neutral-200 break-words">{subtitle}</p>
      ) : null}
      <p className="text-[13px] leading-relaxed text-neutral-100 break-words whitespace-pre-wrap">
        {text}
      </p>
    </div>
  );
}
