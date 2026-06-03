/**
 * Shared UI primitives for the Knowledge Base detail page — aligned with Apex shell tokens.
 */

import AppIcon from '../ui/AppIcon';
import { ApexSkeleton } from '../shell/ApexShellStates';
import { APP_FONT_MONO } from '../../theme/typography.js';
import { COLOR, FONT, KB_DETAIL, SEARCH } from '../shell/apexShellSpec';

export { COLOR, FONT, KB_DETAIL, SEARCH };

export const KB_MONO = APP_FONT_MONO;

export const kbBtnGhost = {
  padding: '6px 14px',
  borderRadius: KB_DETAIL.buttonRadius,
  border: `1px solid ${COLOR.darker}`,
  backgroundColor: 'rgba(255,255,255,0.04)',
  color: COLOR.white,
  fontSize: 12,
  fontWeight: 600,
  fontFamily: FONT.family,
  cursor: 'pointer',
  transition: 'background-color 150ms, opacity 150ms',
};

export function KbRoseSpinner({ size = 32, style }) {
  return (
    <span
      className="inline-block rounded-full animate-spin"
      style={{
        width: size,
        height: size,
        border: `2px solid ${COLOR.darker}`,
        borderTopColor: COLOR.rose,
        flexShrink: 0,
        ...style,
      }}
      aria-hidden="true"
    />
  );
}

export function KbDataTypeBadge({ dataType }) {
  const type = dataType || 'text';
  const styles = {
    integer: { bg: 'rgba(22, 106, 197, 0.15)', fg: '#7eb8ff' },
    numeric: { bg: 'rgba(130, 20, 30, 0.2)', fg: '#e27588' },
    date: { bg: COLOR.successBg, fg: COLOR.successFg },
    datetime: { bg: COLOR.successBg, fg: COLOR.successFg },
    boolean: { bg: COLOR.warningBg, fg: COLOR.warningFg },
    text: { bg: 'rgba(255,255,255,0.06)', fg: COLOR.medium },
  };
  const s = styles[type] || styles.text;
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: '2px 6px',
        borderRadius: 4,
        backgroundColor: s.bg,
        color: s.fg,
        fontFamily: FONT.family,
      }}
    >
      {type}
    </span>
  );
}

export function KbTab({ active, onClick, children, count }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: '8px 14px',
        fontSize: 12,
        fontWeight: 600,
        fontFamily: FONT.family,
        borderRadius: `${KB_DETAIL.buttonRadius}px ${KB_DETAIL.buttonRadius}px 0 0`,
        border: `1px solid ${active ? COLOR.darker : 'transparent'}`,
        borderBottom: active ? `1px solid ${COLOR.darkest}` : '1px solid transparent',
        marginBottom: active ? -1 : 0,
        position: 'relative',
        zIndex: active ? 10 : 0,
        backgroundColor: active ? COLOR.darkest : 'transparent',
        color: active ? COLOR.white : COLOR.dark,
        cursor: 'pointer',
        transition: 'color 150ms, background-color 150ms',
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.color = COLOR.light;
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.color = COLOR.dark;
      }}
    >
      {children}
      {count != null && (
        <span style={{ marginLeft: 6, fontSize: 10, color: COLOR.dark, fontWeight: 500 }}>
          ({count})
        </span>
      )}
    </button>
  );
}

export function KbPaginationFooter({
  label,
  page,
  totalPages,
  onPrev,
  onNext,
  disabled,
}) {
  if (totalPages <= 1) return null;
  return (
    <div
      className="flex items-center justify-between flex-shrink-0"
      style={{
        padding: '12px 24px',
        borderTop: `1px solid ${COLOR.darker}`,
        fontSize: FONT.body3.size,
        color: COLOR.medium,
        fontFamily: FONT.family,
      }}
    >
      <span>{label}</span>
      <div className="flex" style={{ gap: 8 }}>
        <button
          type="button"
          disabled={disabled || page <= 1}
          onClick={onPrev}
          style={{
            ...kbBtnGhost,
            opacity: disabled || page <= 1 ? 0.4 : 1,
            cursor: disabled || page <= 1 ? 'not-allowed' : 'pointer',
          }}
        >
          Prev
        </button>
        <button
          type="button"
          disabled={disabled || page >= totalPages}
          onClick={onNext}
          style={{
            ...kbBtnGhost,
            opacity: disabled || page >= totalPages ? 0.4 : 1,
            cursor: disabled || page >= totalPages ? 'not-allowed' : 'pointer',
          }}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function KbDocSearchBar({ value, onChange, placeholder = 'Search documents' }) {
  return (
    <div
      className="kb-inline-search flex items-center flex-shrink-0"
      style={{
        height: 40,
        marginBottom: 12,
        borderRadius: SEARCH.radius,
        paddingLeft: 14,
        paddingRight: 14,
        gap: 10,
        backgroundColor: COLOR.black,
        border: `1px solid ${COLOR.darker}`,
      }}
    >
      <AppIcon name="search" size={18} color={SEARCH.iconColor} />
      <input
        type="text"
        className="force-white-text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          flex: 1,
          minWidth: 0,
          border: 'none',
          outline: 'none',
          backgroundColor: 'transparent',
          color: COLOR.white,
          fontFamily: FONT.family,
          fontSize: FONT.body3.size,
        }}
      />
    </div>
  );
}

export function KbSplitSeparator({ isDragging, onMouseDown, onDoubleClick }) {
  return (
    <div
      onMouseDown={onMouseDown}
      onDoubleClick={onDoubleClick}
      className="relative flex-shrink-0 flex items-center justify-center cursor-col-resize group select-none"
      style={{ width: 12, marginLeft: 4, marginRight: 4 }}
      title="Drag to resize panels. Double-click to reset."
    >
      <div
        className="absolute inset-y-0 left-1/2 -translate-x-1/2 transition-colors duration-150"
        style={{
          width: 1,
          backgroundColor: isDragging ? COLOR.rose : COLOR.darker,
          opacity: isDragging ? 0.8 : 1,
        }}
      />
      <div
        className="relative z-10 flex items-center justify-center transition-all duration-150"
        style={{
          width: 16,
          height: 28,
          borderRadius: 100,
          border: `1px solid ${isDragging ? COLOR.rose : COLOR.darker}`,
          backgroundColor: isDragging ? 'rgba(217, 56, 84, 0.12)' : COLOR.darkest,
          boxShadow: isDragging ? `0 0 12px rgba(217, 56, 84, 0.25)` : 'none',
        }}
      >
        <AppIcon
          name="moreVertical"
          size={14}
          color={isDragging ? COLOR.rose : COLOR.dark}
          weight="bold"
          style={{ transform: 'rotate(90deg)' }}
        />
      </div>
    </div>
  );
}

export function KbModalBackdrop({ children, onClose, maxWidth = 520 }) {
  return (
    <div
      className="fixed inset-0 flex items-center justify-center"
      style={{ zIndex: 50, backgroundColor: 'rgba(0,0,0,0.65)' }}
      onClick={onClose}
    >
      <div
        data-theme="apex-dark"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: `linear-gradient(135deg, ${COLOR.darkest} 0%, ${COLOR.black} 100%)`,
          border: `1px solid ${COLOR.darker}`,
          borderRadius: KB_DETAIL.cardRadius,
          maxWidth,
          width: '92%',
          boxShadow: '0 12px 40px rgba(0,0,0,0.55)',
          fontFamily: FONT.family,
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function KbCloseButton({ onClick, title = 'Close', size = 20 }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      style={{
        padding: 8,
        border: 'none',
        borderRadius: KB_DETAIL.buttonRadius,
        backgroundColor: 'transparent',
        color: COLOR.medium,
        cursor: 'pointer',
        transition: 'background-color 150ms, color 150ms',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.06)';
        e.currentTarget.style.color = COLOR.white;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent';
        e.currentTarget.style.color = COLOR.medium;
      }}
    >
      <AppIcon name="close" size={size} color="currentColor" weight="bold" />
    </button>
  );
}

export function KbTableSkeleton({ rows = 6 }) {
  return (
    <div style={{ padding: 16 }}>
      {Array.from({ length: rows }, (_, i) => (
        <ApexSkeleton
          key={i}
          width="100%"
          height={28}
          radius={6}
          style={{ marginBottom: 8 }}
        />
      ))}
    </div>
  );
}

export function KbPanelHeader({ title, subtitle, action }) {
  return (
    <div
      className="flex items-start justify-between gap-4 flex-shrink-0"
      style={{
        padding: '16px 24px',
        borderBottom: `1px solid ${COLOR.darker}`,
        backgroundColor: COLOR.darkest,
      }}
    >
      <div className="min-w-0 flex-1">
        <h3
          style={{
            margin: 0,
            color: COLOR.white,
            fontSize: FONT.body1Bold.size,
            fontWeight: FONT.body1Bold.weight,
          }}
        >
          {title}
        </h3>
        {subtitle && (
          <p
            className="truncate"
            style={{ margin: '4px 0 0', color: COLOR.medium, fontSize: FONT.body3.size }}
          >
            {subtitle}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}
