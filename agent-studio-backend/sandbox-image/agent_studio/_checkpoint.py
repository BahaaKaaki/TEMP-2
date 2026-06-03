"""
Checkpoint save/restore for pause-resume in the agent_studio sandbox SDK.

Uses cloudpickle to serialize user-defined variables before an output.ask()
pause so that expensive computations (data processing, LLM calls) are not
re-executed on resume.

All errors are caught and logged -- a failed checkpoint never crashes the
script; it simply falls back to replay-from-top behaviour.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_CHECKPOINT_PATH = "/outputs/_checkpoint.pkl"
_MAX_CHECKPOINT_BYTES = 50 * 1024 * 1024  # 50 MB hard cap

logger = logging.getLogger("agent_studio.checkpoint")

_SKIP_NAMES = frozenset({
    "__builtins__", "__name__", "__doc__", "__package__",
    "__loader__", "__spec__", "__file__", "__cached__",
    "_json", "_sys", "_f", "_builtins", "_agent_studio_inputs",
    "inputs", "_checkpoint_vars",
})

_SKIP_MODULE_PREFIXES = ("agent_studio", "_", "builtins")


def save_checkpoint(frame) -> bool:
    """Serialize the caller's local + module-global variables to disk.

    ``frame`` should be the caller's frame (the user-code frame that
    called ``output.ask()``).  We merge frame locals with module globals
    from ``__main__``, filtering out SDK internals and builtins.

    Returns True on success, False on failure.
    """
    try:
        import cloudpickle
    except ImportError:
        logger.warning("cloudpickle not installed -- checkpoint skipped")
        return False

    try:
        user_vars: dict[str, Any] = {}

        main_mod = sys.modules.get("__main__")
        if main_mod is not None:
            for k, v in vars(main_mod).items():
                if k.startswith("__") and k.endswith("__"):
                    continue
                if k.startswith("_") and not k[1:2].isalpha():
                    continue
                if k in _SKIP_NAMES:
                    continue
                if _is_module(v) or _is_sdk_object(v):
                    continue
                user_vars[k] = v

        if frame is not None:
            for k, v in frame.f_locals.items():
                if k.startswith("_"):
                    continue
                if k in _SKIP_NAMES:
                    continue
                if _is_module(v) or _is_sdk_object(v):
                    continue
                user_vars[k] = v

        if not user_vars:
            logger.info("No user variables to checkpoint")
            return False

        blob = cloudpickle.dumps(user_vars)
        if len(blob) > _MAX_CHECKPOINT_BYTES:
            logger.warning(
                "Checkpoint too large (%d bytes > %d limit) -- skipped",
                len(blob), _MAX_CHECKPOINT_BYTES,
            )
            return False

        with open(_CHECKPOINT_PATH, "wb") as f:
            f.write(blob)

        logger.info(
            "Checkpoint saved: %d variable(s), %d bytes",
            len(user_vars), len(blob),
        )
        return True

    except Exception:
        logger.warning("Failed to save checkpoint", exc_info=True)
        return False


def restore_checkpoint() -> dict[str, Any] | None:
    """Load a previously saved checkpoint from disk.

    Returns the variable dict on success, or None if no checkpoint exists
    or loading fails.
    """
    try:
        import cloudpickle
    except ImportError:
        return None

    try:
        with open(_CHECKPOINT_PATH, "rb") as f:
            data = cloudpickle.load(f)

        if isinstance(data, dict):
            logger.info("Checkpoint restored: %d variable(s)", len(data))
            return data

        logger.warning("Checkpoint data is not a dict -- ignoring")
        return None

    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("Failed to restore checkpoint", exc_info=True)
        return None


def _is_module(obj: Any) -> bool:
    import types
    return isinstance(obj, types.ModuleType)


def _is_sdk_object(obj: Any) -> bool:
    cls_module = getattr(type(obj), "__module__", "") or ""
    return any(cls_module.startswith(p) for p in _SKIP_MODULE_PREFIXES)
