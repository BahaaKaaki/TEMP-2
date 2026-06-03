import { useEffect, useState } from 'react';

/**
 * The Figma "Apex OS - Copy" workflow-builder canvas is designed at
 * 1920×1080.  Every dimension in `figmaSpec.js` (widths, paddings, font
 * sizes, gaps, …) is the literal Figma value at that reference width.
 *
 * On smaller monitors (e.g. a 14" MacBook ≈ 1440 logical px) those raw
 * numbers look proportionally HUGE — a 226px palette eats 16% of the
 * screen instead of the ~12% Figma intends, a 515px config panel eats
 * 36% instead of ~27%, and so on.
 *
 * This hook returns a single scale factor in (0.55, 1] that every
 * builder component multiplies its Figma dimensions by, so the
 * proportions match Figma at any viewport while the chrome stays
 * usable on small laptops.
 *
 *   const scale = useFigmaScale();
 *   const px = (v) => v * scale;          // helper
 *   <div style={{ width: px(226), padding: px(16), gap: px(20) }} />
 *
 * On 1920+ wide viewports the scale is exactly 1.0 (Figma-perfect).
 */

const FIGMA_DESIGN_WIDTH = 1920;
const MIN_SCALE = 0.55; // ~1056 logical px viewport

function calc() {
  if (typeof window === 'undefined') return 1;
  return Math.min(1, Math.max(MIN_SCALE, window.innerWidth / FIGMA_DESIGN_WIDTH));
}

export function useFigmaScale() {
  const [scale, setScale] = useState(calc);

  useEffect(() => {
    const handler = () => setScale(calc());
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return scale;
}

/**
 * Convenience wrapper that returns both the scale factor and a `px`
 * helper so consumer components only have to destructure once.
 *
 *   const { scale, px } = useFigmaPx();
 *   <div style={{ width: px(226) }} />
 */
export function useFigmaPx() {
  const scale = useFigmaScale();
  const px = (v) => v * scale;
  return { scale, px };
}
