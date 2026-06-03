import React, { lazy, Suspense, useCallback } from 'react';
import {
  APEX_MONACO_THEME,
  applyApexMonacoTheme,
  defineApexMonacoTheme,
} from '../../theme/monacoApexTheme';

const MonacoDiffEditor = lazy(() =>
  import('@monaco-editor/react').then((m) => ({ default: m.DiffEditor })),
);

/**
 * Full-screen side-by-side diff between the previous and newly-applied
 * code, overlaid on top of the Code Editor Modal.  Lives outside the
 * modal's regular flow (``z-60``) so it always floats above the banner
 * and the editor.
 *
 * Both the diff drawer and the banner offer Keep/Revert so the user can
 * inspect and decide without having to close one to use the other.
 */
export default function CodeDiffDrawer({
  isOpen,
  prevCode,
  newCode,
  summary,
  onClose,
  onKeep,
  onRevert,
}) {
  const handleBeforeMount = useCallback((monaco) => {
    defineApexMonacoTheme(monaco);
  }, []);

  const handleMount = useCallback((_editor, monaco) => {
    applyApexMonacoTheme(monaco);
  }, []);

  if (!isOpen) return null;

  return (
    <div
      className="code-editor-diff fixed inset-0 z-[60] flex bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        className="flex flex-col w-full h-full rounded-lg overflow-hidden bg-[var(--ce-bg)] border border-[var(--ce-border)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-2.5 bg-[var(--ce-panel)] border-b border-[var(--ce-border)] shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <svg
              className="w-4 h-4 text-[var(--ce-accent)] shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 10h16M4 14h10M4 18h10"
              />
            </svg>
            <span className="text-sm font-medium text-[var(--ce-text)] truncate">
              Diff &mdash; {summary || 'Applied change'}
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onRevert}
              className="px-3 py-1.5 text-xs rounded bg-[var(--ce-btn)] text-[var(--ce-logic)] border border-[var(--ce-logic)]/40 hover:bg-[var(--ce-cta-soft)] transition-colors"
            >
              Revert
            </button>
            <button
              type="button"
              onClick={onKeep}
              className="px-3 py-1.5 text-xs rounded bg-[var(--ce-cta)] text-white hover:bg-[var(--ce-cta-hover)] transition-colors font-medium"
            >
              Keep
            </button>
            <div className="w-px h-5 bg-[var(--ce-border)] mx-1" />
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded bg-[var(--ce-btn)] text-[var(--ce-muted)] hover:text-[var(--ce-text)] border border-[var(--ce-border)] transition-colors"
            >
              Close
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0">
          <Suspense
            fallback={
              <div className="w-full h-full flex items-center justify-center text-[var(--ce-muted)] text-sm">
                Loading diff&hellip;
              </div>
            }
          >
            <MonacoDiffEditor
              height="100%"
              language="python"
              theme={APEX_MONACO_THEME}
              beforeMount={handleBeforeMount}
              onMount={handleMount}
              original={prevCode || ''}
              modified={newCode || ''}
              options={{
                readOnly: true,
                renderSideBySide: true,
                originalEditable: false,
                minimap: { enabled: false },
                fontSize: 13,
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                renderWhitespace: 'selection',
                diffWordWrap: 'on',
              }}
            />
          </Suspense>
        </div>

        <div className="flex items-center justify-between px-4 py-1.5 bg-[var(--ce-panel)] border-t border-[var(--ce-border)] text-[11px] text-[var(--ce-muted)] shrink-0">
          <span>Read-only diff &mdash; use Keep / Revert above to decide.</span>
          <span>Press Esc or click outside to close</span>
        </div>
      </div>
    </div>
  );
}
