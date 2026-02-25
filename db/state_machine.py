"""Task step transition state machine for vibe-relay.

Movement rules:
    - Forward: task can move to the next step (position + 1)
    - Backward: task can move to any previous step (position < current)
    - No-op: moving to the same step is rejected
    - Cancelled tasks cannot be moved

Cancel/uncancel are orthogonal to step position.

Import validate_step_transition() from here. Do not duplicate this logic.
"""

import sqlite3
from typing import Any


class InvalidTransitionError(Exception):
    """Raised when a step transition is not allowed by the state machine."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def validate_step_transition(
    conn: sqlite3.Connection, task_id: str, target_step_id: str
) -> dict[str, Any]:
    """Validate a task step transition.

    Returns dict with current/target step info on success.
    Raises InvalidTransitionError if the move is invalid.
    """
    task = conn.execute(
        "SELECT id, step_id, cancelled, project_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise InvalidTransitionError(f"Task '{task_id}' not found")

    if task["cancelled"]:
        raise InvalidTransitionError(
            f"Task '{task_id}' is cancelled. Uncancel it before moving."
        )

    current_step = conn.execute(
        "SELECT id, name, position, project_id FROM workflow_steps WHERE id = ?",
        (task["step_id"],),
    ).fetchone()

    target_step = conn.execute(
        "SELECT id, name, position, project_id FROM workflow_steps WHERE id = ?",
        (target_step_id,),
    ).fetchone()
    if target_step is None:
        raise InvalidTransitionError(f"Target step '{target_step_id}' not found")

    if target_step["project_id"] != task["project_id"]:
        raise InvalidTransitionError("Target step belongs to a different project")

    if target_step["position"] == current_step["position"]:
        raise InvalidTransitionError(
            f"Task is already at step '{current_step['name']}'"
        )

    # Forward: only next step allowed
    if target_step["position"] > current_step["position"]:
        if target_step["position"] != current_step["position"] + 1:
            raise InvalidTransitionError(
                f"Cannot skip steps. Task is at '{current_step['name']}' "
                f"(position {current_step['position']}), "
                f"target '{target_step['name']}' is at position {target_step['position']}. "
                f"Only the next step (position {current_step['position'] + 1}) is allowed."
            )

    # Backward: any previous step is allowed (position < current) — no restriction

    return {
        "task_id": task_id,
        "project_id": task["project_id"],
        "current_step_id": current_step["id"],
        "current_step_name": current_step["name"],
        "current_position": current_step["position"],
        "target_step_id": target_step["id"],
        "target_step_name": target_step["name"],
        "target_position": target_step["position"],
    }


def get_valid_steps(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """Return the list of valid target steps for a task.

    Valid targets:
    - Next step (position + 1) if it exists
    - All previous steps (position < current)
    """
    task = conn.execute(
        "SELECT id, step_id, cancelled, project_id FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError(f"Task '{task_id}' not found")

    if task["cancelled"]:
        return []

    current_step = conn.execute(
        "SELECT position FROM workflow_steps WHERE id = ?",
        (task["step_id"],),
    ).fetchone()

    current_pos = current_step["position"]

    # Get all steps for this project
    all_steps = conn.execute(
        "SELECT id, name, position, system_prompt IS NOT NULL as has_agent, model, color "
        "FROM workflow_steps WHERE project_id = ? ORDER BY position",
        (task["project_id"],),
    ).fetchall()

    valid: list[dict[str, Any]] = []
    for step in all_steps:
        pos = step["position"]
        # Next step (forward by 1)
        if pos == current_pos + 1:
            valid.append(dict(step))
        # Any previous step (backward)
        elif pos < current_pos:
            valid.append(dict(step))

    return valid


def cancel_task(conn: sqlite3.Connection, task_id: str) -> None:
    """Set a task's cancelled flag. Raises InvalidTransitionError if already cancelled."""
    task = conn.execute(
        "SELECT id, cancelled FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if task is None:
        raise InvalidTransitionError(f"Task '{task_id}' not found")
    if task["cancelled"]:
        raise InvalidTransitionError(f"Task '{task_id}' is already cancelled")


def uncancel_task(conn: sqlite3.Connection, task_id: str) -> None:
    """Clear a task's cancelled flag. Raises InvalidTransitionError if not cancelled."""
    task = conn.execute(
        "SELECT id, cancelled FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if task is None:
        raise InvalidTransitionError(f"Task '{task_id}' not found")
    if not task["cancelled"]:
        raise InvalidTransitionError(f"Task '{task_id}' is not cancelled")
