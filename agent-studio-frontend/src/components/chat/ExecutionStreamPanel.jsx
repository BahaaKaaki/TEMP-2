/**
 * ExecutionStreamPanel -- real-time terminal-like display of code execution
 * output streamed via Server-Sent Events (SSE).
 *
 * Connects to GET /api/executions/{executionId}/stream and renders live
 * stdout/stderr, phase badges, and a progress indicator.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getAccessToken } from '../../api/auth-client';

const PHASE_LABELS = {
  acquiring_sandbox: 'Acquiring sandbox...',
  injecting_files: 'Injecting files...',
  running: 'Running script...',
  extracting: 'Extracting outputs...',
  complete: 'Complete',
  error: 'Error',
};

const PHASE_COLORS = {
  acquiring_sandbox: 'text-blue-400',
  injecting_files: 'text-cyan-400',
  running: 'text-green-400',
  extracting: 'text-yellow-400',
  complete: 'text-emerald-400',
  error: 'text-red-400',
};

export default function ExecutionStreamPanel({ executionId, onComplete, onDeliverable }) {
  const [lines, setLines] = useState([]);
  const [phase, setPhase] = useState('acquiring_sandbox');
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);
  const terminalRef = useRef(null);
  const eventSourceRef = useRef(null);

  const addLine = useCallback((type, text) => {
    setLines(prev => {
      const next = [...prev, { type, text, ts: Date.now() }];
      return next.length > 500 ? next.slice(-400) : next;
    });
  }, []);

  useEffect(() => {
    if (!executionId || done) return;

    const accessToken = getAccessToken();
    const qs = accessToken ? `?token=${encodeURIComponent(accessToken)}` : '';
    const url = `/api/executions/${executionId}/stream${qs}`;
    const es = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => {
      setConnected(false);
      if (!done) {
        addLine('system', 'Connection lost. Retrying...');
      }
    };

    es.addEventListener('status', (e) => {
      try {
        const data = JSON.parse(e.data);
        setPhase(data.phase);
        addLine('status', PHASE_LABELS[data.phase] || data.phase);
      } catch {}
    });

    es.addEventListener('stdout', (e) => {
      addLine('stdout', e.data);
    });

    es.addEventListener('stderr', (e) => {
      addLine('stderr', e.data);
    });

    es.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse(e.data);
        addLine('progress', `Progress: ${Math.round((data.progress || 0) * 100)}% — ${data.message || ''}`);
      } catch {}
    });

    es.addEventListener('deliverable', (e) => {
      try {
        const data = JSON.parse(e.data);
        addLine('status', 'Deliverable received.');
        onDeliverable?.(data);
      } catch {}
    });

    es.addEventListener('complete', (e) => {
      setPhase('complete');
      setDone(true);
      addLine('status', 'Execution complete.');
      es.close();
      onComplete?.();
    });

    es.addEventListener('error', (e) => {
      setPhase('error');
      setDone(true);
      try {
        const data = JSON.parse(e.data);
        addLine('error', data.message || 'Execution failed.');
      } catch {
        addLine('error', 'Execution failed.');
      }
      es.close();
    });

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [executionId, done, addLine, onComplete, onDeliverable]);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [lines]);

  if (!executionId) return null;

  return (
    <div className="bg-gray-950 rounded-lg border border-gray-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${done ? (phase === 'error' ? 'bg-red-400' : 'bg-emerald-400') : 'bg-green-400 animate-pulse'}`} />
          <span className={`text-xs font-medium ${PHASE_COLORS[phase] || 'text-gray-400'}`}>
            {PHASE_LABELS[phase] || phase}
          </span>
        </div>
        {connected && !done && (
          <span className="text-xs text-gray-500">Live</span>
        )}
      </div>

      {/* Terminal output */}
      <div
        ref={terminalRef}
        className="p-3 font-mono text-xs leading-5 overflow-y-auto max-h-64 min-h-[80px]"
      >
        {lines.length === 0 && (
          <span className="text-gray-600">Waiting for output...</span>
        )}
        {lines.map((line, i) => (
          <div key={i} className={
            line.type === 'stderr' || line.type === 'error'
              ? 'text-red-400'
              : line.type === 'status'
                ? 'text-blue-400 italic'
                : line.type === 'progress'
                  ? 'text-yellow-400'
                  : 'text-green-300'
          }>
            {line.text}
          </div>
        ))}
      </div>
    </div>
  );
}
