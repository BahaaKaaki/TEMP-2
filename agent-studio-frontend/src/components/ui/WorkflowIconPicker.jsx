import { useState, useRef, useCallback } from 'react';
import { API_BASE_URL } from '../../api/client';

/**
 * WorkflowIconPicker — click-to-upload image picker for workflow icons.
 *
 * Shows the current icon (or a placeholder) as a rounded tile.
 * Clicking opens the native file picker.  Hovering reveals overlay
 * controls (camera icon to change, X to remove).
 *
 * Props:
 *   iconUrl   — current icon URL (null if none)
 *   onUpload  — (file: File) => Promise<void>   called when user picks a file
 *   onRemove  — () => Promise<void>              called when user clicks remove
 *   size      — pixel size of the tile (default 36)
 *   disabled  — if true, disables interaction
 */
export default function WorkflowIconPicker({
  iconUrl,
  onUpload,
  onRemove,
  size = 36,
  disabled = false,
}) {
  const fileRef = useRef(null);
  const [hover, setHover] = useState(false);
  const [uploading, setUploading] = useState(false);

  const handleFileChange = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file || !onUpload) return;
    try {
      setUploading(true);
      await onUpload(file);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }, [onUpload]);

  const handleRemove = useCallback(async (e) => {
    e.stopPropagation();
    if (!onRemove) return;
    try {
      setUploading(true);
      await onRemove();
    } finally {
      setUploading(false);
    }
  }, [onRemove]);

  const borderRadius = size * 0.22;

  return (
    <div
      style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
        style={{ display: 'none' }}
        onChange={handleFileChange}
        disabled={disabled || uploading}
      />

      {/* Tile */}
      <button
        type="button"
        onClick={() => !disabled && !uploading && fileRef.current?.click()}
        style={{
          width: size,
          height: size,
          borderRadius,
          border: iconUrl ? 'none' : '2px dashed rgba(255,255,255,0.25)',
          backgroundColor: iconUrl ? 'transparent' : 'rgba(255,255,255,0.06)',
          cursor: disabled ? 'default' : 'pointer',
          padding: 0,
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'border-color 0.15s',
        }}
        title={iconUrl ? 'Change icon' : 'Add icon'}
        disabled={disabled || uploading}
      >
        {uploading ? (
          <svg
            width={size * 0.45}
            height={size * 0.45}
            viewBox="0 0 24 24"
            fill="none"
            stroke="rgba(255,255,255,0.5)"
            strokeWidth={2}
            className="animate-spin"
          >
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
        ) : iconUrl ? (
          <img
            src={`${API_BASE_URL}${iconUrl}`}
            alt=""
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'cover',
              borderRadius,
            }}
          />
        ) : (
          <svg
            width={size * 0.45}
            height={size * 0.45}
            viewBox="0 0 24 24"
            fill="none"
            stroke="rgba(255,255,255,0.35)"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <polyline points="21 15 16 10 5 21" />
          </svg>
        )}
      </button>

      {/* Hover overlay — change / remove */}
      {hover && !disabled && !uploading && iconUrl && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius,
            backgroundColor: 'rgba(0,0,0,0.55)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 4,
          }}
        >
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 2,
              display: 'flex',
            }}
            title="Change icon"
          >
            <svg
              width={size * 0.32}
              height={size * 0.32}
              viewBox="0 0 24 24"
              fill="none"
              stroke="white"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
          </button>
          {onRemove && (
            <button
              type="button"
              onClick={handleRemove}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: 2,
                display: 'flex',
              }}
              title="Remove icon"
            >
              <svg
                width={size * 0.28}
                height={size * 0.28}
                viewBox="0 0 24 24"
                fill="none"
                stroke="#d93854"
                strokeWidth={2.5}
                strokeLinecap="round"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
