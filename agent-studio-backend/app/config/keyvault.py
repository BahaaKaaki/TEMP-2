"""
Central application configuration — single source of truth.

Every variable is defined **once** in ``_REGISTRY`` below with:
  - name        → attribute name on ``cfg``
  - source      → ``"keyvault"`` or ``"env"``
  - default     → fallback when neither KV nor env provides a value
  - cast        → type coercion (``bool``, ``int``, ``float``) — strings need no cast
  - kv          → Key Vault secret name (only for ``source="keyvault"``)

Secrets (``source="keyvault"``) **never** touch ``os.environ``.

Usage — one import at the top of each file:

    from config.keyvault import cfg

    cfg.GENAI_PROXY_API_KEY   # source: keyvault
    cfg.DATABASE_HOST          # source: env
"""

import os
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY — every config variable the app needs, defined exactly once.
#
#   source="keyvault"  →  fetched from Azure Key Vault (kv= field),
#                         falls back to os.getenv for local dev.
#                         Value never written to os.environ.
#
#   source="env"       →  always read from os.getenv / .env file.
# ═══════════════════════════════════════════════════════════════════════════

_REGISTRY: list[dict] = [
    # ── Secrets (Azure Key Vault → .env fallback) ─────────────────────
    {"name": "GENAI_PROXY_API_KEY",     "source": "keyvault", "kv": "genai-proxy-api-key"},
    {"name": "MICROSOFT_CLIENT_SECRET", "source": "keyvault", "kv": "microsoft-client-secret"},
    {"name": "JWT_SECRET_KEY",          "source": "keyvault", "kv": "jwt-secret-key"},
    # Fernet key used to encrypt each user's stored Microsoft OAuth refresh
    # token in the `ms_oauth_token` table. Same value MUST be used across all
    # backend replicas and persisted across restarts — losing it invalidates
    # every stored token (users will re-auth via SSO; nothing else breaks).
    {"name": "MS_TOKEN_ENCRYPTION_KEY", "source": "keyvault", "kv": "ms-token-encryption-key"},
    # Langfuse project API keys (optional — observability off when empty)
    {"name": "LANGFUSE_PUBLIC_KEY", "source": "keyvault", "kv": "langfuse-public-key", "default": ""},
    {"name": "LANGFUSE_SECRET_KEY", "source": "keyvault", "kv": "langfuse-secret-key", "default": ""},
    # PwC CaaS proxy token (Proxy-Authorization header on Langfuse HTTP/OTLP)
    {"name": "GCAAS_API_TOKEN",       "source": "keyvault", "kv": "gcass-api-token", "default": ""},

    # ── Langfuse observability (env / .env; secrets above from Key Vault) ─
    {"name": "LANGFUSE_ENABLED",        "source": "env", "default": False, "cast": bool},
    # Hosted Langfuse URL from Settings → API Keys (same page as pk/sk)
    {"name": "LANGFUSE_BASE_URL",       "source": "env", "default": ""},
    {"name": "LANGFUSE_API_BASE_URL",   "source": "env", "default": ""},
    {"name": "LANGFUSE_TRUST_BASE_URL", "source": "env", "default": True, "cast": bool},
    # Full OTLP URL override if ingress exposes API on a different path than the UI
    {"name": "LANGFUSE_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "source": "env", "default": ""},
    # Alias seen in some CaaS demos (falls back if GCAAS_API_TOKEN unset)
    {"name": "HOSTEDAPPS_KEY",          "source": "env", "default": ""},
    {"name": "LANGFUSE_INSERT_API_PATH", "source": "env", "default": True, "cast": bool},
    {"name": "LANGFUSE_SKIP_CONNECTIVITY_CHECK", "source": "env", "default": False, "cast": bool},
    # OTLP batch export (Langfuse BatchSpanProcessor) — same in dev and prod
    {"name": "LANGFUSE_FLUSH_AT",       "source": "env", "default": 25,  "cast": int},
    {"name": "LANGFUSE_FLUSH_INTERVAL", "source": "env", "default": 5,   "cast": int},
    {"name": "LANGFUSE_HOST",           "source": "env", "default": ""},
    {"name": "LANGFUSE_SSL_VERIFY",     "source": "env", "default": True,  "cast": bool},
    {"name": "LANGFUSE_CA_BUNDLE",      "source": "env", "default": ""},
    {"name": "LANGFUSE_TIMEOUT",        "source": "env", "default": 30,   "cast": int},

    # ── LLM / GenAI Proxy ─────────────────────────────────────────────
    {"name": "ENVIRONMENT",          "source": "env", "default": "development"},
    {"name": "GENAI_PROXY_URL",      "source": "env"},
    {"name": "DEFAULT_LLM_MODEL",    "source": "env", "default": "openai.gpt-5"},
    {"name": "DEFAULT_LLM_PROVIDER", "source": "env", "default": "openai"},
    {"name": "DEFAULT_TEMPERATURE",  "source": "env", "default": 0.7,  "cast": float},
    {"name": "DEFAULT_MAX_TOKENS",   "source": "env", "default": 4096, "cast": int},
    {"name": "LLM_TIMEOUT",          "source": "env", "default": 240,  "cast": int},
    {"name": "MAX_TOOL_ITERATIONS",  "source": "env", "default": 10,   "cast": int},
    {"name": "LLM_REASONING_SUMMARY_MODE", "source": "env", "default": "auto"},
    {"name": "LLM_REASONING_EFFORT",       "source": "env"},

    # ── Edwin (PowerPoint handoff) ─────────────────────────────────────
    {"name": "EDWIN_API_URL",              "source": "env"},

    # ── Database (PostgreSQL) ( There are no passwords in cloud environment this is for local devlopment) ─────────────────────────────────────────
    {"name": "POSTGRES_USER",           "source": "env"},
    {"name": "POSTGRES_PASSWORD",       "source": "env"},
    {"name": "ADMIN_POSTGRES_USER",     "source": "env"},
    {"name": "ADMIN_POSTGRES_PASSWORD", "source": "env"},
    {"name": "POSTGRES_DB",             "source": "env"},
    {"name": "DATABASE_HOST",           "source": "env", "default": "localhost"},
    {"name": "DATABASE_PRIMARY_HOST",   "source": "env"},
    {"name": "USE_ENTRA_AUTH",          "source": "env", "default": False, "cast": bool},
    {"name": "POSTGRES_SSL",            "source": "env", "default": True,  "cast": bool},
    {"name": "AZURE_CLIENT_ID_PGSQL",   "source": "env"},
    {"name": "INSTANCE_ID",             "source": "env"},

    # ── Redis ─────────────────────────────────────────────────────────
    {"name": "REDIS_HOST",               "source": "env", "default": "localhost"},
    {"name": "REDIS_PORT",               "source": "env", "default": 6379,  "cast": int},
    {"name": "REDIS_DB",                 "source": "env", "default": 0,     "cast": int},
    {"name": "REDIS_PASSWORD",           "source": "env"},
    {"name": "REDIS_SSL",                "source": "env", "default": False, "cast": bool},
    {"name": "REDIS_SSL_CERT_REQS",      "source": "env"},
    {"name": "REDIS_SSL_CA_CERTS",       "source": "env"},
    {"name": "REDIS_USE_ENTRA_AUTH",     "source": "env", "default": False, "cast": bool},
    {"name": "AZURE_CLIENT_ID_REDIS",    "source": "env"},
    {"name": "REDIS_ENTRA_PRINCIPAL_ID", "source": "env"},
    {"name": "REDIS_URL",               "source": "env"},

    # ── Azure Storage ─────────────────────────────────────────────────
    {"name": "AZURE_STORAGE_CONTAINER_NAME",       "source": "env", "default": "documents"},
    {"name": "AZURE_STORAGE_USE_MANAGED_IDENTITY", "source": "env", "default": False, "cast": bool},
    {"name": "AZURE_STORAGE_ACCOUNT_NAME",         "source": "env"},
    {"name": "AZURE_CLIENT_ID_ADSLGEN2",           "source": "env"},
    {"name": "AZURE_STORAGE_CONNECTION_STRING",     "source": "env"},

    # ── Search Tools ──────────────────────────────────────────────────
    {"name": "GOOGLE_API_KEY", "source": "env"},
    {"name": "GOOGLE_CSE_ID",  "source": "env"},

    # ── Workflow Limits ───────────────────────────────────────────────
    {"name": "MAX_MESSAGES_IN_MEMORY",      "source": "env", "default": 100, "cast": int},
    {"name": "MAX_NODE_OUTPUTS_IN_MEMORY",  "source": "env", "default": 50,  "cast": int},
    {"name": "MAX_CHECKPOINTS_PER_SESSION", "source": "env", "default": 100, "cast": int},

    # ── Sandbox (Code Executor) ───────────────────────────────────────
    {"name": "SANDBOX_PROVIDER",                "source": "env", "default": "docker"},
    {"name": "SANDBOX_IMAGE",                   "source": "env", "default": "agent-studio-sandbox:latest"},
    # Legacy fixed pool size. Kept for backwards compatibility — if set,
    # takes precedence over SANDBOX_HOT_TIER_MIN.
    {"name": "SANDBOX_WARM_POOL_SIZE",          "source": "env", "default": None,    "cast": int},
    {"name": "SANDBOX_POOL_PARALLEL_CREATE",    "source": "env", "default": 2,    "cast": int},
    {"name": "SANDBOX_CREATE_MAX_RETRIES",      "source": "env", "default": 3,    "cast": int},
    {"name": "SANDBOX_CREATE_RETRY_BASE_SECONDS", "source": "env", "default": 2.0, "cast": float},
    {"name": "SANDBOX_CONTAINER_TTL_MINUTES",   "source": "env", "default": 30,   "cast": int},
    # Two-tier autoscaling pool. The hot tier is always running and
    # immediately acquirable. The cold tier is pre-created but STOPPED,
    # billing ~$0 while still being far faster than cold-create on demand.
    {"name": "SANDBOX_HOT_TIER_MIN",            "source": "env", "default": 2,    "cast": int},
    {"name": "SANDBOX_HOT_TIER_HEADROOM",       "source": "env", "default": 2,    "cast": int},
    {"name": "SANDBOX_COLD_TIER_TARGET",        "source": "env", "default": 5,    "cast": int},
    {"name": "SANDBOX_REBALANCER_INTERVAL_SECONDS", "source": "env", "default": 60, "cast": int},
    # Reservation (hold-during-pause) and wash-and-reuse cycle.
    {"name": "SANDBOX_PAUSE_IDLE_TIMEOUT_SECONDS", "source": "env", "default": 600, "cast": int},
    {"name": "SANDBOX_WASH_CYCLE_ENABLED",      "source": "env", "default": True, "cast": bool},
    {"name": "SANDBOX_WASH_CYCLE_TIMEOUT_SECONDS", "source": "env", "default": 15, "cast": int},
    {"name": "SANDBOX_ACI_RESOURCE_GROUP",      "source": "env"},
    {"name": "SANDBOX_ACI_SUBNET_ID",           "source": "env"},
    {"name": "SANDBOX_ACI_CPU",                 "source": "env", "default": 1.0,  "cast": float},
    {"name": "SANDBOX_ACI_MEMORY_GB",           "source": "env", "default": 1.5,  "cast": float},
    # Base URL the sandbox uses to call back into the host (Code Executor KB
    # endpoints). Default targets Docker Desktop's host.docker.internal on Mac
    # / Windows; override in prod with the backend's VNet-reachable URL.
    {"name": "SANDBOX_HOST_CALLBACK_URL",       "source": "env", "default": "http://host.docker.internal:8000"},
    # Optional: private IP to resolve SANDBOX_HOST_CALLBACK_URL's hostname
    # to from inside the sandbox. Used in ACA internal environments where
    # public DNS for the callback host returns a non-routable address
    # (e.g. Private Endpoint IP like 10.66.170.165). The sandbox SDK
    # installs a process-local getaddrinfo override; nothing is written
    # to /etc/hosts and no other hostname is affected.
    {"name": "SANDBOX_KB_PRIVATE_IP",           "source": "env", "default": ""},

    {"name": "SANDBOX_REGISTRY_SERVER",           "source": "env"},
    {"name": "SANDBOX_REGISTRY_USERNAME",         "source": "env"},
    {"name": "SANDBOX_REGISTRY_PASSWORD",         "source": "env"},
    # When set, the ACI provider pulls images using a user-assigned managed
    # identity instead of username/password (required for ACR without admin
    # user enabled).  This is the UAMI resource ID, e.g.
    # /subscriptions/.../userAssignedIdentities/my-aci-pull-uami
    {"name": "SANDBOX_REGISTRY_IDENTITY_RESOURCE_ID", "source": "env"},

    # ── Audit Logging ──────────────────────────────────────────────────
    {"name": "AUDIT_LOG_ENABLED",                  "source": "env", "default": True, "cast": bool},

    {"name": "AZURE_CLIENT_ID_ACI",             "source": "env"},
    {"name": "AZURE_SUBSCRIPTION_ID",           "source": "env"},
    {"name": "AZURE_LOCATION",                  "source": "env", "default": "eastus"},

    # ── Key Vault bootstrap (always env — KV can't fetch its own URL) ─
    {"name": "AZURE_KEYVAULT_URL",       "source": "env"},
    {"name": "AZURE_CLIENT_ID_KEYVAULT", "source": "env"},
]


# ═══════════════════════════════════════════════════════════════════════════
# Singleton — import ``cfg`` everywhere, attributes set by load_secrets()
# ═══════════════════════════════════════════════════════════════════════════

class _AppConfig:
    """Populated once at startup. Do not instantiate directly."""
    pass


cfg = _AppConfig()

# Pre-set defaults so attributes exist before load_secrets() runs
for _entry in _REGISTRY:
    setattr(cfg, _entry["name"], _entry.get("default"))


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════

_kv_client = None


def _build_kv_client():
    """Build and cache the Key Vault SecretClient (singleton)."""
    global _kv_client
    if _kv_client is not None:
        return _kv_client

    vault_url = os.getenv("AZURE_KEYVAULT_URL")
    if not vault_url:
        return None

    from azure.keyvault.secrets import SecretClient

    uami_client_id = os.getenv("AZURE_CLIENT_ID_KEYVAULT")
    if uami_client_id:
        from azure.identity import ManagedIdentityCredential
        credential = ManagedIdentityCredential(client_id=uami_client_id)
        logger.info("Key Vault auth: UAMI (client_id=%s...)", uami_client_id[:8])
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        logger.info("Key Vault auth: DefaultAzureCredential (az CLI / system MI)")

    _kv_client = SecretClient(vault_url=vault_url, credential=credential)
    return _kv_client


def _cast(raw: str, cast_type):
    """Coerce a raw env-var string to the declared type."""
    if cast_type is bool:
        return raw.lower() in ("true", "1", "yes")
    if cast_type is int:
        return int(raw)
    if cast_type is float:
        return float(raw)
    return raw


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def _log(msg: str, level: str = "INFO") -> None:
    """Print to stdout (always visible) AND logger. Runs before logging is configured."""
    import sys
    print(f"[keyvault] {level}: {msg}", file=sys.stderr, flush=True)
    if level == "ERROR":
        logger.error(msg)
    else:
        logger.info(msg)


def load_secrets() -> None:
    """
    Walk ``_REGISTRY`` once and populate every attribute on ``cfg``.

    Call **once** at the top of ``main.py`` before any other app import.
    """
    _log("load_secrets() starting...")

    # 1. Load .env so os.getenv sees local-dev values
    try:
        from dotenv import load_dotenv
        load_dotenv()
        _log(".env loaded")
    except ImportError:
        _log(".env skipped (python-dotenv not installed)")

    # 2. Build KV client (if vault URL is configured)
    vault_url = os.getenv("AZURE_KEYVAULT_URL")
    kv = None
    if vault_url:
        _log(f"AZURE_KEYVAULT_URL={vault_url}")
        try:
            kv = _build_kv_client()
            _log("Key Vault client built OK")
        except Exception as exc:
            _log(f"Key Vault init FAILED: {exc} — secrets fall back to env", "ERROR")
    else:
        _log("No AZURE_KEYVAULT_URL set — using env / .env only")

    # 3. Single pass over the registry
    kv_loaded, kv_failed, kv_total = 0, 0, 0
    kv_results: list[str] = []

    for entry in _REGISTRY:
        name    = entry["name"]
        source  = entry["source"]
        default = entry.get("default")
        cast    = entry.get("cast")

        if source == "keyvault":
            kv_total += 1
            value = None
            origin = None

            if kv:
                try:
                    secret = kv.get_secret(entry["kv"])
                    if secret.value:
                        value = secret.value
                        kv_loaded += 1
                        origin = "keyvault"
                except Exception as exc:
                    kv_failed += 1
                    _log(
                        f"KEYVAULT FETCH FAILED for '{name}' (kv={entry['kv']}): {exc}",
                        "ERROR",
                    )

            if value is None:
                value = os.getenv(name)
                if value:
                    origin = "env-fallback"

            if value is not None:
                setattr(cfg, name, value)
            elif default is not None:
                setattr(cfg, name, default)
                origin = "default"

            final = getattr(cfg, name, None)
            if final is None:
                origin = "MISSING"
                _log(
                    f"SECRET '{name}' is None — not in Key Vault, not in env, "
                    f"no default. Features depending on it WILL fail.",
                    "ERROR",
                )

            kv_results.append(f"  {name}: {origin}")

        else:  # source == "env"
            raw = os.getenv(name)
            # Treat empty strings as "unset" so that e.g. an unset GitHub
            # Actions variable (which renders as `FOO=` in the deployment
            # command) falls through to the registered default instead of
            # crashing `_cast("", int)` at startup.
            if raw is not None and raw != "":
                try:
                    setattr(cfg, name, _cast(raw, cast) if cast else raw)
                except (ValueError, TypeError) as exc:
                    _log(
                        f"Invalid value for env '{name}'='{raw}' "
                        f"(cast={getattr(cast, '__name__', cast)}): {exc} "
                        f"— falling back to default {default!r}",
                        "ERROR",
                    )
                    if default is not None:
                        setattr(cfg, name, default)
            elif default is not None:
                setattr(cfg, name, default)

    # 4. Summary
    if vault_url:
        status = "OK" if kv_failed == 0 else "DEGRADED"
        _log(f"Key Vault [{status}]: {kv_loaded}/{kv_total} from vault, {kv_failed} failed | {vault_url}")
        for line in kv_results:
            _log(line)
    else:
        _log("All config loaded from env / .env")

    _log("load_secrets() complete")
