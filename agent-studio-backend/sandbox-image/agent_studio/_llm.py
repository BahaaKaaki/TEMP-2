"""
LLM client for the agent_studio sandbox SDK.

Calls the GenAI Shared Service proxy (OpenAI-compatible API) directly
from inside the sandbox using only ``urllib`` (stdlib).  The proxy URL
and API key are injected as environment variables by the host.

Usage::

    from agent_studio import llm

    result = llm.complete(
        "Extract all client names from this text: ...",
        model="gpt-4o-mini",
        output_schema={"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}}},
    )
"""
from __future__ import annotations

import json
import os
import ssl
from typing import Any


_ENV_URL = "AGENT_STUDIO_LLM_URL"
_ENV_KEY = "AGENT_STUDIO_LLM_KEY"


class _LLM:
    """Singleton LLM client that talks to the GenAI proxy."""

    def complete(
        self,
        prompt: str,
        *,
        model: str = "bedrock.anthropic.claude-haiku-4-5",
        system_prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> str:
        """Send a chat-completion request and return the assistant message.

        Args:
            prompt: The user message.
            model: Model identifier with provider prefix
                   (e.g. ``"gpt-4o-mini"``, ``"vertex_ai.gemini-2.5-flash"``).
            system_prompt: Optional system message prepended to the conversation.
            output_schema: If provided, requests structured JSON output via
                           ``response_format.type = "json_schema"``.
            temperature: Sampling temperature (omitted for reasoning models).
            max_tokens: Maximum tokens in the response.
            timeout: HTTP request timeout in seconds.

        Returns:
            The ``content`` string from ``choices[0].message``.

        Raises:
            RuntimeError: If the proxy env vars are missing or the API returns
                          a non-200 status.
        """
        import urllib.request

        base_url = os.environ.get(_ENV_URL)
        api_key = os.environ.get(_ENV_KEY)

        if not base_url or not api_key:
            raise RuntimeError(
                f"LLM proxy not configured. The environment variables "
                f"{_ENV_URL} and {_ENV_KEY} must be set by the host."
            )

        url = f"{base_url.rstrip('/')}/v1/chat/completions"

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if temperature is not None:
            body["temperature"] = temperature

        if output_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "schema": output_schema,
                },
            }

        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "API-Key": api_key,
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        ctx = ssl.create_default_context()

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise RuntimeError(
                f"LLM proxy returned HTTP {exc.code}: {err_body[:500]}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"LLM proxy request failed: {exc}") from exc

        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(
                f"Unexpected proxy response structure: {json.dumps(result)[:300]}"
            ) from exc


llm = _LLM()
