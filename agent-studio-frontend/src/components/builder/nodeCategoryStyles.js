// Single source of truth for per-category styling in the workflow builder,
// transcribed from the Figma "Apex OS - Copy" frame (node 86:2447).
//
// Figma uses an asymmetric horizontal gradient on each card:
//   linear-gradient(to right, <bright> 2.063%, <dark> 60.962%)
// the bright colour is essentially flat for the first ~2% of the width,
// then transitions to the dark colour over the next ~59%, and is solid
// dark for the rest. We reproduce that here so the cards look identical.
//
// Each entry maps a workflow node `type` (the id used in nodePaletteConfig.json)
// to the visual treatment used on:
//   - the left palette item (small icon + label)
//   - the canvas card (gradient background, border, glow when selected)
//   - the connection line color (matched to the source node category)
//
// Keep this file in sync with `nodePaletteConfig.json` if categories or
// node types are added.

const G = (bright, dark) =>
  `linear-gradient(to right, ${bright} 2.063%, ${dark} 60.962%)`;

export const NODE_CATEGORIES = {
  initiator: {
    accent: '#166ac5',
    iconBg: '#166ac5',
    cardGradient: G('#082647', '#030f1c'),
    cardSolid: '#082647',
    border: '#166ac5',
    glow: 'rgba(22, 106, 197, 0.55)',
  },
  agent: {
    accent: '#8216c5',
    iconBg: '#8216c5',
    cardGradient: G('#1a0535', '#050111'),
    cardSolid: '#340750',
    border: '#8216c5',
    glow: 'rgba(130, 22, 197, 0.6)',
  },
  logic: {
    accent: '#c56216',
    iconBg: '#c56216',
    cardGradient: G('#3d1d05', '#1a0c02'),
    cardSolid: '#3d1d05',
    border: '#c56216',
    glow: 'rgba(197, 98, 22, 0.55)',
  },
  review: {
    accent: '#16c559',
    iconBg: '#16c559',
    cardGradient: G('#0a4d24', '#05180c'),
    cardSolid: '#0a4d24',
    border: '#16c559',
    glow: 'rgba(22, 197, 89, 0.55)',
  },
  note: {
    accent: '#c5a216',
    iconBg: '#c5a216',
    cardGradient: G('#3d3105', '#1a1402'),
    cardSolid: '#F4CACA',
    border: '#c5a216',
    glow: 'rgba(197, 162, 22, 0.55)',
  },
};

// Maps every workflow node `type` from nodePaletteConfig.json to a category.
// Add new types here when the palette grows.
const TYPE_TO_CATEGORY = {
  // Initiators
  chat: 'initiator',
  'scheduled-start': 'initiator',
  webhook: 'initiator',
  start: 'initiator',
  'manual-input': 'initiator',

  // Agents (any AI/processor node)
  agent: 'agent',
  researcher: 'agent',
  'business-analyst': 'agent',
  'opportunity-classifier': 'agent',
  'data-classifier': 'agent',
  'financial-modeler': 'agent',
  'code-executor': 'agent',
  'ai-judge': 'agent',
  action: 'agent',

  // Logic / branching
  condition: 'logic',
  branches: 'logic',

  // Human-in-the-loop (Control Flow palette)
  hitl: 'logic',
  'human-in-the-loop': 'logic',

  // Output generators reuse the review (green) palette to match Figma's
  // "completion" feel — adjust if a dedicated category is added later.
  output: 'review',
  end: 'review',
  'powerpoint-generator': 'agent',
  'pdf-generator': 'review',
  'excel-generator': 'review',

  // Sticky note
  'sticky-note': 'note',
};

export function getCategoryForType(type) {
  return TYPE_TO_CATEGORY[type] || 'agent';
}

export function getNodeStyle(type) {
  return NODE_CATEGORIES[getCategoryForType(type)];
}

function hexToRgb(hex) {
  const normalized = hex.replace('#', '');
  if (normalized.length !== 6) return { r: 26, g: 26, b: 26 };
  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  };
}

/** Softer wash than the sharp Figma card gradient — used on the config panel. */
export function getPanelGradient(type) {
  const { accent } = getNodeStyle(type);
  const { r, g, b } = hexToRgb(accent);
  return `linear-gradient(165deg, rgba(${r}, ${g}, ${b}, 0.4) 0%, rgba(${r}, ${g}, ${b}, 0.07) 24%, #1a1a1a 52%, #141414 100%)`;
}

/**
 * Chat bubbles are wide and short — use the same horizontal wash as canvas
 * node cards (not the tall-panel 165deg gradient, which reads as a corner spotlight).
 */
export function getMessageBubbleGradient(type) {
  return getNodeStyle(type || 'agent').cardGradient;
}

/** User messages — horizontal rose wash (matches pill / CTA palette). */
export function getUserMessageBubbleGradient() {
  return G('#4a1724', '#631f2a');
}

/** System / workflow notices in chat. */
export function getSystemMessageBubbleGradient() {
  return G('#2a2a2a', '#1a1a1a');
}

/** Agent label chip — solid category tint (avoids double-gradient with the bubble). */
export function getMessageBadgeBackground(type) {
  const { cardSolid, accent } = getNodeStyle(type || 'agent');
  if (cardSolid) return cardSolid;
  const { r, g, b } = hexToRgb(accent);
  return `rgba(${r}, ${g}, ${b}, 0.55)`;
}

/** Accent tokens for config-panel toggles / pickers (matches canvas node category). */
export function getAccentTheme(type) {
  const { accent, glow } = getNodeStyle(type);
  const { r, g, b } = hexToRgb(accent);
  return {
    accent,
    glow,
    bgSelected: `rgba(${r}, ${g}, ${b}, 0.14)`,
    bgHover: `rgba(${r}, ${g}, ${b}, 0.09)`,
    iconBgSelected: `rgba(${r}, ${g}, ${b}, 0.24)`,
    borderHover: `rgba(${r}, ${g}, ${b}, 0.35)`,
    borderSelected: accent,
    shadowSelected: `0 0 0 1px rgba(${r}, ${g}, ${b}, 0.12), 0 1px 4px rgba(${r}, ${g}, ${b}, 0.08)`,
  };
}

// Helper used by the palette items: a small colored icon tile.
export function getPaletteIconBg(type) {
  return getNodeStyle(type).iconBg;
}
