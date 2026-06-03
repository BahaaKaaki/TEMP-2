import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import ApexLoginRays from './ApexLoginRays';
import { APP_FONT_SANS } from '../../theme/typography';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

/**
 * Nudge the ray origin away from the "x" span's geometric center toward
 * the optical center of the glyph itself. Expressed as a fraction of the
 * wordmark's font-size so it scales with the headline.
 */
const RAY_ORIGIN_NUDGE = { x: 0.20, y: 0.06 };

export default function LoginForm() {
  const [redirecting, setRedirecting] = useState(false);
  const pageRef = useRef(null);
  const wordmarkRef = useRef(null);
  const burstAnchorRef = useRef(null);
  const [burstOrigin, setBurstOrigin] = useState({ x: 0, y: 0 });
  const [wordmarkOffset, setWordmarkOffset] = useState(0);

  const updateBurstOrigin = useCallback(() => {
    const page = pageRef.current;
    const wordmark = wordmarkRef.current;
    const anchor = burstAnchorRef.current;
    if (!page || !wordmark || !anchor) return;

    const pageRect = page.getBoundingClientRect();
    const wordmarkRect = wordmark.getBoundingClientRect();
    const anchorRect = anchor.getBoundingClientRect();

    const wordmarkCenter = wordmarkRect.left + wordmarkRect.width / 2;
    const anchorCenter = anchorRect.left + anchorRect.width / 2;
    setWordmarkOffset(wordmarkCenter - anchorCenter);

    const fontSize = parseFloat(getComputedStyle(wordmark).fontSize) || anchorRect.height;
    const nudgeX = fontSize * RAY_ORIGIN_NUDGE.x;
    const nudgeY = fontSize * RAY_ORIGIN_NUDGE.y;

    setBurstOrigin({
      x: anchorRect.left - pageRect.left + anchorRect.width / 2
        + (wordmarkCenter - anchorCenter) + nudgeX,
      y: anchorRect.top - pageRect.top + anchorRect.height / 2 + nudgeY,
    });
  }, []);

  useLayoutEffect(() => {
    updateBurstOrigin();
    document.fonts?.ready?.then(updateBurstOrigin);
    const observer = new ResizeObserver(updateBurstOrigin);
    observer.observe(document.documentElement);
    window.addEventListener('resize', updateBurstOrigin);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateBurstOrigin);
    };
  }, [updateBurstOrigin]);

  const handleSignIn = () => {
    setRedirecting(true);
    const returnTo = encodeURIComponent(window.location.origin);
    window.location.href = `${API_BASE_URL}/api/auth/microsoft/login?return_to=${returnTo}`;
  };

  return (
    <div ref={pageRef} className="login-page fixed inset-0 overflow-hidden bg-canvas">
      <ApexLoginRays
        originX={burstOrigin.x}
        originY={burstOrigin.y}
      />
      <div className="login-page__vignette" aria-hidden="true" />

      <div className="login-page__content">
        <h1
          ref={wordmarkRef}
          className="login-page__wordmark"
          style={{
            fontFamily:APP_FONT_SANS,
            transform: `translateX(${wordmarkOffset}px)`,
          }}
          aria-label="Apex OS"
        >
          <span className="login-page__wordmark-apex">Ape</span>
          <span className="login-page__wordmark-x" ref={burstAnchorRef}>
            x
          </span>
          <span className="login-page__wordmark-os"> OS</span>
        </h1>

        <button
          type="button"
          onClick={handleSignIn}
          disabled={redirecting}
          className="login-page__sign-in"
        >
          {redirecting ? (
            <>
              <span
                className="inline-block h-4 w-4 rounded-full border-2 border-black/30 border-t-black animate-spin"
                aria-hidden="true"
              />
              <span>Redirecting…</span>
            </>
          ) : (
            <>
              <MicrosoftIcon className="h-5 w-5 shrink-0" />
              <span>Sign in with Microsoft</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function MicrosoftIcon({ className = '' }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <rect x="2" y="2" width="9" height="9" fill="#F25022" />
      <rect x="13" y="2" width="9" height="9" fill="#7FBA00" />
      <rect x="2" y="13" width="9" height="9" fill="#00A4EF" />
      <rect x="13" y="13" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}
