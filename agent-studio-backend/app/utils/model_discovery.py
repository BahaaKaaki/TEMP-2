"""
Dynamic LLM model discovery from the GenAI Shared Service proxy.

Fetches available models and groups them by provider
(openai, anthropic/bedrock, google/vertex_ai).
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import httpx

from app.config.llm_config import LLMConfig
from config.keyvault import cfg

logger = logging.getLogger(__name__)

CACHE_DURATION = timedelta(hours=6)
_models_cache: Dict[str, Any] = {}
_cache_timestamp: Optional[datetime] = None


def _should_exclude_model(model_name_lower: str) -> bool:
    """Check if a model should be excluded from the available models list."""
    if model_name_lower.startswith("o3"):
        return True
    if "gpt-oss" in model_name_lower:
        return True
    if "embedding" in model_name_lower:
        return True
    return False


async def fetch_genai_proxy_models() -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch available models from the GenAI Shared Service proxy.

    Returns models grouped by provider (openai, anthropic, google, other).
    Model IDs are in format: "provider.model-name"
    """
    genai_url = cfg.GENAI_PROXY_URL
    genai_key = cfg.GENAI_PROXY_API_KEY

    if not genai_url or not genai_key:
        logger.warning("GenAI proxy not configured (GENAI_PROXY_URL or GENAI_PROXY_API_KEY missing)")
        return {}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{genai_url}/models",
                headers={
                    "accept": "application/json",
                    "API-Key": genai_key,
                },
                timeout=10.0
            )

            if response.status_code != 200:
                logger.error("GenAI proxy API error: %d", response.status_code)
                return {}

            data = response.json()
            models_by_provider = {
                "openai": [],
                "anthropic": [],
                "google": [],
                "other": [],
            }

            for model_data in data.get("data", []):
                model_id = model_data.get("id", "")
                if not model_id:
                    continue

                parts = model_id.split(".", 1)
                if len(parts) < 2:
                    continue

                provider_prefix = parts[0]
                model_name = parts[1]
                model_name_lower = model_name.lower()

                if _should_exclude_model(model_name_lower):
                    continue

                model_info = {
                    "value": model_id,
                    "label": format_proxy_model_name(model_name),
                    "provider": provider_prefix,
                    "context_length": None,
                    "supports_tools": True,
                    "supports_vision": "vision" in model_name_lower or "gpt-4" in model_name_lower or "gemini" in model_name_lower or "claude" in model_name_lower,
                    "tier": estimate_tier_from_name(model_name),
                }

                categorized = False
                if any(keyword in model_name_lower for keyword in ["claude", "anthropic", "haiku", "sonnet", "opus"]):
                    models_by_provider["anthropic"].append(model_info)
                    categorized = True
                elif any(keyword in model_name_lower for keyword in ["gemini", "palm", "bard"]):
                    models_by_provider["google"].append(model_info)
                    categorized = True
                elif any(keyword in model_name_lower for keyword in ["gpt", "o1", "o3", "o4", "dall-e", "whisper", "tts"]):
                    models_by_provider["openai"].append(model_info)
                    categorized = True

                if not categorized:
                    if provider_prefix == "openai":
                        models_by_provider["openai"].append(model_info)
                    elif provider_prefix in ["vertex_ai", "google"]:
                        models_by_provider["google"].append(model_info)
                    elif "anthropic" in provider_prefix or "bedrock" in provider_prefix:
                        if "anthropic" in model_id.lower() or "claude" in model_id.lower():
                            models_by_provider["anthropic"].append(model_info)
                        else:
                            models_by_provider["other"].append(model_info)
                    else:
                        models_by_provider["other"].append(model_info)

            logger.debug(
                "Fetched models from GenAI proxy: OpenAI=%d, Anthropic=%d, Google=%d, Other=%d",
                len(models_by_provider['openai']),
                len(models_by_provider['anthropic']),
                len(models_by_provider['google']),
                len(models_by_provider['other']),
            )
            return models_by_provider

    except Exception as e:
        logger.error("Failed to fetch models from GenAI proxy: %s", e, exc_info=True)
        return {}


async def discover_all_models(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Discover all available models from the GenAI proxy.

    Args:
        force_refresh: Force refresh cache
    """
    global _models_cache, _cache_timestamp

    if not force_refresh and _cache_timestamp:
        age = datetime.now() - _cache_timestamp
        if age < CACHE_DURATION:
            logger.debug("Using cached models (age: %s)", age)
            return _models_cache

    logger.info("Discovering models from GenAI proxy...")

    proxy_models = await fetch_genai_proxy_models()

    result = {
        "providers": {
            "openai": {
                "name": "OpenAI",
                "available": bool(proxy_models.get("openai")),
                "models": proxy_models.get("openai", []),
                "requires_config": ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
            },
            "anthropic": {
                "name": "Anthropic (Claude)",
                "available": bool(proxy_models.get("anthropic")),
                "models": proxy_models.get("anthropic", []),
                "requires_config": ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
            },
            "google": {
                "name": "Google (Gemini)",
                "available": bool(proxy_models.get("google")),
                "models": proxy_models.get("google", []),
                "requires_config": ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
            },
        },
        "default_provider": "openai",
        "default_model": proxy_models.get("openai", [{}])[0].get("value", "openai.gpt-5") if proxy_models.get("openai") else "openai.gpt-5",
        "environment": LLMConfig.ENVIRONMENT,
        "last_updated": datetime.now().isoformat(),
        "using_proxy": True
    }

    _models_cache = result
    _cache_timestamp = datetime.now()
    return result


# ── Helper functions ──────────────────────────────────────────────────────


def format_proxy_model_name(model_name: str) -> str:
    """Format model names from GenAI proxy into human-readable names."""
    if model_name == "gpt-5":
        return "GPT-5"
    if model_name == "gpt-4.1":
        return "GPT-4.1"
    if model_name == "gpt-4o":
        return "GPT-4 Omni"
    if model_name == "gpt-4o-mini":
        return "GPT-4o Mini"
    if model_name == "gpt-4o-mini-transcribe":
        return "GPT-4o Mini Transcribe"
    if model_name.startswith("o3"):
        return model_name.upper().replace("-", " ").title()
    if model_name.startswith("o4"):
        return model_name.upper().replace("-", " ").title()

    if "gemini" in model_name:
        parts = model_name.replace("gemini-", "").split("-")
        version = parts[0] if parts else ""
        variant = " ".join(parts[1:]).title() if len(parts) > 1 else ""
        return f"Gemini {version} {variant}".strip()

    if "claude" in model_name:
        clean_name = model_name
        if "anthropic." in clean_name:
            clean_name = clean_name.split("anthropic.")[-1]
        clean_name = clean_name.replace("claude-", "")
        if "haiku" in clean_name:
            version = clean_name.split("haiku-")[-1].replace("-", ".")
            return f"Claude Haiku {version}"
        elif "sonnet" in clean_name:
            version = clean_name.split("sonnet-")[-1].replace("-", ".")
            return f"Claude Sonnet {version}"
        elif "opus" in clean_name:
            version = clean_name.split("opus-")[-1].replace("-", ".")
            return f"Claude Opus {version}"
        else:
            return f"Claude {clean_name.replace('-', ' ').title()}"

    if "gpt-oss" in model_name:
        size = model_name.split("-")[-1]
        return f"GPT OSS {size.upper()}"

    return model_name.replace("-", " ").replace("_", " ").title()


def estimate_tier_from_name(model_name: str) -> str:
    """Estimate pricing tier from model name."""
    model_lower = model_name.lower()
    if any(keyword in model_lower for keyword in ["gpt-5", "gpt-4.1", "opus", "sonnet-4", "o3-deep", "pro"]):
        return "premium"
    if any(keyword in model_lower for keyword in ["mini", "haiku", "nano", "lite", "flash", "20b"]):
        return "basic"
    return "standard"
