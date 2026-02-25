"""Tests for runner/triggers.py — trigger processor.

Tests should_dispatch, should_cleanup, has_active_run, count_active_runs,
and integration tests verifying trigger event flow with real DB.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from api.deps import get_unconsumed_trigger_events, mark_trigger_consumed
from db.migrations import init_db
from runner.triggers import (
    count_active_runs,
    has_active_run,
    should_cleanup,
    should_dispatch,
)
from vibe_relay.mcp.events import emit_event


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = str(tmp_path / "test.db")
    connection = init_db(db_path)
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
    """Create project with workflow steps. Returns (project_id, step_dicts)."""
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
            {
                "id": sid,
                "name": s["name"],
                "position": pos,
                "project_id": pid,
                "system_prompt": s.get("system_prompt"),
            }
        )

    conn.commit()
    return pid, created


def _seed_task(
    conn: sqlite3.Connection,
    project_id: str,
    step_id: str,
    cancelled: int = 0,
) -> str:
    tid = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, step_id, cancelled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tid, project_id, "Task", step_id, cancelled, now, now),
    )
    conn.commit()
    return tid


def _seed_run(
    conn: sqlite3.Connection, task_id: str, step_id: str, completed: bool = False
) -> str:
    rid = _uuid()
    now = _now()
    completed_at = now if completed else None
    conn.execute(
        "INSERT INTO agent_runs (id, task_id, step_id, started_at, completed_at) VALUES (?, ?, ?, ?, ?)",
        (rid, task_id, step_id, now, completed_at),
    )
    conn.commit()
    return rid


class TestShouldDispatch:
    def test_task_moved_to_agent_step_dispatches(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        event = {
            "type": "task_moved",
            "payload": {
                "task_id": "t1",
                "old_step_id": steps[0]["id"],
                "new_step_id": steps[1]["id"],  # Implement — has agent
            },
        }
        assert should_dispatch(event, conn) is True

    def test_task_moved_to_terminal_step_not_dispatched(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        event = {
            "type": "task_moved",
            "payload": {
                "task_id": "t1",
                "old_step_id": steps[2]["id"],
                "new_step_id": steps[3]["id"],  # Done — no agent
            },
        }
        assert should_dispatch(event, conn) is False

    def test_task_cancelled_not_dispatched(self, conn: sqlite3.Connection) -> None:
        event = {"type": "task_cancelled", "payload": {"task_id": "t1"}}
        assert should_dispatch(event, conn) is False

    def test_comment_added_not_dispatched(self, conn: sqlite3.Connection) -> None:
        event = {"type": "comment_added", "payload": {"comment_id": "c1"}}
        assert should_dispatch(event, conn) is False

    def test_task_created_at_agent_step_dispatches(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[1]["id"])  # Implement — has agent
        event = {
            "type": "task_created",
            "payload": {"task_id": tid},
        }
        assert should_dispatch(event, conn) is True

    def test_task_created_at_terminal_step_not_dispatched(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[3]["id"])  # Done — no agent
        event = {
            "type": "task_created",
            "payload": {"task_id": tid},
        }
        assert should_dispatch(event, conn) is False

    def test_without_conn_returns_false(self) -> None:
        event = {
            "type": "task_moved",
            "payload": {"task_id": "t1", "old_step_id": "s1", "new_step_id": "s2"},
        }
        assert should_dispatch(event) is False


class TestShouldCleanup:
    def test_task_cancelled_triggers_cleanup(self, conn: sqlite3.Connection) -> None:
        event = {"type": "task_cancelled", "payload": {"task_id": "t1"}}
        assert should_cleanup(event, conn) is True

    def test_task_moved_to_terminal_triggers_cleanup(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        event = {
            "type": "task_moved",
            "payload": {
                "task_id": "t1",
                "old_step_id": steps[2]["id"],
                "new_step_id": steps[3]["id"],  # Done — terminal
            },
        }
        assert should_cleanup(event, conn) is True

    def test_task_moved_to_agent_step_no_cleanup(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        event = {
            "type": "task_moved",
            "payload": {
                "task_id": "t1",
                "old_step_id": steps[0]["id"],
                "new_step_id": steps[1]["id"],  # Implement — has agent
            },
        }
        assert should_cleanup(event, conn) is False

    def test_comment_added_no_cleanup(self, conn: sqlite3.Connection) -> None:
        event = {"type": "comment_added", "payload": {"comment_id": "c1"}}
        assert should_cleanup(event, conn) is False


class TestHasActiveRun:
    def test_no_runs(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])
        assert has_active_run(conn, tid) is False

    def test_completed_run(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])
        _seed_run(conn, tid, steps[0]["id"], completed=True)
        assert has_active_run(conn, tid) is False

    def test_active_run(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])
        _seed_run(conn, tid, steps[0]["id"], completed=False)
        assert has_active_run(conn, tid) is True


class TestCountActiveRuns:
    def test_no_runs(self, conn: sqlite3.Connection) -> None:
        assert count_active_runs(conn) == 0

    def test_counts_only_active(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid1 = _seed_task(conn, pid, steps[0]["id"])
        tid2 = _seed_task(conn, pid, steps[1]["id"])
        _seed_run(conn, tid1, steps[0]["id"], completed=False)
        _seed_run(conn, tid2, steps[1]["id"], completed=True)
        assert count_active_runs(conn) == 1

    def test_multiple_active(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid1 = _seed_task(conn, pid, steps[0]["id"])
        tid2 = _seed_task(conn, pid, steps[1]["id"])
        _seed_run(conn, tid1, steps[0]["id"], completed=False)
        _seed_run(conn, tid2, steps[1]["id"], completed=False)
        assert count_active_runs(conn) == 2


class TestTriggerDispatchIntegration:
    """Integration tests verifying trigger event flow with real DB."""

    def test_event_emitted_and_visible_to_trigger(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])
        emit_event(
            conn,
            "task_moved",
            {
                "task_id": tid,
                "old_step_id": steps[0]["id"],
                "new_step_id": steps[1]["id"],
                "project_id": pid,
            },
        )
        conn.commit()

        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1
        assert events[0]["payload"]["task_id"] == tid

    def test_consumed_event_not_visible(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])
        emit_event(
            conn,
            "task_moved",
            {
                "task_id": tid,
                "old_step_id": steps[0]["id"],
                "new_step_id": steps[1]["id"],
                "project_id": pid,
            },
        )
        conn.commit()

        events = get_unconsumed_trigger_events(conn)
        mark_trigger_consumed(conn, events[0]["id"])

        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 0

    def test_capacity_check_blocks_dispatch(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid1 = _seed_task(conn, pid, steps[0]["id"])
        tid2 = _seed_task(conn, pid, steps[1]["id"])
        tid3 = _seed_task(conn, pid, steps[2]["id"])

        _seed_run(conn, tid1, steps[0]["id"], completed=False)
        _seed_run(conn, tid2, steps[1]["id"], completed=False)
        _seed_run(conn, tid3, steps[2]["id"], completed=False)

        assert count_active_runs(conn) == 3

        emit_event(
            conn,
            "task_moved",
            {
                "task_id": "new-task",
                "old_step_id": steps[0]["id"],
                "new_step_id": steps[1]["id"],
                "project_id": pid,
            },
        )
        conn.commit()

        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1

    def test_active_run_prevents_double_launch(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])
        _seed_run(conn, tid, steps[0]["id"], completed=False)

        assert has_active_run(conn, tid) is True

        emit_event(
            conn,
            "task_moved",
            {
                "task_id": tid,
                "old_step_id": steps[0]["id"],
                "new_step_id": steps[1]["id"],
                "project_id": pid,
            },
        )
        conn.commit()

        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1

    def test_completed_run_allows_relaunch(self, conn: sqlite3.Connection) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid = _seed_task(conn, pid, steps[0]["id"])
        _seed_run(conn, tid, steps[0]["id"], completed=True)

        assert has_active_run(conn, tid) is False

    def test_multiple_events_processed_independently(
        self, conn: sqlite3.Connection
    ) -> None:
        pid, steps = _seed_project_with_steps(conn)
        tid1 = _seed_task(conn, pid, steps[0]["id"])
        tid2 = _seed_task(conn, pid, steps[1]["id"])

        emit_event(
            conn,
            "task_moved",
            {
                "task_id": tid1,
                "old_step_id": steps[0]["id"],
                "new_step_id": steps[1]["id"],
                "project_id": pid,
            },
        )
        emit_event(
            conn,
            "task_moved",
            {
                "task_id": tid2,
                "old_step_id": steps[1]["id"],
                "new_step_id": steps[2]["id"],
                "project_id": pid,
            },
        )
        conn.commit()

        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 2

        mark_trigger_consumed(conn, events[0]["id"])

        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1
        assert events[0]["payload"]["task_id"] == tid2
