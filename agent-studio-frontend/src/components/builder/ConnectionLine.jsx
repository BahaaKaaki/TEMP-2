import React from 'react';

export default function ConnectionLine({ from, to, isTemporary = false }) {
  if (!from || !to) return null;

  // Calculate the path for a smooth bezier curve
  const dx = to.x - from.x;
  const dy = to.y - from.y;

  // Control points for bezier curve
  const cx1 = from.x + dx * 0.5;
  const cy1 = from.y;
  const cx2 = to.x - dx * 0.5;
  const cy2 = to.y;

  const path = `M ${from.x} ${from.y} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${to.x} ${to.y}`;

  return (
    <svg
      className="absolute inset-0 pointer-events-none"
      style={{ zIndex: isTemporary ? 1000 : 1 }}
    >
      <path
        d={path}
        fill="none"
        stroke="#D1D5DB"
        strokeWidth="2.4"
        strokeDasharray={isTemporary ? "5,5" : "none"}
        opacity="0.8"
      />
    </svg>
  );
}