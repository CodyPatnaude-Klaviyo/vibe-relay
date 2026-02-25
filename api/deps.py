"""FastAPI dependency injection and DB helpers for vibe-relay."""

import json
import sqlite3
from collections.abc import Generator
from typing import Any

from db.client import get_connection
from db.state_machine import VALID_STATUSES


# Module-level DB path — set by app startup
_db_path: str = ""


def set_db_path(path: str) -> None:
    """Set the database path used by the DB dependency."""
    global _db_path  # noqa: PLW0603
    _db_path = path


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency that yields a DB connection per request."""
    conn = get_connection(_db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_unconsumed_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Fetch all unconsumed events from the events table."""
    rows = conn.execute(
        "SELECT id, type, payload, created_at FROM events WHERE consumed = 0 ORDER BY created_at"
    ).fetchall()
    return [
        {
            "id": row["id"],
            "type": row["type"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def mark_event_consumed(conn: sqlite3.Connection, event_id: str) -> None:
    """Mark an event as consumed."""
    conn.execute("UPDATE events SET consumed = 1 WHERE id = ?", (event_id,))
    conn.commit()


def get_unconsumed_trigger_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Fetch unconsumed trigger events (task state changes and orchestrator triggers)."""
    rows = conn.execute(
        """SELECT id, type, payload, created_at FROM events
           WHERE trigger_consumed = 0
             AND type IN ('task_updated', 'orchestrator_trigger')
           ORDER BY created_at"""
    ).fetchall()
    return [
        {
            "id": row["id"],
            "type": row["type"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def mark_trigger_consumed(conn: sqlite3.Connection, event_id: str) -> None:
    """Mark an event as consumed by the trigger processor."""
    conn.execute("UPDATE events SET trigger_consumed = 1 WHERE id = ?", (event_id,))
    conn.commit()


def get_task_counts_by_status(
    conn: sqlite3.Connection, project_id: str
) -> dict[str, int]:
    """Return task count per status for a project."""
    counts: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE project_id = ? GROUP BY status",
        (project_id,),
    ).fetchall()
    for row in rows:
        counts[row["status"]] = row["cnt"]
    return counts


def get_tasks_grouped_by_status(
    conn: sqlite3.Connection, project_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Return all tasks for a project grouped by status column."""
    result: dict[str, list[dict[str, Any]]] = {s: [] for s in VALID_STATUSES}
    rows = conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at",
        (project_id,),
    ).fetchall()
    for row in rows:
        result[row["status"]].append(dict(row))
    return result


def get_agent_runs(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """Return agent run history for a task."""
    rows = conn.execute(
        "SELECT * FROM agent_runs WHERE task_id = ? ORDER BY started_at",
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def enrich_event_payload(
    conn: sqlite3.Connection, event: dict[str, Any]
) -> dict[str, Any]:
    """Build a websocket event with full object payload, not just IDs."""
    event_type = event["type"]
    payload = event["payload"]

    if event_type in ("task_created", "task_updated"):
        task_id = payload.get("task_id")
        if task_id:
            task = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task:
                return {"type": event_type, "payload": dict(task)}

    elif event_type == "comment_added":
        comment_id = payload.get("comment_id")
        if comment_id:
            comment = conn.execute(
                "SELECT * FROM comments WHERE id = ?", (comment_id,)
            ).fetchone()
            if comment:
                return {"type": event_type, "payload": dict(comment)}

    elif event_type == "project_created":
        project_id = payload.get("project_id")
        if project_id:
            project = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project:
                return {"type": event_type, "payload": dict(project)}

    # Fallback: return raw payload
    return {"type": event_type, "payload": payload}
