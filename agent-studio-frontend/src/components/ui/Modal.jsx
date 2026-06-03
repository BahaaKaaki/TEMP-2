import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';
import Button from './Button';

export default function Modal({ isOpen, onClose, title, children, footer, className }) {
  // Close on Escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  // Prevent scroll when modal is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return createPortal(
    <div
      data-theme="apex-dark"
      className="fixed inset-0 z-50 flex items-center justify-center animate-fadeIn"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className={cn(
          "rounded-2xl shadow-2xl w-[90%] max-w-lg max-h-[80vh] overflow-hidden animate-slideIn",
          className
        )}
        style={{
          background: 'linear-gradient(135deg, #1a1a1a 0%, #121212 100%)',
          border: '1px solid #464646',
          color: '#ffffff',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid #464646' }}>
          <h3 className="text-lg font-semibold" style={{ color: '#ffffff' }}>{title}</h3>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-md transition-colors text-lg"
            style={{ color: '#b5b5b5', backgroundColor: 'transparent' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2a2a2a')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 overflow-y-auto" style={{ color: '#e5e5e5' }}>
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-2 px-6 py-4" style={{ borderTop: '1px solid #464646' }}>
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
