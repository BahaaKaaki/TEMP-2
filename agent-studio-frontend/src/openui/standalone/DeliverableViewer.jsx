/**
 * Standalone deliverable viewer.
 *
 * Renders an embedded deliverable (summary + per-section OpenUI Lang) using the
 * exact same `DeliverableOpenUIView` the app uses, so the exported HTML is the
 * live OpenUI render -- fully interactive (tabs, chart tooltips, sub-toggles,
 * org-chart pan/zoom). Data is injected by the exporter as `window.__DELIVERABLE__`.
 */

import DeliverableOpenUIView from '../DeliverableOpenUIView';

export default function DeliverableViewer({ data }) {
  const sections = Array.isArray(data?.sections) ? data.sections : [];

  // Reconstruct the minimal deliverable shape `DeliverableOpenUIView` expects:
  // an `openuiLang` JSON array of per-section Lang strings, index-aligned to a
  // `sections[]` carrying titles.
  const deliverable = {
    id: 'export',
    deliverable: {
      summary: data?.summary || '',
      sections: sections.map((s) => ({ section_title: s?.title })),
    },
    openuiLang: JSON.stringify(sections.map((s) => (typeof s?.lang === 'string' ? s.lang : ''))),
  };

  return (
    <div style={{ minHeight: '100vh', background: '#2a2a2a' }}>
      <div
        className="deliverable-dark-theme"
        style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}
      >
        {data?.summary ? (
          <p style={{ color: '#e5e5e5', marginBottom: 16, fontSize: 14, lineHeight: 1.6 }}>
            {data.summary}
          </p>
        ) : null}
        <DeliverableOpenUIView deliverable={deliverable} />
      </div>
    </div>
  );
}
