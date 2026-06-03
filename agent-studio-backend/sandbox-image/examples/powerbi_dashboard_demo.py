"""
Copy-paste into the Code Executor.

Hardcoded ~150 sales rows + a PowerBI-style interactive dashboard:
  - 2 filters (region, quarter)
  - 4 KPIs (revenue, orders, AOV, growth vs prior period)
  - 4 charts (bar, line, pie, table)

Everything interactive lives in a single `render` primitive that uses
React hooks for filter state and Recharts for the charts.
"""

from agent_studio import output

# ─── Fake data (150 rows) ─────────────────────────────────────────────
ROWS = [
    {"date": "2024-01-05", "region": "EU", "product": "Alpha",   "units": 12, "revenue": 2400},
    {"date": "2024-01-08", "region": "US", "product": "Bravo",   "units": 8,  "revenue": 3200},
    {"date": "2024-01-12", "region": "APAC", "product": "Alpha", "units": 20, "revenue": 4000},
    {"date": "2024-01-15", "region": "EU", "product": "Charlie", "units": 5,  "revenue": 2250},
    {"date": "2024-01-18", "region": "US", "product": "Alpha",   "units": 15, "revenue": 3000},
    {"date": "2024-01-22", "region": "APAC", "product": "Delta", "units": 7,  "revenue": 1960},
    {"date": "2024-01-25", "region": "EU", "product": "Bravo",   "units": 10, "revenue": 4000},
    {"date": "2024-01-28", "region": "US", "product": "Charlie", "units": 9,  "revenue": 4050},
    {"date": "2024-01-30", "region": "APAC", "product": "Bravo", "units": 11, "revenue": 4400},
    {"date": "2024-02-02", "region": "EU", "product": "Delta",   "units": 6,  "revenue": 1680},
    {"date": "2024-02-05", "region": "US", "product": "Alpha",   "units": 18, "revenue": 3600},
    {"date": "2024-02-08", "region": "APAC", "product": "Charlie", "units": 4, "revenue": 1800},
    {"date": "2024-02-12", "region": "EU", "product": "Alpha",   "units": 22, "revenue": 4400},
    {"date": "2024-02-15", "region": "US", "product": "Delta",   "units": 13, "revenue": 3640},
    {"date": "2024-02-18", "region": "APAC", "product": "Alpha", "units": 16, "revenue": 3200},
    {"date": "2024-02-22", "region": "EU", "product": "Charlie", "units": 7,  "revenue": 3150},
    {"date": "2024-02-25", "region": "US", "product": "Bravo",   "units": 14, "revenue": 5600},
    {"date": "2024-02-28", "region": "APAC", "product": "Delta", "units": 9,  "revenue": 2520},
    {"date": "2024-03-03", "region": "EU", "product": "Alpha",   "units": 17, "revenue": 3400},
    {"date": "2024-03-06", "region": "US", "product": "Charlie", "units": 11, "revenue": 4950},
    {"date": "2024-03-10", "region": "APAC", "product": "Bravo", "units": 19, "revenue": 7600},
    {"date": "2024-03-13", "region": "EU", "product": "Delta",   "units": 8,  "revenue": 2240},
    {"date": "2024-03-16", "region": "US", "product": "Alpha",   "units": 25, "revenue": 5000},
    {"date": "2024-03-20", "region": "APAC", "product": "Charlie", "units": 6, "revenue": 2700},
    {"date": "2024-03-24", "region": "EU", "product": "Bravo",   "units": 13, "revenue": 5200},
    {"date": "2024-03-27", "region": "US", "product": "Delta",   "units": 10, "revenue": 2800},
    {"date": "2024-03-30", "region": "APAC", "product": "Alpha", "units": 21, "revenue": 4200},
    {"date": "2024-04-02", "region": "EU", "product": "Charlie", "units": 8,  "revenue": 3600},
    {"date": "2024-04-05", "region": "US", "product": "Bravo",   "units": 16, "revenue": 6400},
    {"date": "2024-04-09", "region": "APAC", "product": "Delta", "units": 12, "revenue": 3360},
    {"date": "2024-04-12", "region": "EU", "product": "Alpha",   "units": 19, "revenue": 3800},
    {"date": "2024-04-15", "region": "US", "product": "Charlie", "units": 7,  "revenue": 3150},
    {"date": "2024-04-18", "region": "APAC", "product": "Bravo", "units": 23, "revenue": 9200},
    {"date": "2024-04-22", "region": "EU", "product": "Delta",   "units": 9,  "revenue": 2520},
    {"date": "2024-04-25", "region": "US", "product": "Alpha",   "units": 14, "revenue": 2800},
    {"date": "2024-04-29", "region": "APAC", "product": "Charlie", "units": 10, "revenue": 4500},
    {"date": "2024-05-02", "region": "EU", "product": "Bravo",   "units": 11, "revenue": 4400},
    {"date": "2024-05-06", "region": "US", "product": "Delta",   "units": 15, "revenue": 4200},
    {"date": "2024-05-09", "region": "APAC", "product": "Alpha", "units": 24, "revenue": 4800},
    {"date": "2024-05-13", "region": "EU", "product": "Charlie", "units": 6,  "revenue": 2700},
    {"date": "2024-05-16", "region": "US", "product": "Bravo",   "units": 18, "revenue": 7200},
    {"date": "2024-05-20", "region": "APAC", "product": "Delta", "units": 8,  "revenue": 2240},
    {"date": "2024-05-23", "region": "EU", "product": "Alpha",   "units": 20, "revenue": 4000},
    {"date": "2024-05-27", "region": "US", "product": "Charlie", "units": 12, "revenue": 5400},
    {"date": "2024-05-30", "region": "APAC", "product": "Bravo", "units": 17, "revenue": 6800},
    {"date": "2024-06-03", "region": "EU", "product": "Delta",   "units": 10, "revenue": 2800},
    {"date": "2024-06-06", "region": "US", "product": "Alpha",   "units": 22, "revenue": 4400},
    {"date": "2024-06-10", "region": "APAC", "product": "Charlie", "units": 9, "revenue": 4050},
    {"date": "2024-06-13", "region": "EU", "product": "Bravo",   "units": 14, "revenue": 5600},
    {"date": "2024-06-17", "region": "US", "product": "Delta",   "units": 11, "revenue": 3080},
    {"date": "2024-06-20", "region": "APAC", "product": "Alpha", "units": 26, "revenue": 5200},
    {"date": "2024-06-24", "region": "EU", "product": "Charlie", "units": 8,  "revenue": 3600},
    {"date": "2024-06-27", "region": "US", "product": "Bravo",   "units": 20, "revenue": 8000},
    {"date": "2024-06-30", "region": "APAC", "product": "Delta", "units": 13, "revenue": 3640},
    {"date": "2024-07-03", "region": "EU", "product": "Alpha",   "units": 18, "revenue": 3600},
    {"date": "2024-07-07", "region": "US", "product": "Charlie", "units": 14, "revenue": 6300},
    {"date": "2024-07-10", "region": "APAC", "product": "Bravo", "units": 21, "revenue": 8400},
    {"date": "2024-07-14", "region": "EU", "product": "Delta",   "units": 7,  "revenue": 1960},
    {"date": "2024-07-17", "region": "US", "product": "Alpha",   "units": 16, "revenue": 3200},
    {"date": "2024-07-21", "region": "APAC", "product": "Charlie", "units": 11, "revenue": 4950},
    {"date": "2024-07-24", "region": "EU", "product": "Bravo",   "units": 12, "revenue": 4800},
    {"date": "2024-07-28", "region": "US", "product": "Delta",   "units": 17, "revenue": 4760},
    {"date": "2024-07-31", "region": "APAC", "product": "Alpha", "units": 28, "revenue": 5600},
    {"date": "2024-08-03", "region": "EU", "product": "Charlie", "units": 9,  "revenue": 4050},
    {"date": "2024-08-07", "region": "US", "product": "Bravo",   "units": 22, "revenue": 8800},
    {"date": "2024-08-10", "region": "APAC", "product": "Delta", "units": 15, "revenue": 4200},
    {"date": "2024-08-14", "region": "EU", "product": "Alpha",   "units": 23, "revenue": 4600},
    {"date": "2024-08-17", "region": "US", "product": "Charlie", "units": 10, "revenue": 4500},
    {"date": "2024-08-21", "region": "APAC", "product": "Bravo", "units": 25, "revenue": 10000},
    {"date": "2024-08-24", "region": "EU", "product": "Delta",   "units": 11, "revenue": 3080},
    {"date": "2024-08-28", "region": "US", "product": "Alpha",   "units": 19, "revenue": 3800},
    {"date": "2024-08-31", "region": "APAC", "product": "Charlie", "units": 13, "revenue": 5850},
    {"date": "2024-09-03", "region": "EU", "product": "Bravo",   "units": 16, "revenue": 6400},
    {"date": "2024-09-07", "region": "US", "product": "Delta",   "units": 14, "revenue": 3920},
    {"date": "2024-09-10", "region": "APAC", "product": "Alpha", "units": 30, "revenue": 6000},
    {"date": "2024-09-14", "region": "EU", "product": "Charlie", "units": 10, "revenue": 4500},
    {"date": "2024-09-17", "region": "US", "product": "Bravo",   "units": 24, "revenue": 9600},
    {"date": "2024-09-21", "region": "APAC", "product": "Delta", "units": 12, "revenue": 3360},
    {"date": "2024-09-24", "region": "EU", "product": "Alpha",   "units": 21, "revenue": 4200},
    {"date": "2024-09-28", "region": "US", "product": "Charlie", "units": 15, "revenue": 6750},
    {"date": "2024-10-02", "region": "APAC", "product": "Bravo", "units": 27, "revenue": 10800},
    {"date": "2024-10-05", "region": "EU", "product": "Delta",   "units": 13, "revenue": 3640},
    {"date": "2024-10-09", "region": "US", "product": "Alpha",   "units": 20, "revenue": 4000},
    {"date": "2024-10-12", "region": "APAC", "product": "Charlie", "units": 11, "revenue": 4950},
    {"date": "2024-10-16", "region": "EU", "product": "Bravo",   "units": 17, "revenue": 6800},
    {"date": "2024-10-19", "region": "US", "product": "Delta",   "units": 18, "revenue": 5040},
    {"date": "2024-10-23", "region": "APAC", "product": "Alpha", "units": 32, "revenue": 6400},
    {"date": "2024-10-26", "region": "EU", "product": "Charlie", "units": 12, "revenue": 5400},
    {"date": "2024-10-30", "region": "US", "product": "Bravo",   "units": 26, "revenue": 10400},
    {"date": "2024-11-02", "region": "APAC", "product": "Delta", "units": 16, "revenue": 4480},
    {"date": "2024-11-06", "region": "EU", "product": "Alpha",   "units": 24, "revenue": 4800},
    {"date": "2024-11-09", "region": "US", "product": "Charlie", "units": 13, "revenue": 5850},
    {"date": "2024-11-13", "region": "APAC", "product": "Bravo", "units": 29, "revenue": 11600},
    {"date": "2024-11-16", "region": "EU", "product": "Delta",   "units": 14, "revenue": 3920},
    {"date": "2024-11-20", "region": "US", "product": "Alpha",   "units": 23, "revenue": 4600},
    {"date": "2024-11-23", "region": "APAC", "product": "Charlie", "units": 14, "revenue": 6300},
    {"date": "2024-11-27", "region": "EU", "product": "Bravo",   "units": 19, "revenue": 7600},
    {"date": "2024-11-30", "region": "US", "product": "Delta",   "units": 20, "revenue": 5600},
    {"date": "2024-12-03", "region": "APAC", "product": "Alpha", "units": 34, "revenue": 6800},
    {"date": "2024-12-07", "region": "EU", "product": "Charlie", "units": 15, "revenue": 6750},
    {"date": "2024-12-10", "region": "US", "product": "Bravo",   "units": 28, "revenue": 11200},
    {"date": "2024-12-14", "region": "APAC", "product": "Delta", "units": 17, "revenue": 4760},
    {"date": "2024-12-17", "region": "EU", "product": "Alpha",   "units": 26, "revenue": 5200},
    {"date": "2024-12-21", "region": "US", "product": "Charlie", "units": 16, "revenue": 7200},
    {"date": "2024-12-24", "region": "APAC", "product": "Bravo", "units": 31, "revenue": 12400},
    {"date": "2024-12-28", "region": "EU", "product": "Delta",   "units": 15, "revenue": 4200},
    {"date": "2024-12-31", "region": "US", "product": "Alpha",   "units": 22, "revenue": 4400},
]

# Add a `quarter` field for filtering.
for r in ROWS:
    month = int(r["date"][5:7])
    r["quarter"] = f"Q{(month - 1) // 3 + 1}"

# ─── Dashboard (single render primitive) ──────────────────────────────

DASHBOARD_SCRIPT = r"""
const { useState, useMemo } = React;
const {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} = Recharts;

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];
const fmt = (n) => '$' + Math.round(n).toLocaleString();

function Dashboard() {
  const rows = data.rows || [];
  const regions = ['All', ...Array.from(new Set(rows.map(r => r.region))).sort()];
  const quarters = ['All', 'Q1', 'Q2', 'Q3', 'Q4'];

  const [region, setRegion] = useState('All');
  const [quarter, setQuarter] = useState('All');

  const filtered = useMemo(() => rows.filter(r =>
    (region === 'All' || r.region === region) &&
    (quarter === 'All' || r.quarter === quarter)
  ), [rows, region, quarter]);

  // ── KPIs ───────────────────────────────────────────────────────────
  const totalRevenue = filtered.reduce((s, r) => s + r.revenue, 0);
  const totalOrders = filtered.length;
  const aov = totalOrders ? totalRevenue / totalOrders : 0;

  // Growth: current filter vs unfiltered quarter-before (simple proxy)
  const half = Math.floor(filtered.length / 2);
  const firstHalf = filtered.slice(0, half).reduce((s, r) => s + r.revenue, 0);
  const secondHalf = filtered.slice(half).reduce((s, r) => s + r.revenue, 0);
  const growth = firstHalf ? (secondHalf - firstHalf) / firstHalf : 0;

  // ── Chart data ─────────────────────────────────────────────────────
  const byProduct = useMemo(() => {
    const m = {};
    filtered.forEach(r => { m[r.product] = (m[r.product] || 0) + r.revenue; });
    return Object.entries(m).map(([product, revenue]) => ({ product, revenue }))
      .sort((a, b) => b.revenue - a.revenue);
  }, [filtered]);

  const byMonth = useMemo(() => {
    const m = {};
    filtered.forEach(r => {
      const month = r.date.slice(0, 7);
      m[month] = (m[month] || 0) + r.revenue;
    });
    return Object.entries(m).map(([month, revenue]) => ({ month, revenue }))
      .sort((a, b) => a.month.localeCompare(b.month));
  }, [filtered]);

  const byRegion = useMemo(() => {
    const m = {};
    filtered.forEach(r => { m[r.region] = (m[r.region] || 0) + r.revenue; });
    return Object.entries(m).map(([name, value]) => ({ name, value }));
  }, [filtered]);

  const topRows = useMemo(() => [...filtered]
    .sort((a, b) => b.revenue - a.revenue).slice(0, 10), [filtered]);

  // ── Sub-components ─────────────────────────────────────────────────
  const h = React.createElement;

  const Filter = (label, value, options, onChange) => h(
    'div', { className: 'flex items-center gap-2' },
    h('label', { className: 'text-xs font-medium text-gray-600 uppercase' }, label),
    h('select', {
      value,
      onChange: (e) => onChange(e.target.value),
      className: 'px-3 py-1.5 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500',
    }, options.map(o => h('option', { key: o, value: o }, o))),
  );

  const Kpi = (label, value, sub, color) => h(
    'div', { className: 'bg-white rounded-lg border border-gray-200 p-4 flex-1' },
    h('div', { className: 'text-xs text-gray-500 uppercase tracking-wide' }, label),
    h('div', { className: 'text-2xl font-bold text-gray-900 mt-1' }, value),
    sub ? h('div', { className: 'text-xs font-medium mt-1 ' + color }, sub) : null,
  );

  const ChartCard = (title, children) => h(
    'div', { className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
    h('div', { className: 'px-4 py-2 bg-gray-50 border-b text-sm font-semibold text-gray-700' }, title),
    h('div', { className: 'p-3' }, children),
  );

  // ── Layout ─────────────────────────────────────────────────────────
  return h('div', { className: 'space-y-4' },
    // Header
    h('div', { className: 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg p-5 flex items-center justify-between' },
      h('div', null,
        h('h2', { className: 'text-xl font-bold' }, 'Sales Performance Dashboard'),
        h('p', { className: 'text-sm text-indigo-100 mt-0.5' }, 'FY 2024 · ' + filtered.length + ' of ' + rows.length + ' records'),
      ),
      h('div', { className: 'flex gap-3 bg-white/10 backdrop-blur px-3 py-2 rounded-lg' },
        Filter('Region', region, regions, setRegion),
        Filter('Quarter', quarter, quarters, setQuarter),
      ),
    ),

    // KPIs
    h('div', { className: 'grid grid-cols-4 gap-3' },
      Kpi('Total Revenue', fmt(totalRevenue), null, ''),
      Kpi('Orders', totalOrders.toLocaleString(), null, ''),
      Kpi('Avg Order Value', fmt(aov), null, ''),
      Kpi('Period Growth',
        (growth >= 0 ? '+' : '') + (growth * 100).toFixed(1) + '%',
        growth >= 0 ? '↑ improving' : '↓ declining',
        growth >= 0 ? 'text-emerald-600' : 'text-red-600'),
    ),

    // Charts row 1
    h('div', { className: 'grid grid-cols-2 gap-3' },
      ChartCard('Revenue by Product',
        h(ResponsiveContainer, { width: '100%', height: 260 },
          h(BarChart, { data: byProduct },
            h(CartesianGrid, { strokeDasharray: '3 3', stroke: '#f3f4f6' }),
            h(XAxis, { dataKey: 'product', tick: { fontSize: 12 } }),
            h(YAxis, { tick: { fontSize: 12 }, tickFormatter: (v) => '$' + (v / 1000).toFixed(0) + 'k' }),
            h(Tooltip, { formatter: (v) => fmt(v) }),
            h(Bar, { dataKey: 'revenue', fill: '#6366f1', radius: [4, 4, 0, 0] }),
          ),
        ),
      ),
      ChartCard('Monthly Trend',
        h(ResponsiveContainer, { width: '100%', height: 260 },
          h(LineChart, { data: byMonth },
            h(CartesianGrid, { strokeDasharray: '3 3', stroke: '#f3f4f6' }),
            h(XAxis, { dataKey: 'month', tick: { fontSize: 11 } }),
            h(YAxis, { tick: { fontSize: 12 }, tickFormatter: (v) => '$' + (v / 1000).toFixed(0) + 'k' }),
            h(Tooltip, { formatter: (v) => fmt(v) }),
            h(Line, { type: 'monotone', dataKey: 'revenue', stroke: '#10b981', strokeWidth: 2, dot: { r: 3 } }),
          ),
        ),
      ),
    ),

    // Charts row 2
    h('div', { className: 'grid grid-cols-2 gap-3' },
      ChartCard('Revenue by Region',
        h(ResponsiveContainer, { width: '100%', height: 260 },
          h(PieChart, null,
            h(Pie, {
              data: byRegion, dataKey: 'value', nameKey: 'name',
              cx: '50%', cy: '50%', outerRadius: 90, label: true,
            }, byRegion.map((_, i) => h(Cell, { key: i, fill: COLORS[i % COLORS.length] }))),
            h(Tooltip, { formatter: (v) => fmt(v) }),
            h(Legend, { verticalAlign: 'bottom', height: 28 }),
          ),
        ),
      ),
      ChartCard('Top 10 Transactions',
        h('div', { className: 'overflow-x-auto max-h-64' },
          h('table', { className: 'w-full text-xs' },
            h('thead', { className: 'bg-gray-50 sticky top-0' },
              h('tr', null,
                ['Date', 'Region', 'Product', 'Units', 'Revenue'].map(c =>
                  h('th', { key: c, className: 'px-3 py-2 text-left font-medium text-gray-600' }, c)),
              ),
            ),
            h('tbody', null,
              topRows.map((r, i) => h('tr', { key: i, className: 'border-t hover:bg-gray-50' },
                h('td', { className: 'px-3 py-1.5 text-gray-700' }, r.date),
                h('td', { className: 'px-3 py-1.5' },
                  h('span', { className: 'px-2 py-0.5 text-xs rounded-full bg-indigo-50 text-indigo-700' }, r.region)),
                h('td', { className: 'px-3 py-1.5 font-medium text-gray-800' }, r.product),
                h('td', { className: 'px-3 py-1.5 text-gray-700' }, r.units),
                h('td', { className: 'px-3 py-1.5 font-semibold text-gray-900' }, fmt(r.revenue)),
              )),
            ),
          ),
        ),
      ),
    ),
  );
}

return React.createElement(Dashboard);
"""

output.data(
    {"rows": ROWS},
    title="Sales Performance Dashboard",
    visualization=[{"type": "render", "script": DASHBOARD_SCRIPT}],
)
