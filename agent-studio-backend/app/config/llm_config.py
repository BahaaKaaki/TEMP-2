"""
Centralized LLM configuration and client management.

All LLM requests are routed through the GenAI Shared Service proxy,
which provides an OpenAI-compatible API for all providers (OpenAI,
Anthropic/Claude, Google/Gemini, etc.).
"""
import os
from enum import Enum
from typing import Optional, Dict, Any
from langchain_openai import ChatOpenAI
import logging
from app.tracing.langchain import TracedChatModel

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Logical provider names used for model-prefix routing through the proxy."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class OpenAIModel(str, Enum):
    """OpenAI model names."""
    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4_TURBO = "gpt-4-turbo"
    O1 = "o1"
    O1_MINI = "o1-mini"
    O1_PREVIEW = "o1-preview"
    GPT_35_TURBO = "gpt-3.5-turbo"


class AnthropicModel(str, Enum):
    """Anthropic model names."""
    CLAUDE_35_SONNET = "claude-3-5-sonnet-20241022"
    CLAUDE_35_SONNET_LEGACY = "claude-3-5-sonnet-20240620"
    CLAUDE_3_OPUS = "claude-3-opus-20240229"
    CLAUDE_3_SONNET = "claude-3-sonnet-20240229"
    CLAUDE_3_HAIKU = "claude-3-haiku-20240307"


OPENAI_MODEL_METADATA = {
    "gpt-4o": {
        "label": "GPT-4 Omni",
        "description": "Most advanced multimodal model with vision and tools",
        "context_length": 128000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "premium",
        "recommended_for": ["complex reasoning", "vision tasks", "tool usage"]
    },
    "gpt-4o-mini": {
        "label": "GPT-4 Omni Mini",
        "description": "Fast and affordable model with strong performance",
        "context_length": 128000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "standard",
        "recommended_for": ["general tasks", "fast responses", "cost-effective"]
    },
    "gpt-4-turbo": {
        "label": "GPT-4 Turbo",
        "description": "High-performance model with vision capabilities",
        "context_length": 128000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "premium",
        "recommended_for": ["complex tasks", "long context"]
    },
    "o1": {
        "label": "O1",
        "description": "Advanced reasoning model for complex problem solving",
        "context_length": 200000,
        "supports_tools": False,
        "supports_vision": False,
        "supports_json_mode": False,
        "tier": "premium",
        "recommended_for": ["complex reasoning", "mathematics", "coding"]
    },
    "o1-mini": {
        "label": "O1 Mini",
        "description": "Faster reasoning model for STEM tasks",
        "context_length": 128000,
        "supports_tools": False,
        "supports_vision": False,
        "supports_json_mode": False,
        "tier": "standard",
        "recommended_for": ["coding", "mathematics", "science"]
    },
    "o1-preview": {
        "label": "O1 Preview",
        "description": "Preview of advanced reasoning capabilities",
        "context_length": 128000,
        "supports_tools": False,
        "supports_vision": False,
        "supports_json_mode": False,
        "tier": "premium",
        "recommended_for": ["complex reasoning", "research"]
    },
    "gpt-3.5-turbo": {
        "label": "GPT-3.5 Turbo",
        "description": "Fast and affordable legacy model",
        "context_length": 16385,
        "supports_tools": True,
        "supports_vision": False,
        "supports_json_mode": True,
        "tier": "basic",
        "deprecated": True,
        "recommended_for": ["simple tasks", "legacy support"]
    }
}

ANTHROPIC_MODEL_METADATA = {
    "claude-3-5-sonnet-20241022": {
        "label": "Claude 3.5 Sonnet",
        "description": "Most intelligent model with improved coding and reasoning",
        "context_length": 200000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "premium",
        "recommended_for": ["complex reasoning", "coding", "analysis"]
    },
    "claude-3-5-sonnet-20240620": {
        "label": "Claude 3.5 Sonnet (Legacy)",
        "description": "Previous version of Claude 3.5 Sonnet",
        "context_length": 200000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "premium",
        "deprecated": True,
        "recommended_for": ["legacy support"]
    },
    "claude-3-opus-20240229": {
        "label": "Claude 3 Opus",
        "description": "Most powerful model for highly complex tasks",
        "context_length": 200000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "premium",
        "recommended_for": ["complex reasoning", "research", "analysis"]
    },
    "claude-3-sonnet-20240229": {
        "label": "Claude 3 Sonnet",
        "description": "Balanced performance and speed",
        "context_length": 200000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "standard",
        "recommended_for": ["general tasks", "balanced performance"]
    },
    "claude-3-haiku-20240307": {
        "label": "Claude 3 Haiku",
        "description": "Fastest model for quick tasks",
        "context_length": 200000,
        "supports_tools": True,
        "supports_vision": True,
        "supports_json_mode": True,
        "tier": "basic",
        "recommended_for": ["fast responses", "simple tasks", "cost-effective"]
    }
}


class LLMConfig:
    """LLM configuration — reads from central config (config.keyvault.cfg)."""

    from config.keyvault import cfg as _cfg

    ENVIRONMENT = _cfg.ENVIRONMENT
    GENAI_PROXY_URL = _cfg.GENAI_PROXY_URL
    GENAI_PROXY_API_KEY = _cfg.GENAI_PROXY_API_KEY
    DEFAULT_MODEL = _cfg.DEFAULT_LLM_MODEL
    DEFAULT_PROVIDER = _cfg.DEFAULT_LLM_PROVIDER
    DEFAULT_TEMPERATURE = _cfg.DEFAULT_TEMPERATURE
    DEFAULT_MAX_TOKENS = _cfg.DEFAULT_MAX_TOKENS
    DEFAULT_TIMEOUT = _cfg.LLM_TIMEOUT
    MAX_TOOL_ITERATIONS = _cfg.MAX_TOOL_ITERATIONS
    REASONING_SUMMARY_MODE = _cfg.LLM_REASONING_SUMMARY_MODE
    REASONING_EFFORT = _cfg.LLM_REASONING_EFFORT

    @classmethod
    def get_default_provider(cls) -> str:
        return cls.DEFAULT_PROVIDER

    @classmethod
    def get_model_enum(cls, provider: str, model_name: str) -> Optional[Enum]:
        """Get model enum from string."""
        if provider == LLMProvider.OPENAI:
            try:
                return OpenAIModel(model_name)
            except ValueError:
                return model_name
        elif provider == LLMProvider.ANTHROPIC:
            try:
                return AnthropicModel(model_name)
            except ValueError:
                return model_name
        return model_name

    @classmethod
    def validate_model(cls, provider: str, model_name: str) -> bool:
        """Validate if model exists for provider."""
        if provider == LLMProvider.OPENAI:
            return any(m.value == model_name for m in OpenAIModel)
        elif provider == LLMProvider.ANTHROPIC:
            return any(m.value == model_name for m in AnthropicModel)
        return False

    @classmethod
    def get_model_metadata(cls, provider: str, model_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific model."""
        if provider == LLMProvider.OPENAI:
            return OPENAI_MODEL_METADATA.get(model_name)
        elif provider == LLMProvider.ANTHROPIC:
            return ANTHROPIC_MODEL_METADATA.get(model_name)
        return None

    @classmethod
    def get_available_models(cls, provider: str) -> list:
        """Get list of available models for a provider with metadata."""
        models = []
        if provider == LLMProvider.OPENAI:
            for model in OpenAIModel:
                metadata = OPENAI_MODEL_METADATA.get(model.value, {})
                models.append({"value": model.value, "label": metadata.get("label", model.value), **metadata})
        elif provider == LLMProvider.ANTHROPIC:
            for model in AnthropicModel:
                metadata = ANTHROPIC_MODEL_METADATA.get(model.value, {})
                models.append({"value": model.value, "label": metadata.get("label", model.value), **metadata})
        return models

    @classmethod
    def get_all_providers_with_models(cls) -> Dict[str, Any]:
        """Get all providers with their available models and status."""
        proxy_configured = bool(cls.GENAI_PROXY_URL and cls.GENAI_PROXY_API_KEY)
        return {
            "providers": {
                "openai": {
                    "name": "OpenAI",
                    "available": proxy_configured,
                    "models": cls.get_available_models(LLMProvider.OPENAI) if proxy_configured else [],
                    "requires_config": ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
                },
                "anthropic": {
                    "name": "Anthropic",
                    "available": proxy_configured,
                    "models": cls.get_available_models(LLMProvider.ANTHROPIC) if proxy_configured else [],
                    "requires_config": ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
                },
            },
            "default_provider": cls.get_default_provider(),
            "default_model": cls.DEFAULT_MODEL,
            "environment": cls.ENVIRONMENT
        }


class LLMClientManager:
    """
    Centralized LLM client manager with connection pooling.

    All providers are routed through the GenAI Shared Service proxy,
    which exposes an OpenAI-compatible API. ChatOpenAI is used as the
    universal client.

    Prompt caching (Anthropic/Google cache_control, OpenAI prompt_cache_key)
    is applied in TracedChatModel via app.llm.prompt_cache — always on, no env flags.
    """

    _clients: Dict[str, Any] = {}
    _http_client: Optional[Any] = None

    @classmethod
    def _get_http_client(cls) -> Any:
        """Get or create shared HTTP client with connection pooling."""
        if cls._http_client is None:
            try:
                import httpx
                cls._http_client = httpx.AsyncClient(
                    limits=httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                        keepalive_expiry=30.0
                    ),
                    timeout=httpx.Timeout(240.0, connect=10.0),
                    follow_redirects=True
                )
                logger.debug("Created shared HTTP client with connection pooling (max_conn=100, keepalive=20)")
            except ImportError:
                logger.warning("httpx not available, connection pooling disabled")
                return None
        return cls._http_client

    @classmethod
    async def close_all(cls) -> None:
        """Close all LLM clients and HTTP connections."""
        logger.info("Closing all LLM clients...")
        if cls._http_client is not None:
            try:
                await cls._http_client.aclose()
                cls._http_client = None
                logger.info("Shared HTTP client closed")
            except Exception as e:
                logger.warning(f"Error closing HTTP client: {e}")
        cls._clients.clear()
        logger.info("LLM client cache cleared")

    @classmethod
    def get_client(
        cls,
        provider: str = None,
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
        timeout: int = None,
        streaming: bool = False,
        stream_chat: bool = False,
        binding_key: str = None,
        llm_role: str = None,
        **kwargs
    ) -> Any:
        """
        Get or create LLM client routed through the GenAI proxy.

        The provider/model are used to build the proxy model prefix
        (e.g. "openai.gpt-5", "bedrock.anthropic.claude-sonnet-4-5").
        """
        provider = provider or LLMConfig.DEFAULT_PROVIDER
        model = model or LLMConfig.DEFAULT_MODEL
        temperature = temperature if temperature is not None else LLMConfig.DEFAULT_TEMPERATURE
        max_tokens = max_tokens or LLMConfig.DEFAULT_MAX_TOKENS
        timeout = timeout or LLMConfig.DEFAULT_TIMEOUT
        streaming = bool(streaming or stream_chat)

        provider_map = {
            'openai': 'openai',
            'anthropic': 'anthropic',
            'google': 'google',
            'other': 'other',
            LLMProvider.OPENAI: 'openai',
            LLMProvider.ANTHROPIC: 'anthropic',
        }
        normalized_provider = provider_map.get(provider, 'openai')

        original_model = model
        has_prefix = any(model.startswith(prefix) for prefix in ['openai.', 'vertex_ai.', 'bedrock.', 'anthropic.', 'google.'])

        if not has_prefix:
            if normalized_provider == 'google' or 'gemini' in model.lower():
                model = f"vertex_ai.{model}"
                logger.debug("Added vertex_ai prefix: '%s' -> '%s'", original_model, model)
            elif normalized_provider == 'anthropic' or 'claude' in model.lower():
                if 'bedrock' in model.lower():
                    model = f"bedrock.anthropic.{model.replace('bedrock.', '').replace('anthropic.', '')}"
                else:
                    model = f"bedrock.anthropic.{model}"
                logger.debug("Added anthropic prefix: '%s' -> '%s'", original_model, model)
            else:
                model = f"openai.{model}"
                logger.debug("Added openai prefix: '%s' -> '%s'", original_model, model)
        else:
            logger.debug("Model already has prefix: '%s'", model)

        reasoning_cache_key = (
            f":reasoning={LLMConfig.REASONING_SUMMARY_MODE}:"
            f"{LLMConfig.REASONING_EFFORT}"
        )
        bk_suffix = f":bk={binding_key}" if binding_key else ""
        role_suffix = f":role={llm_role}" if llm_role else ""
        cache_key = (
            f"proxy:{model}:{temperature}:{max_tokens}"
            f":streaming={bool(streaming)}:stream_chat={bool(stream_chat)}"
            f"{reasoning_cache_key}{bk_suffix}{role_suffix}"
        )

        if cache_key in cls._clients:
            logger.debug("Using cached proxy client for: %s", model)
            return cls._clients[cache_key]

        logger.info("Creating GenAI proxy client with model: '%s'", model)
        client = cls._create_proxy_client(
            model,
            temperature,
            max_tokens,
            timeout,
            streaming=streaming,
            **kwargs,
        )
        client = TracedChatModel(
            client,
            model=model,
            stream_trace=streaming,
            stream_chat=stream_chat,
            metadata={
                "provider": normalized_provider,
                "max_tokens": max_tokens,
                "streaming": bool(streaming),
            },
            binding_key=binding_key,
            llm_role=llm_role,
        )
        cls._clients[cache_key] = client
        return client

    @classmethod
    def _create_proxy_client(
        cls,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
        streaming: bool = False,
        **kwargs
    ) -> ChatOpenAI:
        """Create a ChatOpenAI client pointed at the GenAI proxy."""
        if not LLMConfig.GENAI_PROXY_URL or not LLMConfig.GENAI_PROXY_API_KEY:
            raise RuntimeError(
                "GenAI proxy not configured. Set GENAI_PROXY_URL and GENAI_PROXY_API_KEY."
            )

        model_lower = (model or "").lower()
        skip_temperature = any(tag in model_lower for tag in ("o1", "o3", "o4", "gpt-5"))

        config = {
            "model": model,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "base_url": f"{LLMConfig.GENAI_PROXY_URL}/v1",
            "api_key": LLMConfig.GENAI_PROXY_API_KEY,
            "streaming": bool(streaming),
            "default_headers": {
                "API-Key": LLMConfig.GENAI_PROXY_API_KEY
            }
        }
        if streaming:
            config["stream_usage"] = True
        if not skip_temperature:
            config["temperature"] = temperature

        config.update(cls._get_reasoning_summary_config(model))
        config.update(kwargs)
        return ChatOpenAI(**config)

    @classmethod
    def _get_reasoning_summary_config(cls, model: str) -> Dict[str, Any]:
        """Enable provider-supported reasoning summaries for OpenAI reasoning models.

        LangChain only exposes summary blocks when the Responses API output format
        is enabled. Keep this scoped to OpenAI reasoning models so Bedrock/Claude
        proxy calls continue to use the chat-compatible path.
        """
        if not cls._is_openai_reasoning_model(model):
            return {}

        mode = str(LLMConfig.REASONING_SUMMARY_MODE or "").strip().lower()
        if mode in {"", "none", "false", "off", "disabled", "disable"}:
            return {}
        if mode == "true":
            mode = "auto"
        if mode not in {"auto", "concise", "detailed"}:
            logger.warning(
                "Unsupported LLM_REASONING_SUMMARY_MODE=%r; using 'auto'",
                LLMConfig.REASONING_SUMMARY_MODE,
            )
            mode = "auto"

        reasoning: Dict[str, Any] = {"summary": mode}
        effort = str(LLMConfig.REASONING_EFFORT or "").strip().lower()
        if effort and effort not in {"none", "false", "off", "disabled", "disable"}:
            reasoning["effort"] = effort

        return {
            "reasoning": reasoning,
            "output_version": "responses/v1",
        }

    @staticmethod
    def _is_openai_reasoning_model(model: str) -> bool:
        model_lower = (model or "").lower()
        if not model_lower.startswith("openai."):
            return False
        bare_model = model_lower.removeprefix("openai.")
        return bare_model.startswith(("gpt-5", "o3", "o4"))

    @classmethod
    def get_client_for_binding(
        cls,
        binding_key: str,
        temperature: float = None,
        max_tokens: int = None,
        timeout: int = None,
        streaming: bool = False,
        stream_chat: bool = False,
        llm_role: str = None,
        **kwargs
    ) -> Any:
        """Get LLM client using the unified model registry for a binding key."""
        from app.llm.registry import LlmModelRegistry
        from app.llm.observability_context import llm_role_from_binding

        resolved = LlmModelRegistry.resolve_for_invoke(binding_key=binding_key)
        role = llm_role or llm_role_from_binding(binding_key)
        return cls.get_client(
            provider=resolved.provider,
            model=resolved.primary,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            streaming=streaming,
            stream_chat=stream_chat,
            binding_key=binding_key,
            llm_role=role,
            **kwargs,
        )

    @classmethod
    def clear_cache(cls):
        """Clear client cache (useful for testing or config changes)."""
        cls._clients.clear()
        logger.info("Cleared LLM client cache")
