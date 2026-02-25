"""Tests for runner/triggers.py — trigger processor."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from db.migrations import init_db
from runner.triggers import (
    count_active_runs,
    has_active_run,
    should_dispatch,
)


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = str(tmp_path / "test.db")
    connection = init_db(db_path)
    yield connection
    connection.close()


def _seed_project_and_task(
    conn: sqlite3.Connection,
    phase: str = "coder",
    status: str = "in_progress",
) -> tuple[str, str]:
    pid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, "Test", "active", now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, phase, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tid, pid, "Task", phase, status, now, now),
    )
    conn.commit()
    return pid, tid


def _seed_run(conn: sqlite3.Connection, task_id: str, completed: bool = False) -> str:
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    completed_at = now if completed else None
    conn.execute(
        "INSERT INTO agent_runs (id, task_id, phase, started_at, completed_at) VALUES (?, ?, ?, ?, ?)",
        (rid, task_id, "coder", now, completed_at),
    )
    conn.commit()
    return rid


class TestShouldDispatch:
    def test_task_updated_to_in_progress(self) -> None:
        event = {
            "type": "task_updated",
            "payload": {
                "task_id": "t1",
                "old_status": "backlog",
                "new_status": "in_progress",
            },
        }
        assert should_dispatch(event) is True

    def test_task_updated_to_done_not_dispatched(self) -> None:
        event = {
            "type": "task_updated",
            "payload": {
                "task_id": "t1",
                "old_status": "in_review",
                "new_status": "done",
            },
        }
        assert should_dispatch(event) is False

    def test_task_updated_to_in_review_not_dispatched(self) -> None:
        event = {
            "type": "task_updated",
            "payload": {
                "task_id": "t1",
                "old_status": "in_progress",
                "new_status": "in_review",
            },
        }
        assert should_dispatch(event) is False

    def test_orchestrator_trigger_not_dispatched(self) -> None:
        event = {
            "type": "orchestrator_trigger",
            "payload": {"parent_task_id": "p1"},
        }
        assert should_dispatch(event) is False

    def test_comment_added_not_dispatched(self) -> None:
        event = {"type": "comment_added", "payload": {"comment_id": "c1"}}
        assert should_dispatch(event) is False

    def test_in_review_to_in_progress_dispatched(self) -> None:
        """Sent-back tasks (in_review -> in_progress) should trigger agent resume."""
        event = {
            "type": "task_updated",
            "payload": {
                "task_id": "t1",
                "old_status": "in_review",
                "new_status": "in_progress",
            },
        }
        assert should_dispatch(event) is True


class TestHasActiveRun:
    def test_no_runs(self, conn: sqlite3.Connection) -> None:
        _, tid = _seed_project_and_task(conn)
        assert has_active_run(conn, tid) is False

    def test_completed_run(self, conn: sqlite3.Connection) -> None:
        _, tid = _seed_project_and_task(conn)
        _seed_run(conn, tid, completed=True)
        assert has_active_run(conn, tid) is False

    def test_active_run(self, conn: sqlite3.Connection) -> None:
        _, tid = _seed_project_and_task(conn)
        _seed_run(conn, tid, completed=False)
        assert has_active_run(conn, tid) is True


class TestCountActiveRuns:
    def test_no_runs(self, conn: sqlite3.Connection) -> None:
        assert count_active_runs(conn) == 0

    def test_counts_only_active(self, conn: sqlite3.Connection) -> None:
        _, tid1 = _seed_project_and_task(conn)
        _, tid2 = _seed_project_and_task(conn)
        _seed_run(conn, tid1, completed=False)
        _seed_run(conn, tid2, completed=True)
        assert count_active_runs(conn) == 1

    def test_multiple_active(self, conn: sqlite3.Connection) -> None:
        _, tid1 = _seed_project_and_task(conn)
        _, tid2 = _seed_project_and_task(conn)
        _seed_run(conn, tid1, completed=False)
        _seed_run(conn, tid2, completed=False)
        assert count_active_runs(conn) == 2
