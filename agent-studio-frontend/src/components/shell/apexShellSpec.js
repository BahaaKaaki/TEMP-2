/**
 * Apex OS shell — single source of truth for the new top-level pages
 * (Storefront, My Sessions, My Tools).
 *
 * All values are taken directly from the Figma file
 * "Apex OS (Copy)" — frames 157:2475 (Storefront), 142:1364 (Sessions),
 * 157:3499 (My Tools). Dimensions are in the original 1920×1080 design
 * space; downstream components scale them with the same `useFigmaScale`
 * hook used by the workflow builder so that everything shrinks
 * proportionally on smaller screens.
 *
 * Design tokens (from Figma `get_variable_defs`):
 *   - Neutral / Black     → #141414   page bg + tab bar bg (soft canvas)
 *   - Neutral / Darkest   → #1a1a1a   card / tile bg
 *   - Neutral / Darker    → #464646   borders + inactive badge bg
 *   - Neutral / Dark      → #6b6b6b   subtle borders + caption text
 *   - Neutral / Medium    → #b5b5b5   secondary text + inactive tab text
 *   - Neutral / Light     → #dadada   tertiary text + count text
 *   - Neutral / White     → #ffffff   primary text + active tab text
 *   - Rose   / Darkest    → #d93854   primary CTA + active tab border
 *   - Rose   / Dark       → #e27588   hover state for rose
 *
 * Typography (Helvetica Neue):
 *   - Subheading 1 (Bold)  32 / 40   page titles ("My Tools", etc.)
 *   - Subheading 2 (Bold)  24 / 32   section titles ("Apex OS Tools")
 *   - Body 1 (Bold)        20 / 28   card titles
 *   - Body 1               20 / 28   description body
 *   - Body 2 (Bold)        16 / 24   chat-item title ("Slide creation…")
 *   - Body 2               16 / 24   default body / pill text / search input
 *   - Body 3               14 / 20   captions ("Shared with 2 people"), date,
 *                                    badge text, sidebar nav text
 *
 *   The tab labels in Figma use SF Pro 14/16 Semibold; we keep
 *   Helvetica Neue everywhere so the shell stays consistent with the
 *   workflow builder shell — visually they're indistinguishable at
 *   navbar size.
 */

import { APP_FONT_SANS } from '../../theme/typography.js';

export const COLOR = {
  black: '#141414',
  darkest: '#1a1a1a',
  darker: '#464646',
  dark: '#6b6b6b',
  medium: '#b5b5b5',
  light: '#dadada',
  white: '#ffffff',
  rose: '#d93854',
  roseHover: '#c52a45',
  roseSoft: '#3b1c21',
  // Status pill colours from Figma (frame 142:1951 etc.)
  successBg: '#18231d',
  successFg: '#20f778',
  warningBg: '#2b2415',
  warningFg: '#e6b34c',
  errorBg: '#2a1418',
  errorFg: '#ff4d6e',
};

/** Matches builder NAVBAR.secondaryButton (Guide / Test / Save pills). */
export const SHELL_SECONDARY_BUTTON = {
  height: 48,
  paddingLeft: 12,
  paddingRight: 16,
  gap: 8,
  radius: 10,
  bg: '#2a1d21',
  bgHover: '#3b1c21',
  border: 'rgba(217, 56, 84, 0.42)',
  borderHover: 'rgba(217, 56, 84, 0.72)',
  text: '#ffffff',
  icon: '#d93854',
  shadow: 'inset 0 1px 0 rgba(217, 56, 84, 0.18)',
  shadowHover: 'inset 0 1px 0 rgba(217, 56, 84, 0.28), 0 0 12px rgba(217, 56, 84, 0.12)',
};

export function applyShellSecondaryButtonHover(el, hovered) {
  const s = SHELL_SECONDARY_BUTTON;
  el.style.backgroundColor = hovered ? s.bgHover : s.bg;
  el.style.borderColor = hovered ? s.borderHover : s.border;
  el.style.boxShadow = hovered ? s.shadowHover : s.shadow;
}

/** Inline styles for shell secondary CTAs (pass scaled `px` from useFigmaPx). */
export function shellSecondaryButtonStyle(px, overrides = {}) {
  const s = SHELL_SECONDARY_BUTTON;
  return {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxSizing: 'border-box',
    height: px(s.height),
    paddingLeft: px(s.paddingLeft),
    paddingRight: px(s.paddingRight),
    borderRadius: px(s.radius),
    backgroundColor: s.bg,
    color: s.text,
    border: `1px solid ${s.border}`,
    boxShadow: s.shadow,
    fontFamily: APP_FONT_SANS,
    fontSize: px(16),
    lineHeight: `${px(24)}px`,
    fontWeight: 700,
    cursor: 'pointer',
    gap: px(s.gap),
    transition: 'background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease',
    ...overrides,
  };
}

/** Generated icon tiles — rose-aligned accents only (no builder purple). */
export const ICON_PALETTE = [
  '#d93854',
  '#c52a45',
  '#166ac5',
  '#16a085',
  '#e67e22',
  '#16c559',
  '#c2185b',
  '#8b7355',
];

export function colorForName(name) {
  if (!name) return ICON_PALETTE[0];
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return ICON_PALETTE[Math.abs(h) % ICON_PALETTE.length];
}

export function initialsForName(name) {
  if (!name) return 'A';
  const parts = name.replace(/[^a-zA-Z0-9 ]/g, ' ').split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return parts[0].slice(0, 2).toUpperCase();
}

export const FONT = {
  family: APP_FONT_SANS,
  sub1Bold: { size: 32, height: 40, weight: 700 },
  sub2Bold: { size: 24, height: 32, weight: 700 },
  body1Bold: { size: 20, height: 28, weight: 700 },
  body1: { size: 20, height: 28, weight: 400 },
  body2Bold: { size: 16, height: 24, weight: 700 },
  body2: { size: 16, height: 24, weight: 400 },
  body3: { size: 14, height: 20, weight: 400 },
  caption: { size: 12, height: 14, weight: 600 },
  pillButton: { size: 16, height: 20, weight: 700 }, // CTA pill
};

// ─── Top navigation bar (Figma 157:2476 / 142:1365 / 157:3500) ────────────
// The bar is a self-contained "card":
//   - sits inside the 1920px page with a 24px margin on all sides
//   - has its own #1a1a1a (Neutral/Darkest) fill + 16px rounded corners
//   - 24px internal padding, contents are 48px tall
export const NAV = {
  outerHeight: 96,        // total card height (24 padding + 48 content + 24 padding)
  outerMargin: 24,        // gap between card and viewport edge
  innerHeight: 48,        // content row height inside the card
  padding: 24,            // internal padding (top/right/bottom/left)
  radius: 16,             // card corner radius
  bg: COLOR.darkest,      // #1a1a1a — the grey container the user pointed to
  innerWidth: 1872,
  logoWidth: 200,
  logoHeight: 45.7,
  avatar: {
    size: 48,
    bg: COLOR.rose,
    border: COLOR.roseHover, // Figma uses rose/dark (#e27588) — close enough; we
    borderStyle: '#e27588',  // keep the exact Figma value here for reference.
    borderWidth: 2,
    text: COLOR.white,
    fontSize: 16,
    fontWeight: 700,
  },
  tabs: {
    width: 684,
    height: 48,
    padding: 4,
    gap: 2,
    radius: 16,
    bg: COLOR.black,
    item: {
      height: 40,
      radius: 12,
      paddingX: 16,
      paddingY: 8,
      gap: 8,
      iconSize: 24,
      activeBg: COLOR.black,
      activeBorder: COLOR.rose,
      activeShadow: 'inset 0 0 12px 0 #ff0631',
      activeText: COLOR.white,
      inactiveText: COLOR.medium,
    },
    badge: {
      bg: COLOR.darker,
      text: COLOR.light,
      activeBg: COLOR.rose,
      activeText: COLOR.white,
      paddingX: 6,
      paddingY: 3,
      radius: 100,
      minWidth: 20,
    },
  },
};

// ─── Search bar (Figma 157:2487 / 142:1376 / 157:3744) ────────────────────
export const SEARCH = {
  height: 48,
  radius: 16,
  paddingX: 20,
  gap: 12,
  iconSize: 20,
  bg: COLOR.darkest,
  border: COLOR.darker,
  borderWidth: 1,
  text: COLOR.white,
  placeholder: COLOR.medium,
  iconColor: COLOR.medium,
};

// ─── Storefront app card (Figma 157:2492) ─────────────────────────────────
export const APP_CARD = {
  height: 112,
  width: 464,
  radius: 12,
  padding: 16,
  gap: 16,
  bg: COLOR.darkest,
  iconSize: 80,
  iconRadius: 10,
  pill: {
    height: 32,
    radius: 8,
    paddingX: 16,
    paddingY: 12,
    bg: COLOR.rose,
    bgHover: COLOR.roseHover,
    text: COLOR.white,
  },
};

/** Storefront featured spotlight row — larger cards above the catalog grid. */
export const SPOTLIGHT = {
  height: 140,
  radius: 12,
  padding: 20,
  gap: 20,
  iconSize: 72,
  iconRadius: 10,
  iconInitialsSize: 32,
  pill: APP_CARD.pill,
};

// ─── My Tools card (Figma 157:3745) ───────────────────────────────────────
export const TOOL_CARD = {
  width: 336,
  height: 244,
  radius: 16,
  padding: 16,
  gap: 12,
  bg: COLOR.darkest,
  border: 'transparent', // Figma uses no border, pure dark surface
  thumbnail: {
    height: 40,
    radius: 100,
    border: COLOR.dark,
    paddingX: 8,
    paddingY: 8,
    gap: 8,
  },
  buttons: {
    height: 32,
    radius: 10,
    gap: 16,
    paddingLeft: 12,
    paddingRight: 16,
    paddingY: 12,
    iconSize: 20,
    primary: { bg: COLOR.rose, bgHover: COLOR.roseHover, text: COLOR.white },
    secondary: { bg: COLOR.roseSoft, bgHover: '#4a232a', text: COLOR.rose },
  },
};

// ─── Sessions left panel (Figma 209:6563) ─────────────────────────────────
export const SESSIONS_PANEL = {
  width: 281,
  paddingX: 16,
  paddingY: 24,
  radius: 16,
  bg: COLOR.darkest,
  itemHeight: 40,
  itemGap: 8,
  itemPaddingX: 12,
  itemPaddingY: 8,
  itemRadius: 8,
  itemActiveBg: 'rgba(217, 56, 84, 0.08)',
  itemActiveBorder: COLOR.rose,
  itemHoverBg: 'rgba(255, 255, 255, 0.04)',
  sectionGap: 16,
  /** @deprecated use SHELL_SECONDARY_BUTTON — kept for reference */
  newProjectButton: SHELL_SECONDARY_BUTTON,
};

// ─── Sessions chat item (Figma 157:3278) ──────────────────────────────────
export const CHAT_ITEM = {
  height: 144,
  paddingX: 16,
  paddingY: 32,
  gap: 16,
  borderColor: COLOR.dark,
  iconSize: 80,
  iconWidth: 82,
  iconRadius: 16,
};

// ─── Status pill ──────────────────────────────────────────────────────────
export const STATUS_PILL = {
  height: 36,
  paddingX: 12,
  paddingY: 8,
  radius: 100,
  gap: 4,
  iconSize: 20,
  variants: {
    success: { bg: COLOR.successBg, fg: COLOR.successFg },
    inProgress: { bg: COLOR.warningBg, fg: COLOR.warningFg },
    cancelled: { bg: COLOR.errorBg, fg: COLOR.errorFg },
  },
};

// ─── Layout (page-level paddings — Figma frames) ──────────────────────────
export const LAYOUT = {
  pageBg: COLOR.black,
  storefront: {
    leftPaddingX: 48,
    contentTop: 154, // search bar y
    leftWidth: 946, // My Tools / Sessions search cap
    mainMaxWidth: 1200,
  },
  sessions: {
    panelLeft: 24,
    panelTop: 144,
    contentLeft: 329,
    contentTop: 144,
  },
  mytools: {
    paddingX: 48,
    paddingTop: 144,
    cardGap: 40,
    rowGap: 56,
  },
};

// ─── Knowledge base detail page ───────────────────────────────────────────
export const KB_DETAIL = {
  buttonRadius: 10,
  cardRadius: 16,
  chunkRowRadius: 10,
  chunkPageSize: 15,
  chunkPreviewChars: 140,
  splitDefault: 38,
  statRadius: 16,
};
