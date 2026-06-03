/**
 * Figma-style source toggle row — accent follows the selected node's category.
 */

import { useState } from 'react';
import AppIcon from '../ui/AppIcon';
import { COLOR, FONT, PANEL } from './figmaSpec';
import { getAccentTheme } from './nodeCategoryStyles';

const ROW_RADIUS = 10;
const TRANSITION = 'border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease, transform 120ms ease';

function FigmaSwitch({ checked, disabled, accent, onToggle, ariaLabel }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onToggle(!checked);
      }}
      className="flex-shrink-0"
      style={{
        opacity: disabled ? 0.45 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'opacity 150ms ease',
      }}
      onMouseDown={(e) => e.preventDefault()}
    >
      <span
        className="flex items-center"
        style={{
          width: PANEL.toggle.track.width,
          padding: PANEL.toggle.track.padding,
          borderRadius: PANEL.toggle.track.radius,
          backgroundColor: checked && !disabled ? accent : COLOR.darker,
          justifyContent: checked ? 'flex-end' : 'flex-start',
          transition: 'background-color 180ms ease',
        }}
      >
        <span
          className="block bg-white shadow-sm"
          style={{
            width: PANEL.toggle.knob.width,
            height: PANEL.toggle.knob.height,
            borderRadius: PANEL.toggle.knob.radius,
            transition: 'transform 180ms ease',
          }}
        />
      </span>
    </button>
  );
}

export default function ConfigToggleRow({
  label,
  helpText,
  icon = 'settings',
  badge,
  checked,
  disabled = false,
  requiresHint,
  onChange,
  nodeType,
}) {
  const theme = getAccentTheme(nodeType);
  const [hovered, setHovered] = useState(false);
  const rowDisabled = disabled;
  const active = checked && !rowDisabled;
  const canHover = !rowDisabled && hovered;

  let borderColor = COLOR.darker;
  let borderLeftColor = COLOR.darker;
  let borderLeftWidth = 1;
  let backgroundColor = COLOR.darkest;
  let boxShadow = 'none';
  let transform = 'none';

  if (active) {
    borderColor = theme.borderSelected;
    borderLeftColor = theme.accent;
    borderLeftWidth = 3;
    backgroundColor = theme.bgSelected;
    boxShadow = theme.shadowSelected;
  } else if (canHover) {
    borderColor = theme.borderHover;
    borderLeftColor = theme.borderHover;
    borderLeftWidth = 2;
    backgroundColor = theme.bgHover;
  }

  const iconColor = active ? theme.accent : canHover ? theme.accent : COLOR.medium;
  const iconBg = active
    ? theme.iconBgSelected
    : canHover
      ? theme.bgHover
      : 'rgba(255, 255, 255, 0.04)';

  return (
    <div style={{ marginBottom: 10 }}>
      <div
        role="button"
        tabIndex={rowDisabled ? -1 : 0}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => {
          if (!rowDisabled) onChange(!checked);
        }}
        onKeyDown={(e) => {
          if (rowDisabled) return;
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onChange(!checked);
          }
        }}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 13,
          padding: '11px 13px',
          borderRadius: ROW_RADIUS,
          border: `1px solid ${borderColor}`,
          borderLeftWidth,
          borderLeftColor,
          backgroundColor,
          boxShadow,
          transform: canHover && !active ? 'translateY(-1px)' : transform,
          opacity: rowDisabled ? 0.55 : 1,
          cursor: rowDisabled ? 'not-allowed' : 'pointer',
          transition: TRANSITION,
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: iconBg,
            transition: 'background-color 180ms ease',
          }}
        >
          <AppIcon
            name={icon}
            size={18}
            style={{ color: iconColor, transition: 'color 180ms ease' }}
          />
        </div>

        <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span
              style={{
                color: active ? COLOR.white : COLOR.lightest,
                fontSize: FONT.body3.size,
                lineHeight: `${FONT.body3.height}px`,
                fontWeight: active ? 600 : 500,
                transition: 'color 180ms ease',
              }}
            >
              {label}
            </span>
            {badge && (
              <span
                style={{
                  fontSize: 11,
                  lineHeight: '14px',
                  padding: '2px 8px',
                  borderRadius: 20,
                  backgroundColor: active
                    ? 'rgba(197, 162, 22, 0.2)'
                    : 'rgba(197, 162, 22, 0.12)',
                  color: '#e8c547',
                  border: '1px solid rgba(197, 162, 22, 0.35)',
                  transition: 'background-color 180ms ease',
                }}
              >
                {badge}
              </span>
            )}
          </div>
          {helpText && (
            <p
              style={{
                margin: '4px 0 0',
                color: COLOR.medium,
                fontSize: 12,
                lineHeight: '16px',
              }}
            >
              {helpText}
            </p>
          )}
          {requiresHint && (
            <p
              style={{
                margin: '4px 0 0',
                color: COLOR.dark,
                fontSize: 11,
                lineHeight: '14px',
                fontStyle: 'italic',
              }}
            >
              {requiresHint}
            </p>
          )}
        </div>

        <FigmaSwitch
          checked={!!checked}
          disabled={rowDisabled}
          accent={theme.accent}
          onToggle={onChange}
          ariaLabel={label}
        />
      </div>
    </div>
  );
}
