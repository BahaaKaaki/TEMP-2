/**
 * QuestionsBuilderModal — full-screen tab for editing the questions
 * payload stored on Chat.initialQuestions / Agent.startupQuestions.
 *
 * Opens when the workflow author flips the "Initial / Startup" toggle to
 * "Questionnaire" and clicks the preview card from DynamicConfigField.
 * Saves on close (we keep a local draft so the user can cancel without
 * losing the previous payload). The card layout deliberately mirrors
 * what the runtime QuestionsCard renders so workflow authors can
 * preview their questionnaire as they build it.
 *
 * Stored payload shape (matches ask_user_questions Pydantic schema):
 *   {
 *     intro?: string,
 *     questions: [
 *       {
 *         id, prompt,
 *         type: 'single_choice'|'multi_choice'|'text'|'number'|'confirm',
 *         options?: [{ id, label, description? }],
 *         allow_other?, other_placeholder?,
 *         required?, placeholder?
 *       }
 *     ]
 *   }
 *
 * NOTE: there is intentionally no `title` or `submit_label` — the chat
 * card always renders with the literal "Questions" header and a fixed
 * "Submit" button so we don't expose those as configurable here.
 */

import { useEffect, useMemo, useState } from 'react';

const QUESTION_TYPES = [
  { value: 'single_choice', label: 'Single choice' },
  { value: 'multi_choice', label: 'Multi choice' },
  { value: 'text', label: 'Free text' },
  { value: 'number', label: 'Number' },
  { value: 'confirm', label: 'Yes / No' },
];

const optionTypeNeedsOptions = (t) => t === 'single_choice' || t === 'multi_choice';

const blankQuestion = (idx) => ({
  id: `q_${idx + 1}`,
  prompt: '',
  type: 'single_choice',
  options: [
    { id: 'opt_1', label: '' },
    { id: 'opt_2', label: '' },
  ],
  allow_other: true,
  required: false,
});

export default function QuestionsBuilderModal({
  isOpen,
  onClose,
  value,
  onSave,
  fieldLabel,
  contextLabel,
}) {
  // Local draft so cancelling discards changes.  We re-seed every time
  // the modal opens with whatever value the parent has cached.
  const seed = useMemo(() => normalizeIncoming(value), [value]);
  const [draft, setDraft] = useState(seed);
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    if (isOpen) {
      setDraft(normalizeIncoming(value));
      setActiveIdx(0);
    }
  }, [isOpen, value]);

  if (!isOpen) return null;

  const questions = draft.questions || [];

  // ── Mutation helpers ────────────────────────────────────────────
  const setQuestions = (next) =>
    setDraft((prev) => ({ ...prev, questions: next }));
  const setIntro = (intro) =>
    setDraft((prev) => ({ ...prev, intro }));

  const updateQuestion = (idx, patch) => {
    setQuestions(questions.map((q, i) => (i === idx ? { ...q, ...patch } : q)));
  };
  const removeQuestion = (idx) => {
    const next = questions.filter((_, i) => i !== idx);
    setQuestions(next);
    setActiveIdx((cur) => Math.max(0, Math.min(cur, next.length - 1)));
  };
  const addQuestion = () => {
    const next = [...questions, blankQuestion(questions.length)];
    setQuestions(next);
    setActiveIdx(next.length - 1);
  };
  const moveQuestion = (idx, delta) => {
    const target = idx + delta;
    if (target < 0 || target >= questions.length) return;
    const next = [...questions];
    [next[idx], next[target]] = [next[target], next[idx]];
    setQuestions(next);
    setActiveIdx(target);
  };

  const updateOption = (qIdx, oIdx, patch) => {
    const opts = [...(questions[qIdx].options || [])];
    opts[oIdx] = { ...opts[oIdx], ...patch };
    updateQuestion(qIdx, { options: opts });
  };
  const removeOption = (qIdx, oIdx) => {
    const opts = (questions[qIdx].options || []).filter((_, i) => i !== oIdx);
    updateQuestion(qIdx, { options: opts });
  };
  const addOption = (qIdx) => {
    const opts = questions[qIdx].options || [];
    const nextId = `opt_${opts.length + 1}`;
    updateQuestion(qIdx, { options: [...opts, { id: nextId, label: '' }] });
  };

  // ── Save / cancel ───────────────────────────────────────────────
  const handleSave = () => {
    const sanitized = sanitizeForSave(draft);
    onSave?.(sanitized);
    onClose?.();
  };
  const handleCancel = () => {
    onClose?.();
  };

  const activeQuestion = questions[activeIdx];

  return (
    <div data-theme="apex-dark" className="fixed inset-0 z-50 flex bg-black/60">
      <div className="flex flex-col w-full h-full" style={{ background: '#141414' }}>

        {/* ── Title bar ───────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-white border-b border-gray-200 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <svg className="w-4 h-4 text-amber-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="text-sm font-medium text-gray-800 truncate">
              {fieldLabel || 'Questionnaire'}
            </span>
            {contextLabel && (
              <span className="text-xs text-gray-500 truncate">
                · {contextLabel}
              </span>
            )}
            <span className="text-xs text-gray-400 ml-2">
              {questions.length} {questions.length === 1 ? 'question' : 'questions'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={addQuestion}
              className="px-3 py-1.5 text-xs font-medium rounded border border-amber-300 text-amber-700 hover:bg-amber-50 inline-flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
              </svg>
              Add question
            </button>
            <button
              type="button"
              onClick={handleCancel}
              className="px-3 py-1.5 text-xs rounded border border-gray-200 text-gray-600 hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="px-3 py-1.5 text-xs font-medium rounded bg-gray-900 text-white hover:bg-gray-800"
            >
              Save questionnaire
            </button>
          </div>
        </div>

        {/* ── Body: list (left) | editor (center) | preview (right) ─ */}
        <div className="flex flex-1 min-h-0">

          {/* List of questions — Add button anchored at the TOP for
              quick access. The list scrolls below it. */}
          <div className="w-72 shrink-0 border-r border-gray-200 bg-white flex flex-col">
            <div className="px-3 pt-3 pb-2 border-b border-gray-100 bg-white">
              <button
                type="button"
                onClick={addQuestion}
                className="w-full text-xs font-semibold px-2.5 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 inline-flex items-center justify-center gap-1.5 shadow-xs transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                </svg>
                Add question
              </button>
              <div className="flex items-center justify-between mt-2 px-0.5">
                <span className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">
                  Questions
                </span>
                <span className="text-[10px] text-gray-400 tabular-nums">
                  {questions.length}
                </span>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto py-1">
              {questions.length === 0 && (
                <div className="px-3 py-6 text-xs text-gray-400 text-center">
                  No questions yet. Click <span className="font-medium text-gray-500">Add question</span> above to start.
                </div>
              )}
              {questions.map((q, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setActiveIdx(i)}
                  className={`w-full text-left px-3 py-2 border-l-2 flex items-start gap-2 group ${
                    i === activeIdx
                      ? 'border-amber-500 bg-amber-50/50'
                      : 'border-transparent hover:bg-gray-50'
                  }`}
                >
                  <span className="text-[10px] font-mono text-gray-400 mt-0.5 shrink-0 w-5">
                    {i + 1}.
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-xs text-gray-800 truncate">
                      {q.prompt || <span className="text-gray-400 italic">Untitled</span>}
                    </span>
                    <span className="block text-[10px] text-gray-400 truncate mt-0.5">
                      {QUESTION_TYPES.find((t) => t.value === q.type)?.label || q.type}
                      {q.required && ' · required'}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Editor for the active question */}
          <div className="flex-1 min-w-0 overflow-y-auto">
            <div className="max-w-3xl mx-auto p-6 space-y-6">

              {/* Card-level intro (not title — title is fixed to "Questions") */}
              <section className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="text-xs font-semibold text-gray-700 mb-1">
                  Card intro <span className="text-gray-400 font-normal">(optional)</span>
                </div>
                <textarea
                  rows={2}
                  value={draft.intro || ''}
                  onChange={(e) => setIntro(e.target.value)}
                  placeholder="One or two sentences shown above the first question — e.g. 'Quick check before we begin…'"
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-amber-300 focus:border-transparent resize-none"
                />
                <p className="mt-2 text-[11px] text-gray-500">
                  The card header itself is always "Questions" and the final
                  button is always "Submit" — both are fixed to keep the chat
                  experience consistent.
                </p>
              </section>

              {/* Active question editor */}
              {activeQuestion ? (
                <section className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-gray-400 shrink-0">
                      Q{activeIdx + 1}
                    </span>
                    <input
                      className="w-32 px-2 py-1.5 text-[11px] border border-gray-200 rounded font-mono focus:outline-none focus:ring-1 focus:ring-amber-300"
                      placeholder="question_id"
                      value={activeQuestion.id || ''}
                      onChange={(e) => updateQuestion(activeIdx, { id: e.target.value })}
                    />
                    <select
                      className="px-2 py-1.5 text-xs border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-amber-300"
                      value={activeQuestion.type || 'single_choice'}
                      onChange={(e) => updateQuestion(activeIdx, { type: e.target.value })}
                    >
                      {QUESTION_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                    <div className="ml-auto flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => moveQuestion(activeIdx, -1)}
                        disabled={activeIdx === 0}
                        title="Move up"
                        className="p-1 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded disabled:opacity-30"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" /></svg>
                      </button>
                      <button
                        type="button"
                        onClick={() => moveQuestion(activeIdx, 1)}
                        disabled={activeIdx === questions.length - 1}
                        title="Move down"
                        className="p-1 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded disabled:opacity-30"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
                      </button>
                      <button
                        type="button"
                        onClick={() => removeQuestion(activeIdx)}
                        title="Delete question"
                        className="p-1 text-red-500 hover:text-red-700 hover:bg-red-50 rounded"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M1 7h22M9 7V4a2 2 0 012-2h2a2 2 0 012 2v3" /></svg>
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Question prompt
                    </label>
                    <input
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-amber-300 focus:border-transparent"
                      placeholder="What's your favorite color?"
                      value={activeQuestion.prompt || ''}
                      onChange={(e) => updateQuestion(activeIdx, { prompt: e.target.value })}
                    />
                  </div>

                  {optionTypeNeedsOptions(activeQuestion.type) && (
                    <div>
                      <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                        Options
                      </label>
                      <div className="space-y-1.5">
                        {(activeQuestion.options || []).map((opt, oIdx) => (
                          <div key={oIdx} className="flex items-center gap-2">
                            <span className="text-[10px] font-mono text-gray-400 w-4 shrink-0 text-right">
                              {String.fromCharCode(65 + oIdx)}
                            </span>
                            <input
                              className="w-24 px-2 py-1.5 text-[11px] border border-gray-200 rounded font-mono focus:outline-none focus:ring-1 focus:ring-amber-300"
                              placeholder="option_id"
                              value={opt.id || ''}
                              onChange={(e) => updateOption(activeIdx, oIdx, { id: e.target.value })}
                            />
                            <input
                              className="flex-1 px-2 py-1.5 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-amber-300"
                              placeholder="Option label shown to the user"
                              value={opt.label || ''}
                              onChange={(e) => updateOption(activeIdx, oIdx, { label: e.target.value })}
                            />
                            <button
                              type="button"
                              onClick={() => removeOption(activeIdx, oIdx)}
                              className="p-1 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                              title="Remove option"
                            >
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                            </button>
                          </div>
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => addOption(activeIdx)}
                        className="mt-2 text-xs font-medium text-indigo-600 hover:text-indigo-800"
                      >
                        + Add option
                      </button>
                    </div>
                  )}

                  {(activeQuestion.type === 'text' || activeQuestion.type === 'number') && (
                    <div>
                      <label className="block text-xs font-semibold text-gray-700 mb-1">
                        Placeholder
                      </label>
                      <input
                        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-amber-300 focus:border-transparent"
                        placeholder={activeQuestion.type === 'number' ? 'Enter a number…' : 'Type your answer…'}
                        value={activeQuestion.placeholder || ''}
                        onChange={(e) => updateQuestion(activeIdx, { placeholder: e.target.value })}
                      />
                    </div>
                  )}

                  <div className="flex flex-wrap gap-4 pt-2 border-t border-gray-100">
                    {optionTypeNeedsOptions(activeQuestion.type) && (
                      <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={!!activeQuestion.allow_other}
                          onChange={(e) => updateQuestion(activeIdx, { allow_other: e.target.checked })}
                        />
                        Allow custom "Other" answer
                      </label>
                    )}
                    <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!activeQuestion.required}
                        onChange={(e) => updateQuestion(activeIdx, { required: e.target.checked })}
                      />
                      Required <span className="text-gray-400">(no Skip button)</span>
                    </label>
                  </div>

                  {optionTypeNeedsOptions(activeQuestion.type) && activeQuestion.allow_other && (
                    <div>
                      <label className="block text-xs font-semibold text-gray-700 mb-1">
                        "Other" placeholder
                      </label>
                      <input
                        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-amber-300 focus:border-transparent"
                        placeholder="Or type your own answer…"
                        value={activeQuestion.other_placeholder || ''}
                        onChange={(e) => updateQuestion(activeIdx, { other_placeholder: e.target.value })}
                      />
                    </div>
                  )}
                </section>
              ) : (
                <div className="flex flex-col items-center justify-center text-center py-16 gap-3">
                  <div className="text-sm text-gray-500">
                    No questions yet.
                  </div>
                  <button
                    type="button"
                    onClick={addQuestion}
                    className="px-4 py-2 text-xs font-semibold rounded-lg bg-amber-500 text-white hover:bg-amber-600 inline-flex items-center gap-1.5 shadow-xs"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                    </svg>
                    Add your first question
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Live preview */}
          <div className="w-96 shrink-0 border-l border-gray-200 bg-gray-50 overflow-y-auto">
            <div className="px-3 py-2 text-[11px] uppercase tracking-wide text-gray-500 border-b border-gray-200 bg-white">
              Live preview
            </div>
            <div className="p-4">
              <PreviewCard payload={draft} activeIdx={activeIdx} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Read-only preview that mirrors QuestionsCard rendering ─────────
// We deliberately don't import QuestionsCard here because it ships
// keyboard handlers / submit logic that we don't want firing inside
// the builder.  This is a lightweight visual preview only.
function PreviewCard({ payload, activeIdx }) {
  const questions = payload?.questions || [];
  const q = questions[activeIdx] || questions[0];
  const total = questions.length || 1;
  const idx = Math.min(activeIdx, total - 1);

  if (!q) {
    return (
      <div className="rounded-xl border border-amber-200 bg-white shadow-sm p-6 text-center text-xs text-gray-400">
        Add a question to see the preview.
      </div>
    );
  }

  const isLast = idx === total - 1;
  const canSkip = !q.required;

  return (
    <div className="rounded-xl border border-amber-200 bg-white shadow-sm">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-amber-100 bg-amber-50/40 rounded-t-xl">
        <div className="flex items-center gap-2 min-w-0">
          <svg className="w-3.5 h-3.5 text-amber-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-xs font-semibold text-gray-700">Questions</span>
        </div>
        <span className="text-[11px] text-gray-500 tabular-nums font-medium">
          {idx + 1} of {total}
        </span>
      </div>

      {payload.intro && idx === 0 && (
        <div className="px-4 pt-3 text-xs text-gray-600">{payload.intro}</div>
      )}

      <div className="px-4 py-3 space-y-3">
        <div className="text-sm font-semibold text-gray-900">
          <span className="mr-2 text-gray-400">{idx + 1}.</span>
          {q.prompt || <span className="text-gray-400 italic">Untitled question</span>}
          {q.required && <span className="text-red-500 ml-1">*</span>}
        </div>

        {(q.type === 'single_choice' || q.type === 'multi_choice') && (
          <div className="space-y-1.5">
            {(q.options || []).map((opt, i) => (
              <div
                key={i}
                className="w-full px-3 py-2 rounded-lg border text-sm flex items-center gap-3 border-gray-200 bg-white text-gray-700"
              >
                <span className="inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-mono font-semibold bg-gray-100 text-gray-500">
                  {String.fromCharCode(65 + i)}
                </span>
                <span className="flex-1 truncate">
                  {opt.label || <span className="text-gray-400 italic">Empty option</span>}
                </span>
              </div>
            ))}
            {q.allow_other && (
              <div className="flex items-center gap-3 px-3 py-2 rounded-lg border border-gray-200 bg-white">
                <span className="inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-mono font-semibold bg-gray-100 text-gray-500">
                  {String.fromCharCode(65 + (q.options?.length || 0))}
                </span>
                <span className="flex-1 text-sm text-gray-400 italic">
                  {q.other_placeholder || 'Or type your own answer…'}
                </span>
              </div>
            )}
          </div>
        )}

        {q.type === 'text' && (
          <div className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg text-gray-400 italic">
            {q.placeholder || 'Type your answer…'}
          </div>
        )}
        {q.type === 'number' && (
          <div className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg text-gray-400 italic">
            {q.placeholder || 'Enter a number…'}
          </div>
        )}
        {q.type === 'confirm' && (
          <div className="flex gap-2">
            <div className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 text-gray-700 text-center">Yes</div>
            <div className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 text-gray-700 text-center">No</div>
          </div>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 px-4 py-2.5 border-t border-amber-100 bg-gray-50/60 rounded-b-xl">
        {canSkip && (
          <span className="text-xs text-gray-500 px-2 py-1">Skip</span>
        )}
        <span className="text-xs font-medium px-3 py-1.5 rounded-lg bg-amber-500 text-white">
          {isLast ? 'Submit' : 'Continue'}
        </span>
      </div>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────
function normalizeIncoming(value) {
  if (!value) return { intro: '', questions: [] };
  if (Array.isArray(value)) return { intro: '', questions: value };
  if (typeof value !== 'object') return { intro: '', questions: [] };
  return {
    intro: value.intro || '',
    questions: Array.isArray(value.questions) ? value.questions : [],
  };
}

function sanitizeForSave(draft) {
  // Strip any legacy fields that older saved payloads might still carry
  // (title / submit_label / per-question skippable) so the value stored
  // on the node config matches the simplified backend schema.
  const out = {};
  if (draft.intro && draft.intro.trim()) {
    out.intro = draft.intro.trim();
  }
  out.questions = (draft.questions || []).map((q) => {
    const clean = { ...q };
    delete clean.skippable;
    return clean;
  });
  return out;
}
