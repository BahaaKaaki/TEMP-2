/**
 * Monaco editor theme + chrome tokens aligned with Apex OS (figmaSpec / apexShellSpec).
 */
import { COLOR, CATEGORY } from '../components/builder/figmaSpec';

export const APEX_MONACO_THEME = 'apex-os';

/** Shell colours for CodeEditorModal, diff drawer, and preview card. */
export const CODE_EDITOR_CHROME = {
  bg: COLOR.black,
  panel: COLOR.darkest,
  surface: '#222222',
  border: COLOR.darker,
  muted: COLOR.medium,
  text: COLOR.light,
  textBright: COLOR.white,
  accent: CATEGORY.agent.accent,
  accentHover: '#9a3dd4',
  accentSoft: 'rgba(130, 22, 197, 0.18)',
  cta: COLOR.rose,
  ctaHover: '#c52a45',
  ctaSoft: COLOR.roseDarkBg,
  success: '#20f778',
  successBg: 'rgba(24, 35, 29, 0.55)',
  error: '#ff4d6e',
  errorBg: 'rgba(42, 20, 24, 0.55)',
  review: CATEGORY.review.accent,
  logic: CATEGORY.logic.accent,
  initiator: CATEGORY.initiator.accent,
  secondaryBtn: '#2a1d21',
};

let themeRegistered = false;

/**
 * Register the Apex OS Monaco theme once per page load.
 * @param {import('monaco-editor')} monaco
 */
export function defineApexMonacoTheme(monaco) {
  if (themeRegistered || !monaco?.editor?.defineTheme) return;
  themeRegistered = true;

  monaco.editor.defineTheme(APEX_MONACO_THEME, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6b6b6b', fontStyle: 'italic' },
      { token: 'string', foreground: 'e27588' },
      { token: 'string.escape', foreground: 'd93854' },
      { token: 'string.regexp', foreground: 'e27588' },
      { token: 'keyword', foreground: 'b47aff' },
      { token: 'keyword.control', foreground: '8216c5' },
      { token: 'number', foreground: 'e6b34c' },
      { token: 'number.hex', foreground: 'e6b34c' },
      { token: 'type', foreground: '166ac5' },
      { token: 'type.identifier', foreground: '166ac5' },
      { token: 'class', foreground: '166ac5' },
      { token: 'function', foreground: 'dadada' },
      { token: 'function.declaration', foreground: '16c559' },
      { token: 'variable', foreground: 'dadada' },
      { token: 'variable.parameter', foreground: 'b5b5b5' },
      { token: 'variable.predefined', foreground: '8216c5' },
      { token: 'operator', foreground: 'd93854' },
      { token: 'delimiter', foreground: 'b5b5b5' },
      { token: 'delimiter.bracket', foreground: 'b5b5b5' },
      { token: 'tag', foreground: '8216c5' },
      { token: 'metatag', foreground: '8216c5' },
      { token: 'attribute.name', foreground: 'e27588' },
      { token: 'attribute.value', foreground: 'e6b34c' },
    ],
    colors: {
      'editor.background': CODE_EDITOR_CHROME.bg,
      'editor.foreground': CODE_EDITOR_CHROME.text,
      'editor.lineHighlightBackground': CODE_EDITOR_CHROME.panel,
      'editor.selectionBackground': '#8216c545',
      'editor.inactiveSelectionBackground': '#46464666',
      'editor.selectionHighlightBackground': '#8216c528',
      'editor.wordHighlightBackground': '#8216c522',
      'editor.wordHighlightStrongBackground': '#d9385433',
      'editorCursor.foreground': CODE_EDITOR_CHROME.cta,
      'editorLineNumber.foreground': COLOR.dark,
      'editorLineNumber.activeForeground': CODE_EDITOR_CHROME.muted,
      'editorIndentGuide.background': '#46464644',
      'editorIndentGuide.activeBackground': COLOR.dark,
      'editorGutter.background': CODE_EDITOR_CHROME.bg,
      'editorWidget.background': CODE_EDITOR_CHROME.panel,
      'editorWidget.border': CODE_EDITOR_CHROME.border,
      'editorSuggestWidget.background': CODE_EDITOR_CHROME.panel,
      'editorSuggestWidget.border': CODE_EDITOR_CHROME.border,
      'editorSuggestWidget.selectedBackground': CODE_EDITOR_CHROME.accentSoft,
      'editorHoverWidget.background': CODE_EDITOR_CHROME.panel,
      'editorHoverWidget.border': CODE_EDITOR_CHROME.border,
      'minimap.background': CODE_EDITOR_CHROME.bg,
      'scrollbarSlider.background': '#46464666',
      'scrollbarSlider.hoverBackground': '#6b6b6b88',
      'scrollbarSlider.activeBackground': '#6b6b6baa',
      'editorBracketMatch.background': '#8216c533',
      'editorBracketMatch.border': CODE_EDITOR_CHROME.accent,
      'editor.findMatchBackground': '#d9385444',
      'editor.findMatchHighlightBackground': '#d9385428',
    },
  });
}

export function applyApexMonacoTheme(monaco) {
  defineApexMonacoTheme(monaco);
  monaco?.editor?.setTheme(APEX_MONACO_THEME);
}
