/**
 * API client for LLM models configuration
 * 
 * Provides dynamic model discovery from backend,
 * ensuring frontend always shows correct available models.
 */

import { API_BASE_URL, authenticatedFetch } from './client.js';
import { safeLog, safeError, safeWarn } from '../utils/safeLogger';

// Cache configuration
const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes
let modelsCache = null;
let cacheTimestamp = null;

/**
 * Check if cache is valid
 */
function isCacheValid() {
  if (!modelsCache || !cacheTimestamp) {
    return false;
  }
  return Date.now() - cacheTimestamp < CACHE_DURATION;
}

/**
 * Get all available LLM providers and models
 * 
 * @param {boolean} forceRefresh - Force refresh cache
 * @returns {Promise<Object>} Providers configuration
 * 
 * Example response:
 * {
 *   providers: {
 *     openai: {
 *       name: "OpenAI",
 *       available: true,
 *       models: [
 *         { value: "gpt-4o", label: "GPT-4 Omni", tier: "premium", ... }
 *       ]
 *     }
 *   },
 *   default_provider: "openai",
 *   default_model: "gpt-4o"
 * }
 */
export async function fetchAllModels(forceRefresh = false) {
  // Return cached data if valid
  if (!forceRefresh && isCacheValid()) {
    safeLog('📦 Using cached models configuration');
    return modelsCache;
  }

  try {
    safeLog('🌐 Fetching models configuration from backend...');
    const response = await authenticatedFetch(`${API_BASE_URL}/api/models`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch models: ${response.statusText}`);
    }

    const data = await response.json();
    
    // Update cache
    modelsCache = data;
    cacheTimestamp = Date.now();
    
    safeLog('✅ Models configuration loaded:', {
      providers: Object.keys(data.providers),
      default_provider: data.default_provider,
      default_model: data.default_model,
    });

    return data;
  } catch (error) {
    safeError('❌ Failed to fetch models:', error);
    
    // Return cached data if available (even if expired)
    if (modelsCache) {
      safeWarn('⚠️  Using expired cache as fallback');
      return modelsCache;
    }
    
    // If no cache, return hardcoded fallback
    return getHardcodedFallback();
  }
}

/**
 * Get models for a specific provider
 * 
 * @param {string} provider - Provider ID (openai, anthropic, azure)
 * @returns {Promise<Array>} List of models
 */
export async function fetchModelsForProvider(provider) {
  try {
    safeLog(`🌐 Fetching models for provider: ${provider}`);
    const response = await authenticatedFetch(`${API_BASE_URL}/api/models/${provider}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch models for ${provider}: ${response.statusText}`);
    }

    const models = await response.json();
    safeLog(`✅ Loaded ${models.length} models for ${provider}`);
    return models;
  } catch (error) {
    safeError(`❌ Failed to fetch models for ${provider}:`, error);
    
    // Try to get from cache
    if (isCacheValid() && modelsCache?.providers?.[provider]) {
      safeWarn(`⚠️  Using cached models for ${provider}`);
      return modelsCache.providers[provider].models;
    }
    
    // Return empty array as fallback
    return [];
  }
}

/**
 * Get list of available providers
 * 
 * @returns {Promise<Array>} List of provider IDs
 */
export async function fetchAvailableProviders() {
  try {
    const response = await authenticatedFetch(`${API_BASE_URL}/api/models/${provider}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch providers: ${response.statusText}`);
    }

    const providers = await response.json();
    safeLog('✅ Available providers:', providers);
    return providers;
  } catch (error) {
    safeError('❌ Failed to fetch providers:', error);
    
    // Try to get from cache
    if (isCacheValid() && modelsCache?.providers) {
      const available = Object.entries(modelsCache.providers)
        .filter(([_, info]) => info.available)
        .map(([id, _]) => id);
      return available;
    }
    
    // Return OpenAI as fallback
    return ['openai'];
  }
}

/**
 * Validate if a specific model is available
 * 
 * @param {string} provider - Provider ID
 * @param {string} modelName - Model name
 * @returns {Promise<Object>} Validation result
 */
export async function validateModel(provider, modelName) {
  try {
    const response = await authenticatedFetch(`${API_BASE_URL}/api/models/validate/${provider}/${modelName}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      return { valid: false, error: response.statusText };
    }

    return await response.json();
  } catch (error) {
    safeError(`❌ Failed to validate model ${provider}/${modelName}:`, error);
    return { valid: false, error: error.message };
  }
}

/**
 * Get model metadata from cache
 * 
 * @param {string} provider - Provider ID
 * @param {string} modelName - Model name
 * @returns {Object|null} Model metadata or null
 */
export function getModelMetadata(provider, modelName) {
  if (!isCacheValid() || !modelsCache) {
    return null;
  }

  const providerData = modelsCache.providers?.[provider];
  if (!providerData) {
    return null;
  }

  const model = providerData.models?.find(m => m.value === modelName);
  return model || null;
}

/**
 * Get models options for dropdown (formatted for Select component)
 * 
 * @param {string} provider - Provider ID
 * @returns {Promise<Array>} Options array [{ value, label }]
 */
export async function getModelOptionsForProvider(provider) {
  const models = await fetchModelsForProvider(provider);
  
  // Filter out deprecated models by default
  return models
    .filter(model => !model.deprecated)
    .map(model => ({
      value: model.value,
      label: model.label,
      // Include metadata for tooltips/badges
      metadata: {
        tier: model.tier,
        supports_tools: model.supports_tools,
        supports_vision: model.supports_vision,
        context_length: model.context_length,
        recommended_for: model.recommended_for,
      }
    }));
}

/**
 * Clear the models cache
 */
export function clearModelsCache() {
  modelsCache = null;
  cacheTimestamp = null;
  safeLog('🗑️  Models cache cleared');
}

/**
 * Health check for models service
 * 
 * @returns {Promise<Object>} Health status
 */
export async function checkModelsHealth() {
  try {
    const response = await authenticatedFetch(`${API_BASE_URL}/api/models/health`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      return { status: 'unhealthy', error: response.statusText };
    }

    return await response.json();
  } catch (error) {
    safeError('❌ Models health check failed:', error);
    return { status: 'unhealthy', error: error.message };
  }
}

/**
 * Hardcoded fallback for when backend is unreachable
 * Provides basic OpenAI models as safety net
 */
function getHardcodedFallback() {
  safeWarn('⚠️  Using hardcoded fallback models');
  return {
    providers: {
      openai: {
        name: "OpenAI",
        available: true,
        models: [
          { value: "openai.gpt-5", label: "GPT-5" },
          { value: "openai.gpt-5.2", label: "GPT-5.2" },
          { value: "openai.gpt-5.2-pro", label: "GPT-5.2 Pro" },
          { value: "openai.gpt-4.1", label: "GPT-4.1" },
        ],
        requires_config: ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
      },
      anthropic: {
        name: "Anthropic",
        available: true,
        models: [
          { value: "bedrock.anthropic.claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
          { value: "bedrock.anthropic.claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
          { value: "bedrock.anthropic.claude-opus-4-6", label: "Claude Opus 4.6" },
          { value: "bedrock.anthropic.claude-opus-4-5", label: "Claude Opus 4.5" },
          { value: "bedrock.anthropic.claude-haiku-4-5", label: "Claude Haiku 4.5" },
        ],
        requires_config: ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
      },
      google: {
        name: "Google",
        available: true,
        models: [
          { value: "vertex_ai.gemini-3.1-pro-preview", label: "Gemini 3.1 Pro" },
          { value: "vertex_ai.gemini-3-pro-preview", label: "Gemini 3 Pro" },
          { value: "vertex_ai.gemini-3-flash-preview", label: "Gemini 3 Flash" },
          { value: "vertex_ai.gemini-2.5-pro", label: "Gemini 2.5 Pro" },
          { value: "vertex_ai.gemini-2.5-flash", label: "Gemini 2.5 Flash" },
        ],
        requires_config: ["GENAI_PROXY_URL", "GENAI_PROXY_API_KEY"]
      }
    },
    default_provider: "openai",
    default_model: "openai.gpt-5",
    environment: "unknown"
  };
}

// Preload models on module import (fire and forget)
fetchAllModels().catch(err => {
  safeWarn('Failed to preload models:', err.message);
});
