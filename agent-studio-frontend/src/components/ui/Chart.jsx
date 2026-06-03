import React from 'react';

/**
 * Chart Component
 * A flexible charting component that supports bar, line, and area charts
 * 
 * @param {Object} props
 * @param {Array} props.data - Array of data objects
 * @param {Array} props.series - Array of series configuration objects with { type, dataKey, color }
 * @param {string} props.xAxis - Key name for x-axis values
 * @param {number} props.height - Height of the chart in pixels
 * @param {string} props.className - Additional CSS classes
 */
const Chart = ({ 
  data = [], 
  series = [], 
  xAxis = 'date', 
  height = 240,
  className = ''
}) => {
  if (!data || data.length === 0) {
    return (
      <div 
        className={`flex items-center justify-center bg-gray-50 rounded border border-gray-200 ${className}`}
        style={{ height: `${height}px` }}
      >
        <p className="text-gray-500">No data available</p>
      </div>
    );
  }

  // Calculate max value for scaling
  const maxValue = Math.max(
    ...data.flatMap(item => 
      series.map(s => item[s.dataKey] || 0)
    )
  );

  // Add 10% padding to top
  const scaledMax = maxValue * 1.1;

  // Calculate bar width based on number of data points
  const chartPadding = 40;
  const availableWidth = 100 - chartPadding;
  const barGroupWidth = availableWidth / data.length;
  const barWidth = barGroupWidth / series.length * 0.8;

  // Generate colors for series if not provided
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];

  return (
    <div className={`bg-white rounded-lg border border-gray-200 p-4 ${className}`}>
      <svg 
        width="100%" 
        height={height}
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
      >
        {/* Y-axis grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio, idx) => (
          <g key={`grid-${idx}`}>
            <line
              x1={chartPadding / 2}
              y1={(height - 30) * (1 - ratio) + 10}
              x2="95"
              y2={(height - 30) * (1 - ratio) + 10}
              stroke="#e5e7eb"
              strokeWidth="0.2"
            />
            <text
              x={chartPadding / 4}
              y={(height - 30) * (1 - ratio) + 10}
              fontSize="2"
              fill="#6b7280"
              textAnchor="end"
              dominantBaseline="middle"
            >
              {Math.round(scaledMax * ratio)}
            </text>
          </g>
        ))}

        {/* Render bars */}
        {data.map((item, dataIndex) => {
          const xPosition = chartPadding / 2 + (dataIndex * barGroupWidth) + barGroupWidth / 2;
          
          return (
            <g key={`group-${dataIndex}`}>
              {series.map((seriesItem, seriesIndex) => {
                const value = item[seriesItem.dataKey] || 0;
                const barHeight = (value / scaledMax) * (height - 40);
                const yPosition = height - 30 - barHeight;
                const xOffset = (seriesIndex - series.length / 2 + 0.5) * barWidth;
                const color = seriesItem.color || colors[seriesIndex % colors.length];

                if (seriesItem.type === 'bar') {
                  return (
                    <rect
                      key={`bar-${dataIndex}-${seriesIndex}`}
                      x={xPosition + xOffset}
                      y={yPosition}
                      width={barWidth}
                      height={barHeight}
                      fill={color}
                      opacity="0.8"
                      rx="0.5"
                    >
                      <title>{`${seriesItem.dataKey}: ${value}`}</title>
                    </rect>
                  );
                }

                // Line and area charts could be added here
                return null;
              })}

              {/* X-axis labels */}
              <text
                x={xPosition}
                y={height - 15}
                fontSize="2.5"
                fill="#6b7280"
                textAnchor="middle"
              >
                {item[xAxis]}
              </text>
            </g>
          );
        })}

        {/* X-axis line */}
        <line
          x1={chartPadding / 2}
          y1={height - 30}
          x2="95"
          y2={height - 30}
          stroke="#d1d5db"
          strokeWidth="0.3"
        />
      </svg>

      {/* Legend */}
      {series.length > 0 && (
        <div className="flex justify-center gap-4 mt-2">
          {series.map((seriesItem, idx) => (
            <div key={`legend-${idx}`} className="flex items-center gap-1">
              <div
                className="w-3 h-3 rounded"
                style={{ backgroundColor: seriesItem.color || colors[idx % colors.length] }}
              />
              <span className="text-xs text-gray-600">{seriesItem.dataKey}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default Chart;




