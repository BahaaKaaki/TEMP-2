"""
ask_user_questions tool — pause an agent to ask the user a short series
of questions, each with optional fixed-choice options and an optional
free-form "Other" row.

Mirrors the existing pattern used by the code-executor's ``output.ask`` /
``output.selection`` SDK calls and the ``submit_deliverable`` tool: the
tool is a *pause primitive*, not a real side-effecting tool.  The
standard agent executor intercepts the tool call by name BEFORE
executing it, lifts the args onto the AIMessage's ``additional_kwargs``
under the ``questions`` key, and returns ``interrupted=True`` so the
workflow pauses for user input.

When the user submits their answers via the normal chat input (the
QuestionsCard widget posts a HumanMessage with a formatted summary),
the workflow resumes and the LLM sees the answers in its message
history.  No special endpoint is needed.

The tool is auto-injected by the agent node when:
- ``agentMode == "chat"`` (chat-style agents always need it), or
- ``enableUserQuestions == True`` is set on the node, or
- ``waitForUserInput == True`` (the "I want a startup pause" flag — the
  agent is already meant to ask things)

The Pydantic schema is what the LLM sees via ``bind_tools``, so it acts
as the source of truth for the payload shape across the whole stack.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Type

from pydantic import BaseModel, Field, field_validator, model_validator
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# Enforced on every single_choice / multi_choice question (UI + answers).
I_DONT_KNOW_OPTION_ID = "i_dont_know"
I_DONT_KNOW_OPTION_LABEL = "I don't know"
DEFAULT_OTHER_PLACEHOLDER = "Or type your own answer…"
_MAX_EXTRACTED_OPTIONS = 8

# Parenthetical / inline lists the LLM often leaves on type='text' questions.
_OPTION_LIST_PATTERNS = (
    re.compile(r"\([Ff]or example:\s*([^)]+)\)"),
    re.compile(r"\([Ee]\.g\.?\s*([^)]+)\)"),
    re.compile(
        r"(?:\b(?:such as|including|like|e\.g\.)\s*:?\s*)"
        r"([^.!?\n]+(?:,\s*[^.!?\n]+)+)",
        re.IGNORECASE,
    ),
)

# Option ids the LLM often invents — UI already provides custom input + I don't know.
_REDUNDANT_OPTION_IDS = frozenset({
    "other",
    "something_else",
    "something-else",
    "custom",
    "custom_answer",
    "none_of_the_above",
    "none",
    "not_sure",
    "not_sure_yet",
    "unsure",
    "idk",
    "dont_know",
    "don_t_know",
    I_DONT_KNOW_OPTION_ID,
})

# Labels that duplicate the enforced "Other" row or "I don't know" option.
_REDUNDANT_OPTION_LABEL_PATTERNS = (
    re.compile(r"^(?:or\s+)?something\s+else\b", re.IGNORECASE),
    re.compile(r"^something\s+different\b", re.IGNORECASE),
    re.compile(r"^other(?:\s*\(.*\))?\s*$", re.IGNORECASE),
    re.compile(r"^none\s+of\s+(?:the\s+)?above", re.IGNORECASE),
    re.compile(r"^not\s+(?:listed|applicable|sure)\b", re.IGNORECASE),
    re.compile(r"^(?:please\s+)?specify\b", re.IGNORECASE),
    re.compile(r"^custom(?:\s+answer)?\s*$", re.IGNORECASE),
    re.compile(r"^type\s+your\s+own\b", re.IGNORECASE),
    re.compile(r"^enter\s+your\s+own\b", re.IGNORECASE),
    re.compile(r"^write\s+in\b", re.IGNORECASE),
    re.compile(
        r"^i\s+(?:do\s+not|don'?t)\s+know\b", re.IGNORECASE,
    ),
    re.compile(r"^(?:not\s+)?unsure\s*$", re.IGNORECASE),
)


def _is_redundant_mcq_option(label: str, option_id: str) -> bool:
    """True when this option duplicates UI-provided Other / I don't know."""
    oid = (option_id or "").strip().lower().replace("-", "_")
    if oid in _REDUNDANT_OPTION_IDS:
        return True

    text = (label or "").strip()
    if not text:
        return True

    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if normalized in {
        "other",
        "something else",
        "something else?",
        "or something else",
        "or something else?",
        "custom",
        "n/a",
        "na",
        "not sure",
        "unsure",
        "idk",
        "i don't know",
        "i dont know",
        "don't know",
        "dont know",
    }:
        return True

    for pattern in _REDUNDANT_OPTION_LABEL_PATTERNS:
        if pattern.search(normalized):
            return True
    return False


def _strip_redundant_mcq_options(
    options: List[QuestionOption],
    *,
    question_id: str = "",
) -> List[QuestionOption]:
    kept: List[QuestionOption] = []
    for opt in options or []:
        if _is_redundant_mcq_option(opt.label, opt.id):
            logger.debug(
                "ask_user_questions: dropped redundant option for '%s': "
                "id=%s label=%r",
                question_id or "?",
                opt.id,
                opt.label,
            )
            continue
        kept.append(opt)
    return kept


def _slug_option_id(label: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:48]
    return slug or f"option_{index + 1}"


def _parse_option_labels(raw: str) -> List[str]:
    """Split a comma/semicolon list into discrete option labels."""
    text = (raw or "").strip()
    text = re.sub(r"\s+etc\.?\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+and so on\s*$", "", text, flags=re.IGNORECASE)
    parts = re.split(r"[,;]\s*|\s+/\s+", text)
    labels: List[str] = []
    for part in parts:
        item = part.strip().strip(".")
        if not item or len(item) < 2:
            continue
        if len(item) > 120:
            item = item[:120].rstrip()
        labels.append(item)
    return labels[:_MAX_EXTRACTED_OPTIONS]


def _extract_mcq_from_prompt(prompt: str) -> Optional[Tuple[str, List[str]]]:
    """If *prompt* embeds a pick-list, return (cleaned_prompt, option_labels)."""
    for pattern in _OPTION_LIST_PATTERNS:
        match = pattern.search(prompt)
        if not match:
            continue
        labels = _parse_option_labels(match.group(1))
        if len(labels) < 2:
            continue
        cleaned = (prompt[: match.start()] + prompt[match.end() :]).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([?.!])", r"\1", cleaned)
        return cleaned, labels
    return None


def _ensure_mcq_standards(question: "Question") -> "Question":
    """MCQ questions always offer 'I don't know' plus a custom text row."""
    if question.type not in ("single_choice", "multi_choice"):
        return question

    options = _strip_redundant_mcq_options(
        list(question.options or []),
        question_id=question.id,
    )
    seen_ids = {o.id for o in options}

    if I_DONT_KNOW_OPTION_ID not in seen_ids:
        options.append(
            QuestionOption(
                id=I_DONT_KNOW_OPTION_ID,
                label=I_DONT_KNOW_OPTION_LABEL,
            )
        )
        seen_ids.add(I_DONT_KNOW_OPTION_ID)

    updates: Dict[str, Any] = {"options": options, "allow_other": True}
    if not question.other_placeholder:
        updates["other_placeholder"] = DEFAULT_OTHER_PLACEHOLDER
    return question.model_copy(update=updates)


def _promote_text_to_mcq_if_possible(question: "Question") -> "Question":
    if question.type != "text":
        return question
    if question.options:
        return question

    extracted = _extract_mcq_from_prompt(question.prompt)
    if not extracted:
        return question

    cleaned_prompt, labels = extracted
    options = [
        QuestionOption(id=_slug_option_id(label, i), label=label)
        for i, label in enumerate(labels)
        if not _is_redundant_mcq_option(label, _slug_option_id(label, i))
    ]
    if len(options) < 2:
        return question
    logger.debug(
        "Promoted question '%s' from text to single_choice (%d options)",
        question.id,
        len(options),
    )
    return question.model_copy(
        update={
            "type": "single_choice",
            "prompt": cleaned_prompt,
            "options": options,
        }
    )


# ---------------------------------------------------------------------------
# Pydantic models — shared payload shape between the LLM tool args, the
# hand-configured node fields (Agent.startupQuestions / Chat.initialQuestions),
# and the frontend QuestionsCard.  ``model_dump()`` of these is exactly the
# JSON we put on additional_kwargs.questions and ship to the UI.
# ---------------------------------------------------------------------------


class QuestionOption(BaseModel):
    """One pickable option on a question."""

    id: str = Field(
        ...,
        min_length=1,
        description="Stable identifier for this option, returned in the answer payload.",
    )
    label: str = Field(
        ...,
        min_length=1,
        description="What the user sees on the option button.",
    )
    description: Optional[str] = Field(
        None,
        description="Optional helper text rendered under the option label.",
    )


class Question(BaseModel):
    """One question in the questionnaire.

    The user can always skip a question that is not ``required`` — there
    is no separate 'skippable' flag.  ``required`` is the single source
    of truth: required questions block Continue/Submit, non-required
    questions show a Skip button.
    """

    id: str = Field(
        ...,
        min_length=1,
        description="Stable identifier for this question, used as the key in the answer payload.",
    )
    prompt: str = Field(
        ...,
        min_length=1,
        description="The question text shown to the user. Must be non-empty.",
    )
    type: Literal["single_choice", "multi_choice", "text", "number", "confirm"] = Field(
        "single_choice",
        description=(
            "Render style: 'single_choice' = one-pick radio cards (preferred "
            "whenever the user can pick from known options); "
            "'multi_choice' = checkboxes when several answers may apply; "
            "'text' = free-form ONLY when no reasonable option list exists; "
            "'number' = numeric input; "
            "'confirm' = yes/no toggle. "
            "Every single_choice/multi_choice question automatically includes "
            "'I don't know' and a custom-answer row in the UI."
        ),
    )
    options: List[QuestionOption] = Field(
        default_factory=list,
        description=(
            "List of pickable options. REQUIRED for 'single_choice' and "
            "'multi_choice' (provide at least 2 options, or 1 option plus "
            "allow_other=true). Ignored for 'text', 'number', and 'confirm'."
        ),
    )
    allow_other: bool = Field(
        False,
        description=(
            "When true, render an extra free-form input row below the options "
            "so the user can type their own answer instead of picking one."
        ),
    )
    other_placeholder: Optional[str] = Field(
        None,
        description="Placeholder text for the 'Other' free-form input.",
    )
    required: bool = Field(
        False,
        description=(
            "When true, the user cannot continue without answering this question. "
            "When false, a Skip button is shown."
        ),
    )
    placeholder: Optional[str] = Field(
        None,
        description="Placeholder text for 'text' / 'number' inputs.",
    )

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, v: str) -> str:
        # ``min_length=1`` lets a single space through; reject pure
        # whitespace too so the LLM can't ship a blank question.
        if not v or not v.strip():
            raise ValueError("question prompt must contain non-whitespace text")
        return v.strip()

    @model_validator(mode="after")
    def _normalize_question_ux(self) -> "Question":
        """Promote embedded option lists to MCQ; enforce standard MCQ rows."""
        q = _promote_text_to_mcq_if_possible(self)
        q = _ensure_mcq_standards(q)
        return q._validate_choice_questions()

    def _validate_choice_questions(self) -> "Question":
        # Single/multi choice need real options. We allow a degenerate
        # 1-option-plus-Other variant because that's a legitimate "pick
        # this preset OR type your own" UX.
        if self.type in ("single_choice", "multi_choice"):
            opt_count = len(self.options or [])
            if opt_count == 0 and not self.allow_other:
                raise ValueError(
                    f"question '{self.id}' has type='{self.type}' but no options "
                    f"and allow_other=false. Provide at least 2 options, or "
                    f"1 option with allow_other=true."
                )
            if opt_count == 1 and not self.allow_other:
                raise ValueError(
                    f"question '{self.id}' has only 1 option for type='{self.type}'. "
                    f"Add another option, or set allow_other=true to let the user "
                    f"type their own answer."
                )
            # Option ids must be unique within a question so the answer
            # payload doesn't collide on submission.
            seen: set = set()
            for opt in self.options:
                if opt.id in seen:
                    raise ValueError(
                        f"question '{self.id}' has duplicate option id '{opt.id}'. "
                        f"Each option id must be unique within a question."
                    )
                seen.add(opt.id)
        return self


class AskUserQuestionsInput(BaseModel):
    """Top-level payload — what the LLM emits when calling the tool.

    The card always renders with a fixed 'Questions' header and a fixed
    'Submit' button label, so the LLM doesn't get to override either.
    Only the optional ``intro`` (1-2 sentence framing) and the
    ``questions`` list are configurable.
    """

    intro: Optional[str] = Field(
        None,
        description=(
            "Optional 1-2 sentence intro rendered above the first question. "
            "Use this to give the user context for why you're asking."
        ),
    )
    questions: List[Question] = Field(
        ...,
        min_length=1,
        max_length=10,
        description=(
            "The list of questions to ask, 1–10 items. Order is preserved "
            "in the UI. Each question's ``id`` must be unique."
        ),
    )

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "AskUserQuestionsInput":
        # Question ids become the keys in the answer payload — duplicates
        # would silently clobber answers, so reject them up front and
        # let the LLM's recovery path retry with corrected ids.
        seen: set = set()
        for q in self.questions:
            if q.id in seen:
                raise ValueError(
                    f"duplicate question id '{q.id}'. Each question's id must "
                    f"be unique across the questionnaire."
                )
            seen.add(q.id)
        return self


# ---------------------------------------------------------------------------
# The tool itself.  Note: the standard executor intercepts this by name and
# never actually calls _run / _arun in the happy path.  We keep a real impl
# as a safety net so a misconfigured workflow still gets a graceful error.
# ---------------------------------------------------------------------------


class AskUserQuestionsTool(BaseTool):
    """Pause-primitive tool that asks the user a short questionnaire.

    The agent's standard-mode tool loop treats a call to this tool as a
    workflow pause: it lifts ``args`` onto the AIMessage and returns
    ``interrupted=True`` instead of executing the tool.
    """

    name: str = "ask_user_questions"
    description: str = (
        "Ask the user a short list of questions and pause the conversation "
        "until they answer.\n\n"
        "Use this whenever you'd otherwise ask the user multiple short "
        "questions in plain text and most answers are best collected as a "
        "pick from fixed options. Examples: gathering preferences, "
        "scoping a task, picking a category, confirming a path forward.\n\n"
        "Rules (the schema enforces these — invalid payloads are rejected):\n"
        "- 1–10 focused questions per call. Don't dump a survey.\n"
        "- Each question's `id` must be unique and non-empty (snake_case "
        "is fine). The `prompt` must be non-empty.\n"
        "- ALWAYS use type='single_choice' (or 'multi_choice' when several "
        "answers may apply) when the user can pick from known options. Put "
        "each option in the `options` array — do NOT use type='text' for "
        "pick-one questions.\n"
        "- If you embed examples in the prompt like '(For example: A, B, C)' "
        "they will be auto-converted to options, but prefer listing them in "
        "`options` directly.\n"
        "- type='single_choice' / 'multi_choice' MUST include >=2 content "
        "options in `options`. The UI always adds 'I don't know' and a "
        "custom-answer text row automatically.\n"
        "- NEVER add catch-all options such as 'Other', 'Something else', "
        "'Or something else?', 'None of the above', or 'I don't know' — "
        "those are injected by the UI and duplicate options will be removed.\n"
        "- type='text' ONLY when the answer is genuinely open-ended with no "
        "sensible preset choices.\n"
        "- type='number' / 'confirm' don't take options.\n"
        "- Set required=true only for questions you truly need answered; "
        "non-required questions get a Skip button.\n"
        "- Only call this when you actually need user input. If you already "
        "know enough, just answer in plain text instead.\n\n"
        "Do NOT include `title`, `submit_label`, or per-question "
        "`skippable` — those fields are not part of the schema; the card "
        "always uses 'Questions' as the header and 'Submit' as the final "
        "button. Use `required=false` to make a question skippable.\n\n"
        "When the user submits their answers, the conversation resumes "
        "and you'll see the answers as the next user message — read them "
        "and continue from there."
    )
    args_schema: Type[BaseModel] = AskUserQuestionsInput

    # ------------------------------------------------------------------
    # The body below is only reached if the standard executor's intercept
    # path didn't fire (e.g. the tool got wired into a non-agent node by
    # mistake).  In that case we return a helpful error instead of
    # silently consuming the call.
    # ------------------------------------------------------------------

    def _run(
        self,
        intro: Optional[str] = None,
        questions: Optional[List[Dict[str, Any]]] = None,
        **_: Any,
    ) -> str:
        logger.warning(
            "ask_user_questions tool invoked outside of the agent intercept path — "
            "this should never happen in normal operation."
        )
        return (
            "ask_user_questions cannot be executed directly. The agent host "
            "should intercept this tool call to pause the workflow. "
            "Please report this as a bug."
        )

    async def _arun(
        self,
        intro: Optional[str] = None,
        questions: Optional[List[Dict[str, Any]]] = None,
        **_: Any,
    ) -> str:
        return self._run(intro=intro, questions=questions)


# ---------------------------------------------------------------------------
# Helpers used by the agent node + chat service when handling
# hand-configured questions (Agent.startupQuestions / Chat.initialQuestions).
# Both paths produce the same JSON payload that the frontend consumes.
# ---------------------------------------------------------------------------


def normalize_questions_payload(raw: Any) -> Optional[Dict[str, Any]]:
    """Validate + normalize a hand-configured questions payload.

    Accepts either:
    - A full payload dict ``{intro?, questions: [...]}``
    - A bare list of questions (we wrap it).

    Legacy fields from older saved workflows (``title``, ``submit_label``
    on the payload, ``skippable`` on each question) are silently dropped
    so existing workflows keep working after the schema simplification.

    This is the **lenient** path used for hand-configured questionnaires:
    individual questions that fail validation are skipped (with a
    warning) instead of nuking the whole payload, so a half-edited
    builder draft still renders whatever questions are valid.  The
    strict ``AskUserQuestionsInput(...)`` validator should be used
    directly when you need the all-or-nothing behaviour (e.g. on
    LLM-emitted tool args).

    Returns ``None`` when the input is empty / unusable / nothing
    salvageable so callers can decide whether to skip the questions
    feature for that node.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        if not raw:
            return None
        raw = {"questions": raw}
    if not isinstance(raw, dict):
        return None

    questions_raw = raw.get("questions") or []
    if not questions_raw:
        return None

    valid_questions: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for idx, q_raw in enumerate(questions_raw):
        if not isinstance(q_raw, dict):
            continue
        cleaned_q = {k: v for k, v in q_raw.items() if k != "skippable"}
        try:
            validated_q = Question(**cleaned_q)
        except Exception as e:
            logger.warning(
                "normalize_questions_payload: dropping invalid question #%d (%s): %s",
                idx + 1, e, str(cleaned_q)[:200],
            )
            continue

        if validated_q.id in seen_ids:
            # De-duplicate by appending a suffix instead of dropping;
            # losing a hand-typed question over an id collision would
            # be confusing.
            new_id = f"{validated_q.id}_{idx + 1}"
            logger.warning(
                "normalize_questions_payload: question #%d has duplicate id "
                "'%s', renaming to '%s'", idx + 1, validated_q.id, new_id,
            )
            validated_q = validated_q.model_copy(update={"id": new_id})
        seen_ids.add(validated_q.id)

        valid_questions.append(validated_q.model_dump(exclude_none=False))

    if not valid_questions:
        logger.warning(
            "normalize_questions_payload: nothing salvageable in payload; "
            "skipping. raw=%s", str(raw)[:200],
        )
        return None

    intro = raw.get("intro")
    payload = {
        "intro": intro if isinstance(intro, str) and intro.strip() else None,
        "questions": valid_questions,
    }
    return payload


def render_questions_for_llm(payload: Dict[str, Any], intro: str = "") -> str:
    """Render a questions payload as plain text the LLM can read.

    Used when an AIMessage carries a questions payload so that the
    LLM, reading state.messages on resume, has full context of what
    was asked alongside the user's answer in the next HumanMessage.

    The frontend ignores this content for display (see ``display_content``
    in additional_kwargs) and renders the QuestionsCard from the
    structured payload instead.
    """
    lines: List[str] = []
    if intro:
        lines.append(intro)
        lines.append("")

    lines.append("Questions for the user:")
    for i, q in enumerate((payload or {}).get("questions") or [], start=1):
        prompt = q.get("prompt") or q.get("id") or f"Question {i}"
        qtype = q.get("type") or "single_choice"
        line = f"{i}. {prompt}"
        opts = q.get("options") or []
        if qtype in ("single_choice", "multi_choice") and opts:
            opt_labels = ", ".join(o.get("label", o.get("id", "")) for o in opts)
            kind = "pick one" if qtype == "single_choice" else "pick any"
            line += f" ({kind} of: {opt_labels})"
            if q.get("allow_other"):
                line += " — or a custom answer"
        elif qtype == "confirm":
            line += " (yes / no)"
        elif qtype == "number":
            line += " (number)"
        elif qtype == "text":
            line += " (free text)"
        lines.append(line)
    return "\n".join(lines)


def format_user_answer_message(
    payload: Dict[str, Any],
    answers: Dict[str, Any],
) -> str:
    """Render a Q/A summary string for the LLM (and chat bubble).

    The QuestionsCard posts the answers via the normal chat input. We
    use this same formatter on the frontend to produce the submitted
    message text — keeping it here lets backend-driven flows (e.g.
    automated testing) generate identical output.

    Output shape (Markdown bullet list):

        - Which season do you enjoy the most? → Summer
        - What's your go-to morning beverage? → Yerba mate (custom)
        - Favorite book? → "Project Hail Mary"
    """
    lines: List[str] = []
    by_id = {q.get("id"): q for q in payload.get("questions") or []}
    for qid, ans in answers.items():
        question = by_id.get(qid) or {}
        prompt = question.get("prompt") or qid
        rendered = _render_answer(question, ans)
        lines.append(f"- {prompt} → {rendered}")
    return "\n".join(lines) if lines else "(no answers provided)"


def _render_answer(question: Dict[str, Any], answer: Any) -> str:
    if answer is None:
        return "(skipped)"
    options = {o.get("id"): o.get("label") for o in question.get("options") or []}

    if isinstance(answer, dict) and "other" in answer:
        return f"{answer['other']} (custom)"

    if isinstance(answer, list):
        rendered = []
        for a in answer:
            if isinstance(a, dict) and "other" in a:
                rendered.append(f"{a['other']} (custom)")
            else:
                rendered.append(options.get(a, str(a)))
        return ", ".join(rendered) if rendered else "(skipped)"

    return options.get(answer, str(answer))
