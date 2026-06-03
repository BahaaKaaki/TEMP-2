import { useMemo } from 'react';
import { getNodeStyle } from './nodeCategoryStyles';

function hexToRgb(hex) {
  const normalized = hex.replace('#', '');
  if (normalized.length !== 6) return { r: 130, g: 22, b: 197 };
  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  };
}

/**
 * Range input with a track gradient tinted to the selected node's category color.
 */
export default function CategoryRangeSlider({
  nodeType,
  min = 0,
  max = 100,
  step = 1,
  value,
  onChange,
  disabled = false,
  className = '',
}) {
  const numValue = value !== undefined && value !== null ? Number(value) : min;
  const { accent, glow } = getNodeStyle(nodeType || 'agent');

  const sliderStyle = useMemo(() => {
    const { r, g, b } = hexToRgb(accent);
    const span = max - min || 1;
    const pct = Math.min(100, Math.max(0, ((numValue - min) / span) * 100));
    const trackBg = `linear-gradient(to right, rgba(${r}, ${g}, ${b}, 0.22) 0%, rgba(${r}, ${g}, ${b}, 0.55) ${pct}%, #3a3a3a ${pct}%, #3a3a3a 100%)`;
    return {
      '--range-accent': accent,
      '--range-glow': glow,
      '--range-track-bg': trackBg,
      accentColor: accent,
    };
  }, [accent, glow, min, max, numValue]);

  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={numValue}
      onChange={onChange}
      disabled={disabled}
      className={`node-category-range w-full ${disabled ? 'opacity-50 cursor-not-allowed' : ''} ${className}`.trim()}
      style={sliderStyle}
    />
  );
}
