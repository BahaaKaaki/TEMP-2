"""
Sandbox infrastructure for secure code execution.

Provides Docker-isolated (local) or ACI-isolated (production) environments
where user/LLM-generated Python code runs with resource limits, network
isolation, and import restrictions.
"""

from .sandbox import Sandbox, ExecutionResult
from .sandbox_provider import SandboxProvider, get_sandbox_provider
from .code_validator import CodeValidator, ValidationResult
from .exceptions import (
    SandboxError,
    SandboxTimeoutError,
    SandboxNotFoundError,
    SandboxPermissionError,
    SandboxResourceError,
    CodeValidationError,
)

__all__ = [
    "Sandbox",
    "ExecutionResult",
    "SandboxProvider",
    "get_sandbox_provider",
    "CodeValidator",
    "ValidationResult",
    "SandboxError",
    "SandboxTimeoutError",
    "SandboxNotFoundError",
    "SandboxPermissionError",
    "SandboxResourceError",
    "CodeValidationError",
]
