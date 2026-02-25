"""MCP tool implementations for vibe-relay.

Each function takes a sqlite3.Connection and explicit params, returns a dict.
The server module registers these as MCP tools.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from db.state_machine import (
    InvalidTransitionError,
    cancel_task as _validate_cancel,
    uncancel_task as _validate_uncancel,
    validate_step_transition,
)
from vibe_relay.mcp.events import emit_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


# ── Workflow step tools ──────────────────────────────────


def create_workflow_steps(
    conn: sqlite3.Connection,
    project_id: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bulk create workflow steps for a project.

    Each step dict should have: name (required), system_prompt (optional),
    model (optional), color (optional).
    Steps are ordered by their position in the list.
    """
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        return {"error": "not_found", "message": f"Project '{project_id}' not found"}

    if not steps:
        return {"error": "invalid_input", "message": "At least one step is required"}

    created = []
    now = _now()

    for position, step in enumerate(steps):
        name = step.get("name")
        if not name:
            return {
                "error": "invalid_input",
                "message": f"Step at position {position} missing 'name'",
            }

        step_id = _uuid()
        conn.execute(
            """INSERT INTO workflow_steps
               (id, project_id, name, position, system_prompt, model, color, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                step_id,
                project_id,
                name,
                position,
                step.get("system_prompt"),
                step.get("model"),
                step.get("color"),
                now,
            ),
        )
        created.append(
            {
                "id": step_id,
                "project_id": project_id,
                "name": name,
                "position": position,
                "has_agent": step.get("system_prompt") is not None,
                "model": step.get("model"),
                "color": step.get("color"),
                "created_at": now,
            }
        )

    conn.commit()
    return {"steps": created}


def get_workflow_steps(
    conn: sqlite3.Connection,
    project_id: str,
) -> dict[str, Any]:
    """Return ordered workflow steps for a project."""
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        return {"error": "not_found", "message": f"Project '{project_id}' not found"}

    rows = conn.execute(
        """SELECT id, project_id, name, position,
                  system_prompt IS NOT NULL as has_agent,
                  model, color, created_at
           FROM workflow_steps
           WHERE project_id = ?
           ORDER BY position""",
        (project_id,),
    ).fetchall()

    return {"steps": [_row_to_dict(r) for r in rows]}


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
    """Return full board state for a project, grouped by workflow step."""
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        return {"error": "not_found", "message": f"Project '{project_id}' not found"}

    steps = conn.execute(
        """SELECT id, name, position,
                  system_prompt IS NOT NULL as has_agent,
                  model, color
           FROM workflow_steps
           WHERE project_id = ?
           ORDER BY position""",
        (project_id,),
    ).fetchall()

    tasks = conn.execute(
        """SELECT t.*,
                  ws.name as step_name,
                  ws.position as step_position,
                  (SELECT COUNT(*) FROM comments c WHERE c.task_id = t.id) AS comment_count
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.project_id = ?
           ORDER BY t.created_at""",
        (project_id,),
    ).fetchall()

    # Group tasks by step_id, separate cancelled
    tasks_by_step: dict[str, list[dict[str, Any]]] = {s["id"]: [] for s in steps}
    cancelled: list[dict[str, Any]] = []

    for t in tasks:
        task_dict = {
            "id": t["id"],
            "title": t["title"],
            "step_id": t["step_id"],
            "step_name": t["step_name"],
            "step_position": t["step_position"],
            "cancelled": bool(t["cancelled"]),
            "parent_task_id": t["parent_task_id"],
            "comment_count": t["comment_count"],
            "branch": t["branch"],
            "worktree_path": t["worktree_path"],
        }
        if t["cancelled"]:
            cancelled.append(task_dict)
        else:
            step_list = tasks_by_step.get(t["step_id"])
            if step_list is not None:
                step_list.append(task_dict)

    return {
        "project": {
            "id": project["id"],
            "title": project["title"],
            "status": project["status"],
        },
        "steps": [_row_to_dict(s) for s in steps],
        "tasks": tasks_by_step,
        "cancelled": cancelled,
    }


def get_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    """Return a single task with its full comment thread."""
    task = conn.execute(
        """SELECT t.*,
                  ws.name as step_name,
                  ws.position as step_position
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    comments = conn.execute(
        "SELECT * FROM comments WHERE task_id = ? ORDER BY created_at",
        (task_id,),
    ).fetchall()

    result = _row_to_dict(task)
    result["cancelled"] = bool(result["cancelled"])
    result["comments"] = [_row_to_dict(c) for c in comments]
    return result


def get_my_tasks(
    conn: sqlite3.Connection,
    step_id: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Return non-cancelled tasks at a given step."""
    step = conn.execute(
        "SELECT id FROM workflow_steps WHERE id = ?", (step_id,)
    ).fetchone()
    if step is None:
        return {
            "error": "not_found",
            "message": f"Step '{step_id}' not found",
        }

    query = """
        SELECT t.*,
               ws.name as step_name,
               ws.position as step_position,
               (SELECT COUNT(*) FROM comments c WHERE c.task_id = t.id) AS comment_count
        FROM tasks t
        JOIN workflow_steps ws ON t.step_id = ws.id
        WHERE t.step_id = ? AND t.cancelled = 0
    """
    params: list[Any] = [step_id]

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
                "step_id": t["step_id"],
                "step_name": t["step_name"],
                "step_position": t["step_position"],
                "cancelled": bool(t["cancelled"]),
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
    step_id: str,
    project_id: str,
    parent_task_id: str | None = None,
) -> dict[str, Any]:
    """Create a single new task at a given workflow step."""
    step = conn.execute(
        "SELECT id, name, position, project_id FROM workflow_steps WHERE id = ?",
        (step_id,),
    ).fetchone()
    if step is None:
        return {"error": "not_found", "message": f"Step '{step_id}' not found"}
    if step["project_id"] != project_id:
        return {
            "error": "invalid_input",
            "message": f"Step '{step_id}' does not belong to project '{project_id}'",
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
           (id, project_id, parent_task_id, title, description, step_id, cancelled, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (task_id, project_id, parent_task_id, title, description, step_id, now, now),
    )
    emit_event(conn, "task_created", {"task_id": task_id, "project_id": project_id})
    conn.commit()

    return {
        "id": task_id,
        "project_id": project_id,
        "parent_task_id": parent_task_id,
        "title": title,
        "description": description,
        "step_id": step_id,
        "step_name": step["name"],
        "step_position": step["position"],
        "cancelled": False,
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
    default_step_id: str | None = None,
) -> dict[str, Any]:
    """Bulk create subtasks under a parent.

    If default_step_id is not provided, subtasks are placed at the next step
    after the parent's current step.
    """
    parent = conn.execute(
        "SELECT id, project_id, step_id FROM tasks WHERE id = ?", (parent_task_id,)
    ).fetchone()
    if parent is None:
        return {
            "error": "not_found",
            "message": f"Parent task '{parent_task_id}' not found",
        }

    project_id = parent["project_id"]

    # Determine default step: next step after parent
    if default_step_id is None:
        parent_step = conn.execute(
            "SELECT position, project_id FROM workflow_steps WHERE id = ?",
            (parent["step_id"],),
        ).fetchone()
        next_step = conn.execute(
            "SELECT id FROM workflow_steps WHERE project_id = ? AND position = ?",
            (project_id, parent_step["position"] + 1),
        ).fetchone()
        if next_step:
            default_step_id = next_step["id"]
        else:
            default_step_id = parent["step_id"]

    created = []
    now = _now()

    for t in tasks:
        step_id = t.get("step_id", default_step_id)

        # Validate step exists and belongs to project
        step = conn.execute(
            "SELECT id, name, position, project_id FROM workflow_steps WHERE id = ?",
            (step_id,),
        ).fetchone()
        if step is None:
            return {
                "error": "not_found",
                "message": f"Step '{step_id}' not found",
            }
        if step["project_id"] != project_id:
            return {
                "error": "invalid_input",
                "message": f"Step '{step_id}' does not belong to project '{project_id}'",
            }

        task_id = _uuid()
        conn.execute(
            """INSERT INTO tasks
               (id, project_id, parent_task_id, title, description, step_id, cancelled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                task_id,
                project_id,
                parent_task_id,
                t["title"],
                t.get("description", ""),
                step_id,
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
                "step_id": step_id,
                "step_name": step["name"],
                "step_position": step["position"],
                "cancelled": False,
                "created_at": now,
                "updated_at": now,
            }
        )

    emit_event(
        conn,
        "subtasks_created",
        {"parent_task_id": parent_task_id, "task_ids": [t["id"] for t in created]},
    )
    for t in created:
        emit_event(
            conn,
            "task_created",
            {"task_id": t["id"], "project_id": t["project_id"]},
        )
    conn.commit()

    return {"created": created}


def move_task(
    conn: sqlite3.Connection,
    task_id: str,
    target_step_id: str,
) -> dict[str, Any]:
    """Move a task to a different workflow step."""
    try:
        info = validate_step_transition(conn, task_id, target_step_id)
    except InvalidTransitionError as e:
        return {"error": "invalid_transition", "message": str(e)}

    now = _now()
    conn.execute(
        "UPDATE tasks SET step_id = ?, updated_at = ? WHERE id = ?",
        (target_step_id, now, task_id),
    )
    emit_event(
        conn,
        "task_moved",
        {
            "task_id": task_id,
            "old_step_id": info["current_step_id"],
            "new_step_id": target_step_id,
            "project_id": info["project_id"],
        },
    )
    conn.commit()

    # Return updated task
    updated = conn.execute(
        """SELECT t.*,
                  ws.name as step_name,
                  ws.position as step_position
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    result = _row_to_dict(updated)
    result["cancelled"] = bool(result["cancelled"])
    return result


def cancel_task(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any]:
    """Cancel a task."""
    try:
        _validate_cancel(conn, task_id)
    except InvalidTransitionError as e:
        return {"error": "invalid_transition", "message": str(e)}

    now = _now()
    conn.execute(
        "UPDATE tasks SET cancelled = 1, updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    emit_event(conn, "task_cancelled", {"task_id": task_id})
    conn.commit()

    updated = conn.execute(
        """SELECT t.*,
                  ws.name as step_name,
                  ws.position as step_position
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    result = _row_to_dict(updated)
    result["cancelled"] = bool(result["cancelled"])
    return result


def uncancel_task(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any]:
    """Uncancel a task."""
    try:
        _validate_uncancel(conn, task_id)
    except InvalidTransitionError as e:
        return {"error": "invalid_transition", "message": str(e)}

    now = _now()
    conn.execute(
        "UPDATE tasks SET cancelled = 0, updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    emit_event(conn, "task_uncancelled", {"task_id": task_id})
    conn.commit()

    updated = conn.execute(
        """SELECT t.*,
                  ws.name as step_name,
                  ws.position as step_position
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    result = _row_to_dict(updated)
    result["cancelled"] = bool(result["cancelled"])
    return result


def add_comment(
    conn: sqlite3.Connection,
    task_id: str,
    content: str,
    author_role: str,
) -> dict[str, Any]:
    """Add a comment to a task's thread."""
    if not author_role or not author_role.strip():
        return {
            "error": "invalid_role",
            "message": "author_role must be a non-empty string",
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
