"""
Code Executor node -- deterministic, sandboxed Python execution.

Runs user-authored or LLM-generated Python code inside a Docker sandbox
and emits typed deliverables (data, table, chart, file, widget).

Key differences from agent nodes:
  - No LLM in the loop -- execution is deterministic.
  - Inputs come from upstream deliverables / node outputs / runtime user form.
  - Outputs are typed via the ``agent_studio`` SDK.
  - Can optionally pause the workflow for interactive widget responses.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage

from .base import BaseNode
from ..state import WorkflowState, resolve_deliverable_sources

_audit_cache = None
def _get_audit():
    global _audit_cache
    if _audit_cache is None:
        from services.audit_service import audit as _a
        _audit_cache = _a
    return _audit_cache

OUTPUT_FILES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "sandbox_output_files"
)

logger = logging.getLogger(__name__)


class CodeExecutorNode(BaseNode):
    """Deterministic code execution in a Docker sandbox."""

    def _make_startup_message(self, text: str) -> AIMessage:
        """Build an AIMessage to show in the chat before execution."""
        return AIMessage(
            content=text,
            additional_kwargs={
                "message_id": str(uuid.uuid4()),
                "agent_id": self.node_id,
                "agent_label": self.label,
                "agent_type": "code-executor",
                "is_startup_message": True,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    async def execute(self, state: WorkflowState) -> Dict[str, Any]:
        # -----------------------------------------------------------------
        # 0. If we are resuming after a runtime-input pause, skip straight
        #    to the execution phase with the collected inputs.
        # -----------------------------------------------------------------
        if self._is_resume_after_input(state):
            return await self._execute_with_inputs(state)

        # Startup message: pause for user input when non-empty (may already
        # have been injected at session open via chat_service).
        from app.workflow.utils.startup import (
            get_startup_message_text,
            should_wait_for_startup,
        )

        emit_messages: List[AIMessage] = []
        node_config = self.node_config or {}
        startup_message = get_startup_message_text(node_config)

        if startup_message and should_wait_for_startup(node_config):
            messages = state.get("messages", [])
            node_outputs = state.get("node_outputs", {})
            startup_in_messages = any(
                getattr(m, "additional_kwargs", {}).get("agent_id") == self.node_id
                and (
                    getattr(m, "additional_kwargs", {}).get("is_startup_message")
                    or getattr(m, "additional_kwargs", {}).get("is_initial_message")
                )
                for m in messages
            )
            if node_outputs.get(self.node_id) is None and not startup_in_messages:
                emit_messages.append(self._make_startup_message(startup_message))
                return {
                    "interrupted": True,
                    "messages": emit_messages,
                    "has_deliverable": False,
                }

        # -----------------------------------------------------------------
        # 1. Resolve code
        # -----------------------------------------------------------------
        code = self._resolve_code(state)
        if code is None:
            return self._error("No code configured or found from upstream node")

        # -----------------------------------------------------------------
        # 2. Validate code (import whitelist + blocked calls)
        # -----------------------------------------------------------------
        from ..sandbox.code_validator import CodeValidator

        extra_allowed = self.get_config_value("allowedImports", [])
        validator = CodeValidator(extra_allowed_imports=extra_allowed)
        validation = validator.validate(code)
        if not validation.valid:
            _get_audit().code_validation_failed(
                execution_id=str(state.get("metadata", {}).get("execution_id", "")),
                node_id=self.node_id, node_label=self.label,
                violations=validation.violations,
            )
            return self._error(
                f"Code validation failed: {'; '.join(validation.violations)}"
            )

        # -----------------------------------------------------------------
        # 3. Resolve inputs from upstream nodes
        # -----------------------------------------------------------------
        inputs = self._resolve_inputs(state)

        # -----------------------------------------------------------------
        # 4. Check if runtime inputs are needed (pause like HITL)
        #    Runtime-input forms are a code-level intent: if the author
        #    defined a schema, the user is expected to fill it in before
        #    the script runs.  This pause is not bypassed by any node
        #    flag — the only way to skip it is to not define a schema.
        # -----------------------------------------------------------------
        runtime_schema = self.get_config_value("runtimeInputs", [])
        if runtime_schema and not state.get("user_input_response"):
            logger.info(
                "Code executor %s pausing for runtime inputs (%d field(s))",
                self.label, len(runtime_schema),
            )
            pause_result: Dict[str, Any] = {
                "interrupted": True,
                "pending_user_input": {
                    "node_id": self.node_id,
                    "type": "code_executor_runtime_input",
                    "fields": runtime_schema,
                    "resolved_inputs_snapshot": inputs,
                    "code": code,
                },
                "metadata": {
                    **state.get("metadata", {}),
                    "status": "paused",
                },
            }
            if emit_messages:
                pause_result["messages"] = emit_messages
            return pause_result

        # -----------------------------------------------------------------
        # 5. Run in sandbox
        # -----------------------------------------------------------------
        result = await self._run_sandbox(code, inputs, state)
        if emit_messages:
            result.setdefault("messages", [])
            result["messages"] = emit_messages + result["messages"]
        return result

    # =====================================================================
    # Resume helpers
    # =====================================================================

    def _is_resume_after_input(self, state: WorkflowState) -> bool:
        pending = state.get("pending_user_input")
        response = state.get("user_input_response")
        if not pending or not response:
            return False
        if pending.get("node_id") != self.node_id:
            return False
        return pending.get("type") in (
            "code_executor_runtime_input",
            "code_executor_midway_input",
        )

    async def _execute_with_inputs(self, state: WorkflowState) -> Dict[str, Any]:
        pending = state["pending_user_input"]
        user_response = state["user_input_response"]
        code = pending.get("code", "")
        inputs = pending.get("resolved_inputs_snapshot", {})

        if pending.get("type") == "code_executor_midway_input":
            pause_type = pending.get("pause_request", {}).get("type", "text")
            pause_index = pending.get("pause_request", {}).get("pause_index", 0)
            prior_responses: List[Any] = list(pending.get("pause_responses", []))
            pause_file_map: Dict[str, Dict[str, str]] = dict(
                pending.get("pause_file_map", {})
            )

            # Fast-path resume: if the pause reserved the original sandbox
            # and it's still alive, the provider can hand it back so we
            # skip file/checkpoint re-injection entirely.
            self._reclaim_target_id = pending.get("reserved_sandbox_id")

            # Slow-path fallback: checkpoint blob to replay globals into a
            # fresh sandbox when the reservation has expired or reclaim
            # fails for any reason.  Modern pauses store a pointer
            # ``checkpoint_blob`` into ADLS; rows written before the blob
            # migration may still carry an inline ``checkpoint_b64``
            # string in Postgres and we keep reading those until they
            # age out.
            self._checkpoint_blob: Optional[str] = pending.get("checkpoint_blob")
            self._checkpoint_b64: Optional[str] = (
                None if self._checkpoint_blob else pending.get("checkpoint_b64")
            )
            has_checkpoint = bool(self._checkpoint_blob or self._checkpoint_b64)
            if self._checkpoint_blob:
                logger.info(
                    "Resuming with checkpoint blob %s", self._checkpoint_blob,
                )
            elif self._checkpoint_b64:
                logger.info(
                    "Resuming with legacy inline checkpoint (%d b64 chars)",
                    len(self._checkpoint_b64),
                )

            logger.info(
                "Resuming code executor: pause_type=%s, pause_index=%d, "
                "prior_responses=%d, has_checkpoint=%s, user_response keys=%s",
                pause_type,
                pause_index,
                len(prior_responses),
                has_checkpoint,
                list(user_response.keys()) if isinstance(user_response, dict) else type(user_response).__name__,
            )

            # ── Fold the newly-arrived pause response into pause_file_map ──
            # The FE upload endpoint now returns ``blob_name`` instead of
            # a backend-local ``local_path``.  We still accept ``local_path``
            # on the read side (pauses paused before the deploy may carry
            # legacy entries) so nothing breaks mid-rollout.
            def _file_ref(src: Dict[str, Any]) -> Optional[Dict[str, str]]:
                fn = src.get("filename") or ""
                bn = src.get("blob_name") or ""
                lp = src.get("local_path") or ""
                if bn:
                    return {"filename": fn or "upload", "blob_name": bn}
                if lp and os.path.isfile(lp):
                    return {"filename": fn or "upload", "local_path": lp}
                return None

            new_response: Any
            if pause_type == "file" and isinstance(user_response, dict):
                multi_files = user_response.get("files")
                if multi_files and isinstance(multi_files, list):
                    # Multi-file upload: [{filename, blob_name|local_path, upload_id}, ...]
                    paths = []
                    for fi, finfo in enumerate(multi_files):
                        ref = _file_ref(finfo)
                        if ref is None:
                            logger.warning(
                                "Multi-file entry missing blob_name/local_path: %s",
                                finfo.get("filename"),
                            )
                            continue
                        key = f"{pause_index}_{fi}"
                        pause_file_map[key] = ref
                        paths.append(f"/workspace/uploads/{ref['filename']}")
                    logger.info("Multi-file resume: %d file(s)", len(paths))
                    new_response = {"value": paths}
                else:
                    # Single-file upload
                    ref = _file_ref(user_response)
                    if ref is not None:
                        pause_file_map[str(pause_index)] = ref
                    filename = (ref or {}).get("filename") or user_response.get("filename") or "upload"
                    logger.info(
                        "File resume: ref=%s, filename=%s", ref, filename,
                    )
                    new_response = {
                        "value": f"/workspace/uploads/{filename}",
                        "filename": filename,
                    }
            else:
                new_response = user_response

            prior_responses.append(new_response)
            inputs["pause_responses"] = prior_responses
            inputs["pause_response"] = new_response

            # Collect ALL file uploads from prior pauses for re-injection.
            # Each entry carries either a blob name (resolved via ADLS at
            # inject time) or a legacy local_path (read from backend pod
            # disk — only present for pauses issued before the blob
            # migration).
            self._midway_files: List[Dict[str, str]] = []
            for _idx, finfo in pause_file_map.items():
                fn = finfo.get("filename", "")
                if not fn:
                    continue
                if finfo.get("blob_name"):
                    self._midway_files.append({"filename": fn, "blob_name": finfo["blob_name"]})
                elif finfo.get("local_path") and os.path.isfile(finfo["local_path"]):
                    self._midway_files.append({"filename": fn, "local_path": finfo["local_path"]})
            self._pause_file_map = pause_file_map

            logger.info(
                "Multi-pause file map: %d file(s) to re-inject", len(self._midway_files)
            )
        else:
            inputs["runtime"] = user_response

        return await self._run_sandbox(code, inputs, state)

    # =====================================================================
    # Code resolution
    # =====================================================================

    def _resolve_code(self, state: WorkflowState) -> Optional[str]:
        return self.get_config_value("code")

    # =====================================================================
    # Input resolution
    # =====================================================================

    def _resolve_inputs(self, state: WorkflowState) -> Dict[str, Any]:
        """Build the ``inputs`` dict that gets injected into the sandbox.

        Always available inside the script:
            inputs["variables"]       - workflow variables
            inputs["workflow_input"]  - original user input
            inputs["deliverables"]    - list of approved upstream deliverables
            inputs["prev_output"]     - immediate predecessor node's output
            inputs["uploaded_files"]  - list of file paths in /workspace/uploads/
            inputs[<custom>]          - anything from inputMappings config
        """
        mappings: dict = self.get_config_value("inputMappings", {})
        inputs: Dict[str, Any] = {}

        for var_name, source_path in mappings.items():
            inputs[var_name] = self._resolve_source_path(source_path, state)

        inputs.setdefault("variables", state.get("variables", {}))
        inputs.setdefault("workflow_input", state.get("input_data", {}))

        approved = resolve_deliverable_sources(
            state, self.node_id, self.node_config or {}
        )
        inputs.setdefault("deliverables", [
            {
                "agent_label": d.get("agent_label"),
                "agent_type": d.get("agent_type"),
                "data": self._strip_internal(d.get("deliverable", {})),
            }
            for d in approved
        ])

        node_outputs = state.get("node_outputs", {})
        prev_output: Any = None
        for nid, nout in reversed(list(node_outputs.items())):
            if nid == self.node_id:
                continue
            out = nout.get("output", {}) if isinstance(nout, dict) else {}
            if out:
                prev_output = {
                    "node_id": nid,
                    "response": out.get("response"),
                    "deliverable": self._strip_internal(out.get("deliverable")),
                }
                break
        inputs.setdefault("prev_output", prev_output)

        inputs.setdefault("uploaded_files", [])

        return inputs

    def _resolve_source_path(self, path: str, state: WorkflowState) -> Any:
        """Resolve ``node.<id>.deliverable``, ``variables.<key>``, etc."""
        parts = path.split(".")
        if not parts:
            return None

        root = parts[0]

        if root == "node" and len(parts) >= 2:
            node_id = parts[1]
            node_output = state.get("node_outputs", {}).get(node_id, {})
            obj: Any = node_output.get("output", {})
            for key in parts[2:]:
                if isinstance(obj, dict):
                    obj = obj.get(key)
                else:
                    return None
            return obj

        if root == "deliverables":
            filtered = resolve_deliverable_sources(
                state, self.node_id, self.node_config or {}
            )
            return [d.get("deliverable", {}) for d in filtered]

        if root == "variables" and len(parts) >= 2:
            return state.get("variables", {}).get(parts[1])

        if root == "input" and len(parts) >= 2:
            obj = state.get("input_data", {})
            for key in parts[1:]:
                if isinstance(obj, dict):
                    obj = obj.get(key)
                else:
                    return None
            return obj

        return None

    # =====================================================================
    # File injection
    # =====================================================================

    async def _setup_kb_session(
        self,
        sandbox,
        state: WorkflowState,
        timeout_seconds: int,
    ) -> Optional[str]:
        """Mint an opaque KB session for this run and forward its id + URL
        to the sandbox as env vars.  Nothing is written to disk.

        Returns the ``session_id`` (so the caller can revoke it in ``finally``)
        or ``None`` if the node isn't configured for KB access.
        """
        raw_ids = self.get_config_value("knowledgeBaseIds", []) or []
        if isinstance(raw_ids, str):
            raw_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]
        kb_ids = [str(k) for k in raw_ids if k]
        if not kb_ids:
            return None

        user_id = state.get("metadata", {}).get("user_id")
        if not user_id:
            logger.warning(
                "Code executor %s: knowledgeBaseIds set but no user_id in state "
                "metadata; skipping KB session setup",
                self.label,
            )
            return None

        from services.code_executor_kb_session import create_session

        try:
            callback_url = self._resolve_kb_callback_url()
            session = create_session(
                user_id=str(user_id),
                kb_ids=kb_ids,
                container_id=self.node_id,
                ttl_seconds=max(60, int(timeout_seconds) + 60),
            )
        except Exception as exc:
            logger.warning(
                "Failed to create KB session for node %s: %s", self.label, exc,
            )
            return None

        try:
            sandbox.set_env_var("AGENT_STUDIO_KB_URL", callback_url)
            sandbox.set_env_var("AGENT_STUDIO_KB_SESSION", session.session_id)
            # Optional: when the callback URL resolves via public DNS to a
            # non-routable address (ACA internal env with Private Endpoint),
            # the host provides a process-local DNS override for the
            # sandbox SDK. Nothing is written to /etc/hosts.
            private_ip = self._resolve_kb_private_ip()
            if private_ip:
                sandbox.set_env_var(
                    "AGENT_STUDIO_KB_PRIVATE_IP", private_ip,
                )
        except Exception as exc:
            logger.warning(
                "Failed to forward KB env vars to sandbox %s: %s", self.label, exc,
            )
            # Revoke the session we just issued — it would be orphaned otherwise.
            try:
                from services.code_executor_kb_session import revoke_session
                revoke_session(session.session_id)
            except Exception:
                pass
            return None

        logger.info(
            "Code executor %s: KB session issued (user=%s, kbs=%d, ttl=%ds)",
            self.label, user_id, len(kb_ids), max(60, int(timeout_seconds) + 60),
        )
        return session.session_id

    @staticmethod
    def _resolve_kb_callback_url() -> str:
        """Pick the URL the sandbox uses to reach the host KB endpoints.

        Configuration precedence:
          1. ``SANDBOX_HOST_CALLBACK_URL`` in keyvault / env.
          2. ``AGENT_STUDIO_HOST_URL`` process env (convenience for tests).
          3. Docker Desktop default.
        """
        try:
            from config.keyvault import cfg
            url = getattr(cfg, "SANDBOX_HOST_CALLBACK_URL", None)
            if url:
                return str(url).rstrip("/")
        except Exception:
            pass
        import os as _os
        env_url = _os.environ.get("AGENT_STUDIO_HOST_URL")
        if env_url:
            return env_url.rstrip("/")
        return "http://host.docker.internal:8000"

    @staticmethod
    def _resolve_kb_private_ip() -> Optional[str]:
        """Optional private IP to resolve the callback hostname to inside
        the sandbox. Set in production where the URL resolves publicly to
        a non-routable address (ACA internal env behind Private Endpoint).
        Empty / unset in local dev (Docker).
        """
        try:
            from config.keyvault import cfg
            ip = getattr(cfg, "SANDBOX_KB_PRIVATE_IP", None)
            if ip:
                return str(ip).strip()
        except Exception:
            pass
        import os as _os
        return _os.environ.get("AGENT_STUDIO_KB_PRIVATE_IP") or None

    async def _inject_files(
        self,
        sandbox,
        inputs: Dict[str, Any],
        state: WorkflowState,
        *,
        reclaimed: bool = False,
    ) -> None:
        """Download session files + upstream output files and inject them
        into the sandbox at ``/workspace/uploads/``.

        When ``reclaimed`` is True the sandbox is being reused from a
        reservation after an ``output.ask()`` pause — the container's
        filesystem still has the session and upstream files from the
        pre-pause execution, so we skip those loops to save I/O.  Midway
        uploads (files the user uploaded *during* the pause) and the
        checkpoint blob must always be (re)injected regardless: midway
        uploads are fresh data that never touched the container, and the
        checkpoint may reflect a newer pause index than what's already
        on /outputs.
        """
        from ..sandbox.file_resolver import resolve_session_files, resolve_upstream_output_files

        injected: List[str] = []

        try:
            from ..sandbox.docker_sandbox import DockerSandbox
            if isinstance(sandbox, DockerSandbox):
                container = await sandbox._ensure_container()
                container.exec_run("mkdir -p /workspace/uploads", user="1000:1000")
        except Exception:
            pass

        if not reclaimed:
            session_id = state.get("metadata", {}).get("session_id")
            session_files = await resolve_session_files(session_id)
            for name, data in session_files:
                try:
                    await sandbox.write_file(f"/workspace/uploads/{name}", data)
                    injected.append(f"/workspace/uploads/{name}")
                except Exception:
                    logger.warning("Failed to inject session file %s", name)

            upstream_files = resolve_upstream_output_files(state, self.node_id)
            for name, local_path in upstream_files:
                try:
                    with open(local_path, "rb") as f:
                        data = f.read()
                    await sandbox.write_file(f"/workspace/uploads/{name}", data)
                    injected.append(f"/workspace/uploads/{name}")
                except Exception:
                    logger.warning("Failed to inject upstream file %s", name)

        # ── Midway files ──
        # Sources (in priority order per entry):
        #   1. ``blob_name`` → pull from ADLS via the storage facade
        #   2. ``local_path`` → read from backend pod disk (legacy;
        #      only ever present for pauses issued before the blob
        #      migration)
        # The sandbox-side transport is unchanged: for Docker we stream
        # via ``exec`` in base64 chunks, for ACI/remote we call
        # ``sandbox.write_file``.
        from .. import code_executor_storage as ce_storage

        midway_files: List[Dict[str, str]] = getattr(self, "_midway_files", [])
        if midway_files:
            from ..sandbox.docker_sandbox import DockerSandbox
            is_docker = isinstance(sandbox, DockerSandbox)
            if is_docker:
                container = await sandbox._ensure_container()
                loop = __import__("asyncio").get_running_loop()

            for entry in midway_files:
                name = entry.get("filename", "upload")
                blob_name = entry.get("blob_name", "")
                local_path = entry.get("local_path", "")
                logger.info(
                    "Injecting midway file: name=%s source=%s",
                    name, "blob" if blob_name else "local",
                )
                try:
                    if blob_name:
                        file_data = await ce_storage.download_midway(blob_name)
                        if file_data is None:
                            logger.warning(
                                "Midway blob %s unavailable; skipping %s",
                                blob_name, name,
                            )
                            continue
                    else:
                        if not local_path or not os.path.isfile(local_path):
                            logger.warning(
                                "Legacy midway file %s missing at %s; skipping",
                                name, local_path,
                            )
                            continue
                        with open(local_path, "rb") as f:
                            file_data = f.read()
                    logger.info("Read midway file %s (%d bytes)", name, len(file_data))

                    if is_docker:
                        import base64 as _b64
                        safe_name = name.replace("'", "'\\''")
                        CHUNK_RAW = 60_000

                        def _write_chunked(_data=file_data, _sname=safe_name):
                            dest = f"/workspace/uploads/{_sname}"
                            for i in range(0, len(_data), CHUNK_RAW):
                                chunk_b64 = _b64.b64encode(_data[i:i + CHUNK_RAW]).decode()
                                op = ">" if i == 0 else ">>"
                                ec, out = container.exec_run(
                                    ["sh", "-c", f"printf '%s' '{chunk_b64}' | base64 -d {op} '{dest}'"],
                                    user="1000:1000",
                                )
                                if ec != 0:
                                    return ec, (out or b"").decode(errors="replace")
                            return 0, ""

                        ec, out = await loop.run_in_executor(None, _write_chunked)
                        if ec != 0:
                            logger.warning("Chunked write failed for %s (exit %d): %s", name, ec, out)
                        else:
                            injected.append(f"/workspace/uploads/{name}")
                            logger.info("Injected midway file %s via chunked exec (%d bytes)", name, len(file_data))
                    else:
                        await sandbox.write_file(f"/workspace/uploads/{name}", file_data)
                        injected.append(f"/workspace/uploads/{name}")
                        logger.info("Injected midway file %s", name)
                except Exception as exc:
                    logger.warning("Failed to inject midway file %s: %s", name, exc, exc_info=True)
            self._midway_files = []
        else:
            logger.debug("No midway files to inject")

        # ── Checkpoint ──
        # New pauses store a pointer (``_checkpoint_blob``) into ADLS.
        # In-flight pauses from before the blob migration may still
        # carry the inline base64 body (``_checkpoint_b64``) — we honour
        # either and clear both at the end so we don't re-inject on the
        # next resume loop.
        cp_bytes: Optional[bytes] = None
        cp_source: str = ""
        cp_blob: Optional[str] = getattr(self, "_checkpoint_blob", None)
        cp_b64: Optional[str] = getattr(self, "_checkpoint_b64", None)
        if cp_blob:
            cp_bytes = await ce_storage.load_checkpoint(cp_blob)
            cp_source = f"blob {cp_blob}"
            if cp_bytes is None:
                logger.warning(
                    "Checkpoint blob %s unavailable; script will re-run from scratch",
                    cp_blob,
                )
        elif cp_b64:
            try:
                cp_bytes = base64.b64decode(cp_b64)
                cp_source = "inline(legacy b64)"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to decode legacy checkpoint b64: %s", exc)
                cp_bytes = None

        if cp_bytes:
            try:
                await sandbox.write_file("/outputs/_checkpoint.pkl", cp_bytes)
                logger.info(
                    "Injected checkpoint into sandbox (%d bytes, source=%s)",
                    len(cp_bytes), cp_source,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to inject checkpoint: %s", exc)

        self._checkpoint_blob = None
        self._checkpoint_b64 = None

        inputs["uploaded_files"] = injected

    # =====================================================================
    # Sandbox execution
    # =====================================================================

    async def _run_sandbox(
        self,
        code: str,
        inputs: Dict[str, Any],
        state: WorkflowState,
    ) -> Dict[str, Any]:
        from ..sandbox.sandbox_provider import get_sandbox_provider
        from ..sandbox.exceptions import SandboxError, SandboxTimeoutError

        timeout = self.get_config_value("timeout", 120)
        provider = get_sandbox_provider()

        execution_id = str(state.get("metadata", {}).get("execution_id", "unknown"))
        sandbox_id: Optional[str] = None
        kb_session_id: Optional[str] = None
        reclaim_target_id: Optional[str] = getattr(
            self, "_reclaim_target_id", None
        )
        reclaimed = False
        reserved_for_pause = False

        async def _emit(event_type: str, data: dict | str) -> None:
            try:
                from routers.sse_routes import push_execution_event
                await push_execution_event(execution_id, event_type, data)
            except Exception:
                pass

        try:
            await _emit("status", {"phase": "acquiring_sandbox", "node": self.label})

            # Fast-path: try to reclaim the container we reserved during
            # the pause. When successful the in-memory state of the script
            # is still there and we skip all file / checkpoint injection.
            sandbox = None
            if reclaim_target_id:
                try:
                    reclaimed_sandbox = await provider.reclaim(reclaim_target_id)
                except Exception as exc:
                    logger.warning(
                        "Reclaim raised for %s, falling back to fresh acquire: %s",
                        reclaim_target_id, exc,
                    )
                    reclaimed_sandbox = None
                if reclaimed_sandbox is not None:
                    sandbox = reclaimed_sandbox
                    sandbox_id = reclaim_target_id
                    reclaimed = True
                    logger.info(
                        "Code executor %s: reclaimed sandbox %s (fast resume)",
                        self.label, sandbox_id,
                    )

            if sandbox is None:
                sandbox_id = await provider.acquire(execution_id)
                sandbox = await provider.get(sandbox_id)
            if sandbox is None:
                return self._error("Failed to acquire sandbox")
            _get_audit().sandbox_created(
                execution_id=execution_id, sandbox_id=sandbox_id,
                provider=type(provider).__name__,
            )
            _get_audit().code_execution_started(
                execution_id=execution_id, node_id=self.node_id, node_label=self.label,
            )

            # On reclaim we reuse a still-running container from the pause
            # reservation, so session + upstream files already live on the
            # container's filesystem and re-injecting them would be wasted
            # I/O.  But midway uploads (files the user uploaded *during*
            # the pause) and the latest checkpoint blob are always fresh
            # data that must land in the container before we re-run the
            # script; _inject_files keeps honouring those regardless of
            # the flag.  We still mint a fresh KB session below because
            # the prior one may have TTL-expired during the pause window.
            await _emit(
                "status",
                {
                    "phase": "resuming_reclaimed" if reclaimed else "injecting_files",
                    "node": self.label,
                },
            )
            await self._inject_files(
                sandbox, inputs, state, reclaimed=reclaimed
            )

            kb_session_id = await self._setup_kb_session(sandbox, state, timeout)

            await _emit("status", {"phase": "running", "node": self.label})

            async def _on_stdout(line: str) -> None:
                await _emit("stdout", {"line": line, "node": self.label})

            async def _on_stderr(line: str) -> None:
                await _emit("stderr", {"line": line, "node": self.label})

            result = await sandbox.execute_code(
                code, inputs=inputs, timeout=timeout,
                on_stdout=_on_stdout, on_stderr=_on_stderr,
            )

            # ── Midway input: script called output.ask() → exit 42 ──
            if result.exit_code == 42:
                pause_data: Dict[str, Any] = (
                    result.output
                    if isinstance(result.output, dict)
                    else {"prompt": "The script is waiting for input."}
                )
                pause_idx = pause_data.get("pause_index", 0)
                prior_responses: List[Any] = list(inputs.get("pause_responses", []))

                # Persist the checkpoint to ADLS (so we're not dragging
                # a multi-MB base64 blob around inside the Postgres
                # ``execution_data.data`` JSON on every state save).  We
                # store only a pointer in pending_input; the inject
                # path resolves it back to bytes on resume.
                checkpoint_blob: Optional[str] = None
                if result.checkpoint_data:
                    user_id = state.get("metadata", {}).get("user_id") or "anon"
                    from .. import code_executor_storage as ce_storage
                    checkpoint_blob = await ce_storage.save_checkpoint(
                        user_id=str(user_id),
                        execution_id=execution_id,
                        pause_index=int(pause_idx),
                        data=result.checkpoint_data,
                    )
                    if checkpoint_blob:
                        logger.info(
                            "Code executor %s: checkpoint stored in blob %s (%d bytes)",
                            self.label, checkpoint_blob, len(result.checkpoint_data),
                        )
                    else:
                        # Blob save failed — we deliberately do NOT fall
                        # back to the legacy Postgres base64 path.  If
                        # storage is unavailable at pause time the user
                        # can still resume; the script will just re-run
                        # from scratch (pause_responses still replay the
                        # answers, so the control flow lands in the
                        # right place).  This avoids re-introducing the
                        # WAL bloat we're specifically trying to remove.
                        logger.warning(
                            "Code executor %s: checkpoint NOT persisted "
                            "(storage unavailable); resume will re-execute "
                            "pre-pause code",
                            self.label,
                        )

                logger.info(
                    "Code executor %s detected exit 42 (midway pause, "
                    "pause_index=%d, prior_responses=%d, has_checkpoint=%s)",
                    self.label, pause_idx, len(prior_responses),
                    bool(checkpoint_blob),
                )

                ask_deliverable_data = {
                    **pause_data,
                    "_output_type": "ask",
                    "_interactive": True,
                    "_metadata": {"title": "Input Required"},
                }
                ask_entry = {
                    "deliverable_id": str(uuid.uuid4()),
                    "agent_id": self.node_id,
                    "agent_label": self.label,
                    "agent_type": "code-executor",
                    "deliverable": ask_deliverable_data,
                    "output_type": "ask",
                    "interactive": True,
                    "status": "pending",
                    "iteration": 1,
                    "created_at": datetime.utcnow().isoformat(),
                }

                logger.info(
                    "Code executor %s paused — created ask deliverable %s "
                    "(pause_index=%d)",
                    self.label, ask_entry["deliverable_id"], pause_idx,
                )

                pending_input: Dict[str, Any] = {
                    "node_id": self.node_id,
                    "type": "code_executor_midway_input",
                    "pause_request": pause_data,
                    "pause_responses": prior_responses,
                    "pause_file_map": getattr(self, "_pause_file_map", {}),
                    "resolved_inputs_snapshot": inputs,
                    "code": code,
                    "deliverable_id": ask_entry["deliverable_id"],
                    "reserved_sandbox_id": sandbox_id,
                }
                if checkpoint_blob:
                    pending_input["checkpoint_blob"] = checkpoint_blob

                reserved_for_pause = True

                return {
                    "interrupted": True,
                    "deliverables": state.get("deliverables", []) + [ask_entry],
                    "has_deliverable": True,
                    "pending_user_input": pending_input,
                    "metadata": {
                        **state.get("metadata", {}),
                        "status": "paused",
                    },
                }

            if not result.success:
                _get_audit().code_execution_failed(
                    execution_id=execution_id, node_id=self.node_id,
                    node_label=self.label, exit_code=result.exit_code,
                    duration_ms=result.duration_ms,
                    error=(result.stderr or result.stdout or "")[:500],
                )
                return self._error(
                    f"Code execution failed (exit {result.exit_code}): "
                    f"{result.stderr or result.stdout}",
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

            # ── Extract output files from the sandbox ──
            exec_id = str(state.get("metadata", {}).get("execution_id", "unknown"))
            dest_dir = os.path.join(OUTPUT_FILES_DIR, exec_id, self.node_id)
            extracted_files: List[Dict[str, str]] = []
            try:
                extracted_files = await sandbox.extract_output_files(dest_dir)
                logger.info(
                    "Extracted %d output file(s) from sandbox %s",
                    len(extracted_files), sandbox_id,
                )
                await self._upload_output_files_to_blob(extracted_files, exec_id)
            except Exception as exc:
                logger.warning("Failed to extract output files from sandbox %s: %s", sandbox_id, exc)

            # Build deliverable from SDK output or raw stdout
            deliverable_payload = self._build_deliverable(result)
            output_type = deliverable_payload.get("type", "data")
            logger.info(
                "Code executor %s finished — output_type=%s, exit=%d",
                self.label, output_type, result.exit_code,
            )

            # ── Deliverable-shape guard (runtime mirror of AST checks) ──
            # Reject HTML-in-data, base64'd HTML pages, oversized blobs,
            # iframe smuggling in render scripts, etc.  This is the last
            # defence before the deliverable hits Postgres / SSE / the
            # frontend / downstream nodes.  We only enforce on data and
            # composed data-type payloads — `file`/`files`/`error`
            # outputs follow different contracts.
            if output_type == "data":
                shape_violations = self._validate_deliverable_payload(
                    deliverable_payload,
                )
                if shape_violations:
                    _get_audit().code_execution_failed(
                        execution_id=execution_id,
                        node_id=self.node_id,
                        node_label=self.label,
                        error="deliverable_shape_violation: "
                        + "; ".join(shape_violations)[:400],
                    )
                    logger.warning(
                        "Code executor %s deliverable rejected by runtime "
                        "shape guard: %s",
                        self.label, "; ".join(shape_violations),
                    )
                    return self._error(
                        "Deliverable failed the runtime shape guard. "
                        "Fix the violations and try again:\n  - "
                        + "\n  - ".join(shape_violations),
                        stdout=result.stdout,
                        stderr=result.stderr,
                    )
            # The deliverable is interactive iff the script emitted one of
            # the interactive widgets (output.selection, output.form, …) —
            # the SDK sets ``interactive=True`` on the payload in that
            # case.  This is the single source of truth for "does this
            # output need user response?"; there is no separate node-
            # level flag.
            is_interactive = deliverable_payload.get("interactive", False)

            # Embed output metadata inside the deliverable data so it
            # survives the DB round-trip (the DB stores deliverable as JSON).
            raw_data = deliverable_payload.get("data", {})
            if not isinstance(raw_data, dict):
                raw_data = {"_raw": raw_data}
            deliverable_data = raw_data
            deliverable_data["_output_type"] = output_type
            deliverable_data["_interactive"] = is_interactive
            deliverable_data["_metadata"] = deliverable_payload.get("metadata", {})
            deliverable_data["_execution_log"] = {
                "stdout": (result.stdout or "")[:50_000],
                "stderr": (result.stderr or "")[:50_000],
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            }
            viz = deliverable_payload.get("visualization")
            if viz is not None:
                deliverable_data["_visualization"] = viz

            # Non-interactive deliverables auto-continue the workflow.
            # Interactive widgets (selection/form) pause so the user can
            # respond — the pause is fully driven by the script's output,
            # mirroring the behaviour of output.ask().
            if is_interactive:
                deliv_status = "pending"
            else:
                deliv_status = "approved"

            # Attach output file download info to the deliverable
            file_records = []
            for ef in extracted_files:
                file_records.append({
                    "name": ef["name"],
                    "download_url": f"/api/code-executor/files/{exec_id}/{self.node_id}/{ef['name']}",
                    "sandbox_path": ef["sandbox_path"],
                })
            if file_records:
                deliverable_data["_output_files"] = file_records

            _get_audit().code_execution_completed(
                execution_id=execution_id, node_id=self.node_id, node_label=self.label,
                exit_code=result.exit_code, duration_ms=result.duration_ms,
                output_type=output_type,
            )

            deliverable_entry = {
                "deliverable_id": str(uuid.uuid4()),
                "agent_id": self.node_id,
                "agent_label": self.label,
                "agent_type": "code-executor",
                "deliverable": deliverable_data,
                "output_type": output_type,
                "interactive": is_interactive,
                "status": deliv_status,
                "iteration": 1,
                "created_at": datetime.utcnow().isoformat(),
            }

            response: Dict[str, Any] = {
                "deliverables": state.get("deliverables", []) + [deliverable_entry],
                "has_deliverable": True,
                "response": result.stdout,
                "execution_result": {
                    "success": True,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration_ms": result.duration_ms,
                    "output_type": output_type,
                    "output_files": result.output_files,
                },
                "deliverable": deliverable_payload.get("data", {}),
                "output_type": output_type,
                # Clear any previous pause state
                "pending_user_input": None,
                "user_input_response": None,
            }

            if is_interactive:
                response["interrupted"] = True
                response["pending_deliverable"] = deliverable_entry
                response["metadata"] = {
                    **state.get("metadata", {}),
                    "status": "pending_review",
                }

            await _emit("complete", {
                "phase": "complete",
                "node": self.label,
                "output_type": output_type,
                "duration_ms": result.duration_ms,
            })
            return response

        except SandboxTimeoutError as exc:
            _get_audit().code_execution_failed(
                execution_id=execution_id, node_id=self.node_id,
                node_label=self.label, error=f"Timeout after {exc.timeout_seconds}s",
            )
            await _emit("error", {"phase": "error", "message": f"Timed out after {exc.timeout_seconds}s"})
            return self._error(f"Code execution timed out after {exc.timeout_seconds}s")
        except SandboxError as exc:
            _get_audit().code_execution_failed(
                execution_id=execution_id, node_id=self.node_id,
                node_label=self.label, error=exc.message,
            )
            await _emit("error", {"phase": "error", "message": exc.message})
            return self._error(f"Sandbox error: {exc.message}")
        except Exception as exc:
            logger.exception("Unexpected error in code executor %s", self.label)
            _get_audit().code_execution_failed(
                execution_id=execution_id, node_id=self.node_id,
                node_label=self.label, error=str(exc),
            )
            await _emit("error", {"phase": "error", "message": str(exc)})
            return self._error(f"Unexpected error: {exc}")
        finally:
            # Always revoke the KB session so a leaked session id becomes
            # worthless the moment the run ends.  Best-effort: a failed
            # revoke still leaves TTL expiry as a backstop.
            if kb_session_id is not None:
                try:
                    from services.code_executor_kb_session import revoke_session
                    revoke_session(kb_session_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to revoke KB session for node %s: %s",
                        self.label, exc,
                    )

            if sandbox_id is not None:
                if reserved_for_pause:
                    try:
                        from config.keyvault import cfg as _cfg
                        pause_ttl = max(
                            30,
                            int(
                                getattr(
                                    _cfg,
                                    "SANDBOX_PAUSE_IDLE_TIMEOUT_SECONDS",
                                    None,
                                )
                                or 600
                            ),
                        )
                    except Exception:
                        pause_ttl = 600
                    try:
                        await provider.reserve(sandbox_id, pause_ttl)
                        logger.info(
                            "Reserved sandbox %s for %ds (pause hold)",
                            sandbox_id, pause_ttl,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Reserve failed for %s (%s); falling back to release",
                            sandbox_id, exc,
                        )
                        try:
                            await provider.release(sandbox_id)
                        except Exception:
                            logger.warning(
                                "Fallback release also failed for %s",
                                sandbox_id,
                            )
                        _get_audit().sandbox_destroyed(
                            execution_id=execution_id, sandbox_id=sandbox_id,
                            provider=type(provider).__name__,
                        )
                else:
                    _get_audit().sandbox_destroyed(
                        execution_id=execution_id, sandbox_id=sandbox_id,
                        provider=type(provider).__name__,
                    )
                    try:
                        await provider.release(sandbox_id)
                    except Exception:
                        logger.warning("Failed to release sandbox %s", sandbox_id)

            self._reclaim_target_id = None

    # =====================================================================
    # Output helpers
    # =====================================================================

    _INTERNAL_KEYS = frozenset({
        "_visualization", "_output_type", "_interactive", "_metadata",
        "_execution_log", "_output_files", "_raw",
    })

    # ── Deliverable-shape guard ──────────────────────────────────────────
    #
    # Runtime mirror of the static checks in ``code_validator.py``.  The
    # AST validator catches deliverable-contract violations that are
    # statically visible (literal HTML strings, ``output.data`` dict
    # literals with forbidden keys, render-script tokens), but anything
    # the model builds dynamically — at runtime, after pandas /
    # f-string / loop assembly — only shows up in the actual emitted
    # payload.  This guard inspects the deliverable AFTER execution and
    # BEFORE we persist it, so a clever runtime escape still gets
    # rejected before downstream nodes ever see the blob.
    _FORBIDDEN_DATA_KEYS = frozenset({
        "html", "html_base64", "html_b64", "html_content", "html_string",
        "rendered_html", "markup", "dom_string", "iframe", "iframe_src",
        "script", "script_html", "raw_html", "page_html", "full_html",
    })
    _HTML_MARKUP_MARKERS = (
        "<!doctype", "<!DOCTYPE",
        "<html", "<HTML", "</html>", "</HTML>",
        "<body", "<BODY", "</body>", "</BODY>",
        "<script", "<SCRIPT", "</script>", "</SCRIPT>",
        "<iframe", "<IFRAME",
        "<style>", "<STYLE>",
    )
    _FORBIDDEN_RENDER_JS_TOKENS = (
        "srcDoc", "srcdoc", "<iframe",
        ".innerHTML", ".outerHTML", "dangerouslySetInnerHTML",
        "document.write", "atob(", "eval(",
        "new Function(", "Function(",
    )

    # Size budgets — generous on the visualization side because composed
    # dashboards with many primitives can legitimately add up.
    _MAX_DATA_BYTES = 256 * 1024              # 256 KB total `data`
    _MAX_DATA_STRING_BYTES = 64 * 1024        # 64 KB per leaf string in `data`
    _MAX_VISUALIZATION_BYTES = 256 * 1024     # 256 KB total visualization list
    _MAX_RENDER_SCRIPT_BYTES = 32 * 1024      # 32 KB per render script body

    @classmethod
    def _strip_internal(cls, data: Any) -> Any:
        """Remove internal metadata keys from a deliverable dict so downstream
        nodes only see clean user data."""
        if not isinstance(data, dict):
            return data
        if "_raw" in data:
            return data["_raw"]
        return {k: v for k, v in data.items() if k not in cls._INTERNAL_KEYS}

    @classmethod
    def _validate_deliverable_payload(
        cls, deliverable_payload: Dict[str, Any],
    ) -> List[str]:
        """Return a list of guardrail violations on the runtime deliverable.

        We re-walk the actual emitted payload (the SDK's serialised
        result, before we wrap it for storage) and reject anything that
        violates the deliverable contract documented in the system
        prompt.  Empty list means clean.

        Layered with the static AST validator: the AST catches anything
        statically obvious (`output.data({"html_base64": ...})` literal),
        this runtime pass catches anything assembled at execution time
        (loops, f-strings of dataframes, conditional injection).
        """
        violations: List[str] = []

        data = deliverable_payload.get("data") if isinstance(
            deliverable_payload, dict,
        ) else None
        if data is not None:
            cls._scan_runtime_value(
                data,
                violations=violations,
                path="data",
                root_kind="data",
            )
            try:
                data_bytes = len(json.dumps(data, default=str).encode("utf-8"))
            except (TypeError, ValueError):
                data_bytes = 0
            if data_bytes > cls._MAX_DATA_BYTES:
                violations.append(
                    f"`data` payload is {data_bytes:,} bytes "
                    f"(limit: {cls._MAX_DATA_BYTES:,}). Move large blobs "
                    f"to `output.file()` and keep `data` semantic."
                )

        viz = deliverable_payload.get("visualization") if isinstance(
            deliverable_payload, dict,
        ) else None
        if viz is not None:
            cls._scan_visualization(viz, violations=violations)
            try:
                viz_bytes = len(json.dumps(viz, default=str).encode("utf-8"))
            except (TypeError, ValueError):
                viz_bytes = 0
            if viz_bytes > cls._MAX_VISUALIZATION_BYTES:
                violations.append(
                    f"`visualization` is {viz_bytes:,} bytes "
                    f"(limit: {cls._MAX_VISUALIZATION_BYTES:,}). Compose "
                    f"smaller specs or move detail into a sub-component."
                )

        return violations

    @classmethod
    def _scan_runtime_value(
        cls,
        value: Any,
        *,
        violations: List[str],
        path: str,
        root_kind: str,
    ) -> None:
        """Recursive walk: forbidden keys, HTML strings, oversized blobs.

        ``root_kind`` distinguishes ``data`` (strict — no markup at all)
        from ``visualization`` (where strings may legitimately contain
        a small amount of markup inside a render script — that's
        scanned separately by ``_scan_visualization``).
        """
        if isinstance(value, dict):
            for k, v in value.items():
                k_str = str(k)
                if root_kind == "data" and k_str.lower() in cls._FORBIDDEN_DATA_KEYS:
                    violations.append(
                        f"Forbidden field '{k_str}' at `{path}.{k_str}`. "
                        f"Rendered markup belongs in `visualization` as a "
                        f"`render` spec, never in `data`."
                    )
                cls._scan_runtime_value(
                    v,
                    violations=violations,
                    path=f"{path}.{k_str}",
                    root_kind=root_kind,
                )
        elif isinstance(value, list):
            for i, item in enumerate(value):
                cls._scan_runtime_value(
                    item,
                    violations=violations,
                    path=f"{path}[{i}]",
                    root_kind=root_kind,
                )
        elif isinstance(value, str):
            if root_kind == "data":
                if len(value) > cls._MAX_DATA_STRING_BYTES:
                    violations.append(
                        f"`{path}` is a {len(value):,}-char string "
                        f"(limit: {cls._MAX_DATA_STRING_BYTES:,}). Large "
                        f"text belongs in `output.file()`, not `data`."
                    )
                if len(value) >= 1024 and any(
                    m in value for m in cls._HTML_MARKUP_MARKERS
                ):
                    violations.append(
                        f"`{path}` contains HTML markup. `data` is for "
                        f"machine-readable values; emit markup via the "
                        f"`visualization` DSL or a `render` spec."
                    )
                # base64 sniff: long ASCII string of [A-Za-z0-9+/=].  If
                # the decode looks like HTML/JS, that's the "smuggle a
                # rendered page through data" pattern.
                if len(value) > 4096 and cls._looks_like_base64(value):
                    decoded_head = cls._safe_b64_decode_head(value)
                    if decoded_head and any(
                        m in decoded_head for m in cls._HTML_MARKUP_MARKERS
                    ):
                        violations.append(
                            f"`{path}` is a base64-encoded HTML/JS blob "
                            f"({len(value):,} chars). This is the bypass "
                            f"pattern; the platform rejects it at runtime."
                        )

    @classmethod
    def _scan_visualization(
        cls, viz: Any, *, violations: List[str],
    ) -> None:
        """Walk the visualization list and lint any embedded `render`
        spec's ``script`` for the same forbidden JS tokens the static
        validator checks for, plus a size budget per script."""
        if isinstance(viz, dict):
            specs: List[Any] = [viz]
        elif isinstance(viz, list):
            specs = viz
        else:
            return
        for i, spec in enumerate(specs):
            if not isinstance(spec, dict):
                continue
            if spec.get("type") == "render":
                script = spec.get("script")
                if isinstance(script, str):
                    if len(script) > cls._MAX_RENDER_SCRIPT_BYTES:
                        violations.append(
                            f"`visualization[{i}].script` is "
                            f"{len(script):,} bytes "
                            f"(limit: {cls._MAX_RENDER_SCRIPT_BYTES:,}). "
                            f"Move data into the payload and keep the "
                            f"render script as a thin renderer."
                        )
                    for token in cls._FORBIDDEN_RENDER_JS_TOKENS:
                        if token in script:
                            violations.append(
                                f"`visualization[{i}].script` contains "
                                f"forbidden token '{token}'. Render "
                                f"scripts must build UI via "
                                f"React.createElement only — no iframe "
                                f"loading, innerHTML, document.write, "
                                f"atob, eval, or Function()."
                            )
            children = spec.get("children")
            if isinstance(children, list):
                cls._scan_visualization(children, violations=violations)

    @staticmethod
    def _looks_like_base64(value: str) -> bool:
        """Cheap heuristic: ≥95% chars are base64 alphabet, ≥1024 long.

        We only need to short-circuit on obvious base64 strings — the
        decode-and-sniff confirms; this just avoids running it on
        every long string.
        """
        if len(value) < 1024:
            return False
        allowed = 0
        for ch in value:
            if (
                "A" <= ch <= "Z"
                or "a" <= ch <= "z"
                or "0" <= ch <= "9"
                or ch in "+/=\n\r"
            ):
                allowed += 1
        return allowed / max(1, len(value)) >= 0.95

    @staticmethod
    def _safe_b64_decode_head(value: str, *, head_bytes: int = 1024) -> str:
        """Decode the first chunk of a candidate base64 string.

        Returns an empty string on any decode error so callers can
        treat ``not result`` as "not base64 / decode failed".
        """
        try:
            cleaned = "".join(value.split())
            chunk = cleaned[: ((head_bytes * 4 // 3 + 3) // 4) * 4]
            decoded = base64.b64decode(chunk, validate=False)
            return decoded[:head_bytes].decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _build_deliverable(result) -> Dict[str, Any]:
        """Convert sandbox ``ExecutionResult`` into a deliverable payload."""
        if result.output:
            return result.output

        # Fallback: wrap raw stdout as data
        stdout = result.stdout.strip()
        try:
            parsed = json.loads(stdout)
            return {"type": "data", "data": parsed, "metadata": {}, "interactive": False}
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "type": "data",
            "data": {"text": stdout},
            "metadata": {"title": "Output"},
            "interactive": False,
        }

    @staticmethod
    async def _upload_output_files_to_blob(
        extracted_files: List[Dict[str, str]],
        execution_id: str,
    ) -> None:
        """Best-effort upload of extracted output files to Azure Blob for
        persistence across ACA replicas and restarts.

        Uses the shared ``AzureStorageConnector`` (same container, same
        UAMI) as the Code Executor checkpoint / midway storage so we
        don't fragment credentials or config.
        """
        try:
            from core.dependencies import get_azure_storage_connector
            connector = get_azure_storage_connector()
        except Exception as exc:
            logger.debug("Storage connector unavailable for output files: %s", exc)
            return
        for ef in extracted_files:
            local_path = ef.get("local_path", "")
            name = ef.get("name", "")
            if not local_path or not os.path.isfile(local_path):
                continue
            blob_path = f"code-executor/outputs/{execution_id}/{name}"
            try:
                with open(local_path, "rb") as f:
                    data = f.read()
                await connector.upload_blob(
                    blob_name=blob_path,
                    data=data,
                    metadata={
                        "execution_id": str(execution_id),
                        "kind": "output_file",
                    },
                    overwrite=True,
                )
                logger.debug("Uploaded output file to blob: %s", blob_path)
            except Exception as exc:
                logger.debug(
                    "Output file blob upload failed for %s: %s", blob_path, exc,
                )

    def _error(self, message: str, *, stdout: str = "", stderr: str = "") -> Dict[str, Any]:
        logger.error("Code executor %s: %s", self.label, message)

        deliverable_data = {
            "_output_type": "error",
            "_metadata": {"title": "Execution Error"},
            "_execution_log": {
                "stdout": (stdout or "")[:50_000],
                "stderr": (stderr or "")[:50_000],
                "error": message,
            },
            "error": message,
        }
        deliverable_entry = {
            "deliverable_id": str(uuid.uuid4()),
            "agent_id": self.node_id,
            "agent_label": self.label,
            "agent_type": "code-executor",
            "deliverable": deliverable_data,
            "output_type": "error",
            "interactive": False,
            "status": "approved",
            "iteration": 1,
            "created_at": datetime.utcnow().isoformat(),
        }

        return {
            "error": message,
            "has_deliverable": True,
            "deliverables": [deliverable_entry],
            "execution_result": {
                "success": False,
                "error": message,
                "stdout": stdout,
                "stderr": stderr,
            },
        }
