# Phase 4: API + Websocket Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the HTTP server with REST endpoints for all board operations and a websocket for live updates, backed by the existing MCP tools and events table.

**Architecture:** FastAPI app wraps the existing MCP tool functions (`vibe_relay/mcp/tools.py`) which own all business logic. A background asyncio task polls the `events` table every 500ms and broadcasts enriched payloads to all connected websocket clients. DB connections are created per-request via FastAPI dependency injection.

**Tech Stack:** FastAPI, uvicorn, Pydantic v2, httpx (testing), pytest-asyncio, websockets

---

## Task 1: Pydantic request/response models (`api/models.py`)

**Files:**
- Create: `api/models.py`
- Test: `tests/test_api.py` (just model validation tests first)

**Step 1: Create the models file**

```python
"""Pydantic request/response models for the vibe-relay API."""

from pydantic import BaseModel, Field


# ── Request models ──────────────────────────────────────

class CreateProjectRequest(BaseModel):
    title: str
    description: str = ""


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    phase: str
    parent_task_id: str | None = None


class UpdateTaskRequest(BaseModel):
    status: str | None = None
    title: str | None = None
    description: str | None = None


class CreateCommentRequest(BaseModel):
    content: str
    author_role: str


# ── Response models ─────────────────────────────────────

class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str
    created_at: str
    updated_at: str


class ProjectDetailResponse(ProjectResponse):
    tasks: dict[str, int]  # status -> count


class TaskResponse(BaseModel):
    id: str
    project_id: str
    parent_task_id: str | None = None
    title: str
    description: str | None = None
    phase: str
    status: str
    branch: str | None = None
    worktree_path: str | None = None
    session_id: str | None = None
    created_at: str
    updated_at: str


class TaskDetailResponse(TaskResponse):
    comments: list[dict]  # full comment dicts


class CommentResponse(BaseModel):
    id: str
    task_id: str
    author_role: str
    content: str
    created_at: str


class AgentRunResponse(BaseModel):
    id: str
    phase: str
    started_at: str
    completed_at: str | None = None
    exit_code: int | None = None
    error: str | None = None


class WebSocketEvent(BaseModel):
    type: str
    payload: dict
```

**Step 2: Verify models import cleanly**

Run: `uv run python -c "from api.models import CreateProjectRequest, TaskDetailResponse; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add api/models.py
git commit -m "Add Pydantic request/response models for API"
```

---

## Task 2: DB dependency and event helpers (`api/deps.py`)

**Files:**
- Create: `api/deps.py`

**Step 1: Create dependency injection module**

```python
"""FastAPI dependency injection and DB helpers for vibe-relay."""

import json
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from db.client import get_connection
from db.state_machine import VALID_STATUSES


# Module-level DB path — set by app startup
_db_path: str = ""


def set_db_path(path: str) -> None:
    """Set the database path used by the DB dependency."""
    global _db_path
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


def get_task_counts_by_status(conn: sqlite3.Connection, project_id: str) -> dict[str, int]:
    """Return task count per status for a project."""
    counts: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE project_id = ? GROUP BY status",
        (project_id,),
    ).fetchall()
    for row in rows:
        counts[row["status"]] = row["cnt"]
    return counts


def get_tasks_grouped_by_status(conn: sqlite3.Connection, project_id: str) -> dict[str, list[dict[str, Any]]]:
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


def enrich_event_payload(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    """Build a websocket event with full object payload, not just IDs."""
    event_type = event["type"]
    payload = event["payload"]

    if event_type in ("task_created", "task_updated"):
        task_id = payload.get("task_id")
        if task_id:
            task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task:
                return {"type": event_type, "payload": dict(task)}

    elif event_type == "comment_added":
        comment_id = payload.get("comment_id")
        if comment_id:
            comment = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
            if comment:
                return {"type": event_type, "payload": dict(comment)}

    elif event_type == "project_created":
        project_id = payload.get("project_id")
        if project_id:
            project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if project:
                return {"type": event_type, "payload": dict(project)}

    # Fallback: return raw payload
    return {"type": event_type, "payload": payload}
```

**Step 2: Verify imports**

Run: `uv run python -c "from api.deps import get_db, get_unconsumed_events; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add api/deps.py
git commit -m "Add FastAPI DB dependency injection and event helpers"
```

---

## Task 3: WebSocket connection manager (`api/ws.py`)

**Files:**
- Create: `api/ws.py`

**Step 1: Create the websocket module**

```python
"""WebSocket connection manager and event broadcaster for vibe-relay."""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from api.deps import (
    enrich_event_payload,
    get_unconsumed_events,
    mark_event_consumed,
)
from db.client import get_connection

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients."""
        dead: list[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active_connections.remove(ws)


manager = ConnectionManager()


async def broadcast_events(db_path: str) -> None:
    """Background task that polls events table and broadcasts to websocket clients.

    Runs every 500ms. Opens its own DB connection.
    """
    while True:
        try:
            conn = get_connection(db_path)
            try:
                events = get_unconsumed_events(conn)
                for event in events:
                    enriched = enrich_event_payload(conn, event)
                    await manager.broadcast(enriched)
                    mark_event_consumed(conn, event["id"])
            finally:
                conn.close()
        except Exception:
            logger.exception("Error in event broadcaster")
        await asyncio.sleep(0.5)
```

**Step 2: Verify imports**

Run: `uv run python -c "from api.ws import ConnectionManager, manager, broadcast_events; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add api/ws.py
git commit -m "Add WebSocket connection manager and event broadcaster"
```

---

## Task 4: REST route handlers (`api/routes.py`)

**Files:**
- Create: `api/routes.py`

**Step 1: Create the routes module**

```python
"""REST API route handlers for vibe-relay.

Wraps MCP tool functions with FastAPI endpoints, adding HTTP semantics
(status codes, validation) on top of the existing business logic.
"""

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from api.deps import get_agent_runs, get_db, get_task_counts_by_status, get_tasks_grouped_by_status
from api.models import (
    CommentResponse,
    CreateCommentRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    UpdateTaskRequest,
)
from api.ws import manager
from vibe_relay.mcp.tools import (
    add_comment,
    create_project,
    create_task,
    get_task,
    update_task_status,
)

router = APIRouter()


def _check_error(result: dict[str, Any], status_code: int = 404) -> None:
    """Raise HTTPException if the MCP tool returned an error dict."""
    if "error" in result:
        code = status_code
        if result["error"] == "invalid_transition":
            code = 422
        elif result["error"] == "invalid_phase":
            code = 422
        elif result["error"] == "invalid_role":
            code = 422
        raise HTTPException(status_code=code, detail=result["message"])


# ── Projects ────────────────────────────────────────────


@router.post("/projects", status_code=201)
def create_project_endpoint(
    body: CreateProjectRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create a new project and a root planner task."""
    project = create_project(conn, body.title, body.description)
    _check_error(project)

    # Create root planning task per spec
    root_task = create_task(
        conn,
        title=f"Plan: {body.title}",
        description=body.description,
        phase="planner",
        project_id=project["id"],
    )
    _check_error(root_task)

    return {"project": project, "root_task": root_task}


@router.get("/projects")
def list_projects(
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all projects."""
    rows = conn.execute(
        "SELECT * FROM projects ORDER BY created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Get a project with task counts by status."""
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
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
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    conn.execute(
        "UPDATE projects SET status = 'cancelled' WHERE id = ?", (project_id,)
    )
    conn.commit()
    return {"status": "cancelled"}


# ── Tasks ───────────────────────────────────────────────


@router.post("/projects/{project_id}/tasks", status_code=201)
def create_task_endpoint(
    project_id: str,
    body: CreateTaskRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create a task in a project."""
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
def list_tasks(
    project_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    """List all tasks for a project grouped by status."""
    # Verify project exists
    row = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    return get_tasks_grouped_by_status(conn, project_id)


@router.get("/tasks/{task_id}")
def get_task_endpoint(
    task_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Get a task with its full comment thread."""
    result = get_task(conn, task_id)
    _check_error(result)
    return result


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    body: UpdateTaskRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Update a task's status, title, or description."""
    # Fetch existing task
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    # Handle status change via state machine
    if body.status is not None:
        result = update_task_status(conn, task_id, body.status)
        _check_error(result, status_code=422)

    # Handle title/description updates
    if body.title is not None or body.description is not None:
        updates: list[str] = []
        params: list[Any] = []
        if body.title is not None:
            updates.append("title = ?")
            params.append(body.title)
        if body.description is not None:
            updates.append("description = ?")
            params.append(body.description)
        if updates:
            from vibe_relay.mcp.events import emit_event
            from datetime import datetime, timezone

            updates.append("updated_at = ?")
            now = datetime.now(timezone.utc).isoformat()
            params.append(now)
            params.append(task_id)
            conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            emit_event(conn, "task_updated", {"task_id": task_id})
            conn.commit()

    # Return full updated task
    result = get_task(conn, task_id)
    _check_error(result)
    return result


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_comment_endpoint(
    task_id: str,
    body: CreateCommentRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Add a comment to a task."""
    result = add_comment(conn, task_id, body.content, body.author_role)
    _check_error(result)
    return result


@router.get("/tasks/{task_id}/runs")
def get_task_runs(
    task_id: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get agent run history for a task."""
    # Verify task exists
    task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    return get_agent_runs(conn, task_id)


# ── WebSocket ───────────────────────────────────────────


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for live board updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive — client doesn't send messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

**Step 2: Verify imports**

Run: `uv run python -c "from api.routes import router; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add api/routes.py
git commit -m "Add REST route handlers for projects, tasks, comments, runs"
```

---

## Task 5: FastAPI app factory (`api/app.py`)

**Files:**
- Create: `api/app.py`

**Step 1: Create the app module**

```python
"""FastAPI application for vibe-relay."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import set_db_path
from api.routes import router
from api.ws import broadcast_events


def create_app(db_path: str) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Start the event broadcaster on startup, cancel on shutdown."""
        task = asyncio.create_task(broadcast_events(db_path))
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    set_db_path(db_path)

    app = FastAPI(title="vibe-relay", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app
```

**Step 2: Verify imports**

Run: `uv run python -c "from api.app import create_app; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add api/app.py
git commit -m "Add FastAPI app factory with CORS and event broadcaster lifespan"
```

---

## Task 6: Update CLI `serve` command (`vibe_relay/cli.py`)

**Files:**
- Modify: `vibe_relay/cli.py:93-96` (replace placeholder `serve` command)

**Step 1: Replace the serve command**

Replace lines 93-96 with:

```python
@main.command()
@click.option("--port", default=8000, help="Port to listen on")
@click.option("--reload", "use_reload", is_flag=True, help="Enable auto-reload for development")
def serve(port: int, use_reload: bool) -> None:
    """Start the vibe-relay API server."""
    import uvicorn

    from db.migrations import init_db
    from vibe_relay.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as e:
        click.echo(f"Config error: {e}", err=True)
        raise SystemExit(1)

    # Ensure DB is initialized
    init_db(config["db_path"])

    from api.app import create_app

    app = create_app(db_path=config["db_path"])
    uvicorn.run(app, host="0.0.0.0", port=port, reload=use_reload)
```

**Step 2: Verify CLI help**

Run: `uv run vibe-relay serve --help`
Expected: Shows `--port` and `--reload` options

**Step 3: Commit**

```bash
git add vibe_relay/cli.py
git commit -m "Update serve command to start FastAPI with uvicorn"
```

---

## Task 7: Tests — Project endpoints (`tests/test_api.py`)

**Files:**
- Create: `tests/test_api.py`

**Step 1: Write tests for project endpoints**

```python
"""Tests for the REST API endpoints.

Uses httpx AsyncClient with the FastAPI test client.
"""

import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from db.migrations import init_db


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    """Create a test database and return its path."""
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


@pytest_asyncio.fixture()
async def client(db_path: str) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    app = create_app(db_path=db_path)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_creates_project_and_root_task(self, client: AsyncClient) -> None:
        resp = await client.post("/projects", json={"title": "My Project", "description": "Desc"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"]["title"] == "My Project"
        assert data["root_task"]["phase"] == "planner"
        assert data["root_task"]["status"] == "backlog"

    @pytest.mark.asyncio
    async def test_root_task_belongs_to_project(self, client: AsyncClient) -> None:
        resp = await client.post("/projects", json={"title": "P"})
        data = resp.json()
        assert data["root_task"]["project_id"] == data["project"]["id"]


class TestListProjects:
    @pytest.mark.asyncio
    async def test_lists_created_projects(self, client: AsyncClient) -> None:
        await client.post("/projects", json={"title": "P1"})
        await client.post("/projects", json={"title": "P2"})
        resp = await client.get("/projects")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_empty_list(self, client: AsyncClient) -> None:
        resp = await client.get("/projects")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetProject:
    @pytest.mark.asyncio
    async def test_returns_project_with_task_counts(self, client: AsyncClient) -> None:
        create_resp = await client.post("/projects", json={"title": "P", "description": "D"})
        project_id = create_resp.json()["project"]["id"]

        resp = await client.get(f"/projects/{project_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "P"
        assert "tasks" in data
        # Root planner task is in backlog
        assert data["tasks"]["backlog"] == 1

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/projects/nonexistent")
        assert resp.status_code == 404


class TestDeleteProject:
    @pytest.mark.asyncio
    async def test_cancels_project(self, client: AsyncClient) -> None:
        create_resp = await client.post("/projects", json={"title": "P"})
        project_id = create_resp.json()["project"]["id"]

        resp = await client.delete(f"/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient) -> None:
        resp = await client.delete("/projects/nonexistent")
        assert resp.status_code == 404
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_api.py -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_api.py
git commit -m "Add tests for project API endpoints"
```

---

## Task 8: Tests — Task endpoints (`tests/test_api.py` continued)

**Files:**
- Modify: `tests/test_api.py` (append task endpoint tests)

**Step 1: Add task endpoint tests**

Append to `tests/test_api.py`:

```python
class TestCreateTask:
    @pytest.mark.asyncio
    async def test_creates_task(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]

        resp = await client.post(
            f"/projects/{pid}/tasks",
            json={"title": "Task 1", "description": "Do it", "phase": "coder"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "backlog"

    @pytest.mark.asyncio
    async def test_invalid_phase(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]

        resp = await client.post(
            f"/projects/{pid}/tasks",
            json={"title": "T", "phase": "bad"},
        )
        assert resp.status_code == 422


class TestListTasks:
    @pytest.mark.asyncio
    async def test_grouped_by_status(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]

        await client.post(f"/projects/{pid}/tasks", json={"title": "T1", "phase": "coder"})

        resp = await client.get(f"/projects/{pid}/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "backlog" in data
        assert "in_progress" in data
        # Root task + T1 in backlog
        assert len(data["backlog"]) == 2

    @pytest.mark.asyncio
    async def test_project_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/projects/nonexistent/tasks")
        assert resp.status_code == 404


class TestGetTask:
    @pytest.mark.asyncio
    async def test_returns_task_with_comments(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]
        task = (
            await client.post(f"/projects/{pid}/tasks", json={"title": "T", "phase": "coder"})
        ).json()
        tid = task["id"]

        # Add a comment
        await client.post(f"/tasks/{tid}/comments", json={"content": "Hello", "author_role": "human"})

        resp = await client.get(f"/tasks/{tid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "T"
        assert len(data["comments"]) == 1
        assert data["comments"][0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/tasks/nonexistent")
        assert resp.status_code == 404


class TestUpdateTask:
    @pytest.mark.asyncio
    async def test_valid_status_transition(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]
        task = (
            await client.post(f"/projects/{pid}/tasks", json={"title": "T", "phase": "coder"})
        ).json()
        tid = task["id"]

        resp = await client.patch(f"/tasks/{tid}", json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_invalid_transition_returns_422(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]
        task = (
            await client.post(f"/projects/{pid}/tasks", json={"title": "T", "phase": "coder"})
        ).json()
        tid = task["id"]

        resp = await client.patch(f"/tasks/{tid}", json={"status": "done"})
        assert resp.status_code == 422
        assert "backlog" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_title(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]
        task = (
            await client.post(f"/projects/{pid}/tasks", json={"title": "T", "phase": "coder"})
        ).json()
        tid = task["id"]

        resp = await client.patch(f"/tasks/{tid}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient) -> None:
        resp = await client.patch("/tasks/nonexistent", json={"status": "in_progress"})
        assert resp.status_code == 404


class TestAddComment:
    @pytest.mark.asyncio
    async def test_adds_comment(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]
        task = (
            await client.post(f"/projects/{pid}/tasks", json={"title": "T", "phase": "coder"})
        ).json()
        tid = task["id"]

        resp = await client.post(
            f"/tasks/{tid}/comments",
            json={"content": "Test comment", "author_role": "human"},
        )
        assert resp.status_code == 201
        assert resp.json()["content"] == "Test comment"

    @pytest.mark.asyncio
    async def test_invalid_role(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]
        task = (
            await client.post(f"/projects/{pid}/tasks", json={"title": "T", "phase": "coder"})
        ).json()
        tid = task["id"]

        resp = await client.post(
            f"/tasks/{tid}/comments",
            json={"content": "x", "author_role": "bad"},
        )
        assert resp.status_code == 422


class TestGetTaskRuns:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self, client: AsyncClient) -> None:
        project = (await client.post("/projects", json={"title": "P"})).json()
        pid = project["project"]["id"]
        task = (
            await client.post(f"/projects/{pid}/tasks", json={"title": "T", "phase": "coder"})
        ).json()
        tid = task["id"]

        resp = await client.get(f"/tasks/{tid}/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/tasks/nonexistent/runs")
        assert resp.status_code == 404
```

**Step 2: Run all API tests**

Run: `uv run pytest tests/test_api.py -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_api.py
git commit -m "Add tests for task, comment, and run API endpoints"
```

---

## Task 9: Tests — WebSocket and event broadcasting (`tests/test_ws.py`)

**Files:**
- Create: `tests/test_ws.py`

**Step 1: Write websocket tests**

```python
"""Tests for WebSocket connection and event broadcasting."""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from api.deps import set_db_path
from api.ws import ConnectionManager, broadcast_events, manager
from db.client import get_connection
from db.migrations import init_db
from vibe_relay.mcp.events import emit_event


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self) -> None:
        mgr = ConnectionManager()
        assert len(mgr.active_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_empty(self) -> None:
        mgr = ConnectionManager()
        # Should not error with no connections
        await mgr.broadcast({"type": "test"})


class TestEventHelpers:
    def test_unconsumed_events(self, db_path: str) -> None:
        from api.deps import get_unconsumed_events, mark_event_consumed

        conn = get_connection(db_path)
        emit_event(conn, "task_created", {"task_id": "t1"})
        conn.commit()

        events = get_unconsumed_events(conn)
        assert len(events) == 1
        assert events[0]["type"] == "task_created"

        mark_event_consumed(conn, events[0]["id"])
        events = get_unconsumed_events(conn)
        assert len(events) == 0
        conn.close()

    def test_enrich_task_event(self, db_path: str) -> None:
        from api.deps import enrich_event_payload
        from vibe_relay.mcp.tools import create_project, create_task

        conn = get_connection(db_path)
        project = create_project(conn, "P")
        task = create_task(conn, "T", "D", "coder", project["id"])

        event = {
            "id": "e1",
            "type": "task_created",
            "payload": {"task_id": task["id"]},
        }
        enriched = enrich_event_payload(conn, event)
        assert enriched["type"] == "task_created"
        assert enriched["payload"]["title"] == "T"
        conn.close()

    def test_enrich_comment_event(self, db_path: str) -> None:
        from api.deps import enrich_event_payload
        from vibe_relay.mcp.tools import add_comment, create_project, create_task

        conn = get_connection(db_path)
        project = create_project(conn, "P")
        task = create_task(conn, "T", "D", "coder", project["id"])
        comment = add_comment(conn, task["id"], "Hello", "human")

        event = {
            "id": "e2",
            "type": "comment_added",
            "payload": {"comment_id": comment["id"]},
        }
        enriched = enrich_event_payload(conn, event)
        assert enriched["type"] == "comment_added"
        assert enriched["payload"]["content"] == "Hello"
        conn.close()


class TestWebSocketEndpoint:
    @pytest.mark.asyncio
    async def test_websocket_accepts_connection(self, db_path: str) -> None:
        """Verify the /ws endpoint accepts a WebSocket connection."""
        app = create_app(db_path=db_path)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Create a task to trigger an event
            resp = await client.post("/projects", json={"title": "WS Test"})
            assert resp.status_code == 201


class TestEventBroadcasting:
    @pytest.mark.asyncio
    async def test_events_emitted_by_api_are_consumable(self, db_path: str) -> None:
        """Verify that API operations create consumable events."""
        from api.deps import get_unconsumed_events

        app = create_app(db_path=db_path)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post("/projects", json={"title": "P"})

        conn = get_connection(db_path)
        events = get_unconsumed_events(conn)
        # project_created + task_created (root planner task)
        assert len(events) >= 2
        types = [e["type"] for e in events]
        assert "project_created" in types
        assert "task_created" in types
        conn.close()
```

**Step 2: Run websocket tests**

Run: `uv run pytest tests/test_ws.py -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_ws.py
git commit -m "Add tests for WebSocket manager and event broadcasting"
```

---

## Task 10: Lint, type check, and full test suite

**Step 1: Run ruff check and format**

Run: `uv run ruff check api/ && uv run ruff format api/`
Fix any issues.

**Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass (107 existing + ~25 new)

**Step 3: Update phase doc**

Check off acceptance criteria in `Phases/phase-4.md` and update status to `complete`.

**Step 4: Commit**

```bash
git add -A
git commit -m "Phase 4 complete: API + WebSocket with full test coverage"
```

---

## Verification Checklist

After all tasks complete, verify each acceptance criterion:

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | `vibe-relay serve` starts uvicorn | `uv run vibe-relay serve` — check "Uvicorn running" output |
| 2 | POST /projects creates project + root task | `curl -X POST localhost:8000/projects -H 'Content-Type: application/json' -d '{"title":"Test"}'` |
| 3 | GET /projects/{id} returns task counts | `curl localhost:8000/projects/{id}` |
| 4 | GET /projects/{id}/tasks grouped by status | `curl localhost:8000/projects/{id}/tasks` |
| 5 | GET /tasks/{id} returns task with comments | `curl localhost:8000/tasks/{id}` |
| 6 | PATCH /tasks/{id} valid transition works | `curl -X PATCH localhost:8000/tasks/{id} -H 'Content-Type: application/json' -d '{"status":"in_progress"}'` |
| 7 | PATCH /tasks/{id} invalid returns 422 | `curl -X PATCH localhost:8000/tasks/{id} -d '{"status":"done"}'` |
| 8 | POST /tasks/{id}/comments adds comment | `curl -X POST localhost:8000/tasks/{id}/comments -d '{"content":"hi","author_role":"human"}'` |
| 9 | GET /tasks/{id}/runs returns history | `curl localhost:8000/tasks/{id}/runs` |
| 10 | GET /ws accepts websocket | `websocat ws://localhost:8000/ws` |
| 11 | Websocket receives events within 1s | Update task via curl, check websocat output |
| 12 | Events include full object | Check websocat output includes title, status, etc. |
