import { useState } from 'react';

/**
 * Expandable panel showing SQL queries executed during an agent message.
 * Renders a compact pill button; clicking reveals SQL, tables, and result data.
 */
export default function QueryDetails({ queries }) {
  const [expanded, setExpanded] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState(null);

  if (!queries || queries.length === 0) return null;

  const handleCopy = async (sql, idx) => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopiedIdx(idx);
      setTimeout(() => setCopiedIdx(null), 1500);
    } catch (e) {
      /* clipboard not available */
    }
  };

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="inline-flex cursor-pointer select-none items-center gap-1.5 rounded-lg bg-white/5 px-2.5 py-1 text-xs font-medium text-[#dadada] ring-1 ring-white/10 transition-all duration-150 hover:bg-white/10 hover:text-white"
      >
        {/* Database icon */}
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        </svg>
        {queries.length === 1 ? '1 Query Executed' : `${queries.length} Queries Executed`}
        <svg
          className={`w-3 h-3 transition-transform duration-150 ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-2 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
          {queries.map((q, idx) => (
            <QueryCard key={idx} q={q} idx={idx} copiedIdx={copiedIdx} onCopy={handleCopy} />
          ))}
        </div>
      )}
    </div>
  );
}

function QueryCard({ q, idx, copiedIdx, onCopy }) {
  const [showResults, setShowResults] = useState(false);
  const hasResults = q.results && q.results.columns && q.results.rows && q.results.rows.length > 0;

  return (
    <div className="overflow-hidden rounded-lg bg-black/25 ring-1 ring-white/10">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2 text-xs text-[#b5b5b5]">
          {q.tables_used && q.tables_used.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="font-medium text-[#888888]">Tables:</span>
              {q.tables_used.map((t) => (
                <span
                  key={t}
                  className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[11px] text-[#dadada]"
                >
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        {q.row_count != null && (
          <span className="ml-2 whitespace-nowrap text-[11px] text-[#888888]">
            {q.row_count} row{q.row_count !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* SQL */}
      {q.sql && (
        <div className="relative group">
          <pre className="max-h-48 overflow-x-auto whitespace-pre-wrap break-all bg-black/30 px-3 py-2 font-mono text-xs leading-relaxed text-[#dadada]">
            {q.sql}
          </pre>
          <button
            type="button"
            onClick={() => onCopy(q.sql, idx)}
            className="absolute right-1.5 top-1.5 rounded p-1 text-[#b5b5b5] opacity-0 ring-1 ring-white/10 transition-opacity hover:text-white group-hover:opacity-100"
            title="Copy SQL"
          >
            {copiedIdx === idx ? (
              <svg className="w-3.5 h-3.5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
              </svg>
            )}
          </button>
        </div>
      )}

      {/* Result data toggle + table */}
      {hasResults && (
        <div className="border-t border-white/10">
          <button
            type="button"
            onClick={() => setShowResults((p) => !p)}
            className="flex w-full cursor-pointer items-center justify-between px-3 py-1.5 text-[11px] text-[#b5b5b5] transition-colors hover:bg-white/5"
          >
            <span className="font-medium flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M3 14h18M3 6h18M3 18h18" />
              </svg>
              View Data ({q.results.rows.length} row{q.results.rows.length !== 1 ? 's' : ''})
            </span>
            <svg
              className={`w-3 h-3 transition-transform duration-150 ${showResults ? 'rotate-180' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showResults && (
            <div className="overflow-x-auto max-h-72">
              <table className="min-w-full text-[11px] font-mono">
                <thead className="sticky top-0 bg-white/10">
                  <tr>
                    {q.results.columns.map((col) => (
                      <th
                        key={col}
                        className="whitespace-nowrap border-b border-white/10 px-2 py-1.5 text-left text-[11px] font-semibold text-[#dadada]"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {q.results.rows.map((row, rIdx) => (
                    <tr key={rIdx} className={rIdx % 2 === 0 ? 'bg-transparent' : 'bg-white/[0.03]'}>
                      {row.map((cell, cIdx) => (
                        <td
                          key={cIdx}
                          className="max-w-[200px] truncate whitespace-nowrap border-b border-white/5 px-2 py-1 text-[#dadada]"
                          title={cell ?? ''}
                        >
                          {cell ?? <span className="italic text-[#888888]">NULL</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Original question */}
      {q.question && (
        <div className="truncate border-t border-white/10 px-3 py-1.5 text-[11px] text-[#888888]">
          <span className="font-medium text-[#b5b5b5]">Question:</span> {q.question}
        </div>
      )}
    </div>
  );
}
