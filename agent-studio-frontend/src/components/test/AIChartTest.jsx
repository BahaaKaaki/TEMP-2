import React, { useState } from 'react';
import AIChart from '../ui/AIChart';

/**
 * AIChartTest Component
 * Test page for AI-friendly chart configurations
 */
const AIChartTest = () => {
  const [mode, setMode] = useState('examples');
  const [selectedExample, setSelectedExample] = useState('bar');

  // Override body overflow to enable scrolling
  React.useEffect(() => {
    document.body.style.overflow = 'auto';
    document.getElementById('root').style.height = 'auto';
    
    return () => {
      document.body.style.overflow = 'hidden';
      document.getElementById('root').style.height = '100vh';
    };
  }, []);
  const [liveConfig, setLiveConfig] = useState(JSON.stringify({
    type: "bar",
    data: [
      { date: "2025-01-01", Desktop: 100, Mobile: 200 },
      { date: "2025-01-02", Desktop: 200, Mobile: 100 }
    ],
    xAxis: "date",
    series: [
      { dataKey: "Desktop", color: "#3b82f6", name: "Desktop Users" },
      { dataKey: "Mobile", color: "#10b981", name: "Mobile Users" }
    ],
    height: 300,
    title: "User Statistics",
    showGrid: true,
    showLegend: true
  }, null, 2));
  const [parsedConfig, setParsedConfig] = useState(null);
  const [parseError, setParseError] = useState(null);

  // AI-Friendly Example Configurations
  const examples = {
    bar: {
      title: "Bar Chart - Multi Series",
      config: {
        type: "bar",
        data: [
          { month: "Jan", Sales: 4000, Revenue: 2400, Profit: 1600 },
          { month: "Feb", Sales: 3000, Revenue: 1398, Profit: 1602 },
          { month: "Mar", Sales: 2000, Revenue: 9800, Profit: 7800 },
          { month: "Apr", Sales: 2780, Revenue: 3908, Profit: 1128 },
          { month: "May", Sales: 1890, Revenue: 4800, Profit: 2910 },
          { month: "Jun", Sales: 2390, Revenue: 3800, Profit: 1410 }
        ],
        xAxis: "month",
        series: [
          { dataKey: "Sales", color: "#3b82f6", name: "Total Sales" },
          { dataKey: "Revenue", color: "#10b981", name: "Revenue" },
          { dataKey: "Profit", color: "#f59e0b", name: "Profit" }
        ],
        height: 350,
        title: "Monthly Business Metrics",
        showGrid: true,
        showLegend: true
      }
    },
    line: {
      title: "Line Chart - Trends",
      config: {
        type: "line",
        data: [
          { date: "Week 1", Users: 120, ActiveUsers: 80 },
          { date: "Week 2", Users: 150, ActiveUsers: 95 },
          { date: "Week 3", Users: 180, ActiveUsers: 120 },
          { date: "Week 4", Users: 220, ActiveUsers: 160 },
          { date: "Week 5", Users: 280, ActiveUsers: 210 }
        ],
        xAxis: "date",
        series: [
          { dataKey: "Users", color: "#3b82f6", name: "Total Users" },
          { dataKey: "ActiveUsers", color: "#10b981", name: "Active Users" }
        ],
        height: 300,
        title: "User Growth Trend",
        showGrid: true,
        showLegend: true
      }
    },
    area: {
      title: "Area Chart - Cumulative",
      config: {
        type: "area",
        data: [
          { quarter: "Q1", Product_A: 2400, Product_B: 1800 },
          { quarter: "Q2", Product_A: 3200, Product_B: 2200 },
          { quarter: "Q3", Product_A: 4100, Product_B: 2800 },
          { quarter: "Q4", Product_A: 5200, Product_B: 3600 }
        ],
        xAxis: "quarter",
        series: [
          { dataKey: "Product_A", color: "#3b82f6", name: "Product A" },
          { dataKey: "Product_B", color: "#10b981", name: "Product B" }
        ],
        height: 300,
        title: "Product Performance",
        showGrid: true,
        showLegend: true
      }
    },
    pie: {
      title: "Pie Chart - Distribution",
      config: {
        type: "pie",
        data: [
          { name: "Desktop", value: 400, color: "#3b82f6" },
          { name: "Mobile", value: 300, color: "#10b981" },
          { name: "Tablet", value: 200, color: "#f59e0b" },
          { name: "Other", value: 100, color: "#ef4444" }
        ],
        height: 350,
        title: "Device Usage Distribution",
        showLegend: true
      }
    },
    simple: {
      title: "Simple Bar Chart",
      config: {
        type: "bar",
        data: [
          { date: "2025-01-01", Desktop: 100, Mobile: 200 },
          { date: "2025-01-02", Desktop: 200, Mobile: 100 }
        ],
        xAxis: "date",
        series: [
          { dataKey: "Desktop" },
          { dataKey: "Mobile" }
        ],
        height: 240
      }
    },
    report: {
      title: "Sales Report Card",
      config: {
        type: "report",
        data: {
          title: "Q4 2024 Sales Performance Report",
          subtitle: "October - December 2024",
          summary: {
            totalRevenue: 1250000,
            growth: 15.3,
            topProduct: "Enterprise Suite"
          },
          sections: [
            {
              title: "Regional Performance",
              description: "Sales breakdown by geographic region",
              items: [
                {
                  label: "North America",
                  sublabel: "USA, Canada, Mexico",
                  value: "$450,000",
                  change: "+12%",
                  status: "up",
                  badge: "high",
                  icon: "🌎",
                  children: [
                    { label: "West Coast", value: "$180,000", change: "+15%", status: "up" },
                    { label: "East Coast", value: "$150,000", change: "+10%", status: "up" },
                    { label: "Central", value: "$120,000", change: "+8%", status: "up" }
                  ]
                },
                {
                  label: "Europe",
                  sublabel: "EU, UK, Switzerland",
                  value: "$380,000",
                  change: "+8%",
                  status: "up",
                  badge: "high",
                  icon: "🌍",
                  children: [
                    { label: "UK & Ireland", value: "$150,000", change: "+12%", status: "up" },
                    { label: "Central Europe", value: "$130,000", change: "+6%", status: "up" },
                    { label: "Nordic", value: "$100,000", change: "+5%", status: "up" }
                  ]
                },
                {
                  label: "Asia Pacific",
                  sublabel: "China, Japan, Australia",
                  value: "$280,000",
                  change: "+22%",
                  status: "up",
                  badge: "high",
                  icon: "🌏",
                  children: [
                    { label: "China", value: "$120,000", change: "+30%", status: "up" },
                    { label: "Japan", value: "$90,000", change: "+18%", status: "up" },
                    { label: "Australia", value: "$70,000", change: "+15%", status: "up" }
                  ]
                },
                {
                  label: "Latin America",
                  sublabel: "Brazil, Argentina, Chile",
                  value: "$140,000",
                  change: "-3%",
                  status: "down",
                  badge: "medium",
                  icon: "🌎",
                  children: [
                    { label: "Brazil", value: "$80,000", change: "+2%", status: "up" },
                    { label: "Argentina", value: "$35,000", change: "-12%", status: "down" },
                    { label: "Chile", value: "$25,000", change: "-5%", status: "down" }
                  ]
                }
              ]
            },
            {
              title: "Product Line Performance",
              description: "Revenue by product category",
              items: [
                {
                  label: "Enterprise Suite",
                  sublabel: "Full-featured business solution",
                  value: "$520,000",
                  change: "+18%",
                  status: "up",
                  badge: "high",
                  icon: "🏢",
                  children: [
                    { label: "Annual Licenses", value: "$350,000", change: "+20%", status: "up" },
                    { label: "Professional Services", value: "$120,000", change: "+15%", status: "up" },
                    { label: "Support & Maintenance", value: "$50,000", change: "+10%", status: "up" }
                  ]
                },
                {
                  label: "Cloud Platform",
                  sublabel: "SaaS infrastructure",
                  value: "$380,000",
                  change: "+25%",
                  status: "up",
                  badge: "high",
                  icon: "☁️",
                  children: [
                    { label: "Monthly Subscriptions", value: "$250,000", change: "+30%", status: "up" },
                    { label: "API Usage", value: "$90,000", change: "+20%", status: "up" },
                    { label: "Storage", value: "$40,000", change: "+15%", status: "up" }
                  ]
                },
                {
                  label: "Mobile Apps",
                  sublabel: "iOS and Android applications",
                  value: "$220,000",
                  change: "+12%",
                  status: "up",
                  badge: "medium",
                  icon: "📱",
                  children: [
                    { label: "Premium Features", value: "$140,000", change: "+15%", status: "up" },
                    { label: "In-App Purchases", value: "$80,000", change: "+8%", status: "up" }
                  ]
                },
                {
                  label: "Legacy Products",
                  sublabel: "Maintenance mode",
                  value: "$130,000",
                  change: "-8%",
                  status: "down",
                  badge: "low",
                  icon: "📦",
                  children: [
                    { label: "Desktop Suite", value: "$80,000", change: "-10%", status: "down" },
                    { label: "On-Premise Licenses", value: "$50,000", change: "-5%", status: "down" }
                  ]
                }
              ]
            },
            {
              title: "Customer Segments",
              description: "Revenue by customer type",
              items: [
                {
                  label: "Enterprise (1000+ employees)",
                  value: "$650,000",
                  change: "+15%",
                  status: "up",
                  badge: "high",
                  icon: "🏛️",
                  children: [
                    { label: "Fortune 500", value: "$400,000", change: "+18%", status: "up" },
                    { label: "Large Enterprise", value: "$250,000", change: "+10%", status: "up" }
                  ]
                },
                {
                  label: "Mid-Market (100-999 employees)",
                  value: "$380,000",
                  change: "+20%",
                  status: "up",
                  badge: "high",
                  icon: "🏢",
                  children: [
                    { label: "Growth Companies", value: "$220,000", change: "+25%", status: "up" },
                    { label: "Established Mid-Market", value: "$160,000", change: "+12%", status: "up" }
                  ]
                },
                {
                  label: "SMB (1-99 employees)",
                  value: "$220,000",
                  change: "+10%",
                  status: "up",
                  badge: "medium",
                  icon: "🏪",
                  children: [
                    { label: "Small Business", value: "$140,000", change: "+12%", status: "up" },
                    { label: "Startups", value: "$80,000", change: "+6%", status: "up" }
                  ]
                }
              ]
            }
          ],
          notes: "Strong performance across most regions and products. Focus on revitalizing Latin America market and transitioning legacy product customers to modern solutions."
        },
        title: "Sales Performance Dashboard"
      }
    },
    text_simple: {
      title: "Simple Text Card",
      config: {
        type: "text_simple",
        data: {
          title: "Analysis Summary",
          content: "Based on the comprehensive data analysis conducted over Q4 2024, we have identified several significant patterns in user behavior and system performance.\n\nKey findings indicate a 15% increase in conversion rates, particularly among mobile users during evening hours. The implementation of the new checkout flow has reduced cart abandonment by 23%, exceeding our initial projections.\n\nAdditionally, user engagement metrics show sustained growth across all demographics, with the 25-34 age group demonstrating the highest retention rates. These insights suggest that our recent UI improvements and personalization features are effectively meeting user needs."
        }
      }
    },
    text_sectioned: {
      title: "Sectioned Text Card",
      config: {
        type: "text_sectioned",
        data: {
          title: "Research Findings Report",
          sections: [
            {
              heading: "Executive Summary",
              content: "This research examined user engagement patterns over a 6-month period, analyzing data from over 50,000 active users. Our findings reveal critical insights into user preferences and behavior that will inform future product development."
            },
            {
              heading: "Methodology",
              content: "We employed a mixed-methods approach combining quantitative analytics with qualitative user interviews. Data was collected through in-app tracking, surveys, and moderated user testing sessions. Statistical analysis was performed using regression models to identify correlation patterns."
            },
            {
              heading: "Key Findings",
              content: "Three major trends emerged from our analysis:\n\n1. Mobile-first users show 40% higher engagement rates\n2. Personalized content recommendations increase session duration by 65%\n3. Social sharing features drive 30% of new user acquisition"
            },
            {
              heading: "Recommendations",
              content: "Based on these findings, we recommend prioritizing mobile optimization, expanding personalization algorithms, and investing in social integration features. Implementation should be phased over the next two quarters with continuous A/B testing."
            },
            {
              heading: "Conclusion",
              content: "The research demonstrates clear opportunities for growth through targeted improvements in user experience. By focusing on mobile optimization and personalization, we can significantly enhance user satisfaction and retention rates."
            }
          ]
        }
      }
    },
    text_keyvalue: {
      title: "Key-Value Text Card",
      config: {
        type: "text_keyvalue",
        data: {
          title: "System Configuration Details",
          items: [
            { key: "Environment", value: "Production" },
            { key: "Status", value: "Active and Running" },
            { key: "Last Deployment", value: "2024-12-15 14:30 UTC" },
            { key: "Version", value: "v2.4.1" },
            { key: "Database Connection", value: "PostgreSQL 14.2 (Primary + 2 Replicas)" },
            { key: "Cache Layer", value: "Redis 7.0 Cluster Mode" },
            { key: "CDN Provider", value: "Cloudflare Enterprise" },
            { key: "Region", value: "us-east-1 (Primary), eu-west-1 (Failover)" },
            { key: "SSL Certificate", value: "Valid until 2025-06-30" },
            { key: "API Rate Limit", value: "10,000 requests/hour per client" },
            { key: "Backup Schedule", value: "Hourly incremental, Daily full backup" },
            { key: "Monitoring", value: "Datadog, Sentry, Uptime Robot" }
          ]
        }
      }
    },
    tree: {
      title: "Organization Tree",
      config: {
        type: "tree",
        data: {
          name: "Sarah Johnson",
          attributes: {
            title: "CEO",
            department: "Executive"
          },
          children: [
            {
              name: "Michael Chen",
              attributes: {
                title: "CTO",
                department: "Technology"
              },
              children: [
                {
                  name: "Emily Rodriguez",
                  attributes: {
                    title: "Engineering Manager",
                    department: "Engineering"
                  },
                  children: [
                    { name: "Dev Team 1", attributes: { title: "5 Engineers" } },
                    { name: "Dev Team 2", attributes: { title: "4 Engineers" } }
                  ]
                },
                {
                  name: "James Wilson",
                  attributes: {
                    title: "Product Manager",
                    department: "Product"
                  }
                }
              ]
            },
            {
              name: "Lisa Anderson",
              attributes: {
                title: "CFO",
                department: "Finance"
              },
              children: [
                {
                  name: "David Brown",
                  attributes: {
                    title: "Controller",
                    department: "Accounting"
                  }
                },
                {
                  name: "Maria Garcia",
                  attributes: {
                    title: "Finance Manager",
                    department: "Finance"
                  }
                }
              ]
            },
            {
              name: "Robert Taylor",
              attributes: {
                title: "CMO",
                department: "Marketing"
              },
              children: [
                {
                  name: "Jennifer Lee",
                  attributes: {
                    title: "Marketing Manager",
                    department: "Digital Marketing"
                  }
                }
              ]
            }
          ]
        },
        height: 600,
        orientation: "vertical",
        title: "Company Organization Chart"
      }
    }
  };

  const currentExample = examples[selectedExample];

  const handleRenderLiveConfig = () => {
    try {
      setParseError(null);
      const config = JSON.parse(liveConfig);
      setParsedConfig(config);
    } catch (error) {
      setParseError(error.message);
      setParsedConfig(null);
    }
  };

  return (
    <div className="w-full min-h-screen bg-gray-50 p-8">
      <div className="max-w-7xl mx-auto pb-20">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            AI-Friendly Chart Component
          </h1>
          <p className="text-gray-600 mb-4">
            Simple JSON configurations for AI to generate beautiful visualizations
          </p>
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="text-sm text-blue-800">
              <span className="font-semibold">💡 For AI:</span> This component accepts a single JSON config object with:
              <code className="bg-blue-100 px-2 py-1 rounded mx-1">type</code>,
              <code className="bg-blue-100 px-2 py-1 rounded mx-1">data</code>,
              <code className="bg-blue-100 px-2 py-1 rounded mx-1">series</code>,
              <code className="bg-blue-100 px-2 py-1 rounded mx-1">xAxis</code>, and optional styling props.
            </p>
          </div>
        </div>

        {/* Mode Selector */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
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
              🤖 AI Playground
            </button>
          </div>
        </div>

        {/* Examples Mode */}
        {mode === 'examples' && (
          <>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Select Chart Type
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {Object.keys(examples).map((key) => (
                  <button
                    key={key}
                    onClick={() => setSelectedExample(key)}
                    className={`px-4 py-3 rounded-lg font-medium transition-colors ${
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

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Chart Display */}
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">
                  Visual Output
                </h2>
                <div className={selectedExample === 'tree' ? 'overflow-x-auto' : ''}>
                  <AIChart config={currentExample.config} />
                </div>
              </div>

              {/* Configuration Display */}
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">
                  JSON Configuration
                </h2>
                <div className="bg-gray-900 rounded-lg p-4 font-mono text-xs overflow-x-auto max-h-[500px] overflow-y-auto">
                  <pre className="text-green-400">
{JSON.stringify(currentExample.config, null, 2)}
                  </pre>
                </div>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(JSON.stringify(currentExample.config, null, 2));
                    alert('Configuration copied to clipboard!');
                  }}
                  className="mt-4 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg font-medium hover:bg-gray-300 transition-colors"
                >
                  📋 Copy Config
                </button>
              </div>
            </div>
          </>
        )}

        {/* AI Playground Mode */}
        {mode === 'live' && (
          <>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                🤖 Paste JSON Configuration
              </h2>
              <p className="text-sm text-gray-600 mb-4">
                AI can generate a complete JSON config and paste it here to create visualizations
              </p>
              <textarea
                value={liveConfig}
                onChange={(e) => setLiveConfig(e.target.value)}
                className="w-full h-96 p-4 font-mono text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white text-gray-800"
                placeholder="Paste JSON configuration here..."
              />
              <div className="mt-4 flex gap-3">
                <button
                  onClick={handleRenderLiveConfig}
                  className="px-6 py-2 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition-colors"
                >
                  🚀 Render Chart
                </button>
                <button
                  onClick={() => {
                    setLiveConfig(JSON.stringify(examples.bar.config, null, 2));
                    setParsedConfig(null);
                    setParseError(null);
                  }}
                  className="px-6 py-2 bg-gray-200 text-gray-700 rounded-lg font-medium hover:bg-gray-300 transition-colors"
                >
                  Reset to Example
                </button>
              </div>
              {parseError && (
                <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                  <p className="text-red-700 font-semibold">JSON Parse Error:</p>
                  <p className="text-red-600 text-sm mt-1">{parseError}</p>
                </div>
              )}
            </div>

            {parsedConfig && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">
                  Generated Chart
                </h2>
                <AIChart config={parsedConfig} />
              </div>
            )}
          </>
        )}

        {/* API Documentation */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mt-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Configuration Reference
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left p-3 font-semibold text-gray-700">Property</th>
                  <th className="text-left p-3 font-semibold text-gray-700">Type</th>
                  <th className="text-left p-3 font-semibold text-gray-700">Required</th>
                  <th className="text-left p-3 font-semibold text-gray-700">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                <tr>
                  <td className="p-3 font-mono text-blue-600">type</td>
                  <td className="p-3 font-mono text-gray-600">string</td>
                  <td className="p-3 text-gray-500">Yes</td>
                  <td className="p-3 text-gray-700">"bar" | "line" | "area" | "pie" | "tree" | "report"</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">data</td>
                  <td className="p-3 font-mono text-gray-600">Array | Object</td>
                  <td className="p-3 text-gray-500">Yes</td>
                  <td className="p-3 text-gray-700">Array for charts, hierarchical object for tree</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">series</td>
                  <td className="p-3 font-mono text-gray-600">Array</td>
                  <td className="p-3 text-gray-500">Yes*</td>
                  <td className="p-3 text-gray-700">Array of {`{ dataKey, color?, name? }`} (*not for pie)</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">xAxis</td>
                  <td className="p-3 font-mono text-gray-600">string</td>
                  <td className="p-3 text-gray-500">Yes*</td>
                  <td className="p-3 text-gray-700">Key for x-axis values (*not for pie)</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">height</td>
                  <td className="p-3 font-mono text-gray-600">number</td>
                  <td className="p-3 text-gray-500">No</td>
                  <td className="p-3 text-gray-700">Height in pixels (default: 300)</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">title</td>
                  <td className="p-3 font-mono text-gray-600">string</td>
                  <td className="p-3 text-gray-500">No</td>
                  <td className="p-3 text-gray-700">Chart title</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">showGrid</td>
                  <td className="p-3 font-mono text-gray-600">boolean</td>
                  <td className="p-3 text-gray-500">No</td>
                  <td className="p-3 text-gray-700">Show grid lines (default: true)</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">showLegend</td>
                  <td className="p-3 font-mono text-gray-600">boolean</td>
                  <td className="p-3 text-gray-500">No</td>
                  <td className="p-3 text-gray-700">Show legend (default: true)</td>
                </tr>
                <tr>
                  <td className="p-3 font-mono text-blue-600">orientation</td>
                  <td className="p-3 font-mono text-gray-600">string</td>
                  <td className="p-3 text-gray-500">No</td>
                  <td className="p-3 text-gray-700">"vertical" | "horizontal" (for tree only, default: "vertical")</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AIChartTest;

