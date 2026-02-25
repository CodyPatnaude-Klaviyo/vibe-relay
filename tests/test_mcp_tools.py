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
    complete_task,
    create_subtasks,
    create_task,
    get_board,
    get_my_tasks,
    get_task,
    update_task_status,
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


class TestCreateTask:
    def test_creates_task_in_backlog(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        result = create_task(conn, "My task", "Do stuff", "coder", pid)
        assert result["status"] == "backlog"
        assert result["title"] == "My task"
        assert result["project_id"] == pid

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        create_task(conn, "My task", "Do stuff", "coder", pid)
        events = conn.execute("SELECT * FROM events").fetchall()
        assert len(events) == 1
        assert events[0]["type"] == "task_created"

    def test_invalid_phase_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        result = create_task(conn, "My task", "Do stuff", "invalid_phase", pid)
        assert result.get("error") == "invalid_phase"

    def test_nonexistent_project_returns_error(self, conn: sqlite3.Connection) -> None:
        result = create_task(conn, "T", "D", "coder", "nonexistent-id")
        assert result.get("error") == "not_found"

    def test_nonexistent_parent_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        result = create_task(conn, "T", "D", "coder", pid, parent_task_id="nonexistent")
        assert result.get("error") == "not_found"

    def test_with_parent_task(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        parent = create_task(conn, "Parent", "P", "planner", pid)
        child = create_task(
            conn, "Child", "C", "coder", pid, parent_task_id=parent["id"]
        )
        assert child["parent_task_id"] == parent["id"]


class TestCreateSubtasks:
    def test_bulk_creates_under_parent(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        parent = create_task(conn, "Parent", "P", "planner", pid)
        result = create_subtasks(
            conn,
            parent["id"],
            [
                {"title": "Sub 1", "description": "S1", "phase": "coder"},
                {"title": "Sub 2", "description": "S2", "phase": "coder"},
            ],
        )
        assert len(result["created"]) == 2
        assert all(t["parent_task_id"] == parent["id"] for t in result["created"])
        assert all(t["project_id"] == pid for t in result["created"])

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        parent = create_task(conn, "Parent", "P", "planner", pid)
        create_subtasks(
            conn,
            parent["id"],
            [{"title": "Sub 1", "phase": "coder"}],
        )
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "subtasks_created" in types

    def test_nonexistent_parent_returns_error(self, conn: sqlite3.Connection) -> None:
        result = create_subtasks(
            conn, "nonexistent", [{"title": "X", "phase": "coder"}]
        )
        assert result.get("error") == "not_found"

    def test_invalid_phase_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        parent = create_task(conn, "Parent", "P", "planner", pid)
        result = create_subtasks(
            conn,
            parent["id"],
            [{"title": "Bad", "phase": "invalid"}],
        )
        assert result.get("error") == "invalid_phase"


class TestUpdateTaskStatus:
    def test_valid_transition(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        result = update_task_status(conn, task["id"], "in_progress")
        assert result["status"] == "in_progress"

    def test_invalid_transition_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        result = update_task_status(conn, task["id"], "in_review")
        assert result.get("error") == "invalid_transition"
        assert "backlog" in result["message"]
        assert "in_review" in result["message"]

    def test_all_valid_transitions(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)

        # backlog -> in_progress
        result = update_task_status(conn, task["id"], "in_progress")
        assert result["status"] == "in_progress"

        # in_progress -> in_review
        result = update_task_status(conn, task["id"], "in_review")
        assert result["status"] == "in_review"

        # in_review -> in_progress (sent back)
        result = update_task_status(conn, task["id"], "in_progress")
        assert result["status"] == "in_progress"

        # in_progress -> in_review again
        result = update_task_status(conn, task["id"], "in_review")
        assert result["status"] == "in_review"

        # in_review -> done
        result = update_task_status(conn, task["id"], "done")
        assert result["status"] == "done"

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        update_task_status(conn, task["id"], "in_progress")
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_updated" in types

    def test_nonexistent_task_returns_error(self, conn: sqlite3.Connection) -> None:
        result = update_task_status(conn, "nonexistent", "in_progress")
        assert result.get("error") == "not_found"

    def test_cancelled_transition(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        result = update_task_status(conn, task["id"], "cancelled")
        assert result["status"] == "cancelled"


class TestGetBoard:
    def test_returns_project_and_tasks(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        create_task(conn, "T1", "D", "coder", pid)
        create_task(conn, "T2", "D", "reviewer", pid)
        result = get_board(conn, pid)
        assert result["project"]["id"] == pid
        assert len(result["tasks"]) == 2

    def test_includes_comment_count(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T1", "D", "coder", pid)
        add_comment(conn, task["id"], "hello", "human")
        add_comment(conn, task["id"], "world", "coder")
        result = get_board(conn, pid)
        assert result["tasks"][0]["comment_count"] == 2

    def test_nonexistent_project(self, conn: sqlite3.Connection) -> None:
        result = get_board(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestGetTask:
    def test_returns_task_with_comments(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        add_comment(conn, task["id"], "hello", "human")
        result = get_task(conn, task["id"])
        assert result["title"] == "T"
        assert len(result["comments"]) == 1
        assert result["comments"][0]["content"] == "hello"

    def test_comments_in_chronological_order(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        add_comment(conn, task["id"], "first", "human")
        add_comment(conn, task["id"], "second", "coder")
        result = get_task(conn, task["id"])
        assert result["comments"][0]["content"] == "first"
        assert result["comments"][1]["content"] == "second"

    def test_nonexistent_task(self, conn: sqlite3.Connection) -> None:
        result = get_task(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestGetMyTasks:
    def test_returns_only_in_progress_for_phase(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        t1 = create_task(conn, "T1", "D", "coder", pid)
        create_task(conn, "T2", "D", "coder", pid)  # stays backlog
        create_task(conn, "T3", "D", "reviewer", pid)  # different phase
        update_task_status(conn, t1["id"], "in_progress")
        result = get_my_tasks(conn, "coder")
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["id"] == t1["id"]

    def test_invalid_phase_returns_error(self, conn: sqlite3.Connection) -> None:
        result = get_my_tasks(conn, "invalid")
        assert result.get("error") == "invalid_phase"

    def test_empty_when_no_in_progress(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        create_task(conn, "T1", "D", "coder", pid)
        result = get_my_tasks(conn, "coder")
        assert result["tasks"] == []


class TestAddComment:
    def test_creates_comment(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        result = add_comment(conn, task["id"], "Test comment", "human")
        assert result["content"] == "Test comment"
        assert result["author_role"] == "human"

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        add_comment(conn, task["id"], "Test", "human")
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "comment_added" in types

    def test_invalid_role_returns_error(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        result = add_comment(conn, task["id"], "x", "invalid_role")
        assert result.get("error") == "invalid_role"

    def test_nonexistent_task_returns_error(self, conn: sqlite3.Connection) -> None:
        result = add_comment(conn, "nonexistent", "x", "human")
        assert result.get("error") == "not_found"


class TestCompleteTask:
    def test_marks_done_from_in_review(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        update_task_status(conn, task["id"], "in_progress")
        update_task_status(conn, task["id"], "in_review")
        result = complete_task(conn, task["id"])
        assert result["task"]["status"] == "done"

    def test_cannot_complete_from_backlog(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        result = complete_task(conn, task["id"])
        assert result.get("error") == "invalid_transition"

    def test_detects_siblings_complete(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        parent = create_task(conn, "Parent", "P", "planner", pid)
        subs = create_subtasks(
            conn,
            parent["id"],
            [
                {"title": "S1", "phase": "coder"},
                {"title": "S2", "phase": "coder"},
            ],
        )
        s1_id = subs["created"][0]["id"]
        s2_id = subs["created"][1]["id"]

        # Move both through pipeline
        for sid in [s1_id, s2_id]:
            update_task_status(conn, sid, "in_progress")
            update_task_status(conn, sid, "in_review")

        # Complete first — siblings not all done yet
        r1 = complete_task(conn, s1_id)
        assert r1["siblings_complete"] is False
        assert r1["orchestrator_task_id"] is None

        # Complete second — now all siblings done
        r2 = complete_task(conn, s2_id)
        assert r2["siblings_complete"] is True
        assert r2["orchestrator_task_id"] is not None

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid = _seed_project(conn)
        task = create_task(conn, "T", "D", "coder", pid)
        update_task_status(conn, task["id"], "in_progress")
        update_task_status(conn, task["id"], "in_review")
        complete_task(conn, task["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_updated" in types

    def test_nonexistent_task_returns_error(self, conn: sqlite3.Connection) -> None:
        result = complete_task(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestEventEmission:
    def test_every_write_emits_event(self, conn: sqlite3.Connection) -> None:
        """Verify that every write operation creates an event row."""
        pid = _seed_project(conn)

        # create_task
        task = create_task(conn, "T", "D", "coder", pid)
        # add_comment
        add_comment(conn, task["id"], "hi", "human")
        # update_task_status
        update_task_status(conn, task["id"], "in_progress")
        # create_subtasks
        parent = create_task(conn, "Parent", "P", "planner", pid)
        create_subtasks(conn, parent["id"], [{"title": "S", "phase": "coder"}])

        events = conn.execute("SELECT type FROM events ORDER BY created_at").fetchall()
        types = [e["type"] for e in events]
        assert "task_created" in types
        assert "comment_added" in types
        assert "task_updated" in types
        assert "subtasks_created" in types
        assert len(events) >= 4


class TestCompleteTaskOrchestratorCreation:
    def test_creates_orchestrator_when_siblings_complete(
        self, conn: sqlite3.Connection
    ) -> None:
        """When all siblings are done, complete_task creates an orchestrator task."""
        # Create a project and parent planner task
        pid = _seed_project(conn)
        parent_task = create_task(conn, "Plan", "P", "planner", pid)

        # Create two coder subtasks under the parent
        t1 = create_task(
            conn, "Code A", "", "coder", pid, parent_task_id=parent_task["id"]
        )
        t2 = create_task(
            conn, "Code B", "", "coder", pid, parent_task_id=parent_task["id"]
        )

        # Move both through the state machine to in_review
        update_task_status(conn, t1["id"], "in_progress")
        update_task_status(conn, t1["id"], "in_review")
        update_task_status(conn, t2["id"], "in_progress")
        update_task_status(conn, t2["id"], "in_review")

        # Complete first — siblings not all done yet
        r1 = complete_task(conn, t1["id"])
        assert r1["siblings_complete"] is False
        assert r1["orchestrator_task_id"] is None

        # Complete second — triggers orchestrator
        r2 = complete_task(conn, t2["id"])
        assert r2["siblings_complete"] is True
        assert r2["orchestrator_task_id"] is not None

        # Verify orchestrator task was created correctly
        orch = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (r2["orchestrator_task_id"],)
        ).fetchone()
        assert orch["phase"] == "orchestrator"
        assert orch["status"] == "in_progress"
        assert orch["parent_task_id"] == parent_task["id"]
        assert orch["project_id"] == pid

    def test_no_orchestrator_for_task_without_parent(
        self, conn: sqlite3.Connection
    ) -> None:
        """complete_task on a root task (no parent) does not create orchestrator."""
        pid = _seed_project(conn)
        t = create_task(conn, "Solo", "", "coder", pid)
        update_task_status(conn, t["id"], "in_progress")
        update_task_status(conn, t["id"], "in_review")
        result = complete_task(conn, t["id"])
        assert result["siblings_complete"] is False
        assert result["orchestrator_task_id"] is None

    def test_no_orchestrator_when_siblings_not_all_done(
        self, conn: sqlite3.Connection
    ) -> None:
        """complete_task doesn't create orchestrator when some siblings still pending."""
        pid = _seed_project(conn)
        parent = create_task(conn, "Plan", "", "planner", pid)
        t1 = create_task(conn, "A", "", "coder", pid, parent_task_id=parent["id"])
        create_task(conn, "B", "", "coder", pid, parent_task_id=parent["id"])

        update_task_status(conn, t1["id"], "in_progress")
        update_task_status(conn, t1["id"], "in_review")
        # t2 stays in backlog

        r1 = complete_task(conn, t1["id"])
        assert r1["siblings_complete"] is False
        assert r1["orchestrator_task_id"] is None
