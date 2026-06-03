/**
 * Export a deliverable as a fully interactive, self-contained HTML file.
 *
 * Rather than snapshotting the DOM (which freezes OpenUI's React-driven
 * behavior -- chart tooltips, sub-toggles, table pagination, org-chart
 * pan/zoom), we ship the actual renderer. `public/viewer.html` is a single
 * self-contained bundle (React + the OpenUI Lang renderer + our component
 * library, all inlined) built by `vite.viewer.config.js`. Here we fetch that
 * bundle, inject the deliverable's per-section Lang as `window.__DELIVERABLE__`,
 * and download it. Opening the file re-renders the deliverable live and
 * offline, identical to and as interactive as the in-app view.
 */

const VIEWER_URL = '/viewer.html';
const DATA_PLACEHOLDER = '"__DELIVERABLE_DATA_PLACEHOLDER__"';

/**
 * Serialize the deliverable payload into a JS-literal-safe string and inline it
 * into the viewer template. `<` is escaped so the JSON can never prematurely
 * close the surrounding inline <script>.
 */
function injectDeliverableData(template, data) {
  const json = JSON.stringify(data).replace(/</g, '\\u003c').replace(/\u2028|\u2029/g, '');
  if (!template.includes(DATA_PLACEHOLDER)) {
    throw new Error('Viewer template is missing the deliverable data placeholder.');
  }
  // Function replacement so `$` sequences in the JSON aren't treated specially.
  return template.replace(DATA_PLACEHOLDER, () => json);
}

function triggerDownload(html, title) {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  const label = String(title || 'Deliverable')
    .replace(/[^\w\s]/g, '_')
    .replace(/\s+/g, '_');
  a.download = `${label || 'Deliverable'}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(blobUrl);
}

/**
 * Build and download an interactive standalone HTML for a deliverable.
 *
 * @param {{ title?: string, summary?: string, sections: Array<{ title: string, lang: string }> }} data
 */
export async function downloadInteractiveDeliverableHtml(data) {
  const sections = Array.isArray(data?.sections) ? data.sections : [];
  if (sections.length === 0) {
    throw new Error('Nothing to export yet.');
  }
  const res = await fetch(VIEWER_URL, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Could not load the viewer template (${res.status}).`);
  }
  const template = await res.text();
  const payload = {
    title: data?.title || 'Deliverable',
    summary: data?.summary || '',
    sections: sections.map((s) => ({
      title: s?.title || '',
      lang: typeof s?.lang === 'string' ? s.lang : '',
    })),
  };
  const html = injectDeliverableData(template, payload);
  triggerDownload(html, payload.title);
}
