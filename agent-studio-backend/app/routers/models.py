"""
API endpoints for LLM model discovery and configuration.

This router provides dynamic model information to the frontend,
ensuring the UI always shows the correct available models based
on backend configuration and API key availability.

Models are fetched directly from OpenAI/Anthropic APIs for accuracy.
"""
from fastapi import APIRouter, Depends, HTTPException

from core.dependencies import get_current_user
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import logging

from app.config.llm_config import LLMConfig, LLMProvider
from app.utils.model_discovery import discover_all_models

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/models",
    tags=["models"],
    dependencies=[Depends(get_current_user)],
)


# Response Models
class ModelInfo(BaseModel):
    """Information about a single LLM model."""
    value: str
    label: str
    description: Optional[str] = None
    context_length: Optional[int] = None
    supports_tools: Optional[bool] = None
    supports_vision: Optional[bool] = None
    supports_json_mode: Optional[bool] = None
    tier: Optional[str] = None
    deprecated: Optional[bool] = False
    recommended_for: Optional[List[str]] = None


class ProviderInfo(BaseModel):
    """Information about an LLM provider."""
    name: str
    available: bool
    models: List[ModelInfo]
    requires_config: List[str]


class ModelsResponse(BaseModel):
    """Complete response with all providers and models."""
    providers: Dict[str, ProviderInfo]
    default_provider: str
    default_model: str
    environment: str


@router.get("", response_model=ModelsResponse)
async def get_all_models(force_refresh: bool = False) -> ModelsResponse:
    """
    Get all available LLM providers and their models.
    
    Fetches models directly from OpenAI/Anthropic APIs for real-time accuracy.
    Results are cached for 6 hours to minimize API calls.
    
    Args:
        force_refresh: Force refresh cache (default: False)
    
    Returns:
        Complete configuration of providers, models, and defaults
        
    Example Response:
        {
            "providers": {
                "openai": {
                    "name": "OpenAI",
                    "available": true,
                    "models": [
                        {
                            "value": "gpt-4o",
                            "label": "GPT-4 Omni",
                            "context_length": 128000,
                            "supports_tools": true,
                            "tier": "premium"
                        }
                    ]
                }
            },
            "default_provider": "openai",
            "default_model": "gpt-4o"
        }
    """
    try:
        # Discover models from provider APIs
        config = await discover_all_models(force_refresh=force_refresh)
        return ModelsResponse(**config)
    except Exception as e:
        logger.error(f"Error fetching models configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve models configuration"
        )


@router.get("/providers", response_model=List[str])
async def get_providers() -> List[str]:
    """
    Get list of available provider names.
    
    Returns:
        List of provider identifiers (e.g., ["openai", "anthropic", "azure"])
    """
    try:
        config = await discover_all_models()
        # Only return providers that are available (have API keys configured)
        available_providers = [
            provider_id 
            for provider_id, provider_info in config["providers"].items()
            if provider_info["available"]
        ]
        return available_providers
    except Exception as e:
        logger.error(f"Error fetching providers: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve providers"
        )


@router.get("/{provider}", response_model=List[ModelInfo])
async def get_models_for_provider(provider: str) -> List[ModelInfo]:
    """
    Get available models for a specific provider.
    
    Fetches from provider API for real-time accuracy.
    
    Args:
        provider: Provider identifier (openai, anthropic, azure)
        
    Returns:
        List of models available for the specified provider
        
    Raises:
        404: If provider not found or not configured
    """
    try:
        # Validate provider
        valid_providers = ["openai", "anthropic", "azure"]
        if provider not in valid_providers:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
            )
        
        # Get all models from discovery
        config = await discover_all_models()
        
        # Extract models for requested provider
        provider_data = config.get("providers", {}).get(provider)
        
        if not provider_data:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider}' not found"
            )
        
        if not provider_data.get("available"):
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider}' not configured. Required: {', '.join(provider_data.get('requires_config', []))}"
            )
        
        models = provider_data.get("models", [])
        
        if not models:
            raise HTTPException(
                status_code=404,
                detail=f"No models available for provider '{provider}'"
            )
        
        return [ModelInfo(**model) for model in models]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching models for provider {provider}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve models for provider: {provider}"
        )


@router.get("/validate/{provider}/{model_name}")
async def validate_model(provider: str, model_name: str) -> Dict[str, Any]:
    """
    Validate if a specific model is available for a provider.
    
    Args:
        provider: Provider identifier
        model_name: Model identifier
        
    Returns:
        Validation result with model metadata if available
    """
    try:
        # Map provider
        provider_map = {
            "openai": LLMProvider.OPENAI,
            "anthropic": LLMProvider.ANTHROPIC,
        }
        
        if provider not in provider_map:
            return {
                "valid": False,
                "error": "Invalid provider"
            }
        
        backend_provider = provider_map[provider]
        
        # Validate model
        is_valid = LLMConfig.validate_model(backend_provider, model_name)
        
        if not is_valid:
            return {
                "valid": False,
                "error": "Model not found for provider"
            }
        
        # Get metadata
        metadata = LLMConfig.get_model_metadata(backend_provider, model_name)
        
        return {
            "valid": True,
            "provider": provider,
            "model": model_name,
            "metadata": metadata
        }
        
    except Exception as e:
        logger.error(f"Error validating model {provider}/{model_name}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to validate model"
        )


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for model service.
    
    Returns status of all providers and configuration.
    Includes cache status and last refresh time.
    """
    try:
        config = await discover_all_models()
        
        providers_status = {}
        for provider_id, provider_info in config["providers"].items():
            providers_status[provider_id] = {
                "available": provider_info["available"],
                "model_count": len(provider_info["models"])
            }
        
        return {
            "status": "healthy",
            "providers": providers_status,
            "default_provider": config["default_provider"],
            "environment": config["environment"],
            "last_updated": config.get("last_updated", "unknown"),
            "cache_enabled": True
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": safe_error_detail(e, "Model service health check failed"),
        }

