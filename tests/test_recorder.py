"""Tests for runner/recorder.py — agent run recorder."""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from db.migrations import init_db
from runner.recorder import complete_run, fail_run, start_run


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = init_db(tmp_path / "test.db")
    yield connection
    connection.close()


def _seed_project_and_task(conn: sqlite3.Connection) -> tuple[str, str, str]:
    """Insert a project, workflow step, and task. Return (project_id, task_id, step_id)."""
    pid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, "Test", "active", now, now),
    )
    conn.execute(
        "INSERT INTO workflow_steps (id, project_id, name, position, system_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (sid, pid, "Implement", 0, "You are a coder", now),
    )
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, step_id, cancelled, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
        (tid, pid, "Task", sid, now, now),
    )
    conn.commit()
    return pid, tid, sid


class TestStartRun:
    def test_creates_row(self, conn):
        _, tid, sid = _seed_project_and_task(conn)
        run_id = start_run(conn, tid, sid)

        row = conn.execute(
            "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row is not None
        assert row["task_id"] == tid
        assert row["step_id"] == sid
        assert row["started_at"] is not None
        assert row["completed_at"] is None
        assert row["exit_code"] is None

    def test_returns_uuid(self, conn):
        _, tid, sid = _seed_project_and_task(conn)
        run_id = start_run(conn, tid, sid)
        # Should be a valid UUID
        uuid.UUID(run_id)


class TestCompleteRun:
    def test_sets_completed_and_exit_code(self, conn):
        _, tid, sid = _seed_project_and_task(conn)
        run_id = start_run(conn, tid, sid)
        complete_run(conn, run_id, 0)

        row = conn.execute(
            "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["completed_at"] is not None
        assert row["exit_code"] == 0
        assert row["error"] is None

    def test_nonzero_exit_code(self, conn):
        _, tid, sid = _seed_project_and_task(conn)
        run_id = start_run(conn, tid, sid)
        complete_run(conn, run_id, 1)

        row = conn.execute(
            "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["exit_code"] == 1


class TestFailRun:
    def test_sets_error_and_negative_exit(self, conn):
        _, tid, sid = _seed_project_and_task(conn)
        run_id = start_run(conn, tid, sid)
        fail_run(conn, run_id, "Something broke")

        row = conn.execute(
            "SELECT * FROM agent_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["completed_at"] is not None
        assert row["exit_code"] == -1
        assert row["error"] == "Something broke"


class TestMultipleRuns:
    def test_multiple_runs_per_task(self, conn):
        _, tid, sid = _seed_project_and_task(conn)
        run1 = start_run(conn, tid, sid)
        complete_run(conn, run1, 0)
        run2 = start_run(conn, tid, sid)
        complete_run(conn, run2, 0)

        rows = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id = ?", (tid,)
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["id"] != rows[1]["id"]
