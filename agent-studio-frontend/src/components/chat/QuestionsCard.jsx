/**
 * QuestionsCard — inline multi-question card rendered in the chat
 * whenever a message carries a `questions` payload (from the
 * ask_user_questions tool, hand-configured Chat.initialQuestions, or
 * Agent.startupQuestions).
 *
 * UX matches Cursor's question card:
 * - Header is always the literal "Questions" — neither the LLM nor the
 *   workflow author can override it.
 * - One question visible at a time with a `1 of N` pager.
 * - A/B/C/D… letter labels on each option, plus an empty "Other" row
 *   with a free-form input when `allow_other: true`.
 * - Up/Down arrows to move between options inside a question.
 * - `Skip (Esc)` (only when the question is not `required`) and
 *   `Continue (⏎)` between questions.
 * - Final fixed `Submit` button on the last question.
 * - No preview of later questions until the user advances.
 *
 * On submit the card calls `onSubmit(formattedSummary, structuredAnswers)`
 * which the parent uses to POST a HumanMessage back to the session
 * (with the structured payload in the request body for audit/restore).
 */

import { useEffect, useMemo, useRef, useState } from 'react';

const LETTER = (i) => String.fromCharCode(65 + i);

export default function QuestionsCard({
  payload,
  isAnswered = false,
  onSubmit,
  // When true, the card knows it's the only thing inside the bubble,
  // so it doesn't add an extra top margin (the bubble's own padding
  // already gives it breathing room).
  embedded = false,
}) {
  const questions = useMemo(
    () => Array.isArray(payload?.questions) ? payload.questions : [],
    [payload],
  );
  const totalQuestions = questions.length;
  const intro = payload?.intro;

  const [activeIdx, setActiveIdx] = useState(0);
  // answers[questionId] -> string (single_choice option id or 'text/number')
  // | string[] (multi_choice option ids) | { other: string } (custom text)
  // | null (skipped)
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);

  const containerRef = useRef(null);
  const currentQuestion = questions[activeIdx];

  // Auto-scroll into view when the active question changes — keeps the
  // current question pinned in the visible chat area as the user
  // navigates with keyboard or buttons.
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    if (typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [activeIdx]);

  // ─── Per-question answer mutation helpers ─────────────────────────
  const updateAnswer = (qid, value) => {
    setAnswers(prev => ({ ...prev, [qid]: value }));
  };

  const toggleMultiOption = (qid, optionId) => {
    setAnswers(prev => {
      const current = Array.isArray(prev[qid]) ? prev[qid] : [];
      const next = current.includes(optionId)
        ? current.filter(v => v !== optionId)
        : [...current, optionId];
      return { ...prev, [qid]: next };
    });
  };

  const setOtherForSingle = (qid, otherText) => {
    setAnswers(prev => ({ ...prev, [qid]: { other: otherText } }));
  };

  const setOtherForMulti = (qid, otherText) => {
    setAnswers(prev => {
      const current = Array.isArray(prev[qid]) ? prev[qid] : [];
      // Replace any prior `other` entry; keep all option-ids.
      const filtered = current.filter(v => !(v && typeof v === 'object' && 'other' in v));
      return {
        ...prev,
        [qid]: otherText ? [...filtered, { other: otherText }] : filtered,
      };
    });
  };

  // ─── Validation ────────────────────────────────────────────────────
  const isQuestionAnswered = (q) => {
    if (!q) return false;
    const a = answers[q.id];
    if (a === undefined || a === null) return false;
    if (q.type === 'multi_choice') {
      return Array.isArray(a) && a.length > 0;
    }
    if (typeof a === 'object' && 'other' in a) {
      return Boolean((a.other ?? '').toString().trim());
    }
    if (typeof a === 'string' || typeof a === 'number') {
      return String(a).length > 0;
    }
    if (typeof a === 'boolean') return true;
    return false;
  };

  const canContinue = (() => {
    if (!currentQuestion) return false;
    if (currentQuestion.required) return isQuestionAnswered(currentQuestion);
    return true;
  })();

  const canSkip = !currentQuestion?.required;

  const isLastQuestion = activeIdx === totalQuestions - 1;

  // ─── Navigation ────────────────────────────────────────────────────
  const goNext = () => {
    if (!canContinue) return;
    if (isLastQuestion) {
      handleSubmit();
    } else {
      setActiveIdx(i => Math.min(i + 1, totalQuestions - 1));
    }
  };

  const goPrev = () => setActiveIdx(i => Math.max(i - 1, 0));

  const skipCurrent = () => {
    if (!canSkip) return;
    updateAnswer(currentQuestion.id, null);
    if (isLastQuestion) {
      handleSubmit();
    } else {
      setActiveIdx(i => Math.min(i + 1, totalQuestions - 1));
    }
  };

  // ─── Submit ────────────────────────────────────────────────────────
  const buildDisplaySummary = () => {
    const lines = [];
    questions.forEach(q => {
      const a = answers[q.id];
      lines.push(`- ${q.prompt} → ${renderAnswerText(q, a)}`);
    });
    return lines.join('\n');
  };

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    const summary = buildDisplaySummary();
    try {
      await onSubmit?.(summary, answers);
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Keyboard handling on the card itself ──────────────────────────
  const onKeyDown = (e) => {
    if (isAnswered) return;
    // Don't hijack typing inside the "Other" input or text/number fields.
    const isInputTarget = ['INPUT', 'TEXTAREA'].includes(e.target.tagName);
    if (e.key === 'Enter' && !isInputTarget) {
      e.preventDefault();
      goNext();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      if (canSkip) skipCurrent();
    } else if (e.key === 'ArrowDown' && !isInputTarget && activeIdx < totalQuestions - 1) {
      e.preventDefault();
      setActiveIdx(i => i + 1);
    } else if (e.key === 'ArrowUp' && !isInputTarget && activeIdx > 0) {
      e.preventDefault();
      setActiveIdx(i => i - 1);
    }
  };

  // ─── Answered (collapsed) view ─────────────────────────────────────
  if (isAnswered) {
    return (
      <div className={`${embedded ? '' : 'mt-3'} flex items-center gap-2 text-xs font-medium text-emerald-400`}>
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        Answered
      </div>
    );
  }

  if (!currentQuestion) return null;

  // The card is rendered *inside* the agent message bubble. Using a
  // heavy white background + amber border made it look like a card-
  // in-a-card (see the v3 feedback screenshot). We instead use just a
  // subtle top/bottom border on the header & footer rows so the
  // questions form reads as a section of the bubble rather than a
  // nested card. Background stays transparent.
  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className={`${embedded ? '' : 'mt-3'} -mx-1 focus:outline-none`}
    >
      <Header
        currentIdx={activeIdx}
        total={totalQuestions}
        onPrev={goPrev}
        onNext={() => activeIdx < totalQuestions - 1 && setActiveIdx(activeIdx + 1)}
        canPrev={activeIdx > 0}
        canNext={activeIdx < totalQuestions - 1}
      />

      {intro && activeIdx === 0 && (
        <div className="pt-2.5 pb-1 text-xs text-white/85 leading-relaxed">{intro}</div>
      )}

      <div className="pt-2.5 pb-1 space-y-2.5">
        <div className="text-sm font-semibold text-white">
          <span className="mr-2 text-gray-400">{activeIdx + 1}.</span>
          {currentQuestion.prompt}
          {currentQuestion.required && <span className="text-red-400 ml-1">*</span>}
        </div>

        <QuestionBody
          question={currentQuestion}
          answer={answers[currentQuestion.id]}
          onPickSingle={(optionId) => updateAnswer(currentQuestion.id, optionId)}
          onToggleMulti={(optionId) => toggleMultiOption(currentQuestion.id, optionId)}
          onChangeText={(value) => updateAnswer(currentQuestion.id, value)}
          onChangeNumber={(value) => updateAnswer(currentQuestion.id, value)}
          onChangeConfirm={(value) => updateAnswer(currentQuestion.id, value)}
          onChangeOtherSingle={(value) => setOtherForSingle(currentQuestion.id, value)}
          onChangeOtherMulti={(value) => setOtherForMulti(currentQuestion.id, value)}
        />
      </div>

      <Footer
        canSkip={canSkip}
        canContinue={canContinue}
        isLastQuestion={isLastQuestion}
        submitting={submitting}
        onSkip={skipCurrent}
        onContinue={goNext}
      />
    </div>
  );
}

// ─── Header (fixed "Questions" label + pager) ──────────────────────
// Renders as a thin labelled row separated from the body by a single
// horizontal rule. No background — keeps the card from looking like a
// nested container inside the agent message bubble.
function Header({ currentIdx, total, onPrev, onNext, canPrev, canNext }) {
  return (
    <div className="flex items-center justify-between border-b border-white/10 px-1 py-1.5">
      <div className="flex items-center gap-1.5 min-w-0">
        <svg className="w-3.5 h-3.5 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span className="text-xs font-semibold text-gray-200 truncate">
          Questions
        </span>
      </div>
      <div className="flex items-center gap-1 text-[11px] text-gray-400">
        <button
          type="button"
          onClick={onPrev}
          disabled={!canPrev}
          aria-label="Previous question"
          className="p-0.5 rounded hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
          </svg>
        </button>
        <span className="font-medium tabular-nums">
          {currentIdx + 1} of {total}
        </span>
        <button
          type="button"
          onClick={onNext}
          disabled={!canNext}
          aria-label="Next question"
          className="p-0.5 rounded hover:bg-white/10 disabled:opacity-30 disabled:hover:bg-transparent"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>
    </div>
  );
}

// ─── Footer (Skip / Continue or Submit) ─────────────────────────────
// Submit button label is hardcoded — last question always says "Submit",
// intermediate questions say "Continue" so users can tell where they
// are in the flow.
function Footer({
  canSkip,
  canContinue,
  isLastQuestion,
  submitting,
  onSkip,
  onContinue,
}) {
  return (
    <div className="mt-1 flex items-center justify-end gap-2 border-t border-white/10 pt-2.5">
      {canSkip && (
        <button
          type="button"
          onClick={onSkip}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 inline-flex items-center gap-1.5 transition-colors"
        >
          Skip
          <kbd className="font-mono text-[10px] text-gray-400 border border-[#6b6b6b] rounded px-1 py-px bg-[#464646]/80">
            Esc
          </kbd>
        </button>
      )}
      <button
        type="button"
        onClick={onContinue}
        disabled={!canContinue || submitting}
        className="text-xs font-medium px-3 py-1.5 rounded-lg bg-[#d93854] text-white hover:bg-[#c52a45] disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1.5 transition-colors shadow-sm"
      >
        {submitting
          ? 'Submitting…'
          : isLastQuestion ? 'Submit' : 'Continue'}
        <kbd className="font-mono text-[10px] text-white/80 border border-white/30 rounded px-1 py-px">
          ⏎
        </kbd>
      </button>
    </div>
  );
}

// ─── Per-question body (branches on `type`) ─────────────────────────
function QuestionBody({
  question,
  answer,
  onPickSingle,
  onToggleMulti,
  onChangeText,
  onChangeNumber,
  onChangeConfirm,
  onChangeOtherSingle,
  onChangeOtherMulti,
}) {
  const otherText = (() => {
    if (question.type === 'single_choice' && answer && typeof answer === 'object' && 'other' in answer) {
      return answer.other ?? '';
    }
    if (question.type === 'multi_choice' && Array.isArray(answer)) {
      const o = answer.find(v => v && typeof v === 'object' && 'other' in v);
      return o ? (o.other ?? '') : '';
    }
    return '';
  })();

  const isOtherSelectedSingle =
    question.type === 'single_choice' && answer && typeof answer === 'object' && 'other' in answer;

  switch (question.type) {
    case 'single_choice':
    case 'multi_choice': {
      const isMulti = question.type === 'multi_choice';
      return (
        <div className="space-y-1.5">
          {(question.options || []).map((opt, i) => {
            const isActive = isMulti
              ? Array.isArray(answer) && answer.includes(opt.id)
              : answer === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => isMulti ? onToggleMulti(opt.id) : onPickSingle(opt.id)}
                className={`flex w-full items-center gap-3 rounded-lg border border-transparent bg-white/5 px-3 py-2 text-left text-sm text-white transition-colors ${
                  isActive
                    ? 'bg-amber-500/15 text-white ring-1 ring-amber-400/50'
                    : 'hover:bg-white/10'
                }`}
              >
                <LetterBadge letter={LETTER(i)} active={isActive} />
                <span className="flex-1 truncate">{opt.label}</span>
                {opt.description && (
                  <span className="text-[11px] text-gray-400 truncate ml-2">{opt.description}</span>
                )}
              </button>
            );
          })}

          {/* The free-form "Other" row — exactly mirrors the empty 'E' row
              in the Cursor screenshot. Lets the user type their own
              answer instead of (or alongside, for multi_choice) picking
              one of the canned options. */}
          {question.allow_other && (
            <div
              className={`flex items-center gap-3 rounded-lg border border-transparent bg-white/5 px-3 py-2 transition-colors ${
                isOtherSelectedSingle || (isMulti && otherText)
                  ? 'bg-amber-500/15 ring-1 ring-amber-400/50'
                  : ''
              }`}
            >
              <LetterBadge
                letter={LETTER((question.options || []).length)}
                active={isOtherSelectedSingle || (isMulti && Boolean(otherText))}
              />
              <input
                type="text"
                value={otherText}
                onChange={(e) =>
                  isMulti
                    ? onChangeOtherMulti(e.target.value)
                    : onChangeOtherSingle(e.target.value)
                }
                placeholder={question.other_placeholder || 'Or type your own answer…'}
                className="flex-1 bg-transparent text-sm text-white placeholder:text-gray-500 focus:outline-none"
              />
            </div>
          )}
        </div>
      );
    }

    case 'text':
      return (
        <input
          type="text"
          autoFocus
          value={typeof answer === 'string' ? answer : ''}
          onChange={(e) => onChangeText(e.target.value)}
          placeholder={question.placeholder || 'Type your answer…'}
          className="w-full px-3 py-2 text-sm border border-[#6b6b6b] rounded-lg bg-[#464646] text-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50"
        />
      );

    case 'number':
      return (
        <input
          type="number"
          autoFocus
          value={(typeof answer === 'number' || typeof answer === 'string') ? answer : ''}
          onChange={(e) => {
            const v = e.target.value;
            onChangeNumber(v === '' ? '' : Number(v));
          }}
          placeholder={question.placeholder || 'Enter a number…'}
          className="w-full px-3 py-2 text-sm border border-[#6b6b6b] rounded-lg bg-[#464646] text-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 focus:border-amber-500/50"
        />
      );

    case 'confirm':
      return (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onChangeConfirm(true)}
            className={`flex-1 px-3 py-2 text-sm rounded-lg border transition-colors ${
              answer === true
                ? 'border-emerald-400 bg-emerald-500/20 text-emerald-100'
                : 'border-[#6b6b6b] hover:border-[#8a8a8a] bg-[#464646] text-white hover:bg-[#525252]'
            }`}
          >
            Yes
          </button>
          <button
            type="button"
            onClick={() => onChangeConfirm(false)}
            className={`flex-1 px-3 py-2 text-sm rounded-lg border transition-colors ${
              answer === false
                ? 'border-rose-400 bg-rose-500/20 text-rose-100'
                : 'border-[#6b6b6b] hover:border-[#8a8a8a] bg-[#464646] text-white hover:bg-[#525252]'
            }`}
          >
            No
          </button>
        </div>
      );

    default:
      return (
        <div className="text-xs text-gray-400 italic">
          Unsupported question type: {question.type}
        </div>
      );
  }
}

function LetterBadge({ letter, active }) {
  return (
    <span
      className={`inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-mono font-semibold shrink-0 ${
        active
          ? 'bg-amber-500 text-white'
          : 'bg-[#3a3a3a] text-gray-300 border border-[#6b6b6b]/80'
      }`}
    >
      {letter}
    </span>
  );
}

// ─── Local renderer used to build the submitted-message summary ──────
// Mirrors backend `format_user_answer_message` so the bubble shown in
// chat looks the same regardless of who built the string.
function renderAnswerText(question, answer) {
  if (answer === undefined || answer === null) return '(skipped)';
  const optionsById = Object.fromEntries(
    (question.options || []).map(o => [o.id, o.label]),
  );

  if (Array.isArray(answer)) {
    if (answer.length === 0) return '(skipped)';
    return answer
      .map(a => {
        if (a && typeof a === 'object' && 'other' in a) {
          return `${a.other} (custom)`;
        }
        return optionsById[a] ?? String(a);
      })
      .join(', ');
  }

  if (answer && typeof answer === 'object' && 'other' in answer) {
    return `${answer.other} (custom)`;
  }

  if (typeof answer === 'boolean') return answer ? 'Yes' : 'No';

  return optionsById[answer] ?? String(answer);
}
