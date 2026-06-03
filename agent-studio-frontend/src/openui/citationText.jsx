/**
 * Shared, generic "make text citation-aware" primitive.
 *
 * One place owns the logic that turns inline `[n]` markers into interactive
 * source badges. Any component — built-in or custom — can opt in with a single
 * line (`renderTextWithCitations(text, citations)` for raw strings, or the
 * `<CitationText>` wrapper which reads citations from context), instead of each
 * component re-implementing the scan/replace. This keeps "sources" scalable
 * across the whole component library.
 */
import OpenUICitationReference from './components/openUICitationReference';
import { useOpenUICitations } from './citationContext';

const CITATION_RE = /\[(\d+)\]/g;

function buildMap(citations) {
  return new Map(
    (Array.isArray(citations) ? citations : []).map((c) => [Number(c.citation_number), c]),
  );
}

/** Replace `[n]` markers in a string with interactive citation badges. */
export function renderTextWithCitations(text, citations, keyPrefix = 'cite') {
  if (typeof text !== 'string' || !text) return text;
  const byNum = buildMap(citations);
  if (byNum.size === 0) return text;

  const parts = [];
  let last = 0;
  let match;
  let i = 0;
  CITATION_RE.lastIndex = 0;
  while ((match = CITATION_RE.exec(text)) !== null) {
    const num = Number(match[1]);
    if (match.index > last) parts.push(text.slice(last, match.index));
    const data = byNum.get(num);
    parts.push(
      data ? (
        <OpenUICitationReference key={`${keyPrefix}-${num}-${i}`} citationNumber={num} citationData={data} />
      ) : (
        <span
          key={`${keyPrefix}-${num}-${i}`}
          title={`Citation ${num}`}
          className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-cyan-300/70 bg-cyan-400/20 px-1 text-[11px] font-bold leading-none text-cyan-100 align-baseline"
        >
          {num}
        </span>
      ),
    );
    last = match.index + match[0].length;
    i += 1;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length > 0 ? parts : text;
}

/** Apply citation replacement to react-markdown children (string or array). */
export function processChildren(children, citations, keyPrefix = 'cite') {
  if (typeof children === 'string') return renderTextWithCitations(children, citations, keyPrefix);
  if (Array.isArray(children)) {
    return children.map((child, idx) =>
      typeof child === 'string' ? renderTextWithCitations(child, citations, `${keyPrefix}-${idx}`) : child,
    );
  }
  return children;
}

/**
 * Drop-in wrapper that makes any component's text citation-aware. Pass a string
 * child; `[n]` markers become interactive source badges. Reads the active
 * citations from context, so any component rendered under the renderer's
 * `OpenUICitationProvider` can use it without threading props.
 */
export function CitationText({ children }) {
  const citations = useOpenUICitations();
  if (typeof children !== 'string') return children;
  return <>{renderTextWithCitations(children, citations)}</>;
}
