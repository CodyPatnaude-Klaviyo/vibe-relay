"""MCP server for vibe-relay.

Exposes tools for board management via stdio transport.
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
from typing import Any

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
    def create_project(
        title: str,
        description: str = "",
        repo_path: str | None = None,
        base_branch: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.create_project(conn, title, description, repo_path, base_branch)
        return json.dumps(result, indent=2)

    @server.tool(description="Create workflow steps for a project")
    def create_workflow_steps(
        project_id: str,
        steps: list[dict[str, Any]],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.create_workflow_steps(conn, project_id, steps)
        return json.dumps(result, indent=2)

    @server.tool(description="Return workflow steps for a project")
    def get_workflow_steps(project_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        conn = _get_conn(ctx)
        result = tools.get_workflow_steps(conn, project_id)
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

    @server.tool(description="Return non-cancelled tasks at a given workflow step")
    def get_my_tasks(
        step_id: str, project_id: str | None = None, ctx: Context = None  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.get_my_tasks(conn, step_id, project_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Create a new task at a workflow step")
    def create_task(
        title: str,
        description: str,
        step_id: str,
        project_id: str,
        parent_task_id: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.create_task(
            conn, title, description, step_id, project_id, parent_task_id
        )
        return json.dumps(result, indent=2)

    @server.tool(description="Bulk create subtasks under a parent task. Use 'dependencies' to atomically set up blocking edges between tasks in the same batch (e.g. [{\"from_index\": 0, \"to_index\": 3}] means task at index 0 blocks task at index 3). Use 'cascade_deps_from' to re-block that task's successors on all newly created tasks (keeps downstream workstreams blocked until these tasks complete).")
    def create_subtasks(
        parent_task_id: str,
        tasks: list[dict[str, str]],
        default_step_id: str | None = None,
        dependencies: list[dict[str, int]] | None = None,
        cascade_deps_from: str | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.create_subtasks(conn, parent_task_id, tasks, default_step_id, dependencies, cascade_deps_from)
        return json.dumps(result, indent=2)

    @server.tool(
        description="Move a task to a different workflow step (enforces step transitions)"
    )
    def move_task(
        task_id: str,
        target_step_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.move_task(conn, task_id, target_step_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Cancel a task")
    def cancel_task(task_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        conn = _get_conn(ctx)
        result = tools.cancel_task(conn, task_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Uncancel a previously cancelled task")
    def uncancel_task(task_id: str, ctx: Context = None) -> str:  # type: ignore[assignment]
        conn = _get_conn(ctx)
        result = tools.uncancel_task(conn, task_id)
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

    @server.tool(
        description="Add a dependency: successor is blocked until predecessor reaches Done"
    )
    def add_dependency(
        predecessor_id: str,
        successor_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.add_dependency(conn, predecessor_id, successor_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Remove a dependency edge")
    def remove_dependency(
        dependency_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.remove_dependency(conn, dependency_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Get predecessors and successors for a task")
    def get_dependencies(
        task_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.get_dependencies(conn, task_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Approve a milestone's plan, enabling child task dispatch")
    def approve_plan(
        task_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.approve_plan(conn, task_id)
        return json.dumps(result, indent=2)

    @server.tool(
        description="Move a task to Done, unblock dependents, auto-advance parent"
    )
    def complete_task(
        task_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.complete_task(conn, task_id)
        return json.dumps(result, indent=2)

    @server.tool(description="Set the output field on a task (research findings)")
    def set_task_output(
        task_id: str,
        output: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        conn = _get_conn(ctx)
        result = tools.set_task_output(conn, task_id, output)
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
