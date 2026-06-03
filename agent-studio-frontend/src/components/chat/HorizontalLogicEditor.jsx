/**
 * HorizontalLogicEditor Component
 * 
 * Displays the presentation storyline as draggable slide title cards.
 * Supports:
 *  - Inline editing of headlines and subtitles
 *  - Drag-and-drop reordering
 *  - Add/remove slides
 *  - Layout type selector per slide
 */

import { useState, useCallback, useRef } from 'react';

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
];

const HorizontalLogicEditor = ({ horizontalLogic, onChange, disabled = false }) => {
  const [dragIdx, setDragIdx] = useState(null);
  const [dragOverIdx, setDragOverIdx] = useState(null);
  const containerRef = useRef(null);

  const slides = horizontalLogic?.slides || [];
  const deckTitle = horizontalLogic?.deck_title || '';

  // Update a single slide field
  const updateSlide = useCallback((index, field, value) => {
    const updated = [...slides];
    updated[index] = { ...updated[index], [field]: value };
    onChange({ ...horizontalLogic, slides: updated });
  }, [slides, horizontalLogic, onChange]);

  // Update deck title
  const updateDeckTitle = useCallback((value) => {
    onChange({ ...horizontalLogic, deck_title: value });
  }, [horizontalLogic, onChange]);

  // Remove a slide
  const removeSlide = useCallback((index) => {
    const updated = slides.filter((_, i) => i !== index);
    onChange({ ...horizontalLogic, slides: updated });
  }, [slides, horizontalLogic, onChange]);

  // Add a new slide
  const addSlide = useCallback(() => {
    const newSlide = {
      id: `s${Date.now()}`,
      headline: 'New slide headline (edit me)',
      subtitle: 'Topic tag',
      message: '',
      suggested_layout: 'title_content',
      rationale: null,
    };
    onChange({ ...horizontalLogic, slides: [...slides, newSlide] });
  }, [slides, horizontalLogic, onChange]);

  // Drag and drop handlers
  const handleDragStart = (e, idx) => {
    if (disabled) return;
    setDragIdx(idx);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', idx.toString());
  };

  const handleDragOver = (e, idx) => {
    e.preventDefault();
    if (dragIdx === null || dragIdx === idx) return;
    setDragOverIdx(idx);
  };

  const handleDragLeave = () => {
    setDragOverIdx(null);
  };

  const handleDrop = (e, dropIdx) => {
    e.preventDefault();
    if (dragIdx === null || dragIdx === dropIdx || disabled) return;

    const updated = [...slides];
    const [moved] = updated.splice(dragIdx, 1);
    updated.splice(dropIdx, 0, moved);
    onChange({ ...horizontalLogic, slides: updated });
    setDragIdx(null);
    setDragOverIdx(null);
  };

  const handleDragEnd = () => {
    setDragIdx(null);
    setDragOverIdx(null);
  };

  return (
    <div className="space-y-5" ref={containerRef}>
      {/* Deck title */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-foreground whitespace-nowrap">Deck Title:</label>
        <input
          type="text"
          value={deckTitle}
          onChange={(e) => updateDeckTitle(e.target.value)}
          disabled={disabled}
          className="flex-1 px-3 py-2 text-sm bg-background border border-border rounded-lg focus:outline-none focus:border-primary text-foreground disabled:opacity-50"
          placeholder="Presentation title"
        />
      </div>

      {/* Slide sorter view */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">
            Slide Sorter ({slides.length} slides)
          </h3>
          {!disabled && (
            <button
              onClick={addSlide}
              className="text-xs px-3 py-1.5 bg-gray-700 hover:bg-gray-800 text-white rounded-lg transition-colors flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
              </svg>
              Add Slide
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3">
          {slides.map((slide, idx) => (
            <div
              key={slide.id || idx}
              draggable={!disabled}
              onDragStart={(e) => handleDragStart(e, idx)}
              onDragOver={(e) => handleDragOver(e, idx)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, idx)}
              onDragEnd={handleDragEnd}
              className={`
                bg-surface border rounded-lg p-4 cursor-grab transition-all
                ${dragIdx === idx ? 'opacity-40 border-dashed border-gray-400' : ''}
                ${dragOverIdx === idx ? 'ring-2 ring-[#A32020] border-[#A32020]' : 'border-border'}
                ${disabled ? 'cursor-default opacity-75' : 'hover:shadow-md'}
              `}
            >
              <div className="flex items-start gap-3">
                {/* Slide number + drag handle */}
                <div className="flex flex-col items-center gap-1 mt-1">
                  <div className="w-8 h-8 rounded-full bg-[#A32020] text-white text-sm font-bold flex items-center justify-center flex-shrink-0">
                    {idx + 1}
                  </div>
                  {!disabled && (
                    <svg className="w-4 h-4 text-gray-300 mt-1" fill="currentColor" viewBox="0 0 20 20">
                      <path d="M7 2a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 2zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 8zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 7 14zM13 2a2 2 0 1 0 .001 4.001A2 2 0 0 0 13 2zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 13 8zm0 6a2 2 0 1 0 .001 4.001A2 2 0 0 0 13 14z" />
                    </svg>
                  )}
                </div>

                {/* Slide info */}
                <div className="flex-1 space-y-2 min-w-0">
                  {/* Headline */}
                  <textarea
                    value={slide.headline}
                    onChange={(e) => updateSlide(idx, 'headline', e.target.value)}
                    disabled={disabled}
                    rows={2}
                    className="w-full text-sm font-medium bg-transparent border-0 border-b border-transparent hover:border-border focus:border-primary focus:outline-none resize-none text-foreground disabled:bg-transparent"
                    placeholder="Headline (active sentence)"
                  />
                  
                  {/* Subtitle + Layout */}
                  <div className="flex items-center gap-3">
                    <input
                      type="text"
                      value={slide.subtitle}
                      onChange={(e) => updateSlide(idx, 'subtitle', e.target.value)}
                      disabled={disabled}
                      className="flex-1 text-xs px-2 py-1 bg-background border border-border rounded focus:outline-none focus:border-primary text-muted-foreground disabled:bg-transparent"
                      placeholder="Subtitle tag"
                    />
                    <select
                      value={slide.suggested_layout}
                      onChange={(e) => updateSlide(idx, 'suggested_layout', e.target.value)}
                      disabled={disabled}
                      className="text-xs px-2 py-1 bg-background border border-border rounded focus:outline-none focus:border-primary text-foreground disabled:bg-transparent"
                    >
                      {LAYOUT_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>

                  {/* Message / Slide brief (editable) */}
                  <textarea
                    value={slide.message || ''}
                    onChange={(e) => updateSlide(idx, 'message', e.target.value)}
                    disabled={disabled}
                    rows={2}
                    className="w-full text-xs px-2 py-1.5 bg-background border border-border rounded focus:outline-none focus:border-primary text-muted-foreground disabled:bg-transparent resize-none"
                    placeholder="Slide brief — describe what content this slide should contain..."
                  />

                  {/* Rationale (read-only) */}
                  {slide.rationale && (
                    <p className="text-xs text-muted-foreground italic mt-1">
                      {slide.rationale}
                    </p>
                  )}
                </div>

                {/* Remove button */}
                {!disabled && slides.length > 1 && (
                  <button
                    onClick={() => removeSlide(idx)}
                    className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                    title="Remove slide"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Tip */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground mt-2">
          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>
            Drag cards to reorder. Headlines should be active sentences that tell the story when read in sequence.
          </span>
        </div>
      </div>
    </div>
  );
};

export default HorizontalLogicEditor;
