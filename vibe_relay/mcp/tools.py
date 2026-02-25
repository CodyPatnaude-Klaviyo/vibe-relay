"""MCP tool implementations for vibe-relay.

Each function takes a sqlite3.Connection and explicit params, returns a dict.
The server module registers these as MCP tools.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from db.state_machine import (
    VALID_AUTHOR_ROLES,
    VALID_PHASES,
    InvalidTransitionError,
    validate_transition,
)
from vibe_relay.mcp.events import emit_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


# ── Project tools ─────────────────────────────────────────


def create_project(
    conn: sqlite3.Connection,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    """Create a new project."""
    project_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO projects (id, title, description, status, created_at, updated_at)
           VALUES (?, ?, ?, 'active', ?, ?)""",
        (project_id, title, description, now, now),
    )
    emit_event(conn, "project_created", {"project_id": project_id})
    conn.commit()

    return {
        "id": project_id,
        "title": title,
        "description": description,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


# ── Read tools ────────────────────────────────────────────


def get_board(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    """Return full board state for a project."""
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        return {"error": "not_found", "message": f"Project '{project_id}' not found"}

    tasks = conn.execute(
        """SELECT t.*,
                  (SELECT COUNT(*) FROM comments c WHERE c.task_id = t.id) AS comment_count
           FROM tasks t
           WHERE t.project_id = ?
           ORDER BY t.created_at""",
        (project_id,),
    ).fetchall()

    return {
        "project": {
            "id": project["id"],
            "title": project["title"],
            "status": project["status"],
        },
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "phase": t["phase"],
                "status": t["status"],
                "parent_task_id": t["parent_task_id"],
                "comment_count": t["comment_count"],
                "branch": t["branch"],
                "worktree_path": t["worktree_path"],
            }
            for t in tasks
        ],
    }


def get_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    """Return a single task with its full comment thread."""
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    comments = conn.execute(
        "SELECT * FROM comments WHERE task_id = ? ORDER BY created_at",
        (task_id,),
    ).fetchall()

    result = _row_to_dict(task)
    result["comments"] = [_row_to_dict(c) for c in comments]
    return result


def get_my_tasks(
    conn: sqlite3.Connection,
    phase: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Return in_progress tasks for a given phase."""
    if phase not in VALID_PHASES:
        return {
            "error": "invalid_phase",
            "message": f"Unknown phase: '{phase}'. Valid: {sorted(VALID_PHASES)}",
        }

    query = """
        SELECT t.*,
               (SELECT COUNT(*) FROM comments c WHERE c.task_id = t.id) AS comment_count
        FROM tasks t
        WHERE t.phase = ? AND t.status = 'in_progress'
    """
    params: list[Any] = [phase]

    if project_id:
        query += " AND t.project_id = ?"
        params.append(project_id)

    query += " ORDER BY t.created_at"
    rows = conn.execute(query, params).fetchall()

    return {
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "phase": t["phase"],
                "status": t["status"],
                "parent_task_id": t["parent_task_id"],
                "comment_count": t["comment_count"],
                "branch": t["branch"],
                "worktree_path": t["worktree_path"],
            }
            for t in rows
        ]
    }


# ── Write tools ───────────────────────────────────────────


def create_task(
    conn: sqlite3.Connection,
    title: str,
    description: str,
    phase: str,
    project_id: str,
    parent_task_id: str | None = None,
) -> dict[str, Any]:
    """Create a single new task."""
    if phase not in VALID_PHASES:
        return {
            "error": "invalid_phase",
            "message": f"Unknown phase: '{phase}'. Valid: {sorted(VALID_PHASES)}",
        }

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        return {"error": "not_found", "message": f"Project '{project_id}' not found"}

    if parent_task_id:
        parent = conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (parent_task_id,)
        ).fetchone()
        if parent is None:
            return {
                "error": "not_found",
                "message": f"Parent task '{parent_task_id}' not found",
            }

    task_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO tasks
           (id, project_id, parent_task_id, title, description, phase, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'backlog', ?, ?)""",
        (task_id, project_id, parent_task_id, title, description, phase, now, now),
    )
    emit_event(conn, "task_created", {"task_id": task_id, "project_id": project_id})
    conn.commit()

    return {
        "id": task_id,
        "project_id": project_id,
        "parent_task_id": parent_task_id,
        "title": title,
        "description": description,
        "phase": phase,
        "status": "backlog",
        "worktree_path": None,
        "branch": None,
        "session_id": None,
        "created_at": now,
        "updated_at": now,
    }


def create_subtasks(
    conn: sqlite3.Connection,
    parent_task_id: str,
    tasks: list[dict[str, str]],
) -> dict[str, Any]:
    """Bulk create subtasks under a parent."""
    parent = conn.execute(
        "SELECT id, project_id FROM tasks WHERE id = ?", (parent_task_id,)
    ).fetchone()
    if parent is None:
        return {
            "error": "not_found",
            "message": f"Parent task '{parent_task_id}' not found",
        }

    project_id = parent["project_id"]
    created = []
    now = _now()

    for t in tasks:
        phase = t.get("phase", "coder")
        if phase not in VALID_PHASES:
            return {
                "error": "invalid_phase",
                "message": f"Unknown phase: '{phase}'. Valid: {sorted(VALID_PHASES)}",
            }

        task_id = _uuid()
        conn.execute(
            """INSERT INTO tasks
               (id, project_id, parent_task_id, title, description, phase, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'backlog', ?, ?)""",
            (
                task_id,
                project_id,
                parent_task_id,
                t["title"],
                t.get("description", ""),
                phase,
                now,
                now,
            ),
        )
        created.append(
            {
                "id": task_id,
                "project_id": project_id,
                "parent_task_id": parent_task_id,
                "title": t["title"],
                "description": t.get("description", ""),
                "phase": phase,
                "status": "backlog",
                "created_at": now,
                "updated_at": now,
            }
        )

    emit_event(
        conn,
        "subtasks_created",
        {"parent_task_id": parent_task_id, "task_ids": [t["id"] for t in created]},
    )
    conn.commit()

    return {"created": created}


def update_task_status(
    conn: sqlite3.Connection,
    task_id: str,
    status: str,
) -> dict[str, Any]:
    """Move a task to a new status, enforcing the state machine."""
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    current = task["status"]
    try:
        validate_transition(current, status)
    except InvalidTransitionError as e:
        return {"error": "invalid_transition", "message": str(e)}

    now = _now()
    conn.execute(
        "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, task_id),
    )
    emit_event(
        conn,
        "task_updated",
        {"task_id": task_id, "old_status": current, "new_status": status},
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_dict(updated)


def add_comment(
    conn: sqlite3.Connection,
    task_id: str,
    content: str,
    author_role: str,
) -> dict[str, Any]:
    """Add a comment to a task's thread."""
    if author_role not in VALID_AUTHOR_ROLES:
        return {
            "error": "invalid_role",
            "message": f"Unknown author role: '{author_role}'. Valid: {sorted(VALID_AUTHOR_ROLES)}",
        }

    task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    comment_id = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO comments (id, task_id, author_role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (comment_id, task_id, author_role, content, now),
    )
    emit_event(conn, "comment_added", {"comment_id": comment_id, "task_id": task_id})
    conn.commit()

    return {
        "id": comment_id,
        "task_id": task_id,
        "author_role": author_role,
        "content": content,
        "created_at": now,
    }


def complete_task(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any]:
    """Mark a task done and check if all siblings are complete."""
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    current = task["status"]
    try:
        validate_transition(current, "done")
    except InvalidTransitionError as e:
        return {"error": "invalid_transition", "message": str(e)}

    now = _now()
    conn.execute(
        "UPDATE tasks SET status = 'done', updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    emit_event(
        conn,
        "task_updated",
        {"task_id": task_id, "old_status": current, "new_status": "done"},
    )
    conn.commit()

    # Check sibling completion
    parent_task_id = task["parent_task_id"]
    siblings_complete = False
    orchestrator_task_id = None

    if parent_task_id:
        siblings = conn.execute(
            "SELECT status FROM tasks WHERE parent_task_id = ? AND id != ?",
            (parent_task_id, task_id),
        ).fetchall()
        siblings_complete = all(s["status"] == "done" for s in siblings)

        if siblings_complete and siblings:
            # Create orchestrator task in in_progress
            orch_id = _uuid()
            orch_now = _now()
            conn.execute(
                """INSERT INTO tasks
                   (id, project_id, parent_task_id, title, description, phase, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?)""",
                (
                    orch_id,
                    task["project_id"],
                    parent_task_id,
                    "Orchestrate: merge and verify",
                    "All sibling tasks complete. Review merged code, run checks, and finalize.",
                    "orchestrator",
                    orch_now,
                    orch_now,
                ),
            )
            emit_event(
                conn,
                "task_created",
                {"task_id": orch_id, "project_id": task["project_id"]},
            )
            emit_event(
                conn,
                "task_updated",
                {
                    "task_id": orch_id,
                    "old_status": "backlog",
                    "new_status": "in_progress",
                },
            )
            emit_event(
                conn,
                "orchestrator_trigger",
                {
                    "parent_task_id": parent_task_id,
                    "project_id": task["project_id"],
                    "orchestrator_task_id": orch_id,
                },
            )
            conn.commit()
            orchestrator_task_id = orch_id

    updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return {
        "task": _row_to_dict(updated),
        "siblings_complete": siblings_complete,
        "orchestrator_task_id": orchestrator_task_id,
    }
