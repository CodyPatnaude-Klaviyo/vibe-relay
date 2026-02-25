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
    def test_creates_steps(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        result = create_workflow_steps(
            conn,
            pid,
            [
                {"name": "Plan", "system_prompt": "planner"},
                {"name": "Done"},
            ],
        )
        assert "steps" in result
        assert len(result["steps"]) == 2
        assert result["steps"][0]["name"] == "Plan"
        assert result["steps"][0]["position"] == 0
        assert result["steps"][0]["has_agent"] is True
        assert result["steps"][1]["name"] == "Done"
        assert result["steps"][1]["position"] == 1
        assert result["steps"][1]["has_agent"] is False

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
    def test_returns_ordered_steps(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        result = get_workflow_steps(conn, pid)
        assert len(result["steps"]) == 4
        assert result["steps"][0]["name"] == "Plan"
        assert result["steps"][3]["name"] == "Done"

    def test_nonexistent_project_returns_error(self, conn: sqlite3.Connection) -> None:
        result = get_workflow_steps(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestCreateTask:
    def test_creates_task_at_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        result = create_task(conn, "My task", "Do stuff", steps[1]["id"], pid)
        assert result["step_id"] == steps[1]["id"]
        assert result["step_name"] == "Implement"
        assert result["title"] == "My task"
        assert result["project_id"] == pid
        assert result["cancelled"] is False

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        create_task(conn, "My task", "Do stuff", steps[0]["id"], pid)
        events = conn.execute("SELECT * FROM events").fetchall()
        assert len(events) == 1
        assert events[0]["type"] == "task_created"

    def test_nonexistent_step_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        result = create_task(conn, "T", "D", "nonexistent-step", pid)
        assert result.get("error") == "not_found"

    def test_step_wrong_project_returns_error(self, conn: sqlite3.Connection) -> None:
        pid1, steps1 = _seed_project_with_steps(conn)
        pid2 = _seed_project(conn)
        result = create_task(conn, "T", "D", steps1[0]["id"], pid2)
        assert result.get("error") == "invalid_input"

    def test_nonexistent_project_returns_error(self, conn: sqlite3.Connection) -> None:
        result = create_task(conn, "T", "D", "step-id", "nonexistent-id")
        assert result.get("error") == "not_found"

    def test_nonexistent_parent_returns_error(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        result = create_task(
            conn, "T", "D", steps[0]["id"], pid, parent_task_id="nonexistent"
        )
        assert result.get("error") == "not_found"

    def test_with_parent_task(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        parent = create_task(conn, "Parent", "P", steps[0]["id"], pid)
        child = create_task(
            conn, "Child", "C", steps[1]["id"], pid, parent_task_id=parent["id"]
        )
        assert child["parent_task_id"] == parent["id"]


class TestCreateSubtasks:
    def test_bulk_creates_under_parent(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        parent = create_task(conn, "Parent", "P", steps[0]["id"], pid)
        result = create_subtasks(
            conn,
            parent["id"],
            [
                {"title": "Sub 1", "description": "S1"},
                {"title": "Sub 2", "description": "S2"},
            ],
        )
        assert len(result["created"]) == 2
        assert all(t["parent_task_id"] == parent["id"] for t in result["created"])
        assert all(t["project_id"] == pid for t in result["created"])

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
    def test_forward_movement(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = move_task(conn, task["id"], steps[1]["id"])
        assert result["step_id"] == steps[1]["id"]
        assert result["step_name"] == "Implement"

    def test_backward_movement(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[2]["id"], pid)
        result = move_task(conn, task["id"], steps[0]["id"])
        assert result["step_id"] == steps[0]["id"]
        assert result["step_name"] == "Plan"

    def test_skip_forward_returns_error(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = move_task(conn, task["id"], steps[2]["id"])
        assert result.get("error") == "invalid_transition"

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

    def test_full_lifecycle(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)

        # Plan -> Implement
        result = move_task(conn, task["id"], steps[1]["id"])
        assert result["step_name"] == "Implement"

        # Implement -> Review
        result = move_task(conn, task["id"], steps[2]["id"])
        assert result["step_name"] == "Review"

        # Review -> Implement (backward)
        result = move_task(conn, task["id"], steps[1]["id"])
        assert result["step_name"] == "Implement"

        # Implement -> Review again
        result = move_task(conn, task["id"], steps[2]["id"])
        assert result["step_name"] == "Review"

        # Review -> Done
        result = move_task(conn, task["id"], steps[3]["id"])
        assert result["step_name"] == "Done"


class TestCancelTask:
    def test_cancel_succeeds(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = cancel_task(conn, task["id"])
        assert result["cancelled"] is True

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
    def test_uncancel_succeeds(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        cancel_task(conn, task["id"])
        result = uncancel_task(conn, task["id"])
        assert result["cancelled"] is False

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
    def test_returns_project_steps_and_tasks(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        create_task(conn, "T1", "D", steps[0]["id"], pid)
        create_task(conn, "T2", "D", steps[2]["id"], pid)
        result = get_board(conn, pid)
        assert result["project"]["id"] == pid
        assert len(result["steps"]) == 4
        assert "tasks" in result
        assert "cancelled" in result

    def test_tasks_grouped_by_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        create_task(conn, "T1", "D", steps[0]["id"], pid)
        create_task(conn, "T2", "D", steps[0]["id"], pid)
        create_task(conn, "T3", "D", steps[1]["id"], pid)
        result = get_board(conn, pid)
        assert len(result["tasks"][steps[0]["id"]]) == 2
        assert len(result["tasks"][steps[1]["id"]]) == 1

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
    def test_returns_task_with_comments(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        add_comment(conn, task["id"], "hello", "human")
        result = get_task(conn, task["id"])
        assert result["title"] == "T"
        assert result["step_name"] == "Plan"
        assert result["step_position"] == 0
        assert result["cancelled"] is False
        assert len(result["comments"]) == 1
        assert result["comments"][0]["content"] == "hello"

    def test_comments_in_chronological_order(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        add_comment(conn, task["id"], "first", "human")
        add_comment(conn, task["id"], "second", "Plan")
        result = get_task(conn, task["id"])
        assert result["comments"][0]["content"] == "first"
        assert result["comments"][1]["content"] == "second"

    def test_nonexistent_task(self, conn: sqlite3.Connection) -> None:
        result = get_task(conn, "nonexistent")
        assert result.get("error") == "not_found"


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

    def test_empty_when_no_tasks(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        result = get_my_tasks(conn, steps[0]["id"])
        assert result["tasks"] == []


class TestAddComment:
    def test_creates_comment(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = add_comment(conn, task["id"], "Test comment", "human")
        assert result["content"] == "Test comment"
        assert result["author_role"] == "human"

    def test_accepts_any_author_role(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        # Any non-empty string is valid
        result = add_comment(conn, task["id"], "hello", "Plan")
        assert result["author_role"] == "Plan"
        result = add_comment(conn, task["id"], "hi", "custom_role")
        assert result["author_role"] == "custom_role"

    def test_empty_role_returns_error(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = add_comment(conn, task["id"], "x", "")
        assert result.get("error") == "invalid_role"

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        add_comment(conn, task["id"], "Test", "human")
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "comment_added" in types

    def test_nonexistent_task_returns_error(self, conn: sqlite3.Connection) -> None:
        result = add_comment(conn, "nonexistent", "x", "human")
        assert result.get("error") == "not_found"


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
