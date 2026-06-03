import React, { useState } from 'react';
import Chart from '../ui/Chart';

/**
 * ChartTest Component
 * A test page for the Chart component with various examples and configurations
 */
const ChartTest = () => {
  const [selectedExample, setSelectedExample] = useState('simple');
  const [mode, setMode] = useState('examples'); // 'examples' or 'live'
  const [liveCode, setLiveCode] = useState(`<Chart
  data={[{ date: "2025-01-01", Desktop: 100, Mobile: 200 }]}
  series={[{ type: "bar", dataKey: "Desktop" }]}
  xAxis="date"
  height={240}
/>`);
  const [parsedProps, setParsedProps] = useState(null);
  const [parseError, setParseError] = useState(null);

  // Example data sets
  const examples = {
    simple: {
      title: 'Simple Bar Chart (Your Example)',
      data: [{ date: "2025-01-01", Desktop: 100, Mobile: 200 }],
      series: [{ type: "bar", dataKey: "Desktop" }],
      xAxis: "date",
      height: 240
    },
    twoSeries: {
      title: 'Two Series Bar Chart',
      data: [{ date: "2025-01-01", Desktop: 100, Mobile: 200 }],
      series: [
        { type: "bar", dataKey: "Desktop", color: "#3b82f6" },
        { type: "bar", dataKey: "Mobile", color: "#10b981" }
      ],
      xAxis: "date",
      height: 240
    },
    multipleDataPoints: {
      title: 'Multiple Data Points',
      data: [
        { date: "Jan", Desktop: 100, Mobile: 200 },
        { date: "Feb", Desktop: 150, Mobile: 180 },
        { date: "Mar", Desktop: 200, Mobile: 220 },
        { date: "Apr", Desktop: 180, Mobile: 250 },
        { date: "May", Desktop: 220, Mobile: 280 }
      ],
      series: [
        { type: "bar", dataKey: "Desktop", color: "#3b82f6" },
        { type: "bar", dataKey: "Mobile", color: "#10b981" }
      ],
      xAxis: "date",
      height: 300
    },
    sales: {
      title: 'Sales Data',
      data: [
        { month: "Q1", Revenue: 45000, Expenses: 32000, Profit: 13000 },
        { month: "Q2", Revenue: 52000, Expenses: 35000, Profit: 17000 },
        { month: "Q3", Revenue: 48000, Expenses: 33000, Profit: 15000 },
        { month: "Q4", Revenue: 61000, Expenses: 38000, Profit: 23000 }
      ],
      series: [
        { type: "bar", dataKey: "Revenue", color: "#3b82f6" },
        { type: "bar", dataKey: "Expenses", color: "#ef4444" },
        { type: "bar", dataKey: "Profit", color: "#10b981" }
      ],
      xAxis: "month",
      height: 300
    },
    empty: {
      title: 'Empty Data (Error State)',
      data: [],
      series: [{ type: "bar", dataKey: "Desktop" }],
      xAxis: "date",
      height: 240
    }
  };

  const currentExample = examples[selectedExample];

  // Parse the live code
  const handleRenderLiveCode = () => {
    try {
      setParseError(null);
      
      // Extract props from the JSX-like string - improved regex to handle nested brackets
      const dataMatch = liveCode.match(/data=\{(\[[\s\S]*?\])\}/);
      const seriesMatch = liveCode.match(/series=\{(\[[\s\S]*?\])\}/);
      const xAxisMatch = liveCode.match(/xAxis="([^"]+)"/);
      const heightMatch = liveCode.match(/height=\{(\d+)\}/);
      
      if (!dataMatch) {
        throw new Error('Could not parse data prop. Make sure it follows the format: data={[...]}');
      }
      if (!seriesMatch) {
        throw new Error('Could not parse series prop. Make sure it follows the format: series={[...]}');
      }
      
      const data = JSON.parse(dataMatch[1]);
      const series = JSON.parse(seriesMatch[1]);
      const xAxis = xAxisMatch ? xAxisMatch[1] : 'date';
      const height = heightMatch ? parseInt(heightMatch[1]) : 240;
      
      setParsedProps({ data, series, xAxis, height });
    } catch (error) {
      setParseError(error.message);
      setParsedProps(null);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            Chart Component Test Page
          </h1>
          <p className="text-gray-600">
            Test different configurations and data for the Chart component
          </p>
        </div>

        {/* Mode Selector */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Mode
          </h2>
          <div className="flex gap-2">
            <button
              onClick={() => setMode('examples')}
              className={`px-6 py-3 rounded-lg font-medium transition-colors ${
                mode === 'examples'
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              📊 Examples
            </button>
            <button
              onClick={() => setMode('live')}
              className={`px-6 py-3 rounded-lg font-medium transition-colors ${
                mode === 'live'
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              ✏️ Live Editor
            </button>
          </div>
        </div>

        {/* Examples Mode */}
        {mode === 'examples' && (
          <>
            {/* Example Selector */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Select Example
              </h2>
              <div className="flex flex-wrap gap-2">
                {Object.keys(examples).map((key) => (
                  <button
                    key={key}
                    onClick={() => setSelectedExample(key)}
                    className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                      selectedExample === key
                        ? 'bg-blue-500 text-white'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {examples[key].title}
                  </button>
                ))}
              </div>
            </div>

            {/* Chart Display */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                {currentExample.title}
              </h2>
              <Chart
                data={currentExample.data}
                series={currentExample.series}
                xAxis={currentExample.xAxis}
                height={currentExample.height}
              />
            </div>

            {/* Configuration Display */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Configuration
              </h2>
              <div className="bg-gray-50 rounded-lg p-4 font-mono text-sm overflow-x-auto">
                <pre className="text-gray-800">
{`<Chart
  data={${JSON.stringify(currentExample.data, null, 2)}}
  series={${JSON.stringify(currentExample.series, null, 2)}}
  xAxis="${currentExample.xAxis}"
  height={${currentExample.height}}
/>`}
                </pre>
              </div>
            </div>
          </>
        )}

        {/* Live Editor Mode */}
        {mode === 'live' && (
          <>
            {/* Code Editor */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Paste Your Chart Widget Code
              </h2>
              <textarea
                value={liveCode}
                onChange={(e) => setLiveCode(e.target.value)}
                className="w-full h-64 p-4 font-mono text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="Paste your Chart component JSX here..."
              />
              <div className="mt-4 flex gap-3">
                <button
                  onClick={handleRenderLiveCode}
                  className="px-6 py-2 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition-colors"
                >
                  🚀 Render Chart
                </button>
                <button
                  onClick={() => {
                    setLiveCode(`<Chart
  data={[{ date: "2025-01-01", Desktop: 100, Mobile: 200 }]}
  series={[{ type: "bar", dataKey: "Desktop" }]}
  xAxis="date"
  height={240}
/>`);
                    setParsedProps(null);
                    setParseError(null);
                  }}
                  className="px-6 py-2 bg-gray-200 text-gray-700 rounded-lg font-medium hover:bg-gray-300 transition-colors"
                >
                  Reset
                </button>
              </div>
              {parseError && (
                <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                  <p className="text-red-700 font-semibold">Error:</p>
                  <p className="text-red-600 text-sm mt-1">{parseError}</p>
                </div>
              )}
            </div>

            {/* Live Chart Display */}
            {parsedProps && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">
                  Your Chart
                </h2>
                <Chart
                  data={parsedProps.data}
                  series={parsedProps.series}
                  xAxis={parsedProps.xAxis}
                  height={parsedProps.height}
                />
              </div>
            )}
          </>
        )}

        {/* Props Documentation */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mt-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Component Props
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left p-3 font-semibold text-gray-700">Prop</th>
                  <th className="text-left p-3 font-semibold text-gray-700">Type</th>
                  <th className="text-left p-3 font-semibold text-gray-700">Default</th>
                  <th className="text-left p-3 font-semibold text-gray-700">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                <tr>
                  <td className="p-3 font-mono text-blue-600">data</td>
                  <td className="p-3 font-mono text-gray-600">Array</td>
                  <td className="p-3 font-mono text-gray-500">[]</td>
                  <td className="p-3 text-gray-700">Array of data objects to visualize</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">series</td>
                  <td className="p-3 font-mono text-gray-600">Array</td>
                  <td className="p-3 font-mono text-gray-500">[]</td>
                  <td className="p-3 text-gray-700">Array of series config objects with type, dataKey, color</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">xAxis</td>
                  <td className="p-3 font-mono text-gray-600">string</td>
                  <td className="p-3 font-mono text-gray-500">"date"</td>
                  <td className="p-3 text-gray-700">Key name for x-axis values from data objects</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">height</td>
                  <td className="p-3 font-mono text-gray-600">number</td>
                  <td className="p-3 font-mono text-gray-500">240</td>
                  <td className="p-3 text-gray-700">Height of the chart in pixels</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">className</td>
                  <td className="p-3 font-mono text-gray-600">string</td>
                  <td className="p-3 font-mono text-gray-500">""</td>
                  <td className="p-3 text-gray-700">Additional CSS classes</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChartTest;

