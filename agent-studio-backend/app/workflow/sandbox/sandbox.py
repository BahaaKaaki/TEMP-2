"""
Abstract sandbox interface.

Every sandbox backend (Docker, future microVM, etc.) implements this
contract so that the CodeExecutorNode is decoupled from isolation details.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

OnOutputCallback = Optional[Callable[[str], Awaitable[None]]]


@dataclass
class ExecutionResult:
    """Result returned after running code inside a sandbox."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    output: dict[str, Any] | None = None
    output_files: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    checkpoint_data: bytes | None = None


class Sandbox(ABC):
    """Abstract base class for sandbox environments."""

    _id: str

    def __init__(self, sandbox_id: str):
        self._id = sandbox_id
        # Extra env vars to forward into the user script at execute_code time.
        # Set by the node via set_env_var() before execute_code runs.  Nothing
        # here is ever written to disk.
        self._extra_env: dict[str, str] = {}

    @property
    def id(self) -> str:
        return self._id

    def set_env_var(self, key: str, value: str) -> None:
        """Register a per-run env var the user script will see at runtime.

        Values are merged into the subprocess environment only when
        ``execute_code`` launches the user script; they are never written
        to disk and are scoped to this sandbox instance.
        """
        if not key:
            return
        self._extra_env[str(key)] = str(value if value is not None else "")

    def clear_env_var(self, key: str) -> None:
        """Remove a previously-registered env var."""
        self._extra_env.pop(key, None)

    @property
    def extra_env(self) -> dict[str, str]:
        """Read-only view of the per-run env vars (copy)."""
        return dict(self._extra_env)

    @abstractmethod
    async def execute_code(
        self,
        code: str,
        inputs: dict[str, Any] | None = None,
        timeout: int = 120,
        on_stdout: OnOutputCallback = None,
        on_stderr: OnOutputCallback = None,
    ) -> ExecutionResult:
        """Run Python code inside the sandbox.

        Args:
            code: Python source code to execute.
            inputs: JSON-serialisable dict injected as ``inputs`` variable.
            timeout: Maximum wall-clock seconds before the run is killed.
            on_stdout: Async callback invoked with each stdout line/chunk.
            on_stderr: Async callback invoked with each stderr line/chunk.

        Returns:
            An ``ExecutionResult`` with stdout, structured output, files, etc.
        """
        ...

    @abstractmethod
    async def read_file(self, path: str) -> bytes:
        """Read a file from the sandbox filesystem."""
        ...

    @abstractmethod
    async def write_file(self, path: str, content: bytes) -> None:
        """Write a file into the sandbox filesystem."""
        ...

    @abstractmethod
    async def list_files(self, path: str = "/workspace") -> list[str]:
        """List files under *path* inside the sandbox."""
        ...

    async def extract_output_files(self, dest_dir: str) -> list[dict[str, str]]:
        """Extract all files from /outputs/ to *dest_dir*.

        Returns a list of ``{"sandbox_path": ..., "local_path": ..., "name": ...}``.
        Default implementation uses ``read_file`` + ``list_files``.
        """
        import os
        files = await self.list_files("/outputs")
        extracted = []
        for fpath in files:
            if fpath.endswith("/_result.json") or fpath.endswith("/_pause.json"):
                continue
            try:
                data = await self.read_file(fpath)
                name = fpath.rsplit("/", 1)[-1]
                local = os.path.join(dest_dir, name)
                os.makedirs(dest_dir, exist_ok=True)
                with open(local, "wb") as f:
                    f.write(data)
                extracted.append({"sandbox_path": fpath, "local_path": local, "name": name})
            except Exception:
                pass
        return extracted

    @abstractmethod
    async def cleanup(self) -> None:
        """Release all resources held by this sandbox instance."""
        ...

    async def health_check(self) -> bool:
        """Verify the sandbox is still reachable and responsive.

        Used before reusing a sandbox from the warm pool or after a pause
        reservation to catch crashed/unresponsive containers.  Default
        implementation returns True; providers that support health checks
        should override.
        """
        return True

    async def wash(self, *, timeout: int = 15) -> bool:
        """Reset sandbox state so it can be safely reused for another workflow.

        Clears /workspace and /outputs, drops per-run env vars, and confirms
        the underlying command server / process is still responsive.

        Returns True if the wash succeeded (sandbox is clean and ready to
        return to the warm pool).  Returns False if anything went wrong —
        the caller must then destroy the sandbox rather than reuse it.

        Default implementation only clears in-memory env vars (safe no-op
        for simple providers that always destroy on release).
        """
        self._extra_env.clear()
        return True
