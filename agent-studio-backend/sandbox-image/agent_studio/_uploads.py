"""
Convenience helpers for accessing uploaded files inside the sandbox.

Files injected by the host appear at ``/workspace/uploads/``.
"""

from __future__ import annotations

import os
from typing import List

_UPLOADS_DIR = "/workspace/uploads"


class _Uploads:
    """Read-only accessor for files placed in the sandbox by the host."""

    @staticmethod
    def list() -> List[str]:
        """Return full paths of all uploaded files."""
        if not os.path.isdir(_UPLOADS_DIR):
            return []
        return sorted(
            os.path.join(_UPLOADS_DIR, f)
            for f in os.listdir(_UPLOADS_DIR)
            if os.path.isfile(os.path.join(_UPLOADS_DIR, f))
        )

    @staticmethod
    def get(name: str) -> str:
        """Return the full path for an uploaded file by name.

        Raises ``FileNotFoundError`` if the file doesn't exist.
        """
        path = os.path.join(_UPLOADS_DIR, name)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Uploaded file not found: {name}")
        return path

    @staticmethod
    def exists(name: str) -> bool:
        return os.path.isfile(os.path.join(_UPLOADS_DIR, name))


uploads = _Uploads()
