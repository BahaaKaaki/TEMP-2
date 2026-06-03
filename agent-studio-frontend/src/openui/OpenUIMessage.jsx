/**
 * OpenUIMessage - renders assistant content as OpenUI Lang via @openuidev/react-lang.
 *
 * Generative UI only: no markdown or plain-text fallback. On a fatal parse
 * failure, render the optional `fallback` node (used by deliverables to show a
 * clean read-only JSON view) and otherwise fall back to a developer error panel.
 */

import { useCallback, useMemo, useState } from 'react';
import { Renderer } from '@openuidev/react-lang';

import openuiLibrary from './library';
import { OpenUICitationProvider } from './citationContext';

function OpenUIErrorPanel({ errors }) {
  const primary = errors?.[0];
  return (
    <div
      className="rounded-lg border border-red-500/40 bg-red-950/30 p-4 text-sm text-white"
      role="alert"
    >
      <p className="font-semibold text-red-200 mb-2">Could not render generative UI</p>
      <p className="text-white/80 mb-2">
        The assistant response was not valid OpenUI Lang. Send another message to try again,
        or ask the agent to fix the layout using only components from the library.
      </p>
      {primary?.message ? (
        <p className="text-xs text-white/50 font-mono break-words">{primary.message}</p>
      ) : null}
      {primary?.hint ? (
        <p className="text-xs text-white/40 mt-2 break-words">{primary.hint}</p>
      ) : null}
    </div>
  );
}

export default function OpenUIMessage({ content, isStreaming = false, fallback = null, citations = null }) {
  const [fatalErrors, setFatalErrors] = useState(null);
  const [renderErrors, setRenderErrors] = useState(null);

  const handleError = useCallback((errors) => {
    if (!errors || errors.length === 0) {
      setFatalErrors(null);
      setRenderErrors(null);
      return;
    }
    const fatal = errors.filter(
      (e) => e.code === 'parse-failed' || e.code === 'parse-exception',
    );
    if (fatal.length > 0 && !isStreaming) {
      setFatalErrors(fatal);
      setRenderErrors(null);
    } else if (isStreaming) {
      setFatalErrors(null);
      setRenderErrors(null);
    } else {
      setFatalErrors(null);
      setRenderErrors(errors);
    }
  }, [isStreaming]);

  const response = useMemo(() => (typeof content === 'string' ? content : ''), [content]);

  if (fatalErrors && fatalErrors.length > 0) {
    if (fallback !== null) {
      console.warn('OpenUI render failed; showing JSON fallback', fatalErrors);
      return fallback;
    }
    return <OpenUIErrorPanel errors={fatalErrors} />;
  }

  return (
    <div className="openui-message overflow-hidden text-white space-y-3">
      <OpenUICitationProvider citations={citations}>
        <Renderer
          library={openuiLibrary}
          response={response}
          isStreaming={isStreaming}
          onError={handleError}
        />
      </OpenUICitationProvider>
      {renderErrors?.length && fallback === null ? <OpenUIErrorPanel errors={renderErrors} /> : null}
    </div>
  );
}
