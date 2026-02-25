"""Schema creation and migration logic for vibe-relay.

Migrations are idempotent — running them multiple times has no effect
because all CREATE TABLE statements use IF NOT EXISTS.

Can be run directly:
    python -m db.migrations [db_path]
"""

import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from db.client import get_connection
from db.schema import TABLE_CREATION_ORDER, TABLES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def run_migrations(conn: sqlite3.Connection) -> None:
    """Create all tables in dependency order. Idempotent."""
    for table_name in TABLE_CREATION_ORDER:
        conn.execute(TABLES[table_name])
    conn.commit()

    # Migration: add trigger_consumed column to events if it doesn't exist (Phase 6)
    try:
        conn.execute(
            "ALTER TABLE events ADD COLUMN trigger_consumed INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: transition from phase/status to step_id/cancelled (Phase 7)
    _migrate_to_workflow_steps(conn)


def _migrate_to_workflow_steps(conn: sqlite3.Connection) -> None:
    """Migrate existing projects from phase/status to workflow_steps.

    For existing databases that still have the old schema:
    - Add step_id and cancelled columns to tasks
    - Add step_id column to agent_runs
    - Create default workflow steps for each project
    - Backfill step_id from old status/phase values
    """
    # Check if this is an old-schema DB by looking for the 'phase' column
    columns = conn.execute("PRAGMA table_info(tasks)").fetchall()
    col_names = [c[1] for c in columns]

    if "phase" not in col_names:
        return  # New schema, nothing to migrate

    if "step_id" in col_names:
        return  # Already migrated

    # Add new columns
    try:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN step_id TEXT REFERENCES workflow_steps(id)"
        )
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN cancelled INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute(
            "ALTER TABLE agent_runs ADD COLUMN step_id TEXT REFERENCES workflow_steps(id)"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Create workflow_steps table if it doesn't exist
    conn.execute(TABLES["workflow_steps"])
    conn.commit()

    # Create default steps for each existing project
    default_steps = [
        ("Plan", 0, None),
        ("Implement", 1, None),
        ("Review", 2, None),
        ("Done", 3, None),
    ]

    # Map old status values to step positions
    status_to_position = {
        "backlog": 0,
        "in_progress": 0,
        "in_review": 2,
        "done": 3,
    }

    projects = conn.execute("SELECT id FROM projects").fetchall()
    for project in projects:
        project_id = project[0]
        now = _now()

        step_ids: dict[int, str] = {}
        for name, position, _ in default_steps:
            step_id = _uuid()
            step_ids[position] = step_id
            conn.execute(
                "INSERT OR IGNORE INTO workflow_steps (id, project_id, name, position, created_at) VALUES (?, ?, ?, ?, ?)",
                (step_id, project_id, name, position, now),
            )

        # Backfill step_id on tasks
        tasks = conn.execute(
            "SELECT id, status FROM tasks WHERE project_id = ?", (project_id,)
        ).fetchall()
        for task in tasks:
            task_id = task[0]
            old_status = task[1]
            position = status_to_position.get(old_status, 0)
            target_step = step_ids.get(position, step_ids[0])

            is_cancelled = 1 if old_status == "cancelled" else 0
            conn.execute(
                "UPDATE tasks SET step_id = ?, cancelled = ? WHERE id = ?",
                (target_step, is_cancelled, task_id),
            )

        # Backfill step_id on agent_runs
        phase_to_position = {
            "planner": 0,
            "coder": 1,
            "reviewer": 2,
            "orchestrator": 3,
        }
        runs = conn.execute(
            """SELECT ar.id, ar.phase FROM agent_runs ar
               JOIN tasks t ON ar.task_id = t.id
               WHERE t.project_id = ?""",
            (project_id,),
        ).fetchall()
        for run in runs:
            run_id = run[0]
            phase = run[1]
            position = phase_to_position.get(phase, 0)
            target_step = step_ids.get(position, step_ids[0])
            conn.execute(
                "UPDATE agent_runs SET step_id = ? WHERE id = ?",
                (target_step, run_id),
            )

    conn.commit()


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection, run migrations, and return the ready connection."""
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn


def main() -> None:
    """CLI entry point for running migrations directly."""
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "vibe-relay.db"

    print(f"Running migrations on {db_path}...")
    conn = init_db(db_path)

    # Verify WAL mode
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"Journal mode: {journal_mode}")

    # Verify tables
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print(f"Tables created: {[t[0] for t in tables]}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
