// Custom Alert Modal Component — Apex OS dark theme
import { useEffect } from 'react';
import { createPortal } from 'react-dom';

const PANEL_BG = 'linear-gradient(135deg, #1a1a1a 0%, #121212 100%)';
const PANEL_BORDER = '#464646';
const TEXT_PRIMARY = '#ffffff';
const TEXT_MUTED = '#b5b5b5';
const ROSE = '#d93854';
const ROSE_HOVER = '#c52a45';

export default function AlertModal({ isOpen, title, message, confirmText = 'OK', onClose, variant = 'info' }) {
  useEffect(() => {
    if (isOpen) {
      const handleEscape = (e) => {
        if (e.key === 'Escape' || e.key === 'Enter') {
          onClose();
        }
      };
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const variantBg = {
    info: '#3a3a3a',
    success: '#1aab40',
    error: ROSE,
    warning: ROSE,
  };
  const variantHover = {
    info: '#505050',
    success: '#149036',
    error: ROSE_HOVER,
    warning: ROSE_HOVER,
  };
  const iconMap = {
    info: 'i',
    success: '\u2713',
    error: '\u2715',
    warning: '!',
  };
  const iconBg = {
    info: 'rgba(130, 22, 197, 0.15)',
    success: 'rgba(26, 171, 64, 0.15)',
    error: 'rgba(217, 56, 84, 0.15)',
    warning: 'rgba(217, 56, 84, 0.15)',
  };
  const iconColor = {
    info: '#8216c5',
    success: '#1aab40',
    error: ROSE,
    warning: ROSE,
  };

  const btnBg = variantBg[variant] || '#3a3a3a';
  const btnHover = variantHover[variant] || '#505050';

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center z-[9999]"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl p-6 w-[90vw] max-w-md shadow-2xl"
        style={{
          background: PANEL_BG,
          border: `1px solid ${PANEL_BORDER}`,
          color: TEXT_PRIMARY,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          <span
            className="flex-shrink-0 flex items-center justify-center rounded-full text-base font-bold"
            style={{
              width: 32,
              height: 32,
              backgroundColor: iconBg[variant],
              color: iconColor[variant],
            }}
          >
            {iconMap[variant]}
          </span>
          <div className="flex-1">
            <h3 className="text-lg font-semibold mb-2" style={{ color: TEXT_PRIMARY }}>
              {title}
            </h3>
            <p className="text-sm" style={{ color: TEXT_MUTED }}>
              {message}
            </p>
          </div>
        </div>

        <div className="flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{ color: TEXT_PRIMARY, backgroundColor: btnBg, border: 'none' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = btnHover)}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = btnBg)}
            autoFocus
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
