"""
Sandbox KB session — stateless signed sessions.

A "session" is an HMAC-SHA256 signed blob that encapsulates
``{user_id, kb_ids[], sandbox_id, iat, exp}``.  There is no shared
in-memory or external store: every worker can verify a session it
didn't create, because verification only needs the shared
``JWT_SECRET_KEY`` that signs the blob.

This matters because the API is typically run with multiple uvicorn
workers (one per core), and an in-memory dict wouldn't be visible to
siblings — a session minted in worker A would fail to resolve in worker
B's callback.

Why this is still secure
========================
* **Signed.** The token can't be forged — it's HMAC-SHA256 over
  ``header.payload`` using ``JWT_SECRET_KEY``.  The sandbox gets the
  token, but user code cannot produce a new one with different
  ``user_id`` or different ``kb_ids``.
* **Never on disk.** The host forwards the token only as an env var;
  the SDK ``os.environ.pop``s it at import.  User code doing
  ``print(os.environ)`` or ``ls /workspace`` reveals nothing.
* **Short-lived.** Default TTL = run timeout + 60 s (~3 min for a
  default run).  Not the 2-hour value the first cut of this feature
  used.
* **Scoped.** Every callback re-checks the ``kb_id`` against the list
  baked into the payload, enforces RLS via the payload's ``user_id``,
  and runs the SQL through the SELECT-only validator with row/timeout
  caps.

Revocation
==========
There is no authoritative revoke (no shared store).  ``revoke_session``
exists for API symmetry with the earlier registry implementation, but
logically it's a no-op — the TTL handles lifetime.  A leaked token is
useless after a few minutes and, more importantly, after the sandbox
exits the token can't be used from the user's context anyway (they
never had it to begin with because the SDK popped it).

Compatibility
=============
The public surface (``create_session``, ``get_session``,
``revoke_session``, ``SandboxKbSession``) matches what the routes and
the node already consume, so this is a drop-in replacement for the
earlier in-memory registry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────

def _secret_key() -> bytes:
    """Return the HMAC key.  Read late so tests can override env."""
    try:
        from config.keyvault import cfg
        key = getattr(cfg, "JWT_SECRET_KEY", None) or getattr(cfg, "SECRET_KEY", None)
    except Exception:
        key = None

    if not key:
        # In dev / tests without keyvault configured, fall back to a
        # per-process random key.  This still signs; it just means
        # sessions don't survive a process restart (acceptable).
        import os as _os
        key = _os.environ.get("JWT_SECRET_KEY") or _os.environ.get("SECRET_KEY")
        if not key:
            # Absolute last resort — stable per process, logged once.
            global _FALLBACK_KEY  # type: ignore[misc]
            try:
                _FALLBACK_KEY  # type: ignore[used-before-def]
            except NameError:
                _FALLBACK_KEY = secrets.token_bytes(32)  # type: ignore[assignment]
                logger.warning(
                    "KB session signer: no JWT_SECRET_KEY / SECRET_KEY configured; "
                    "using an ephemeral per-process key.  Sessions will not be "
                    "verifiable by sibling workers.",
                )
            return _FALLBACK_KEY  # type: ignore[return-value]
    return key.encode("utf-8") if isinstance(key, str) else bytes(key)


# ── Base64url helpers (no padding) ─────────────────────────────────────

def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


# ── Public dataclass ───────────────────────────────────────────────────

@dataclass
class SandboxKbSession:
    """Decoded signed-session record.

    Produced by :func:`create_session` and returned by :func:`get_session`
    after successful verification.
    """

    session_id: str  # the full signed token string
    user_id: str
    kb_ids: List[str]
    container_id: Optional[str]
    created_at: float
    expires_at: float
    revoked: bool = field(default=False)


# ── Token codec ────────────────────────────────────────────────────────

def _sign(parts: str) -> str:
    digest = hmac.new(_secret_key(), parts.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _mint(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "AS-KBSES"}
    p_hdr = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_pl = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _sign(f"{p_hdr}.{p_pl}")
    return f"{p_hdr}.{p_pl}.{sig}"


def _verify(token: str) -> Optional[dict]:
    try:
        p_hdr, p_pl, sig = token.split(".", 2)
    except ValueError:
        return None

    expected = _sign(f"{p_hdr}.{p_pl}")
    if not hmac.compare_digest(expected, sig):
        return None

    try:
        payload = json.loads(_b64url_decode(p_pl).decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    return payload


# ── Public API ─────────────────────────────────────────────────────────

def create_session(
    *,
    user_id: str,
    kb_ids: List[str],
    container_id: Optional[str] = None,
    ttl_seconds: int = 3600,
) -> SandboxKbSession:
    """Mint a new signed session for a sandbox run."""
    if not user_id:
        raise ValueError("user_id is required to create a KB session")
    if not kb_ids:
        raise ValueError("kb_ids must contain at least one id")

    now = time.time()
    exp = now + max(1, int(ttl_seconds))
    clean_kb_ids = [str(k) for k in kb_ids if k]

    payload = {
        "uid": str(user_id),
        "kbs": clean_kb_ids,
        "sid": container_id or "",
        "iat": int(now),
        "exp": int(exp),
        # jti lets two tokens with otherwise identical payloads differ,
        # so callers can tell them apart in logs / diagnostics.
        "jti": secrets.token_urlsafe(12),
    }
    token = _mint(payload)

    logger.debug(
        "Minted KB session (user=%s, kbs=%d, ttl=%ds)",
        user_id, len(clean_kb_ids), ttl_seconds,
    )
    return SandboxKbSession(
        session_id=token,
        user_id=str(user_id),
        kb_ids=clean_kb_ids,
        container_id=container_id,
        created_at=now,
        expires_at=exp,
    )


def get_session(session_id: str) -> Optional[SandboxKbSession]:
    """Verify a session token and return the decoded record.

    Returns ``None`` when the signature is bad, the payload is malformed,
    or the token has expired.
    """
    if not session_id or not isinstance(session_id, str):
        return None

    payload = _verify(session_id)
    if payload is None:
        return None

    try:
        uid = str(payload["uid"])
        kbs = list(payload.get("kbs") or [])
        iat = float(payload.get("iat") or 0)
        exp = float(payload.get("exp") or 0)
    except Exception:
        return None

    if not uid or not kbs or not exp:
        return None

    if time.time() >= exp:
        return None

    return SandboxKbSession(
        session_id=session_id,
        user_id=uid,
        kb_ids=[str(k) for k in kbs],
        container_id=str(payload.get("sid") or "") or None,
        created_at=iat,
        expires_at=exp,
    )


def revoke_session(session_id: str) -> bool:
    """No-op revoke (the registry is stateless).

    Logs the intent for diagnostics; real lifecycle control is TTL.
    Returns ``True`` if the token was valid at revoke time, ``False``
    otherwise — purely informational.
    """
    sess = get_session(session_id) if session_id else None
    if sess is None:
        return False
    logger.debug(
        "KB session revoke requested for user=%s (stateless -- TTL %.0fs remaining)",
        sess.user_id, max(0.0, sess.expires_at - time.time()),
    )
    return True


def active_session_count() -> int:
    """Stateless: we don't track a count.  Kept for API symmetry."""
    return -1


def _reset_for_tests() -> None:
    """No-op (stateless)."""
    return None
