import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  getDeliverableOpenUISections,
  hasRenderableOpenUI,
  parseSectionLangs,
} from './resolveOpenUILang.js';

const lang0 = 'root = Stack([Text("section one content")])';
const lang1 = 'root = Stack([Text("section two content")])';

describe('parseSectionLangs', () => {
  it('parses a JSON array of lang strings', () => {
    const d = { openuiLang: JSON.stringify([lang0, lang1]) };
    assert.deepEqual(parseSectionLangs(d), [lang0, lang1]);
  });

  it('returns [] for a non-array string (no plain-string fallback)', () => {
    assert.deepEqual(parseSectionLangs({ openuiLang: lang0 }), []);
  });

  it('returns [] for empty or missing values', () => {
    assert.deepEqual(parseSectionLangs({ openuiLang: '' }), []);
    assert.deepEqual(parseSectionLangs({}), []);
  });

  it('coerces non-string entries to empty strings', () => {
    const d = { openuiLang: JSON.stringify([lang0, null, 5]) };
    assert.deepEqual(parseSectionLangs(d), [lang0, '', '']);
  });
});

describe('getDeliverableOpenUISections', () => {
  it('pairs langs with section titles by index', () => {
    const d = {
      openuiLang: JSON.stringify([lang0, lang1]),
      deliverable: { sections: [{ section_title: 'Overview' }, { section_title: 'Risks' }] },
    };
    assert.deepEqual(getDeliverableOpenUISections(d), [
      { title: 'Overview', lang: lang0 },
      { title: 'Risks', lang: lang1 },
    ]);
  });

  it('falls back to Section N when no title', () => {
    const d = { openuiLang: JSON.stringify([lang0]), deliverable: {} };
    assert.deepEqual(getDeliverableOpenUISections(d), [{ title: 'Section 1', lang: lang0 }]);
  });
});

describe('hasRenderableOpenUI', () => {
  it('waits when openuiLang is missing', () => {
    assert.equal(hasRenderableOpenUI({ deliverable: {}, outputType: 'sections' }), false);
  });

  it('is ready when at least one section is renderable', () => {
    const d = { outputType: 'sections', deliverable: {}, openuiLang: JSON.stringify([lang0, '']) };
    assert.equal(hasRenderableOpenUI(d), true);
  });

  it('waits when all sections failed (empty strings)', () => {
    const d = { outputType: 'sections', deliverable: {}, openuiLang: JSON.stringify(['', '']) };
    assert.equal(hasRenderableOpenUI(d), false);
  });
});
