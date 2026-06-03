import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  AlignmentType,
  BorderStyle,
  ShadingType,
  ExternalHyperlink,
  Header,
  Footer,
  PageNumber,
} from 'docx';
import { saveAs } from 'file-saver';

const BRAND_RED = 'A32020';
const DARK = '1F2937';
const GRAY = '4B5563';
const LIGHT_GRAY = '6B7280';
const BODY = '374151';
const ACCENT_BLUE = '3B82F6';
const BG_LIGHT = 'F3F4F6';

const SKIP_KEYS = new Set(['_citations', 'citation_markers', 'sub_pillar_definition']);

function strip(text) {
  return (text || '').replace(/\s*\[\d+\]/g, '');
}

function formatKey(key) {
  return key
    .replace(/([A-Z])/g, ' $1')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .trim();
}

function isScalar(v) {
  return typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean';
}

function findTitleKey(obj) {
  const candidates = ['term', 'title', 'name', 'label', 'pillar', 'sub_pillar_title', 'pillar_title', 'recommendation', 'heading'];
  return candidates.find(k => typeof obj[k] === 'string');
}

function findDescriptionKey(obj) {
  const candidates = ['definition', 'description', 'value', 'justification', 'explanation', 'content', 'pillar_description', 'detail', 'summary'];
  return candidates.find(k => typeof obj[k] === 'string');
}

function hasEvidenceShape(obj) {
  return obj && typeof obj === 'object' && 'exact_text_content' in obj;
}

function hasLinkShape(obj) {
  return obj && typeof obj === 'object' && 'url' in obj;
}

// ── Core recursive renderer ──
// Pushes Paragraph nodes into `children` array for any data shape.

function renderValue(children, value, indent, depth = 0) {
  if (value === null || value === undefined) return;

  if (isScalar(value)) {
    children.push(para(strip(String(value)), { size: 19, color: BODY, indent }));
    return;
  }

  if (Array.isArray(value)) {
    value.forEach((item, idx) => {
      if (isScalar(item)) {
        children.push(para(`\u2022  ${strip(String(item))}`, { size: 19, color: BODY, indent: indent + 100 }));
      } else if (hasEvidenceShape(item)) {
        renderEvidence(children, item, idx, indent);
      } else if (hasLinkShape(item)) {
        renderLink(children, item, indent);
      } else if (typeof item === 'object') {
        renderObjectAsBullet(children, item, indent, depth);
      }
    });
    return;
  }

  if (typeof value === 'object') {
    renderObject(children, value, indent, depth);
  }
}

function renderObject(children, obj, indent, depth = 0) {
  if (!obj) return;

  Object.entries(obj).forEach(([key, val]) => {
    if (SKIP_KEYS.has(key)) return;

    const label = formatKey(key);

    // Special-case known structures
    if (key === 'sub_pillars' && Array.isArray(val)) {
      val.forEach((sp, i) => renderSubPillar(children, sp, i, indent));
      return;
    }
    if (key === 'evidence_collected' && Array.isArray(val)) {
      val.forEach((ev, i) => renderEvidence(children, ev, i, indent));
      return;
    }
    if (key === 'salesforce_links' && Array.isArray(val)) {
      val.forEach(link => renderLink(children, link, indent));
      return;
    }

    if (isScalar(val)) {
      // Short values: inline "Key: Value"
      if (String(val).length < 100) {
        children.push(new Paragraph({
          children: [
            new TextRun({ text: `${label}: `, bold: true, size: 18, color: GRAY, font: 'Calibri' }),
            new TextRun({ text: strip(String(val)), size: 18, color: BODY, font: 'Calibri' }),
          ],
          spacing: { after: 80 },
          indent: { left: indent },
        }));
      } else {
        // Long values: label on its own line, then wrapped text
        children.push(para(label + ':', { size: 18, color: GRAY, bold: true, indent, after: 40 }));
        children.push(para(strip(String(val)), { size: 18, color: BODY, indent: indent + 150, after: 80 }));
      }
    } else if (Array.isArray(val)) {
      children.push(para(label + ':', { size: 18, color: GRAY, bold: true, indent, after: 40 }));
      renderValue(children, val, indent + 150, depth + 1);
    } else if (typeof val === 'object' && val !== null) {
      children.push(para(label + ':', { size: 18, color: GRAY, bold: true, indent, after: 40 }));
      renderObject(children, val, indent + 150, depth + 1);
    }
  });
}

// Render an object from an array as a nicely formatted bullet
function renderObjectAsBullet(children, obj, indent, depth) {
  const titleKey = findTitleKey(obj);
  const descKey = findDescriptionKey(obj);

  if (titleKey) {
    children.push(new Paragraph({
      children: [
        new TextRun({ text: '\u2022  ', size: 19, color: ACCENT_BLUE, font: 'Calibri' }),
        new TextRun({ text: strip(obj[titleKey]), bold: true, size: 19, color: ACCENT_BLUE, font: 'Calibri' }),
      ],
      spacing: { before: 80, after: 40 },
      indent: { left: indent + 100 },
    }));

    if (descKey && obj[descKey]) {
      children.push(para(strip(obj[descKey]), { size: 18, color: BODY, indent: indent + 300, after: 60 }));
    }

    // Render remaining scalar keys as small metadata
    Object.entries(obj).forEach(([k, v]) => {
      if (k === titleKey || k === descKey || SKIP_KEYS.has(k)) return;
      if (isScalar(v)) {
        children.push(new Paragraph({
          children: [
            new TextRun({ text: `${formatKey(k)}: `, bold: true, size: 16, color: LIGHT_GRAY, font: 'Calibri' }),
            new TextRun({ text: strip(String(v)), size: 16, color: GRAY, font: 'Calibri' }),
          ],
          spacing: { after: 30 },
          indent: { left: indent + 300 },
        }));
      } else if (!isScalar(v)) {
        renderValue(children, v, indent + 300, depth + 1);
      }
    });
  } else {
    renderObject(children, obj, indent + 150, depth + 1);
  }
}

// Sub-pillar
function renderSubPillar(children, sp, idx, indent) {
  const title = sp.sub_pillar_title || `Sub-pillar ${idx + 1}`;

  children.push(new Paragraph({
    children: [
      new TextRun({ text: title, bold: true, size: 22, color: ACCENT_BLUE, font: 'Calibri' }),
    ],
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 100 },
    indent: { left: indent + 200 },
  }));

  Object.entries(sp).forEach(([key, val]) => {
    if (key === 'sub_pillar_title' || SKIP_KEYS.has(key)) return;
    if (key === 'evidence_collected' && Array.isArray(val)) {
      val.forEach((ev, i) => renderEvidence(children, ev, i, indent + 200));
    } else {
      renderValue(children, val, indent + 200, 1);
    }
  });
}

// Evidence block
function renderEvidence(children, ev, idx, indent) {
  const cleanText = strip(ev.exact_text_content || '');
  if (!cleanText) return;

  children.push(para(`EVIDENCE ${idx + 1}`, {
    size: 15, color: LIGHT_GRAY, bold: true, allCaps: true,
    indent: indent + 200, before: 160, after: 40,
  }));

  children.push(new Paragraph({
    children: [
      new TextRun({ text: cleanText, size: 18, color: BODY, font: 'Calibri' }),
    ],
    shading: { type: ShadingType.CLEAR, fill: 'F9FAFB' },
    border: { left: { style: BorderStyle.SINGLE, size: 4, color: 'D1D5DB', space: 6 } },
    spacing: { after: 60 },
    indent: { left: indent + 200 },
  }));

  // Source info
  const parts = [];
  if (ev.source_file) parts.push(`Source: ${ev.source_file}`);
  if (ev.page_numbers?.length) parts.push(`Pages: ${ev.page_numbers.join(', ')}`);
  if (parts.length) {
    children.push(para(parts.join('   |   '), {
      size: 16, color: LIGHT_GRAY, italics: true, indent: indent + 200, after: 40,
    }));
  }

  // Salesforce links
  (ev.salesforce_links || []).forEach(link => renderLink(children, link, indent + 200));
}

// Salesforce / hyperlink
function renderLink(children, link, indent) {
  if (!link?.url) return;
  const runs = [];
  if (link.supporting_content_snippet) {
    runs.push(new TextRun({ text: `${strip(link.supporting_content_snippet)}: `, size: 16, color: GRAY, font: 'Calibri' }));
  }
  runs.push(
    new ExternalHyperlink({
      children: [new TextRun({ text: link.url, style: 'Hyperlink', size: 16, color: '2563EB', font: 'Calibri' })],
      link: link.url,
    }),
  );
  children.push(new Paragraph({ children: runs, spacing: { after: 30 }, indent: { left: indent } }));
}

// ── Convenience paragraph builder ──
function para(text, opts = {}) {
  return new Paragraph({
    children: [
      new TextRun({
        text: strip(String(text)),
        size: opts.size || 19,
        color: opts.color || BODY,
        bold: opts.bold || false,
        italics: opts.italics || false,
        allCaps: opts.allCaps || false,
        font: 'Calibri',
      }),
    ],
    spacing: { before: opts.before || 0, after: opts.after || 80 },
    indent: opts.indent != null ? { left: opts.indent } : undefined,
    ...(opts.shading ? { shading: opts.shading } : {}),
    ...(opts.border ? { border: opts.border } : {}),
  });
}


// ── Main export function ──

export async function downloadDeliverableDOCX(deliverableData, deliverableInfo = {}) {
  let data = deliverableData;
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch { data = { sections: [] }; }
  }

  const sections = data?.sections || [];
  const children = [];

  // Title
  children.push(new Paragraph({
    children: [
      new TextRun({ text: deliverableInfo.agentLabel || 'Deliverable Report', bold: true, size: 40, color: BRAND_RED, font: 'Calibri' }),
    ],
    spacing: { after: 120 },
  }));

  // Date
  if (deliverableInfo.createdAt) {
    const dateStr = new Date(deliverableInfo.createdAt).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    children.push(para(dateStr, { size: 20, color: LIGHT_GRAY, italics: true, after: 200 }));
  }

  // Divider
  children.push(new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BRAND_RED } },
    spacing: { after: 300 },
  }));

  // Each section
  sections.forEach((section, sIdx) => {
    const sectionTitle = section.section_title || `Section ${sIdx + 1}`;

    // Section heading
    children.push(new Paragraph({
      children: [
        new TextRun({ text: sectionTitle, bold: true, size: 26, color: DARK, font: 'Calibri' }),
      ],
      heading: HeadingLevel.HEADING_1,
      shading: { type: ShadingType.CLEAR, fill: BG_LIGHT },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: BRAND_RED, space: 8 } },
      spacing: { before: 360, after: 120 },
    }));

    // Section description
    if (section.description) {
      children.push(para(section.description, { size: 19, color: LIGHT_GRAY, italics: true, indent: 200, after: 160 }));
    }

    // Render ALL content keys smartly
    const sectionContent = section.content;
    if (sectionContent && typeof sectionContent === 'object') {
      renderObject(children, sectionContent, 200, 0);
    } else if (isScalar(sectionContent)) {
      children.push(para(strip(String(sectionContent)), { indent: 200 }));
    }

    // Section separator
    children.push(new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: 'E5E7EB' } },
      spacing: { before: 200, after: 200 },
    }));
  });

  const doc = new Document({
    creator: deliverableInfo.agentLabel || 'Agent Studio',
    title: deliverableInfo.agentLabel || 'Deliverable Report',
    styles: {
      default: {
        document: { run: { font: 'Calibri', size: 20, color: BODY } },
        heading1: { run: { font: 'Calibri', size: 26, bold: true, color: DARK } },
        heading2: { run: { font: 'Calibri', size: 22, bold: true, color: ACCENT_BLUE } },
      },
    },
    sections: [{
      properties: {
        page: { margin: { top: 1000, bottom: 800, left: 1000, right: 1000 } },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            children: [new TextRun({ text: deliverableInfo.agentLabel || 'Deliverable Report', size: 16, color: LIGHT_GRAY, font: 'Calibri' })],
            alignment: AlignmentType.RIGHT,
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            children: [
              new TextRun({ text: 'Generated by Agent Studio  \u2014  Page ', size: 16, color: LIGHT_GRAY, font: 'Calibri' }),
              new TextRun({ children: [PageNumber.CURRENT], size: 16, color: LIGHT_GRAY, font: 'Calibri' }),
            ],
            alignment: AlignmentType.CENTER,
          })],
        }),
      },
      children,
    }],
  });

  const blob = await Packer.toBlob(doc);
  const label = deliverableInfo.agentLabel || 'deliverable';
  const filename = `${label.toLowerCase().replace(/[^a-z0-9]+/g, '-').substring(0, 50)}-report.docx`;
  saveAs(blob, filename);
}
