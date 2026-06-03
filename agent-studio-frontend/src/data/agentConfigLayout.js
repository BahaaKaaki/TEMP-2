/** AI Agent config panel — aligned with product spec (basic / advanced). */

export const AGENT_CONFIG_CATEGORY_ORDER = [
  'Basic',
  'Sources',
  'Behavior',
  'Output',
  'Model',
];

/** Omitted from the panel; backend may still read these from saved workflows. */
export const AGENT_PANEL_HIDDEN_KEYS = new Set([
  'deliverableModelProvider',
  'deliverableModelName',
  'autoKbOneShot',
  'searchMethod',
  'enableReranking',
  'rerankerModel',
  'parallelKBSearch',
  'startupType',
  'startupQuestions',
]);

const AGENT_SOURCES_BASIC_KEYS = new Set([
  'enableWebSearch',
  'enableDeepResearch',
  'knowledgeBase',
  'knowledgeBaseIds',
]);

const AGENT_SOURCES_ADVANCED_KEYS = new Set([
  'deliverableSources',
  'fileScope',
]);

export function isAgentConfigFieldVisible(field, advancedMode) {
  if (AGENT_PANEL_HIDDEN_KEYS.has(field.key)) return false;
  if (field.configMode === 'basic') return true;
  if (field.configMode === 'advanced') return advancedMode;
  return advancedMode;
}

function includeAgentField(field, advancedMode) {
  if (!isAgentConfigFieldVisible(field, advancedMode)) return false;
  if (field.configCategory === 'Sources') {
    if (!advancedMode) return AGENT_SOURCES_BASIC_KEYS.has(field.key);
    return AGENT_SOURCES_ADVANCED_KEYS.has(field.key);
  }
  return true;
}

export function groupAgentConfigFields(fields, advancedMode) {
  const byCategory = new Map();
  for (const field of fields) {
    if (!includeAgentField(field, advancedMode)) continue;
    const category = field.configCategory || 'Other';
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category).push(field);
  }
  return AGENT_CONFIG_CATEGORY_ORDER
    .filter((title) => byCategory.has(title))
    .map((title) => ({ title, fields: byCategory.get(title) }));
}
