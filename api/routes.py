"""REST route handlers for the vibe-relay API.

Routes wrap MCP tool functions with HTTP semantics. All board mutations
go through the MCP tools (source of truth for business logic).
"""

import json
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
    AddDependencyRequest,
    AgentRunResponse,
    CommentResponse,
    CreateCommentRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    DependencyResponse,
    ProjectDetailResponse,
    ProjectResponse,
    TaskDetailResponse,
    TaskResponse,
    UpdatePromptRequest,
    UpdateTaskRequest,
    WorkflowStepResponse,
)
from api.ws import manager
from vibe_relay.mcp.events import emit_event
from vibe_relay.mcp.tools import (
    add_comment,
    add_dependency,
    approve_plan,
    cancel_task,
    create_project,
    create_task,
    create_workflow_steps,
    get_dependencies,
    get_task,
    get_workflow_steps,
    move_task,
    remove_dependency,
    set_task_output,
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
                # Read system prompt from file — prefer project repo_path over config
                repo_path = body.repo_path or (
                    config.get("repo_path", ".") if config else "."
                )
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

    # Default 7-step workflow
    return [
        {"name": "Plan"},
        {"name": "Research"},
        {"name": "Synthesize"},
        {"name": "Implement"},
        {"name": "Test"},
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
    project = create_project(
        conn,
        title=body.title,
        description=body.description,
        repo_path=body.repo_path,
        base_branch=body.base_branch,
    )
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

    # Create root milestone at the first agent step (Plan)
    root_task = create_task(
        conn,
        title=f"Plan: {body.title}",
        description=body.description,
        step_id=first_agent_step["id"],
        project_id=project["id"],
        task_type="milestone",
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

    # Handle output update
    if body.output is not None:
        result = set_task_output(conn, task_id, body.output)
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


# ── Approval endpoint ──────────────────────────────────────


@router.post("/tasks/{task_id}/approve", response_model=TaskResponse)
def approve_plan_endpoint(
    task_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Approve a milestone's plan, enabling its child tasks to be dispatched."""
    result = approve_plan(conn, task_id)
    _check_error(result)
    return result


# ── Dependency endpoints ──────────────────────────────────


@router.get("/tasks/{task_id}/dependencies")
def get_task_dependencies(
    task_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Get predecessors and successors for a task."""
    result = get_dependencies(conn, task_id)
    _check_error(result)
    return result


@router.post(
    "/tasks/{task_id}/dependencies", status_code=201, response_model=DependencyResponse
)
def add_task_dependency(
    task_id: str,
    body: AddDependencyRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Add a dependency for a task."""
    result = add_dependency(conn, body.predecessor_id, body.successor_id)
    _check_error(result)
    return result


@router.delete("/dependencies/{dependency_id}")
def delete_dependency(
    dependency_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Remove a dependency edge."""
    result = remove_dependency(conn, dependency_id)
    _check_error(result)
    return result


# ── Repo validation + config endpoints ─────────────────────


@router.get("/repos/validate")
def validate_repo(path: str) -> dict[str, Any]:
    """Validate a local path as a git repository and detect its default branch."""
    from runner.git_utils import detect_default_branch, is_git_repo

    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {"valid": False, "error": f"Path does not exist: {path}"}
    if not resolved.is_dir():
        return {"valid": False, "error": f"Path is not a directory: {path}"}
    if not is_git_repo(resolved):
        return {"valid": False, "error": f"Not a git repository: {path}"}

    return {
        "valid": True,
        "repo_path": str(resolved),
        "default_branch": detect_default_branch(resolved),
    }


@router.get("/config/defaults")
def get_config_defaults() -> dict[str, Any]:
    """Return global config defaults for repo_path and base_branch."""
    return {
        "repo_path": _config.get("repo_path") if _config else None,
        "base_branch": _config.get("base_branch") if _config else None,
    }


# ── Agent prompt management ─────────────────────────────


@router.get("/projects/{project_id}/steps/{step_id}/prompt")
def get_step_prompt(
    project_id: str,
    step_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Get the system prompt for a workflow step."""
    step = conn.execute(
        "SELECT id, name, system_prompt, system_prompt_file FROM workflow_steps WHERE id = ? AND project_id = ?",
        (step_id, project_id),
    ).fetchone()
    if step is None:
        raise HTTPException(status_code=404, detail=f"Step '{step_id}' not found")

    return {
        "step_id": step["id"],
        "step_name": step["name"],
        "system_prompt": step["system_prompt"] or "",
        "system_prompt_file": step["system_prompt_file"],
    }


@router.put("/projects/{project_id}/steps/{step_id}/prompt")
def update_step_prompt(
    project_id: str,
    step_id: str,
    body: UpdatePromptRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Update the system prompt for a workflow step."""
    step = conn.execute(
        "SELECT id, name FROM workflow_steps WHERE id = ? AND project_id = ?",
        (step_id, project_id),
    ).fetchone()
    if step is None:
        raise HTTPException(status_code=404, detail=f"Step '{step_id}' not found")

    conn.execute(
        "UPDATE workflow_steps SET system_prompt = ? WHERE id = ?",
        (body.system_prompt, step_id),
    )
    conn.commit()

    return {
        "step_id": step["id"],
        "step_name": step["name"],
        "system_prompt": body.system_prompt,
    }


# ── Agent log streaming endpoint ──────────────────────────


def _get_transcript_path(worktree_path: str, session_id: str) -> Path | None:
    """Derive the Claude Code transcript JSONL path for a session.

    Claude Code stores transcripts at:
    ~/.claude/projects/{path-encoded-worktree}/{session_id}.jsonl

    The path encoding replaces leading '/' and all '/' with '-'.
    """
    encoded = worktree_path.lstrip("/").replace("/", "-")
    transcript = Path.home() / ".claude" / "projects" / encoded / f"{session_id}.jsonl"
    if transcript.exists():
        return transcript
    return None


_LOG_MESSAGE_TYPES = {"assistant", "tool_use", "tool_result", "system"}


@router.get("/tasks/{task_id}/logs")
def get_task_logs(
    task_id: str,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Stream agent transcript logs for a running or completed task.

    Returns JSONL lines from the Claude Code session transcript, filtered
    to meaningful message types. Use `offset` for pagination — pass back
    the returned `offset` to get only new lines.
    """
    task = conn.execute(
        "SELECT id, session_id, worktree_path FROM tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    session_id = task["session_id"]
    worktree_path = task["worktree_path"]

    if not session_id:
        return {"lines": [], "offset": 0, "status": "no_session"}

    if not worktree_path:
        return {"lines": [], "offset": 0, "status": "no_worktree"}

    transcript = _get_transcript_path(worktree_path, session_id)
    if transcript is None:
        return {"lines": [], "offset": offset, "status": "transcript_not_found"}

    lines: list[dict[str, Any]] = []
    new_offset = offset
    try:
        with open(transcript) as f:
            for i, raw_line in enumerate(f):
                if i < offset:
                    continue
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type", "")
                if msg_type not in _LOG_MESSAGE_TYPES:
                    continue

                line_data: dict[str, Any] = {
                    "index": i,
                    "type": msg_type,
                }

                if msg_type == "assistant" and "message" in entry:
                    msg = entry["message"]
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            texts = [
                                b.get("text", "")
                                for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            ]
                            line_data["content"] = "\n".join(texts) if texts else ""
                        else:
                            line_data["content"] = str(content)
                    else:
                        line_data["content"] = str(msg)
                elif msg_type == "tool_use":
                    line_data["tool"] = entry.get("name", entry.get("tool", "unknown"))
                    tool_input = entry.get("input", entry.get("args", ""))
                    input_str = (
                        json.dumps(tool_input)
                        if not isinstance(tool_input, str)
                        else tool_input
                    )
                    if len(input_str) > 500:
                        input_str = input_str[:500] + "..."
                    line_data["content"] = input_str
                elif msg_type == "tool_result":
                    result_content = entry.get("content", entry.get("output", ""))
                    result_str = str(result_content)
                    if len(result_str) > 500:
                        result_str = result_str[:500] + "..."
                    line_data["content"] = result_str
                elif msg_type == "system":
                    line_data["content"] = str(
                        entry.get("message", entry.get("content", ""))
                    )

                lines.append(line_data)
                new_offset = i + 1

    except OSError:
        return {"lines": [], "offset": offset, "status": "read_error"}

    active_run = conn.execute(
        "SELECT id FROM agent_runs WHERE task_id = ? AND completed_at IS NULL",
        (task_id,),
    ).fetchone()

    return {
        "lines": lines,
        "offset": new_offset,
        "status": "running" if active_run else "completed",
    }


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
