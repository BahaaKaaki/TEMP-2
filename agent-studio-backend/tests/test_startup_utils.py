"""Tests for workflow startup helpers."""

import pytest

from app.workflow.utils.startup import (
    get_entry_chain_first_executable,
    get_first_downstream_executable,
    get_first_executable_after_node,
    has_startup_content,
    should_auto_start_on_session_open,
    should_wait_for_startup,
)


class _FakeWorkflow:
    def __init__(self, nodes, edges):
        self._nodes = nodes
        self._edges = edges

    def get_nodes_list(self):
        return self._nodes

    def get_edges_list(self):
        return self._edges


def test_has_startup_content_empty():
    assert has_startup_content({}) is False
    assert has_startup_content({"startupMessage": "  "}) is False


def test_has_startup_content_message():
    assert has_startup_content({"startupMessage": "Hello"}) is True


def test_has_startup_content_questions_only():
    config = {
        "startupType": "questions",
        "startupQuestions": {
            "intro": "Pick one",
            "questions": [{"id": "q1", "text": "Q?", "options": ["A", "B"]}],
        },
    }
    assert has_startup_content(config) is True


def test_should_wait_inferred_from_content():
    assert should_wait_for_startup({"startupMessage": "Hi"}) is True
    assert should_wait_for_startup({}) is False


def test_should_wait_legacy_flag_requires_content():
    assert should_wait_for_startup(
        {"waitForUserInput": True, "startupMessage": "Hi"}
    ) is True
    assert should_wait_for_startup({"waitForUserInput": True}) is False
    assert should_wait_for_startup(
        {"waitForUserInput": False, "startupMessage": "Hi"}
    ) is False


def test_get_first_downstream_executable():
    wf = _FakeWorkflow(
        nodes=[
            {"id": "chat1", "type": "chat"},
            {"id": "agent1", "type": "agent", "config": {"label": "A"}},
            {"id": "exec1", "type": "code-executor"},
        ],
        edges=[
            {"source": "chat1", "target": "agent1"},
            {"source": "agent1", "target": "exec1"},
        ],
    )
    found = get_first_downstream_executable(wf, "chat1")
    assert found is not None
    assert found["id"] == "agent1"


def test_should_auto_start_chat_to_agent_empty_startup():
    wf = _FakeWorkflow(
        nodes=[
            {"id": "chat1", "type": "chat", "config": {"label": "Chat"}},
            {
                "id": "agent1",
                "type": "agent",
                "config": {
                    "startupType": "message",
                    "startupMessage": "",
                    "startupQuestions": {"questions": []},
                },
            },
        ],
        edges=[{"source": "chat1", "target": "agent1"}],
    )
    assert should_auto_start_on_session_open(wf) is True
    assert get_entry_chain_first_executable(wf)["id"] == "agent1"


def test_should_wait_false_for_any_upstream_context():
    """Empty startup never waits — applies regardless of what precedes the node."""
    empty_agent_config = {
        "startupType": "message",
        "startupMessage": "",
        "startupQuestions": {"questions": []},
    }
    assert should_wait_for_startup(empty_agent_config) is False


def test_get_first_executable_after_agent_chain():
    wf = _FakeWorkflow(
        nodes=[
            {"id": "agent1", "type": "agent", "config": {"startupMessage": "Hi"}},
            {"id": "agent2", "type": "agent", "config": {"startupMessage": ""}},
        ],
        edges=[{"source": "agent1", "target": "agent2"}],
    )
    found = get_first_executable_after_node(
        wf,
        "agent1",
        pass_through_types=frozenset(),
    )
    assert found is not None
    assert found["id"] == "agent2"


def test_should_not_auto_start_when_startup_message_set():
    wf = _FakeWorkflow(
        nodes=[
            {"id": "chat1", "type": "chat"},
            {
                "id": "agent1",
                "type": "agent",
                "config": {"startupMessage": "Please wait"},
            },
        ],
        edges=[{"source": "chat1", "target": "agent1"}],
    )
    assert should_auto_start_on_session_open(wf) is False
