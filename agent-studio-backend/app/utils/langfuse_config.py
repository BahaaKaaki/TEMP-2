"""
Langfuse integration for LLM observability.

Central LLM tracing is emitted from TracedChatModel via app.llm.langfuse_emit.
Configuration is loaded via config.keyvault.cfg (Key Vault → .env fallback).
Values are mirrored into os.environ on init for the Langfuse SDK.
"""
from __future__ import annotations

import base64
import logging
import os
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

_langfuse_initialized = False
_otlp_ssl_patch_applied = False


def _cfg():
    from config.keyvault import cfg

    return cfg


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1].strip()
    return value


def _cfg_str(name: str) -> str:
    """Read a string setting from central cfg (Key Vault or env)."""
    raw = getattr(_cfg(), name, None)
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    return _strip_quotes(str(raw).strip())


def _cfg_bool(name: str, *, default: bool = False) -> bool:
    raw = getattr(_cfg(), name, None)
    if isinstance(raw, bool):
        return raw
    text = _cfg_str(name)
    if not text:
        return default
    return text.lower() in ("true", "1", "yes", "on")


def _cfg_int(name: str, default: int) -> int:
    raw = getattr(_cfg(), name, None)
    if isinstance(raw, int):
        return raw
    text = _cfg_str(name)
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _langfuse_ssl_verify() -> bool:
    """Whether to verify TLS for Langfuse HTTP + OTLP export."""
    return _cfg_bool("LANGFUSE_SSL_VERIFY", default=True)


def _langfuse_ca_bundle() -> Optional[str]:
    path = _cfg_str("LANGFUSE_CA_BUNDLE") or (os.getenv("REQUESTS_CA_BUNDLE") or "").strip()
    return path or None


def _configure_langfuse_ssl() -> None:
    """
    Configure TLS for Langfuse SDK (OTLP trace export + httpx API client).

    - LANGFUSE_CA_BUNDLE: path to corporate/root CA PEM (preferred on PwC laptops)
    - LANGFUSE_SSL_VERIFY=false: dev-only bypass when CA is not in trust store
    """
    global _otlp_ssl_patch_applied

    ca_bundle = _langfuse_ca_bundle()
    if ca_bundle:
        os.environ["OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE"] = ca_bundle
        os.environ["OTEL_EXPORTER_OTLP_CERTIFICATE"] = ca_bundle
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
        os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
        logger.info("Langfuse OTLP using custom CA bundle: %s", ca_bundle)
        return

    if _langfuse_ssl_verify():
        return

    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    if _otlp_ssl_patch_applied:
        return

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        _original_init = OTLPSpanExporter.__init__

        def _init_with_optional_insecure(self, *args, **kwargs):
            _original_init(self, *args, **kwargs)
            self._certificate_file = False

        OTLPSpanExporter.__init__ = _init_with_optional_insecure  # type: ignore[method-assign]
        _otlp_ssl_patch_applied = True
        logger.warning(
            "Langfuse OTLP export: TLS certificate verification is DISABLED "
            "(LANGFUSE_SSL_VERIFY=false). Use only for local development."
        )
    except Exception as exc:
        logger.warning("Failed to patch Langfuse OTLP SSL settings: %s", exc)


def _gcass_proxy_token() -> str:
    """Global CaaS API token for Proxy-Authorization (required on PwC hosted Langfuse)."""
    return _cfg_str("GCAAS_API_TOKEN") or _cfg_str("HOSTEDAPPS_KEY")


def _requires_gcass_proxy(base_url: str) -> bool:
    """PwC CaaS ingress requires Proxy-Authorization before Langfuse sees pk/sk."""
    host = (base_url or "").lower()
    return "pwclabs" in host or "pwcglb.com" in host


def _gcass_proxy_headers(*, include_langfuse_auth: bool = False) -> Dict[str, str]:
    """Headers for PwC CaaS ingress — matches working Langfuse demo config."""
    headers: Dict[str, str] = {"Accept": "application/json"}
    proxy_token = _gcass_proxy_token()
    if proxy_token:
        headers["Proxy-Authorization"] = proxy_token
    if include_langfuse_auth:
        public_key = _cfg_str("LANGFUSE_PUBLIC_KEY")
        secret_key = _cfg_str("LANGFUSE_SECRET_KEY")
        if public_key and secret_key:
            basic = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
            headers["Authorization"] = f"Basic {basic}"
    return headers


def _normalize_langfuse_host_url(url: str) -> str:
    """
    PwC CaaS Langfuse expects /api/ after the domain.

    UI may show:  https://host/{deployment-id}/.../langfuse
    API route:    https://host/api/{deployment-id}/.../langfuse
    """
    if not url or not _cfg_bool("LANGFUSE_INSERT_API_PATH", default=True):
        return url.rstrip("/")

    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url.rstrip("/"))
    path = parsed.path or ""
    if path.startswith("/api/") or path == "/api":
        return url.rstrip("/")

    new_path = "/api" + (path if path.startswith("/") else f"/{path}")
    normalized = urlunparse(parsed._replace(path=new_path)).rstrip("/")
    if normalized != url.rstrip("/"):
        logger.info("Langfuse URL: inserted /api/ path segment → %s", normalized)
    return normalized


def _langfuse_ui_base_url() -> str:
    """Hosted Langfuse URL from Settings → API Keys (+ /api/ normalization for CaaS)."""
    raw = _cfg_str("LANGFUSE_BASE_URL") or _cfg_str("LANGFUSE_HOST")
    if not raw:
        return ""
    return _normalize_langfuse_host_url(raw)


def _langfuse_http_verify() -> Union[bool, str]:
    """requests/httpx verify argument."""
    if _langfuse_ca_bundle():
        return _langfuse_ca_bundle()  # type: ignore[return-value]
    return _langfuse_ssl_verify()


def _probe_langfuse_api(base_url: str) -> Tuple[bool, str]:
    """
    Check that base_url is the Langfuse API and that configured keys authenticate.

    Returns (ok, detail). Only HTTP 200 JSON health counts as success.
    """
    public_key = _cfg_str("LANGFUSE_PUBLIC_KEY")
    secret_key = _cfg_str("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        return False, "missing API keys"

    url = f"{base_url.rstrip('/')}/api/public/health"
    try:
        import requests

        response = requests.get(
            url,
            headers=_gcass_proxy_headers(include_langfuse_auth=True),
            verify=_langfuse_http_verify(),
            timeout=15,
        )
        content_type = (response.headers.get("content-type") or "").lower()
        body = (response.text or "")[:200]
        if "json" in content_type or body.strip().startswith("{"):
            if response.status_code == 200:
                return True, "health_ok"
            if response.status_code == 401:
                return False, (
                    "auth_rejected (401) — keys are not valid for this API host. "
                    "Use LANGFUSE_BASE_URL from Langfuse Settings → API Keys; "
                    "remove LANGFUSE_API_BASE_URL unless your platform team gave a different API host."
                )
            return False, f"json_status_{response.status_code}: {body}"
        return False, (
            f"got_html_not_api (status={response.status_code}) — ingress returned the UI shell "
            f"instead of the Langfuse API at {url}. Ask whoever hosts Langfuse to proxy "
            "/api/public/* to the Langfuse server, or set LANGFUSE_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT."
        )
    except Exception as exc:
        return False, str(exc)


def _langfuse_url_candidates() -> list[str]:
    """Probe only the hosted URL(s) from config — never guess the gateway root."""
    ui_base = _langfuse_ui_base_url()
    candidates: list[str] = [ui_base]
    api_override = _cfg_str("LANGFUSE_API_BASE_URL")
    if api_override and api_override.rstrip("/") != ui_base:
        candidates.append(api_override.rstrip("/"))
    if ui_base.endswith("/langfuse"):
        parent = ui_base.removesuffix("/langfuse")
        if parent and parent not in candidates:
            candidates.append(parent)

    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _resolve_langfuse_base_url() -> str:
    """Use LANGFUSE_BASE_URL from .env / Key Vault (hosted URL from Langfuse project settings)."""
    ui_base = _langfuse_ui_base_url()
    if not ui_base:
        logger.error("LANGFUSE_BASE_URL is not set — copy the hosted URL from Langfuse Settings → API Keys")
        return ""

    if _cfg_bool("LANGFUSE_TRUST_BASE_URL", default=True):
        logger.info("Langfuse using hosted LANGFUSE_BASE_URL=%s", ui_base)
        return ui_base

    candidates = _langfuse_url_candidates()
    last_error = "no candidates"
    for candidate in candidates:
        ok, detail = _probe_langfuse_api(candidate)
        if ok:
            if candidate != ui_base:
                logger.info("Langfuse API base=%s (LANGFUSE_BASE_URL was %s)", candidate, ui_base)
            return candidate
        last_error = detail
        logger.debug("Langfuse API probe failed for %s: %s", candidate, detail)

    logger.warning(
        "Langfuse health probe failed (last: %s). Still using LANGFUSE_BASE_URL=%s",
        last_error,
        ui_base,
    )
    return ui_base


def _otlp_traces_endpoint(base_url: str) -> str:
    """OTLP ingest URL: explicit override or {LANGFUSE_BASE_URL}/api/public/otel/v1/traces."""
    override = _cfg_str("LANGFUSE_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if override:
        return override.rstrip("/")
    return f"{base_url.rstrip('/')}/api/public/otel/v1/traces"


def _validate_langfuse_connectivity(base_url: str) -> bool:
    """
    Preflight GET /api/public/health (same auth as the working CaaS demo).

    Empty OTLP POST often returns 401 even when tracing works; health is the reliable check.
    """
    if _cfg_bool("LANGFUSE_SKIP_CONNECTIVITY_CHECK", default=False):
        return True

    if _requires_gcass_proxy(base_url) and not _gcass_proxy_token():
        logger.error(
            "GCAAS_API_TOKEN is not set — PwC CaaS requires Proxy-Authorization on every "
            "Langfuse request. Add your Global CaaS API token to .env (or Key Vault secret "
            "gcass-api-token). HOSTEDAPPS_KEY is also accepted as an alias."
        )
        return False

    url = f"{base_url.rstrip('/')}/api/public/health"
    try:
        import requests

        response = requests.get(
            url,
            headers=_gcass_proxy_headers(include_langfuse_auth=True),
            verify=_langfuse_http_verify(),
            timeout=15,
        )
        content_type = (response.headers.get("content-type") or "").lower()
        body = (response.text or "")[:200]
        is_html = "html" in content_type or body.lstrip().startswith("<!")
        if is_html:
            logger.error(
                "Langfuse health check returned HTML (not the API): %s. "
                "Confirm LANGFUSE_BASE_URL includes /api/ after the domain.",
                url,
            )
            return False
        if response.status_code == 200:
            return True
        if response.status_code == 401:
            if _requires_gcass_proxy(base_url) and not _gcass_proxy_token():
                logger.error(
                    "Langfuse health check 401 at %s — set GCAAS_API_TOKEN (Proxy-Authorization).",
                    url,
                )
            else:
                logger.error(
                    "Langfuse health check 401 at %s — verify GCAAS_API_TOKEN, LANGFUSE_PUBLIC_KEY, "
                    "and LANGFUSE_SECRET_KEY are all from the same hosted project.",
                    url,
                )
            return False
        logger.warning(
            "Langfuse health check returned %s at %s — continuing init anyway.",
            response.status_code,
            url,
        )
        return True
    except Exception as exc:
        logger.warning("Langfuse connectivity check failed for %s: %s", url, exc)
        return True


def _sync_langfuse_env(*, public_key: str, secret_key: str, base_url: str) -> None:
    """Mirror resolved config into os.environ for the Langfuse Python SDK."""
    os.environ["LANGFUSE_PUBLIC_KEY"] = public_key
    os.environ["LANGFUSE_SECRET_KEY"] = secret_key
    os.environ["LANGFUSE_BASE_URL"] = base_url
    os.environ["LANGFUSE_HOST"] = base_url
    if _cfg_str("LANGFUSE_API_BASE_URL"):
        os.environ["LANGFUSE_API_BASE_URL"] = _cfg_str("LANGFUSE_API_BASE_URL")
    os.environ["LANGFUSE_ENABLED"] = "true" if _cfg_bool("LANGFUSE_ENABLED") else "false"
    os.environ["LANGFUSE_SSL_VERIFY"] = "true" if _langfuse_ssl_verify() else "false"
    ca = _langfuse_ca_bundle()
    if ca:
        os.environ["LANGFUSE_CA_BUNDLE"] = ca
    otel_override = _cfg_str("LANGFUSE_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if otel_override:
        os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = otel_override
    # Langfuse SDK reads these from os.environ (BatchSpanProcessor batching).
    os.environ["LANGFUSE_FLUSH_AT"] = str(_cfg_int("LANGFUSE_FLUSH_AT", 25))
    os.environ["LANGFUSE_FLUSH_INTERVAL"] = str(_cfg_int("LANGFUSE_FLUSH_INTERVAL", 5))


def is_langfuse_enabled() -> bool:
    """Check if Langfuse is configured and enabled."""
    if not _cfg_bool("LANGFUSE_ENABLED", default=False):
        return False
    return bool(_cfg_str("LANGFUSE_PUBLIC_KEY") and _cfg_str("LANGFUSE_SECRET_KEY"))


def init_langfuse() -> bool:
    """
    Initialize Langfuse from central cfg (Key Vault / .env).
    Call this on application startup after load_secrets().
    """
    global _langfuse_initialized
    if not is_langfuse_enabled():
        return False

    public_key = _cfg_str("LANGFUSE_PUBLIC_KEY")
    secret_key = _cfg_str("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        return False

    _configure_langfuse_ssl()
    base_url = _resolve_langfuse_base_url()
    if not base_url:
        return False

    _sync_langfuse_env(public_key=public_key, secret_key=secret_key, base_url=base_url)

    otel_endpoint = _otlp_traces_endpoint(base_url)
    if not _validate_langfuse_connectivity(base_url):
        return False

    try:
        import httpx
        from langfuse import Langfuse

        timeout = _cfg_int("LANGFUSE_TIMEOUT", 30)
        proxy_headers = _gcass_proxy_headers()
        httpx_client = httpx.Client(
            headers=proxy_headers or None,
            verify=_langfuse_http_verify(),
            timeout=timeout,
        )
        Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=base_url,
            httpx_client=httpx_client,
            additional_headers=proxy_headers or None,
            timeout=timeout,
        )
        _langfuse_initialized = True
        ssl_mode = "custom-ca" if _langfuse_ca_bundle() else (
            "verify" if _langfuse_ssl_verify() else "insecure"
        )
        logger.info(
            "Langfuse observability initialized (host=%s, otel=%s, ssl=%s, caas_proxy=%s, "
            "flush_at=%s, flush_interval=%ss)",
            base_url,
            otel_endpoint,
            ssl_mode,
            "yes" if proxy_headers.get("Proxy-Authorization") else "no",
            os.environ.get("LANGFUSE_FLUSH_AT"),
            os.environ.get("LANGFUSE_FLUSH_INTERVAL"),
        )
        return True
    except Exception as exc:
        logger.warning("Langfuse enabled but failed to initialize: %s", exc)
        return False


def flush_langfuse() -> None:
    """Flush Langfuse data to server. Call after workflows and before shutdown."""
    if not is_langfuse_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
        logger.debug("Langfuse trace batch flushed")
    except Exception as exc:
        logger.warning("Failed to flush Langfuse: %s", exc)


def observe(*args: Any, **kwargs: Any) -> Callable:
    """
    Langfuse @observe when enabled; no-op decorator otherwise.
    Supports @observe and @observe(name="...").
    """
    if is_langfuse_enabled():
        try:
            from langfuse import observe as _lf_observe

            return _lf_observe(*args, **kwargs)
        except Exception:
            logger.debug("Langfuse observe unavailable", exc_info=True)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*f_args: Any, **f_kwargs: Any) -> Any:
            return func(*f_args, **f_kwargs)

        @wraps(func)
        async def async_wrapper(*f_args: Any, **f_kwargs: Any) -> Any:
            return await func(*f_args, **f_kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    if len(args) == 1 and callable(args[0]):
        return decorator(args[0])
    return decorator
