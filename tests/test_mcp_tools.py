"""Tests for MCP tool implementations.

Tests call tool functions directly with a test DB connection,
bypassing MCP transport.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from db.migrations import init_db
from vibe_relay.mcp.tools import (
    add_comment,
    cancel_task,
    create_subtasks,
    create_task,
    create_workflow_steps,
    get_board,
    get_my_tasks,
    get_task,
    get_workflow_steps,
    move_task,
    uncancel_task,
)


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = init_db(tmp_path / "test.db")
    yield connection
    connection.close()


def _seed_project(conn: sqlite3.Connection, title: str = "Test Project") -> str:
    """Insert a test project and return its ID."""
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, title, "active", now, now),
    )
    conn.commit()
    return pid


def _seed_steps(
    conn: sqlite3.Connection,
    project_id: str,
    steps: list[dict] | None = None,
) -> list[dict]:
    """Create workflow steps for a project. Returns list of step dicts with id, name, position."""
    if steps is None:
        steps = [
            {"name": "Plan", "system_prompt": "You are a planner"},
            {"name": "Implement", "system_prompt": "You are a coder"},
            {"name": "Review", "system_prompt": "You are a reviewer"},
            {"name": "Done"},
        ]

    result = create_workflow_steps(conn, project_id, steps)
    return result["steps"]


def _seed_project_with_steps(
    conn: sqlite3.Connection,
) -> tuple[str, list[dict]]:
    """Create a project with default workflow steps."""
    pid = _seed_project(conn)
    steps = _seed_steps(conn, pid)
    return pid, steps


class TestCreateWorkflowSteps:
    def test_empty_steps_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        result = create_workflow_steps(conn, pid, [])
        assert result.get("error") == "invalid_input"

    def test_missing_name_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        result = create_workflow_steps(conn, pid, [{"system_prompt": "test"}])
        assert result.get("error") == "invalid_input"

    def test_nonexistent_project_returns_error(self, conn: sqlite3.Connection) -> None:
        result = create_workflow_steps(conn, "nonexistent", [{"name": "Plan"}])
        assert result.get("error") == "not_found"


class TestGetWorkflowSteps:
    def test_nonexistent_project_returns_error(self, conn: sqlite3.Connection) -> None:
        result = get_workflow_steps(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestCreateTask:
    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        create_task(conn, "My task", "Do stuff", steps[0]["id"], pid)
        events = conn.execute("SELECT * FROM events").fetchall()
        assert len(events) == 1
        assert events[0]["type"] == "task_created"

    def test_step_wrong_project_returns_error(self, conn: sqlite3.Connection) -> None:
        pid1, steps1 = _seed_project_with_steps(conn)
        pid2 = _seed_project(conn)
        result = create_task(conn, "T", "D", steps1[0]["id"], pid2)
        assert result.get("error") == "invalid_input"

    def test_nonexistent_parent_returns_error(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        result = create_task(
            conn, "T", "D", steps[0]["id"], pid, parent_task_id="nonexistent"
        )
        assert result.get("error") == "not_found"


class TestCreateSubtasks:
    def test_default_step_is_next(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        parent = create_task(conn, "Parent", "P", steps[0]["id"], pid)
        result = create_subtasks(
            conn,
            parent["id"],
            [{"title": "Sub 1"}],
        )
        # Parent at step 0, subtask should default to step 1
        assert result["created"][0]["step_id"] == steps[1]["id"]

    def test_explicit_step_id(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        parent = create_task(conn, "Parent", "P", steps[0]["id"], pid)
        result = create_subtasks(
            conn,
            parent["id"],
            [{"title": "Sub 1", "step_id": steps[2]["id"]}],
        )
        assert result["created"][0]["step_id"] == steps[2]["id"]

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        parent = create_task(conn, "Parent", "P", steps[0]["id"], pid)
        create_subtasks(
            conn,
            parent["id"],
            [{"title": "Sub 1"}],
        )
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "subtasks_created" in types

    def test_nonexistent_parent_returns_error(self, conn: sqlite3.Connection) -> None:
        result = create_subtasks(conn, "nonexistent", [{"title": "X"}])
        assert result.get("error") == "not_found"


class TestMoveTask:
    def test_backward_movement(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[2]["id"], pid)
        result = move_task(conn, task["id"], steps[0]["id"])
        assert result["step_id"] == steps[0]["id"]
        assert result["step_name"] == "Plan"

    def test_same_step_returns_error(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[1]["id"], pid)
        result = move_task(conn, task["id"], steps[1]["id"])
        assert result.get("error") == "invalid_transition"

    def test_emits_task_moved_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        move_task(conn, task["id"], steps[1]["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_moved" in types

    def test_nonexistent_task_returns_error(self, conn: sqlite3.Connection) -> None:
        result = move_task(conn, "nonexistent", "step-id")
        assert result.get("error") == "invalid_transition"


class TestCancelTask:
    def test_cancel_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        cancel_task(conn, task["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_cancelled" in types

    def test_cancel_already_cancelled_returns_error(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        cancel_task(conn, task["id"])
        result = cancel_task(conn, task["id"])
        assert result.get("error") == "invalid_transition"


class TestUncancelTask:
    def test_uncancel_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        cancel_task(conn, task["id"])
        uncancel_task(conn, task["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_uncancelled" in types

    def test_uncancel_not_cancelled_returns_error(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = uncancel_task(conn, task["id"])
        assert result.get("error") == "invalid_transition"


class TestGetBoard:
    def test_cancelled_tasks_separated(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T1", "D", steps[0]["id"], pid)
        cancel_task(conn, task["id"])
        result = get_board(conn, pid)
        assert len(result["cancelled"]) == 1
        assert len(result["tasks"][steps[0]["id"]]) == 0

    def test_includes_comment_count(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T1", "D", steps[0]["id"], pid)
        add_comment(conn, task["id"], "hello", "human")
        add_comment(conn, task["id"], "world", "Plan")
        result = get_board(conn, pid)
        assert result["tasks"][steps[0]["id"]][0]["comment_count"] == 2

    def test_nonexistent_project(self, conn: sqlite3.Connection) -> None:
        result = get_board(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestGetTask:
    def test_comments_in_chronological_order(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        add_comment(conn, task["id"], "first", "human")
        add_comment(conn, task["id"], "second", "Plan")
        result = get_task(conn, task["id"])
        assert result["comments"][0]["content"] == "first"
        assert result["comments"][1]["content"] == "second"


class TestGetMyTasks:
    def test_returns_tasks_at_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        t1 = create_task(conn, "T1", "D", steps[1]["id"], pid)
        create_task(conn, "T2", "D", steps[0]["id"], pid)  # Different step
        result = get_my_tasks(conn, steps[1]["id"])
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["id"] == t1["id"]

    def test_excludes_cancelled(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T1", "D", steps[0]["id"], pid)
        cancel_task(conn, task["id"])
        result = get_my_tasks(conn, steps[0]["id"])
        assert result["tasks"] == []

    def test_nonexistent_step_returns_error(self, conn: sqlite3.Connection) -> None:
        result = get_my_tasks(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestAddComment:
    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        add_comment(conn, task["id"], "Test", "human")
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "comment_added" in types


class TestEventEmission:
    def test_every_write_emits_event(self, conn: sqlite3.Connection) -> None:
        """Verify that every write operation creates an event row."""
        pid, steps = _seed_project_with_steps(conn)

        # create_task
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        # add_comment
        add_comment(conn, task["id"], "hi", "human")
        # move_task
        move_task(conn, task["id"], steps[1]["id"])
        # create_subtasks
        parent = create_task(conn, "Parent", "P", steps[0]["id"], pid)
        create_subtasks(conn, parent["id"], [{"title": "S"}])

        events = conn.execute("SELECT type FROM events ORDER BY created_at").fetchall()
        types = [e["type"] for e in events]
        assert "task_created" in types
        assert "comment_added" in types
        assert "task_moved" in types
        assert "subtasks_created" in types
        assert len(events) >= 4
