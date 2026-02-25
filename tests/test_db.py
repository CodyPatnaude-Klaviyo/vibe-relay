"""Tests for the database layer.

Verifies:
- DB creation and migrations
- WAL mode enabled
- Foreign key enforcement
- Idempotent migrations (running twice doesn't error)
- Table creation verification
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
        assert table_names == [
            "agent_runs",
            "comments",
            "events",
            "ports",
            "projects",
            "task_dependencies",
            "tasks",
            "workflow_steps",
        ]

    def test_wal_mode_enabled(self, conn: sqlite3.Connection) -> None:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, conn: sqlite3.Connection) -> None:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_idempotent(self, conn: sqlite3.Connection) -> None:
        """Running migrations twice should not raise."""
        run_migrations(conn)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(t[0] for t in tables)
        assert table_names == [
            "agent_runs",
            "comments",
            "events",
            "ports",
            "projects",
            "task_dependencies",
            "tasks",
            "workflow_steps",
        ]


class TestForeignKeyConstraints:
    def test_task_requires_valid_project(self, conn: sqlite3.Connection) -> None:
        """Inserting a task with a nonexistent project_id should fail."""
        task_id = _uuid()
        fake_project_id = _uuid()
        now = _now()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (id, project_id, title, step_id, cancelled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 0, ?, ?)",
                (task_id, fake_project_id, "Orphan Task", _uuid(), now, now),
            )
