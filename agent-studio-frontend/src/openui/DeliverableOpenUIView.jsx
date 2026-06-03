import { useEffect, useState } from 'react';

import OpenUICitationReference from './components/openUICitationReference';
import OpenUIMessage from './OpenUIMessage';
import {
  getDeliverableOpenUISections,
  getDeliverableSections,
  isRenderableOpenUILang,
} from './resolveOpenUILang';

/** Read-only formatted JSON shown when a section has no renderable Lang. */
function JsonFallback({ data }) {
  let text;
  try {
    text = JSON.stringify(data ?? {}, null, 2);
  } catch {
    text = String(data);
  }
  return (
    <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-xl border border-[#464646] bg-[#1a1a1a]/60 p-4 text-xs text-[#d8d8d8]">
      {text}
    </pre>
  );
}

function SectionBody({ lang, fallbackData, citations }) {
  if (isRenderableOpenUILang(lang)) {
    return (
      <OpenUIMessage
        content={lang}
        isStreaming={false}
        citations={citations}
        fallback={<JsonFallback data={fallbackData} />}
      />
    );
  }
  return <JsonFallback data={fallbackData} />;
}

function collectCitationNumbers(value, numbers = new Set()) {
  if (typeof value === 'string') {
    for (const match of value.matchAll(/\[(\d+)\]/g)) {
      numbers.add(Number(match[1]));
    }
    return numbers;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectCitationNumbers(item, numbers));
    return numbers;
  }
  if (value && typeof value === 'object') {
    Object.values(value).forEach((item) => collectCitationNumbers(item, numbers));
  }
  return numbers;
}

function shortSourceName(citation) {
  const metadata = citation?.chunk_metadata || {};
  return (
    citation?.document_name
    || citation?.title
    || metadata.document_name
    || metadata.file_name
    || metadata.filename
    || metadata.source
    || citation?.url
    || citation?.chunk_id
    || 'Source'
  );
}

function sourceLocation(citation) {
  const metadata = citation?.chunk_metadata || {};
  const page = citation?.page_number || metadata.page_number || metadata.page || metadata.slide_number || metadata.slide;
  const parts = [];
  if (page) parts.push(metadata.slide_number || metadata.slide ? `Slide ${page}` : `Page ${page}`);
  if (citation?.chunk_index !== undefined) parts.push(`Chunk ${Number(citation.chunk_index) + 1}`);
  if (citation?.relevance_score) parts.push(`${Math.round(Number(citation.relevance_score) * 100)}% match`);
  return parts.join(' · ');
}

function sourcePreview(citation) {
  const text = String(citation?.chunk_text || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > 260 ? `${text.slice(0, 260)}…` : text;
}

function SourcesPanel({ citations, sectionData }) {
  if (!Array.isArray(citations) || citations.length === 0) return null;
  const usedNumbers = collectCitationNumbers(sectionData);
  const visible = citations.filter((citation) => usedNumbers.has(Number(citation.citation_number)));
  if (visible.length === 0) return null;

  return (
    <details className="mt-4 rounded-xl border border-[#464646] bg-[#111111]/70 p-3 text-sm text-[#dadada]">
      <summary className="cursor-pointer select-none font-semibold text-white">
        Sources used in this section ({visible.length})
      </summary>
      <p className="mt-2 text-xs text-[#9d9d9d]">
        Click a citation badge in the content or source list to open the source details.
      </p>
      <div className="mt-3 grid gap-2">
        {visible.map((citation) => (
          <div key={citation.citation_number} className="flex gap-3 rounded-lg bg-white/[0.03] px-3 py-2">
            <span className="mt-0.5 flex-shrink-0">
              <OpenUICitationReference citationNumber={citation.citation_number} citationData={citation} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="break-words font-medium text-white" title={shortSourceName(citation)}>
                {shortSourceName(citation)}
              </div>
              {sourceLocation(citation) && (
                <div className="mt-0.5 text-xs text-[#9d9d9d]">{sourceLocation(citation)}</div>
              )}
              {sourcePreview(citation) && (
                <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-[#b5b5b5]">
                  {sourcePreview(citation)}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

/**
 * Renders pre-translated per-section OpenUI Lang from `agent_deliverable.openuiLang`
 * (a JSON array of Lang strings, index-aligned to the deliverable's sections[]).
 *
 * Builds a deterministic tab bar from sections[].section_title; one section
 * renders directly without tabs. This same component is used inline and in the
 * expanded modal, so both views are always identical.
 */
export default function DeliverableOpenUIView({
  deliverable,
  className = '',
  initialSectionIndex = 0,
  onActiveSectionChange,
}) {
  const sections = getDeliverableOpenUISections(deliverable);
  const rawSections = getDeliverableSections(deliverable);
  const [active, setActive] = useState(initialSectionIndex);

  // Re-sync the active tab when the deliverable changes or when a caller
  // requests a specific starting tab (deep-link from the Output panel, or
  // carrying the inline tab into the expanded view).
  useEffect(() => {
    setActive(initialSectionIndex);
  }, [deliverable?.id, initialSectionIndex]);

  // Never show a "preparing" placeholder: a deliverable is only displayed once
  // its OpenUI Lang is ready. While translation is still pending (or this isn't
  // an OpenUI deliverable) render nothing; the chat keeps polling and fills the
  // view in as soon as the Lang lands.
  if (sections.length === 0) {
    return null;
  }

  const activeIdx = Math.min(active, sections.length - 1);
  const fallbackFor = (index) => rawSections?.[index] ?? deliverable?.deliverable ?? null;
  const citations = deliverable?.deliverable?._citations;

  if (sections.length === 1) {
    const fallbackData = fallbackFor(0);
    return (
      <div className={className}>
        <SectionBody lang={sections[0].lang} fallbackData={fallbackData} citations={citations} />
        <SourcesPanel citations={citations} sectionData={fallbackData} />
      </div>
    );
  }

  const activeFallbackData = fallbackFor(activeIdx);

  return (
    <div className={className}>
      <div
        role="tablist"
        className="mb-3 flex flex-wrap items-center gap-1 border-b border-[#464646] pb-1"
      >
        {sections.map((section, index) => {
          const isActive = index === activeIdx;
          return (
            <button
              key={index}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => {
                setActive(index);
                onActiveSectionChange?.(index);
              }}
              className={`rounded-t-lg px-3 py-2 text-xs font-semibold transition-colors ${
                isActive
                  ? 'border-b-2 border-[#d93854] text-white'
                  : 'text-[#b5b5b5] hover:text-white'
              }`}
            >
              {section.title}
            </button>
          );
        })}
      </div>
      <div key={activeIdx} className="animate-in fade-in duration-200">
        <SectionBody lang={sections[activeIdx].lang} fallbackData={activeFallbackData} citations={citations} />
        <SourcesPanel citations={citations} sectionData={activeFallbackData} />
      </div>
    </div>
  );
}
