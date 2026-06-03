import React from 'react';

/**
 * Floating banner shown above the Monaco editor after the AI auto-applies
 * a new code version.  Cursor-style: the code is already in the buffer --
 * this just surfaces the choice to Keep, Revert, or open a side-by-side
 * diff drawer.
 *
 * Visual priorities:
 *   - Never block the first ~3 visible lines of the editor (we sit on top
 *     but below the title bar).
 *   - Keep the three actions equally prominent; the default is "Keep" but
 *     we don't highlight any single one -- Cursor lets the user decide.
 */
export default function AppliedBanner({
  summary,
  truncated = false,
  onKeep,
  onRevert,
  onViewDiff,
}) {
  return (
    <div className="px-4 pt-3 shrink-0">
      <div className="flex items-center gap-3 px-3 py-2 rounded-lg border border-indigo-500/40 bg-indigo-900/30 backdrop-blur-sm shadow-lg">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <div className="w-6 h-6 rounded-full bg-indigo-500/80 flex items-center justify-center shrink-0">
            <svg
              className="w-3.5 h-3.5 text-white"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase tracking-wide text-indigo-300/80 font-semibold">
              Applied
            </div>
            <div className="text-sm text-gray-100 truncate" title={summary || 'Updated code'}>
              {summary || 'Updated code'}
              {truncated && (
                <span className="ml-2 text-[10px] text-amber-300/80">
                  (truncated for storage)
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={onViewDiff}
            className="px-2.5 py-1 text-[11px] rounded bg-[#2d2d2d]/80 text-gray-200 border border-[#505050] hover:bg-[#3d3d3d] transition-colors"
          >
            View diff
          </button>
          <button
            type="button"
            onClick={onRevert}
            className="px-2.5 py-1 text-[11px] rounded bg-[#2d2d2d]/80 text-amber-300 border border-amber-600/40 hover:bg-amber-900/30 transition-colors"
          >
            Revert
          </button>
          <button
            type="button"
            onClick={onKeep}
            className="px-2.5 py-1 text-[11px] rounded bg-indigo-600 text-white hover:bg-indigo-700 transition-colors font-medium"
          >
            Keep
          </button>
        </div>
      </div>
    </div>
  );
}
