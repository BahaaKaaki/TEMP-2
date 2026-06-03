"""Tests for Langfuse usage extraction."""

from types import SimpleNamespace

from app.llm.usage_for_langfuse import (
    extract_usage_for_langfuse as _extract_usage,
    finalize_usage_details_for_langfuse,
)


def test_finalize_langfuse_cache_keys():
    out = finalize_usage_details_for_langfuse({
        "input": 100,
        "output": 10,
        "input_cache_read": 80,
        "input_cache_creation": 75,
    })
    assert out["cache_read_input_tokens"] == 80
    assert out["cache_creation_input_tokens"] == 75
    assert out["input_cached_tokens"] == 80


def test_extract_flat_usage_metadata_with_reasoning():
    response = SimpleNamespace(
        usage_metadata={
            "input_tokens": 277,
            "output_tokens": 350,
            "total_tokens": 627,
            "input_token_details": {"cache_read": 0},
            "output_token_details": {"reasoning": 289},
        },
        response_metadata={"model_name": "openai.gpt-5.5"},
    )
    usage = _extract_usage(response)
    assert usage is not None
    assert usage["input"] == 277
    assert usage["output_reasoning_tokens"] == 289
    assert usage["prompt_tokens"] == 277


def test_extract_nested_token_usage_with_cache_and_reasoning():
    response = SimpleNamespace(
        usage_metadata={},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "prompt_tokens_details": {"cached_tokens": 64},
                "completion_tokens_details": {"reasoning_tokens": 12},
            }
        },
    )
    usage = _extract_usage(response)
    assert usage["input"] == 100
    assert usage["cache_read_input_tokens"] == 64
    assert usage["input_cached_tokens"] == 64
    assert usage["output_reasoning_tokens"] == 12


def test_extract_top_level_anthropic_cache_fields():
    response = SimpleNamespace(
        usage_metadata={},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
                "cache_read_input_tokens": 80,
                "cache_creation_input_tokens": 0,
            }
        },
    )
    usage = _extract_usage(response)
    assert usage["cache_read_input_tokens"] == 80
    assert usage["input_cached_tokens"] == 80


def test_extract_returns_none_without_usage():
    assert _extract_usage(SimpleNamespace()) is None
