"""Tests for db/state_machine.py — step-based transitions.

Validates:
- Forward movement (next step only)
- Backward movement (any previous step)
- Same-step rejection
- Cancelled task rejection
- Skip-forward rejection
- Cross-project rejection
- Cancel/uncancel operations
- get_valid_steps computation
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from db.migrations import init_db
from db.state_machine import (
    InvalidTransitionError,
    cancel_task,
    get_valid_steps,
    uncancel_task,
    validate_step_transition,
)


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = init_db(tmp_path / "test.db")
    yield connection
    connection.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _seed_project_with_steps(
    conn: sqlite3.Connection,
    steps: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Create a project with workflow steps. Returns (project_id, step_dicts)."""
    pid = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO projects (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, "Test", "active", now, now),
    )

    if steps is None:
        steps = [
            {"name": "Plan", "system_prompt": "You are a planner"},
            {"name": "Implement", "system_prompt": "You are a coder"},
            {"name": "Review", "system_prompt": "You are a reviewer"},
            {"name": "Done"},
        ]

    created = []
    for pos, s in enumerate(steps):
        sid = _uuid()
        conn.execute(
            "INSERT INTO workflow_steps (id, project_id, name, position, system_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, pid, s["name"], pos, s.get("system_prompt"), now),
        )
        created.append(
            {"id": sid, "name": s["name"], "position": pos, "project_id": pid}
        )

    conn.commit()
    return pid, created


def _seed_task(
    conn: sqlite3.Connection,
    project_id: str,
    step_id: str,
    cancelled: int = 0,
) -> str:
    """Create a task at a given step. Returns task_id."""
    tid = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, step_id, cancelled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tid, project_id, "Task", step_id, cancelled, now, now),
    )
    conn.commit()
    return tid


class TestValidateStepTransition:
    def test_forward_to_next_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])

        result = validate_step_transition(conn, tid, steps[1]["id"])
        assert result["target_step_id"] == steps[1]["id"]
        assert result["current_step_id"] == steps[0]["id"]
        assert result["project_id"] == pid

    def test_backward_to_any_previous(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[2]["id"])  # Review

        # Can go back to Plan (position 0)
        result = validate_step_transition(conn, tid, steps[0]["id"])
        assert result["target_step_id"] == steps[0]["id"]

    def test_backward_to_immediately_previous(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[2]["id"])  # Review

        result = validate_step_transition(conn, tid, steps[1]["id"])
        assert result["target_step_id"] == steps[1]["id"]

    def test_same_step_rejected(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[1]["id"])

        with pytest.raises(InvalidTransitionError, match="already at step"):
            validate_step_transition(conn, tid, steps[1]["id"])

    def test_skip_forward_rejected(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])  # Plan

        with pytest.raises(InvalidTransitionError, match="Cannot skip steps"):
            validate_step_transition(conn, tid, steps[2]["id"])  # Skip to Review

    def test_cancelled_task_rejected(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"], cancelled=1)

        with pytest.raises(InvalidTransitionError, match="cancelled"):
            validate_step_transition(conn, tid, steps[1]["id"])

    def test_nonexistent_task_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(InvalidTransitionError, match="not found"):
            validate_step_transition(conn, "nonexistent", "nonexistent")

    def test_nonexistent_target_step_raises(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])

        with pytest.raises(InvalidTransitionError, match="not found"):
            validate_step_transition(conn, tid, "nonexistent")

    def test_cross_project_step_rejected(self, conn: sqlite3.Connection) -> None:
        pid1, steps1 = _seed_project_with_steps(conn)
        pid2, steps2 = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid1, steps1[0]["id"])

        with pytest.raises(InvalidTransitionError, match="different project"):
            validate_step_transition(conn, tid, steps2[1]["id"])

    def test_returns_step_info(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])

        result = validate_step_transition(conn, tid, steps[1]["id"])
        assert result["task_id"] == tid
        assert result["project_id"] == pid
        assert result["current_step_name"] == "Plan"
        assert result["target_step_name"] == "Implement"
        assert result["current_position"] == 0
        assert result["target_position"] == 1


class TestGetValidSteps:
    def test_from_first_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])

        valid = get_valid_steps(conn, tid)
        # Only forward to next step
        assert len(valid) == 1
        assert valid[0]["id"] == steps[1]["id"]

    def test_from_middle_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[1]["id"])  # Implement

        valid = get_valid_steps(conn, tid)
        # Previous (Plan) + next (Review)
        ids = {s["id"] for s in valid}
        assert steps[0]["id"] in ids  # Plan (backward)
        assert steps[2]["id"] in ids  # Review (forward)
        assert len(valid) == 2

    def test_from_last_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[3]["id"])  # Done

        valid = get_valid_steps(conn, tid)
        # All previous steps
        ids = {s["id"] for s in valid}
        assert steps[0]["id"] in ids
        assert steps[1]["id"] in ids
        assert steps[2]["id"] in ids
        assert len(valid) == 3

    def test_cancelled_task_returns_empty(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[1]["id"], cancelled=1)

        valid = get_valid_steps(conn, tid)
        assert valid == []

    def test_nonexistent_task_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="not found"):
            get_valid_steps(conn, "nonexistent")


class TestCancelTask:
    def test_cancel_succeeds(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])

        cancel_task(conn, tid)  # Should not raise

    def test_cancel_already_cancelled_raises(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"], cancelled=1)

        with pytest.raises(InvalidTransitionError, match="already cancelled"):
            cancel_task(conn, tid)

    def test_cancel_nonexistent_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(InvalidTransitionError, match="not found"):
            cancel_task(conn, "nonexistent")


class TestUncancelTask:
    def test_uncancel_succeeds(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"], cancelled=1)

        uncancel_task(conn, tid)  # Should not raise

    def test_uncancel_not_cancelled_raises(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])

        with pytest.raises(InvalidTransitionError, match="not cancelled"):
            uncancel_task(conn, tid)

    def test_uncancel_nonexistent_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(InvalidTransitionError, match="not found"):
            uncancel_task(conn, "nonexistent")
