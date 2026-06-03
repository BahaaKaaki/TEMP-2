"""Tests for centralized prompt cache message preparation."""

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.prompt_cache import (
    _model_family,
    prepare_messages_for_cache,
)


def test_model_family_detection():
    assert _model_family("openai.gpt-5.5") == "openai"
    assert _model_family("bedrock.anthropic.claude-sonnet-4-6") == "anthropic"
    assert _model_family("vertex_ai.gemini-2.5-flash") == "google"


def test_anthropic_adds_cache_control_to_long_system():
    long_text = "x" * 5000
    messages = [
        SystemMessage(content=long_text),
        HumanMessage(content="hi"),
    ]
    out, extras = prepare_messages_for_cache(messages, "bedrock.anthropic.claude-sonnet-4-6")
    assert extras == {}
    assert isinstance(out[0].content, list)
    assert out[0].content[0].get("cache_control") == {"type": "ephemeral"}
    assert out[1] is messages[1]


def test_anthropic_skips_short_system():
    messages = [SystemMessage(content="short"), HumanMessage(content="hi")]
    out, _ = prepare_messages_for_cache(messages, "bedrock.anthropic.claude-sonnet-4-6")
    assert out[0].content == "short"


def test_openai_adds_prompt_cache_key_for_long_system():
    long_text = "y" * 5000
    messages = [SystemMessage(content=long_text), HumanMessage(content="hi")]
    out, extras = prepare_messages_for_cache(messages, "openai.gpt-5.5")
    assert out is messages
    assert "prompt_cache_key" in extras
    assert extras["prompt_cache_key"].startswith("as-")


def test_idempotent_when_cache_control_present():
    content = [{"type": "text", "text": "z" * 5000, "cache_control": {"type": "ephemeral"}}]
    messages = [SystemMessage(content=content)]
    out, _ = prepare_messages_for_cache(messages, "bedrock.anthropic.claude-sonnet-4-6")
    assert out[0].content == content
