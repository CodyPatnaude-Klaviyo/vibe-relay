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


# ── Dependency helpers ─────────────────────────────────────


def has_cycle(conn: sqlite3.Connection, predecessor_id: str, successor_id: str) -> bool:
    """BFS from successor forward — if we reach predecessor, adding the edge creates a cycle."""
    visited: set[str] = set()
    queue = [successor_id]
    while queue:
        current = queue.pop(0)
        if current == predecessor_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        rows = conn.execute(
            "SELECT successor_id FROM task_dependencies WHERE predecessor_id = ?",
            (current,),
        ).fetchall()
        for row in rows:
            queue.append(row["successor_id"])
    return False


def is_blocked(conn: sqlite3.Connection, task_id: str) -> bool:
    """True if any predecessor has NOT reached the terminal step (last step in project)."""
    predecessors = conn.execute(
        "SELECT predecessor_id FROM task_dependencies WHERE successor_id = ?",
        (task_id,),
    ).fetchall()
    if not predecessors:
        return False

    for pred_row in predecessors:
        pred_id = pred_row["predecessor_id"]
        pred = conn.execute(
            """SELECT t.step_id, t.cancelled, ws.position, ws.project_id
               FROM tasks t
               JOIN workflow_steps ws ON t.step_id = ws.id
               WHERE t.id = ?""",
            (pred_id,),
        ).fetchone()
        if pred is None:
            continue
        # Find terminal step (last position) for this project
        max_pos = conn.execute(
            "SELECT MAX(position) as max_pos FROM workflow_steps WHERE project_id = ?",
            (pred["project_id"],),
        ).fetchone()
        if pred["position"] != max_pos["max_pos"]:
            return True
    return False


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
    repo_path: str | None = None,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """Create a new project."""
    from pathlib import Path

    from runner.git_utils import detect_default_branch, is_git_repo

    # Validate and resolve repo_path if provided
    resolved_repo: str | None = None
    resolved_branch: str | None = base_branch
    if repo_path:
        p = Path(repo_path).expanduser().resolve()
        if not is_git_repo(p):
            return {
                "error": "invalid_input",
                "message": f"Not a git repository: {repo_path}",
            }
        resolved_repo = str(p)
        if not resolved_branch:
            resolved_branch = detect_default_branch(p)

    project_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO projects (id, title, description, repo_path, base_branch, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
        (project_id, title, description, resolved_repo, resolved_branch, now, now),
    )
    emit_event(conn, "project_created", {"project_id": project_id})
    conn.commit()

    return {
        "id": project_id,
        "title": title,
        "description": description,
        "repo_path": resolved_repo,
        "base_branch": resolved_branch,
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

    # Fetch all dependencies for this project's tasks
    all_deps = conn.execute(
        """SELECT td.id, td.predecessor_id, td.successor_id
           FROM task_dependencies td
           JOIN tasks t ON td.predecessor_id = t.id
           WHERE t.project_id = ?""",
        (project_id,),
    ).fetchall()

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
            "type": t["type"],
            "plan_approved": bool(t["plan_approved"]),
            "output": t["output"],
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
        "dependencies": [_row_to_dict(d) for d in all_deps],
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
    result["plan_approved"] = bool(result.get("plan_approved", 0))
    result["comments"] = [_row_to_dict(c) for c in comments]

    # Include dependencies
    deps = get_dependencies(conn, task_id)
    if "error" not in deps:
        result["dependencies"] = {
            "predecessors": deps["predecessors"],
            "successors": deps["successors"],
        }

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
    task_type: str = "task",
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

    if task_type not in ("task", "research", "milestone"):
        return {
            "error": "invalid_input",
            "message": f"Invalid task type '{task_type}'. Must be 'task', 'research', or 'milestone'",
        }

    task_id = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO tasks
           (id, project_id, parent_task_id, title, description, step_id, cancelled, type, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (
            task_id,
            project_id,
            parent_task_id,
            title,
            description,
            step_id,
            task_type,
            now,
            now,
        ),
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
        "type": task_type,
        "plan_approved": False,
        "output": None,
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
    dependencies: list[dict[str, int]] | None = None,
    cascade_deps_from: str | None = None,
) -> dict[str, Any]:
    """Bulk create subtasks under a parent.

    If default_step_id is not provided, subtasks are placed at the next step
    after the parent's current step (with a fallback to the first agent step
    if the parent is at the terminal step).

    dependencies: optional list of {"from_index": i, "to_index": j} dicts
    that create dependency edges between tasks in the same batch. Edges are
    created BEFORE task_created events are emitted, preventing race conditions.

    cascade_deps_from: optional task ID whose successors should be re-blocked
    on ALL newly created tasks. Used by synthesize agents to ensure downstream
    workstreams stay blocked until implementation tasks complete.
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
            # Parent is at terminal step — find first step with an agent
            first_agent = conn.execute(
                """SELECT id FROM workflow_steps
                   WHERE project_id = ? AND system_prompt IS NOT NULL
                   ORDER BY position LIMIT 1""",
                (project_id,),
            ).fetchone()
            if first_agent:
                default_step_id = first_agent["id"]
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

        task_type = t.get("type", "task")
        task_id = _uuid()
        conn.execute(
            """INSERT INTO tasks
               (id, project_id, parent_task_id, title, description, step_id, cancelled, type, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                task_id,
                project_id,
                parent_task_id,
                t["title"],
                t.get("description", ""),
                step_id,
                task_type,
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
                "type": task_type,
                "created_at": now,
                "updated_at": now,
            }
        )

    # Create dependency edges BEFORE emitting events (prevents race conditions)
    if dependencies:
        for dep in dependencies:
            from_idx = dep.get("from_index", dep.get("from"))
            to_idx = dep.get("to_index", dep.get("to"))
            if from_idx is not None and to_idx is not None:
                if 0 <= from_idx < len(created) and 0 <= to_idx < len(created):
                    dep_id = _uuid()
                    conn.execute(
                        """INSERT INTO task_dependencies (id, predecessor_id, successor_id, created_at)
                           VALUES (?, ?, ?, ?)""",
                        (dep_id, created[from_idx]["id"], created[to_idx]["id"], now),
                    )

    # Cascade dependencies: make successors of cascade_deps_from also depend
    # on all newly created tasks. This keeps downstream workstreams blocked
    # until these implementation tasks reach Done.
    if cascade_deps_from:
        successors = conn.execute(
            "SELECT successor_id FROM task_dependencies WHERE predecessor_id = ?",
            (cascade_deps_from,),
        ).fetchall()
        for succ_row in successors:
            succ_id = succ_row["successor_id"]
            for t in created:
                dep_id = _uuid()
                conn.execute(
                    """INSERT INTO task_dependencies (id, predecessor_id, successor_id, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (dep_id, t["id"], succ_id, now),
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
            "from_step_name": info["current_step_name"],
            "to_step_name": info["target_step_name"],
            "from_position": info["current_position"],
            "to_position": info["target_position"],
            "direction": "forward"
            if info["target_position"] > info["current_position"]
            else "backward",
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


# ── Dependency tools ──────────────────────────────────────


def add_dependency(
    conn: sqlite3.Connection,
    predecessor_id: str,
    successor_id: str,
) -> dict[str, Any]:
    """Add a dependency edge: successor is blocked until predecessor reaches Done."""
    if predecessor_id == successor_id:
        return {"error": "invalid_input", "message": "A task cannot depend on itself"}

    # Validate both tasks exist
    for tid, label in [(predecessor_id, "Predecessor"), (successor_id, "Successor")]:
        row = conn.execute("SELECT id FROM tasks WHERE id = ?", (tid,)).fetchone()
        if row is None:
            return {"error": "not_found", "message": f"{label} task '{tid}' not found"}

    # Check for duplicate
    existing = conn.execute(
        "SELECT id FROM task_dependencies WHERE predecessor_id = ? AND successor_id = ?",
        (predecessor_id, successor_id),
    ).fetchone()
    if existing:
        return {
            "error": "invalid_input",
            "message": "This dependency already exists",
        }

    # Cycle detection
    if has_cycle(conn, predecessor_id, successor_id):
        return {
            "error": "invalid_input",
            "message": "Adding this dependency would create a cycle",
        }

    dep_id = _uuid()
    now = _now()
    conn.execute(
        "INSERT INTO task_dependencies (id, predecessor_id, successor_id, created_at) VALUES (?, ?, ?, ?)",
        (dep_id, predecessor_id, successor_id, now),
    )
    emit_event(
        conn,
        "dependency_created",
        {
            "dependency_id": dep_id,
            "predecessor_id": predecessor_id,
            "successor_id": successor_id,
        },
    )
    conn.commit()

    return {
        "id": dep_id,
        "predecessor_id": predecessor_id,
        "successor_id": successor_id,
        "created_at": now,
    }


def remove_dependency(
    conn: sqlite3.Connection,
    dependency_id: str,
) -> dict[str, Any]:
    """Remove a dependency edge."""
    dep = conn.execute(
        "SELECT * FROM task_dependencies WHERE id = ?", (dependency_id,)
    ).fetchone()
    if dep is None:
        return {
            "error": "not_found",
            "message": f"Dependency '{dependency_id}' not found",
        }

    conn.execute("DELETE FROM task_dependencies WHERE id = ?", (dependency_id,))
    emit_event(
        conn,
        "dependency_removed",
        {
            "dependency_id": dependency_id,
            "predecessor_id": dep["predecessor_id"],
            "successor_id": dep["successor_id"],
        },
    )
    conn.commit()

    return {"status": "removed", "id": dependency_id}


def get_dependencies(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any]:
    """Return predecessors and successors for a task."""
    task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    preds = conn.execute(
        """SELECT td.id as dependency_id, td.predecessor_id, t.title, t.step_id,
                  ws.name as step_name, ws.position as step_position
           FROM task_dependencies td
           JOIN tasks t ON td.predecessor_id = t.id
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE td.successor_id = ?""",
        (task_id,),
    ).fetchall()

    succs = conn.execute(
        """SELECT td.id as dependency_id, td.successor_id, t.title, t.step_id,
                  ws.name as step_name, ws.position as step_position
           FROM task_dependencies td
           JOIN tasks t ON td.successor_id = t.id
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE td.predecessor_id = ?""",
        (task_id,),
    ).fetchall()

    return {
        "task_id": task_id,
        "predecessors": [_row_to_dict(r) for r in preds],
        "successors": [_row_to_dict(r) for r in succs],
    }


# ── Approval tools ────────────────────────────────────────


def approve_plan(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any]:
    """Approve a milestone's plan, enabling its child tasks to be dispatched."""
    task = conn.execute(
        """SELECT t.*, ws.name as step_name, ws.position as step_position
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    if task["type"] != "milestone":
        return {
            "error": "invalid_input",
            "message": "Only milestones can be approved",
        }

    if task["plan_approved"]:
        return {
            "error": "invalid_input",
            "message": "This milestone is already approved",
        }

    # Verify milestone has at least one child task
    children = conn.execute(
        "SELECT id FROM tasks WHERE parent_task_id = ? AND cancelled = 0",
        (task_id,),
    ).fetchall()
    if not children:
        return {
            "error": "invalid_input",
            "message": "Milestone must have at least one child task before approval",
        }

    now = _now()
    conn.execute(
        "UPDATE tasks SET plan_approved = 1, updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    emit_event(
        conn,
        "plan_approved",
        {"task_id": task_id, "project_id": task["project_id"]},
    )

    # Emit task_ready for unblocked children
    for child in children:
        if not is_blocked(conn, child["id"]):
            emit_event(
                conn,
                "task_ready",
                {"task_id": child["id"], "project_id": task["project_id"]},
            )

    conn.commit()

    result = _row_to_dict(task)
    result["plan_approved"] = True
    result["cancelled"] = bool(result["cancelled"])
    result["updated_at"] = now
    return result


# ── Complete task + auto-advance ──────────────────────────


def complete_task(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any]:
    """Move a task to the terminal step (Done), cascade unblock dependents,
    and check if parent milestone should auto-advance."""
    task = conn.execute(
        """SELECT t.*, ws.position as current_position, ws.project_id as ws_project_id
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    if task["cancelled"]:
        return {
            "error": "invalid_transition",
            "message": "Cannot complete a cancelled task",
        }

    # Find terminal step
    terminal = conn.execute(
        "SELECT id, name, position FROM workflow_steps WHERE project_id = ? ORDER BY position DESC LIMIT 1",
        (task["project_id"],),
    ).fetchone()

    if task["step_id"] == terminal["id"]:
        return {
            "error": "invalid_transition",
            "message": "Task is already at the terminal step",
        }

    # Look up current step name for enriched event
    current_step = conn.execute(
        "SELECT name, position FROM workflow_steps WHERE id = ?",
        (task["step_id"],),
    ).fetchone()

    # Move to terminal step
    now = _now()
    conn.execute(
        "UPDATE tasks SET step_id = ?, updated_at = ? WHERE id = ?",
        (terminal["id"], now, task_id),
    )
    emit_event(
        conn,
        "task_moved",
        {
            "task_id": task_id,
            "old_step_id": task["step_id"],
            "new_step_id": terminal["id"],
            "project_id": task["project_id"],
            "from_step_name": current_step["name"],
            "to_step_name": terminal["name"],
            "from_position": current_step["position"],
            "to_position": terminal["position"],
            "direction": "forward",
        },
    )

    # Cascade unblock
    _cascade_unblock(conn, task_id)

    # Check sibling completion for parent auto-advance
    if task["parent_task_id"]:
        _check_sibling_completion(conn, task["parent_task_id"])

    conn.commit()

    updated = conn.execute(
        """SELECT t.*, ws.name as step_name, ws.position as step_position
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (task_id,),
    ).fetchone()
    result = _row_to_dict(updated)
    result["cancelled"] = bool(result["cancelled"])
    return result


def _cascade_unblock(conn: sqlite3.Connection, completed_task_id: str) -> list[str]:
    """Check all successors of a completed task. Emit task_ready for fully unblocked ones."""
    successors = conn.execute(
        "SELECT successor_id FROM task_dependencies WHERE predecessor_id = ?",
        (completed_task_id,),
    ).fetchall()

    unblocked: list[str] = []
    for succ_row in successors:
        succ_id = succ_row["successor_id"]
        if not is_blocked(conn, succ_id):
            # Check if parent milestone is approved
            succ = conn.execute(
                "SELECT parent_task_id, project_id, cancelled FROM tasks WHERE id = ?",
                (succ_id,),
            ).fetchone()
            if succ and not succ["cancelled"]:
                parent_approved = True
                if succ["parent_task_id"]:
                    parent = conn.execute(
                        "SELECT type, plan_approved FROM tasks WHERE id = ?",
                        (succ["parent_task_id"],),
                    ).fetchone()
                    if (
                        parent
                        and parent["type"] == "milestone"
                        and not parent["plan_approved"]
                    ):
                        parent_approved = False

                if parent_approved:
                    emit_event(
                        conn,
                        "task_ready",
                        {"task_id": succ_id, "project_id": succ["project_id"]},
                    )
                    unblocked.append(succ_id)

    return unblocked


def _check_sibling_completion(conn: sqlite3.Connection, parent_task_id: str) -> None:
    """When all non-cancelled children of a milestone complete, auto-advance the milestone."""
    parent = conn.execute(
        """SELECT t.*, ws.position as current_position, ws.name as step_name
           FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.id = ?""",
        (parent_task_id,),
    ).fetchone()
    if parent is None or parent["type"] != "milestone" or parent["cancelled"]:
        return

    # Check if all non-cancelled children are at the terminal step
    children = conn.execute(
        "SELECT t.id, t.step_id, ws.position FROM tasks t JOIN workflow_steps ws ON t.step_id = ws.id WHERE t.parent_task_id = ? AND t.cancelled = 0",
        (parent_task_id,),
    ).fetchall()
    if not children:
        return

    terminal = conn.execute(
        "SELECT id, position FROM workflow_steps WHERE project_id = ? ORDER BY position DESC LIMIT 1",
        (parent["project_id"],),
    ).fetchone()

    all_done = all(c["position"] == terminal["position"] for c in children)
    if not all_done:
        return

    # Auto-advance: move parent to next step
    next_step = conn.execute(
        "SELECT id, name, position FROM workflow_steps WHERE project_id = ? AND position = ?",
        (parent["project_id"], parent["current_position"] + 1),
    ).fetchone()

    if next_step:
        now = _now()
        conn.execute(
            "UPDATE tasks SET step_id = ?, updated_at = ? WHERE id = ?",
            (next_step["id"], now, parent_task_id),
        )
        emit_event(
            conn,
            "task_moved",
            {
                "task_id": parent_task_id,
                "old_step_id": parent["step_id"],
                "new_step_id": next_step["id"],
                "project_id": parent["project_id"],
                "from_step_name": parent["step_name"],
                "to_step_name": next_step["name"],
                "from_position": parent["current_position"],
                "to_position": next_step["position"],
                "direction": "forward",
            },
        )

        # If parent reached terminal, check its own parent
        if next_step["position"] == terminal["position"]:
            emit_event(
                conn,
                "milestone_completed",
                {"task_id": parent_task_id, "project_id": parent["project_id"]},
            )
            if parent["parent_task_id"]:
                _check_sibling_completion(conn, parent["parent_task_id"])


def set_task_output(
    conn: sqlite3.Connection,
    task_id: str,
    output: str,
) -> dict[str, Any]:
    """Set the output field on a task (used by research tasks to store findings)."""
    task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        return {"error": "not_found", "message": f"Task '{task_id}' not found"}

    now = _now()
    conn.execute(
        "UPDATE tasks SET output = ?, updated_at = ? WHERE id = ?",
        (output, now, task_id),
    )
    emit_event(conn, "task_updated", {"task_id": task_id})
    conn.commit()

    return {"task_id": task_id, "output": output, "updated_at": now}
