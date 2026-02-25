"""FastAPI dependency injection and DB helpers for vibe-relay."""

import json
import sqlite3
from collections.abc import Generator
from typing import Any

from db.client import get_connection


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
    """Fetch unconsumed trigger events."""
    rows = conn.execute(
        """SELECT id, type, payload, created_at FROM events
           WHERE trigger_consumed = 0
             AND type IN (
                 'task_created', 'task_moved', 'task_cancelled',
                 'plan_approved', 'task_ready', 'milestone_completed'
             )
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


def get_task_counts_by_step(
    conn: sqlite3.Connection, project_id: str
) -> dict[str, int]:
    """Return task count per workflow step for a project (excluding cancelled)."""
    steps = conn.execute(
        "SELECT id, name FROM workflow_steps WHERE project_id = ? ORDER BY position",
        (project_id,),
    ).fetchall()

    counts: dict[str, int] = {s["name"]: 0 for s in steps}
    counts["cancelled"] = 0

    rows = conn.execute(
        """SELECT ws.name as step_name, t.cancelled, COUNT(*) as cnt
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.project_id = ?
           GROUP BY ws.name, t.cancelled""",
        (project_id,),
    ).fetchall()

    for row in rows:
        if row["cancelled"]:
            counts["cancelled"] += row["cnt"]
        else:
            counts[row["step_name"]] = row["cnt"]

    return counts


def get_tasks_grouped_by_step(
    conn: sqlite3.Connection, project_id: str
) -> dict[str, Any]:
    """Return all tasks for a project grouped by workflow step."""
    steps = conn.execute(
        """SELECT id, name, position,
                  system_prompt IS NOT NULL as has_agent,
                  model, color
           FROM workflow_steps
           WHERE project_id = ?
           ORDER BY position""",
        (project_id,),
    ).fetchall()

    tasks_by_step: dict[str, list[dict[str, Any]]] = {s["id"]: [] for s in steps}
    cancelled: list[dict[str, Any]] = []

    rows = conn.execute(
        """SELECT t.*,
                  ws.name as step_name,
                  ws.position as step_position,
                  EXISTS(
                      SELECT 1 FROM agent_runs ar
                      WHERE ar.task_id = t.id AND ar.completed_at IS NULL
                  ) as has_active_run
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.project_id = ?
           ORDER BY t.created_at""",
        (project_id,),
    ).fetchall()

    for row in rows:
        task = dict(row)
        task["cancelled"] = bool(task["cancelled"])
        task["plan_approved"] = bool(task.get("plan_approved", 0))
        task["has_active_run"] = bool(task.get("has_active_run", 0))
        if task["cancelled"]:
            cancelled.append(task)
        else:
            step_list = tasks_by_step.get(task["step_id"])
            if step_list is not None:
                step_list.append(task)

    # Fetch dependencies
    all_deps = conn.execute(
        """SELECT td.id, td.predecessor_id, td.successor_id
           FROM task_dependencies td
           JOIN tasks t ON td.predecessor_id = t.id
           WHERE t.project_id = ?""",
        (project_id,),
    ).fetchall()

    return {
        "steps": [dict(s) for s in steps],
        "tasks": tasks_by_step,
        "cancelled": cancelled,
        "dependencies": [dict(d) for d in all_deps],
    }


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

    if event_type in (
        "task_created",
        "task_moved",
        "task_cancelled",
        "task_uncancelled",
        "plan_approved",
        "task_ready",
        "task_updated",
        "milestone_completed",
    ):
        task_id = payload.get("task_id")
        if task_id:
            task = conn.execute(
                """SELECT t.*,
                          ws.name as step_name,
                          ws.position as step_position,
                          EXISTS(
                              SELECT 1 FROM agent_runs ar
                              WHERE ar.task_id = t.id AND ar.completed_at IS NULL
                          ) as has_active_run
                   FROM tasks t
                   JOIN workflow_steps ws ON t.step_id = ws.id
                   WHERE t.id = ?""",
                (task_id,),
            ).fetchone()
            if task:
                task_dict = dict(task)
                task_dict["cancelled"] = bool(task_dict["cancelled"])
                task_dict["has_active_run"] = bool(task_dict.get("has_active_run", 0))
                return {"type": event_type, "payload": task_dict}

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
