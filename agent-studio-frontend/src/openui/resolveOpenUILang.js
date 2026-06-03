/**
 * Read renderable OpenUI Lang from the deliverable `openuiLang` column.
 *
 * The backend stores a JSON array of per-section OpenUI Lang strings,
 * index-aligned to the deliverable's `sections[]`. Each entry is a plain
 * `root = ...` program; a failed section is an empty string. There is no
 * legacy plain-string or envelope format.
 */

const ROOT_RE = /^root\s*=/m;
const OPENUI_OUTPUT_TYPES = new Set([undefined, null, '', 'sections']);

export function isRenderableOpenUILang(text) {
  if (typeof text !== 'string') return false;
  const trimmed = text.trim();
  return trimmed.length >= 24 && ROOT_RE.test(trimmed);
}

export function readDeliverableOpenUILang(deliverable) {
  if (!deliverable) return '';
  const raw = deliverable.openuiLang ?? deliverable.openui_lang;
  return typeof raw === 'string' ? raw : '';
}

/** Parse the column into an array of per-section Lang strings ([] when not ready). */
export function parseSectionLangs(deliverable) {
  const raw = readDeliverableOpenUILang(deliverable).trim();
  if (!raw || raw[0] !== '[') return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((lang) => (typeof lang === 'string' ? lang : ''));
  } catch {
    return [];
  }
}

/** The deliverable's `sections[]` array, or null when not sectioned. */
export function getDeliverableSections(deliverable) {
  const data = deliverable?.deliverable;
  const content = typeof data === 'object' && data !== null ? data : null;
  return content && Array.isArray(content.sections) ? content.sections : null;
}

/**
 * Normalized render model: [{ title, lang }] paired by index with sections[].
 * Returns [] when OpenUI Lang is not ready yet.
 */
export function getDeliverableOpenUISections(deliverable) {
  const langs = parseSectionLangs(deliverable);
  if (langs.length === 0) return [];
  const sections = getDeliverableSections(deliverable);
  return langs.map((lang, index) => ({
    title:
      sections?.[index]?.section_title
      || sections?.[index]?.title
      || `Section ${index + 1}`,
    lang,
  }));
}

export function requiresOpenUI(deliverable) {
  if (!deliverable) return false;
  if (deliverable.agentType === 'code-executor' || deliverable.agentType === 'powerpoint-generator') {
    return false;
  }
  const data = deliverable.deliverable;
  const outputType = deliverable.outputType ?? (typeof data === 'object' ? data?._output_type : undefined);
  return OPENUI_OUTPUT_TYPES.has(outputType);
}

export function hasRenderableOpenUI(deliverable) {
  if (!requiresOpenUI(deliverable)) return true;
  return parseSectionLangs(deliverable).some(isRenderableOpenUILang);
}

export function getDeliverableSummary(deliverable) {
  const data = deliverable?.deliverable;
  const summary = (typeof data === 'object' && data?.summary) || deliverable?.summary;
  if (typeof summary === 'string') return summary.trim() || null;
  return null;
}
