"""
Docker-based sandbox implementation.

Each sandbox is a short-lived container with:
  - CPU / memory / PID limits
  - Bridge networking with a single whitelisted DNS (GenAI proxy)
  - Read-only root FS, writable /workspace and /outputs
  - A pre-installed agent_studio SDK
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

from .exceptions import (
    SandboxError,
    SandboxResourceError,
    SandboxTimeoutError,
)
from .sandbox import ExecutionResult, OnOutputCallback, Sandbox

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "agent-studio-sandbox:latest"
MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MB


def _resolve_kb_callback_host() -> tuple[str, str] | None:
    """Parse the configured KB callback URL into ``(hostname, ip_or_gateway)``.

    The sandbox runs with ``dns=["127.0.0.1"]`` which blocks DNS lookups,
    so any hostname the sandbox is expected to reach (in this case the
    host's KB API) has to be installed as a static ``/etc/hosts`` entry
    via Docker's ``extra_hosts``.

    For ``host.docker.internal`` we map to ``host-gateway`` (Docker's
    built-in sentinel that resolves to the Docker-Desktop gateway IP).
    For any other hostname we resolve via the usual DNS on the host.
    """
    try:
        from config.keyvault import cfg
        url = getattr(cfg, "SANDBOX_HOST_CALLBACK_URL", None)
    except Exception:
        url = None

    if not url:
        return None

    parsed = urlparse(str(url))
    hostname = parsed.hostname or ""
    if not hostname:
        return None

    if hostname == "host.docker.internal":
        return hostname, "host-gateway"

    try:
        ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        logger.warning("DNS resolution failed for KB callback host %s", hostname)
        return None

    return hostname, ip


def _resolve_proxy_host() -> tuple[str, str, str, str] | None:
    """Resolve the GenAI proxy URL into (base_url, hostname, ip, api_key).

    Returns None when the proxy is not configured.
    """
    proxy_url: str | None = None
    api_key: str | None = None

    try:
        from config.keyvault import cfg
        proxy_url = getattr(cfg, "GENAI_PROXY_URL", None)
        api_key = getattr(cfg, "GENAI_PROXY_API_KEY", None)
    except Exception as exc:
        logger.warning("Failed to read GenAI proxy config: %s", exc)

    if not proxy_url or not api_key:
        logger.warning(
            "GenAI proxy not configured — sandbox will have no network "
            "(GENAI_PROXY_URL=%s, API_KEY=%s)",
            "set" if proxy_url else "missing",
            "set" if api_key else "missing",
        )
        return None

    parsed = urlparse(proxy_url)
    hostname = parsed.hostname or ""
    if not hostname:
        logger.warning("Could not parse hostname from GENAI_PROXY_URL=%s", proxy_url)
        return None

    try:
        ip = socket.gethostbyname(hostname)
    except socket.gaierror:
        logger.warning("DNS resolution failed for proxy hostname %s", hostname)
        return None

    logger.info("Resolved GenAI proxy: %s → %s", hostname, ip)
    return proxy_url, hostname, ip, api_key

# Wrapper injected before user code so that ``inputs`` and the SDK output
# path are available without any boilerplate from the user.
_BOOTSTRAP = """\
import json as _json, sys as _sys

# Load inputs injected by the host
try:
    with open("/workspace/_inputs.json") as _f:
        inputs = _json.load(_f)
except FileNotFoundError:
    inputs = {}

# Make inputs accessible to the SDK (for output.ask() resume check)
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


class DockerSandbox(Sandbox):
    """Wraps a single Docker container."""

    def __init__(
        self,
        sandbox_id: str,
        *,
        cpu_count: float = 1.0,
        mem_limit: str = "512m",
        pids_limit: int = 100,
        image: str = SANDBOX_IMAGE,
    ):
        super().__init__(sandbox_id)
        self._cpu = cpu_count
        self._mem = mem_limit
        self._pids = pids_limit
        self._image = image
        self._container: Any | None = None
        self._client: Any | None = None

    async def _ensure_container(self) -> Any:
        """Lazily create the Docker container on first use.

        Networking strategy:
        - If the GenAI proxy is configured, use bridge mode with a single
          ``/etc/hosts`` entry so that *only* the proxy hostname resolves.
          ``dns=["127.0.0.1"]`` prevents any other DNS lookups.
        - Otherwise, fall back to ``network_mode="none"`` (fully isolated).
        """
        if self._container is not None:
            return self._container

        import docker  # type: ignore[import-untyped]

        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(None, docker.from_env)

        proxy_info = _resolve_proxy_host()
        kb_host = _resolve_kb_callback_host()

        def _create():
            kwargs: dict[str, Any] = dict(
                image=self._image,
                command="sleep infinity",
                detach=True,
                name=f"sandbox-{self._id}",
                cpu_count=int(self._cpu),
                mem_limit=self._mem,
                pids_limit=self._pids,
                read_only=True,
                tmpfs={
                    "/workspace": "size=1G,uid=1000",
                    "/outputs": "size=256M,uid=1000",
                    "/tmp": "size=256M,uid=1000",
                },
                working_dir="/workspace",
                user="1000:1000",
                labels={"managed-by": "agent-studio-sandbox"},
            )

            extra_hosts: dict[str, str] = {}
            env_vars: dict[str, str] = {}

            if proxy_info:
                base_url, hostname, ip, api_key = proxy_info
                extra_hosts[hostname] = ip
                env_vars["AGENT_STUDIO_LLM_URL"] = base_url
                env_vars["AGENT_STUDIO_LLM_KEY"] = api_key

            if kb_host:
                kb_hostname, kb_ip = kb_host
                extra_hosts.setdefault(kb_hostname, kb_ip)

            if extra_hosts:
                kwargs["network_mode"] = "bridge"
                kwargs["dns"] = ["127.0.0.1"]
                kwargs["extra_hosts"] = extra_hosts
                if env_vars:
                    kwargs["environment"] = env_vars
                logger.info(
                    "Sandbox %s: bridge network, extra_hosts=%s",
                    self._id,
                    ", ".join(f"{h}->{ip}" for h, ip in extra_hosts.items()),
                )
            else:
                kwargs["network_mode"] = "none"
                logger.info("Sandbox %s: no network (proxy not configured)", self._id)

            return self._client.containers.run(**kwargs)

        self._container = await loop.run_in_executor(None, _create)
        logger.info("Created sandbox container %s (%s)", self._id, self._container.short_id)
        return self._container

    async def execute_code(
        self,
        code: str,
        inputs: dict[str, Any] | None = None,
        timeout: int = 120,
        on_stdout: OnOutputCallback = None,
        on_stderr: OnOutputCallback = None,
    ) -> ExecutionResult:
        container = await self._ensure_container()
        loop = asyncio.get_running_loop()
        start = time.monotonic()

        # Inject inputs as JSON file
        inputs_json = json.dumps(inputs or {}, default=str)
        await self._exec(container, f"cat > /workspace/_inputs.json << 'AGENT_STUDIO_EOF'\n{inputs_json}\nAGENT_STUDIO_EOF")

        # Build the full script
        full_script = _BOOTSTRAP + code + _EPILOGUE
        await self._exec(container, f"cat > /workspace/_script.py << 'AGENT_STUDIO_EOF'\n{full_script}\nAGENT_STUDIO_EOF")

        # Extra env vars registered via set_env_var() (e.g. the KB session
        # credentials) are merged into the user script's environment here.
        # They are NEVER written to disk: Docker's exec API accepts them as
        # a per-exec parameter, so user code sees them only inside this
        # single subprocess.
        extra_env = dict(self._extra_env) if self._extra_env else None

        try:
            if on_stdout or on_stderr:
                exit_code, stdout, stderr = await asyncio.wait_for(
                    self._run_streaming(container, on_stdout, on_stderr, env=extra_env),
                    timeout=timeout,
                )
            else:
                exit_code, stdout, stderr = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._run_in_container(
                            container, "python /workspace/_script.py", env=extra_env,
                        ),
                    ),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            await loop.run_in_executor(None, lambda: container.exec_run("kill -9 -1"))
            raise SandboxTimeoutError(timeout)

        elapsed = (time.monotonic() - start) * 1000

        # Cap output size
        if len(stdout) > MAX_OUTPUT_BYTES:
            stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... (output truncated at 10 MB)"
        if len(stderr) > MAX_OUTPUT_BYTES:
            stderr = stderr[:MAX_OUTPUT_BYTES] + "\n... (stderr truncated at 10 MB)"

        # Read structured SDK output
        structured_output = await self._read_sdk_output(container)

        # If exit 42 (midway pause), read the pause request + checkpoint
        checkpoint_data: bytes | None = None
        if exit_code == 42:
            structured_output = await self._read_pause_request(container) or structured_output
            checkpoint_data = await self._read_checkpoint(container)

        # List output files
        output_files = await self._list_outputs(container)

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
        container = await self._ensure_container()
        loop = asyncio.get_running_loop()

        def _read():
            bits, _ = container.get_archive(path)
            import tarfile, io
            stream = io.BytesIO()
            for chunk in bits:
                stream.write(chunk)
            stream.seek(0)
            with tarfile.open(fileobj=stream) as tar:
                member = tar.getmembers()[0]
                f = tar.extractfile(member)
                return f.read() if f else b""

        return await loop.run_in_executor(None, _read)

    async def write_file(self, path: str, content: bytes) -> None:
        container = await self._ensure_container()
        loop = asyncio.get_running_loop()

        def _write():
            import tarfile, io
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as tar:
                info = tarfile.TarInfo(name=path.rsplit("/", 1)[-1])
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
            stream.seek(0)
            directory = path.rsplit("/", 1)[0] if "/" in path else "/workspace"
            container.put_archive(directory, stream)

        await loop.run_in_executor(None, _write)

    async def list_files(self, path: str = "/workspace") -> list[str]:
        container = await self._ensure_container()
        loop = asyncio.get_running_loop()

        def _ls():
            exit_code, output = container.exec_run(f"find {path} -maxdepth 2 -type f")
            if exit_code != 0:
                return []
            return [line for line in output.decode().strip().split("\n") if line]

        return await loop.run_in_executor(None, _ls)

    async def extract_output_files(self, dest_dir: str) -> list[dict[str, str]]:
        """Extract output files using exec_run + base64 (more reliable than get_archive)."""
        import base64, os

        container = await self._ensure_container()
        loop = asyncio.get_running_loop()

        files = await self.list_files("/outputs")
        extracted: list[dict[str, str]] = []

        for fpath in files:
            basename = fpath.rsplit("/", 1)[-1]
            if basename.startswith("_"):
                continue
            try:
                def _read_b64(p=fpath):
                    ec, out = container.exec_run(f"base64 '{p}'")
                    if ec != 0:
                        logger.warning("base64 read failed for %s (exit %d)", p, ec)
                        return None
                    return base64.b64decode(out)

                data = await loop.run_in_executor(None, _read_b64)
                if data is None:
                    continue

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
        if self._container is not None:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, lambda: self._container.remove(force=True))
                logger.info("Removed sandbox container %s", self._id)
            except Exception as exc:
                logger.warning("Failed to remove container %s: %s", self._id, exc)
            finally:
                self._container = None

    async def health_check(self) -> bool:
        """Confirm the container still exists and is runnable."""
        if self._container is None:
            return False
        loop = asyncio.get_running_loop()
        try:
            def _check() -> bool:
                self._container.reload()
                return self._container.status in {"running", "created"}
            return await loop.run_in_executor(None, _check)
        except Exception as exc:
            logger.warning("Docker sandbox %s health check failed: %s", self._id, exc)
            return False

    async def wash(self, *, timeout: int = 15) -> bool:
        """Reset the container for reuse.

        Wipes /workspace and /outputs (both are tmpfs mounts — cheap) and
        clears any per-run env vars.  Returns True if the container is
        safe to reuse.
        """
        self._extra_env.clear()

        if self._container is None:
            return False

        loop = asyncio.get_running_loop()
        try:
            def _wipe():
                self._container.exec_run(
                    "sh -c 'rm -rf /workspace/* /workspace/.[!.]* "
                    "/outputs/* /outputs/.[!.]* 2>/dev/null; "
                    "mkdir -p /workspace/uploads; exit 0'"
                )

            await asyncio.wait_for(
                loop.run_in_executor(None, _wipe),
                timeout=timeout,
            )
            if not await self.health_check():
                return False
            return True
        except Exception as exc:
            logger.warning("Docker wash on %s failed: %s", self._id, exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_streaming(
        self,
        container: Any,
        on_stdout: OnOutputCallback,
        on_stderr: OnOutputCallback,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Execute the script with line-by-line streaming via the low-level
        Docker API so we can reliably retrieve the exit code afterwards."""
        loop = asyncio.get_running_loop()
        api = container.client.api

        def _create_and_start():
            exec_kwargs: dict[str, Any] = dict(
                workdir="/workspace",
                stdout=True, stderr=True,
            )
            if env:
                exec_kwargs["environment"] = env
            exec_obj = api.exec_create(
                container.id,
                "python /workspace/_script.py",
                **exec_kwargs,
            )
            exec_id = exec_obj["Id"]
            stream = api.exec_start(exec_id, stream=True, demux=True)
            return exec_id, stream

        exec_id, stream = await loop.run_in_executor(None, _create_and_start)

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        def _iter_chunks():
            chunks = []
            for stdout_chunk, stderr_chunk in stream:
                chunks.append((
                    stdout_chunk.decode(errors="replace") if stdout_chunk else "",
                    stderr_chunk.decode(errors="replace") if stderr_chunk else "",
                ))
            return chunks

        chunks = await loop.run_in_executor(None, _iter_chunks)

        for out_text, err_text in chunks:
            if out_text:
                stdout_parts.append(out_text)
                if on_stdout:
                    for line in out_text.splitlines(keepends=True):
                        await on_stdout(line.rstrip("\n\r"))
            if err_text:
                stderr_parts.append(err_text)
                if on_stderr:
                    for line in err_text.splitlines(keepends=True):
                        await on_stderr(line.rstrip("\n\r"))

        inspect = await loop.run_in_executor(None, lambda: api.exec_inspect(exec_id))
        exit_code = inspect.get("ExitCode", 0)

        return exit_code, "".join(stdout_parts), "".join(stderr_parts)

    @staticmethod
    def _run_in_container(
        container: Any,
        cmd: str,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Synchronous exec inside the container. Returns (exit_code, stdout, stderr)."""
        exec_kwargs: dict[str, Any] = {"demux": True, "workdir": "/workspace"}
        if env:
            exec_kwargs["environment"] = env
        result = container.exec_run(cmd, **exec_kwargs)
        exit_code = result.exit_code
        stdout = (result.output[0] or b"").decode(errors="replace") if isinstance(result.output, tuple) else (result.output or b"").decode(errors="replace")
        stderr = (result.output[1] or b"").decode(errors="replace") if isinstance(result.output, tuple) else ""
        return exit_code, stdout, stderr

    async def _exec(self, container: Any, cmd: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: container.exec_run(["sh", "-c", cmd], workdir="/workspace"),
        )

    async def _read_pause_request(self, container: Any) -> dict[str, Any] | None:
        """Read /outputs/_pause.json written by output.ask() using exec_run cat."""
        loop = asyncio.get_running_loop()

        def _read():
            exit_code, out = container.exec_run("cat /outputs/_pause.json")
            if exit_code != 0:
                return None
            try:
                return json.loads(out.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None

        return await loop.run_in_executor(None, _read)

    async def _read_checkpoint(self, container: Any) -> bytes | None:
        """Read /outputs/_checkpoint.pkl written by the SDK before a pause."""
        loop = asyncio.get_running_loop()

        def _read():
            import base64 as _b64
            exit_code, out = container.exec_run("base64 /outputs/_checkpoint.pkl")
            if exit_code != 0:
                return None
            try:
                return _b64.b64decode(out)
            except Exception:
                return None

        data = await loop.run_in_executor(None, _read)
        if data:
            logger.info("Read checkpoint from sandbox (%d bytes)", len(data))
        return data

    async def _read_sdk_output(self, container: Any) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()

        def _read():
            exit_code, out = container.exec_run("cat /outputs/_result.json")
            if exit_code != 0:
                return None
            try:
                return json.loads(out.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None

        return await loop.run_in_executor(None, _read)

    async def _list_outputs(self, container: Any) -> list[str]:
        loop = asyncio.get_running_loop()

        def _ls():
            exit_code, out = container.exec_run("find /outputs -maxdepth 2 -type f -not -name '_result.json'")
            if exit_code != 0:
                return []
            return [l for l in out.decode().strip().split("\n") if l]

        return await loop.run_in_executor(None, _ls)
