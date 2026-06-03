import { APP_FONT_SANS } from '../../theme/typography.js';

/* ============================================================================
 * Figma "Apex OS - Copy" / Workflow builder canvas (node 86:2447)
 * Single source of truth for every dimension, color, font, padding, and gap
 * extracted directly from the Figma design tokens (get_variable_defs) and
 * the Figma component tree (get_design_context).
 * Values here come VERBATIM from Figma. If the design changes, update here.
 * ===========================================================================*/

// ----- Color tokens -----------------------------------------------------------
export const COLOR = {
  black:        '#141414',  // Neutral/Black — app canvas (soft dark, not pure #000)
  darkest:      '#1a1a1a',  // Neutral/Darkest — panel backgrounds
  darker:       '#464646',  // Neutral/Darker — borders, toggle off, secondary chips
  dark:         '#6b6b6b',  // Neutral/Dark   — chevron-down icon
  medium:       '#b5b5b5',  // Neutral/Medium — secondary text, captions
  light:        '#dadada',  // Neutral/Light  — toggle caption text
  lightest:     '#f2f2f2',  // Neutral/Lightest
  white:        '#ffffff',  // Neutral/White
  rose:         '#d93854',  // Rose/Darkest — primary CTA, secondary-button text
  roseLight:    '#e27588',  // Rose/Dark — avatar border
  roseDarkBg:   '#3b1c21',  // (no token) — Feedback / Test / Save bg
  delete:       '#ff1212',  // Legacy destructive accent
  deleteSoft:     '#ff6b7a',  // Delete button label + icon
  deleteBg:       'rgba(255, 77, 110, 0.1)',
  deleteBgHover:  'rgba(255, 77, 110, 0.18)',
  deleteBorder:   'rgba(255, 77, 110, 0.42)',
  deleteBorderHover: 'rgba(255, 77, 110, 0.68)',
};

// ----- Category accent colors (per Figma node category) ----------------------
export const CATEGORY = {
  initiator: { accent: '#166ac5', from: '#082647', to: '#030f1c', solid: '#082647' },
  agent:     { accent: '#8216c5', from: '#1a0535', to: '#050111', solid: '#340750' },
  logic:     { accent: '#c56216', from: '#3d1d05', to: '#1a0c02', solid: '#3d1d05' },
  review:    { accent: '#16c559', from: '#0a4d24', to: '#05180c', solid: '#0a4d24' },
  note:      { accent: '#c5a216', from: '#3d3105', to: '#1a1402', solid: '#F4CACA' },
};

// ----- Typography (from get_variable_defs) -----------------------------------
// Family: Geist (see src/theme/typography.js + index.css).
export const FONT = {
  family: APP_FONT_SANS,
  // Label / caption pill on toggle (12/16 Regular)
  caption:        { size: 12, height: 16, weight: 400 },
  // Category labels, helper text, card subtitle (14/20 Regular)
  body3:          { size: 14, height: 20, weight: 400 },
  // Form labels, palette labels, input text (16/24 Regular)
  body2:          { size: 16, height: 24, weight: 400 },
  // Avatar text, top-bar buttons body? — 16/24 Bold
  body2Bold:      { size: 16, height: 24, weight: 700 },
  // Card title, zoom percentage (20/28 Regular & Bold)
  body1:          { size: 20, height: 28, weight: 400 },
  body1Bold:      { size: 20, height: 28, weight: 700 },
  // Section headings: "Nodes", "Workflow builder", "AI Agent" (24/32 Bold)
  subhead2Bold:   { size: 24, height: 32, weight: 700 },
  // Button label: 16/20 Bold (used by ALL the pill buttons in Figma)
  button:         { size: 16, height: 20, weight: 700 },
};

// ----- Frame -----------------------------------------------------------------
export const FRAME = { width: 1920, height: 1080, radius: 24 };

// ----- Top bar (ApexOS logo + Feedback + Avatar) -----------------------------
export const TOP_BAR = {
  logo:     { left: 30,   top: 28, width: 238.65, height: 54.535 },
  feedback: { left: 1701, top: 31, height: 48, gap: 4, paddingLeft: 12, paddingRight: 16, paddingY: 8, radius: 10 },
  avatar:   { left: 1848, top: 31, size: 48, padding: 4, radius: 100, borderWidth: 2 },
};

// ----- Workflow-builder navbar (back + title + Test/Save/launch) -------------
export const NAVBAR = {
  left: 24, top: 108, width: 1872,
  padding: 16, gap: 16, radius: 16,
  back:    { height: 48, padding: 12, radius: 10, iconSize: 24 },
  button:  { height: 48, paddingLeft: 12, paddingRight: 16, paddingY: 8, gap: 4, radius: 10, iconSize: 24 },
  /** Secondary toolbar pills — rose accent on dark base (not rose-on-rose text) */
  secondaryButton: {
    bg: '#2a1d21',
    bgHover: '#3b1c21',
    border: 'rgba(217, 56, 84, 0.42)',
    borderHover: 'rgba(217, 56, 84, 0.72)',
    text: '#ffffff',
    shadow: 'inset 0 1px 0 rgba(217, 56, 84, 0.18)',
    shadowHover: 'inset 0 1px 0 rgba(217, 56, 84, 0.28), 0 0 12px rgba(217, 56, 84, 0.12)',
  },
  primaryButton: {
    bg: '#d93854',
    bgHover: '#c52a45',
    text: '#ffffff',
  },
};

// ----- Zoom pill (bottom-centred control bar) --------------------------------
export const ZOOM = {
  bottom: 24, right: 563,
  padding: 16, gap: 24, radius: 16,
  iconSize: 32,
};

// ----- Left "Nodes" palette --------------------------------------------------
export const PALETTE = {
  left: 30, top: 212, width: 226,
  padding: 16, gap: 20, radius: 16,
  itemListGap: 8,
  item:        { gap: 12 },
  iconTile:    { size: 32, innerIcon: 24, padding: 4, radius: 8 },
  // Visual sub-icon insets (for masks). Each icon was hand-edited to use these
  // translates inside its 24x24 viewBox so they all sit pixel-perfect within
  // the 32x32 colored tile.
  insets: {
    'sticky-note':       { x: 3, y: 3 },
    chat:                { x: 2, y: 2 },
    agent:               { x: 3, y: 3 },
    'code-executor':     { x: 1, y: 3.7 },
    condition:           { x: 2, y: 3.96 },
    branches:            { x: 4, y: 4 },
    'human-in-the-loop': { x: 1, y: 4 },
  },
};

// ----- Canvas card (chat / agent / human review) -----------------------------
/** Chat / workflow entry node — circular on canvas (not CARD rectangle). */
export const START_NODE = {
  size: 92,
  padding: 12,
  gap: 6,
};

export const CARD = {
  width: 276,
  paddingTop: 12, paddingRight: 12, paddingBottom: 12, paddingLeft: 16,
  gap: 12, radius: 16, borderWidth: 2,
  iconTile: { size: 36, innerIcon: 24, padding: 6, radius: 8 },
  // Drop-shadow on selected card from Figma 86:2538
  glow: '0px 0px 10px',
  insetGlow: 'inset 0px 0px 10px rgba(255,255,255,0.05)',
  // Asymmetric gradient stops (Figma uses the same stops on every card)
  gradientStops: { from: 2.063, to: 60.962 },
};

// ----- Right config panel (83:1437) ------------------------------------------
export const PANEL = {
  left: 1381, top: 212, width: 515, height: 844,
  padding: 16, gap: 12, radius: 16, borderWidth: 1,
  // Background gradient (verbatim from Figma)
  gradient: 'linear-gradient(156.396deg, rgb(130,22,197) 3.938%, rgb(26,26,26) 16.628%)',

  header:        { gap: 12, iconSize: 36, iconInnerInset: 4.5 /* 12.5% of 36 */ },
  toggle: {
    border: 1, gap: 8, paddingLeft: 12, paddingRight: 16, paddingY: 12, radius: 16,
    track: { width: 48, padding: 2, radius: 50 },
    knob:  { width: 28, height: 20, radius: 80 },
  },
  divider:       { height: 1 },
  inputField:    { gap: 8 },
  input:         { gap: 8, minWidth: 240, paddingX: 16, paddingY: 12, radius: 16, borderWidth: 1, inputHeight: 24 },
  textareaInput: { height: 108 },

  delete: {
    bottom: 15, left: 15, width: 483, height: 48,
    borderWidth: 1, radius: 10, gap: 8,
    paddingLeft: 12, paddingRight: 16, paddingY: 8,
    iconSize: 20,
  },
};

// ----- Connection edges ------------------------------------------------------
export const EDGE = {
  strokeWidth: 3,
  startDotRadius: 4,
  startDotStrokeWidth: 1.5,
  arrowMarker: { width: 5, height: 5, refX: 8, refY: 5 },
};

// ----- Background dot grid (Figma render) ------------------------------------
// Matches Figma's editor canvas grid: a 16×16 tile with a tiny (~0.8px) white
// dot at low opacity so the grid is *barely* visible — like a faint starfield
// behind the nodes, not a strong texture.
export const BACKGROUND = {
  bg: COLOR.black,
  dotColor: 'rgba(255,255,255,0.18)',
  dotRadius: 0.8,
  tile: 16,
};
