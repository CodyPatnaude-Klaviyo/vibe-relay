"""Tests for SDLC planning features: dependencies, approval, auto-advance, cascading unblock.

Covers:
- Schema: type, plan_approved, output columns; task_dependencies table
- Dependencies: add/remove CRUD, cycle detection, is_blocked
- Approval: approve_plan sets flag, emits events, rejects invalid cases
- Auto-advance: sibling completion moves parent milestone forward
- Cascading unblock: completing a task unblocks dependents
- Trigger processor: approval gating, dependency gating
- API endpoints: approve, dependency CRUD, updated responses
"""

import sqlite3
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from db.migrations import init_db
from vibe_relay.mcp.tools import (
    add_dependency,
    approve_plan,
    cancel_task,
    complete_task,
    create_task,
    create_workflow_steps,
    get_board,
    get_dependencies,
    get_task,
    has_cycle,
    is_blocked,
    move_task,
    remove_dependency,
    set_task_output,
)


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = init_db(tmp_path / "test.db")
    yield connection
    connection.close()


def _seed_project(conn: sqlite3.Connection, title: str = "Test Project") -> str:
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, title, "active", now, now),
    )
    conn.commit()
    return pid


def _seed_7step_workflow(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    """Create the full 7-step SDLC workflow."""
    steps = [
        {"name": "Plan", "system_prompt": "You are a planner"},
        {"name": "Design", "system_prompt": "You are a designer"},
        {"name": "Backlog"},
        {"name": "Implement", "system_prompt": "You are a coder"},
        {"name": "Test", "system_prompt": "You are a tester"},
        {"name": "Review", "system_prompt": "You are a reviewer"},
        {"name": "Done"},
    ]
    result = create_workflow_steps(conn, project_id, steps)
    return result["steps"]


def _seed_project_with_7steps(
    conn: sqlite3.Connection,
) -> tuple[str, list[dict]]:
    pid = _seed_project(conn)
    steps = _seed_7step_workflow(conn, pid)
    return pid, steps


def _seed_4step_workflow(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    """Create a simpler 4-step workflow for basic tests."""
    steps = [
        {"name": "Plan", "system_prompt": "You are a planner"},
        {"name": "Implement", "system_prompt": "You are a coder"},
        {"name": "Review", "system_prompt": "You are a reviewer"},
        {"name": "Done"},
    ]
    result = create_workflow_steps(conn, project_id, steps)
    return result["steps"]


def _seed_project_with_4steps(
    conn: sqlite3.Connection,
) -> tuple[str, list[dict]]:
    pid = _seed_project(conn)
    steps = _seed_4step_workflow(conn, pid)
    return pid, steps


# ── Schema tests ──────────────────────────────────────────


class TestSchemaSDLC:
    def test_task_has_type_column(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(tasks)").fetchall()
        col_names = [c["name"] for c in columns]
        assert "type" in col_names

    def test_task_has_plan_approved_column(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(tasks)").fetchall()
        col_names = [c["name"] for c in columns]
        assert "plan_approved" in col_names

    def test_task_has_output_column(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(tasks)").fetchall()
        col_names = [c["name"] for c in columns]
        assert "output" in col_names

    def test_task_dependencies_table_exists(self, conn: sqlite3.Connection) -> None:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='task_dependencies'"
        ).fetchall()
        assert len(tables) == 1

    def test_task_dependencies_columns(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(task_dependencies)").fetchall()
        col_names = [c["name"] for c in columns]
        assert col_names == ["id", "predecessor_id", "successor_id", "created_at"]

    def test_task_type_default(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "Test", "D", steps[0]["id"], pid)
        assert task["type"] == "task"

    def test_task_type_milestone(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(
            conn, "Milestone", "D", steps[0]["id"], pid, task_type="milestone"
        )
        assert task["type"] == "milestone"

    def test_task_type_research(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(
            conn, "Research", "D", steps[0]["id"], pid, task_type="research"
        )
        assert task["type"] == "research"

    def test_invalid_task_type_returns_error(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        result = create_task(conn, "Bad", "D", steps[0]["id"], pid, task_type="invalid")
        assert result.get("error") == "invalid_input"


# ── Dependency CRUD tests ────────────────────────────────


class TestAddDependency:
    def test_creates_dependency(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        result = add_dependency(conn, t1["id"], t2["id"])
        assert "id" in result
        assert result["predecessor_id"] == t1["id"]
        assert result["successor_id"] == t2["id"]

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "dependency_created" in types

    def test_self_reference_rejected(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        result = add_dependency(conn, t1["id"], t1["id"])
        assert result.get("error") == "invalid_input"
        assert "itself" in result["message"]

    def test_duplicate_rejected(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        result = add_dependency(conn, t1["id"], t2["id"])
        assert result.get("error") == "invalid_input"

    def test_nonexistent_predecessor_rejected(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        result = add_dependency(conn, "nonexistent", t1["id"])
        assert result.get("error") == "not_found"

    def test_nonexistent_successor_rejected(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        result = add_dependency(conn, t1["id"], "nonexistent")
        assert result.get("error") == "not_found"


class TestCycleDetection:
    def test_simple_cycle_rejected(self, conn: sqlite3.Connection) -> None:
        """A -> B -> A should be rejected."""
        pid, steps = _seed_project_with_4steps(conn)
        a = create_task(conn, "A", "D", steps[0]["id"], pid)
        b = create_task(conn, "B", "D", steps[0]["id"], pid)
        add_dependency(conn, a["id"], b["id"])  # A -> B
        result = add_dependency(conn, b["id"], a["id"])  # B -> A (cycle!)
        assert result.get("error") == "invalid_input"
        assert "cycle" in result["message"]

    def test_long_cycle_rejected(self, conn: sqlite3.Connection) -> None:
        """A -> B -> C -> A should be rejected."""
        pid, steps = _seed_project_with_4steps(conn)
        a = create_task(conn, "A", "D", steps[0]["id"], pid)
        b = create_task(conn, "B", "D", steps[0]["id"], pid)
        c = create_task(conn, "C", "D", steps[0]["id"], pid)
        add_dependency(conn, a["id"], b["id"])  # A -> B
        add_dependency(conn, b["id"], c["id"])  # B -> C
        result = add_dependency(conn, c["id"], a["id"])  # C -> A (cycle!)
        assert result.get("error") == "invalid_input"
        assert "cycle" in result["message"]

    def test_no_false_positive(self, conn: sqlite3.Connection) -> None:
        """A -> B, A -> C is fine (no cycle)."""
        pid, steps = _seed_project_with_4steps(conn)
        a = create_task(conn, "A", "D", steps[0]["id"], pid)
        b = create_task(conn, "B", "D", steps[0]["id"], pid)
        c = create_task(conn, "C", "D", steps[0]["id"], pid)
        add_dependency(conn, a["id"], b["id"])
        result = add_dependency(conn, a["id"], c["id"])
        assert "error" not in result

    def test_has_cycle_function_directly(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        a = create_task(conn, "A", "D", steps[0]["id"], pid)
        b = create_task(conn, "B", "D", steps[0]["id"], pid)
        add_dependency(conn, a["id"], b["id"])
        assert has_cycle(conn, b["id"], a["id"]) is True
        assert has_cycle(conn, a["id"], b["id"]) is False


class TestRemoveDependency:
    def test_removes_dependency(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        dep = add_dependency(conn, t1["id"], t2["id"])
        result = remove_dependency(conn, dep["id"])
        assert result["status"] == "removed"

    def test_emits_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        dep = add_dependency(conn, t1["id"], t2["id"])
        remove_dependency(conn, dep["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "dependency_removed" in types

    def test_nonexistent_dependency_rejected(self, conn: sqlite3.Connection) -> None:
        result = remove_dependency(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestGetDependencies:
    def test_returns_predecessors_and_successors(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        t3 = create_task(conn, "T3", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])  # T1 -> T2
        add_dependency(conn, t2["id"], t3["id"])  # T2 -> T3

        deps = get_dependencies(conn, t2["id"])
        assert len(deps["predecessors"]) == 1
        assert deps["predecessors"][0]["predecessor_id"] == t1["id"]
        assert len(deps["successors"]) == 1
        assert deps["successors"][0]["successor_id"] == t3["id"]

    def test_nonexistent_task(self, conn: sqlite3.Connection) -> None:
        result = get_dependencies(conn, "nonexistent")
        assert result.get("error") == "not_found"


class TestIsBlocked:
    def test_unblocked_when_no_deps(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        assert is_blocked(conn, t1["id"]) is False

    def test_blocked_when_predecessor_not_done(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        assert is_blocked(conn, t2["id"]) is True

    def test_unblocked_when_predecessor_done(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        # Move t1 to Done
        complete_task(conn, t1["id"])
        assert is_blocked(conn, t2["id"]) is False

    def test_blocked_when_one_of_many_predecessors_not_done(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        t3 = create_task(conn, "T3", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t3["id"])
        add_dependency(conn, t2["id"], t3["id"])
        complete_task(conn, t1["id"])
        # t2 still not done, so t3 remains blocked
        assert is_blocked(conn, t3["id"]) is True


# ── Approval tests ───────────────────────────────────────


class TestApprovePlan:
    def test_approves_milestone(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        # Need at least one child
        create_task(
            conn, "Child", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        result = approve_plan(conn, milestone["id"])
        assert result.get("plan_approved") is True

    def test_emits_plan_approved_event(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        create_task(
            conn, "Child", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        approve_plan(conn, milestone["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "plan_approved" in types

    def test_emits_task_ready_for_unblocked_children(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        create_task(
            conn, "Child", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        approve_plan(conn, milestone["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_ready" in types

    def test_rejects_non_milestone(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = approve_plan(conn, task["id"])
        assert result.get("error") == "invalid_input"
        assert "milestone" in result["message"].lower()

    def test_rejects_already_approved(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        create_task(
            conn, "Child", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        approve_plan(conn, milestone["id"])
        result = approve_plan(conn, milestone["id"])
        assert result.get("error") == "invalid_input"

    def test_rejects_no_children(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        result = approve_plan(conn, milestone["id"])
        assert result.get("error") == "invalid_input"
        assert "child" in result["message"].lower()

    def test_rejects_nonexistent_task(self, conn: sqlite3.Connection) -> None:
        result = approve_plan(conn, "nonexistent")
        assert result.get("error") == "not_found"


# ── Complete task tests ──────────────────────────────────


class TestCompleteTask:
    def test_moves_to_terminal_step(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        result = complete_task(conn, task["id"])
        assert result["step_name"] == "Done"

    def test_emits_task_moved(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        complete_task(conn, task["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_moved" in types

    def test_rejects_already_done(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        complete_task(conn, task["id"])
        result = complete_task(conn, task["id"])
        assert result.get("error") == "invalid_transition"

    def test_rejects_cancelled(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        cancel_task(conn, task["id"])
        result = complete_task(conn, task["id"])
        assert result.get("error") == "invalid_transition"

    def test_nonexistent_task(self, conn: sqlite3.Connection) -> None:
        result = complete_task(conn, "nonexistent")
        assert result.get("error") == "not_found"


# ── Cascading unblock tests ─────────────────────────────


class TestCascadeUnblock:
    def test_completing_predecessor_emits_task_ready(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        complete_task(conn, t1["id"])
        events = conn.execute("SELECT type FROM events").fetchall()
        types = [e["type"] for e in events]
        assert "task_ready" in types

    def test_partial_completion_does_not_emit_ready(
        self, conn: sqlite3.Connection
    ) -> None:
        """If a task has two predecessors, completing only one should NOT emit task_ready."""
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        t3 = create_task(conn, "T3", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t3["id"])
        add_dependency(conn, t2["id"], t3["id"])

        # Clear events before completing
        conn.execute("DELETE FROM events")
        conn.commit()

        complete_task(conn, t1["id"])
        events = conn.execute(
            "SELECT type, payload FROM events WHERE type = 'task_ready'"
        ).fetchall()
        # task_ready should NOT be emitted for t3 because t2 is still pending
        ready_for_t3 = [e for e in events if t3["id"] in e["payload"]]
        assert len(ready_for_t3) == 0

    def test_unapproved_parent_blocks_ready(self, conn: sqlite3.Connection) -> None:
        """Even if deps are met, unapproved parent milestone should prevent task_ready."""
        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        t1 = create_task(
            conn, "T1", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        t2 = create_task(
            conn, "T2", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        add_dependency(conn, t1["id"], t2["id"])

        # Clear events
        conn.execute("DELETE FROM events")
        conn.commit()

        complete_task(conn, t1["id"])
        events = conn.execute(
            "SELECT type, payload FROM events WHERE type = 'task_ready'"
        ).fetchall()
        ready_for_t2 = [e for e in events if t2["id"] in e["payload"]]
        assert len(ready_for_t2) == 0


# ── Auto-advance tests ──────────────────────────────────


class TestAutoAdvance:
    def test_all_research_complete_advances_milestone(
        self, conn: sqlite3.Connection
    ) -> None:
        """When all children of a milestone complete, parent should advance to next step."""
        pid, steps = _seed_project_with_7steps(conn)
        milestone = create_task(
            conn, "Root", "D", steps[0]["id"], pid, task_type="milestone"
        )
        r1 = create_task(
            conn,
            "Research 1",
            "D",
            steps[0]["id"],
            pid,
            parent_task_id=milestone["id"],
            task_type="research",
        )
        r2 = create_task(
            conn,
            "Research 2",
            "D",
            steps[0]["id"],
            pid,
            parent_task_id=milestone["id"],
            task_type="research",
        )

        complete_task(conn, r1["id"])
        # After r1 completes, milestone should still be at Plan
        m = get_task(conn, milestone["id"])
        assert m["step_name"] == "Plan"

        complete_task(conn, r2["id"])
        # After r2 completes, all children done → milestone jumps to Done
        m = get_task(conn, milestone["id"])
        assert m["step_name"] == "Done"

    def test_cancelled_children_ignored(self, conn: sqlite3.Connection) -> None:
        """Cancelled children should not prevent auto-advance."""
        pid, steps = _seed_project_with_7steps(conn)
        milestone = create_task(
            conn, "Root", "D", steps[0]["id"], pid, task_type="milestone"
        )
        r1 = create_task(
            conn,
            "R1",
            "D",
            steps[0]["id"],
            pid,
            parent_task_id=milestone["id"],
            task_type="research",
        )
        r2 = create_task(
            conn,
            "R2",
            "D",
            steps[0]["id"],
            pid,
            parent_task_id=milestone["id"],
            task_type="research",
        )
        cancel_task(conn, r2["id"])
        complete_task(conn, r1["id"])
        m = get_task(conn, milestone["id"])
        assert m["step_name"] == "Done"

    def test_no_advance_when_children_remain(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_7steps(conn)
        milestone = create_task(
            conn, "Root", "D", steps[0]["id"], pid, task_type="milestone"
        )
        r1 = create_task(
            conn,
            "R1",
            "D",
            steps[0]["id"],
            pid,
            parent_task_id=milestone["id"],
            task_type="research",
        )
        create_task(
            conn,
            "R2",
            "D",
            steps[0]["id"],
            pid,
            parent_task_id=milestone["id"],
            task_type="research",
        )
        complete_task(conn, r1["id"])
        m = get_task(conn, milestone["id"])
        assert m["step_name"] == "Plan"

    def test_milestone_completes_when_all_tasks_done(
        self, conn: sqlite3.Connection
    ) -> None:
        """When all child tasks under a milestone reach Done, milestone should auto-complete."""
        pid, steps = _seed_project_with_7steps(conn)
        parent_milestone = create_task(
            conn, "Parent", "D", steps[0]["id"], pid, task_type="milestone"
        )
        # Simulate: parent is in Design step after research phase
        move_task(conn, parent_milestone["id"], steps[1]["id"])  # -> Design

        child = create_task(
            conn,
            "Child",
            "D",
            steps[3]["id"],
            pid,
            parent_task_id=parent_milestone["id"],
        )
        complete_task(conn, child["id"])

        m = get_task(conn, parent_milestone["id"])
        # Parent should have advanced past Design
        assert m["step_position"] > 1


# ── Set task output tests ────────────────────────────────


class TestSetTaskOutput:
    def test_sets_output(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "R", "D", steps[0]["id"], pid, task_type="research")
        result = set_task_output(conn, task["id"], "Found: X, Y, Z")
        assert result["output"] == "Found: X, Y, Z"

    def test_output_visible_in_get_task(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "R", "D", steps[0]["id"], pid, task_type="research")
        set_task_output(conn, task["id"], "Findings here")
        result = get_task(conn, task["id"])
        assert result["output"] == "Findings here"

    def test_nonexistent_task(self, conn: sqlite3.Connection) -> None:
        result = set_task_output(conn, "nonexistent", "data")
        assert result.get("error") == "not_found"


# ── Board response tests ─────────────────────────────────


class TestBoardNewFields:
    def test_board_includes_type_and_plan_approved(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        create_task(conn, "M", "D", steps[0]["id"], pid, task_type="milestone")
        result = get_board(conn, pid)
        task = result["tasks"][steps[0]["id"]][0]
        assert "type" in task
        assert "plan_approved" in task
        assert task["type"] == "milestone"

    def test_board_includes_dependencies(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        result = get_board(conn, pid)
        assert "dependencies" in result
        assert len(result["dependencies"]) == 1

    def test_get_task_includes_dependencies(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        result = get_task(conn, t2["id"])
        assert "dependencies" in result
        assert len(result["dependencies"]["predecessors"]) == 1


# ── Trigger processor helper tests ──────────────────────


class TestTriggerGating:
    def test_is_parent_approved_no_parent(self, conn: sqlite3.Connection) -> None:
        from runner.triggers import _is_parent_approved

        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        assert _is_parent_approved(conn, task["id"]) is True

    def test_is_parent_approved_with_approved_milestone(
        self, conn: sqlite3.Connection
    ) -> None:
        from runner.triggers import _is_parent_approved

        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        child = create_task(
            conn, "C", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        approve_plan(conn, milestone["id"])
        assert _is_parent_approved(conn, child["id"]) is True

    def test_is_parent_not_approved_with_unapproved_milestone(
        self, conn: sqlite3.Connection
    ) -> None:
        from runner.triggers import _is_parent_approved

        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        child = create_task(
            conn, "C", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        assert _is_parent_approved(conn, child["id"]) is False

    def test_can_dispatch_blocks_unapproved(self, conn: sqlite3.Connection) -> None:
        from runner.triggers import _can_dispatch_task

        pid, steps = _seed_project_with_4steps(conn)
        milestone = create_task(
            conn, "M", "D", steps[0]["id"], pid, task_type="milestone"
        )
        child = create_task(
            conn, "C", "D", steps[1]["id"], pid, parent_task_id=milestone["id"]
        )
        assert _can_dispatch_task(conn, child["id"]) is False

    def test_can_dispatch_blocks_dependency(self, conn: sqlite3.Connection) -> None:
        from runner.triggers import _can_dispatch_task

        pid, steps = _seed_project_with_4steps(conn)
        t1 = create_task(conn, "T1", "D", steps[0]["id"], pid)
        t2 = create_task(conn, "T2", "D", steps[0]["id"], pid)
        add_dependency(conn, t1["id"], t2["id"])
        assert _can_dispatch_task(conn, t2["id"]) is False

    def test_can_dispatch_allows_unblocked(self, conn: sqlite3.Connection) -> None:
        from runner.triggers import _can_dispatch_task

        pid, steps = _seed_project_with_4steps(conn)
        task = create_task(conn, "T", "D", steps[0]["id"], pid)
        assert _can_dispatch_task(conn, task["id"]) is True


# ── API endpoint tests ───────────────────────────────────


class TestAPIApprove:
    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> str:
        path = str(tmp_path / "test.db")
        connection = init_db(path)
        connection.close()
        return path

    @pytest_asyncio.fixture()
    async def client(self, db_path: str) -> AsyncGenerator[AsyncClient, None]:
        app = create_app(db_path=db_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_approve_endpoint(self, client) -> None:
        # Create project
        resp = await client.post(
            "/projects", json={"title": "Test", "description": "test"}
        )
        data = resp.json()
        project_id = data["project"]["id"]
        root_task_id = data["task"]["id"]
        steps = (await client.get(f"/projects/{project_id}/steps")).json()

        # Create a child task under the root milestone
        await client.post(
            f"/projects/{project_id}/tasks",
            json={
                "title": "Child",
                "step_id": steps[1]["id"],
                "parent_task_id": root_task_id,
            },
        )

        # Approve
        resp = await client.post(f"/tasks/{root_task_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["plan_approved"] is True

    @pytest.mark.asyncio
    async def test_approve_non_milestone_422(self, client) -> None:
        resp = await client.post("/projects", json={"title": "Test"})
        data = resp.json()
        project_id = data["project"]["id"]
        steps = (await client.get(f"/projects/{project_id}/steps")).json()

        # Create a regular task
        task_resp = await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "Regular", "step_id": steps[0]["id"]},
        )
        task_id = task_resp.json()["id"]

        resp = await client.post(f"/tasks/{task_id}/approve")
        assert resp.status_code == 422


class TestAPIDependencies:
    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> str:
        path = str(tmp_path / "test.db")
        connection = init_db(path)
        connection.close()
        return path

    @pytest_asyncio.fixture()
    async def client(self, db_path: str) -> AsyncGenerator[AsyncClient, None]:
        app = create_app(db_path=db_path)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_add_dependency_endpoint(self, client) -> None:
        resp = await client.post("/projects", json={"title": "Test"})
        data = resp.json()
        project_id = data["project"]["id"]
        steps = (await client.get(f"/projects/{project_id}/steps")).json()

        t1 = (
            await client.post(
                f"/projects/{project_id}/tasks",
                json={"title": "T1", "step_id": steps[0]["id"]},
            )
        ).json()
        t2 = (
            await client.post(
                f"/projects/{project_id}/tasks",
                json={"title": "T2", "step_id": steps[0]["id"]},
            )
        ).json()

        resp = await client.post(
            f"/tasks/{t1['id']}/dependencies",
            json={"predecessor_id": t1["id"], "successor_id": t2["id"]},
        )
        assert resp.status_code == 201
        assert resp.json()["predecessor_id"] == t1["id"]

    @pytest.mark.asyncio
    async def test_get_dependencies_endpoint(self, client) -> None:
        resp = await client.post("/projects", json={"title": "Test"})
        data = resp.json()
        project_id = data["project"]["id"]
        steps = (await client.get(f"/projects/{project_id}/steps")).json()

        t1 = (
            await client.post(
                f"/projects/{project_id}/tasks",
                json={"title": "T1", "step_id": steps[0]["id"]},
            )
        ).json()
        t2 = (
            await client.post(
                f"/projects/{project_id}/tasks",
                json={"title": "T2", "step_id": steps[0]["id"]},
            )
        ).json()

        await client.post(
            f"/tasks/{t1['id']}/dependencies",
            json={"predecessor_id": t1["id"], "successor_id": t2["id"]},
        )

        resp = await client.get(f"/tasks/{t2['id']}/dependencies")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["predecessors"]) == 1

    @pytest.mark.asyncio
    async def test_delete_dependency_endpoint(self, client) -> None:
        resp = await client.post("/projects", json={"title": "Test"})
        data = resp.json()
        project_id = data["project"]["id"]
        steps = (await client.get(f"/projects/{project_id}/steps")).json()

        t1 = (
            await client.post(
                f"/projects/{project_id}/tasks",
                json={"title": "T1", "step_id": steps[0]["id"]},
            )
        ).json()
        t2 = (
            await client.post(
                f"/projects/{project_id}/tasks",
                json={"title": "T2", "step_id": steps[0]["id"]},
            )
        ).json()

        dep = (
            await client.post(
                f"/tasks/{t1['id']}/dependencies",
                json={"predecessor_id": t1["id"], "successor_id": t2["id"]},
            )
        ).json()

        resp = await client.delete(f"/dependencies/{dep['id']}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_board_response_includes_dependencies(self, client) -> None:
        resp = await client.post("/projects", json={"title": "Test"})
        data = resp.json()
        project_id = data["project"]["id"]

        resp = await client.get(f"/projects/{project_id}/tasks")
        body = resp.json()
        assert "dependencies" in body
