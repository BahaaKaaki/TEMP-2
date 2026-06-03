// Output Schema Builder Component - OpenAI Style
// Provides a user-friendly interface for defining structured output schemas
import { useState, useEffect, useRef } from 'react';
import { authenticatedFetch, createWorkflow } from '@/api/client';
import { uploadTemplate, deleteTemplate } from '@/api/template-client';
import { useWorkflow } from '@/context/WorkflowContext';
import AlertModal from '../ui/AlertModal';
import { safeLog, safeError } from '../../utils/safeLogger';

// Recursive Property Row Component
function PropertyRow({ property, onUpdate, onRemove, onAddNested, depth = 0 }) {
  const indent = depth * 24;
  const isObject = property.type === 'object';
  const isEnum = property.type === 'enum';
  const hasNested = property.properties && property.properties.length > 0;

  return (
    <div style={{ marginLeft: `${indent}px` }} className="space-y-2">
      <div className="grid grid-cols-12 gap-3 items-start">
        {/* Icon for nested properties */}
        {depth > 0 && (
          <div className="col-span-12 flex items-center gap-2 text-xs text-muted-foreground mb-1">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            <span>Nested property</span>
          </div>
        )}
        
        {/* Name */}
        <div className="col-span-4">
          <input
            type="text"
            value={property.name}
            onChange={(e) => onUpdate(property.id, 'name', e.target.value)}
            placeholder="Property name"
            className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        {/* Type */}
        <div className="col-span-3">
          <select
            value={property.type}
            onChange={(e) => onUpdate(property.id, 'type', e.target.value)}
            className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="string">STR</option>
            <option value="number">NUM</option>
            <option value="boolean">BOOL</option>
            <option value="enum">ENUM</option>
            <option value="object">OBJ</option>
            <option value="array">ARR</option>
          </select>
        </div>

        {/* Description */}
        <div className="col-span-3">
          <input
            type="text"
            value={property.description}
            onChange={(e) => onUpdate(property.id, 'description', e.target.value)}
            placeholder="Add description"
            className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        {/* Required Checkbox */}
        <div className="col-span-1 flex items-center justify-center">
          <label className="flex items-center cursor-pointer" title="Required field">
            <input
              type="checkbox"
              checked={property.required}
              onChange={(e) => onUpdate(property.id, 'required', e.target.checked)}
              className="w-4 h-4 text-primary bg-background border-border rounded focus:ring-2 focus:ring-primary"
            />
          </label>
        </div>

        {/* Remove Button */}
        <div className="col-span-1 flex justify-end">
          <button
            type="button"
            onClick={() => onRemove(property.id)}
            className="w-8 h-8 flex items-center justify-center text-muted-foreground hover:text-red-600 hover:bg-red-50 rounded transition-colors"
            title="Remove property"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Enum Values */}
      {isEnum && (
        <div className="ml-4 p-3 bg-gray-50 border border-gray-300 rounded-lg">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-medium text-foreground">Enum Values</label>
            <button
              type="button"
              onClick={() => {
                const newEnum = [...(property.enum || []), ''];
                onUpdate(property.id, 'enum', newEnum);
              }}
              className="text-xs text-gray-700 hover:underline"
            >
              + Add value
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {(property.enum || []).map((enumVal, idx) => (
              <div key={idx} className="flex items-center gap-1 bg-background border border-border rounded px-2 py-1">
                <input
                  type="text"
                  value={enumVal}
                  onChange={(e) => {
                    const newEnum = [...(property.enum || [])];
                    newEnum[idx] = e.target.value;
                    onUpdate(property.id, 'enum', newEnum);
                  }}
                  placeholder={`Value ${idx + 1}`}
                  className="w-24 text-xs bg-transparent border-none focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => {
                    const newEnum = property.enum.filter((_, i) => i !== idx);
                    onUpdate(property.id, 'enum', newEnum);
                  }}
                  className="text-red-600 hover:text-red-800 text-sm font-bold"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add Nested Property Button for Objects */}
      {isObject && (
        <div className="ml-4">
          <button
            type="button"
            onClick={() => onAddNested(property.id)}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-200 hover:bg-gray-300 border border-gray-300 rounded-lg transition-colors cursor-pointer"
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add nested property
          </button>
        </div>
      )}

      {/* Nested Properties */}
      {isObject && hasNested && (
        <div className="ml-4 pl-4 border-l-2 border-gray-300 space-y-2">
          {property.properties.map((nestedProp) => (
            <PropertyRow
              key={nestedProp.id}
              property={nestedProp}
              onUpdate={onUpdate}
              onRemove={onRemove}
              onAddNested={onAddNested}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function OutputSchemaBuilder({ value, onChange, onConfigChange, label = "Output Schema", config = {}, workflowId = null, nodeId = null }) {
  const { state, dispatch, ACTIONS } = useWorkflow();
  const [mode, setMode] = useState('simple'); // 'simple' or 'advanced'
  const [schemaName, setSchemaName] = useState('response_schema');
  const [properties, setProperties] = useState([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [userRequirements, setUserRequirements] = useState(config.schemaRequirements || '');
  const [showGenerateError, setShowGenerateError] = useState(false);
  const [generateErrorMsg, setGenerateErrorMsg] = useState('');
  const [templateUploading, setTemplateUploading] = useState(false);
  const [templateError, setTemplateError] = useState(null);
  const templateInputRef = useRef(null);

  const ensureWorkflowSaved = async () => {
    const existingId = workflowId || state.selectedWorkflow?.id;
    if (existingId) return existingId;

    const nodesArray = Array.from(state.canvasNodes.entries()).map(([id, node]) => ({
      id,
      type: node.type,
      position: { x: node.x, y: node.y },
      data: { label: node.config?.label || node.nodeType?.name || 'Node', config: node.config },
      config: node.config,
    }));
    const edgesArray = state.connections.map((conn) => ({
      id: conn.id,
      source: conn.source,
      target: conn.target,
      sourceHandle: conn.sourceHandle || null,
      targetHandle: conn.targetHandle || null,
      conditionId: conn.conditionId || null,
    }));

    const draftName = `Draft ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString()}`;
    const result = await createWorkflow({
      name: draftName,
      active: false,
      isDraft: true,
      nodes: JSON.stringify(nodesArray),
      connections: JSON.stringify(edgesArray),
    });

    const saved = { name: draftName, id: result.id, ...result };
    dispatch({ type: ACTIONS.PUBLISH_WORKFLOW, payload: saved });
    dispatch({ type: ACTIONS.SELECT_WORKFLOW, payload: saved });
    return result.id;
  };

  // Parse JSON property to internal format
  const jsonToProperty = (name, jsonProp, isRequired = false) => {
    const prop = {
      id: `prop_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      name: name,
      type: jsonProp.type || 'string',
      description: jsonProp.description || '',
      required: isRequired,
      enum: jsonProp.enum || [],
      properties: [],
      default: jsonProp.default, // Preserve default value from advanced mode
    };
    
    if (jsonProp.type === 'object' && jsonProp.properties) {
      const requiredFields = jsonProp.required || [];
      prop.properties = Object.entries(jsonProp.properties).map(([nestedName, nestedProp]) => 
        jsonToProperty(nestedName, nestedProp, requiredFields.includes(nestedName))
      );
    }
    
    return prop;
  };

  // Sync userRequirements with persisted config value when config changes
  useEffect(() => {
    if (config.schemaRequirements !== undefined) {
      setUserRequirements(config.schemaRequirements);
    }
  }, [config.schemaRequirements]);

  // Initialize properties from existing schema
  useEffect(() => {
    if (value && isModalOpen) {
      try {
        // Try to parse existing JSON schema
        const parsed = JSON.parse(value);
        
        // Check if it's standard JSON Schema format (has "type" at root)
        if (parsed.type === 'object') {
          // Standard JSON Schema format
          setSchemaName(parsed.title || 'response_schema');
          
          if (parsed.properties) {
            const requiredFields = parsed.required || [];
            const parsedProps = Object.entries(parsed.properties).map(([name, prop]) =>
              jsonToProperty(name, prop, requiredFields.includes(name))
            );
            setProperties(parsedProps);
          }
        } else {
          // Old format with wrapper
          const schemaKeys = Object.keys(parsed);
          if (schemaKeys.length > 0) {
            const firstKey = schemaKeys[0];
            setSchemaName(firstKey);
            
            if (parsed[firstKey] && parsed[firstKey].properties) {
              const requiredFields = parsed[firstKey].required || [];
              const parsedProps = Object.entries(parsed[firstKey].properties).map(([name, prop]) =>
                jsonToProperty(name, prop, requiredFields.includes(name))
              );
              setProperties(parsedProps);
            }
          }
        }
      } catch (e) {
        // If parsing fails, it might be old YAML format or invalid JSON
        safeError('Failed to parse schema:', e);
        setProperties([]);
      }
    } else if (!value && isModalOpen) {
      setProperties([]);
      setSchemaName('response_schema');
    }
  }, [value, isModalOpen]);

  const addProperty = (parentId = null) => {
    const newProp = {
      id: `prop_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      name: '',
      type: 'string',
      description: '',
      required: true, // Default to required
      enum: [],
      properties: [], // For nested objects
      // default is undefined initially - can be added manually in advanced mode
    };
    
    if (parentId) {
      // Add nested property
      const updateNested = (props) => {
        return props.map(prop => {
          if (prop.id === parentId) {
            return { ...prop, properties: [...(prop.properties || []), newProp] };
          } else if (prop.properties && prop.properties.length > 0) {
            return { ...prop, properties: updateNested(prop.properties) };
          }
          return prop;
        });
      };
      setProperties(updateNested(properties));
    } else {
      setProperties([...properties, newProp]);
    }
  };

  const updateProperty = (id, field, newValue) => {
    const updateNested = (props) => {
      return props.map(prop => {
        if (prop.id === id) {
          return { ...prop, [field]: newValue };
        } else if (prop.properties && prop.properties.length > 0) {
          return { ...prop, properties: updateNested(prop.properties) };
        }
        return prop;
      });
    };
    setProperties(updateNested(properties));
  };

  const removeProperty = (id) => {
    const removeNested = (props) => {
      return props.filter(prop => prop.id !== id).map(prop => {
        if (prop.properties && prop.properties.length > 0) {
          return { ...prop, properties: removeNested(prop.properties) };
        }
        return prop;
      });
    };
    setProperties(removeNested(properties));
  };


  const propertyToJson = (prop) => {
    if (!prop.name) return null;
    
    const jsonProp = {
      type: prop.type,
    };
    
    // Handle object type - properties come first, then description
    if (prop.type === 'object' && prop.properties && prop.properties.length > 0) {
      jsonProp.properties = {};
      const requiredFields = [];
      
      prop.properties.forEach(nested => {
        const nestedJson = propertyToJson(nested);
        if (nestedJson && nested.name) {
          jsonProp.properties[nested.name] = nestedJson;
          if (nested.required) {
            requiredFields.push(nested.name);
          }
        }
      });
      
      if (requiredFields.length > 0) {
        jsonProp.required = requiredFields;
      }
      jsonProp.additionalProperties = false;
      
      // Add description for object after properties
      if (prop.description) {
        jsonProp.description = prop.description;
      }
    } else {
      // For non-object types, description comes before enum/default
      if (prop.description) {
        jsonProp.description = prop.description;
      }
      
      // Always include default value based on type
      if (prop.default !== undefined && prop.default !== null && prop.default !== '') {
        // Use the existing default value
        jsonProp.default = prop.default;
      } else {
        // Generate appropriate empty default based on type
        if (prop.type === 'string') {
          jsonProp.default = '';
        } else if (prop.type === 'number') {
          jsonProp.default = 0;
        } else if (prop.type === 'boolean') {
          jsonProp.default = false;
        } else if (prop.type === 'array') {
          jsonProp.default = [];
        } else if (prop.type === 'enum' && prop.enum && prop.enum.length > 0) {
          // For enum, default to first value or empty string
          jsonProp.default = prop.enum[0] || '';
        } else {
          // For other types, use empty string
          jsonProp.default = '';
        }
      }
      
      if (prop.type === 'enum' && prop.enum && prop.enum.length > 0) {
        jsonProp.enum = prop.enum.filter(e => e);
      }
    }
    
    return jsonProp;
  };

  const generateSchema = () => {
    if (mode === 'advanced') {
      return value || '';
    }

    if (properties.length === 0) {
      return '';
    }

    // Standard JSON Schema format
    const schema = {
      type: 'object',
      title: schemaName,
      properties: {},
      required: [],
      additionalProperties: false
    };

    properties.forEach(prop => {
      const jsonProp = propertyToJson(prop);
      if (jsonProp && prop.name) {
        schema.properties[prop.name] = jsonProp;
        if (prop.required) {
          schema.required.push(prop.name);
        }
      }
    });

    return JSON.stringify(schema, null, 2);
  };

  const handleSave = () => {
    const schema = generateSchema();
    onChange(schema);
    setIsModalOpen(false);
  };

  const handleGenerate = () => {
    // Show modal to collect user requirements
    setShowGenerateModal(true);
  };

  const handleGenerateSchema = async () => {
    setIsAnalyzing(true);
    setAnalysisResult(null);

    try {
      const promptText = config.userPrompt || config.prompt || config.systemInstructions || '';
      
      safeLog('Generating schema with:', { promptText, userRequirements, workflowId, nodeId });
      
      const response = await authenticatedFetch(`/api/workflows/${workflowId || 'temp'}/nodes/${nodeId || 'temp'}/generate-schema`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          prompt: promptText,
          systemInstructions: config.systemInstructions || config.taskInstructions || config.reasoningGuideline || '',
          userRequirements: userRequirements,
          outputSchema: value
        })
      });

      safeLog('Response status:', response.status);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        safeError('Error response:', errorData);
        throw new Error(errorData.detail || 'Failed to generate schema');
      }

      const result = await response.json();
      safeLog('Schema generation result:', result);
      setAnalysisResult(result.schema);

      // Auto-fill schema if suggested
      if (result.schema.suggestedSchema) {
        const schemaStr = JSON.stringify(result.schema.suggestedSchema, null, 2);
        onChange(schemaStr);
        // Persist the requirements text in node config
        if (onConfigChange && userRequirements) {
          onConfigChange('schemaRequirements', userRequirements);
        }
        // Close the generate modal (user can click "Edit manually" to open the editor)
        setShowGenerateModal(false);
      }
    } catch (error) {
      safeError('Error generating schema:', error);
      setGenerateErrorMsg(error.message || 'Please try again.');
      setShowGenerateError(true);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const displayValue = value || 'Click to define output schema...';
  const truncatedValue = displayValue.length > 60 ? displayValue.substring(0, 60) + '...' : displayValue;

  return (
    <>
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-foreground">
            {label}
          </label>
        </div>
        
        {analysisResult && (
          <div className="mb-2 p-3 bg-gray-50 border border-gray-300 rounded-lg text-xs">
            <div className="font-semibold text-gray-900">Schema Generated (Multi-Section):</div>
            {analysisResult.reasoning && (
              <div className="text-gray-700 mt-1 text-xs italic">{analysisResult.reasoning}</div>
            )}
            {/* Show section previews if the schema has sections */}
            {analysisResult.suggestedSchema?.properties?.sections && (
              <div className="mt-2 space-y-1">
                <div className="font-medium text-gray-800">Sections:</div>
                {(() => {
                  try {
                    const items = analysisResult.suggestedSchema.properties.sections.items;
                    // Handle oneOf (fallback schemas) or direct properties
                    const sectionDefs = items?.oneOf || (items?.properties ? [items] : []);
                    return sectionDefs.map((sectionDef, idx) => {
                      const title = sectionDef?.properties?.section_title?.const || 
                                    sectionDef?.properties?.section_title?.default || 
                                    `Section ${idx + 1}`;
                      const desc = sectionDef?.properties?.description?.const || 
                                   sectionDef?.properties?.description?.default || '';
                      return (
                        <div key={idx} className="flex items-center gap-2 ml-2 text-gray-700">
                          <span className="text-gray-400">&#8226;</span>
                          <span className="font-medium">{title}</span>
                          {desc && <span className="text-gray-500">- {desc}</span>}
                        </div>
                      );
                    });
                  } catch {
                    return null;
                  }
                })()}
              </div>
            )}
            {/* Legacy display for old-style schemas */}
            {analysisResult.schemaType && (
              <div className="text-gray-800 mt-1">
                <span className="font-medium">Schema Type:</span> {analysisResult.schemaType}
              </div>
            )}
            {analysisResult.outputType && (
              <div className="text-gray-800">
                <span className="font-medium">Output Type:</span> {analysisResult.outputType}
              </div>
            )}
            {analysisResult.vizType && analysisResult.vizType !== 'none' && (
              <div className="text-gray-800">
                <span className="font-medium">Visualization:</span> {analysisResult.vizType}
              </div>
            )}
          </div>
        )}

        {/* Show linked template indicator */}
        {config.templateId && config.templateName && (
          <div className="mb-2 flex items-center gap-1.5 text-xs text-blue-700">
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span>From template: {config.templateName}</span>
          </div>
        )}

        <div
          onClick={() => {
            setShowGenerateModal(true);
          }}
          className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg cursor-pointer hover:border-primary/50 transition-colors"
        >
          {value ? (
            <span className="text-foreground font-mono text-xs">{truncatedValue}</span>
          ) : (
            <span className="text-muted-foreground">Click to define output schema...</span>
          )}
        </div>
      </div>

      {/* Schema Builder Modal */}
      {isModalOpen && (
        <div
          data-theme="apex-dark"
          className="fixed inset-0 flex items-center justify-center z-[9999]"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
          onClick={() => setIsModalOpen(false)}
        >
          <div
            className="rounded-2xl p-6 w-[90vw] max-w-4xl max-h-[85vh] flex flex-col shadow-2xl"
            style={{
              background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
              border: '1px solid #464646',
              color: '#ffffff',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-foreground">Structured output (JSON)</h3>
                <p className="text-sm text-muted-foreground mt-1">The model will generate a JSON object that matches this schema.</p>
              </div>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="w-8 h-8 rounded-lg bg-secondary hover:bg-muted flex items-center justify-center transition-colors"
              >
                <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Mode Tabs */}
            <div className="flex gap-2 mb-4 border-b border-border">
              <button
                type="button"
                onClick={() => setMode('simple')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  mode === 'simple'
                    ? 'text-foreground border-b-2 border-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Simple
              </button>
              <button
                type="button"
                onClick={() => setMode('advanced')}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  mode === 'advanced'
                    ? 'text-foreground border-b-2 border-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Advanced
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 min-h-0 overflow-y-auto mb-4">
              {mode === 'simple' ? (
                <div className="space-y-4">
                  {/* Schema Name */}
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-2">
                      Name
                    </label>
                    <input
                      type="text"
                      value={schemaName}
                      onChange={(e) => setSchemaName(e.target.value)}
                      placeholder="response_schema"
                      className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>

                  {/* Properties */}
                  <div>
                    <label className="block text-sm font-medium text-foreground mb-3">
                      Properties
                    </label>
                    
                    {/* Properties Header */}
                    {properties.length > 0 && (
                      <div className="grid grid-cols-12 gap-3 mb-2 px-3 text-xs font-medium text-muted-foreground">
                        <div className="col-span-4">Name</div>
                        <div className="col-span-3">Type</div>
                        <div className="col-span-3">Description</div>
                        <div className="col-span-1 text-center">Required</div>
                        <div className="col-span-1"></div>
                      </div>
                    )}

                    {/* Property Rows */}
                    <div className="space-y-3">
                      {properties.map((prop) => (
                        <PropertyRow
                          key={prop.id}
                          property={prop}
                          onUpdate={updateProperty}
                          onRemove={removeProperty}
                          onAddNested={addProperty}
                          depth={0}
                        />
                      ))}
                    </div>

                    {/* Add Property Button */}
                    <button
                      onClick={() => addProperty(null)}
                      type="button"
                      className="mt-3 flex items-center gap-2 px-3 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-muted rounded-lg transition-colors cursor-pointer"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                      </svg>
                      Add property
                    </button>
                  </div>
                </div>
              ) : (
                /* Advanced Mode */
                <div>
                  <label className="block text-sm font-medium text-foreground mb-2">
                    JSON Schema
                  </label>
                  <textarea
                    value={value || ''}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={`{
  "type": "object",
  "title": "response_schema",
  "properties": {
    "classification": {
      "type": "string",
      "description": "Classification of user intent",
      "default": ""
    },
    "confidence": {
      "type": "number",
      "description": "Confidence score",
      "default": 0
    },
    "details": {
      "type": "object",
      "properties": {
        "reason": {
          "type": "string",
          "description": "Detailed reason",
          "default": ""
        }
      },
      "required": ["reason"],
      "additionalProperties": false,
      "description": "Additional details"
    }
  },
  "required": ["classification"],
  "additionalProperties": false
}`}
                    rows={20}
                    className="w-full px-3 py-2 text-sm font-mono bg-background border border-border rounded-lg focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary resize-none"
                  />
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex items-center justify-between pt-4 border-t border-border">
              <button
                type="button"
                onClick={handleGenerate}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-muted rounded-lg transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Generate
              </button>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-muted rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  className="px-4 py-2 text-sm font-medium text-white bg-gray-700 hover:bg-gray-800 rounded-lg transition-colors"
                >
                  Update
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Generate Schema Modal */}
      {showGenerateModal && (
        <div
          data-theme="apex-dark"
          className="fixed inset-0 flex items-center justify-center z-[10000]"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
          onClick={() => setShowGenerateModal(false)}
        >
          <div
            className="rounded-2xl p-6 w-[90vw] max-w-2xl flex flex-col shadow-2xl"
            style={{
              background: 'linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 100%)',
              border: '1px solid #464646',
              color: '#ffffff',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold" style={{ color: '#ffffff' }}>Generate Output Schema</h3>
                <p className="text-sm mt-1" style={{ color: '#b5b5b5' }}>Describe what you want the agent to output, and we&apos;ll generate an appropriate schema.</p>
              </div>
              <button
                type="button"
                onClick={() => setShowGenerateModal(false)}
                className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
                style={{ backgroundColor: 'transparent', color: '#b5b5b5' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#2a2a2a'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* From PPTX Template */}
            <div
              className="mb-4 p-3 rounded-lg"
              style={{
                backgroundColor: 'rgba(217, 56, 84, 0.08)',
                border: '1px solid rgba(217, 56, 84, 0.35)',
              }}
            >
              <label className="block text-sm font-medium mb-1" style={{ color: '#ffffff' }}>
                From PPTX Template
              </label>
              <p className="text-xs mb-2" style={{ color: '#b5b5b5' }}>
                Upload a .pptx file with {'{{ }}'} placeholders. The schema will be generated automatically from the template.
              </p>

              {config.templateId && config.templateName ? (
                <div
                  className="flex items-center gap-2 p-2 rounded-lg mb-2"
                  style={{
                    backgroundColor: 'rgba(32, 247, 120, 0.1)',
                    border: '1px solid rgba(32, 247, 120, 0.35)',
                  }}
                >
                  <svg className="w-4 h-4 flex-shrink-0" style={{ color: '#20f778' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="text-xs truncate flex-1" style={{ color: '#20f778' }}>{config.templateName}</span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await deleteTemplate(config.templateId);
                      } catch { /* best effort */ }
                      if (onConfigChange) {
                        onConfigChange('templateId', null);
                        onConfigChange('templateName', null);
                      }
                    }}
                    className="text-xs transition-colors"
                    style={{ color: '#ff4d6e' }}
                  >
                    Remove
                  </button>
                </div>
              ) : null}

              <input
                ref={templateInputRef}
                type="file"
                accept=".pptx"
                className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  e.target.value = '';
                  setTemplateUploading(true);
                  setTemplateError(null);
                  try {
                    const wfId = await ensureWorkflowSaved();
                    const result = await uploadTemplate(wfId, nodeId, file);
                    if (onConfigChange) {
                      onConfigChange('templateId', result.id);
                      onConfigChange('templateName', result.name || file.name);
                    }
                    if (result.generatedSchema) {
                      onChange(JSON.stringify(result.generatedSchema, null, 2));
                    }
                    setShowGenerateModal(false);
                  } catch (err) {
                    setTemplateError(err.message);
                  } finally {
                    setTemplateUploading(false);
                  }
                }}
              />
              <button
                type="button"
                disabled={templateUploading}
                onClick={() => templateInputRef.current?.click()}
                className="w-full text-xs px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
                style={{
                  border: '1px dashed rgba(217, 56, 84, 0.55)',
                  color: '#ffffff',
                  backgroundColor: 'rgba(0, 0, 0, 0.25)',
                }}
                onMouseEnter={(e) => {
                  if (!templateUploading) {
                    e.currentTarget.style.backgroundColor = 'rgba(217, 56, 84, 0.12)';
                    e.currentTarget.style.borderColor = 'rgba(217, 56, 84, 0.75)';
                  }
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'rgba(0, 0, 0, 0.25)';
                  e.currentTarget.style.borderColor = 'rgba(217, 56, 84, 0.55)';
                }}
              >
                {templateUploading ? 'Saving & analyzing template...' : 'Upload .pptx template'}
              </button>
              {templateError && (
                <p className="text-xs mt-1" style={{ color: '#ff4d6e' }}>{templateError}</p>
              )}
            </div>

            {/* User Requirements Input */}
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2" style={{ color: '#ffffff' }}>
                Requirements (Optional)
              </label>
              <textarea
                value={userRequirements}
                onChange={(e) => setUserRequirements(e.target.value)}
                placeholder="e.g., Include timestamps, confidence scores, and nested categories. Or: Generate a bar chart showing sales by region."
                rows={6}
                className="force-white-text w-full px-3 py-2 text-sm rounded-lg resize-none focus:outline-none"
                style={{
                  backgroundColor: '#1a1a1a',
                  border: '1px solid #464646',
                  color: '#ffffff',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = '#d93854'; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = '#464646'; }}
              />
              <div className="flex items-center justify-between mt-2 gap-2">
                <p className="text-xs flex-1" style={{ color: '#b5b5b5' }}>
                  Tip: We&apos;ll analyze the agent&apos;s prompt and your requirements to generate the best schema.
                  For visualizations, mention chart types (bar, line, pie) or analytical keywords.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setShowGenerateModal(false);
                    setIsModalOpen(true);
                  }}
                  className="text-xs hover:underline whitespace-nowrap ml-2 shrink-0"
                  style={{ color: '#e8a0ad' }}
                >
                  Or edit manually →
                </button>
              </div>
            </div>

            {/* Context Info */}
            {(config.userPrompt || config.prompt || config.systemInstructions) && (
              <div
                className="mb-4 p-3 rounded-lg"
                style={{
                  backgroundColor: 'rgba(255, 255, 255, 0.04)',
                  border: '1px solid #464646',
                }}
              >
                <div className="text-xs font-medium mb-1" style={{ color: '#ffffff' }}>Agent Context:</div>
                <div className="text-xs line-clamp-3" style={{ color: '#b5b5b5' }}>
                  {config.userPrompt || config.prompt || config.systemInstructions}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 pt-4" style={{ borderTop: '1px solid #464646' }}>
              <button
                type="button"
                onClick={() => {
                  setShowGenerateModal(false);
                }}
                className="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
                style={{
                  color: '#ffffff',
                  backgroundColor: 'transparent',
                  border: '1px solid #464646',
                }}
                disabled={isAnalyzing}
                onMouseEnter={(e) => { if (!isAnalyzing) e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleGenerateSchema}
                disabled={isAnalyzing}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                style={{ backgroundColor: '#d93854' }}
                onMouseEnter={(e) => { if (!isAnalyzing) e.currentTarget.style.backgroundColor = '#c52a45'; }}
                onMouseLeave={(e) => { if (!isAnalyzing) e.currentTarget.style.backgroundColor = '#d93854'; }}
              >
                {isAnalyzing ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Generating...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    Generate Schema
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error Modal */}
      <AlertModal
        isOpen={showGenerateError}
        title="Generate Schema Failed"
        message={`Failed to generate schema: ${generateErrorMsg}`}
        variant="error"
        onClose={() => setShowGenerateError(false)}
      />
    </>
  );
}
