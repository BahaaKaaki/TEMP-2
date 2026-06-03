"""Tests for user email in Langfuse observability metadata."""

from types import SimpleNamespace

from app.llm.observability_context import (
    build_langfuse_metadata,
    format_user_email,
    format_user_display_name,
    reset_llm_observability_context,
    set_llm_observability_context,
)


def test_format_user_email_normalizes():
    user = SimpleNamespace(email="  User@Example.COM  ", firstName="A", lastName="B")
    assert format_user_email(user) == "user@example.com"
    assert format_user_display_name(user) == "A B"


def test_build_langfuse_metadata_includes_user_email():
    tokens = set_llm_observability_context(
        user_id="user-123",
        user_name="Jane Doe",
        user_email="jane@example.com",
    )
    try:
        meta = build_langfuse_metadata(model="openai.gpt-5.4")
        assert meta["user_id"] == "user-123"
        assert meta["user_name"] == "Jane Doe"
        assert meta["user_email"] == "jane@example.com"
    finally:
        reset_llm_observability_context(tokens)
