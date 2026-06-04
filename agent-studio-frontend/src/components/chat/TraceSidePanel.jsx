import { useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE_URL } from '@/api/client';
import { getAccessToken } from '@/api/auth-client';
import { CHAT_ICON_BTN } from './chatButtonStyles';

function formatDuration(ms) {
  if (ms === null || ms === undefined) return '';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

function eventTitle(event) {
  const payload = event.payload || {};
  if (payload.label) return payload.label;
  if (payload.tool_name) return payload.tool_name;
  return event.event_type?.replace(/\./g, ' ') || 'Trace event';
}

function statusClass(status) {
  if (status === 'error') return 'bg-red-900/40 text-red-300 border-red-900/60';
  if (status === 'success') return 'bg-emerald-900/30 text-emerald-300 border-emerald-900/60';
  return 'bg-blue-900/30 text-blue-300 border-blue-900/60';
}

function statusDotClass(status) {
  if (status === 'error') return 'border-[#d93854] bg-[#d93854]';
  if (status === 'success') return 'border-emerald-400 bg-emerald-400';
  return 'border-cyan-300 bg-cyan-300 animate-pulse';
}

function kindLabel(eventType) {
  if (eventType?.startsWith('node.')) return 'Node';
  if (eventType?.startsWith('llm.')) return 'LLM';
  if (eventType?.startsWith('tool_decider.')) return 'Tool Decider';
  if (eventType?.startsWith('tool.')) return 'Tool';
  if (eventType?.startsWith('kb_')) return 'Knowledge Base';
  if (eventType?.startsWith('structured_')) return 'Structured Data';
  if (eventType?.startsWith('deep_research.')) return 'Deep Research';
  if (eventType?.startsWith('ask_questions.')) return 'Ask Questions';
  return 'Step';
}

function kindColor(eventType) {
  if (eventType?.startsWith('llm.')) return 'text-violet-300';
  if (eventType?.startsWith('tool_decider.')) return 'text-amber-300';
  if (eventType?.startsWith('tool.')) return 'text-sky-300';
  if (eventType?.startsWith('kb_')) return 'text-cyan-300';
  return 'text-[#d93854]';
}

function payloadRows(payload = {}) {
  const hidden = new Set([
    'label',
    'reasoning_summary',
    'reasoning_summary_delta_chars',
    'message_count',
    'message_types',
    'node_type',
    'operation',
    'provider',
    'streaming',
    'max_tokens',
  ]);
  const priority = new Map([
    ['model', 0],
    ['schema', 1],
    ['message_preview', 2],
    ['response_type', 3],
    ['content_chars', 4],
    ['output_text_chars', 5],
  ]);
  return Object.entries(payload)
    .filter(([key, value]) => !hidden.has(key) && value !== null && value !== undefined && value !== '')
    .sort(([left], [right]) => (priority.get(left) ?? 20) - (priority.get(right) ?? 20))
    .slice(0, 8);
}

function humanizeTraceKey(key) {
  const labels = {
    model: 'Model',
    schema: 'Output schema',
    message_preview: 'Messages',
    input_fields: 'Inputs',
    output_fields: 'Outputs',
    available_tools: 'Tools',
    top_k: 'Top K',
    retrieved_chunks: 'Retrieved chunks',
    kb_name: 'Knowledge base',
    sub_query_count: 'Sub queries',
    query: 'Query',
    action: 'Action',
    iteration: 'Iteration',
    response_type: 'Response',
    content_chars: 'Content chars',
    output_text_chars: 'Output chars',
  };
  return labels[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSchemaSummary(value) {
  if (!value) return '';
  let parsed = value;
  if (typeof value === 'string') {
    try {
      parsed = JSON.parse(value);
    } catch {
      return value;
    }
  }
  if (!parsed || typeof parsed !== 'object') return String(value);
  const title = parsed.title || parsed.name || 'Schema';
  const type = parsed.type ? String(parsed.type) : null;
  const properties = Array.isArray(parsed.properties)
    ? parsed.properties
    : parsed.properties && typeof parsed.properties === 'object'
      ? Object.keys(parsed.properties)
      : [];
  const fields = properties.length ? `Fields: ${properties.join(', ')}` : null;
  return [title, type, fields].filter(Boolean).join(' · ');
}

function formatMaybeJsonText(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  if (!text.startsWith('{') && !text.startsWith('[')) return text;
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function truncateText(text, max = 140) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (!value) return '';
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function stringifyTraceValue(value) {
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function messageRole(message) {
  return String(message?.type || 'Message').replace(/Message$/, '');
}

function roleClass(role) {
  if (role === 'System') return 'border-violet-400/30 bg-violet-500/10 text-violet-200';
  if (role === 'AI') return 'border-cyan-400/30 bg-cyan-500/10 text-cyan-200';
  if (role === 'Human') return 'border-[#d93854]/30 bg-[#d93854]/10 text-[#ff8ba0]';
  return 'border-white/15 bg-white/[0.04] text-[#dadada]';
}

function TraceMessages({ messages }) {
  if (!Array.isArray(messages) || messages.length === 0) return null;
  return (
    <details className="rounded-lg border border-[#353535] bg-[#1a1a1a] p-2.5">
      <summary className="cursor-pointer select-none text-xs font-semibold text-[#dadada] marker:text-[#858585]">
        Prompt messages ({messages.length})
      </summary>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {messages.map((message, index) => {
          const role = messageRole(message);
          return (
            <span key={`${role}-chip-${index}`} className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${roleClass(role)}`}>
              {role}
            </span>
          );
        })}
      </div>
      <div className="mt-2 grid gap-2">
        {messages.map((message, index) => {
          const role = messageRole(message);
          return (
            <div key={`${role}-${index}`} className="rounded-lg border border-[#353535] bg-[#161616] p-2.5">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${roleClass(role)}`}>
                  {role}
                </span>
                <span className="font-mono text-[10px] text-[#777]">#{index + 1}</span>
              </div>
              <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words font-sans text-xs leading-relaxed text-[#dadada] scrollbar-dark [overflow-wrap:anywhere]">
                {formatMaybeJsonText(message?.content) || '[empty message]'}
              </pre>
            </div>
          );
        })}
      </div>
    </details>
  );
}

function TraceValue({ value, fieldKey }) {
  if (fieldKey === 'message_preview') return <TraceMessages messages={value} />;

  if (fieldKey === 'schema') {
    return (
      <span className="min-w-0 max-w-full whitespace-pre-wrap break-words text-[#d8d8d8] [overflow-wrap:anywhere]">
        {formatSchemaSummary(value)}
      </span>
    );
  }

  if (fieldKey === 'action') {
    return (
      <code className="block max-h-24 min-w-0 max-w-full overflow-auto whitespace-pre-wrap rounded-md border border-[#353535] bg-[#1a1a1a] px-2 py-1 font-mono text-[11px] leading-relaxed text-[#d8d8d8] break-all scrollbar-dark [overflow-wrap:anywhere]">
        {formatMaybeJsonText(value)}
      </code>
    );
  }

  if (Array.isArray(value) && value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))) {
    return (
      <div className="flex min-w-0 flex-wrap gap-1.5">
        {value.map((item, index) => (
          <span
            key={`${String(item)}-${index}`}
            className="max-w-full rounded-full border border-[#464646] bg-[#1a1a1a] px-2 py-0.5 font-mono text-[11px] text-[#d8d8d8] break-all [overflow-wrap:anywhere]"
          >
            {String(item)}
          </span>
        ))}
      </div>
    );
  }

  const text = stringifyTraceValue(value);
  const isComplex = typeof value === 'object' || text.length > 96;
  if (isComplex) {
    return (
      <code className="block max-h-28 min-w-0 max-w-full overflow-auto whitespace-pre-wrap rounded-md border border-[#353535] bg-[#1a1a1a] px-2 py-1 font-mono text-[11px] leading-relaxed text-[#d8d8d8] break-all scrollbar-dark [overflow-wrap:anywhere]">
        {text}
      </code>
    );
  }

  return (
    <span className="min-w-0 max-w-full overflow-hidden whitespace-pre-wrap break-words text-[#cfcfcf] [overflow-wrap:anywhere]">
      {text}
    </span>
  );
}

function TraceCard({ span }) {
  const started = span.started || span.events[0];
  const completed = span.completed || span.failed;
  const payload = span.events.reduce(
    (acc, event) => ({ ...acc, ...(event.payload || {}) }),
    {}
  );
  const status = completed?.status || started?.status || 'running';
  const duration = completed?.duration_ms;
  const reasoningSummary = payload.reasoning_summary;
  const rows = payloadRows(payload);
  const previewMessages = Array.isArray(payload.message_preview) ? payload.message_preview : [];
  const previewText = previewMessages.length > 0
    ? truncateText(previewMessages[previewMessages.length - 1]?.content)
    : '';

  return (
    <div className="relative pl-5">
      <div className={`absolute left-[1.5px] top-1/2 -translate-y-1/2 h-[8px] w-[8px] rounded-full border-2 ${statusDotClass(status)}`} />
      <div className="overflow-hidden rounded-xl border border-[#464646] bg-[#202020] px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.16)]">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className={`text-[10px] uppercase tracking-wider font-bold flex-shrink-0 ${kindColor(started?.event_type)}`}>
                {kindLabel(started?.event_type)}
              </span>
              <span className="text-sm font-semibold text-white truncate">
                {eventTitle(started)}
              </span>
            </div>
            <p className="text-[11px] text-[#8b8b8b] mt-0.5 truncate">
              {started?.node_label || started?.node_id || 'Workflow'} · {started?.event_type}
            </p>
            {previewText && (
              <p className="mt-2 truncate text-xs text-[#b5b5b5]">
                {previewText}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {duration !== undefined && (
              <span className="text-[11px] text-[#b5b5b5] font-mono">{formatDuration(duration)}</span>
            )}
            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${statusClass(status)}`}>
              {status === 'running' ? 'Running' : status === 'error' ? 'Error' : 'Done'}
            </span>
          </div>
        </div>

        {rows.length > 0 && (
          <div className="mt-3 grid gap-1.5 min-w-0 border-t border-white/[0.06] pt-3">
            {rows.map(([key, value]) => (
              <div key={key} className="grid min-w-0 grid-cols-[6.75rem_minmax(0,1fr)] gap-3 text-xs sm:grid-cols-[7.75rem_minmax(0,1fr)]">
                <span className="min-w-0 truncate text-[#8b8b8b]" title={key}>{humanizeTraceKey(key)}</span>
                <TraceValue value={value} fieldKey={key} />
              </div>
            ))}
          </div>
        )}

        {reasoningSummary && (
          <details className="mt-3 rounded-md border border-[#353535] bg-[#1a1a1a] p-3">
            <summary className="cursor-pointer select-none text-[10px] uppercase tracking-wider text-[#d93854] font-bold marker:text-[#858585]">
              Reasoning Summary
            </summary>
            <p className="text-xs text-[#d7d7d7] leading-relaxed whitespace-pre-wrap break-words">
              {reasoningSummary}
            </p>
          </details>
        )}
      </div>
    </div>
  );
}

export default function TraceSidePanel({ executionId, onClose }) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const eventIds = useRef(new Set());

  useEffect(() => {
    if (!executionId) return undefined;

    setEvents([]);
    setError('');
    eventIds.current = new Set();

    const accessToken = getAccessToken();
    const qs = accessToken ? `?token=${encodeURIComponent(accessToken)}` : '';
    const url = `${API_BASE_URL}/api/executions/${executionId}/trace/stream${qs}`;
    const es = new EventSource(url, { withCredentials: true });

    es.onopen = () => {
      setConnected(true);
      setError('');
    };
    es.onerror = () => {
      setConnected(false);
      setError('Reconnecting...');
    };
    es.addEventListener('trace', (e) => {
      try {
        if (e.lastEventId && eventIds.current.has(e.lastEventId)) return;
        if (e.lastEventId) eventIds.current.add(e.lastEventId);
        const parsed = JSON.parse(e.data);
        setEvents((prev) => [...prev, parsed].slice(-500));
      } catch {
        // Ignore malformed trace frames.
      }
    });

    return () => es.close();
  }, [executionId]);

  const spans = useMemo(() => {
    const byId = new Map();
    for (const event of events) {
      const spanId = event.span_id || `${event.event_type}:${event.timestamp}`;
      const existing = byId.get(spanId) || { span_id: spanId, events: [] };
      existing.events.push(event);
      if (event.event_type?.endsWith('.started')) existing.started = event;
      if (event.event_type?.endsWith('.completed')) existing.completed = event;
      if (event.event_type?.endsWith('.failed')) existing.failed = event;
      byId.set(spanId, existing);
    }
    return Array.from(byId.values()).sort((a, b) => {
      const at = a.events[0]?.timestamp || '';
      const bt = b.events[0]?.timestamp || '';
      return at.localeCompare(bt);
    });
  }, [events]);

  const traceStats = useMemo(() => {
    const completed = spans.filter((span) => span.completed).length;
    const failed = spans.filter((span) => span.failed).length;
    const running = spans.filter((span) => !span.completed && !span.failed).length;
    const totalDuration = spans.reduce((sum, span) => sum + (span.completed?.duration_ms || span.failed?.duration_ms || 0), 0);
    return { completed, failed, running, totalDuration };
  }, [spans]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed top-0 right-0 h-full w-[500px] max-w-[94vw] z-40 bg-[#1a1a1a] border-l border-[#464646] shadow-2xl flex flex-col output-panel-slide">
        <div className="flex items-center justify-between px-6 pt-6 pb-4 flex-shrink-0">
          <div>
            <h2 className="text-2xl font-bold text-white">Trace</h2>
            <div className="flex items-center gap-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-yellow-400'}`} />
              <span className="text-xs text-[#8b8b8b]">
                {connected ? 'Live' : error || 'Connecting'} · Execution {executionId || 'pending'}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className={`w-9 h-9 rounded-[10px] ${CHAT_ICON_BTN}`}
            title="Close trace"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {executionId && spans.length > 0 && (
          <div className="mx-6 mb-4 grid grid-cols-4 gap-1.5 rounded-xl border border-[#353535] bg-[#202020] p-1.5">
            <div className="rounded-lg bg-[#1a1a1a] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-wide text-[#858585]">Steps</div>
              <div className="mt-0.5 text-base font-bold text-white">{spans.length}</div>
            </div>
            <div className="rounded-lg bg-[#1a1a1a] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-wide text-[#858585]">Done</div>
              <div className="mt-0.5 text-base font-bold text-emerald-300">{traceStats.completed}</div>
            </div>
            <div className="rounded-lg bg-[#1a1a1a] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-wide text-[#858585]">Running</div>
              <div className="mt-0.5 text-base font-bold text-cyan-200">{traceStats.running}</div>
            </div>
            <div className="rounded-lg bg-[#1a1a1a] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-wide text-[#858585]">Time</div>
              <div className={`mt-0.5 text-base font-bold ${traceStats.failed ? 'text-[#ff8ba0]' : 'text-white'}`}>
                {formatDuration(traceStats.totalDuration) || '—'}
              </div>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 pb-6 scrollbar-dark">
          {!executionId ? (
            <div className="flex h-full items-center justify-center text-sm text-[#6b6b6b] text-center">
              Trace will appear after an execution starts.
            </div>
          ) : spans.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-[#6b6b6b] text-center">
              Waiting for trace events...
            </div>
          ) : (
            <div className="relative">
              <div className="absolute left-[5px] top-5 bottom-5 w-px bg-[#353535]" />
              <div className="space-y-3">
                {spans.map((span) => (
                  <TraceCard key={span.span_id} span={span} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
