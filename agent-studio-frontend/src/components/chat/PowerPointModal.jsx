/**
 * PowerPointModal Component
 *
 * Modal for AI-driven PowerPoint generation (storyline -> build -> refine).
 * CV / template-based exports are handled by the generic template engine
 * via the "Export with Template" path in DeliverableReview.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import Button from '../ui/Button';
import HorizontalLogicEditor from './HorizontalLogicEditor';
import SlideContentEditor from './SlideContentEditor';
import {
  generateHorizontalLogic,
  generateVerticalLogic,
  generateSlide,
  modifySlide,
  exportPowerPoint,
} from '@/api/client';

const PHASES = {
  HORIZONTAL: 'horizontal',
  VERTICAL: 'vertical',
  REFINEMENT: 'refinement',
};

const SLIDE_LAYOUTS = [
  { value: 'title_content', label: 'Title + Content', description: 'Simple title with bullet points' },
  { value: 'two_column', label: 'Two Column', description: 'Side-by-side comparison cards' },
  { value: 'three_column', label: 'Three Column', description: 'Three strategic pillars or levers' },
  { value: 'spotlight', label: 'Spotlight', description: 'One main topic with supporting sidebar' },
  { value: 'approach_3step', label: 'Approach (3-step)', description: 'Three-phase methodology' },
  { value: 'approach_4step', label: 'Approach (4-step)', description: 'Four-phase project plan' },
  { value: 'approach_5step', label: 'Approach (5-step)', description: 'Five-phase roadmap' },
  { value: 'horizontal_approach', label: 'Horizontal Approach', description: 'Process flow with crosscut bar' },
  { value: 'metrics_dashboard', label: 'Metrics Dashboard', description: 'KPI boxes with insight panels' },
  { value: 'timeline', label: 'Timeline', description: 'Quarterly or phased milestones' },
  { value: 'comparison_table', label: 'Comparison Table', description: 'Options evaluation matrix' },
  { value: 'call_to_action', label: 'Call to Action', description: 'Next steps with owners and dates' },
  { value: 'kpi_hero', label: 'KPI Hero', description: 'Hero metric with supporting detail cards' },
];

const LAYOUT_SAMPLES = {
  title_content: { id: 'p1', layout: 'title_content', headline: 'Market growth is decelerating across core segments', subtitle: 'Market context', content: { type: 'bullet_list', items: [{ text: 'Revenue declined 12% YoY in Q3', bold_prefix: 'Revenue decline', level: 0 }, { text: 'Three segments below growth threshold', bold_prefix: null, level: 1 }, { text: 'Competitive pressure intensifying in digital', bold_prefix: 'Digital threat', level: 0 }] } },
  two_column: { id: 'p2', layout: 'two_column', headline: 'Two strategic imperatives drive the transformation agenda', subtitle: 'Strategic imperatives', content: { type: 'card_grid', cards: [{ tag: 'Imperative 1', title: 'Operational excellence', description: 'Streamline core operations', items: ['Process automation', 'Cost reduction'], footer: 'Target: -20% OpEx' }, { tag: 'Imperative 2', title: 'Digital growth', description: 'Expand digital channels', items: ['Platform launch', 'Customer acquisition'], footer: 'Target: +30% digital' }] } },
  three_column: { id: 'p3', layout: 'three_column', headline: 'Three pillars underpin the growth strategy', subtitle: 'Strategic pillars', content: { type: 'card_grid', cards: [{ tag: 'Pillar 1', title: 'Innovation', description: 'R&D investment', items: ['New products', 'IP portfolio'], footer: '$50M allocated' }, { tag: 'Pillar 2', title: 'Expansion', description: 'Market entry', items: ['GCC markets', 'SE Asia'], footer: '3 new markets' }, { tag: 'Pillar 3', title: 'Talent', description: 'Capability build', items: ['Hiring plan', 'Upskilling'], footer: '200 new hires' }] } },
  spotlight: { id: 'p4', layout: 'spotlight', headline: 'Digital transformation is the primary value lever', subtitle: 'Key initiative', content: { type: 'spotlight', main_card: { tag: 'Primary', title: 'Digital platform', description: 'End-to-end digital transformation', items: ['Customer portal', 'API ecosystem', 'Data platform'] }, stats: [{ value: '$45M', label: 'Annual Value' }, { value: '18mo', label: 'Timeline' }], sidebar_cards: [{ tag: 'Supporting', title: 'Change mgmt', description: 'Organization readiness', footer: '$5M' }, { tag: 'Enabler', title: 'Cloud migration', description: 'Infrastructure modernization', footer: '$8M' }] } },
  approach_3step: { id: 'p5', layout: 'approach_3step', headline: 'A three-phase approach delivers results within 12 months', subtitle: 'Approach', content: { type: 'approach', phases: [{ number: 1, title: 'Diagnose', duration: 'Weeks 1-4', substeps: ['Stakeholder interviews', 'Data analysis', 'Gap assessment'] }, { number: 2, title: 'Design', duration: 'Weeks 5-12', substeps: ['Solution architecture', 'Roadmap planning', 'Business case'] }, { number: 3, title: 'Deliver', duration: 'Weeks 13-24', substeps: ['Implementation', 'Testing & launch', 'Change management'] }] } },
  approach_4step: { id: 'p6', layout: 'approach_4step', headline: 'Four phases ensure systematic execution', subtitle: 'Implementation plan', content: { type: 'approach', phases: [{ number: 1, title: 'Assess', duration: 'Wk 1-3', substeps: ['Current state', 'Benchmarking'] }, { number: 2, title: 'Plan', duration: 'Wk 4-8', substeps: ['Target model', 'Roadmap'] }, { number: 3, title: 'Build', duration: 'Wk 9-16', substeps: ['Development', 'Integration'] }, { number: 4, title: 'Scale', duration: 'Wk 17-24', substeps: ['Rollout', 'Optimization'] }] } },
  approach_5step: { id: 'p7', layout: 'approach_5step', headline: 'Five workstreams run in parallel to accelerate delivery', subtitle: 'Workstreams', content: { type: 'approach', phases: [{ number: 1, title: 'Strategy', duration: 'Wk 1-4', substeps: ['Vision', 'Priorities'] }, { number: 2, title: 'Design', duration: 'Wk 3-8', substeps: ['Architecture', 'UX'] }, { number: 3, title: 'Build', duration: 'Wk 6-14', substeps: ['Development', 'QA'] }, { number: 4, title: 'Test', duration: 'Wk 12-18', substeps: ['UAT', 'Performance'] }, { number: 5, title: 'Launch', duration: 'Wk 16-20', substeps: ['Deploy', 'Monitor'] }] } },
  horizontal_approach: { id: 'p8', layout: 'horizontal_approach', headline: 'Delivery follows a phased approach with cross-cutting governance', subtitle: 'Delivery model', content: { type: 'approach', phases: [{ number: 1, title: 'Foundation', duration: 'Months 1-3', substeps: ['Setup', 'Baseline'] }, { number: 2, title: 'Execution', duration: 'Months 4-9', substeps: ['Sprints', 'Integration'] }, { number: 3, title: 'Transition', duration: 'Months 10-12', substeps: ['Handover', 'Stabilize'] }], crosscut: { title: 'PMO & Governance', items: ['Steering committee', 'Risk management', 'Quality assurance'] } } },
  metrics_dashboard: { id: 'p9', layout: 'metrics_dashboard', headline: 'Program is tracking ahead of plan across all KPIs', subtitle: 'Performance dashboard', content: { type: 'metrics_dashboard', metrics: [{ value: '$18.4M', label: 'Cost Savings', change: '+24%', status: 'up' }, { value: '94%', label: 'On-time Delivery', change: '+8%', status: 'up' }, { value: '4.2/5', label: 'Satisfaction', change: '+0.6', status: 'up' }], insights: [{ title: "What's Working", items: ['Automation pipeline', 'Team velocity'] }, { title: 'Watch Items', items: ['Vendor delays', 'Scope creep'] }] } },
  timeline: { id: 'p10', layout: 'timeline', headline: 'Implementation roadmap spans four quarters', subtitle: 'Roadmap', content: { type: 'timeline', phases: [{ phase_label: 'Q1 2025', date_range: 'Jan-Mar', title: 'Foundation', items: ['Team setup', 'Requirements'], status: 'past' }, { phase_label: 'Q2 2025', date_range: 'Apr-Jun', title: 'Build', items: ['Development', 'Testing'], status: 'current' }, { phase_label: 'Q3 2025', date_range: 'Jul-Sep', title: 'Launch', items: ['Deployment', 'Training'], status: 'future' }] } },
  comparison_table: { id: 'p11', layout: 'comparison_table', headline: 'Option B delivers the best risk-adjusted return', subtitle: 'Options analysis', content: { type: 'comparison_table', headers: ['Criteria', 'Option A', 'Option B', 'Option C'], rows: [['Investment', '$10M', '$15M', '$25M'], ['Timeline', '6 months', '9 months', '18 months'], ['ROI', '2.1x', '3.4x', '2.8x'], ['Risk', 'High', 'Medium', 'Low']], recommended_column: 2, recommendation: 'Option B balances investment with returns' } },
  call_to_action: { id: 'p12', layout: 'call_to_action', headline: 'Three decisions are needed to maintain momentum', subtitle: 'Next steps', content: { type: 'call_to_action', banner_headline: 'Approval required by end of month', banner_subtext: 'Delay risks Q3 delivery milestones', actions: [{ number: 1, title: 'Approve budget', description: 'Sign off on $15M investment', owner: 'CFO', due_date: 'Mar 15' }, { number: 2, title: 'Confirm team', description: 'Assign project leads', owner: 'CHRO', due_date: 'Mar 20' }] } },
  kpi_hero: { id: 'p13', layout: 'kpi_hero', headline: 'Strategy& has delivered $7-10T in client value globally', subtitle: 'Track record', content: { type: 'kpi_hero', pill_label: 'Global impact', kpi_value: '$7-10T', kpi_label: 'Cumulative client value delivered', kpi_subnote: 'Across 50+ countries since 2014', kpi_footnote: 'Source: Strategy& internal analysis', cards: [{ icon: 'G', title: 'Government', items: ['National strategies', 'Giga-projects'] }, { icon: 'E', title: 'Enterprise', items: ['Digital transformation', 'M&A advisory'] }] } },
};

function collectSlideItems(value, limit = 8) {
  const items = [];
  const push = (text) => {
    if (text && items.length < limit) items.push(String(text));
  };

  const walk = (node) => {
    if (!node || items.length >= limit) return;
    if (typeof node === 'string') {
      push(node);
      return;
    }
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (typeof node === 'object') {
      if (node.text) push(node.bold_prefix ? `${node.bold_prefix}: ${node.text}` : node.text);
      if (node.title && node.description) push(`${node.title}: ${node.description}`);
      else if (node.title) push(node.title);
      if (node.value && node.label) push(`${node.value} ${node.label}`);
      if (node.phase_label && node.title) push(`${node.phase_label}: ${node.title}`);
      Object.entries(node).forEach(([key, child]) => {
        if (!['text', 'bold_prefix', 'title', 'description', 'value', 'label', 'phase_label'].includes(key)) {
          walk(child);
        }
      });
    }
  };

  walk(value);
  return items;
}

function NativeSlidePreview({ slide, scale = 1 }) {
  const items = collectSlideItems(slide?.content);
  return (
    <div
      className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg"
      style={{
        width: 960,
        height: 540,
        transform: `scale(${scale})`,
        transformOrigin: 'top left',
      }}
    >
      <div className="flex h-full flex-col p-12">
        <div className="mb-4 text-xs font-bold uppercase tracking-[0.25em] text-[#A32020]">
          {slide?.subtitle || slide?.layout || 'Slide'}
        </div>
        <h2 className="max-w-[780px] text-4xl font-bold leading-tight text-gray-950">
          {slide?.headline || slide?.title || 'Untitled slide'}
        </h2>
        <div className="mt-8 grid flex-1 gap-4">
          {items.length ? (
            items.slice(0, 6).map((item, index) => (
              <div key={index} className="flex gap-3 rounded-xl border border-gray-200 bg-gray-50 p-4">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#A32020] text-sm font-bold text-white">
                  {index + 1}
                </span>
                <p className="text-lg leading-snug text-gray-800">{item}</p>
              </div>
            ))
          ) : (
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-5 text-lg text-gray-600">
              Slide content will appear here.
            </div>
          )}
        </div>
        <div className="mt-6 h-1.5 w-32 rounded-full bg-[#A32020]" />
      </div>
    </div>
  );
}

const PowerPointModal = ({ isOpen, onClose, deliverable }) => {
  // Phase state
  const [phase, setPhase] = useState(PHASES.HORIZONTAL);
  const [maxPhaseReached, setMaxPhaseReached] = useState(PHASES.HORIZONTAL);
  const [horizontalLogic, setHorizontalLogic] = useState(null);
  const [slides, setSlides] = useState([]);
  const [selectedSlideIdx, setSelectedSlideIdx] = useState(0);

  // Loading / generation states
  const [isGeneratingHL, setIsGeneratingHL] = useState(false);
  const [isGeneratingVL, setIsGeneratingVL] = useState(false);
  const [slidesReady, setSlidesReady] = useState(0);
  const [isModifying, setIsModifying] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);

  // Storyline guidance state
  const [storylineInput, setStorylineInput] = useState('');
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [mentionStartIdx, setMentionStartIdx] = useState(null);
  const [mentionHighlight, setMentionHighlight] = useState(0);
  const [mentionPreview, setMentionPreview] = useState(null);
  const storylineRef = useRef(null);

  // Chat state
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const chatEndRef = useRef(null);
  
  // Right panel mode: 'chat' (LLM-assisted) or 'edit' (manual hand-editing)
  const [rightPanelMode, setRightPanelMode] = useState('chat');
  
  // Error state
  const [error, setError] = useState(null);

  // Scroll chat to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  // Reset when modal opens
  useEffect(() => {
    if (isOpen) {
      setHorizontalLogic(null);
      setSlides([]);
      setSelectedSlideIdx(0);
      setSlidesReady(0);
      setStorylineInput('');
      setChatHistory([]);
      setChatInput('');
      setRightPanelMode('chat');
      setError(null);
      setPhase(PHASES.HORIZONTAL);
      setMaxPhaseReached(PHASES.HORIZONTAL);
    }
  }, [isOpen]);

  const getDeliverableData = useCallback(() => {
    if (!deliverable?.deliverable) return {};
    let content = deliverable.deliverable;
    if (typeof content === 'string') {
      try { content = JSON.parse(content); } catch { return { text: content }; }
    }
    return content;
  }, [deliverable]);

  // ==========================================================================
  // PHASE 1: HORIZONTAL LOGIC
  // ==========================================================================

  const handleGenerateHL = async (context = null) => {
    setIsGeneratingHL(true);
    setError(null);
    try {
      const result = await generateHorizontalLogic({
        deliverable_id: deliverable.id,
        deliverable_data: getDeliverableData(),
        context,
      });
      setHorizontalLogic(result.horizontal_logic);
    } catch (err) {
      setError(`Failed to generate storyline: ${err.message}`);
    } finally {
      setIsGeneratingHL(false);
    }
  };

  const handleConfirmHL = () => {
    if (!horizontalLogic?.slides?.length) return;
    setPhase(PHASES.VERTICAL);
    setMaxPhaseReached((prev) => {
      const order = [PHASES.HORIZONTAL, PHASES.VERTICAL, PHASES.REFINEMENT];
      return order.indexOf(PHASES.VERTICAL) > order.indexOf(prev) ? PHASES.VERTICAL : prev;
    });
    handleGenerateVL();
  };

  // ==========================================================================
  // PHASE 2: VERTICAL LOGIC
  // ==========================================================================

  const handleGenerateVL = async () => {
    setIsGeneratingVL(true);
    setSlidesReady(0);
    setError(null);
    try {
      const result = await generateVerticalLogic({
        deliverable_data: getDeliverableData(),
        horizontal_logic: horizontalLogic,
      });
      setSlides(result.slides || []);
      setSlidesReady(result.total || result.slides?.length || 0);
      setPhase(PHASES.REFINEMENT);
      setMaxPhaseReached(PHASES.REFINEMENT);
      setSelectedSlideIdx(0);
    } catch (err) {
      setError(`Failed to generate slides: ${err.message}`);
    } finally {
      setIsGeneratingVL(false);
    }
  };

  // ==========================================================================
  // PHASE 3: REFINEMENT
  // ==========================================================================

  const handleModifySlide = async () => {
    if (!chatInput.trim() || isModifying) return;
    const instruction = chatInput.trim();
    setChatInput('');
    setChatHistory(prev => [...prev, { role: 'user', text: instruction }]);
    setIsModifying(true);
    setError(null);
    
    try {
      const result = await modifySlide({
        slide: slides[selectedSlideIdx],
        instruction,
        deliverable_data: getDeliverableData(),
      });
      const updatedSlides = [...slides];
      updatedSlides[selectedSlideIdx] = result.slide;
      setSlides(updatedSlides);
      setChatHistory(prev => [...prev, { role: 'assistant', text: `Slide updated: ${result.message}` }]);
    } catch (err) {
      setChatHistory(prev => [...prev, { role: 'assistant', text: `Error: ${err.message}`, isError: true }]);
    } finally {
      setIsModifying(false);
    }
  };

  const handleRegenerateSlide = async (idx) => {
    if (!horizontalLogic?.slides?.[idx]) return;
    setIsRegenerating(true);
    setError(null);
    const stub = horizontalLogic.slides[idx];
    
    try {
      const result = await generateSlide({
        deliverable_data: getDeliverableData(),
        headline: stub.headline,
        subtitle: stub.subtitle,
        layout: stub.suggested_layout,
      });
      const updatedSlides = [...slides];
      updatedSlides[idx] = result.slide;
      setSlides(updatedSlides);
    } catch (err) {
      setError(`Failed to regenerate slide: ${err.message}`);
    } finally {
      setIsRegenerating(false);
    }
  };

  const getDeckTitle = useCallback(() => {
    if (horizontalLogic?.deck_title) return horizontalLogic.deck_title;
    const data = getDeliverableData();
    if (data?.team_title) return data.team_title;
    return 'Presentation';
  }, [horizontalLogic, getDeliverableData]);

  const handleExport = async () => {
    setIsExporting(true);
    setError(null);
    try {
      const title = getDeckTitle();
      const blob = await exportPowerPoint({
        title,
        slides,
        theme: {},
      });
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const titleSlug = title.replace(/[^\w\s]/g, '').replace(/\s+/g, '_').substring(0, 40);
      a.download = `Strategy_and_${titleSlug}.pptx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      setError(`Failed to export: ${err.message}`);
    } finally {
      setIsExporting(false);
    }
  };

  // Manual edit handler: directly update slide in state (no LLM call)
  const handleManualSlideUpdate = useCallback((updatedSlide) => {
    const updatedSlides = [...slides];
    updatedSlides[selectedSlideIdx] = updatedSlide;
    setSlides(updatedSlides);
  }, [slides, selectedSlideIdx]);

  // ==========================================================================
  // STORYLINE @MENTION HANDLERS
  // ==========================================================================

  const filteredLayouts = SLIDE_LAYOUTS.filter(
    (l) => l.label.toLowerCase().includes(mentionFilter.toLowerCase()) ||
           l.value.toLowerCase().includes(mentionFilter.toLowerCase())
  );

  const handleStorylineChange = (e) => {
    const val = e.target.value;
    const cursor = e.target.selectionStart;
    setStorylineInput(val);

    const textBeforeCursor = val.slice(0, cursor);
    const atIdx = textBeforeCursor.lastIndexOf('@');

    if (atIdx !== -1) {
      const charBefore = atIdx > 0 ? val[atIdx - 1] : ' ';
      const textAfterAt = textBeforeCursor.slice(atIdx + 1);
      const hasSpace = /\n/.test(textAfterAt);

      if ((charBefore === ' ' || charBefore === '\n' || atIdx === 0) && !hasSpace) {
        setMentionOpen(true);
        setMentionFilter(textAfterAt);
        setMentionStartIdx(atIdx);
        setMentionHighlight(0);
        return;
      }
    }
    setMentionOpen(false);
  };

  const handleMentionSelect = (layout) => {
    if (mentionStartIdx === null) return;
    const before = storylineInput.slice(0, mentionStartIdx);
    const ta = storylineRef.current;
    const cursorPos = ta ? ta.selectionStart : mentionStartIdx + mentionFilter.length + 1;
    const after = storylineInput.slice(cursorPos);
    const inserted = `@${layout.label} `;
    const newVal = before + inserted + after;
    setStorylineInput(newVal);
    setMentionOpen(false);
    setMentionFilter('');
    setMentionStartIdx(null);

    requestAnimationFrame(() => {
      if (ta) {
        const newCursor = before.length + inserted.length;
        ta.focus();
        ta.setSelectionRange(newCursor, newCursor);
      }
    });
  };

  const handleStorylineKeyDown = (e) => {
    if (!mentionOpen || filteredLayouts.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setMentionHighlight((prev) => Math.min(prev + 1, filteredLayouts.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setMentionHighlight((prev) => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      handleMentionSelect(filteredLayouts[mentionHighlight]);
    } else if (e.key === 'Escape') {
      setMentionOpen(false);
    }
  };

  const handleChatKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleModifySlide();
    }
  };

  // ==========================================================================
  // PHASE NAVIGATION
  // ==========================================================================

  const PHASE_ORDER = [PHASES.HORIZONTAL, PHASES.VERTICAL, PHASES.REFINEMENT];

  const canNavigateToPhase = (targetPhase) => {
    const targetIdx = PHASE_ORDER.indexOf(targetPhase);
    const currentIdx = PHASE_ORDER.indexOf(phase);
    const maxIdx = PHASE_ORDER.indexOf(maxPhaseReached);
    return targetIdx !== currentIdx && targetIdx <= maxIdx && !isGeneratingHL && !isGeneratingVL && !isModifying && !isExporting;
  };

  const navigateToPhase = (targetPhase) => {
    if (!canNavigateToPhase(targetPhase)) return;
    setPhase(targetPhase);
    setError(null);
  };

  const handleBack = () => {
    const currentIdx = PHASE_ORDER.indexOf(phase);
    if (currentIdx > 0) {
      navigateToPhase(PHASE_ORDER[currentIdx - 1]);
    }
  };

  // ==========================================================================
  // RENDER
  // ==========================================================================

  if (!isOpen) return null;

  // Calculate scale for slide preview to fit container
  const previewScale = phase === PHASES.REFINEMENT ? 0.9 : 0.5;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div className="bg-surface border border-border rounded-2xl shadow-2xl flex flex-col"
           style={{ width: '90%', maxWidth: '1400px', height: '88vh' }}>
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <svg className="w-5 h-5 text-[#A32020]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <h2 className="text-lg font-semibold text-foreground">PowerPoint Generator</h2>
            </div>
            
            {/* Back button */}
            {PHASE_ORDER.indexOf(phase) > 0 && (
              <button
                onClick={handleBack}
                disabled={isGeneratingHL || isGeneratingVL || isModifying || isExporting}
                className="ml-2 flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-full transition-colors border border-gray-200"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
                Back
              </button>
            )}

            {/* Phase indicator */}
            <div className="flex items-center gap-2 ml-4">
              {[
                { key: PHASES.HORIZONTAL, label: '1. Storyline' },
                { key: PHASES.VERTICAL, label: '2. Building' },
                { key: PHASES.REFINEMENT, label: '3. Refine & Export' },
              ].map((p, i) => {
                const clickable = canNavigateToPhase(p.key);
                return (
                  <div key={p.key} className="flex items-center gap-1.5">
                    {i > 0 && <div className="w-5 h-0.5 bg-border" />}
                    <span
                      onClick={clickable ? () => navigateToPhase(p.key) : undefined}
                      className={`
                        text-xs font-medium px-2.5 py-1 rounded-full transition-colors
                        ${phase === p.key
                          ? 'bg-[#A32020] text-white'
                          : PHASE_ORDER.indexOf(p.key) <= PHASE_ORDER.indexOf(maxPhaseReached)
                            ? 'bg-green-100 text-green-700'
                            : 'bg-gray-100 text-gray-500'
                        }
                        ${clickable ? 'cursor-pointer hover:ring-2 hover:ring-[#A32020]/30' : ''}
                      `}
                    >
                      {p.label}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
          
          <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-gray-600 transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Error banner */}
        {error && (
          <div className="mx-6 mt-3 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
            <svg className="w-4 h-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <span className="text-sm text-red-700 flex-1">{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-hidden">

          {/* PHASE 1: Horizontal Logic */}
          {phase === PHASES.HORIZONTAL && (
            <div className="h-full flex flex-col p-6">
              {!horizontalLogic && !isGeneratingHL && (
                <div className="flex-1 flex flex-col items-center pt-4">
                  <div className="w-full max-w-3xl flex flex-col flex-1 min-h-0 gap-4">
                    <div className="text-center flex-shrink-0">
                      <h3 className="text-xl font-semibold text-foreground mb-1">Generate Presentation Storyline</h3>
                      <p className="text-sm text-muted-foreground">
                        Describe the storyline you want, or let the AI build one automatically from the deliverable.
                      </p>
                    </div>

                    {/* Guidance input */}
                    <div className="bg-white border border-border rounded-xl shadow-sm flex flex-col flex-1 min-h-0 focus-within:border-border">
                      <textarea
                        ref={storylineRef}
                        value={storylineInput}
                        onChange={handleStorylineChange}
                        onKeyDown={handleStorylineKeyDown}
                        onBlur={() => setTimeout(() => setMentionOpen(false), 200)}
                        style={{ outline: 'none' }}
                        className="w-full flex-1 px-5 py-4 text-sm bg-transparent border-0 rounded-t-xl focus:outline-none focus:ring-0 text-foreground placeholder:text-muted-foreground resize-none min-h-[200px]"
                        placeholder={"Describe the slides you want. Type @ to insert a layout template.\n\nExample:\n\"I want 5 slides:\n1. Intro slide using @Title + Content\n2. Track record as @KPI Hero\n3. Three pillars using @Three Column\n4. Approach in @Approach (4-step)\n5. @Call to Action with next steps\""}
                      />

                      {/* @mention dropdown with live preview */}
                      {mentionOpen && filteredLayouts.length > 0 && (
                        <div className="border-t border-border bg-white flex" style={{ maxHeight: 320 }}>
                          {/* Layout list */}
                          <div className="w-56 flex-shrink-0 overflow-y-auto border-r border-border">
                            <div className="px-3 py-1.5 bg-gray-50 border-b border-border sticky top-0">
                              <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Slide Layouts</span>
                            </div>
                            {filteredLayouts.map((layout, i) => (
                              <button
                                key={layout.value}
                                onMouseDown={(e) => { e.preventDefault(); handleMentionSelect(layout); }}
                                onMouseEnter={() => { setMentionHighlight(i); setMentionPreview(layout.value); }}
                                className={`w-full text-left px-3 py-2 transition-colors ${
                                  i === mentionHighlight ? 'bg-[#FDF2F4]' : 'hover:bg-gray-50'
                                }`}
                              >
                                <span className={`text-xs font-semibold block ${
                                  i === mentionHighlight ? 'text-[#A32020]' : 'text-foreground'
                                }`}>
                                  @{layout.label}
                                </span>
                                <span className="text-[10px] text-muted-foreground leading-tight">{layout.description}</span>
                              </button>
                            ))}
                          </div>

                          {/* Live preview panel */}
                          <div className="flex-1 min-w-0 bg-gray-50 flex items-center justify-center p-3">
                            {LAYOUT_SAMPLES[mentionPreview || filteredLayouts[mentionHighlight]?.value] ? (
                              <div className="w-full" style={{ maxWidth: 384 }}>
                                <div style={{ width: '100%', aspectRatio: '16/9' }}>
                                  <NativeSlidePreview
                                    slide={LAYOUT_SAMPLES[mentionPreview || filteredLayouts[mentionHighlight]?.value]}
                                    scale={0.4}
                                  />
                                </div>
                              </div>
                            ) : (
                              <span className="text-xs text-muted-foreground">Hover to preview</span>
                            )}
                          </div>
                        </div>
                      )}

                      <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-t border-border rounded-b-xl">
                        <span className="text-xs text-muted-foreground">
                          {storylineInput.trim()
                            ? 'AI will follow your guidance'
                            : <>Type <kbd className="px-1 py-0.5 bg-gray-200 rounded text-[10px] font-mono">@</kbd> to insert a layout template</>
                          }
                        </span>
                        <div className="flex items-center gap-2">
                          {storylineInput.trim() && (
                            <button
                              onClick={() => setStorylineInput('')}
                              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                            >
                              Clear
                            </button>
                          )}
                          <Button
                            onClick={() => handleGenerateHL(storylineInput.trim() || null)}
                            className="bg-[#A32020] hover:bg-[#7a1818] text-white text-sm px-5"
                          >
                            {storylineInput.trim() ? 'Generate from Brief' : 'Auto Generate'}
                          </Button>
                        </div>
                      </div>
                    </div>

                    {/* Quick examples */}
                    <div className="flex-shrink-0 pb-2">
                      <p className="text-xs text-muted-foreground mb-2">Quick examples — click to use:</p>
                      <div className="flex flex-wrap gap-2">
                        {[
                          '4 slides: intro, problem, solution, next steps',
                          '6 slides with a KPI hero slide and a timeline',
                          'Focus on our track record and credentials',
                          'Start with market context, end with call to action',
                        ].map((example) => (
                          <button
                            key={example}
                            onClick={() => setStorylineInput(example)}
                            className="text-xs px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-full transition-colors border border-gray-200"
                          >
                            {example}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {isGeneratingHL && (
                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                  <div className="w-10 h-10 border-4 border-[#A32020] border-t-transparent rounded-full animate-spin" />
                  <p className="text-sm text-muted-foreground">Generating storyline...</p>
                </div>
              )}

              {horizontalLogic && !isGeneratingHL && (
                <div className="flex-1 flex flex-col overflow-hidden">
                  <div className="flex-1 overflow-y-auto mb-4 pr-2">
                    <HorizontalLogicEditor
                      horizontalLogic={horizontalLogic}
                      onChange={setHorizontalLogic}
                    />
                  </div>
                  <div className="flex items-center gap-3 pt-4 border-t border-border">
                    <Button
                      onClick={() => handleGenerateHL(storylineInput.trim() || null)}
                      variant="outline"
                      disabled={isGeneratingHL}
                    >
                      Regenerate
                    </Button>
                    <div className="flex-1" />
                    <Button
                      onClick={handleConfirmHL}
                      disabled={!horizontalLogic?.slides?.length}
                      className="bg-[#A32020] hover:bg-[#7a1818] text-white px-8"
                    >
                      Confirm Storyline & Build Slides
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* PHASE 2: Vertical Logic (Building) */}
          {phase === PHASES.VERTICAL && (
            <div className="h-full flex flex-col items-center justify-center p-6">
              <div className="text-center max-w-lg">
                <div className="w-14 h-14 border-4 border-[#A32020] border-t-transparent rounded-full animate-spin mx-auto mb-6" />
                <h3 className="text-xl font-semibold text-foreground mb-2">Building Slides</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Generating content for {horizontalLogic?.slides?.length || 0} slides in parallel...
                </p>
                {/* Progress bar */}
                <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
                  <div
                    className="h-full bg-[#A32020] rounded-full transition-all duration-500"
                    style={{ width: `${(slidesReady / Math.max(horizontalLogic?.slides?.length || 1, 1)) * 100}%` }}
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  {slidesReady} / {horizontalLogic?.slides?.length || 0} slides ready
                </p>
              </div>
            </div>
          )}

          {/* PHASE 3: Refinement */}
          {phase === PHASES.REFINEMENT && (
            <div className="h-full flex">
              {/* Left: Slide thumbnail strip */}
              <div className="w-40 border-r border-border bg-gray-50/50 overflow-y-auto p-3 flex flex-col gap-2 flex-shrink-0">
                {slides.map((slide, idx) => (
                  <button
                    key={slide.id || idx}
                    onClick={() => { setSelectedSlideIdx(idx); setChatHistory([]); }}
                    className={`
                      relative p-2 rounded-lg text-left transition-all text-xs
                      ${selectedSlideIdx === idx
                        ? 'bg-white border-2 border-[#A32020] shadow-sm'
                        : 'bg-white border border-border hover:border-gray-300'
                      }
                    `}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`
                        w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0
                        ${selectedSlideIdx === idx ? 'bg-[#A32020] text-white' : 'bg-gray-200 text-gray-600'}
                      `}>
                        {idx + 1}
                      </span>
                      <span className="font-medium text-foreground truncate text-[10px]">
                        {slide.subtitle}
                      </span>
                    </div>
                    <p className="text-[9px] text-muted-foreground line-clamp-2 pl-7">
                      {slide.headline}
                    </p>
                  </button>
                ))}
              </div>

              {/* Center: Slide preview */}
              <div className="flex-1 flex flex-col overflow-hidden">
              <div className="flex-1 overflow-auto p-4 flex items-center justify-center bg-gray-100/50">

                  {slides[selectedSlideIdx] && (
                    <div style={{ width: 960 * previewScale, height: 540 * previewScale }}>
                      <NativeSlidePreview
                        slide={slides[selectedSlideIdx]}
                        scale={previewScale}
                      />
                    </div>
                  )}
                </div>
                
                {/* Slide actions */}
                <div className="flex items-center gap-2 px-4 py-2 border-t border-border bg-surface">
                  <button
                    onClick={() => handleRegenerateSlide(selectedSlideIdx)}
                    disabled={isRegenerating}
                    className="text-xs px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors flex items-center gap-1 disabled:opacity-50"
                  >
                    <svg className={`w-3 h-3 ${isRegenerating ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Regenerate
                  </button>
                  <div className="flex-1" />
                  <Button
                    onClick={handleExport}
                    disabled={isExporting || slides.length === 0}
                    className="bg-[#A32020] hover:bg-[#7a1818] text-white text-xs px-4"
                  >
                    {isExporting ? (
                      <>
                        <svg className="w-3 h-3 animate-spin mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Exporting...
                      </>
                    ) : (
                      <>
                        <svg className="w-3 h-3 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        Export .pptx
                      </>
                    )}
                  </Button>
                </div>
              </div>

              {/* Right: Chat / Edit panel */}
              <div className="w-72 border-l border-border flex flex-col bg-surface flex-shrink-0">

                {/* Panel header with tab toggle */}
                <div className="px-4 py-3 border-b border-border">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold text-foreground">Slide {selectedSlideIdx + 1}</h4>
                  </div>
                  {/* Tab toggle */}
                  <div className="flex bg-gray-100 rounded-lg p-0.5">
                    <button
                      onClick={() => setRightPanelMode('chat')}
                      className={`flex-1 text-xs py-1.5 rounded-md font-medium transition-colors flex items-center justify-center gap-1.5 ${
                        rightPanelMode === 'chat'
                          ? 'bg-white text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                      </svg>
                      AI Chat
                    </button>
                    <button
                      onClick={() => setRightPanelMode('edit')}
                      className={`flex-1 text-xs py-1.5 rounded-md font-medium transition-colors flex items-center justify-center gap-1.5 ${
                        rightPanelMode === 'edit'
                          ? 'bg-white text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                      Manual Edit
                    </button>
                  </div>
                </div>

                {/* CHAT MODE */}
                {rightPanelMode === 'chat' && (
                  <>
                    {/* Chat history */}
                    <div className="flex-1 overflow-y-auto p-4 space-y-3">
                      {chatHistory.length === 0 && (
                        <div className="text-center text-xs text-muted-foreground py-8">
                          <p>Type an instruction to modify this slide.</p>
                          <p className="mt-2 italic">e.g., "Make the headline more concise" or "Add a fourth data point"</p>
                        </div>
                      )}
                      {chatHistory.map((msg, i) => (
                        <div
                          key={i}
                          className={`
                            text-xs px-3 py-2 rounded-lg max-w-[95%]
                            ${msg.role === 'user'
                              ? 'bg-gray-100 text-foreground ml-auto'
                              : msg.isError
                                ? 'bg-red-50 text-red-700 border border-red-200'
                                : 'bg-[#FDF2F4] text-[#2d2d2d]'
                            }
                          `}
                        >
                          {msg.text}
                        </div>
                      ))}
                      {isModifying && (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground px-3 py-2">
                          <div className="w-3 h-3 border-2 border-[#A32020] border-t-transparent rounded-full animate-spin" />
                          <span>Modifying slide...</span>
                        </div>
                      )}
                      <div ref={chatEndRef} />
                    </div>

                    {/* Chat input */}
                    <div className="p-3 border-t border-border">
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={chatInput}
                          onChange={(e) => setChatInput(e.target.value)}
                          onKeyDown={handleChatKeyDown}
                          disabled={isModifying}
                          placeholder="Modify this slide..."
                          className="flex-1 px-3 py-2 text-xs bg-background border border-border rounded-lg focus:outline-none focus:border-[#A32020] text-foreground placeholder:text-muted-foreground disabled:opacity-50"
                        />
                        <button
                          onClick={handleModifySlide}
                          disabled={!chatInput.trim() || isModifying}
                          className="px-3 py-2 bg-[#A32020] text-white rounded-lg text-xs font-medium hover:bg-[#7a1818] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  </>
                )}

                {/* EDIT MODE */}
                {rightPanelMode === 'edit' && (
                  <div className="flex-1 overflow-y-auto p-4">
                    <SlideContentEditor
                      slide={slides[selectedSlideIdx]}
                      onChange={handleManualSlideUpdate}
                    />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default PowerPointModal;
