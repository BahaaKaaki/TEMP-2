/**
 * ApexTopBar — the dark navbar that sits at the top of the three new
 * top-level pages (Storefront, My Sessions, My Tools).
 *
 * Figma:
 *   - Frame             157:2476  (1872 × 96 inside an outer 1920 frame)
 *   - Logo              157:2477  (Apex OS, 200 × 45.7)
 *   - Tabs - Big        157:2484  (684 × 48, three tabs centred)
 *   - Avatar            157:2485  (48 × 48, rose bg, MH initials)
 *
 * Dimensions/colours are read from `apexShellSpec.js` and scaled by
 * `useFigmaPx()` so the bar shrinks proportionally on smaller viewports.
 */

import { useState, useEffect, useRef, useLayoutEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useAuth } from '../../context/AuthContext';
import { useFigmaPx } from '../builder/useFigmaScale';
import { COLOR, FONT, NAV } from './apexShellSpec';
import AppIcon from '../ui/AppIcon';

const TABS = [
  { id: 'storefront', label: 'Storefront', icon: 'storefront' },
  { id: 'sessions', label: 'My Sessions', icon: 'sessions', showBadge: true },
  { id: 'mytools', label: 'My tools', icon: 'tools' },
];

const TAB_INDICATOR_TRANSITION =
  'transform 0.28s cubic-bezier(0.32, 0.72, 0, 1), width 0.28s cubic-bezier(0.32, 0.72, 0, 1), opacity 0.2s ease';

function TabButton({ tab, active, badgeCount, onClick, buttonRef }) {
  const { px } = useFigmaPx();
  const t = NAV.tabs;
  const itemColor = active ? t.item.activeText : t.item.inactiveText;

  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onClick}
      className="relative z-[1] flex items-center justify-center"
      style={{
        flex: '1 1 0',
        height: px(t.item.height),
        minWidth: 0,
        paddingLeft: px(t.item.paddingX),
        paddingRight: px(t.item.paddingX),
        paddingTop: px(t.item.paddingY),
        paddingBottom: px(t.item.paddingY),
        gap: px(t.item.gap),
        borderRadius: px(t.item.radius),
        border: '1px solid transparent',
        backgroundColor: 'transparent',
        color: itemColor,
        fontFamily: FONT.family,
        fontSize: px(14),
        lineHeight: `${px(16)}px`,
        fontWeight: 600,
        cursor: 'pointer',
        transition: 'color 0.2s ease',
      }}
    >
      <AppIcon name={tab.icon} size={px(t.item.iconSize)} color={itemColor} weight="regular" />
      <span style={{ whiteSpace: 'nowrap' }}>{tab.label}</span>
      {tab.showBadge && badgeCount != null && (
        <span
          className="flex items-center justify-center"
          style={{
            backgroundColor: active ? NAV.tabs.badge.activeBg : NAV.tabs.badge.bg,
            color: active ? NAV.tabs.badge.activeText : NAV.tabs.badge.text,
            paddingLeft: px(NAV.tabs.badge.paddingX),
            paddingRight: px(NAV.tabs.badge.paddingX),
            paddingTop: px(NAV.tabs.badge.paddingY),
            paddingBottom: px(NAV.tabs.badge.paddingY),
            borderRadius: NAV.tabs.badge.radius,
            minWidth: px(NAV.tabs.badge.minWidth),
            fontSize: px(12),
            lineHeight: `${px(14)}px`,
            fontWeight: 600,
            transition: 'background-color 0.2s ease, color 0.2s ease',
          }}
        >
          {badgeCount}
        </span>
      )}
    </button>
  );
}

export default function ApexTopBar({ activeTab, onTabChange, sessionCount = 0 }) {
  const { scale, px } = useFigmaPx();
  const { user, logout } = useAuth();
  const [showMenu, setShowMenu] = useState(false);
  const avatarRef = useRef(null);
  const tabsContainerRef = useRef(null);
  const tabButtonRefs = useRef({});
  const [menuPos, setMenuPos] = useState(null);
  const [tabIndicator, setTabIndicator] = useState({
    left: 0,
    top: 0,
    width: 0,
    height: 0,
    ready: false,
  });

  const updateTabIndicator = useCallback(() => {
    const container = tabsContainerRef.current;
    const activeEl = tabButtonRefs.current[activeTab];
    if (!container || !activeEl) return;

    const containerRect = container.getBoundingClientRect();
    const activeRect = activeEl.getBoundingClientRect();

    const next = {
      left: activeRect.left - containerRect.left,
      top: activeRect.top - containerRect.top,
      width: activeRect.width,
      height: activeRect.height,
      ready: true,
    };

    setTabIndicator((prev) => {
      if (
        prev.ready === next.ready
        && Math.abs(prev.left - next.left) < 0.5
        && Math.abs(prev.top - next.top) < 0.5
        && Math.abs(prev.width - next.width) < 0.5
        && Math.abs(prev.height - next.height) < 0.5
      ) {
        return prev;
      }
      return next;
    });
  }, [activeTab]);

  useLayoutEffect(() => {
    updateTabIndicator();
  }, [updateTabIndicator, sessionCount, scale]);

  useEffect(() => {
    const container = tabsContainerRef.current;
    if (!container) return undefined;

    const observer = new ResizeObserver(updateTabIndicator);
    observer.observe(container);
    TABS.forEach((tab) => {
      const el = tabButtonRefs.current[tab.id];
      if (el) observer.observe(el);
    });

    window.addEventListener('resize', updateTabIndicator);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateTabIndicator);
    };
  }, [updateTabIndicator, activeTab, sessionCount]);

  const initials = (() => {
    if (user?.firstName && user?.lastName) return `${user.firstName[0]}${user.lastName[0]}`.toUpperCase();
    if (user?.firstName) return user.firstName[0].toUpperCase();
    if (user?.email) return user.email[0].toUpperCase();
    return 'U';
  })();

  useEffect(() => {
    if (!showMenu) return;
    const onKey = (e) => e.key === 'Escape' && setShowMenu(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showMenu]);

  const openMenu = () => {
    if (avatarRef.current) {
      const r = avatarRef.current.getBoundingClientRect();
      setMenuPos({ top: r.bottom + 8, right: window.innerWidth - r.right });
    }
    setShowMenu(true);
  };

  const isAdmin = user?.roleSlug?.toLowerCase().includes('admin') || false;

  return (
    <div
      className="flex-shrink-0"
      style={{
        backgroundColor: COLOR.black,
        paddingLeft: px(NAV.outerMargin),
        paddingRight: px(NAV.outerMargin),
        paddingTop: px(NAV.outerMargin),
        paddingBottom: 0,
        position: 'relative',
        zIndex: 50,
      }}
    >
      <header
        className="relative flex items-center"
        style={{
          height: px(NAV.outerHeight),
          paddingLeft: px(NAV.padding),
          paddingRight: px(NAV.padding),
          paddingTop: px(NAV.padding),
          paddingBottom: px(NAV.padding),
          backgroundColor: NAV.bg,
          borderRadius: px(NAV.radius),
          overflow: 'hidden',
        }}
      >
        {/* Logo */}
        <img
          src="/icons/apex-os-logo.svg"
          alt="Apex OS"
          draggable={false}
          style={{ width: px(NAV.logoWidth), height: px(NAV.logoHeight), flexShrink: 0 }}
        />

        {/* Tab group — centered on the bar (Figma 157:2484), not between logo/avatar */}
        <div
          ref={tabsContainerRef}
          className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 items-start"
          style={{
            width: px(NAV.tabs.width),
            maxWidth: 'min(60vw, calc(100% - 280px))',
            padding: px(NAV.tabs.padding),
            gap: px(NAV.tabs.gap),
            backgroundColor: NAV.tabs.bg,
            borderRadius: px(NAV.tabs.radius),
          }}
        >
          <div
            aria-hidden="true"
            className="pointer-events-none absolute left-0 top-0"
            style={{
              transform: `translate3d(${tabIndicator.left}px, ${tabIndicator.top}px, 0)`,
              width: tabIndicator.width,
              height: tabIndicator.height,
              opacity: tabIndicator.ready ? 1 : 0,
              transition: tabIndicator.ready ? TAB_INDICATOR_TRANSITION : 'none',
              borderRadius: px(NAV.tabs.item.radius),
              border: `1px solid ${NAV.tabs.item.activeBorder}`,
              backgroundColor: NAV.tabs.item.activeBg,
              boxShadow: NAV.tabs.item.activeShadow,
              willChange: 'transform, width',
            }}
          />
          {TABS.map((tab) => (
            <TabButton
              key={tab.id}
              tab={tab}
              active={activeTab === tab.id}
              badgeCount={tab.id === 'sessions' ? sessionCount : undefined}
              onClick={() => onTabChange?.(tab.id)}
              buttonRef={(el) => {
                tabButtonRefs.current[tab.id] = el;
              }}
            />
          ))}
        </div>

        {/* Avatar — solid rose with a 2px lighter-rose ring per Figma 157:2485 */}
        <button
          ref={avatarRef}
          type="button"
          onClick={openMenu}
          className="ml-auto flex items-center justify-center"
          style={{
            width: px(NAV.avatar.size),
            height: px(NAV.avatar.size),
            flexShrink: 0,
            borderRadius: '50%',
            backgroundColor: NAV.avatar.bg,
            color: NAV.avatar.text,
            fontFamily: FONT.family,
            fontSize: px(NAV.avatar.fontSize),
            fontWeight: NAV.avatar.fontWeight,
            border: `${px(NAV.avatar.borderWidth)}px solid ${NAV.avatar.borderStyle}`,
            cursor: 'pointer',
            padding: 0,
            transition: 'background-color 200ms ease, transform 200ms ease, box-shadow 200ms ease',
          }}
          title={user?.email || 'Account'}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = NAV.avatar.borderStyle;
            e.currentTarget.style.boxShadow = '0 0 0 2px rgba(217, 56, 84, 0.25)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = NAV.avatar.bg;
            e.currentTarget.style.boxShadow = 'none';
          }}
          onMouseDown={(e) => {
            e.currentTarget.style.transform = 'scale(0.97)';
          }}
          onMouseUp={(e) => {
            e.currentTarget.style.transform = 'scale(1)';
          }}
        >
          {initials}
        </button>
      </header>

      {showMenu && menuPos &&
        createPortal(
          <>
            <div
              className="fixed inset-0"
              style={{ zIndex: 100 }}
              onClick={() => setShowMenu(false)}
            />
            <div
              className="rounded-2xl shadow-2xl"
              style={{
                position: 'fixed',
                top: menuPos.top,
                right: menuPos.right,
                width: 260,
                background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
                border: `1px solid ${COLOR.darker}`,
                color: COLOR.white,
                zIndex: 101,
                fontFamily: FONT.family,
              }}
            >
              <div style={{ padding: 16, borderBottom: `1px solid ${COLOR.darker}` }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: COLOR.white }}>
                  {user?.firstName && user?.lastName
                    ? `${user.firstName} ${user.lastName}`
                    : user?.firstName || 'User'}
                </div>
                <div style={{ fontSize: 12, color: COLOR.medium, marginTop: 2 }}>{user?.email}</div>
              </div>
              <div style={{ padding: 8 }}>
                {isAdmin && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowMenu(false);
                      onTabChange?.('admin');
                    }}
                    className="w-full text-left"
                    style={{
                      padding: '8px 12px',
                      borderRadius: 8,
                      color: COLOR.white,
                      backgroundColor: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: 14,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                  >
                    Admin Portal
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setShowMenu(false);
                    logout();
                  }}
                  className="w-full text-left"
                  style={{
                    padding: '8px 12px',
                    borderRadius: 8,
                    color: COLOR.rose,
                    backgroundColor: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 14,
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  Sign out
                </button>
              </div>
            </div>
          </>,
          document.body,
        )}
    </div>
  );
}
