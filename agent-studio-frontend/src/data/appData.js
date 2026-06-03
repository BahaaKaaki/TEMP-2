// Application Data - Loads node configuration from JSON and provides helper functions
import nodePaletteConfig from './nodePaletteConfig.json';

// Transform JSON config into the format the palette expects.
// Categories with the same `name` are merged so the JSON can keep them in
// separate blocks (e.g. agent + code-executor) while the UI shows a single
// section. The first occurrence of a name wins for `categoryColor`.
const transformNodeConfig = (config) => {
  const merged = new Map();
  config.categories.forEach((category) => {
    const key = category.name || '';
    const existing = merged.get(key);
    if (existing) {
      existing.nodes.push(...category.elements);
    } else {
      merged.set(key, {
        category: category.name,
        categoryColor: category.color,
        nodes: [...category.elements],
      });
    }
  });
  return Array.from(merged.values());
};

// Build flat map of nodeType -> config for quick lookup
const buildNodeConfigMap = () => {
  const map = {};
  nodePaletteConfig.categories.forEach(category => {
    category.elements.forEach(element => {
      map[element.id] = {
        ...element,
        configFields: element.configFields || []
      };
    });
  });
  return map;
};

const NODE_CONFIG_MAP = buildNodeConfigMap();

// Main application data export
export const APP_DATA = {
  nodeTypes: transformNodeConfig(nodePaletteConfig),
  templates: []
};

// Helper functions for node configuration

export const getNodeConfigFields = (nodeType) => {
  const nodeInfo = NODE_CONFIG_MAP[nodeType];
  return nodeInfo ? nodeInfo.configFields || [] : [];
};

export const getDefaultConfig = (nodeType) => {
  const configFields = getNodeConfigFields(nodeType);
  const defaultConfig = {};
  
  configFields.forEach(field => {
    defaultConfig[field.key] = field.defaultValue;
  });
  
  return defaultConfig;
};

export const getNodeInfo = (nodeType) => {
  return NODE_CONFIG_MAP[nodeType] || null;
};

export const isChatCompatibleNode = (nodeType) => {
  const nodeInfo = NODE_CONFIG_MAP[nodeType];
  return nodeInfo ? nodeInfo.isChatCompatible === true : false;
};
