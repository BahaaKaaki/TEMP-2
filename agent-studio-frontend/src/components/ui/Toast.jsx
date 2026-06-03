import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const EXIT_MS = 260;

const VARIANT_STYLES = {
  success: {
    border: 'rgba(26, 171, 64, 0.45)',
    background: 'linear-gradient(135deg, #1a2e1f 0%, #141414 100%)',
    iconBg: 'rgba(26, 171, 64, 0.2)',
    iconColor: '#4ade80',
    icon: '\u2713',
  },
  error: {
    border: 'rgba(217, 56, 84, 0.45)',
    background: 'linear-gradient(135deg, #2a1a1d 0%, #141414 100%)',
    iconBg: 'rgba(217, 56, 84, 0.2)',
    iconColor: '#f87171',
    icon: '\u2715',
  },
  info: {
    border: 'rgba(217, 56, 84, 0.35)',
    background: 'linear-gradient(135deg, #1e1e1e 0%, #1a1a1a 100%)',
    iconBg: 'rgba(130, 22, 197, 0.15)',
    iconColor: '#d93854',
    icon: 'i',
  },
};

/**
 * Non-blocking toast (portal, top-right). Slides in from the right; slides out on dismiss.
 */
export default function Toast({
  isOpen,
  message,
  title,
  variant = 'success',
  durationMs = 4000,
  onClose,
}) {
  const [visible, setVisible] = useState(false);
  const [exiting, setExiting] = useState(false);
  const dismissTimerRef = useRef(null);
  const exitTimerRef = useRef(null);
  const exitingRef = useRef(false);
  const onCloseRef = useRef(onClose);

  onCloseRef.current = onClose;

  const clearDismissTimer = useCallback(() => {
    if (dismissTimerRef.current != null) {
      window.clearTimeout(dismissTimerRef.current);
      dismissTimerRef.current = null;
    }
  }, []);

  const clearExitTimer = useCallback(() => {
    if (exitTimerRef.current != null) {
      window.clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }
  }, []);

  const finishClose = useCallback(() => {
    exitingRef.current = false;
    setExiting(false);
    setVisible(false);
    onCloseRef.current?.();
  }, []);

  const startExit = useCallback(() => {
    if (exitingRef.current) return;
    exitingRef.current = true;
    clearDismissTimer();
    setExiting(true);
    clearExitTimer();
    exitTimerRef.current = window.setTimeout(finishClose, EXIT_MS);
  }, [clearDismissTimer, clearExitTimer, finishClose]);

  // Open: mount + schedule auto-dismiss (only when isOpen/message change to a new toast)
  useEffect(() => {
    if (!isOpen || !message) {
      return undefined;
    }

    exitingRef.current = false;
    setExiting(false);
    setVisible(true);
    clearDismissTimer();

    if (durationMs > 0) {
      dismissTimerRef.current = window.setTimeout(startExit, durationMs);
    }

    return () => {
      clearDismissTimer();
    };
  }, [isOpen, message, title, durationMs, startExit, clearDismissTimer]);

  // Parent cleared isOpen while still visible — run exit if not already exiting
  useEffect(() => {
    if (!isOpen && visible && !exitingRef.current) {
      startExit();
    }
  }, [isOpen, visible, startExit]);

  useEffect(() => () => {
    clearDismissTimer();
    clearExitTimer();
  }, [clearDismissTimer, clearExitTimer]);

  if (!visible || !message) return null;

  const v = VARIANT_STYLES[variant] || VARIANT_STYLES.info;
  const motionClass = exiting ? 'toast-slide-out' : 'toast-slide-in';

  return createPortal(
    <div
      className="fixed top-6 right-6 z-[100] pointer-events-none w-[min(420px,calc(100vw-3rem))] min-w-[280px]"
      role="status"
      aria-live="polite"
    >
      <div
        className={`pointer-events-auto flex w-full items-start gap-3 rounded-[10px] border px-4 py-3 shadow-2xl ${motionClass}`}
        style={{
          borderColor: v.border,
          background: v.background,
        }}
      >
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] text-sm font-bold"
          style={{ backgroundColor: v.iconBg, color: v.iconColor }}
          aria-hidden
        >
          {v.icon}
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          {title ? (
            <p className="text-sm font-bold text-white leading-snug">{title}</p>
          ) : null}
          <p className={`text-sm text-[#dadada] leading-snug ${title ? 'mt-0.5' : ''}`}>
            {message}
          </p>
        </div>
        <button
          type="button"
          onClick={startExit}
          className="shrink-0 rounded-[6px] p-1 text-[#6b6b6b] hover:bg-white/10 hover:text-white transition-colors"
          aria-label="Dismiss"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>,
    document.body,
  );
}
