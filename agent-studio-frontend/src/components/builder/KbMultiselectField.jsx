/**
 * Selectable knowledge-base cards for agent / code-runner node config.
 */

import { useEffect, useMemo, useState } from 'react';
import { listKnowledgeBasesForAttach } from '@/api/kb-client';
import AppIcon from '../ui/AppIcon';
import { COLOR, FONT } from './figmaSpec';
import { getAccentTheme } from './nodeCategoryStyles';

const CARD_RADIUS = 10;

function KbPickerSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="apex-skeleton"
          style={{
            height: 56,
            borderRadius: CARD_RADIUS,
            backgroundColor: COLOR.darkest,
          }}
        />
      ))}
    </div>
  );
}

function KbPickerCard({ kb, selected, disabled, onToggle, theme }) {
  const id = kb.kb_id || kb.id;
  const [hovered, setHovered] = useState(false);
  const canHover = !disabled && hovered && !selected;

  let borderColor = COLOR.darker;
  let borderLeftColor = COLOR.darker;
  let borderLeftWidth = 1;
  let backgroundColor = COLOR.darkest;
  let boxShadow = 'none';

  if (selected) {
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

  const iconColor = selected ? theme.accent : canHover ? theme.accent : COLOR.medium;
  const iconBg = selected
    ? theme.iconBgSelected
    : canHover
      ? theme.bgHover
      : 'rgba(255, 255, 255, 0.04)';

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onToggle(id)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="w-full text-left"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 13,
        padding: '11px 13px',
        borderRadius: CARD_RADIUS,
        border: `1px solid ${borderColor}`,
        borderLeftWidth,
        borderLeftColor,
        backgroundColor,
        boxShadow,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        transform: canHover ? 'translateY(-1px)' : 'none',
        transition: 'border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease, transform 120ms ease',
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
          name="kb"
          size={20}
          color={iconColor}
          weight={selected ? 'fill' : 'regular'}
        />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          className="truncate"
          style={{
            color: COLOR.white,
            fontSize: FONT.body2.size,
            fontWeight: FONT.body2Bold.weight,
            lineHeight: `${FONT.body2.height}px`,
          }}
          title={kb.name}
        >
          {kb.name}
        </div>
        <div
          className="flex items-center flex-wrap"
          style={{ gap: 6, marginTop: 4 }}
        >
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: 4,
              backgroundColor: 'rgba(255, 255, 255, 0.06)',
              color: COLOR.medium,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {kb.document_count ?? 0} docs
          </span>
          <span style={{ color: COLOR.dark, fontSize: 11 }}>·</span>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: 4,
              backgroundColor: 'rgba(255, 255, 255, 0.06)',
              color: COLOR.medium,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {kb.chunk_count ?? 0} chunks
          </span>
        </div>
      </div>

      <div
        aria-hidden="true"
        style={{
          width: 20,
          height: 20,
          borderRadius: 6,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: `2px solid ${selected ? theme.accent : COLOR.darker}`,
          backgroundColor: selected ? theme.accent : 'transparent',
          transition: 'border-color 180ms ease, background-color 180ms ease',
        }}
      >
        {selected && (
          <AppIcon name="check" size={12} color={COLOR.white} weight="bold" />
        )}
      </div>
    </button>
  );
}

export default function KbMultiselectField({
  value = [],
  onChange,
  disabled = false,
  label = 'Attached bases',
  helpText,
  nodeType,
}) {
  const theme = getAccentTheme(nodeType);
  const [kbs, setKbs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');

  const selectedIds = Array.isArray(value) ? value : [];

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await listKnowledgeBasesForAttach();
        if (cancelled) return;
        setKbs(data.knowledge_bases || []);
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load knowledge bases:', err);
          setKbs([]);
          setError(err.message || 'Failed to load knowledge bases');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return kbs;
    return kbs.filter((kb) => kb.name?.toLowerCase().includes(q));
  }, [kbs, search]);

  const handleToggle = (kbId) => {
    if (disabled) return;
    const next = [...selectedIds];
    const idx = next.indexOf(kbId);
    if (idx >= 0) {
      next.splice(idx, 1);
    } else {
      next.push(kbId);
    }
    onChange(next);
  };

  const panelBorder = theme.borderHover || COLOR.darker;

  return (
    <div style={{ marginBottom: 18 }}>
      <div
        style={{
          borderRadius: CARD_RADIUS,
          border: `1px solid ${panelBorder}`,
          backgroundColor: 'rgba(0, 0, 0, 0.35)',
          padding: '12px 14px',
        }}
      >
        <label
          className="block"
          style={{
            marginBottom: 10,
            fontSize: FONT.body2.size,
            lineHeight: `${FONT.body2.height}px`,
            fontWeight: 500,
            color: COLOR.medium,
          }}
        >
          {label}
          {selectedIds.length > 0 && (
            <span style={{ marginLeft: 8, fontSize: FONT.body3.size, color: COLOR.dark }}>
              ({selectedIds.length} selected)
            </span>
          )}
        </label>

        {loading ? (
          <KbPickerSkeleton />
        ) : error ? (
          <div
            style={{
              padding: 12,
              borderRadius: CARD_RADIUS,
              border: `1px solid ${COLOR.darker}`,
              color: COLOR.rose,
              fontSize: FONT.body3.size,
            }}
          >
            {error}
          </div>
        ) : kbs.length === 0 ? (
          <div
            style={{
              padding: 16,
              borderRadius: CARD_RADIUS,
              border: `1px dashed ${COLOR.darker}`,
              color: COLOR.medium,
              fontSize: FONT.body3.size,
              textAlign: 'center',
            }}
          >
            No knowledge bases yet. Create one in My tools, then return here to attach it.
          </div>
        ) : (
          <>
            {kbs.length > 3 && (
              <div
                className="kb-inline-search flex items-center"
                style={{
                  marginBottom: 10,
                  height: 36,
                  borderRadius: CARD_RADIUS,
                  paddingLeft: 12,
                  paddingRight: 12,
                  gap: 8,
                  backgroundColor: COLOR.black,
                  border: `1px solid ${COLOR.darker}`,
                }}
              >
                <AppIcon name="search" size={16} color={COLOR.medium} />
                <input
                  type="text"
                  className="force-white-text"
                  placeholder="Search knowledge bases"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  disabled={disabled}
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
            )}

            <div
              className="flex flex-col overflow-y-auto scrollbar-dark"
              style={{ gap: 10, maxHeight: 220 }}
            >
              {filtered.length === 0 ? (
                <p
                  style={{
                    margin: 0,
                    padding: 12,
                    textAlign: 'center',
                    color: COLOR.medium,
                    fontSize: FONT.body3.size,
                  }}
                >
                  No knowledge bases match your search.
                </p>
              ) : (
                filtered.map((kb) => {
                  const id = kb.kb_id || kb.id;
                  return (
                    <KbPickerCard
                      key={id}
                      kb={kb}
                      selected={selectedIds.includes(id)}
                      disabled={disabled}
                      onToggle={handleToggle}
                      theme={theme}
                    />
                  );
                })
              )}
            </div>
          </>
        )}

        {helpText && (
          <p
            style={{
              marginTop: 10,
              marginBottom: 0,
              fontSize: FONT.body3.size,
              lineHeight: `${FONT.body3.height}px`,
              color: COLOR.dark,
            }}
          >
            {helpText}
          </p>
        )}
      </div>
    </div>
  );
}
