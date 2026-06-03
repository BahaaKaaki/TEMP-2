/**
 * Dynamic Options Handler
 * 
 * Handles dynamic dropdown options that are fetched from backend
 * instead of being hardcoded in nodePaletteConfig.json
 */

import { fetchAllModels, getModelOptionsForProvider } from '../api/models';

// Cache for processed options
const optionsCache = new Map();

/**
 * Check if a field uses dynamic options
 * 
 * @param {Object} field - Config field from nodePaletteConfig
 * @returns {boolean} True if field uses dynamic options
 */
export function isDynamicField(field) {
  return field.options === 'DYNAMIC_MODELS' || field.options === 'DYNAMIC';
}

/**
 * Get dynamic options for a field
 * 
 * @param {Object} field - Config field from nodePaletteConfig
 * @param {Object} context - Current form values (for dependent fields)
 * @returns {Promise<Array>} Options array
 */
export async function getDynamicOptions(field, context = {}) {
  // Handle model fields (depends on provider)
  if (field.key === 'modelName' && field.dependsOn === 'modelProvider') {
    const provider = context.modelProvider || 'openai';
    return await getModelOptionsForProvider(provider);
  }

  // Handle provider fields
  if (field.key === 'modelProvider') {
    return await getProviderOptions();
  }

  // Fallback to static options or empty array
  return Array.isArray(field.options) ? field.options : [];
}

/**
 * Get provider options
 * 
 * @returns {Promise<Array>} Provider options
 */
async function getProviderOptions() {
  try {
    const config = await fetchAllModels();
    
    const options = Object.entries(config.providers)
      .filter(([_, providerInfo]) => providerInfo.available)
      .map(([providerId, providerInfo]) => ({
        value: providerId,
        label: providerInfo.name,
        available: providerInfo.available,
      }));

    return options.length > 0 ? options : getDefaultProviderOptions();
  } catch (error) {
    console.error('Failed to fetch provider options:', error);
    return getDefaultProviderOptions();
  }
}

/**
 * Get default provider options (fallback)
 */
function getDefaultProviderOptions() {
  return [
    { value: 'openai', label: 'OpenAI' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'google', label: 'Google' },
  ];
}

/**
 * Resolve options for a field (handles both static and dynamic)
 * 
 * @param {Object} field - Config field
 * @param {Object} context - Current form values
 * @returns {Promise<Array>} Resolved options
 */
export async function resolveFieldOptions(field, context = {}) {
  // If field has no options, return empty array
  if (!field.options) {
    return [];
  }

  // Handle dynamic options
  if (isDynamicField(field)) {
    return await getDynamicOptions(field, context);
  }

  // Handle conditional options (dependsOn with object options)
  if (field.dependsOn && typeof field.options === 'object' && !Array.isArray(field.options)) {
    const dependentValue = context[field.dependsOn];
    return field.options[dependentValue] || [];
  }

  // Handle static array options
  if (Array.isArray(field.options)) {
    return field.options;
  }

  // Unknown format
  console.warn('Unknown options format for field:', field.key, field.options);
  return [];
}

/**
 * Get default value for a field based on backend configuration
 * 
 * @param {Object} field - Config field
 * @returns {Promise<any>} Default value
 */
export async function getDefaultValue(field) {
  // If field has explicit default, use it
  if (field.defaultValue !== undefined && field.defaultValue !== null) {
    return field.defaultValue;
  }

  // Get backend default for model fields
  if (field.key === 'modelName') {
    try {
      const config = await fetchAllModels();
      return config.default_model || 'openai.gpt-5';
    } catch (error) {
      return 'openai.gpt-5'; // Safe fallback - use with prefix for proxy routing
    }
  }

  // Get backend default for provider fields
  if (field.key === 'modelProvider') {
    try {
      const config = await fetchAllModels();
      return config.default_provider || 'openai';
    } catch (error) {
      return 'openai'; // Safe fallback
    }
  }

  return null;
}

/**
 * Preload dynamic options for better UX
 * Call this when the node config panel opens
 */
export async function preloadDynamicOptions() {
  try {
    await fetchAllModels();
    console.log('✅ Dynamic options preloaded');
  } catch (error) {
    console.warn('Failed to preload dynamic options:', error);
  }
}

/**
 * Check if a model is valid for a provider
 * 
 * @param {string} provider - Provider ID
 * @param {string} modelName - Model name
 * @returns {Promise<boolean>} True if valid
 */
export async function isValidModelForProvider(provider, modelName) {
  try {
    const options = await getModelOptionsForProvider(provider);
    return options.some(opt => opt.value === modelName);
  } catch (error) {
    console.warn('Failed to validate model:', error);
    return true; // Assume valid to avoid blocking user
  }
}

/**
 * Get model metadata for display (tooltips, badges, etc.)
 * 
 * @param {string} provider - Provider ID
 * @param {string} modelName - Model name
 * @returns {Promise<Object|null>} Model metadata
 */
export async function getModelMetadata(provider, modelName) {
  try {
    const options = await getModelOptionsForProvider(provider);
    const option = options.find(opt => opt.value === modelName);
    return option?.metadata || null;
  } catch (error) {
    console.warn('Failed to get model metadata:', error);
    return null;
  }
}

/**
 * Format model option with badges/icons
 * 
 * @param {Object} model - Model option with metadata
 * @returns {string} Formatted label with badges
 */
export function formatModelLabel(model) {
  let label = model.label;
  
  if (model.metadata) {
    const badges = [];
    
    if (model.metadata.tier === 'premium') {
      badges.push('⭐');
    }
    
    if (model.metadata.supports_vision) {
      badges.push('👁️');
    }
    
    if (model.metadata.supports_tools) {
      badges.push('🔧');
    }
    
    if (badges.length > 0) {
      label = `${label} ${badges.join(' ')}`;
    }
  }
  
  return label;
}

/**
 * Clear all cached options
 */
export function clearOptionsCache() {
  optionsCache.clear();
  console.log('🗑️  Options cache cleared');
}
