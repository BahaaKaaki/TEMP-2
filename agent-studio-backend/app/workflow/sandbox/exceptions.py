"""Sandbox exception hierarchy."""


class SandboxError(Exception):
    """Base exception for all sandbox-related errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SandboxNotFoundError(SandboxError):
    """Raised when a sandbox cannot be found or acquired."""

    def __init__(self, message: str = "Sandbox not found", sandbox_id: str | None = None):
        super().__init__(message, {"sandbox_id": sandbox_id} if sandbox_id else None)
        self.sandbox_id = sandbox_id


class SandboxTimeoutError(SandboxError):
    """Raised when code execution exceeds the configured timeout."""

    def __init__(self, timeout_seconds: int, message: str | None = None):
        msg = message or f"Code execution exceeded {timeout_seconds}s timeout"
        super().__init__(msg, {"timeout_seconds": timeout_seconds})
        self.timeout_seconds = timeout_seconds


class SandboxPermissionError(SandboxError):
    """Raised when code attempts a forbidden operation."""
    pass


class SandboxResourceError(SandboxError):
    """Raised when a sandbox hits resource limits (OOM, disk, PIDs)."""
    pass


class CodeValidationError(SandboxError):
    """Raised when code fails static validation (e.g. blocked imports)."""

    def __init__(self, message: str, violations: list[str] | None = None):
        super().__init__(message, {"violations": violations or []})
        self.violations = violations or []
