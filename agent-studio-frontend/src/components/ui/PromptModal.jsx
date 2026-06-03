// Custom Prompt Modal Component — Apex OS dark theme
import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

const PANEL_BG = 'linear-gradient(135deg, #1a1a1a 0%, #121212 100%)';
const PANEL_BORDER = '#464646';
const TEXT_PRIMARY = '#ffffff';
const TEXT_MUTED = '#b5b5b5';
const ROSE = '#d93854';
const ROSE_HOVER = '#c52a45';

export default function PromptModal({ isOpen, title, message, placeholder = '', defaultValue = '', confirmText = 'OK', cancelText = 'Cancel', onConfirm, onCancel }) {
  const [value, setValue] = useState(defaultValue);
  const inputRef = useRef(null);
  const valueRef = useRef(value);
  const onConfirmRef = useRef(onConfirm);
  const onCancelRef = useRef(onCancel);

  valueRef.current = value;
  onConfirmRef.current = onConfirm;
  onCancelRef.current = onCancel;

  useEffect(() => {
    if (isOpen) {
      setValue(defaultValue);
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);

      const handleKeyDown = (e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onCancelRef.current();
        } else if (e.key === 'Enter' && valueRef.current.trim()) {
          e.stopPropagation();
          onConfirmRef.current(valueRef.current);
        }
      };
      document.addEventListener('keydown', handleKeyDown, true);
      return () => document.removeEventListener('keydown', handleKeyDown, true);
    }
  }, [isOpen, defaultValue]);

  if (!isOpen) return null;

  const handleConfirm = () => {
    if (value.trim()) {
      onConfirm(value);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center z-[9999]"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onCancel}
    >
      <div
        data-theme="apex-dark"
        className="rounded-2xl p-6 w-[90vw] max-w-md shadow-2xl"
        style={{
          background: PANEL_BG,
          border: `1px solid ${PANEL_BORDER}`,
          color: TEXT_PRIMARY,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold mb-2" style={{ color: TEXT_PRIMARY }}>{title}</h3>
        {message && <p className="text-sm mb-4" style={{ color: TEXT_MUTED }}>{message}</p>}

        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
          placeholder={placeholder}
          className="force-white-text w-full px-4 py-3 text-sm rounded-2xl mb-6 focus:outline-none"
          style={{
            backgroundColor: 'transparent',
            border: `1px solid ${PANEL_BORDER}`,
            color: TEXT_PRIMARY,
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = ROSE)}
          onBlur={(e) => (e.currentTarget.style.borderColor = PANEL_BORDER)}
        />

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
            onClick={handleConfirm}
            disabled={!value.trim()}
            className="px-4 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ color: TEXT_PRIMARY, backgroundColor: ROSE, border: 'none' }}
            onMouseEnter={(e) => {
              if (!e.currentTarget.disabled) e.currentTarget.style.backgroundColor = ROSE_HOVER;
            }}
            onMouseLeave={(e) => {
              if (!e.currentTarget.disabled) e.currentTarget.style.backgroundColor = ROSE;
            }}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
