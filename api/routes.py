"""REST route handlers for the vibe-relay API.

Routes wrap MCP tool functions with HTTP semantics. All board mutations
go through the MCP tools (source of truth for business logic).
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.websockets import WebSocket, WebSocketDisconnect

from api.deps import (
    get_agent_runs,
    get_db,
    get_task_counts_by_status,
    get_tasks_grouped_by_status,
)
from api.models import (
    AgentRunResponse,
    CommentResponse,
    CreateCommentRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    ProjectDetailResponse,
    ProjectResponse,
    TaskDetailResponse,
    TaskResponse,
    UpdateTaskRequest,
)
from api.ws import manager
from vibe_relay.mcp.events import emit_event
from vibe_relay.mcp.tools import (
    add_comment,
    create_project,
    create_task,
    get_task,
    update_task_status,
)

router = APIRouter()


def _check_error(result: dict[str, Any]) -> None:
    """Convert MCP tool error dicts to HTTPException.

    MCP tools return {"error": "...", "message": "..."} on failure.
    This helper maps known error types to HTTP status codes.
    """
    if "error" not in result:
        return
    error = result["error"]
    message = result.get("message", "Unknown error")
    if error == "not_found":
        raise HTTPException(status_code=404, detail=message)
    if error in ("invalid_transition", "invalid_phase", "invalid_role"):
        raise HTTPException(status_code=422, detail=message)
    raise HTTPException(status_code=400, detail=message)


# ── Project endpoints ──────────────────────────────────────


@router.post("/projects", status_code=201)
def create_project_endpoint(
    body: CreateProjectRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create a new project and a root planner task."""
    project = create_project(conn, title=body.title, description=body.description)
    _check_error(project)

    # Create the root planner task as required by spec
    root_task = create_task(
        conn,
        title=f"Plan: {body.title}",
        description=body.description,
        phase="planner",
        project_id=project["id"],
    )
    _check_error(root_task)

    return {"project": project, "task": root_task}


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all projects."""
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Get a project with task counts by status."""
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    result = dict(row)
    result["tasks"] = get_task_counts_by_status(conn, project_id)
    return result


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, str]:
    """Cancel/archive a project."""
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE projects SET status = 'cancelled', updated_at = ? WHERE id = ?",
        (now, project_id),
    )
    emit_event(
        conn, "project_updated", {"project_id": project_id, "status": "cancelled"}
    )
    conn.commit()
    return {"status": "cancelled"}


# ── Task endpoints ─────────────────────────────────────────


@router.post(
    "/projects/{project_id}/tasks", status_code=201, response_model=TaskResponse
)
def create_task_endpoint(
    project_id: str,
    body: CreateTaskRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create a task within a project."""
    result = create_task(
        conn,
        title=body.title,
        description=body.description,
        phase=body.phase,
        project_id=project_id,
        parent_task_id=body.parent_task_id,
    )
    _check_error(result)
    return result


@router.get("/projects/{project_id}/tasks")
def list_project_tasks(
    project_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    """List all tasks for a project grouped by status."""
    # Verify project exists
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    return get_tasks_grouped_by_status(conn, project_id)


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
def get_task_endpoint(
    task_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Get a task with its full comment thread."""
    result = get_task(conn, task_id)
    _check_error(result)
    return result


@router.patch("/tasks/{task_id}", response_model=TaskDetailResponse)
def update_task_endpoint(
    task_id: str,
    body: UpdateTaskRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Update a task's status, title, or description."""
    # Handle status update via state machine
    if body.status is not None:
        result = update_task_status(conn, task_id, body.status)
        _check_error(result)

    # Handle title/description updates via direct SQL
    if body.title is not None or body.description is not None:
        # First verify task exists
        task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        updates: list[str] = []
        params: list[Any] = []
        if body.title is not None:
            updates.append("title = ?")
            params.append(body.title)
        if body.description is not None:
            updates.append("description = ?")
            params.append(body.description)

        now = datetime.now(timezone.utc).isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(task_id)

        conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",  # noqa: S608
            params,
        )
        emit_event(conn, "task_updated", {"task_id": task_id})
        conn.commit()

    # Return the full updated task
    result = get_task(conn, task_id)
    _check_error(result)
    return result


# ── Comment endpoints ──────────────────────────────────────


@router.post(
    "/tasks/{task_id}/comments", status_code=201, response_model=CommentResponse
)
def create_comment_endpoint(
    task_id: str,
    body: CreateCommentRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Add a comment to a task."""
    result = add_comment(
        conn,
        task_id=task_id,
        content=body.content,
        author_role=body.author_role,
    )
    _check_error(result)
    return result


# ── Agent run endpoints ────────────────────────────────────


@router.get("/tasks/{task_id}/runs", response_model=list[AgentRunResponse])
def list_task_runs(
    task_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get agent run history for a task."""
    # Verify task exists
    task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    return get_agent_runs(conn, task_id)


# ── WebSocket endpoint ─────────────────────────────────────


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for live board updates."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
