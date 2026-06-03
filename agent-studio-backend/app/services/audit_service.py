"""
Structured audit logging for security-sensitive operations.

Writes JSON-formatted events to a dedicated ``audit.code_execution`` logger
so they can be routed to a separate file, SIEM, or log aggregator without
polluting regular application logs.

Usage::

    from services.audit_service import audit

    audit.code_execution_started(
        user_id="abc", session_id="s1", execution_id="42",
        node_id="n1", node_label="Code Executor",
    )
"""

import json
import logging
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

_logger = logging.getLogger("audit.code_execution")
_configured = False


def _ensure_configured() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    try:
        from config.keyvault import cfg
        enabled = getattr(cfg, "AUDIT_LOG_ENABLED", True)
    except Exception:
        enabled = True

    if not enabled:
        _logger.disabled = True
        return

    _logger.setLevel(logging.INFO)
    _logger.propagate = False

    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return record.getMessage()

    import os
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(log_dir, "audit.log"), maxBytes=50 * 1024 * 1024, backupCount=5,
    )
    handler.setFormatter(_JsonFormatter())
    _logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(_JsonFormatter())
    _logger.addHandler(console)


def _emit(event_type: str, *, details: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
    _ensure_configured()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **kwargs,
    }
    if details:
        record["details"] = details
    _logger.info(json.dumps(record, default=str))


class _AuditEmitter:
    """Namespace of typed audit event helpers."""

    @staticmethod
    def code_execution_started(
        *, user_id: str = "", session_id: str = "", execution_id: str = "",
        node_id: str = "", node_label: str = "",
    ) -> None:
        _emit(
            "code_execution.started",
            user_id=user_id, session_id=session_id,
            execution_id=execution_id, node_id=node_id, node_label=node_label,
        )

    @staticmethod
    def code_execution_completed(
        *, user_id: str = "", session_id: str = "", execution_id: str = "",
        node_id: str = "", node_label: str = "",
        exit_code: int = 0, duration_ms: float = 0, output_type: str = "",
    ) -> None:
        _emit(
            "code_execution.completed",
            user_id=user_id, session_id=session_id,
            execution_id=execution_id, node_id=node_id, node_label=node_label,
            details={
                "exit_code": exit_code,
                "duration_ms": round(duration_ms, 1),
                "output_type": output_type,
            },
        )

    @staticmethod
    def code_execution_failed(
        *, user_id: str = "", session_id: str = "", execution_id: str = "",
        node_id: str = "", node_label: str = "",
        error: str = "", exit_code: int = -1, duration_ms: float = 0,
    ) -> None:
        _emit(
            "code_execution.failed",
            user_id=user_id, session_id=session_id,
            execution_id=execution_id, node_id=node_id, node_label=node_label,
            details={"error": error, "exit_code": exit_code, "duration_ms": round(duration_ms, 1)},
        )

    @staticmethod
    def code_validation_failed(
        *, user_id: str = "", session_id: str = "", execution_id: str = "",
        node_id: str = "", node_label: str = "",
        violations: list[str] | None = None,
    ) -> None:
        _emit(
            "code_execution.validation_failed",
            user_id=user_id, session_id=session_id,
            execution_id=execution_id, node_id=node_id, node_label=node_label,
            details={"violations": violations or []},
        )

    @staticmethod
    def sandbox_created(
        *, execution_id: str = "", sandbox_id: str = "", provider: str = "",
    ) -> None:
        _emit(
            "sandbox.created",
            execution_id=execution_id,
            details={"sandbox_id": sandbox_id, "provider": provider},
        )

    @staticmethod
    def sandbox_destroyed(
        *, execution_id: str = "", sandbox_id: str = "", provider: str = "",
    ) -> None:
        _emit(
            "sandbox.destroyed",
            execution_id=execution_id,
            details={"sandbox_id": sandbox_id, "provider": provider},
        )


audit = _AuditEmitter()
