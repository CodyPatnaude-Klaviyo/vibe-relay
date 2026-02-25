"""Tests for the database layer.

Verifies:
- DB creation and migrations
- WAL mode enabled
- Table creation with correct columns
- Insert and read for projects and tasks
- Foreign key constraint enforcement between tasks and projects
- Idempotent migrations (running twice doesn't error)
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from db.client import get_connection
from db.migrations import init_db, run_migrations


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    connection = init_db(db_path)
    yield connection
    connection.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


class TestMigrations:
    def test_creates_all_tables(self, conn: sqlite3.Connection) -> None:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(t[0] for t in tables)
        assert table_names == ["agent_runs", "comments", "events", "ports", "projects", "tasks"]

    def test_wal_mode_enabled(self, conn: sqlite3.Connection) -> None:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, conn: sqlite3.Connection) -> None:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_idempotent(self, conn: sqlite3.Connection) -> None:
        """Running migrations twice should not raise."""
        run_migrations(conn)
        # Verify tables still exist
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(t[0] for t in tables)
        assert table_names == ["agent_runs", "comments", "events", "ports", "projects", "tasks"]


class TestProjectCRUD:
    def test_insert_and_read_project(self, conn: sqlite3.Connection) -> None:
        project_id = _uuid()
        now = _now()

        conn.execute(
            "INSERT INTO projects (id, title, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, "Test Project", "A test project", "active", now, now),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()

        assert row["id"] == project_id
        assert row["title"] == "Test Project"
        assert row["description"] == "A test project"
        assert row["status"] == "active"
        assert row["created_at"] == now
        assert row["updated_at"] == now


class TestTaskCRUD:
    def test_insert_and_read_task(self, conn: sqlite3.Connection) -> None:
        project_id = _uuid()
        task_id = _uuid()
        now = _now()

        conn.execute(
            "INSERT INTO projects (id, title, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, "Test Project", "active", now, now),
        )
        conn.execute(
            "INSERT INTO tasks (id, project_id, title, phase, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, project_id, "Test Task", "coder", "backlog", now, now),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

        assert row["id"] == task_id
        assert row["project_id"] == project_id
        assert row["title"] == "Test Task"
        assert row["phase"] == "coder"
        assert row["status"] == "backlog"

    def test_foreign_key_constraint(self, conn: sqlite3.Connection) -> None:
        """Inserting a task with a nonexistent project_id should fail."""
        task_id = _uuid()
        fake_project_id = _uuid()
        now = _now()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (id, project_id, title, phase, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, fake_project_id, "Orphan Task", "coder", "backlog", now, now),
            )


class TestTaskColumns:
    def test_task_has_all_columns(self, conn: sqlite3.Connection) -> None:
        """Verify the tasks table has every column defined in the schema."""
        columns = conn.execute("PRAGMA table_info(tasks)").fetchall()
        column_names = [c["name"] for c in columns]
        expected = [
            "id",
            "project_id",
            "parent_task_id",
            "title",
            "description",
            "phase",
            "status",
            "worktree_path",
            "branch",
            "session_id",
            "created_at",
            "updated_at",
        ]
        assert column_names == expected

    def test_project_has_all_columns(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(projects)").fetchall()
        column_names = [c["name"] for c in columns]
        expected = ["id", "title", "description", "status", "created_at", "updated_at"]
        assert column_names == expected

    def test_comments_has_all_columns(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(comments)").fetchall()
        column_names = [c["name"] for c in columns]
        expected = ["id", "task_id", "author_role", "content", "created_at"]
        assert column_names == expected

    def test_agent_runs_has_all_columns(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(agent_runs)").fetchall()
        column_names = [c["name"] for c in columns]
        expected = [
            "id",
            "task_id",
            "phase",
            "started_at",
            "completed_at",
            "exit_code",
            "error",
        ]
        assert column_names == expected

    def test_ports_has_all_columns(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(ports)").fetchall()
        column_names = [c["name"] for c in columns]
        expected = ["port", "task_id", "allocated_at"]
        assert column_names == expected

    def test_events_has_all_columns(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(events)").fetchall()
        column_names = [c["name"] for c in columns]
        expected = ["id", "type", "payload", "created_at", "consumed"]
        assert column_names == expected
