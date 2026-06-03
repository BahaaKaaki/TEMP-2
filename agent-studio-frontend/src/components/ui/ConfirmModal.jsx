// Custom Confirm Modal Component
import { useEffect } from 'react';
import { createPortal } from 'react-dom';

// Apex OS dark theme — same gradient + tokens used by the workflow
// builder's right-hand config panel (Figma file "Apex OS 5"). Keeping
// these inline so the modal looks correct even if it's rendered outside
// the .builder-config-panel scope.
const PANEL_BG = 'linear-gradient(135deg, #1a1a1a 0%, #121212 100%)';
const PANEL_BORDER = '#464646';
const TEXT_PRIMARY = '#ffffff';
const TEXT_MUTED = '#b5b5b5';
const ROSE = '#d93854';
const ROSE_HOVER = '#c52a45';

export default function ConfirmModal({ isOpen, title, message, confirmText = 'Confirm', cancelText = 'Cancel', onConfirm, onCancel, variant = 'default' }) {
  useEffect(() => {
    if (isOpen) {
      const handleEscape = (e) => {
        if (e.key === 'Escape') {
          onCancel();
        }
      };
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  const isDanger = variant === 'danger';
  const confirmBg = isDanger ? ROSE : '#3a3a3a';
  const confirmHoverBg = isDanger ? ROSE_HOVER : '#505050';

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center z-[9999]"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onCancel}
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
        <h3 className="text-lg font-semibold mb-3" style={{ color: TEXT_PRIMARY }}>
          {title}
        </h3>
        <p className="text-sm mb-6" style={{ color: TEXT_MUTED }}>
          {message}
        </p>

        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{
              color: TEXT_PRIMARY,
              backgroundColor: 'transparent',
              border: `1px solid ${PANEL_BORDER}`,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
            style={{
              color: TEXT_PRIMARY,
              backgroundColor: confirmBg,
              border: 'none',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = confirmHoverBg)}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = confirmBg)}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
