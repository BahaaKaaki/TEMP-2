"""Tests for chat streaming eligibility helper."""

from app.workflow.utils.streaming import (
    classify_chat_stream_release,
    should_stream_chat_responses,
)


def test_stream_when_chat_session():
    assert should_stream_chat_responses(metadata={"session_id": "sess-1"}) is True


def test_stream_when_agent_mode_chat():
    assert should_stream_chat_responses(node_config={"agentMode": "chat"}) is True


def test_stream_when_chat_node_type():
    assert should_stream_chat_responses(node_type="chat") is True


def test_no_stream_for_headless_run():
    assert should_stream_chat_responses(
        node_config={"agentMode": "regular"},
        node_type="agent",
        metadata={},
    ) is False


def test_release_flush_for_chat_action():
    assert classify_chat_stream_release("chat") == "flush"


def test_release_clear_for_questions_and_deliverable():
    assert classify_chat_stream_release("ask_user_questions") == "clear"
    assert classify_chat_stream_release("submit_deliverable") == "clear"


def test_release_flush_when_submit_blocked_as_chat():
    assert (
        classify_chat_stream_release(
            "submit_deliverable",
            agent_mode="chat",
        )
        == "flush"
    )


def test_release_clear_for_tool_routing():
    assert classify_chat_stream_release("search_kb") == "clear"
