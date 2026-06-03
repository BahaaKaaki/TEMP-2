"""
Normalize LLM model identifiers to GenAI proxy format.

Mirrors prefix rules in LLMClientManager.get_client so inventory,
workflow scans, and runtime resolution stay consistent.
"""
from __future__ import annotations

from typing import Optional


def normalize_model_name(model: str, provider: Optional[str] = None) -> str:
    """Return proxy-prefixed model id (e.g. openai.gpt-5)."""
    if not model or not str(model).strip():
        from app.config.llm_config import LLMConfig
        return normalize_model_name(LLMConfig.DEFAULT_MODEL, LLMConfig.DEFAULT_PROVIDER)

    model = str(model).strip()
    lowered = model.lower()
    if any(
        lowered.startswith(p)
        for p in ("openai.", "vertex_ai.", "bedrock.", "anthropic.", "google.")
    ):
        return model

    provider_map = {
        "openai": "openai",
        "anthropic": "anthropic",
        "google": "google",
        "bedrock": "bedrock",
        "other": "openai",
    }
    normalized_provider = provider_map.get((provider or "openai").lower(), "openai")

    if normalized_provider == "google" or "gemini" in lowered:
        return f"vertex_ai.{model}"
    if normalized_provider in ("anthropic", "bedrock") or "claude" in lowered:
        bare = model.replace("bedrock.", "").replace("anthropic.", "")
        if "bedrock" in lowered:
            return f"bedrock.anthropic.{bare}"
        return f"bedrock.anthropic.{model}"
    return f"openai.{model}"


def infer_provider(model_name: str) -> str:
    lowered = (model_name or "").lower()
    if lowered.startswith("vertex_ai.") or "gemini" in lowered:
        return "google"
    if lowered.startswith("bedrock.") or "claude" in lowered:
        return "anthropic"
    return "openai"
