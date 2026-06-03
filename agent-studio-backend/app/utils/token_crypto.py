"""
Fernet-based field-level encryption for high-value secrets stored in the
database. Currently used to wrap each user's Microsoft OAuth refresh token
so that even a `SELECT *` from the `ms_oauth_token` table — accidental,
malicious, or via an RLS bypass — yields opaque ciphertext, not a usable
credential.

Why Fernet (vs raw AES-GCM):
    * Authenticated encryption out of the box (HMAC-SHA256), so tampering
      is detected automatically.
    * 128-bit AES-CBC + IV per message — every encrypt() of the same
      plaintext produces a different ciphertext.
    * Url-safe base64 wire format, so we can store directly in TEXT columns.
    * Built into the `cryptography` library, which is already a transitive
      dependency via python-jose[cryptography].

Operational notes:
    * The encryption key MUST be set in env var `MS_TOKEN_ENCRYPTION_KEY`.
      Generate one with:
          python -c "from cryptography.fernet import Fernet; \\
                     print(Fernet.generate_key().decode())"
    * Losing the key invalidates every stored refresh token; users will
      simply need to re-authenticate via Microsoft SSO. There is no
      "decrypt without the key" path — that's the point.
    * Rotating the key is supported via Fernet's MultiFernet, but is out
      of scope for the initial implementation. To rotate later, switch
      `_singleton` to a MultiFernet of [new_key, old_key], rewrite all
      stored tokens with `new_key.encrypt(old.decrypt(...))`, then drop
      the old key.
"""

from __future__ import annotations

import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class TokenCrypto:
    """Thin wrapper around Fernet that operates on `str` instead of bytes."""

    def __init__(self, key: bytes | str) -> None:
        if isinstance(key, str):
            key = key.encode()
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> Optional[str]:
        """Returns None if the ciphertext is corrupted, has been tampered
        with, or was encrypted with a different key. Callers should treat
        a None as "no token available, force re-auth"."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            # Either tampered ciphertext or, more likely, encryption key
            # rotated without re-encrypting existing rows. We deliberately
            # do NOT log the ciphertext.
            logger.warning(
                "Failed to decrypt stored token (key rotated or tampered). "
                "Affected user will need to re-authenticate."
            )
            return None


_singleton: Optional[TokenCrypto] = None


def get_token_crypto() -> TokenCrypto:
    """Lazy-initialised singleton so we don't blow up on import if the
    secret is missing — only when an endpoint that needs encryption runs.

    Source order (handled centrally in ``config.keyvault.load_secrets``):
        1. Azure Key Vault secret ``ms-token-encryption-key``  (cloud)
        2. ``MS_TOKEN_ENCRYPTION_KEY`` env / .env              (local dev)
    """
    global _singleton
    if _singleton is None:
        from config.keyvault import cfg
        key = getattr(cfg, "MS_TOKEN_ENCRYPTION_KEY", None)
        if not key:
            raise RuntimeError(
                "MS_TOKEN_ENCRYPTION_KEY is not configured.\n"
                "  • Cloud: add a Key Vault secret named 'ms-token-encryption-key'.\n"
                "  • Local: set MS_TOKEN_ENCRYPTION_KEY in your .env file.\n"
                "Generate a value with:\n"
                "    python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"\n"
                "The same value MUST be used across all backend replicas and "
                "persisted across restarts — losing it invalidates every "
                "stored Microsoft refresh token."
            )
        _singleton = TokenCrypto(key)
    return _singleton


def reset_token_crypto_for_tests() -> None:
    """Test helper — reset the singleton so tests can override the key."""
    global _singleton
    _singleton = None
