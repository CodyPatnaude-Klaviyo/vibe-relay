"""Agent run recorder for vibe-relay.

Writes to the agent_runs table to track when agents start,
complete, or fail.
"""

import sqlite3
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def start_run(conn: sqlite3.Connection, task_id: str, step_id: str) -> str:
    """Record the start of an agent run.

    Args:
        conn: Active SQLite connection.
        task_id: The task being worked on.
        step_id: The workflow step ID for this run.

    Returns:
        The generated run_id (UUID4).
    """
    run_id = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO agent_runs (id, task_id, step_id, started_at) VALUES (?, ?, ?, ?)",
        (run_id, task_id, step_id, now),
    )
    conn.commit()
    return run_id


def complete_run(conn: sqlite3.Connection, run_id: str, exit_code: int) -> None:
    """Record successful completion of an agent run.

    Args:
        conn: Active SQLite connection.
        run_id: The run to update.
        exit_code: Process exit code (0 = success).
    """
    now = _now()
    conn.execute(
        "UPDATE agent_runs SET completed_at = ?, exit_code = ? WHERE id = ?",
        (now, exit_code, run_id),
    )
    conn.commit()


def fail_run(conn: sqlite3.Connection, run_id: str, error: str) -> None:
    """Record a failed agent run.

    Args:
        conn: Active SQLite connection.
        run_id: The run to update.
        error: Error message describing the failure.
    """
    now = _now()
    conn.execute(
        "UPDATE agent_runs SET completed_at = ?, exit_code = -1, error = ? WHERE id = ?",
        (now, error, run_id),
    )
    conn.commit()
