"""
ACI-based sandbox implementation — HTTP command server variant.

Communicates with a lightweight HTTP server running inside the ACI
container over the private VNet.  This avoids Azure's exec WebSocket
relay (port 19390) which is blocked by corporate firewalls.

Traffic path:
    ACA backend (10.66.170.x) → NVA → ACI container (10.66.142.x:443)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

from .exceptions import SandboxError, SandboxTimeoutError
from .sandbox import ExecutionResult, Sandbox

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MB
SANDBOX_PORT = 443

_BOOTSTRAP = """\
import json as _json, sys as _sys

try:
    with open("/workspace/_inputs.json") as _f:
        inputs = _json.load(_f)
except FileNotFoundError:
    inputs = {}

import builtins as _builtins
_builtins._agent_studio_inputs = inputs

# Restore checkpoint if available (resume after output.ask() pause)
_checkpoint_vars = None
try:
    from agent_studio._checkpoint import restore_checkpoint as _restore_cp
    _checkpoint_vars = _restore_cp()
    if _checkpoint_vars:
        globals().update(_checkpoint_vars)
except Exception:
    pass

# ---- user code starts below ----
"""

_EPILOGUE = """
# ---- user code ends above ----
"""


class AciSandbox(Sandbox):
    """Wraps a single Azure Container Instance container group.

    All interaction happens over HTTP to the sandbox_server running
    inside the container on port 443.
    """

    def __init__(
        self,
        sandbox_id: str,
        *,
        resource_group: str,
        container_group_name: str,
        container_name: str = "sandbox",
        aci_client: Any = None,
        container_ip: str = "",
    ):
        super().__init__(sandbox_id)
        self._rg = resource_group
        self._cg_name = container_group_name
        self._container_name = container_name
        self._aci_client = aci_client
        self._base_url = f"http://{container_ip}:{SANDBOX_PORT}"

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: dict, *, timeout: int = 60) -> dict:
        """POST JSON to the sandbox HTTP server."""
        import aiohttp

        url = f"{self._base_url}{path}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    return await resp.json()
        except asyncio.TimeoutError:
            raise SandboxTimeoutError(timeout)
        except Exception as exc:
            raise SandboxError(f"HTTP request to sandbox failed: {exc}")

    async def _get(self, path: str, *, timeout: int = 10) -> dict:
        import aiohttp

        url = f"{self._base_url}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                return await resp.json()

    async def _exec_command(self, command: str, *, timeout: int = 60) -> tuple[int, str, str]:
        """Run a shell command inside the container via the HTTP server."""
        result = await self._post("/exec", {"command": command, "timeout": timeout}, timeout=timeout + 5)
        return (
            result.get("exit_code", -1),
            result.get("stdout", ""),
            result.get("stderr", ""),
        )

    async def _write_file(self, container_path: str, content: str | bytes) -> None:
        if isinstance(content, str):
            content = content.encode()
        b64 = base64.b64encode(content).decode()
        await self._post("/write", {"path": container_path, "b64": b64}, timeout=30)

    async def _read_file_text(self, container_path: str) -> str:
        result = await self._post("/read-text", {"path": container_path}, timeout=30)
        return result.get("text", "")

    async def _read_file_bytes(self, container_path: str) -> bytes:
        result = await self._post("/read", {"path": container_path}, timeout=30)
        return base64.b64decode(result.get("b64", ""))

    async def _list_files(self, container_path: str) -> list[str]:
        result = await self._post("/list", {"path": container_path}, timeout=15)
        return result.get("files", [])

    # ------------------------------------------------------------------
    # Sandbox ABC implementation
    # ------------------------------------------------------------------

    async def execute_code(
        self,
        code: str,
        inputs: dict[str, Any] | None = None,
        timeout: int = 120,
        on_stdout=None,
        on_stderr=None,
    ) -> ExecutionResult:
        start = time.monotonic()

        inputs_json = json.dumps(inputs or {}, default=str)
        await self._write_file("/workspace/_inputs.json", inputs_json)

        full_script = _BOOTSTRAP + code + _EPILOGUE
        await self._write_file("/workspace/_script.py", full_script)

        # Forward per-run env vars (e.g. KB session credentials) into the
        # user script's shell subprocess.  Never written to disk.
        env_prefix = ""
        if self._extra_env:
            import shlex as _shlex
            env_prefix = " ".join(
                f"{k}={_shlex.quote(v)}" for k, v in self._extra_env.items()
            ) + " "

        try:
            run_cmd = (
                f"{env_prefix}python /workspace/_script.py 2>/outputs/_stderr.log; "
                'echo "$?" > /outputs/_exit_code'
            )
            _, stdout, _ = await self._exec_command(run_cmd, timeout=timeout)
        except SandboxTimeoutError:
            try:
                await self._exec_command("kill -9 -1", timeout=5)
            except Exception:
                pass
            raise

        exit_code = 0
        try:
            ec_raw = await self._read_file_text("/outputs/_exit_code")
            exit_code = int(ec_raw.strip())
        except Exception:
            pass

        stderr = ""
        try:
            stderr = await self._read_file_text("/outputs/_stderr.log")
        except Exception:
            pass

        elapsed = (time.monotonic() - start) * 1000

        if len(stdout) > MAX_OUTPUT_BYTES:
            stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... (output truncated at 10 MB)"
        if len(stderr) > MAX_OUTPUT_BYTES:
            stderr = stderr[:MAX_OUTPUT_BYTES] + "\n... (stderr truncated at 10 MB)"

        structured_output = await self._read_sdk_output()

        checkpoint_data: bytes | None = None
        if exit_code == 42:
            structured_output = await self._read_pause_request() or structured_output
            checkpoint_data = await self._read_checkpoint()

        output_files = await self._list_output_names()

        return ExecutionResult(
            success=exit_code == 0,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            output=structured_output,
            output_files=output_files,
            duration_ms=elapsed,
            error=stderr if exit_code != 0 else None,
            checkpoint_data=checkpoint_data,
        )

    async def read_file(self, path: str) -> bytes:
        return await self._read_file_bytes(path)

    async def write_file(self, path: str, content: bytes) -> None:
        await self._write_file(path, content)

    async def list_files(self, path: str = "/workspace") -> list[str]:
        return await self._list_files(path)

    async def extract_output_files(self, dest_dir: str) -> list[dict[str, str]]:
        files = await self.list_files("/outputs")
        extracted: list[dict[str, str]] = []

        for fpath in files:
            basename = fpath.rsplit("/", 1)[-1]
            if basename.startswith("_"):
                continue
            try:
                data = await self.read_file(fpath)
                os.makedirs(dest_dir, exist_ok=True)
                local = os.path.join(dest_dir, basename)
                with open(local, "wb") as f:
                    f.write(data)
                extracted.append({"sandbox_path": fpath, "local_path": local, "name": basename})
                logger.debug("Extracted output file %s (%d bytes)", basename, len(data))
            except Exception as exc:
                logger.warning("Failed to extract %s: %s", fpath, exc)

        return extracted

    async def cleanup(self) -> None:
        """Delete the ACI container group."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self._aci_client.container_groups.begin_delete(
                    self._rg, self._cg_name,
                ).result(),
            )
            logger.info("Deleted ACI container group %s", self._cg_name)
        except Exception as exc:
            logger.warning("Failed to delete ACI group %s: %s", self._cg_name, exc)

    async def health_check(self) -> bool:
        """Ping the sandbox HTTP command server.

        Verifies the container is alive AND the server process inside it
        is responsive.  Used before reusing a pooled / reclaimed sandbox
        to avoid handing a dead container to a new workflow.
        """
        try:
            result = await self._get("/health", timeout=5)
            return bool(result.get("ok", False)) or result is not None
        except Exception:
            try:
                exit_code, _, _ = await self._exec_command("true", timeout=5)
                return exit_code == 0
            except Exception as exc:
                logger.warning(
                    "ACI sandbox %s health check failed: %s",
                    self._cg_name, exc,
                )
                return False

    async def wash(self, *, timeout: int = 15) -> bool:
        """Reset the container for reuse by the next workflow.

        Wipes ``/workspace`` and ``/outputs`` (user code, uploads, SDK
        output, checkpoint, inputs file), clears any per-run env vars,
        then health-checks the server.  All three steps must succeed for
        this sandbox to be safe to hand to another user.

        Returns True on a clean wash.  On any failure the provider must
        destroy the container instead of returning it to the pool — data
        leakage between tenants is not acceptable.
        """
        self._extra_env.clear()

        wash_cmd = (
            "rm -rf /workspace/* /workspace/.[!.]* /outputs/* /outputs/.[!.]* "
            "2>/dev/null; mkdir -p /workspace/uploads; true"
        )
        try:
            exit_code, _, stderr = await self._exec_command(wash_cmd, timeout=timeout)
            if exit_code != 0:
                logger.warning(
                    "Wash cycle on %s returned exit %d: %s",
                    self._cg_name, exit_code, (stderr or "")[:200],
                )
                return False
        except Exception as exc:
            logger.warning("Wash cycle on %s failed: %s", self._cg_name, exc)
            return False

        if not await self.health_check():
            logger.warning("Wash cycle on %s: health check failed post-clean", self._cg_name)
            return False

        logger.info("Washed container %s — ready for reuse", self._cg_name)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _read_checkpoint(self) -> bytes | None:
        """Read /outputs/_checkpoint.pkl written by the SDK before a pause."""
        try:
            data = await self._read_file_bytes("/outputs/_checkpoint.pkl")
            if data:
                logger.info("Read checkpoint from ACI sandbox (%d bytes)", len(data))
                return data
            return None
        except Exception:
            return None

    async def _read_sdk_output(self) -> dict[str, Any] | None:
        try:
            raw = await self._read_file_text("/outputs/_result.json")
            return json.loads(raw)
        except (Exception, json.JSONDecodeError):
            return None

    async def _read_pause_request(self) -> dict[str, Any] | None:
        try:
            raw = await self._read_file_text("/outputs/_pause.json")
            return json.loads(raw)
        except (Exception, json.JSONDecodeError):
            return None

    async def _list_output_names(self) -> list[str]:
        files = await self.list_files("/outputs")
        return [f for f in files if not f.rsplit("/", 1)[-1].startswith("_")]
