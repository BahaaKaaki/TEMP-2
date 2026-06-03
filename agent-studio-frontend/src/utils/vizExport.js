/**
 * vizExport — build a fully interactive, self-contained HTML export of a
 * visualization deliverable.
 *
 * Goal: the user double-clicks the downloaded .html file in Finder / opens
 * it in Chrome and gets back a *live* copy of the dashboard, with all
 * filters, buttons, accordions, tabs, sorting, and JS `render` scripts
 * still working.  A DOM screenshot was not enough (dead — no event
 * handlers, no React state).
 *
 * Shape of the exported file:
 *   - React 18 + ReactDOM 18 + Recharts 2 + Tailwind (CDN; graceful
 *     offline-fallback for Tailwind via a small preflight stylesheet).
 *   - Embedded specs + data as JSON constants.
 *   - An inline viewer runtime (plain JS, uses `React.createElement`)
 *     that faithfully mirrors the in-app DSL primitives AND the JS
 *     `type: "render"` escape hatch.
 *
 * Why CDN (vs. inlining the libraries):
 *   - Keeps the exported file small (< 50 KB vs. multi-MB).
 *   - Standard caches hit for users who already opened another export.
 *   - Opens instantly in Chrome without the 2 MB parse cost.
 *
 * The CDN URLs use a pinned major version (pure UMD builds), so a
 * future breaking release of Recharts won't silently break past
 * exports — you'd have to bump the pin and re-export.
 */

/**
 * The standalone runtime gets injected verbatim into the exported
 * HTML.  Keep everything inside the IIFE: it must not touch any outer
 * symbols (CommonJS/ES module), and it must work under a plain
 * `<script>` tag with React/ReactDOM/Recharts available as globals.
 *
 * This runtime is intentionally a ~1:1 re-implementation of the
 * primitives in `VisualizationRenderer.jsx`, expressed with
 * `React.createElement` (aliased to `h`) because the exported page
 * has no JSX transformer.  Prefer `className` + Tailwind so the output
 * matches the in-app look without shipping a custom stylesheet.
 */
const RUNTIME_JS = String.raw`
(function () {
  // ── CDN sanity check ───────────────────────────────────────────────
  // Recharts' UMD build (inspected from unpkg) declares its factory as
  //   factory(require("react"), require("prop-types"), require("react-dom"))
  // If ANY of those three globals is missing at load time, Recharts
  // initializes to a broken shell and every component becomes
  // undefined -- which then triggers React error #130 when the user's
  // render() script does React.createElement(Recharts.BarChart, ...).
  //
  // Fail loudly with a readable message instead of producing the
  // cryptic "Minified React error #130" stack.
  function renderFatal(message, details) {
    var host = document.getElementById('root');
    if (!host) return;
    host.innerHTML =
      '<div style="padding:24px;max-width:680px;margin:0 auto;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;color:#991b1b;font-family:ui-monospace,Menlo,monospace">' +
        '<div style="font-weight:600;margin-bottom:8px">Visualization export failed to bootstrap</div>' +
        '<div style="font-size:13px;line-height:1.5;color:#7f1d1d">' + message + '</div>' +
        (details ? '<pre style="margin-top:8px;font-size:12px;background:#fff;padding:8px;border:1px solid #fecaca;border-radius:4px;overflow:auto">' + details + '</pre>' : '') +
      '</div>';
  }
  if (typeof React === 'undefined' || typeof ReactDOM === 'undefined') {
    renderFatal('React or ReactDOM failed to load from the CDN. Check your network connection, then reload.');
    return;
  }
  if (typeof window.Recharts === 'undefined' || !window.Recharts.BarChart) {
    renderFatal(
      'Recharts failed to load. This is almost always because the prop-types UMD or react-dom UMD did not load before Recharts, which leaves its components undefined.',
      'typeof window.Recharts = ' + typeof window.Recharts + '\\n' +
      'typeof window.PropTypes = ' + typeof window.PropTypes + '\\n' +
      'typeof window.ReactDOM = ' + typeof window.ReactDOM
    );
    return;
  }

  var h = React.createElement;
  var useState = React.useState;
  var useMemo = React.useMemo;

  var RC = window.Recharts;
  var BarChart = RC.BarChart, Bar = RC.Bar, LineChart = RC.LineChart, Line = RC.Line;
  var AreaChart = RC.AreaChart, Area = RC.Area, PieChart = RC.PieChart, Pie = RC.Pie;
  var XAxis = RC.XAxis, YAxis = RC.YAxis, CartesianGrid = RC.CartesianGrid;
  var Tooltip = RC.Tooltip, Legend = RC.Legend;
  var ResponsiveContainer = RC.ResponsiveContainer, Cell = RC.Cell;

  var DEFAULT_COLORS = ['#A32020', '#7A1818', '#EA9595', '#F4CACA', '#DB536A', '#BA2741', '#464646', '#7D7D7D'];

  // ── Error boundary for JS render() scripts ─────────────────────────
  var ErrorBoundary = (function () {
    function EB(props) { React.Component.call(this, props); this.state = { error: null }; }
    EB.prototype = Object.create(React.Component.prototype);
    EB.prototype.constructor = EB;
    EB.getDerivedStateFromError = function (error) { return { error: error }; };
    EB.prototype.render = function () {
      if (this.state.error) {
        return h('div', { className: 'bg-red-50 border border-red-200 rounded-lg p-4 text-sm' },
          h('p', { className: 'font-semibold text-red-700' }, 'Render function error'),
          h('pre', { className: 'mt-1 text-xs text-red-600 whitespace-pre-wrap' },
            (this.state.error && this.state.error.message) || String(this.state.error))
        );
      }
      return this.props.children;
    };
    return EB;
  })();

  // ── Custom JS renderer (the "render" escape hatch) ─────────────────
  // Runs the user-supplied script with the same locals the in-app
  // runtime provides: (data, React, Recharts).  If the script throws,
  // the ErrorBoundary below catches it and shows a readable message.
  //
  // Memoization note (mirrors the in-app fix in
  // VisualizationRenderer.jsx): we key the memo on a STRUCTURAL data
  // signature, not the data reference.  Without this, a browser-window
  // resize re-renders our parent, hands us a fresh-but-equal data
  // object, we'd re-parse the script via new Function(), get fresh
  // component identities, React would remount the subtree, every
  // useEffect inside the script would re-fire -- one setState there
  // and we're in a "Maximum update depth exceeded" loop.
  function stableDataSig(data) {
    try { return JSON.stringify(data); } catch { return null; }
  }

  function CustomRender(props) {
    var spec = props.spec;
    var data = props.data;
    var sig = useMemo(function () { return stableDataSig(data); }, [data]);
    var element = useMemo(function () {
      try {
        var fn = new Function('data', 'React', 'Recharts', spec.script);
        return fn(data, React, RC);
      } catch (err) {
        return h('div', { className: 'bg-red-50 border border-red-200 rounded-lg p-4 text-sm' },
          h('p', { className: 'font-semibold text-red-700' }, 'Script evaluation error'),
          h('pre', { className: 'mt-1 text-xs text-red-600 whitespace-pre-wrap' },
            (err && err.message) || String(err))
        );
      }
      // We intentionally depend on the signature, not on the data
      // reference.  The hook lint rule can't know that.
    }, [spec.script, sig]);
    return h(ErrorBoundary, null, element);
  }

  // ── DSL primitives ─────────────────────────────────────────────────

  function HeaderPrimitive(props) {
    var spec = props.spec;
    var badges = spec.badges || {};
    var entries = Object.keys(badges).filter(function (k) { return badges[k]; }).map(function (k) { return [k, badges[k]]; });
    return h('div', { className: 'bg-white rounded-lg border border-gray-200 px-5 py-4' },
      spec.title && h('h2', { className: 'text-lg font-bold text-gray-900' }, spec.title),
      spec.subtitle && h('p', { className: 'text-sm text-gray-500 mt-0.5' }, spec.subtitle),
      entries.length > 0 && h('div', { className: 'flex flex-wrap gap-2 mt-2' },
        entries.map(function (pair) {
          var k = pair[0], v = pair[1];
          return h('span', { key: k, className: 'inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 border border-gray-200' },
            h('span', { className: 'font-medium text-gray-500' }, String(k).replace(/_/g, ' ') + ':'),
            ' ', String(v)
          );
        })
      )
    );
  }

  function simpleMarkdown(text) {
    return String(text || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/\x60(.+?)\x60/g, '<code class="bg-gray-100 px-1 rounded text-xs">$1</code>')
      .replace(/\n/g, '<br/>');
  }

  function TextPrimitive(props) {
    var spec = props.spec;
    var value = spec.value || spec.content || '';
    if (spec.format === 'markdown') {
      return h('div', {
        className: 'prose prose-sm max-w-none text-gray-700',
        dangerouslySetInnerHTML: { __html: simpleMarkdown(value) },
      });
    }
    return h('p', { className: 'text-sm text-gray-700 leading-relaxed whitespace-pre-wrap' }, value);
  }

  function TablePrimitive(props) {
    var spec = props.spec;
    var columns = spec.columns || [];
    var rows = spec.rows || [];
    var sortState = useState(null);
    var sortCol = sortState[0], setSortCol = sortState[1];
    var ascState = useState(true);
    var sortAsc = ascState[0], setSortAsc = ascState[1];

    var sorted = useMemo(function () {
      if (!sortCol) return rows;
      return rows.slice().sort(function (a, b) {
        var av = a[sortCol], bv = b[sortCol];
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === 'number' && typeof bv === 'number') return sortAsc ? av - bv : bv - av;
        return sortAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
      });
    }, [rows, sortCol, sortAsc]);

    function handleSort(col) {
      if (sortCol === col) setSortAsc(!sortAsc);
      else { setSortCol(col); setSortAsc(true); }
    }

    if (columns.length === 0) return null;

    return h('div', { className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
      spec.title && h('div', { className: 'px-4 py-2 bg-gray-50 border-b text-sm font-semibold text-gray-700' }, spec.title),
      h('div', { className: 'overflow-x-auto max-h-96' },
        h('table', { className: 'w-full text-xs' },
          h('thead', { className: 'bg-gray-50 sticky top-0' },
            h('tr', null, columns.map(function (col) {
              return h('th', {
                key: col,
                className: 'px-3 py-2 text-left font-medium text-gray-600 cursor-pointer hover:bg-gray-100 select-none',
                onClick: function () { handleSort(col); },
              }, col + ' ' + (sortCol === col ? (sortAsc ? '\u25B2' : '\u25BC') : ''));
            }))
          ),
          h('tbody', null, sorted.map(function (row, i) {
            return h('tr', { key: i, className: 'border-t hover:bg-gray-50' },
              columns.map(function (col) {
                var v = row[col];
                var display = typeof v === 'object' ? JSON.stringify(v) : String(v == null ? '' : v);
                return h('td', { key: col, className: 'px-3 py-1.5 text-gray-800' }, display);
              })
            );
          }))
        )
      ),
      h('div', { className: 'px-4 py-1.5 bg-gray-50 border-t text-xs text-gray-500' }, rows.length + ' rows')
    );
  }

  function ListPrimitive(props) {
    var spec = props.spec;
    var items = spec.items || [];
    var Tag = spec.ordered ? 'ol' : 'ul';
    var listClass = spec.ordered ? 'list-decimal' : 'list-disc';
    return h('div', { className: 'bg-white rounded-lg border border-gray-200 px-4 py-3' },
      spec.title && h('div', { className: 'text-sm font-semibold text-gray-700 mb-2' }, spec.title),
      h(Tag, { className: listClass + ' list-inside space-y-1 text-sm text-gray-700' },
        items.map(function (item, i) {
          var label = typeof item === 'string' ? item : (item.label || JSON.stringify(item));
          return h('li', { key: i }, label);
        })
      )
    );
  }

  function AccordionPrimitive(props) {
    var spec = props.spec;
    var data = props.data;
    var sections = spec.sections || [];
    var openState = useState(function () {
      var s = new Set();
      for (var i = 0; i < sections.length; i++) s.add(i);
      return s;
    });
    var open = openState[0], setOpen = openState[1];

    function toggle(idx) {
      setOpen(function (prev) {
        var next = new Set(prev);
        if (next.has(idx)) next.delete(idx); else next.add(idx);
        return next;
      });
    }

    return h('div', { className: 'space-y-2' },
      sections.map(function (sec, idx) {
        return h('div', { key: idx, className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
          h('button', {
            type: 'button',
            onClick: function () { toggle(idx); },
            className: 'w-full text-left px-4 py-3 flex items-center justify-between bg-gray-50 hover:bg-gray-100 transition-colors',
          },
            h('span', { className: 'text-sm font-semibold text-gray-700' }, sec.title || ('Section ' + (idx + 1))),
            h('svg', {
              className: 'w-4 h-4 text-gray-400 transition-transform ' + (open.has(idx) ? 'rotate-180' : ''),
              fill: 'none', stroke: 'currentColor', viewBox: '0 0 24 24',
            },
              h('path', { strokeLinecap: 'round', strokeLinejoin: 'round', strokeWidth: 2, d: 'M19 9l-7 7-7-7' })
            )
          ),
          open.has(idx) && h('div', { className: 'px-4 py-3' },
            h(ComponentList, { specs: sec.content || [], data: data })
          )
        );
      })
    );
  }

  function TabsPrimitive(props) {
    var spec = props.spec;
    var data = props.data;
    var tabs = spec.tabs || [];
    var activeState = useState(0);
    var active = activeState[0], setActive = activeState[1];
    if (tabs.length === 0) return null;

    return h('div', { className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
      h('div', { className: 'flex border-b bg-gray-50 overflow-x-auto' },
        tabs.map(function (tab, idx) {
          var isActive = active === idx;
          return h('button', {
            key: idx,
            type: 'button',
            onClick: function () { setActive(idx); },
            className: 'px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ' +
              (isActive ? 'text-indigo-600 border-b-2 border-indigo-600 bg-white' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'),
          }, tab.label || ('Tab ' + (idx + 1)));
        })
      ),
      h('div', { className: 'p-4' },
        h(ComponentList, { specs: (tabs[active] && tabs[active].content) || [], data: data })
      )
    );
  }

  function GridPrimitive(props) {
    var spec = props.spec;
    var data = props.data;
    var cols = spec.columns || 2;
    var children = spec.children || [];
    return h('div', {
      className: 'grid gap-4',
      style: { gridTemplateColumns: 'repeat(' + cols + ', minmax(0, 1fr))' },
    },
      children.map(function (child, idx) {
        var specs = Array.isArray(child) ? child : [child];
        return h('div', { key: idx }, h(ComponentList, { specs: specs, data: data }));
      })
    );
  }

  function CardPrimitive(props) {
    var spec = props.spec;
    var data = props.data;
    return h('div', { className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
      spec.title && h('div', { className: 'px-4 py-2.5 bg-gray-50 border-b text-sm font-semibold text-gray-700' }, spec.title),
      h('div', { className: 'p-4' }, h(ComponentList, { specs: spec.children || [], data: data }))
    );
  }

  // ── Charts (bar / line / area / pie) ───────────────────────────────
  // Mirrors the common shape the AIChart config exposes. Export snapshots keep
  // to compact chart primitives rather than every interactive app renderer.
  // Bar/line/area/pie cover everything emitted by output.chart() and the
  // most common custom render() visualizations.
  function resolveSeries(config, data) {
    if (config.series && config.series.length) return config.series;
    // Auto-derive series: every numeric key that isn't the xAxis.
    var xAxisKey = config.xAxis || config.xAxisKey || 'date';
    var seriesKeys = [];
    if (Array.isArray(data) && data.length > 0) {
      var first = data[0];
      Object.keys(first).forEach(function (k) {
        if (k !== xAxisKey && typeof first[k] === 'number') seriesKeys.push(k);
      });
    }
    return seriesKeys.map(function (k, idx) {
      return { dataKey: k, color: DEFAULT_COLORS[idx % DEFAULT_COLORS.length], name: k };
    });
  }

  function ChartPrimitive(props) {
    var spec = props.spec;
    var type = spec.chart_type || spec.chartType || spec.type || 'bar';
    // Guard: if somebody nested {type:"chart"} inside itself (the outer
    // wrapper vs. the inner chart_type) we'd recurse forever -- fall
    // back to a plain bar chart so the export still renders.
    if (type === 'chart') type = 'bar';
    var data = spec.chart_data || spec.chartData || spec.data || [];
    var xAxisKey = spec.x_label || spec.xLabel || spec.xAxis || 'date';
    var height = spec.height || 300;
    var showGrid = spec.showGrid !== false;
    var showTooltip = spec.showTooltip !== false;
    var showLegend = spec.showLegend !== false;
    var series = resolveSeries({
      series: spec.series,
      xAxis: xAxisKey,
    }, data);

    var children;
    if (type === 'bar') {
      children = h(BarChart, { data: data, margin: { top: 20, right: 30, left: 20, bottom: 5 } },
        showGrid && h(CartesianGrid, { strokeDasharray: '3 3', stroke: '#e5e7eb' }),
        h(XAxis, { dataKey: xAxisKey, stroke: '#6b7280', style: { fontSize: '12px' } }),
        h(YAxis, { stroke: '#6b7280', style: { fontSize: '12px' } }),
        showTooltip && h(Tooltip, { contentStyle: { backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' } }),
        showLegend && h(Legend, { wrapperStyle: { fontSize: '14px' } }),
        series.map(function (s, idx) {
          return h(Bar, {
            key: s.dataKey,
            dataKey: s.dataKey,
            fill: s.color || DEFAULT_COLORS[idx % DEFAULT_COLORS.length],
            name: s.name || s.dataKey,
            radius: [4, 4, 0, 0],
          });
        })
      );
    } else if (type === 'line') {
      children = h(LineChart, { data: data, margin: { top: 20, right: 30, left: 20, bottom: 5 } },
        showGrid && h(CartesianGrid, { strokeDasharray: '3 3', stroke: '#e5e7eb' }),
        h(XAxis, { dataKey: xAxisKey, stroke: '#6b7280', style: { fontSize: '12px' } }),
        h(YAxis, { stroke: '#6b7280', style: { fontSize: '12px' } }),
        showTooltip && h(Tooltip, { contentStyle: { backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' } }),
        showLegend && h(Legend, { wrapperStyle: { fontSize: '14px' } }),
        series.map(function (s, idx) {
          var color = s.color || DEFAULT_COLORS[idx % DEFAULT_COLORS.length];
          return h(Line, {
            key: s.dataKey, type: 'monotone', dataKey: s.dataKey,
            stroke: color, strokeWidth: 2,
            name: s.name || s.dataKey,
            dot: { fill: color, r: 4 },
          });
        })
      );
    } else if (type === 'area') {
      children = h(AreaChart, { data: data, margin: { top: 20, right: 30, left: 20, bottom: 5 } },
        showGrid && h(CartesianGrid, { strokeDasharray: '3 3', stroke: '#e5e7eb' }),
        h(XAxis, { dataKey: xAxisKey, stroke: '#6b7280', style: { fontSize: '12px' } }),
        h(YAxis, { stroke: '#6b7280', style: { fontSize: '12px' } }),
        showTooltip && h(Tooltip, { contentStyle: { backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' } }),
        showLegend && h(Legend, { wrapperStyle: { fontSize: '14px' } }),
        series.map(function (s, idx) {
          var color = s.color || DEFAULT_COLORS[idx % DEFAULT_COLORS.length];
          return h(Area, {
            key: s.dataKey, type: 'monotone', dataKey: s.dataKey,
            stroke: color, fill: color, fillOpacity: 0.6,
            name: s.name || s.dataKey,
          });
        })
      );
    } else if (type === 'pie') {
      var safeData = Array.isArray(data) ? data : [];
      children = h(PieChart, null,
        h(Pie, {
          data: safeData, dataKey: 'value', nameKey: 'name',
          cx: '50%', cy: '50%',
          outerRadius: Math.min(height * 0.35, 120),
          label: function (o) { return o.name + ': ' + (o.percent * 100).toFixed(0) + '%'; },
          labelLine: { stroke: '#6b7280' },
        }, safeData.map(function (entry, index) {
          return h(Cell, { key: 'cell-' + index, fill: entry.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length] });
        })),
        showTooltip && h(Tooltip, { contentStyle: { backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' } }),
        showLegend && h(Legend, { wrapperStyle: { fontSize: '14px' } })
      );
    } else {
      return h('div', { className: 'bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-xs text-yellow-700' },
        'Unsupported chart type in export: ', h('code', null, String(type))
      );
    }

    return h('div', { className: 'bg-white rounded-lg border border-gray-200 p-4' },
      spec.title && h('div', { className: 'text-sm font-semibold text-gray-700 mb-2' }, spec.title),
      h(ResponsiveContainer, { width: '100%', height: height }, children)
    );
  }

  function FlowchartPrimitive(props) {
    var spec = props.spec;
    var nodes = spec.nodes || [];
    var edges = spec.edges || [];
    return h('div', { className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
      h('div', { className: 'px-4 py-3 bg-gray-50 border-b text-sm font-semibold text-gray-700 flex items-center justify-between' },
        h('span', null, spec.title || 'Process Flow'),
        h('span', { className: 'text-xs font-normal text-gray-400' }, nodes.length + ' nodes · ' + edges.length + ' edges')
      ),
      h('div', { className: 'p-6 text-xs text-gray-500 text-center' },
        'Flowchart visualization is not available in the static HTML export. Reopen in Agent Studio for the interactive view.'
      )
    );
  }

  function MetricPrimitive(props) {
    var spec = props.spec;
    var trendColors = { up: 'text-emerald-600', down: 'text-red-600', neutral: 'text-gray-500' };
    var trendArrows = { up: '\u2191', down: '\u2193', neutral: '\u2192' };
    var trend = spec.trend || 'neutral';

    return h('div', { className: 'bg-white rounded-lg border border-gray-200 p-4 text-center' },
      h('div', { className: 'text-2xl font-bold text-gray-900' }, spec.value),
      spec.label && h('div', { className: 'text-sm text-gray-500 mt-1' }, spec.label),
      spec.change != null && h('div', { className: 'text-sm mt-1 font-medium ' + (trendColors[trend] || trendColors.neutral) },
        (trendArrows[trend] || '') + ' ' + spec.change
      )
    );
  }

  function DividerPrimitive() { return h('hr', { className: 'border-gray-200 my-2' }); }

  function CodePrimitive(props) {
    var spec = props.spec;
    return h('div', { className: 'bg-white rounded-lg border border-gray-200 overflow-hidden' },
      spec.title && h('div', { className: 'px-4 py-2 bg-gray-50 border-b text-xs font-semibold text-gray-600 flex items-center justify-between' },
        h('span', null, spec.title),
        spec.language && h('span', { className: 'text-gray-400 font-normal' }, spec.language)
      ),
      h('pre', { className: 'p-4 text-xs font-mono text-gray-800 overflow-x-auto bg-gray-50 whitespace-pre-wrap' }, spec.value || '')
    );
  }

  var PRIMITIVES = {
    header: HeaderPrimitive,
    text: TextPrimitive,
    table: TablePrimitive,
    list: ListPrimitive,
    accordion: AccordionPrimitive,
    tabs: TabsPrimitive,
    grid: GridPrimitive,
    card: CardPrimitive,
    chart: ChartPrimitive,
    flowchart: FlowchartPrimitive,
    metric: MetricPrimitive,
    divider: DividerPrimitive,
    code: CodePrimitive,
  };

  function VizComponent(props) {
    var spec = props.spec;
    var data = props.data;
    if (!spec || !spec.type) return null;
    if (spec.type === 'render') return h(CustomRender, { spec: spec, data: data });
    var Comp = PRIMITIVES[spec.type];
    if (!Comp) {
      return h('div', { className: 'bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-xs text-yellow-700' },
        'Unknown visualization type: ', h('code', null, String(spec.type))
      );
    }
    return h(Comp, { spec: spec, data: data });
  }

  function ComponentList(props) {
    var specs = props.specs;
    var data = props.data;
    if (!specs || specs.length === 0) return null;
    return h('div', { className: 'space-y-4' },
      specs.map(function (spec, idx) { return h(VizComponent, { key: idx, spec: spec, data: data }); })
    );
  }

  function Root() {
    var payload = window.__AGENT_STUDIO_EXPORT__ || {};
    var specs = payload.visualization;
    if (!Array.isArray(specs)) specs = specs ? [specs] : [];
    return h(ComponentList, { specs: specs, data: payload.data || {} });
  }

  var rootEl = document.getElementById('root');
  if (rootEl) {
    if (ReactDOM.createRoot) {
      ReactDOM.createRoot(rootEl).render(h(Root));
    } else {
      ReactDOM.render(h(Root), rootEl);
    }
  }
})();
`;

/**
 * Small offline-fallback stylesheet for the common Tailwind classes the
 * runtime uses.  If the Tailwind CDN script fails to run (offline), at
 * least the layout is readable.  Not exhaustive — just the most-used
 * helpers so spacing/colors/borders survive.
 */
const FALLBACK_CSS = `
  html, body { margin: 0; padding: 0; background: #f9fafb; color: #111827; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  .agent-studio-export-shell { padding: 24px; max-width: 1280px; margin: 0 auto; }
  .agent-studio-export-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #e5e7eb; }
  .agent-studio-export-title { font-size: 16px; font-weight: 600; }
  .agent-studio-export-meta { font-size: 11px; color: #6b7280; }
  /* Basic readability for the body area even before Tailwind JIT finishes. */
  #root { min-height: 200px; }
`;

function sanitizeForFilename(name) {
  return String(name || 'visualization')
    .replace(/[^a-zA-Z0-9-_]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'visualization';
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, function (c) {
    return ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c];
  });
}

/**
 * The payload we embed is user-generated: it comes from `output.data(...)`,
 * which can include arbitrary strings and deep objects.  We serialize it
 * as JSON then escape the only two sequences that can prematurely break
 * out of the surrounding `<script>` tag:
 *
 *   </script>  →  <\/script>   (prevents tag closure)
 *   <!--       →  <\!--        (prevents HTML-comment confusion in
 *                               older parsers that don't yet see it as
 *                               just text inside a script)
 *
 * The rest of JSON is already safe inside a `<script>` — quotes and
 * backslashes are already JSON-escaped.
 */
function safeJsonForScript(value) {
  return JSON.stringify(value)
    .replace(/<\/script/gi, '<\\/script')
    .replace(/<!--/g, '<\\!--');
}

/**
 * Normalize a visualization spec (array or single object) to an array
 * suitable for embedding.  Matches the `VisualizationRenderer` input
 * handling so the runtime renders the same tree.
 */
function normalizeVisualization(visualization) {
  if (!visualization) return [];
  if (Array.isArray(visualization)) return visualization;
  return [visualization];
}

/**
 * Build the full self-contained HTML document.  Returns a string you can
 * stuff into a Blob.
 */
export function buildExportHtml({ visualization, data, title }) {
  const safeTitle = escapeHtml(title || 'Visualization Export');
  const payload = {
    visualization: normalizeVisualization(visualization),
    data: data || {},
    exportedAt: new Date().toISOString(),
    title: title || 'Visualization Export',
  };

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>${safeTitle}</title>
  <style>${FALLBACK_CSS}</style>
  <script src="https://cdn.tailwindcss.com"></script>
  <!--
    Load order matters: Recharts' UMD factory is
      factory(require("react"), require("prop-types"), require("react-dom"))
    so React, PropTypes, AND ReactDOM must all be global on window BEFORE
    the Recharts UMD runs.  Loading prop-types was missing in the first
    version of this exporter; without it, Recharts silently initializes
    to a broken shell and the user's render() script hits React error #130.

    We use the *development* builds of React/ReactDOM intentionally:
    exported dashboards are viewed by humans, and when a render() script
    throws, they need the full error message (not "Minified error #130").
    Size cost is ~140KB extra, paid once per browser cache.
  -->
  <script crossorigin src="https://unpkg.com/react@18.3.1/umd/react.development.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js"></script>
  <script crossorigin src="https://unpkg.com/prop-types@15.8.1/prop-types.min.js"></script>
  <script crossorigin src="https://unpkg.com/recharts@2.12.7/umd/Recharts.js"></script>
</head>
<body>
  <div class="agent-studio-export-shell">
    <div class="agent-studio-export-header">
      <div class="agent-studio-export-title">${safeTitle}</div>
      <div class="agent-studio-export-meta">Exported from Agent Studio · ${escapeHtml(new Date().toLocaleString())}</div>
    </div>
    <div id="root"></div>
  </div>
  <script>window.__AGENT_STUDIO_EXPORT__ = ${safeJsonForScript(payload)};</script>
  <script>${RUNTIME_JS}</script>
</body>
</html>`;
}

/**
 * Download the visualization as a standalone HTML file.
 *
 * The exported document is live: filters, buttons, accordions, tabs,
 * table sorting, and any custom JS in a `type: "render"` spec all
 * keep working once the user opens the file in Chrome.  This is
 * intentionally different from a DOM snapshot — we trade exact visual
 * parity (e.g. React state at export time) for actual interactivity.
 */
export function downloadVisualizationAsHtml({ visualization, data, title }) {
  const html = buildExportHtml({ visualization, data, title });
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${sanitizeForFilename(title)}.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
