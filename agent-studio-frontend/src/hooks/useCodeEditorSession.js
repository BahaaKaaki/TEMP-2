import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Persistent, per-node chat + code-version session for the Code Editor's
 * AI assistant.
 *
 * Storage model
 * -------------
 * Each code-executor node (keyed by `workflowId + nodeId`) owns one
 * ``localStorage`` entry holding its full chat history and every code
 * version the assistant produced.  We keep this client-side so the
 * backend stays stateless and users see their refinement thread pop
 * back up even after a full page reload.
 *
 * Caps
 * ----
 * - Per-session: 50 messages, 20 versions (oldest evicted first).
 * - Per-version: code body truncated to 200 KB before persisting.  This
 *   is rare -- a typical generated script is well under 20 KB -- but the
 *   cap prevents a single pathological turn from blowing the browser
 *   quota.
 * - Globally: up to 50 sessions across all nodes/workflows, evicted by
 *   least-recently-written.
 *
 * Writes are debounced at ~200 ms so a burst of state updates (e.g. the
 * banner flipping between "applied" and "reverted") doesn't hammer
 * ``localStorage`` -- it's synchronous and surprisingly expensive.
 */

const KEY_PREFIX = 'code_editor_session__';
const MASTER_INDEX_KEY = 'code_editor_session__index';

const MAX_MESSAGES = 50;
const MAX_VERSIONS = 20;
const MAX_SESSIONS = 50;
const MAX_CODE_CHARS = 200_000;
const WRITE_DEBOUNCE_MS = 200;

const EMPTY_STATE = Object.freeze({
  messages: [],
  versions: [],
  currentVersionId: null,
});

const makeSessionKey = (workflowId, nodeId) =>
  `${KEY_PREFIX}${workflowId || 'anon'}__${nodeId || 'anon'}`;

const makeId = () =>
  `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;

const capMessages = (messages) =>
  messages.length > MAX_MESSAGES ? messages.slice(-MAX_MESSAGES) : messages;

const capVersions = (versions) =>
  versions.length > MAX_VERSIONS ? versions.slice(-MAX_VERSIONS) : versions;

// ── localStorage helpers ────────────────────────────────────────────────
// All of these swallow errors so SSR, privacy mode, and quota failures
// degrade gracefully to in-memory-only behaviour.

function safeGet(key) {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return null;
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key, value) {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return false;
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

function safeRemove(key) {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return;
    window.localStorage.removeItem(key);
  } catch {
    /* noop */
  }
}

// ── Master session index (for global LRU eviction) ──────────────────────

function readIndex() {
  const raw = safeGet(MASTER_INDEX_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e) => e && typeof e.key === 'string' && typeof e.lastWrittenAt === 'number',
    );
  } catch {
    return [];
  }
}

function writeIndex(entries) {
  safeSet(MASTER_INDEX_KEY, JSON.stringify(entries));
}

function touchIndex(key) {
  const entries = readIndex();
  const now = Date.now();
  const existing = entries.findIndex((e) => e.key === key);
  if (existing >= 0) entries[existing].lastWrittenAt = now;
  else entries.push({ key, lastWrittenAt: now });
  entries.sort((a, b) => (a.lastWrittenAt || 0) - (b.lastWrittenAt || 0));
  // Enforce the global session cap by evicting LRU entries.
  while (entries.length > MAX_SESSIONS) {
    const oldest = entries.shift();
    if (oldest?.key && oldest.key !== key) safeRemove(oldest.key);
  }
  writeIndex(entries);
}

function removeFromIndex(key) {
  const entries = readIndex().filter((e) => e.key !== key);
  writeIndex(entries);
}

function evictOldest(exceptKey) {
  const entries = readIndex();
  if (!entries.length) return false;
  entries.sort((a, b) => (a.lastWrittenAt || 0) - (b.lastWrittenAt || 0));
  const victim = entries.find((e) => e.key !== exceptKey);
  if (!victim) return false;
  safeRemove(victim.key);
  writeIndex(entries.filter((e) => e.key !== victim.key));
  return true;
}

// ── Load / persist session payloads ─────────────────────────────────────

function loadSession(key) {
  const raw = safeGet(key);
  if (!raw) return { ...EMPTY_STATE };
  try {
    const parsed = JSON.parse(raw);
    if (
      !parsed ||
      typeof parsed !== 'object' ||
      !Array.isArray(parsed.messages) ||
      !Array.isArray(parsed.versions)
    ) {
      return { ...EMPTY_STATE };
    }
    return {
      messages: capMessages(parsed.messages),
      versions: capVersions(parsed.versions),
      currentVersionId:
        typeof parsed.currentVersionId === 'string' ? parsed.currentVersionId : null,
    };
  } catch {
    return { ...EMPTY_STATE };
  }
}

function persistSession(key, state) {
  const hasContent = state.messages.length || state.versions.length;
  if (!hasContent) {
    safeRemove(key);
    removeFromIndex(key);
    return;
  }
  const payload = JSON.stringify({
    messages: capMessages(state.messages),
    versions: capVersions(state.versions),
    currentVersionId: state.currentVersionId,
    lastWrittenAt: Date.now(),
  });
  let ok = safeSet(key, payload);
  // Quota-exceeded fallback: evict oldest foreign session and retry once.
  if (!ok && evictOldest(key)) {
    ok = safeSet(key, payload);
  }
  if (ok) touchIndex(key);
}

// ── Hook ────────────────────────────────────────────────────────────────

export default function useCodeEditorSession({ workflowId, nodeId }) {
  const key = makeSessionKey(workflowId, nodeId);
  const keyRef = useRef(key);

  const [state, setState] = useState(() => loadSession(key));
  const stateRef = useRef(state);
  stateRef.current = state;

  // When the caller switches nodes (hot-swap of workflowId/nodeId), reload.
  useEffect(() => {
    if (keyRef.current === key) return;
    keyRef.current = key;
    setState(loadSession(key));
  }, [key]);

  // Debounced write.  Works off a ref so the timer always flushes the
  // latest state, not the closed-over snapshot from when it was queued.
  const writeTimerRef = useRef(null);
  useEffect(() => {
    if (writeTimerRef.current) clearTimeout(writeTimerRef.current);
    writeTimerRef.current = setTimeout(() => {
      persistSession(keyRef.current, stateRef.current);
    }, WRITE_DEBOUNCE_MS);
    return () => {
      if (writeTimerRef.current) clearTimeout(writeTimerRef.current);
    };
  }, [state, key]);

  // Best-effort flush on unmount so a quick close-and-reopen doesn't drop
  // the last turn.
  useEffect(
    () => () => {
      if (writeTimerRef.current) clearTimeout(writeTimerRef.current);
      persistSession(keyRef.current, stateRef.current);
    },
    [],
  );

  const pushUserTurn = useCallback((turn) => {
    const id = makeId();
    setState((prev) => ({
      ...prev,
      messages: capMessages([
        ...prev.messages,
        {
          id,
          role: 'user',
          ts: Date.now(),
          content: '',
          images: [],
          ...turn,
        },
      ]),
    }));
    return id;
  }, []);

  const pushAssistantTurn = useCallback(
    ({
      kind = 'code',
      content = '',
      summary = '',
      code = null,
      assumptions = [],
      valid = true,
      violations = [],
      question = '',
      options = [],
      prevCode = null,
    }) => {
      const messageId = makeId();
      const versionId = makeId();
      const ts = Date.now();

      setState((prev) => {
        const nextMessage = {
          id: messageId,
          role: 'assistant',
          ts,
          kind,
          content,
          summary,
          code: typeof code === 'string' ? code : null,
          assumptions: Array.isArray(assumptions) ? assumptions : [],
          valid,
          violations: Array.isArray(violations) ? violations : [],
          question,
          options: Array.isArray(options) ? options : [],
          versionId: kind === 'code' && typeof code === 'string' ? versionId : null,
        };

        let nextVersions = prev.versions;
        let nextCurrentVersionId = prev.currentVersionId;

        if (kind === 'code' && typeof code === 'string') {
          const truncated = code.length > MAX_CODE_CHARS;
          nextVersions = capVersions([
            ...prev.versions,
            {
              id: versionId,
              messageId,
              ts,
              summary,
              prevCode:
                typeof prevCode === 'string'
                  ? prevCode.slice(0, MAX_CODE_CHARS)
                  : null,
              code: truncated ? code.slice(0, MAX_CODE_CHARS) : code,
              truncated,
              reverted: false,
            },
          ]);
          nextCurrentVersionId = versionId;
        }

        return {
          messages: capMessages([...prev.messages, nextMessage]),
          versions: nextVersions,
          currentVersionId: nextCurrentVersionId,
        };
      });

      return { messageId, versionId: kind === 'code' ? versionId : null };
    },
    [],
  );

  const restoreVersion = useCallback((versionId) => {
    setState((prev) => {
      const exists = prev.versions.some((v) => v.id === versionId);
      if (!exists) return prev;
      return { ...prev, currentVersionId: versionId };
    });
  }, []);

  const markVersionReverted = useCallback((versionId, reverted = true) => {
    setState((prev) => ({
      ...prev,
      versions: prev.versions.map((v) =>
        v.id === versionId ? { ...v, reverted } : v,
      ),
    }));
  }, []);

  const clear = useCallback(() => {
    setState({ ...EMPTY_STATE });
    safeRemove(keyRef.current);
    removeFromIndex(keyRef.current);
  }, []);

  return {
    messages: state.messages,
    versions: state.versions,
    currentVersionId: state.currentVersionId,
    pushUserTurn,
    pushAssistantTurn,
    restoreVersion,
    markVersionReverted,
    clear,
  };
}
