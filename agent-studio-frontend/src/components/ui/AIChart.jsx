import React from 'react';
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area, PieChart, Pie,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell
} from 'recharts';

function SimpleTreeNode({ node, depth = 0 }) {
  if (!node || typeof node !== 'object') return null;
  const children = Array.isArray(node.children) ? node.children : [];
  const attributes = node.attributes && typeof node.attributes === 'object' ? node.attributes : {};
  const title = node.name || node.title || node.label || 'Node';
  const subtitle = attributes.title || attributes.role || node.role || node.department || '';

  return (
    <li className="relative pl-4">
      <div className={`rounded-lg border p-3 ${depth === 0 ? 'border-[#A32020] bg-[#FDF2F4]' : 'border-gray-200 bg-white'}`}>
        <div className="text-sm font-semibold text-gray-900">{title}</div>
        {subtitle ? <div className="mt-1 text-xs text-gray-600">{subtitle}</div> : null}
      </div>
      {children.length ? (
        <ul className="ml-4 mt-3 space-y-3 border-l border-gray-200 pl-4">
          {children.map((child, index) => (
            <SimpleTreeNode key={`${child?.name || child?.title || 'node'}-${index}`} node={child} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function SimpleTree({ data, height }) {
  return (
    <div className="overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-4" style={{ height }}>
      <ul className="space-y-3">
        <SimpleTreeNode node={data} />
      </ul>
    </div>
  );
}

/**
 * AIChart Component - AI-Friendly Visualization Tool
 * 
 * A flexible charting component designed for AI to generate visualizations
 * Supports: Bar, Line, Area, and Pie charts with simple JSON configuration
 * 
 * @param {Object} config - Complete chart configuration object
 * 
 * Example configurations:
 * 
 * BAR CHART:
 * {
 *   type: "bar",
 *   data: [
 *     { date: "2025-01-01", Desktop: 100, Mobile: 200 },
 *     { date: "2025-01-02", Desktop: 150, Mobile: 180 }
 *   ],
 *   xAxis: "date",
 *   series: [
 *     { dataKey: "Desktop", color: "#3b82f6", name: "Desktop Users" },
 *     { dataKey: "Mobile", color: "#10b981", name: "Mobile Users" }
 *   ],
 *   height: 300,
 *   title: "User Statistics",
 *   showGrid: true,
 *   showLegend: true
 * }
 * 
 * LINE CHART:
 * {
 *   type: "line",
 *   data: [...],
 *   xAxis: "date",
 *   series: [{ dataKey: "revenue", color: "#3b82f6", name: "Revenue" }],
 *   height: 300
 * }
 * 
 * PIE CHART:
 * {
 *   type: "pie",
 *   data: [
 *     { name: "Desktop", value: 400 },
 *     { name: "Mobile", value: 300 }
 *   ],
 *   height: 300
 * }
 * 
 * ORGANIZATIONAL TREE:
 * {
 *   type: "tree",
 *   data: {
 *     name: "CEO",
 *     attributes: { title: "Chief Executive Officer" },
 *     children: [
 *       { name: "CTO", attributes: { title: "Chief Technology Officer" } },
 *       { name: "CFO", attributes: { title: "Chief Financial Officer" } }
 *     ]
 *   },
 *   height: 500,
 *   orientation: "vertical"
 * }
 * 
 * REPORT CARD:
 * {
 *   type: "report",
 *   data: {
 *     title: "Q4 2024 Sales Report",
 *     summary: {
 *       totalRevenue: 1250000,
 *       growth: 15.3,
 *       topProduct: "Enterprise Suite"
 *     },
 *     sections: [
 *       {
 *         title: "Regional Performance",
 *         items: [
 *           { label: "North America", value: "$450,000", change: "+12%", status: "up" },
 *           { label: "Europe", value: "$380,000", change: "+8%", status: "up" }
 *         ]
 *       }
 *     ]
 *   }
 * }
 */
const AIChart = ({ config }) => {
  // Default values
  const {
    type = 'bar',
    data = [],
    xAxis = 'date',
    series = [],
    height = 300,
    width = '100%',
    title = '',
    showGrid = true,
    showLegend = true,
    showTooltip = true,
    orientation = 'vertical', // For tree: 'vertical' or 'horizontal'
    colors = ['#A32020', '#7A1818', '#EA9595', '#F4CACA', '#DB536A', '#BA2741', '#464646', '#7D7D7D'],
    className = ''
  } = config || {};

  // Types that use object data (not array)
  const objectDataTypes = ['tree', 'report', 'text_simple', 'text_sectioned', 'text_keyvalue', 'key_value', 'metric_cards', 'table'];
  const isObjectType = objectDataTypes.includes(type?.toLowerCase());

  // Validation
  if (!isObjectType && (!data || (Array.isArray(data) && data.length === 0))) {
    return (
      <div 
        className={`flex items-center justify-center bg-gray-50 rounded-lg border border-gray-200 ${className}`}
        style={{ height: `${height}px` }}
      >
        <p className="text-gray-500">No data available</p>
      </div>
    );
  }

  if (isObjectType && !data && !config?.metrics && !config?.columns && !config?.content && !config?.items) {
    return (
      <div 
        className={`flex items-center justify-center bg-gray-50 rounded-lg border border-gray-200 ${className}`}
        style={{ height: `${height}px` }}
      >
        <p className="text-gray-500">No data available</p>
      </div>
    );
  }

  // Render different chart types
  const renderChart = () => {
    switch (type.toLowerCase()) {
      case 'text_simple':
        return (
          <div className="prose max-w-none">
            {data.title && (
              <h2 className="text-2xl font-bold text-gray-900 mb-4 pb-2 border-b-2 border-gray-400">
                {data.title}
              </h2>
            )}
            <div className="text-gray-700 leading-relaxed whitespace-pre-wrap break-words" style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
              {data.content}
            </div>
          </div>
        );

      case 'text_sectioned':
        return (
          <div className="space-y-6">
            {data.title && (
              <h2 className="text-2xl font-bold text-gray-900 mb-4 pb-2 border-b-2 border-gray-400">
                {data.title}
              </h2>
            )}
            {data.sections && data.sections.map((section, idx) => (
              <div key={idx} className="space-y-2">
                <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
                  <span className="text-gray-700">▸</span>
                  {section.heading}
                </h3>
                <div className="ml-6 pl-4 border-l-2 border-gray-200">
                  <div className="text-gray-700 leading-relaxed whitespace-pre-wrap break-words" style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                    {section.content}
                  </div>
                </div>
              </div>
            ))}
          </div>
        );

      case 'text_keyvalue':
        return (
          <div className="space-y-4">
            {data.title && (
              <h2 className="text-2xl font-bold text-gray-900 mb-4 pb-2 border-b-2 border-gray-400">
                {data.title}
              </h2>
            )}
            <div className="grid gap-3">
              {data.items && data.items.map((item, idx) => (
                <div 
                  key={idx} 
                  className="flex items-start justify-between p-4 bg-gray-50 rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
                >
                  <div className="font-semibold text-gray-900 min-w-[150px]">
                    {item.key}
                  </div>
                  <div className="text-gray-700 text-right flex-1 break-words">
                    {item.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );

      case 'report':
        return (
          <div className="space-y-6">
            {/* Report Title */}
            {data.title && (
              <div className="border-b border-gray-200 pb-3">
                <h2 className="text-lg font-semibold text-gray-900">{data.title}</h2>
                {data.subtitle && (
                  <p className="text-sm text-gray-500 mt-1">{data.subtitle}</p>
                )}
              </div>
            )}

            {/* Summary Cards */}
            {data.summary && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {Object.entries(data.summary)
                  .filter(([, value]) => {
                    // Only render simple primitive values as metric cards
                    // Skip complex objects, arrays, and very long strings
                    if (typeof value === 'object' && value !== null) return false;
                    if (typeof value === 'string' && value.length > 200) return false;
                    return true;
                  })
                  .map(([key, value], idx) => {
                    const isMetric = typeof value === 'number';
                    const displayValue = isMetric && key.toLowerCase().includes('revenue') 
                      ? `$${(value / 1000).toFixed(0)}K`
                      : isMetric && key.toLowerCase().includes('growth')
                      ? `${value}%`
                      : String(value);
                    
                    return (
                      <div key={idx} className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg p-5 border border-gray-300">
                        <div className="text-sm font-medium text-gray-700 uppercase tracking-wide">
                          {key.replace(/([A-Z])/g, ' $1').trim()}
                        </div>
                        <div className="text-3xl font-bold text-gray-900 mt-2">
                          {displayValue}
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
            
            {/* Complex Summary Content (for nested structures) */}
            {data.summary && Object.entries(data.summary).some(([, v]) =>
              (typeof v === 'object' && v !== null) || (typeof v === 'string' && v.length > 200)
            ) && (
              <div className="bg-white rounded-lg border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Summary</h3>
                <div className="space-y-4">
                  {Object.entries(data.summary).map(([key, value], idx) => {
                    // Skip simple values already rendered as cards
                    if (typeof value !== 'object' && !(typeof value === 'string' && value.length > 200)) {
                      return null;
                    }
                    
                    return (
                      <div key={idx} className="border-l-4 border-gray-300 pl-4">
                        <div className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-2">
                          {key.replace(/([A-Z])/g, ' $1').replace(/_/g, ' ').trim()}
                        </div>
                        <div className="text-gray-800">
                          {typeof value === 'string' ? (
                            <p className="text-sm leading-relaxed">{value}</p>
                          ) : Array.isArray(value) ? (
                            <ul className="list-disc list-inside space-y-2">
                              {value.map((item, i) => (
                                <li key={i} className="text-sm">
                                  {typeof item === 'object' && item !== null ? (
                                    <div className="ml-4 mt-1 space-y-1">
                                      {Object.entries(item).map(([k, v]) => (
                                        <div key={k}>
                                          <span className="font-medium">{k}:</span> {String(v)}
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    String(item)
                                  )}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <div className="text-sm space-y-1">
                              {Object.entries(value).map(([k, v]) => (
                                <div key={k}>
                                  <span className="font-medium">{k}:</span> {String(v)}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Sections with hierarchical data */}
            {data.sections && data.sections.map((section, sectionIdx) => (
              <div key={sectionIdx} className="bg-white rounded-lg border border-gray-200">
                <div className="bg-gray-50 px-6 py-4 border-b border-gray-200">
                  <h3 className="text-lg font-semibold text-gray-900">{section.title}</h3>
                  {section.description && (
                    <p className="text-sm text-gray-600 mt-1">{section.description}</p>
                  )}
                </div>
                <div className="p-6">
                  <div className="space-y-4">
                    {section.items && section.items.map((item, itemIdx) => (
                      <div key={itemIdx}>
                        {/* Main Item */}
                        <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
                          <div className="flex-1">
                            <div className="flex items-center gap-3">
                              {item.icon && <span className="text-2xl">{item.icon}</span>}
                              <div>
                                <div className="font-semibold text-gray-900">{item.label}</div>
                                {item.sublabel && (
                                  <div className="text-sm text-gray-500">{item.sublabel}</div>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-4">
                            <div className="text-right">
                              <div className="text-xl font-bold text-gray-900">{item.value}</div>
                              {item.change && (
                                <div className={`text-sm font-medium flex items-center gap-1 justify-end ${
                                  item.status === 'up' ? 'text-gray-700' : 
                                  item.status === 'down' ? 'text-red-600' : 
                                  'text-gray-600'
                                }`}>
                                  {item.status === 'up' && '↑'}
                                  {item.status === 'down' && '↓'}
                                  {item.change}
                                </div>
                              )}
                            </div>
                            {item.badge && (
                              <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                                item.badge === 'high' ? 'bg-gray-200 text-gray-800' :
                                item.badge === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                                item.badge === 'low' ? 'bg-gray-100 text-gray-800' :
                                'bg-gray-100 text-gray-800'
                              }`}>
                                {item.badge}
                              </span>
                            )}
                          </div>
                        </div>
                        
                        {/* Sub Items (Hierarchy) */}
                        {item.children && item.children.length > 0 && (
                          <div className="ml-8 mt-2 space-y-2">
                            {item.children.map((child, childIdx) => (
                              <div key={childIdx} className="flex items-center justify-between p-3 bg-white border border-gray-200 rounded-lg">
                                <div className="flex items-center gap-2">
                                  <span className="text-gray-400">└─</span>
                                  <div>
                                    <div className="text-sm font-medium text-gray-700">{child.label}</div>
                                    {child.sublabel && (
                                      <div className="text-xs text-gray-500">{child.sublabel}</div>
                                    )}
                                  </div>
                                </div>
                                <div className="text-right">
                                  <div className="text-sm font-semibold text-gray-900">{child.value}</div>
                                  {child.change && (
                                    <div className={`text-xs ${
                                      child.status === 'up' ? 'text-gray-700' : 
                                      child.status === 'down' ? 'text-red-600' : 
                                      'text-gray-600'
                                    }`}>
                                      {child.status === 'up' && '↑'}
                                      {child.status === 'down' && '↓'}
                                      {child.change}
                                    </div>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}

            {/* Footer Notes */}
            {data.notes && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                <div className="flex gap-2">
                  <span className="text-yellow-600">💡</span>
                  <div className="text-sm text-yellow-800">{data.notes}</div>
                </div>
              </div>
            )}
          </div>
        );

      case 'bar':
        return (
          <ResponsiveContainer width={width} height={height}>
            <BarChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />}
              <XAxis dataKey={xAxis} stroke="#6b7280" style={{ fontSize: '12px' }} />
              <YAxis stroke="#6b7280" style={{ fontSize: '12px' }} />
              {showTooltip && <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }} />}
              {showLegend && <Legend wrapperStyle={{ fontSize: '14px' }} />}
              {series.map((s, idx) => (
                <Bar 
                  key={s.dataKey} 
                  dataKey={s.dataKey} 
                  fill={s.color || colors[idx % colors.length]}
                  name={s.name || s.dataKey}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        );

      case 'line':
        return (
          <ResponsiveContainer width={width} height={height}>
            <LineChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />}
              <XAxis dataKey={xAxis} stroke="#6b7280" style={{ fontSize: '12px' }} />
              <YAxis stroke="#6b7280" style={{ fontSize: '12px' }} />
              {showTooltip && <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }} />}
              {showLegend && <Legend wrapperStyle={{ fontSize: '14px' }} />}
              {series.map((s, idx) => (
                <Line 
                  key={s.dataKey} 
                  type="monotone"
                  dataKey={s.dataKey} 
                  stroke={s.color || colors[idx % colors.length]}
                  strokeWidth={2}
                  name={s.name || s.dataKey}
                  dot={{ fill: s.color || colors[idx % colors.length], r: 4 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        );

      case 'area':
        return (
          <ResponsiveContainer width={width} height={height}>
            <AreaChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />}
              <XAxis dataKey={xAxis} stroke="#6b7280" style={{ fontSize: '12px' }} />
              <YAxis stroke="#6b7280" style={{ fontSize: '12px' }} />
              {showTooltip && <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }} />}
              {showLegend && <Legend wrapperStyle={{ fontSize: '14px' }} />}
              {series.map((s, idx) => (
                <Area 
                  key={s.dataKey} 
                  type="monotone"
                  dataKey={s.dataKey} 
                  stroke={s.color || colors[idx % colors.length]}
                  fill={s.color || colors[idx % colors.length]}
                  fillOpacity={0.6}
                  name={s.name || s.dataKey}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        );

      case 'pie':
        return (
          <ResponsiveContainer width={width} height={height}>
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={Math.min(height * 0.35, 120)}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                labelLine={{ stroke: '#6b7280' }}
              >
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color || colors[index % colors.length]} />
                ))}
              </Pie>
              {showTooltip && <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }} />}
              {showLegend && <Legend wrapperStyle={{ fontSize: '14px' }} />}
            </PieChart>
          </ResponsiveContainer>
        );

      case 'tree':
        return (
          <SimpleTree data={data} height={height} orientation={orientation} />
        );

      case 'table':
        {
          const columns = config?.columns || [];
          const rows = config?.rows || [];
          if (!columns.length && !rows.length) {
            return <p className="text-gray-500">No table data available</p>;
          }
          // Auto-derive columns from rows if not provided
          const tableColumns = columns.length > 0 ? columns : 
            (rows.length > 0 ? Object.keys(rows[0]).map(k => ({ key: k, label: k.replace(/([A-Z])/g, ' $1').replace(/_/g, ' ').trim().replace(/\b\w/g, l => l.toUpperCase()) })) : []);
          
          return (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="border-b-2 border-gray-300 bg-gray-50">
                    {tableColumns.map((col, idx) => (
                      <th key={idx} className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">
                        {col.label || col.key}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, rowIdx) => (
                    <tr key={rowIdx} className="border-b border-gray-200 hover:bg-gray-50 transition-colors">
                      {tableColumns.map((col, colIdx) => (
                        <td key={colIdx} className="px-4 py-3 text-gray-700">
                          {String(row[col.key] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

      case 'metric_cards':
        {
          const metrics = config?.metrics || [];
          if (!metrics.length) {
            return <p className="text-gray-500">No metrics available</p>;
          }
          return (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {metrics.map((metric, idx) => (
                <div key={idx} className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg p-5 border border-gray-300">
                  <div className="text-sm font-medium text-gray-600 uppercase tracking-wide">
                    {metric.label}
                  </div>
                  <div className="text-3xl font-bold text-gray-900 mt-2">
                    {metric.value}
                  </div>
                  {metric.change && (
                    <div className={`text-sm font-medium mt-1 flex items-center gap-1 ${
                      metric.status === 'up' ? 'text-green-700' : 
                      metric.status === 'down' ? 'text-red-600' : 
                      'text-gray-600'
                    }`}>
                      {metric.status === 'up' && '↑'}
                      {metric.status === 'down' && '↓'}
                      {metric.change}
                    </div>
                  )}
                </div>
              ))}
            </div>
          );
        }

      case 'key_value':
        {
          const kvTitle = config?.title || data?.title;
          const kvItems = config?.items || data?.items || [];
          return (
            <div className="space-y-4">
              {kvTitle && (
                <h2 className="text-2xl font-bold text-gray-900 mb-4 pb-2 border-b-2 border-gray-400">
                  {kvTitle}
                </h2>
              )}
              <div className="grid gap-3">
                {kvItems.map((item, idx) => (
                  <div 
                    key={idx} 
                    className="flex items-start justify-between p-4 bg-gray-50 rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
                  >
                    <div className="font-semibold text-gray-900 min-w-[150px]">
                      {item.key}
                    </div>
                    <div className="text-gray-700 text-right flex-1 break-words">
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        }

      default:
        return (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500">Unsupported chart type: {type}</p>
          </div>
        );
    }
  };

  // Skip outer title for types that render their own title internally
  const hasInternalTitle = ['report', 'text_simple', 'text_sectioned', 'text_keyvalue', 'key_value', 'metric_cards', 'table'].includes(type?.toLowerCase());

  return (
    <div className={`bg-white rounded-lg border border-gray-200 p-4 ${className}`}>
      {title && !hasInternalTitle && (
        <h3 className="text-lg font-semibold text-gray-900 mb-4">{title}</h3>
      )}
      {renderChart()}
    </div>
  );
};

export default AIChart;

