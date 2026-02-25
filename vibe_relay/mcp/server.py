"""MCP server for vibe-relay.

Exposes 8 tools for board management via stdio transport.
Launched by `vibe-relay mcp [--task-id <id>]`.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from db.migrations import init_db
from vibe_relay.mcp import tools


@dataclass
class AppState:
    """Lifespan state accessible by tools via Context."""

    conn: sqlite3.Connection
    task_id: str | None


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppState]:  # type: ignore[type-arg]
    """Open DB connection at startup, close on shutdown."""
    db_path = os.environ.get("VIBE_RELAY_DB", "~/.vibe-relay/vibe-relay.db")
    db_path = str(Path(db_path).expanduser())

    conn = init_db(db_path)
    task_id = os.environ.get("VIBE_RELAY_TASK_ID")
    try:
        yield AppState(conn=conn, task_id=task_id)
    finally:
        conn.close()


def _get_conn(ctx: Context) -> sqlite3.Connection:
    """Extract DB connection from Context lifespan state."""
    state: AppState = ctx.request_context.lifespan_context
    return state.conn


def create_server() -> FastMCP:
    """Create and configure the MCP server with all tools registered."""
    server = FastMCP(
        name="vibe-relay",
        instructions="Board management tools for the vibe-relay multi-agent orchestration system.",
        lifespan=app_lifespan,
    )

    @server.tool(description="Create a new project")
    def create_project(title: str, description: str = "", ctx: Context = None) -> str:  # type: ignore[assignment]
        conn = _get_conn(ctx)
        result = tools.create_project(conn, title, description)
        return json.dumps(result, indent=2)

    @server.tool(description="Return the full board state for a project")
    def get_board(project_id: str, ctx: Context) -> str:
        conn = _get_conn(ctx)
        result = tools.get_board(conn, project_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Return a single task with its full comment thread")
    def get_task(task_id: str, ctx: Context) -> str:
        conn = _get_conn(ctx)
        result = tools.get_task(conn, task_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Return in_progress tasks for a given phase")
    def get_my_tasks(phase: str, project_id: str | None = None, ctx: Context = None) -> str:  # type: ignore[assignment]
        conn = _get_conn(ctx)
        result = tools.get_my_tasks(conn, phase, project_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Create a new task")
    def create_task(
        title: str,
        description: str,
        phase: str,
        project_id: str,
        parent_task_id: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.create_task(
            conn, title, description, phase, project_id, parent_task_id
        )
        return json.dumps(result, indent=2)

    @server.tool(description="Bulk create subtasks under a parent task")
    def create_subtasks(
        parent_task_id: str,
        tasks: list[dict[str, str]],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.create_subtasks(conn, parent_task_id, tasks)
        return json.dumps(result, indent=2)

    @server.tool(
        description="Move a task to a new status (enforces state machine)"
    )
    def update_task_status(
        task_id: str, status: str, ctx: Context = None  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.update_task_status(conn, task_id, status)
        return json.dumps(result, indent=2)

    @server.tool(description="Add a comment to a task's thread")
    def add_comment(
        task_id: str,
        content: str,
        author_role: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.add_comment(conn, task_id, content, author_role)
        return json.dumps(result, indent=2)

    @server.tool(description="Mark a task done and check sibling completion")
    def complete_task(task_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        conn = _get_conn(ctx)
        result = tools.complete_task(conn, task_id)
        return json.dumps(result, indent=2)

    return server


def run_server(task_id: str | None = None, db_path: str | None = None) -> None:
    """Entry point: create server and run on stdio."""
    if db_path:
        os.environ["VIBE_RELAY_DB"] = db_path
    if task_id:
        os.environ["VIBE_RELAY_TASK_ID"] = task_id

    server = create_server()
    server.run(transport="stdio")
