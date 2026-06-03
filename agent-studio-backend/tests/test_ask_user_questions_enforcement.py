"""Tests for questionnaire MCQ enforcement."""

from app.workflow.tools.ask_user_questions import (
    I_DONT_KNOW_OPTION_ID,
    Question,
    QuestionOption,
    _extract_mcq_from_prompt,
    normalize_questions_payload,
)


def test_extract_options_from_for_example_parenthetical():
    prompt = (
        "What kind of analytics are you looking to deliver? "
        "(For example: executive dashboards, forecasting models, optimization, "
        "operational reporting, etc.)"
    )
    result = _extract_mcq_from_prompt(prompt)
    assert result is not None
    cleaned, labels = result
    assert "For example" not in cleaned
    assert len(labels) >= 4
    assert "executive dashboards" in labels[0].lower()


def test_text_question_with_examples_promoted_to_mcq():
    q = Question(
        id="analytics_type",
        prompt=(
            "For the data-driven engine — what kind of analytics are you looking "
            "to deliver? (For example: executive dashboards, forecasting models, "
            "optimization, operational reporting, etc.)"
        ),
        type="text",
        required=True,
    )
    assert q.type == "single_choice"
    assert q.allow_other is True
    assert any(o.id == I_DONT_KNOW_OPTION_ID for o in q.options)
    assert len([o for o in q.options if o.id != I_DONT_KNOW_OPTION_ID]) >= 2


def test_mcq_always_gets_i_dont_know_and_other():
    q = Question(
        id="scope",
        prompt="Which scope fits best?",
        type="single_choice",
        options=[
            QuestionOption(id="small", label="Small"),
            QuestionOption(id="large", label="Large"),
        ],
        allow_other=False,
    )
    assert q.allow_other is True
    ids = [o.id for o in q.options]
    assert I_DONT_KNOW_OPTION_ID in ids
    assert ids.count(I_DONT_KNOW_OPTION_ID) == 1


def test_normalize_payload_applies_enforcement():
    raw = {
        "questions": [
            {
                "id": "q1",
                "prompt": "Pick a stack (e.g. Python, Java, Go)",
                "type": "text",
            }
        ]
    }
    payload = normalize_questions_payload(raw)
    assert payload is not None
    q0 = payload["questions"][0]
    assert q0["type"] == "single_choice"
    assert q0["allow_other"] is True
    assert any(o["id"] == I_DONT_KNOW_OPTION_ID for o in q0["options"])


def test_strips_llm_something_else_and_other_catchalls():
    q = Question(
        id="goal",
        prompt="What is the primary goal?",
        type="single_choice",
        options=[
            QuestionOption(id="a", label="consolidating data from multiple systems"),
            QuestionOption(id="b", label="building a central repository"),
            QuestionOption(id="c", label="enabling self-service analytics"),
            QuestionOption(id="d", label="or something else?"),
            QuestionOption(id="other", label="Other"),
        ],
    )
    labels = [o.label for o in q.options]
    assert "or something else?" not in [l.lower() for l in labels]
    assert "Other" not in labels
    assert any(o.id == I_DONT_KNOW_OPTION_ID for o in q.options)
    assert q.allow_other is True
    assert len([o for o in q.options if o.id != I_DONT_KNOW_OPTION_ID]) == 3


def test_open_ended_text_stays_text():
    q = Question(
        id="description",
        prompt="Describe your project goals in detail.",
        type="text",
    )
    assert q.type == "text"
    assert not q.options
