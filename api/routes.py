"""REST route handlers for the vibe-relay API.

Routes wrap MCP tool functions with HTTP semantics. All board mutations
go through the MCP tools (source of truth for business logic).
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.websockets import WebSocket, WebSocketDisconnect

from api.deps import (
    get_agent_runs,
    get_db,
    get_task_counts_by_step,
    get_tasks_grouped_by_step,
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
    WorkflowStepResponse,
)
from api.ws import manager
from vibe_relay.mcp.events import emit_event
from vibe_relay.mcp.tools import (
    add_comment,
    cancel_task,
    create_project,
    create_task,
    create_workflow_steps,
    get_task,
    get_workflow_steps,
    move_task,
    uncancel_task,
)

router = APIRouter()


def _check_error(result: dict[str, Any]) -> None:
    """Convert MCP tool error dicts to HTTPException."""
    if "error" not in result:
        return
    error = result["error"]
    message = result.get("message", "Unknown error")
    if error == "not_found":
        raise HTTPException(status_code=404, detail=message)
    if error in ("invalid_transition", "invalid_input", "invalid_role"):
        raise HTTPException(status_code=422, detail=message)
    raise HTTPException(status_code=400, detail=message)


def _resolve_workflow_steps(
    body: CreateProjectRequest, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Resolve workflow steps from request body or config defaults.

    Returns a list of step dicts with 'name' and optionally 'system_prompt', 'model', 'color'.
    """
    if body.workflow_steps:
        steps = []
        for ws in body.workflow_steps:
            step: dict[str, Any] = {"name": ws.name}
            if ws.system_prompt:
                step["system_prompt"] = ws.system_prompt
            elif ws.system_prompt_file:
                # Read system prompt from file
                repo_path = config.get("repo_path", ".") if config else "."
                prompt_path = Path(repo_path) / ws.system_prompt_file
                if prompt_path.exists():
                    step["system_prompt"] = prompt_path.read_text()
            if ws.model:
                step["model"] = ws.model
            if ws.color:
                step["color"] = ws.color
            steps.append(step)
        return steps

    # Use config defaults
    if config and "default_workflow" in config:
        steps = []
        repo_path = config.get("repo_path", ".")
        for ws_def in config["default_workflow"]:
            step = {"name": ws_def["name"]}
            if "system_prompt_file" in ws_def:
                prompt_path = Path(repo_path) / ws_def["system_prompt_file"]
                if prompt_path.exists():
                    step["system_prompt"] = prompt_path.read_text()
            if "model" in ws_def:
                step["model"] = ws_def["model"]
            if "color" in ws_def:
                step["color"] = ws_def["color"]
            steps.append(step)
        return steps

    # Bare minimum: Plan, Implement, Review, Done
    return [
        {"name": "Plan"},
        {"name": "Implement"},
        {"name": "Review"},
        {"name": "Done"},
    ]


# Store config reference for workflow step resolution
_config: dict[str, Any] | None = None


def set_config(config: dict[str, Any] | None) -> None:
    """Set the config dict for workflow step resolution."""
    global _config  # noqa: PLW0603
    _config = config


# ── Project endpoints ──────────────────────────────────────


@router.post("/projects", status_code=201)
def create_project_endpoint(
    body: CreateProjectRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create a new project with workflow steps and a root task at the first agent step."""
    project = create_project(conn, title=body.title, description=body.description)
    _check_error(project)

    # Create workflow steps
    step_defs = _resolve_workflow_steps(body, _config)
    steps_result = create_workflow_steps(conn, project["id"], step_defs)
    _check_error(steps_result)

    # Find first step with an agent (system_prompt)
    first_agent_step = None
    for s in steps_result["steps"]:
        if s["has_agent"]:
            first_agent_step = s
            break

    # If no agent steps, use first step
    if first_agent_step is None:
        first_agent_step = steps_result["steps"][0]

    # Create root task at the first agent step
    root_task = create_task(
        conn,
        title=f"Plan: {body.title}",
        description=body.description,
        step_id=first_agent_step["id"],
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
    """Get a project with task counts by step."""
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    result = dict(row)
    result["tasks"] = get_task_counts_by_step(conn, project_id)
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


# ── Workflow step endpoints ─────────────────────────────────


@router.get("/projects/{project_id}/steps", response_model=list[WorkflowStepResponse])
def list_project_steps(
    project_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return ordered workflow steps for a project."""
    result = get_workflow_steps(conn, project_id)
    _check_error(result)
    return result["steps"]


# ── Task endpoints ─────────────────────────────────────────


@router.post(
    "/projects/{project_id}/tasks", status_code=201, response_model=TaskResponse
)
def create_task_endpoint(
    project_id: str,
    body: CreateTaskRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create a task within a project at a workflow step."""
    result = create_task(
        conn,
        title=body.title,
        description=body.description,
        step_id=body.step_id,
        project_id=project_id,
        parent_task_id=body.parent_task_id,
    )
    _check_error(result)
    return result


@router.get("/projects/{project_id}/tasks")
def list_project_tasks(
    project_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """List all tasks for a project grouped by workflow step."""
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    return get_tasks_grouped_by_step(conn, project_id)


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
    """Update a task's step, cancelled state, title, or description."""
    # Handle step movement
    if body.step_id is not None:
        result = move_task(conn, task_id, body.step_id)
        _check_error(result)

    # Handle cancel/uncancel
    if body.cancelled is not None:
        if body.cancelled:
            result = cancel_task(conn, task_id)
        else:
            result = uncancel_task(conn, task_id)
        _check_error(result)

    # Handle title/description updates via direct SQL
    if body.title is not None or body.description is not None:
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
        emit_event(conn, "task_created", {"task_id": task_id})
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
