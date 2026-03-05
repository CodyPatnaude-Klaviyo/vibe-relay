"""Workflow validation utilities for vibe-relay.

Validates that workflow steps are properly configured and follow conventions.
"""

from typing import List, Dict, Any, Optional


class WorkflowValidationError(Exception):
    """Raised when workflow validation fails."""
    pass


def validate_workflow_steps(steps: List[Dict[str, Any]]) -> bool:
    """Validate that workflow steps follow vibe-relay conventions.

    Args:
        steps: List of workflow step dictionaries with keys:
            - name (str): Step name
            - position (int): Step position in workflow
            - has_agent (bool): Whether step has an associated agent

    Returns:
        bool: True if valid

    Raises:
        WorkflowValidationError: If validation fails
    """
    if not steps:
        raise WorkflowValidationError("Workflow must have at least one step")

    # Check positions are sequential starting from 0
    positions = sorted([s["position"] for s in steps])
    expected_positions = list(range(len(steps)))
    if positions != expected_positions:
        raise WorkflowValidationError(
            f"Step positions must be sequential starting from 0. "
            f"Expected {expected_positions}, got {positions}"
        )

    # Check for duplicate step names
    names = [s["name"] for s in steps]
    if len(names) != len(set(names)):
        raise WorkflowValidationError(f"Duplicate step names found: {names}")

    # Last step should be "Done" with no agent
    last_step = steps[-1]
    if last_step["name"] != "Done":
        raise WorkflowValidationError(
            f"Last step must be 'Done', got '{last_step['name']}'"
        )
    if last_step.get("has_agent"):
        raise WorkflowValidationError("Done step should not have an agent")

    return True


def get_simplified_workflow() -> List[Dict[str, Any]]:
    """Get the simplified workflow template (Plan → Implement → Review → Done).

    Returns:
        List of workflow step configurations
    """
    return [
        {
            "name": "Plan",
            "position": 0,
            "has_agent": True,
        },
        {
            "name": "Implement",
            "position": 1,
            "has_agent": True,
        },
        {
            "name": "Review",
            "position": 2,
            "has_agent": True,
        },
        {
            "name": "Done",
            "position": 3,
            "has_agent": False,
        },
    ]


def is_simplified_workflow(steps: List[Dict[str, Any]]) -> bool:
    """Check if workflow matches the simplified template.

    Args:
        steps: List of workflow step dictionaries

    Returns:
        bool: True if workflow is the simplified Plan → Implement → Review → Done
    """
    if len(steps) != 4:
        return False

    expected_names = ["Plan", "Implement", "Review", "Done"]
    actual_names = [s["name"] for s in sorted(steps, key=lambda x: x["position"])]

    return actual_names == expected_names
