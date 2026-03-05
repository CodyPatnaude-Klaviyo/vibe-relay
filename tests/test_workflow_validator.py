"""Tests for workflow validation utilities."""

import pytest
from vibe_relay.workflow_validator import (
    validate_workflow_steps,
    get_simplified_workflow,
    is_simplified_workflow,
    WorkflowValidationError,
)


def test_validate_workflow_steps_valid():
    """Test validation passes for valid workflow."""
    steps = [
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Implement", "position": 1, "has_agent": True},
        {"name": "Done", "position": 2, "has_agent": False},
    ]
    assert validate_workflow_steps(steps) is True


def test_validate_workflow_steps_empty():
    """Test validation fails for empty workflow."""
    with pytest.raises(WorkflowValidationError, match="must have at least one step"):
        validate_workflow_steps([])


def test_validate_workflow_steps_non_sequential_positions():
    """Test validation fails for non-sequential positions."""
    steps = [
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Implement", "position": 2, "has_agent": True},
        {"name": "Done", "position": 3, "has_agent": False},
    ]
    with pytest.raises(WorkflowValidationError, match="must be sequential"):
        validate_workflow_steps(steps)


def test_validate_workflow_steps_duplicate_names():
    """Test validation fails for duplicate step names."""
    steps = [
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Plan", "position": 1, "has_agent": True},
        {"name": "Done", "position": 2, "has_agent": False},
    ]
    with pytest.raises(WorkflowValidationError, match="Duplicate step names"):
        validate_workflow_steps(steps)


def test_validate_workflow_steps_last_not_done():
    """Test validation fails when last step is not 'Done'."""
    steps = [
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Implement", "position": 1, "has_agent": True},
    ]
    with pytest.raises(WorkflowValidationError, match="Last step must be 'Done'"):
        validate_workflow_steps(steps)


def test_validate_workflow_steps_done_has_agent():
    """Test validation fails when Done step has an agent."""
    steps = [
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Done", "position": 1, "has_agent": True},
    ]
    with pytest.raises(WorkflowValidationError, match="Done step should not have an agent"):
        validate_workflow_steps(steps)


def test_get_simplified_workflow():
    """Test simplified workflow template is correct."""
    workflow = get_simplified_workflow()
    assert len(workflow) == 4
    assert workflow[0]["name"] == "Plan"
    assert workflow[1]["name"] == "Implement"
    assert workflow[2]["name"] == "Review"
    assert workflow[3]["name"] == "Done"
    assert all(s["has_agent"] for s in workflow[:-1])
    assert not workflow[-1]["has_agent"]


def test_is_simplified_workflow_valid():
    """Test detection of simplified workflow."""
    steps = get_simplified_workflow()
    assert is_simplified_workflow(steps) is True


def test_is_simplified_workflow_wrong_length():
    """Test detection fails for wrong number of steps."""
    steps = [
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Done", "position": 1, "has_agent": False},
    ]
    assert is_simplified_workflow(steps) is False


def test_is_simplified_workflow_wrong_names():
    """Test detection fails for different step names."""
    steps = [
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Research", "position": 1, "has_agent": True},
        {"name": "Implement", "position": 2, "has_agent": True},
        {"name": "Done", "position": 3, "has_agent": False},
    ]
    assert is_simplified_workflow(steps) is False


def test_is_simplified_workflow_unordered_input():
    """Test detection works with unordered input."""
    steps = [
        {"name": "Done", "position": 3, "has_agent": False},
        {"name": "Plan", "position": 0, "has_agent": True},
        {"name": "Review", "position": 2, "has_agent": True},
        {"name": "Implement", "position": 1, "has_agent": True},
    ]
    assert is_simplified_workflow(steps) is True
