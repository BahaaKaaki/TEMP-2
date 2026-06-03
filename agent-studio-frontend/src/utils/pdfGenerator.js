import { jsPDF } from 'jspdf';

const COLORS = {
  primary: [163, 32, 32],
  dark: [31, 41, 55],
  gray: [75, 85, 99],
  lightGray: [107, 114, 128],
  body: [55, 65, 81],
  white: [255, 255, 255],
  accent: [59, 130, 246],
  bgLight: [243, 244, 246],
  bgLighter: [249, 250, 251],
  link: [37, 99, 235],
  divider: [209, 213, 219],
};

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

function objectLooksLikeEvidence(obj) {
  return obj && typeof obj === 'object' && 'exact_text_content' in obj;
}

function objectLooksLikeLink(obj) {
  return obj && typeof obj === 'object' && 'url' in obj;
}

export function generateDeliverablePDF(deliverableData, deliverableInfo = {}) {
  const doc = new jsPDF();
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 18;
  const maxWidth = pageWidth - 2 * margin;
  let yPos = margin;

  const checkPageBreak = (space = 15) => {
    if (yPos + space > pageHeight - 20) {
      doc.addPage();
      yPos = margin;
      return true;
    }
    return false;
  };

  const wrap = (text, width, fontSize) => {
    doc.setFontSize(fontSize);
    return doc.splitTextToSize(strip(String(text || '')), width);
  };

  const addText = (text, x, width, fontSize, style = 'normal', color = COLORS.body) => {
    doc.setFontSize(fontSize);
    doc.setFont('helvetica', style);
    doc.setTextColor(...color);
    const lines = wrap(text, width, fontSize);
    lines.forEach(line => {
      checkPageBreak();
      doc.text(line, x, yPos);
      yPos += fontSize * 0.52;
    });
  };

  const drawSeparator = () => {
    doc.setDrawColor(...COLORS.divider);
    doc.setLineWidth(0.2);
    doc.line(margin, yPos, pageWidth - margin, yPos);
    yPos += 8;
  };

  // ── Recursive smart renderer ──
  const renderValue = (value, x, width, depth = 0) => {
    if (value === null || value === undefined) return;

    if (isScalar(value)) {
      addText(value, x, width, 9, 'normal', COLORS.body);
      yPos += 2;
      return;
    }

    if (Array.isArray(value)) {
      value.forEach((item, idx) => {
        checkPageBreak(10);
        if (isScalar(item)) {
          addText(`\u2022  ${strip(String(item))}`, x + 3, width - 3, 9, 'normal', COLORS.body);
          yPos += 1;
        } else if (objectLooksLikeEvidence(item)) {
          renderEvidence(item, idx, x, width);
        } else if (objectLooksLikeLink(item)) {
          renderLink(item, x, width);
        } else if (typeof item === 'object') {
          renderObjectAsBullet(item, x, width, depth);
          yPos += 2;
        }
      });
      return;
    }

    if (typeof value === 'object') {
      renderObject(value, x, width, depth);
    }
  };

  // Render an object's key-value pairs
  const renderObject = (obj, x, width, depth = 0) => {
    if (!obj) return;
    Object.entries(obj).forEach(([key, val]) => {
      if (SKIP_KEYS.has(key)) return;
      checkPageBreak(10);

      const label = formatKey(key);

      if (key === 'sub_pillars' && Array.isArray(val)) {
        val.forEach((sp, spIdx) => renderSubPillar(sp, spIdx, x, width));
        return;
      }
      if (key === 'evidence_collected' && Array.isArray(val)) {
        val.forEach((ev, evIdx) => renderEvidence(ev, evIdx, x, width));
        return;
      }
      if (key === 'salesforce_links' && Array.isArray(val)) {
        val.forEach(link => renderLink(link, x, width));
        return;
      }

      if (isScalar(val)) {
        // Key: Value on same line (or wrapped)
        doc.setFontSize(9);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(...COLORS.gray);
        const labelWidth = doc.getTextWidth(`${label}: `);

        if (String(val).length < 80) {
          checkPageBreak();
          doc.text(`${label}: `, x, yPos);
          doc.setFont('helvetica', 'normal');
          doc.setTextColor(...COLORS.body);
          doc.text(strip(String(val)), x + labelWidth, yPos);
          yPos += 5.5;
        } else {
          doc.text(`${label}:`, x, yPos);
          yPos += 5;
          addText(val, x + 4, width - 4, 9, 'normal', COLORS.body);
          yPos += 1;
        }
      } else if (Array.isArray(val)) {
        doc.setFontSize(9);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(...COLORS.gray);
        doc.text(`${label}:`, x, yPos);
        yPos += 5;
        renderValue(val, x + 4, width - 4, depth + 1);
        yPos += 2;
      } else if (typeof val === 'object' && val !== null) {
        doc.setFontSize(9);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(...COLORS.gray);
        doc.text(`${label}:`, x, yPos);
        yPos += 5;
        renderObject(val, x + 4, width - 4, depth + 1);
        yPos += 2;
      }
    });
  };

  // Render an object as a nicely formatted bullet (for arrays of objects)
  const renderObjectAsBullet = (obj, x, width, depth) => {
    const titleKey = findTitleKey(obj);
    const descKey = findDescriptionKey(obj);

    if (titleKey) {
      checkPageBreak();
      doc.setFontSize(9);
      doc.setFont('helvetica', 'bold');
      doc.setTextColor(...COLORS.accent);
      const bulletLines = wrap(`\u2022  ${obj[titleKey]}`, width, 9);
      bulletLines.forEach(line => {
        checkPageBreak();
        doc.text(line, x + 3, yPos);
        yPos += 5;
      });

      if (descKey && obj[descKey]) {
        addText(obj[descKey], x + 10, width - 10, 9, 'normal', COLORS.body);
      }

      // Render remaining keys
      Object.entries(obj).forEach(([k, v]) => {
        if (k === titleKey || k === descKey || SKIP_KEYS.has(k)) return;
        if (isScalar(v) && String(v).length < 120) {
          checkPageBreak();
          doc.setFontSize(8);
          doc.setFont('helvetica', 'normal');
          doc.setTextColor(...COLORS.lightGray);
          doc.text(`${formatKey(k)}: ${strip(String(v))}`, x + 10, yPos);
          yPos += 4.5;
        } else if (!isScalar(v)) {
          renderValue(v, x + 10, width - 10, depth + 1);
        }
      });
    } else {
      // No obvious title: render all key-value pairs
      renderObject(obj, x + 4, width - 4, depth + 1);
    }
  };

  // Sub-pillar rendering
  const renderSubPillar = (sp, idx, x, width) => {
    checkPageBreak(18);
    const title = sp.sub_pillar_title || `Sub-pillar ${idx + 1}`;

    doc.setFontSize(10);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...COLORS.accent);
    const titleLines = wrap(title, width - 6, 10);
    titleLines.forEach(line => {
      checkPageBreak();
      doc.text(line, x + 6, yPos);
      yPos += 5.5;
    });
    yPos += 2;

    // Render all other sub-pillar keys
    Object.entries(sp).forEach(([key, val]) => {
      if (key === 'sub_pillar_title' || SKIP_KEYS.has(key)) return;

      if (key === 'evidence_collected' && Array.isArray(val)) {
        val.forEach((ev, evIdx) => renderEvidence(ev, evIdx, x + 8, width - 8));
      } else {
        renderValue(val, x + 8, width - 8, 1);
      }
    });
    yPos += 3;
  };

  // Evidence block rendering
  const renderEvidence = (ev, idx, x, width) => {
    const cleanText = strip(ev.exact_text_content || '');
    if (!cleanText) return;

    const evLines = wrap(cleanText, width - 12, 9);
    const boxHeight = Math.max(evLines.length * 4.5 + 16, 22);
    checkPageBreak(boxHeight + 8);

    doc.setFillColor(...COLORS.bgLighter);
    doc.setDrawColor(...COLORS.divider);
    doc.roundedRect(x + 4, yPos - 2, width - 4, boxHeight, 1.5, 1.5, 'FD');

    doc.setFontSize(7);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...COLORS.lightGray);
    doc.text(`EVIDENCE ${idx + 1}`, x + 7, yPos + 3);
    yPos += 7;

    doc.setFontSize(9);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...COLORS.body);
    evLines.forEach(line => {
      checkPageBreak();
      doc.text(line, x + 7, yPos);
      yPos += 4.5;
    });
    yPos += 2;

    // Source info
    const parts = [];
    if (ev.source_file) parts.push(`Source: ${ev.source_file}`);
    if (ev.page_numbers?.length) parts.push(`Pages: ${ev.page_numbers.join(', ')}`);
    if (parts.length) {
      doc.setFontSize(7.5);
      doc.setFont('helvetica', 'italic');
      doc.setTextColor(...COLORS.lightGray);
      doc.text(parts.join('  |  '), x + 7, yPos);
      yPos += 5;
    }

    // Salesforce links
    (ev.salesforce_links || []).forEach(link => renderLink(link, x + 7, width - 7));
    yPos += 4;
  };

  // Link rendering
  const renderLink = (link, x, width) => {
    if (!link?.url) return;
    checkPageBreak(6);
    doc.setFontSize(7.5);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...COLORS.link);
    const snippet = link.supporting_content_snippet ? `${strip(link.supporting_content_snippet)}: ` : '';
    const linkText = `${snippet}${link.url}`;
    const lines = wrap(linkText, width, 7.5);
    lines.forEach(line => {
      checkPageBreak();
      doc.text(line, x, yPos);
      yPos += 4;
    });
    yPos += 1;
  };

  // ── Cover header ──
  doc.setFillColor(...COLORS.primary);
  doc.rect(0, 0, pageWidth, 40, 'F');

  doc.setFontSize(18);
  doc.setFont('helvetica', 'bold');
  doc.setTextColor(...COLORS.white);
  const title = deliverableInfo.agentLabel || 'Deliverable Report';
  const titleLines = doc.splitTextToSize(title, maxWidth);
  titleLines.forEach((line, i) => {
    doc.text(line, margin, 18 + i * 9);
  });

  if (deliverableInfo.createdAt) {
    const dateStr = new Date(deliverableInfo.createdAt).toLocaleDateString('en-US', {
      year: 'numeric', month: 'long', day: 'numeric',
    });
    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.text(dateStr, margin, 34);
  }

  yPos = 52;

  // ── Parse content ──
  let content = deliverableData;
  if (typeof content === 'string') {
    try { content = JSON.parse(content); } catch { content = { sections: [] }; }
  }

  const sections = content?.sections || [];

  // ── Render each section ──
  sections.forEach((section, sIdx) => {
    checkPageBreak(35);

    // Section banner
    doc.setFillColor(...COLORS.bgLight);
    const sectionTitle = section.section_title || `Section ${sIdx + 1}`;
    const sTitleLines = wrap(sectionTitle, maxWidth - 12, 12);
    const bannerH = Math.max(sTitleLines.length * 7 + 4, 14);

    doc.roundedRect(margin, yPos - 2, maxWidth, bannerH, 2, 2, 'F');
    doc.setDrawColor(...COLORS.primary);
    doc.setLineWidth(0.8);
    doc.line(margin, yPos - 2, margin, yPos - 2 + bannerH);

    doc.setFontSize(12);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...COLORS.dark);
    sTitleLines.forEach((line, i) => {
      doc.text(line, margin + 5, yPos + 5 + i * 6);
    });
    yPos += bannerH + 6;

    // Section description
    if (section.description) {
      addText(section.description, margin + 4, maxWidth - 8, 9, 'italic', COLORS.lightGray);
      yPos += 3;
    }

    // Render ALL content keys smartly
    const sectionContent = section.content;
    if (sectionContent && typeof sectionContent === 'object') {
      renderObject(sectionContent, margin + 4, maxWidth - 8, 0);
    } else if (isScalar(sectionContent)) {
      addText(sectionContent, margin + 4, maxWidth - 8, 9, 'normal', COLORS.body);
    }

    yPos += 4;
    drawSeparator();
  });

  // ── Page footers ──
  const totalPages = doc.internal.getNumberOfPages();
  for (let i = 1; i <= totalPages; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(...COLORS.lightGray);
    doc.text(`Page ${i} of ${totalPages}`, pageWidth / 2, pageHeight - 8, { align: 'center' });
    if (deliverableInfo.agentLabel) {
      doc.text(`Generated by ${deliverableInfo.agentLabel}`, margin, pageHeight - 8);
    }
  }

  return doc;
}

function findTitleKey(obj) {
  const candidates = ['term', 'title', 'name', 'label', 'pillar', 'sub_pillar_title', 'pillar_title', 'recommendation', 'heading'];
  return candidates.find(k => typeof obj[k] === 'string');
}

function findDescriptionKey(obj) {
  const candidates = ['definition', 'description', 'value', 'justification', 'explanation', 'content', 'pillar_description', 'detail', 'summary'];
  return candidates.find(k => typeof obj[k] === 'string');
}

export function downloadDeliverablePDF(deliverableData, deliverableInfo = {}) {
  const doc = generateDeliverablePDF(deliverableData, deliverableInfo);
  const label = deliverableInfo.agentLabel || 'deliverable';
  const filename = `${label.toLowerCase().replace(/[^a-z0-9]+/g, '-').substring(0, 50)}-report.pdf`;
  doc.save(filename);
}

export function generateReportPDF(reportData, deliverableInfo = {}) {
  return generateDeliverablePDF(reportData, deliverableInfo);
}

export function downloadReportPDF(reportData, deliverableInfo = {}) {
  return downloadDeliverablePDF(reportData, deliverableInfo);
}
