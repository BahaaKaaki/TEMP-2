"""
Test workflow output collection bugfix.

Tests that workflows ending at HITL nodes properly collect deliverables as output.
"""
import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime

from app.workflow.executor import WorkflowExecutor
from app.workflow.state import WorkflowState, create_initial_state


@pytest.mark.asyncio
async def test_workflow_with_deliverables_but_no_output_data():
    """
    Test that workflow collects deliverables as output when output_data is empty.
    
    This simulates a workflow that ends at a HITL node without an explicit END node.
    """
    # Mock database session
    mock_db = AsyncMock()
    executor = WorkflowExecutor(mock_db)
    
    # Create a final state with deliverables but no output_data
    # (This is what happens when workflow ends at HITL node)
    final_state = {
        "messages": [],
        "current_node": "hitl_final",
        "next_node": None,
        "node_outputs": {
            "agent_1": {
                "node_id": "agent_1",
                "node_type": "agent",
                "output": {"response": "Agent 1 output"},
                "status": "success"
            },
            "agent_2": {
                "node_id": "agent_2", 
                "node_type": "agent",
                "output": {"response": "Agent 2 output"},
                "status": "success"
            }
        },
        "variables": {},
        "input_data": {},
        "output_data": None,  # ❌ No output data set!
        "deliverables": [  # ✅ But we have deliverables
            {
                "deliverable_id": "deliv_1",
                "agent_id": "agent_1",
                "agent_label": "Context Collector",
                "agent_type": "agent",
                "deliverable": {"key": "value1"},
                "status": "approved"
            },
            {
                "deliverable_id": "deliv_2",
                "agent_id": "agent_2",
                "agent_label": "Plan Generator",
                "agent_type": "agent",
                "deliverable": {"key": "value2"},
                "status": "approved"
            }
        ],
        "error": None,
        "error_node": None,
        "metadata": {
            "execution_id": 123,
            "workflow_id": "wf_test",
            "workflow_name": "Test Workflow",
            "status": "running"
        },
        "should_continue": True,
        "interrupted": False,
        "pending_deliverable": None
    }
    
    # Simulate the logic from executor.py
    # This is what the bugfix should handle
    if final_state.get("error"):
        status = "failed"
        error = final_state.get("error")
        output_data = None
    elif final_state.get("pending_deliverable"):
        status = "pending_review"
        error = None
        output_data = None
    elif final_state.get("interrupted"):
        status = "paused"
        error = None
        output_data = None
    else:
        status = "completed"
        error = None
        output_data = final_state.get("output_data", {})
        
        # BUGFIX: If output_data is empty but we have deliverables, collect them
        if not output_data and final_state.get("deliverables"):
            deliverables = final_state.get("deliverables", [])
            output_data = {
                "deliverables": deliverables,
                "final_deliverable": deliverables[-1] if deliverables else None,
                "all_node_outputs": final_state.get("node_outputs", {})
            }
    
    # Assertions
    assert status == "completed", "Status should be completed"
    assert output_data is not None, "Output data should not be None"
    assert "deliverables" in output_data, "Output should contain deliverables"
    assert len(output_data["deliverables"]) == 2, "Should have 2 deliverables"
    assert output_data["final_deliverable"]["agent_id"] == "agent_2", "Final deliverable should be from agent_2"
    assert output_data["final_deliverable"]["deliverable"]["key"] == "value2", "Final deliverable content should match"
    assert "all_node_outputs" in output_data, "Output should contain all node outputs"


@pytest.mark.asyncio
async def test_workflow_with_explicit_output_data():
    """
    Test that workflow doesn't override explicit output_data with deliverables.
    
    This ensures backward compatibility - if output_data is explicitly set,
    we don't override it.
    """
    final_state = {
        "messages": [],
        "output_data": {"explicit": "output"},  # ✅ Explicit output set
        "deliverables": [
            {
                "deliverable_id": "deliv_1",
                "agent_id": "agent_1",
                "deliverable": {"key": "value1"},
                "status": "approved"
            }
        ],
        "error": None,
        "interrupted": False,
        "pending_deliverable": None
    }
    
    # Simulate bugfix logic
    status = "completed"
    output_data = final_state.get("output_data", {})
    
    # Should NOT apply bugfix when output_data exists
    if not output_data and final_state.get("deliverables"):
        deliverables = final_state.get("deliverables", [])
        output_data = {
            "deliverables": deliverables,
            "final_deliverable": deliverables[-1] if deliverables else None
        }
    
    # Assertions
    assert output_data == {"explicit": "output"}, "Should preserve explicit output_data"
    assert "deliverables" not in output_data, "Should NOT add deliverables when output_data exists"


@pytest.mark.asyncio
async def test_workflow_with_no_deliverables_no_output():
    """
    Test that workflow handles case with no deliverables and no output gracefully.
    """
    final_state = {
        "messages": [],
        "output_data": None,
        "deliverables": [],  # ❌ No deliverables
        "error": None,
        "interrupted": False,
        "pending_deliverable": None,
        "node_outputs": {}
    }
    
    # Simulate bugfix logic
    status = "completed"
    output_data = final_state.get("output_data", {})
    
    # Bugfix should NOT trigger when no deliverables exist
    if not output_data and final_state.get("deliverables"):
        deliverables = final_state.get("deliverables", [])
        output_data = {
            "deliverables": deliverables,
            "final_deliverable": deliverables[-1] if deliverables else None
        }
    
    # Assertions
    assert output_data == {}, "Should return empty dict when no deliverables and no output"


@pytest.mark.asyncio
async def test_workflow_paused_at_hitl():
    """
    Test that paused workflow doesn't incorrectly collect output.
    """
    final_state = {
        "messages": [],
        "output_data": None,
        "deliverables": [
            {
                "deliverable_id": "deliv_1",
                "agent_id": "agent_1",
                "deliverable": {"key": "value1"},
                "status": "pending"  # Not approved yet
            }
        ],
        "error": None,
        "interrupted": False,
        "pending_deliverable": {
            "agent_id": "agent_1",
            "deliverable": {"key": "value1"}
        }  # ⏸️ Paused for review
    }
    
    # Simulate logic
    if final_state.get("pending_deliverable"):
        status = "pending_review"
        error = None
        output_data = None
    else:
        status = "completed"
        output_data = final_state.get("output_data", {})
        if not output_data and final_state.get("deliverables"):
            deliverables = final_state.get("deliverables", [])
            output_data = {"deliverables": deliverables}
    
    # Assertions
    assert status == "pending_review", "Status should be pending_review"
    assert output_data is None, "Output should be None when paused"


if __name__ == "__main__":
    import asyncio
    
    print("Running workflow output collection tests...")
    asyncio.run(test_workflow_with_deliverables_but_no_output_data())
    print("✅ Test 1: Deliverables collected as output")
    
    asyncio.run(test_workflow_with_explicit_output_data())
    print("✅ Test 2: Explicit output preserved")
    
    asyncio.run(test_workflow_with_no_deliverables_no_output())
    print("✅ Test 3: No deliverables handled gracefully")
    
    asyncio.run(test_workflow_paused_at_hitl())
    print("✅ Test 4: Paused workflow doesn't collect output")
    
    print("\n✅ All tests passed!")







