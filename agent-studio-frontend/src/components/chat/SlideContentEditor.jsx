/**
 * SlideContentEditor Component
 * 
 * Structured form editor for directly editing slide content by hand.
 * Renders editable fields for headline, subtitle, and layout-specific content.
 * Changes update the slide in real-time so the preview refreshes instantly.
 */

import { useState, useCallback } from 'react';

const LAYOUT_OPTIONS = [
  { value: 'title_content', label: 'Title + Content' },
  { value: 'two_column', label: 'Two Column' },
  { value: 'three_column', label: 'Three Column' },
  { value: 'spotlight', label: 'Spotlight' },
  { value: 'approach_3step', label: 'Approach (3-step)' },
  { value: 'approach_4step', label: 'Approach (4-step)' },
  { value: 'approach_5step', label: 'Approach (5-step)' },
  { value: 'horizontal_approach', label: 'Horizontal Approach' },
  { value: 'metrics_dashboard', label: 'Metrics Dashboard' },
  { value: 'timeline', label: 'Timeline' },
  { value: 'comparison_table', label: 'Comparison Table' },
  { value: 'call_to_action', label: 'Call to Action' },
  { value: 'kpi_hero', label: 'KPI Hero' },
  { value: 'cv_team_summary', label: 'CV Team Summary' },
  { value: 'cv_individual', label: 'CV Individual' },
];

// Reusable field styles
const inputCls = "w-full px-2 py-1.5 text-xs bg-background border border-border rounded focus:outline-none focus:border-[#A32020] text-foreground";
const labelCls = "text-[10px] font-semibold text-muted-foreground uppercase tracking-wider";
const sectionCls = "space-y-2 p-2.5 bg-gray-50/50 rounded-lg border border-border/50";

// ---------------------------------------------------------------------------
// HELPER: Editable string list (bullets, substeps, items, etc.)
// ---------------------------------------------------------------------------
function EditableList({ items, onChange, placeholder = "Item text", label = "Items" }) {
  const update = (idx, val) => {
    const next = [...items];
    next[idx] = val;
    onChange(next);
  };
  const remove = (idx) => onChange(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, '']);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className={labelCls}>{label}</span>
        <button onClick={add} className="text-[10px] text-[#A32020] hover:underline">+ Add</button>
      </div>
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground w-4 text-right">{i + 1}.</span>
          <input
            value={item}
            onChange={(e) => update(i, e.target.value)}
            className={inputCls + " flex-1"}
            placeholder={placeholder}
          />
          <button onClick={() => remove(i)} className="text-gray-400 hover:text-red-500 text-xs px-1">&times;</button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CONTENT EDITORS PER LAYOUT TYPE
// ---------------------------------------------------------------------------

function BulletListEditor({ content, onChange }) {
  const items = content?.items || [];
  const updateItem = (idx, field, val) => {
    const next = [...items];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, items: next });
  };
  const removeItem = (idx) => onChange({ ...content, items: items.filter((_, i) => i !== idx) });
  const addItem = () => onChange({ ...content, items: [...items, { text: '', bold_prefix: null, level: 0 }] });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className={labelCls}>Bullet Items</span>
        <button onClick={addItem} className="text-[10px] text-[#A32020] hover:underline">+ Add bullet</button>
      </div>
      {items.map((item, i) => (
        <div key={i} className={sectionCls}>
          <div className="flex items-center gap-1">
            <input
              value={item.bold_prefix || ''}
              onChange={(e) => updateItem(i, 'bold_prefix', e.target.value || null)}
              className={inputCls + " w-24"}
              placeholder="Bold prefix"
            />
            <input
              value={item.text || ''}
              onChange={(e) => updateItem(i, 'text', e.target.value)}
              className={inputCls + " flex-1"}
              placeholder="Bullet text"
            />
            <select
              value={item.level || 0}
              onChange={(e) => updateItem(i, 'level', parseInt(e.target.value))}
              className="text-[10px] px-1 py-1 border border-border rounded bg-background w-14"
            >
              <option value={0}>L0</option>
              <option value={1}>L1</option>
              <option value={2}>L2</option>
            </select>
            <button onClick={() => removeItem(i)} className="text-gray-400 hover:text-red-500 text-xs px-1">&times;</button>
          </div>
        </div>
      ))}
    </div>
  );
}

function CardEditor({ card, onChange, index, onRemove, canRemove }) {
  const updateField = (field, val) => onChange({ ...card, [field]: val });
  const items = card.items || [];

  return (
    <div className={sectionCls}>
      <div className="flex items-center justify-between">
        <span className={labelCls}>Card {index + 1}</span>
        {canRemove && <button onClick={onRemove} className="text-[10px] text-red-500 hover:underline">Remove</button>}
      </div>
      <div className="grid grid-cols-2 gap-1">
        <div>
          <span className={labelCls}>Tag</span>
          <input value={card.tag || ''} onChange={(e) => updateField('tag', e.target.value)} className={inputCls} placeholder="e.g., Lever 1" />
        </div>
        <div>
          <span className={labelCls}>Title</span>
          <input value={card.title || ''} onChange={(e) => updateField('title', e.target.value)} className={inputCls} placeholder="Card title" />
        </div>
      </div>
      <div>
        <span className={labelCls}>Description</span>
        <input value={card.description || ''} onChange={(e) => updateField('description', e.target.value)} className={inputCls} placeholder="Brief description" />
      </div>
      <EditableList items={items} onChange={(v) => updateField('items', v)} placeholder="Action item" label="Items" />
      <div>
        <span className={labelCls}>Footer</span>
        <input value={card.footer || ''} onChange={(e) => updateField('footer', e.target.value)} className={inputCls} placeholder="Footer text" />
      </div>
    </div>
  );
}

function CardGridEditor({ content, onChange }) {
  const cards = content?.cards || [];
  const updateCard = (idx, card) => {
    const next = [...cards];
    next[idx] = card;
    onChange({ ...content, cards: next });
  };
  const removeCard = (idx) => onChange({ ...content, cards: cards.filter((_, i) => i !== idx) });
  const addCard = () => onChange({ ...content, cards: [...cards, { tag: '', title: 'New Card', description: '', items: [], footer: '' }] });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className={labelCls}>Cards</span>
        <button onClick={addCard} className="text-[10px] text-[#A32020] hover:underline">+ Add card</button>
      </div>
      {cards.map((card, i) => (
        <CardEditor key={i} card={card} onChange={(c) => updateCard(i, c)} index={i} onRemove={() => removeCard(i)} canRemove={true} />
      ))}
    </div>
  );
}

function ApproachEditor({ content, onChange }) {
  const phases = content?.phases || [];
  const crosscut = content?.crosscut;

  const updatePhase = (idx, field, val) => {
    const next = [...phases];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, phases: next });
  };
  const removePhase = (idx) => onChange({ ...content, phases: phases.filter((_, i) => i !== idx) });
  const addPhase = () => onChange({ ...content, phases: [...phases, { number: phases.length + 1, title: '', duration: '', substeps: [] }] });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className={labelCls}>Phases</span>
        <button onClick={addPhase} className="text-[10px] text-[#A32020] hover:underline">+ Add phase</button>
      </div>
      {phases.map((phase, i) => (
        <div key={i} className={sectionCls}>
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-[#A32020] text-white text-[10px] font-bold flex items-center justify-center flex-shrink-0">
              {phase.number || i + 1}
            </span>
            <input value={phase.title || ''} onChange={(e) => updatePhase(i, 'title', e.target.value)} className={inputCls + " flex-1"} placeholder="Phase title" />
            <button onClick={() => removePhase(i)} className="text-gray-400 hover:text-red-500 text-xs px-1">&times;</button>
          </div>
          <div>
            <span className={labelCls}>Duration</span>
            <input value={phase.duration || ''} onChange={(e) => updatePhase(i, 'duration', e.target.value)} className={inputCls} placeholder="e.g., Weeks 1-4" />
          </div>
          <EditableList
            items={phase.substeps || []}
            onChange={(v) => updatePhase(i, 'substeps', v)}
            placeholder="Substep (max 5 words)"
            label="Substeps"
          />
        </div>
      ))}
      {crosscut && (
        <div className={sectionCls}>
          <span className={labelCls}>Crosscut Bar</span>
          <input
            value={crosscut.title || ''}
            onChange={(e) => onChange({ ...content, crosscut: { ...crosscut, title: e.target.value } })}
            className={inputCls}
            placeholder="Crosscut title"
          />
          <EditableList
            items={crosscut.items || []}
            onChange={(v) => onChange({ ...content, crosscut: { ...crosscut, items: v } })}
            placeholder="Activity"
            label="Activities"
          />
        </div>
      )}
    </div>
  );
}

function MetricsDashboardEditor({ content, onChange }) {
  const metrics = content?.metrics || [];
  const insights = content?.insights || [];

  const updateMetric = (idx, field, val) => {
    const next = [...metrics];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, metrics: next });
  };
  const addMetric = () => onChange({ ...content, metrics: [...metrics, { value: '', label: '', change: '', status: 'neutral' }] });
  const removeMetric = (idx) => onChange({ ...content, metrics: metrics.filter((_, i) => i !== idx) });

  const updateInsight = (idx, field, val) => {
    const next = [...insights];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, insights: next });
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className={labelCls}>Metric Boxes</span>
        <button onClick={addMetric} className="text-[10px] text-[#A32020] hover:underline">+ Add metric</button>
      </div>
      {metrics.map((m, i) => (
        <div key={i} className={sectionCls}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-foreground">Metric {i + 1}</span>
            <button onClick={() => removeMetric(i)} className="text-[10px] text-red-500 hover:underline">Remove</button>
          </div>
          <div className="grid grid-cols-2 gap-1">
            <div>
              <span className={labelCls}>Value</span>
              <input value={m.value || ''} onChange={(e) => updateMetric(i, 'value', e.target.value)} className={inputCls} placeholder="$18.4M" />
            </div>
            <div>
              <span className={labelCls}>Label</span>
              <input value={m.label || ''} onChange={(e) => updateMetric(i, 'label', e.target.value)} className={inputCls} placeholder="Cost Savings" />
            </div>
            <div>
              <span className={labelCls}>Change</span>
              <input value={m.change || ''} onChange={(e) => updateMetric(i, 'change', e.target.value)} className={inputCls} placeholder="+24%" />
            </div>
            <div>
              <span className={labelCls}>Status</span>
              <select value={m.status || 'neutral'} onChange={(e) => updateMetric(i, 'status', e.target.value)} className={inputCls}>
                <option value="up">Up</option>
                <option value="down">Down</option>
                <option value="neutral">Neutral</option>
              </select>
            </div>
          </div>
        </div>
      ))}
      <span className={labelCls}>Insight Columns</span>
      {insights.map((ins, i) => (
        <div key={i} className={sectionCls}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-foreground">Column {i + 1}</span>
            <button onClick={() => onChange({ ...content, insights: insights.filter((_, j) => j !== i) })} className="text-[10px] text-red-500 hover:underline">Remove</button>
          </div>
          <input value={ins.title || ''} onChange={(e) => updateInsight(i, 'title', e.target.value)} className={inputCls} placeholder="Column title" />
          <EditableList items={ins.items || []} onChange={(v) => updateInsight(i, 'items', v)} placeholder="Insight point" label="Points" />
        </div>
      ))}
    </div>
  );
}

function TimelineEditor({ content, onChange }) {
  const phases = content?.phases || [];
  const updatePhase = (idx, field, val) => {
    const next = [...phases];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, phases: next });
  };
  const removePhase = (idx) => onChange({ ...content, phases: phases.filter((_, i) => i !== idx) });
  const addPhase = () => onChange({ ...content, phases: [...phases, { phase_label: '', date_range: '', title: '', items: [], status: 'future' }] });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className={labelCls}>Timeline Phases</span>
        <button onClick={addPhase} className="text-[10px] text-[#A32020] hover:underline">+ Add phase</button>
      </div>
      {phases.map((p, i) => (
        <div key={i} className={sectionCls}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-medium text-foreground">Phase {i + 1}</span>
            <button onClick={() => removePhase(i)} className="text-[10px] text-red-500 hover:underline">Remove</button>
          </div>
          <div className="grid grid-cols-2 gap-1">
            <div>
              <span className={labelCls}>Phase Label</span>
              <input value={p.phase_label || ''} onChange={(e) => updatePhase(i, 'phase_label', e.target.value)} className={inputCls} placeholder="Q1 2025" />
            </div>
            <div>
              <span className={labelCls}>Date Range</span>
              <input value={p.date_range || ''} onChange={(e) => updatePhase(i, 'date_range', e.target.value)} className={inputCls} placeholder="Jan-Mar" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-1">
            <div>
              <span className={labelCls}>Title</span>
              <input value={p.title || ''} onChange={(e) => updatePhase(i, 'title', e.target.value)} className={inputCls} placeholder="Phase title" />
            </div>
            <div>
              <span className={labelCls}>Status</span>
              <select value={p.status || 'current'} onChange={(e) => updatePhase(i, 'status', e.target.value)} className={inputCls}>
                <option value="past">Past</option>
                <option value="current">Current</option>
                <option value="future">Future</option>
              </select>
            </div>
          </div>
          <EditableList items={p.items || []} onChange={(v) => updatePhase(i, 'items', v)} placeholder="Activity" label="Items" />
        </div>
      ))}
    </div>
  );
}

function ComparisonTableEditor({ content, onChange }) {
  const headers = content?.headers || [];
  const rows = content?.rows || [];

  const updateHeader = (idx, val) => {
    const next = [...headers];
    next[idx] = val;
    onChange({ ...content, headers: next });
  };
  const updateCell = (ri, ci, val) => {
    const next = rows.map(r => [...r]);
    next[ri][ci] = val;
    onChange({ ...content, rows: next });
  };
  const removeColumn = (ci) => {
    const nextHeaders = headers.filter((_, i) => i !== ci);
    const nextRows = rows.map(r => r.filter((_, i) => i !== ci));
    onChange({ ...content, headers: nextHeaders, rows: nextRows });
  };
  const removeRow = (ri) => onChange({ ...content, rows: rows.filter((_, i) => i !== ri) });
  const addRow = () => onChange({ ...content, rows: [...rows, headers.map(() => '')] });

  return (
    <div className="space-y-2">
      <span className={labelCls}>Headers</span>
      <div className="flex flex-wrap gap-1">
        {headers.map((h, i) => (
          <div key={i} className="flex items-center gap-0.5 flex-1 min-w-[80px]">
            <input value={h} onChange={(e) => updateHeader(i, e.target.value)} className={inputCls + " flex-1"} />
            <button onClick={() => removeColumn(i)} className="text-gray-400 hover:text-red-500 text-xs px-0.5">&times;</button>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className={labelCls}>Rows</span>
        <button onClick={addRow} className="text-[10px] text-[#A32020] hover:underline">+ Add row</button>
      </div>
      {rows.map((row, ri) => (
        <div key={ri} className="flex gap-1">
          {row.map((cell, ci) => (
            <input key={ci} value={cell} onChange={(e) => updateCell(ri, ci, e.target.value)} className={inputCls + " flex-1 min-w-[60px]"} />
          ))}
          <button onClick={() => removeRow(ri)} className="text-gray-400 hover:text-red-500 text-xs px-0.5">&times;</button>
        </div>
      ))}
      <div className="grid grid-cols-2 gap-1">
        <div>
          <span className={labelCls}>Recommended Col (0-based)</span>
          <input type="number" value={content?.recommended_column ?? ''} onChange={(e) => onChange({ ...content, recommended_column: e.target.value ? parseInt(e.target.value) : null })} className={inputCls} />
        </div>
        <div>
          <span className={labelCls}>Recommendation</span>
          <input value={content?.recommendation || ''} onChange={(e) => onChange({ ...content, recommendation: e.target.value })} className={inputCls} placeholder="Summary" />
        </div>
      </div>
    </div>
  );
}

function CallToActionEditor({ content, onChange }) {
  const actions = content?.actions || [];
  const updateAction = (idx, field, val) => {
    const next = [...actions];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, actions: next });
  };
  const addAction = () => onChange({ ...content, actions: [...actions, { number: actions.length + 1, title: '', description: '', owner: '', due_date: '' }] });
  const removeAction = (idx) => onChange({ ...content, actions: actions.filter((_, i) => i !== idx) });

  return (
    <div className="space-y-2">
      <div>
        <span className={labelCls}>Banner Headline</span>
        <input value={content?.banner_headline || ''} onChange={(e) => onChange({ ...content, banner_headline: e.target.value })} className={inputCls} placeholder="Key message" />
      </div>
      <div>
        <span className={labelCls}>Banner Subtext</span>
        <input value={content?.banner_subtext || ''} onChange={(e) => onChange({ ...content, banner_subtext: e.target.value })} className={inputCls} placeholder="Supporting text" />
      </div>
      <div className="flex items-center justify-between">
        <span className={labelCls}>Action Cards</span>
        <button onClick={addAction} className="text-[10px] text-[#A32020] hover:underline">+ Add action</button>
      </div>
      {actions.map((a, i) => (
        <div key={i} className={sectionCls}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-foreground">Action {a.number || i + 1}</span>
            <button onClick={() => removeAction(i)} className="text-[10px] text-red-500 hover:underline">Remove</button>
          </div>
          <input value={a.title || ''} onChange={(e) => updateAction(i, 'title', e.target.value)} className={inputCls} placeholder="Action title" />
          <textarea value={a.description || ''} onChange={(e) => updateAction(i, 'description', e.target.value)} className={inputCls + " resize-none"} rows={2} placeholder="Description" />
          <div className="grid grid-cols-2 gap-1">
            <div>
              <span className={labelCls}>Owner</span>
              <input value={a.owner || ''} onChange={(e) => updateAction(i, 'owner', e.target.value)} className={inputCls} placeholder="CFO" />
            </div>
            <div>
              <span className={labelCls}>Due Date</span>
              <input value={a.due_date || ''} onChange={(e) => updateAction(i, 'due_date', e.target.value)} className={inputCls} placeholder="Dec 15" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function KPIHeroEditor({ content, onChange }) {
  const cards = content?.cards || [];
  const updateCard = (idx, card) => {
    const next = [...cards];
    next[idx] = card;
    onChange({ ...content, cards: next });
  };
  const removeCard = (idx) => onChange({ ...content, cards: cards.filter((_, i) => i !== idx) });
  const addCard = () => onChange({ ...content, cards: [...cards, { icon: '', title: 'New Card', items: [] }] });

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-1">
        <div>
          <span className={labelCls}>Pill Label</span>
          <input value={content?.pill_label || ''} onChange={(e) => onChange({ ...content, pill_label: e.target.value })} className={inputCls} placeholder="Category tag" />
        </div>
        <div>
          <span className={labelCls}>KPI Value</span>
          <input value={content?.kpi_value || ''} onChange={(e) => onChange({ ...content, kpi_value: e.target.value })} className={inputCls} placeholder="+$7-10T" />
        </div>
      </div>
      <div>
        <span className={labelCls}>KPI Label</span>
        <input value={content?.kpi_label || ''} onChange={(e) => onChange({ ...content, kpi_label: e.target.value })} className={inputCls} placeholder="Label" />
      </div>
      <div>
        <span className={labelCls}>Subnote</span>
        <input value={content?.kpi_subnote || ''} onChange={(e) => onChange({ ...content, kpi_subnote: e.target.value })} className={inputCls} placeholder="Supporting explanation" />
      </div>
      <div>
        <span className={labelCls}>Footnote</span>
        <input value={content?.kpi_footnote || ''} onChange={(e) => onChange({ ...content, kpi_footnote: e.target.value })} className={inputCls} placeholder="Source note" />
      </div>
      <div className="flex items-center justify-between">
        <span className={labelCls}>Detail Cards</span>
        <button onClick={addCard} className="text-[10px] text-[#A32020] hover:underline">+ Add card</button>
      </div>
      {cards.map((card, i) => (
        <CardEditor key={i} card={card} onChange={(c) => updateCard(i, c)} index={i} onRemove={() => removeCard(i)} canRemove={true} />
      ))}
    </div>
  );
}

// Spotlight reuses CardEditor for main + sidebar
function SpotlightEditor({ content, onChange }) {
  const main = content?.main_card || {};
  const sidebar = content?.sidebar_cards || [];
  const stats = content?.stats || [];

  const updateSidebar = (idx, card) => {
    const next = [...sidebar];
    next[idx] = card;
    onChange({ ...content, sidebar_cards: next });
  };
  const removeSidebar = (idx) => onChange({ ...content, sidebar_cards: sidebar.filter((_, i) => i !== idx) });
  const addSidebar = () => onChange({ ...content, sidebar_cards: [...sidebar, { tag: '', title: 'New Card', items: [] }] });
  const updateStat = (idx, field, val) => {
    const next = [...stats];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, stats: next });
  };
  const removeStat = (idx) => onChange({ ...content, stats: stats.filter((_, i) => i !== idx) });

  return (
    <div className="space-y-2">
      <span className={labelCls}>Main Card</span>
      <CardEditor card={main} onChange={(c) => onChange({ ...content, main_card: c })} index={0} onRemove={() => {}} canRemove={false} />
      {stats.length > 0 && (
        <>
          <span className={labelCls}>Stats Row</span>
          {stats.map((s, i) => (
            <div key={i} className="flex items-center gap-1">
              <input value={s.value || ''} onChange={(e) => updateStat(i, 'value', e.target.value)} className={inputCls + " flex-1"} placeholder="Value" />
              <input value={s.label || ''} onChange={(e) => updateStat(i, 'label', e.target.value)} className={inputCls + " flex-1"} placeholder="Label" />
              <button onClick={() => removeStat(i)} className="text-gray-400 hover:text-red-500 text-xs px-1">&times;</button>
            </div>
          ))}
        </>
      )}
      <div className="flex items-center justify-between">
        <span className={labelCls}>Sidebar Cards</span>
        <button onClick={addSidebar} className="text-[10px] text-[#A32020] hover:underline">+ Add card</button>
      </div>
      {sidebar.map((card, i) => (
        <CardEditor key={i} card={card} onChange={(c) => updateSidebar(i, c)} index={i} onRemove={() => removeSidebar(i)} canRemove={true} />
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------------
// CV TEAM SUMMARY EDITOR
// ---------------------------------------------------------------------------

function CVTeamSummaryEditor({ content, onChange }) {
  const profiles = content?.profiles || [];

  const updateProfile = (idx, field, val) => {
    const next = [...profiles];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, profiles: next });
  };

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Team Title</label>
        <input
          value={content?.team_title || ''}
          onChange={(e) => onChange({ ...content, team_title: e.target.value })}
          className={inputCls}
          placeholder="Short team description"
        />
      </div>
      {profiles.map((p, i) => (
        <div key={i} className={sectionCls}>
          <span className="text-[10px] font-bold text-[#A32020]">Profile {i + 1}</span>
          <input value={p.name || ''} onChange={(e) => updateProfile(i, 'name', e.target.value)} className={inputCls} placeholder="Name" />
          <div className="grid grid-cols-2 gap-1">
            <input value={p.level || ''} onChange={(e) => updateProfile(i, 'level', e.target.value)} className={inputCls} placeholder="Level" />
            <input value={p.city || ''} onChange={(e) => updateProfile(i, 'city', e.target.value)} className={inputCls} placeholder="City" />
          </div>
          <EditableList items={p.summary_lines || []} onChange={(v) => updateProfile(i, 'summary_lines', v)} label="Summary" placeholder="Summary bullet" />
          <EditableList items={p.relevant_experience_lines || []} onChange={(v) => updateProfile(i, 'relevant_experience_lines', v)} label="Relevant Experience" placeholder="Experience bullet" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CV INDIVIDUAL EDITOR
// ---------------------------------------------------------------------------

function CVIndividualEditor({ content, onChange }) {
  const leftCol = content?.left_column || {};
  const projects = content?.projects || [];

  const updateLeft = (field, val) => {
    onChange({ ...content, left_column: { ...leftCol, [field]: val } });
  };

  const updateProject = (idx, field, val) => {
    const next = [...projects];
    next[idx] = { ...next[idx], [field]: val };
    onChange({ ...content, projects: next });
  };
  const removeProject = (idx) => onChange({ ...content, projects: projects.filter((_, i) => i !== idx) });
  const addProject = () => onChange({ ...content, projects: [...projects, { title: '', bullets: [] }] });

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-1">
        <input value={content?.name || ''} onChange={(e) => onChange({ ...content, name: e.target.value })} className={inputCls} placeholder="Name" />
        <input value={content?.level || ''} onChange={(e) => onChange({ ...content, level: e.target.value })} className={inputCls} placeholder="Level" />
        <input value={content?.city || ''} onChange={(e) => onChange({ ...content, city: e.target.value })} className={inputCls} placeholder="City" />
      </div>

      <div className={sectionCls}>
        <span className="text-[10px] font-bold text-[#A32020]">Profile Sections</span>
        <EditableList items={leftCol.executive_summary || []} onChange={(v) => updateLeft('executive_summary', v)} label="Executive Summary" placeholder="Summary bullet" />
        <EditableList items={leftCol.relevant_experience || []} onChange={(v) => updateLeft('relevant_experience', v)} label="Relevant Experience" placeholder="Experience bullet" />
        <EditableList items={leftCol.prior_experience || []} onChange={(v) => updateLeft('prior_experience', v)} label="Prior Experience" placeholder="Prior experience bullet" />
        <EditableList items={leftCol.education_and_languages || []} onChange={(v) => updateLeft('education_and_languages', v)} label="Education & Languages" placeholder="Education bullet" />
      </div>

      <div className={sectionCls}>
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold text-[#A32020]">Projects</span>
          <button onClick={addProject} className="text-[10px] text-[#A32020] hover:underline">+ Add Project</button>
        </div>
        {projects.map((proj, i) => (
          <div key={i} className="space-y-1 p-2 bg-white rounded border border-border/50">
            <div className="flex items-center gap-1">
              <input value={proj.title || ''} onChange={(e) => updateProject(i, 'title', e.target.value)} className={inputCls + " flex-1"} placeholder="Project title" />
              <button onClick={() => removeProject(i)} className="text-gray-400 hover:text-red-500 text-xs px-1">&times;</button>
            </div>
            <EditableList items={proj.bullets || []} onChange={(v) => updateProject(i, 'bullets', v)} label="Bullets" placeholder="Bullet point" />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CONTENT EDITOR DISPATCHER
// ---------------------------------------------------------------------------

const CONTENT_EDITORS = {
  bullet_list: BulletListEditor,
  card_grid: CardGridEditor,
  spotlight: SpotlightEditor,
  approach: ApproachEditor,
  metrics_dashboard: MetricsDashboardEditor,
  timeline: TimelineEditor,
  comparison_table: ComparisonTableEditor,
  call_to_action: CallToActionEditor,
  kpi_hero: KPIHeroEditor,
  cv_team_summary: CVTeamSummaryEditor,
  cv_individual: CVIndividualEditor,
};

// Map layout types to their content type
function getContentType(layout) {
  const map = {
    title_content: 'bullet_list',
    two_column: 'card_grid',
    three_column: 'card_grid',
    spotlight: 'spotlight',
    approach_3step: 'approach',
    approach_4step: 'approach',
    approach_5step: 'approach',
    horizontal_approach: 'approach',
    metrics_dashboard: 'metrics_dashboard',
    timeline: 'timeline',
    comparison_table: 'comparison_table',
    call_to_action: 'call_to_action',
    kpi_hero: 'kpi_hero',
    cv_team_summary: 'cv_team_summary',
    cv_individual: 'cv_individual',
  };
  return map[layout] || 'bullet_list';
}


// ---------------------------------------------------------------------------
// MAIN COMPONENT
// ---------------------------------------------------------------------------

const SlideContentEditor = ({ slide, onChange }) => {
  if (!slide) return null;

  const handleFieldChange = useCallback((field, value) => {
    onChange({ ...slide, [field]: value });
  }, [slide, onChange]);

  const handleContentChange = useCallback((newContent) => {
    onChange({ ...slide, content: newContent });
  }, [slide, onChange]);

  const content = slide.content || {};
  const contentType = content.type || getContentType(slide.layout);
  const ContentEditor = CONTENT_EDITORS[contentType];

  return (
    <div className="space-y-3 text-xs">
      {/* Headline */}
      <div>
        <label className={labelCls}>Headline</label>
        <textarea
          value={slide.headline || ''}
          onChange={(e) => handleFieldChange('headline', e.target.value)}
          className={inputCls + " resize-none"}
          rows={2}
          placeholder="Active, news-style sentence (the 'so what')"
        />
      </div>

      {/* Subtitle + Layout */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className={labelCls}>Subtitle</label>
          <input
            value={slide.subtitle || ''}
            onChange={(e) => handleFieldChange('subtitle', e.target.value)}
            className={inputCls}
            placeholder="Topic tag"
          />
        </div>
        <div>
          <label className={labelCls}>Layout</label>
          <select
            value={slide.layout || 'title_content'}
            onChange={(e) => handleFieldChange('layout', e.target.value)}
            className={inputCls}
          >
            {LAYOUT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-border pt-2">
        <span className="text-[10px] font-bold text-foreground uppercase tracking-wider">Content</span>
      </div>

      {/* Content editor */}
      {ContentEditor ? (
        <ContentEditor content={content} onChange={handleContentChange} />
      ) : (
        <div className="text-muted-foreground italic text-[10px]">
          No structured editor for content type "{contentType}". Use chat to modify.
        </div>
      )}

      {/* Speaker Notes */}
      <div>
        <label className={labelCls}>Speaker Notes</label>
        <textarea
          value={slide.speaker_notes || ''}
          onChange={(e) => handleFieldChange('speaker_notes', e.target.value)}
          className={inputCls + " resize-none"}
          rows={2}
          placeholder="Notes for the presenter..."
        />
      </div>
    </div>
  );
};

export default SlideContentEditor;
