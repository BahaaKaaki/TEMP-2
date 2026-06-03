/**
 * Shared loading skeletons and empty states for Apex OS shell views.
 */

import { useFigmaPx } from '../builder/useFigmaScale';
import { APP_CARD, COLOR, FONT } from './apexShellSpec';

export function ApexSkeleton({ width = '100%', height = 16, radius = 8, style }) {
  return (
    <div
      className="apex-skeleton"
      aria-hidden="true"
      style={{ width, height, borderRadius: radius, flexShrink: 0, ...style }}
    />
  );
}

export function ApexStorefrontLoading() {
  const { px } = useFigmaPx();
  return (
    <div
      role="status"
      aria-label="Loading tools"
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: px(12),
      }}
    >
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: px(APP_CARD.height),
            backgroundColor: APP_CARD.bg,
            borderRadius: px(APP_CARD.radius),
            padding: px(APP_CARD.padding),
            display: 'flex',
            gap: px(APP_CARD.gap),
            alignItems: 'center',
          }}
        >
          <ApexSkeleton width={px(APP_CARD.iconSize)} height={px(APP_CARD.iconSize)} radius={px(APP_CARD.iconRadius)} />
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: px(10) }}>
            <ApexSkeleton width="72%" height={px(18)} />
            <ApexSkeleton width="100%" height={px(14)} />
            <ApexSkeleton width="40%" height={px(32)} radius={px(100)} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ApexSessionListLoading({ rows = 5 }) {
  const { px } = useFigmaPx();
  return (
    <div role="status" aria-label="Loading sessions" style={{ padding: px(16) }}>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: px(16),
            padding: `${px(14)}px ${px(16)}px`,
            borderBottom: `1px solid ${COLOR.darker}`,
          }}
        >
          <ApexSkeleton width={px(40)} height={px(40)} radius={px(10)} />
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: px(8) }}>
            <ApexSkeleton width={`${58 + (i % 3) * 8}%`} height={px(16)} />
            <ApexSkeleton width={`${32 + (i % 2) * 10}%`} height={px(12)} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ApexToolsGridLoading({ count = 6 }) {
  const { px } = useFigmaPx();
  return (
    <div
      role="status"
      aria-label="Loading tools"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 280px), 1fr))',
        gap: px(12),
        marginTop: px(24),
      }}
    >
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          style={{
            height: px(140),
            backgroundColor: COLOR.darkest,
            borderRadius: px(16),
            padding: px(16),
            display: 'flex',
            flexDirection: 'column',
            gap: px(12),
          }}
        >
          <ApexSkeleton width={px(48)} height={px(48)} radius={px(12)} />
          <ApexSkeleton width="80%" height={px(16)} />
          <ApexSkeleton width="100%" height={px(12)} />
          <ApexSkeleton width="36%" height={px(28)} radius={px(100)} style={{ marginTop: 'auto' }} />
        </div>
      ))}
    </div>
  );
}

export function ApexShellEmpty({ title, description, style }) {
  const { px } = useFigmaPx();
  return (
    <div
      style={{
        fontFamily: FONT.family,
        padding: px(24),
        borderRadius: px(12),
        border: `1px dashed ${COLOR.darker}`,
        backgroundColor: 'rgba(255,255,255,0.02)',
        ...style,
      }}
    >
      {title && (
        <div
          style={{
            color: COLOR.white,
            fontSize: px(FONT.body2.size),
            lineHeight: `${px(FONT.body2.height)}px`,
            fontWeight: 600,
            marginBottom: description ? px(6) : 0,
          }}
        >
          {title}
        </div>
      )}
      <div
        style={{
          color: COLOR.medium,
          fontSize: px(FONT.body3.size),
          lineHeight: `${px(FONT.body3.height)}px`,
        }}
      >
        {description}
      </div>
    </div>
  );
}
