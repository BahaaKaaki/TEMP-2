// Edge Inspector Component
// Shows edge details including source/target node schemas
import { useState } from 'react';

export default function EdgeInspector({ edge, sourceNode, targetNode, onClose, onDelete }) {
  const [connectionStatus, setConnectionStatus] = useState('valid');

  const getNodeSchema = (node) => {
    if (!node || !node.config) return null;
    
    // Check for output schema (from agent nodes)
    if (node.config.outputSchema) {
      return {
        type: 'output',
        schema: node.config.outputSchema
      };
    }
    
    // Check for input schema
    if (node.config.inputSchema) {
      return {
        type: 'input',
        schema: node.config.inputSchema
      };
    }
    
    return null;
  };

  const sourceSchema = getNodeSchema(sourceNode);
  const targetSchema = getNodeSchema(targetNode);

  const formatSchemaPreview = (schemaText) => {
    if (!schemaText) return 'No schema defined';
    // Show first 150 characters
    const preview = schemaText.trim();
    return preview.length > 150 ? preview.substring(0, 150) + '...' : preview;
  };

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-[9998]" onClick={onClose}>
      <div 
        className="bg-surface border border-border rounded-xl p-5 w-[500px] max-h-[80vh] flex flex-col shadow-2xl" 
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-foreground">Edge</h3>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg bg-secondary hover:bg-muted flex items-center justify-center transition-colors"
          >
            <svg className="w-4 h-4 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto space-y-4">
          {/* Connection Info */}
          <div className="p-3 bg-secondary/30 rounded-lg">
            <div className="text-xs font-medium text-muted-foreground mb-2">Connection</div>
            <div className="flex items-center gap-2">
              <div className="flex-1 p-2 bg-background rounded text-sm">
                <div className="font-medium text-foreground truncate">
                  {sourceNode?.config?.label || sourceNode?.type || 'Source'}
                </div>
                <div className="text-xs text-muted-foreground">{sourceNode?.type}</div>
              </div>
              <svg className="w-5 h-5 text-muted-foreground flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
              </svg>
              <div className="flex-1 p-2 bg-background rounded text-sm">
                <div className="font-medium text-foreground truncate">
                  {targetNode?.config?.label || targetNode?.type || 'Target'}
                </div>
                <div className="text-xs text-muted-foreground">{targetNode?.type}</div>
              </div>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <div className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                connectionStatus === 'valid' 
                  ? 'bg-gray-100 text-gray-700'
                  : 'bg-yellow-100 text-yellow-700'
              }`}>
                <div className={`w-1.5 h-1.5 rounded-full ${
                  connectionStatus === 'valid' ? 'bg-gray-500' : 'bg-yellow-500'
                }`} />
                {connectionStatus === 'valid' ? 'Valid connection' : 'Check schemas'}
              </div>
            </div>
          </div>

          {/* Source Output Schema */}
          {sourceSchema && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-medium text-foreground">Source output schema</div>
                <span className="text-xs text-muted-foreground">object</span>
              </div>
              <div className="p-3 bg-secondary/30 rounded-lg">
                <div className="space-y-2">
                  <div className="flex items-start gap-2">
                    <svg className="w-4 h-4 text-gray-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div className="flex-1">
                      <div className="text-xs font-medium text-foreground mb-1">output_text <span className="text-muted-foreground">string</span></div>
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <svg className="w-4 h-4 text-gray-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div className="flex-1">
                      <div className="text-xs font-medium text-foreground mb-1">output_parsed <span className="text-muted-foreground">object</span></div>
                      <pre className="text-xs text-muted-foreground bg-background p-2 rounded mt-1 font-mono overflow-x-auto whitespace-pre-wrap">
                        {formatSchemaPreview(sourceSchema.schema)}
                      </pre>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Target Input Schema */}
          {targetSchema && targetSchema.type === 'input' && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-medium text-foreground">Target input schema</div>
                <span className="text-xs text-muted-foreground">object</span>
              </div>
              <div className="p-3 bg-secondary/30 rounded-lg">
                <pre className="text-xs text-muted-foreground font-mono overflow-x-auto whitespace-pre-wrap">
                  {formatSchemaPreview(targetSchema.schema)}
                </pre>
              </div>
            </div>
          )}

          {!sourceSchema && !targetSchema && (
            <div className="p-4 text-center text-sm text-muted-foreground bg-secondary/30 rounded-lg">
              No schemas defined for this connection
            </div>
          )}
        </div>

        {/* Actions */}
        <div className={`mt-4 pt-4 border-t border-border flex ${onDelete ? 'justify-between' : 'justify-end'}`}>
          {onDelete && (
            <button
              onClick={onDelete}
              className="px-4 py-2 text-sm font-medium text-red-600 bg-red-100 hover:bg-red-200 rounded-lg transition-colors"
            >
              Delete Connection
            </button>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-foreground bg-secondary hover:bg-muted rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

