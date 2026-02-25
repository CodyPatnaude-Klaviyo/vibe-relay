"""Tests for WebSocket connection manager and event helpers.

Covers ConnectionManager unit tests, event helper functions, and
verification that API operations emit consumable events.
"""

import json
import sqlite3
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from api.deps import (
    enrich_event_payload,
    get_unconsumed_events,
    mark_event_consumed,
)
from api.ws import ConnectionManager
from db.client import get_connection
from db.migrations import init_db


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.close()
    return path


@pytest.fixture()
def conn(db_path: str) -> sqlite3.Connection:
    """A raw DB connection for direct event/helper testing."""
    c = get_connection(db_path)
    yield c  # type: ignore[misc]
    c.close()


@pytest_asyncio.fixture()
async def client(db_path: str) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=db_path)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    payload: dict[str, Any],
    consumed: int = 0,
) -> str:
    """Insert a raw event row for testing. Returns the event ID."""
    event_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO events (id, type, payload, created_at, consumed) VALUES (?, ?, ?, ?, ?)",
        (event_id, event_type, json.dumps(payload), now, consumed),
    )
    conn.commit()
    return event_id


def _insert_project(
    conn: sqlite3.Connection, project_id: str, title: str = "Test"
) -> None:
    """Insert a project row for FK references."""
    now = _now()
    conn.execute(
        "INSERT INTO projects (id, title, description, status, created_at, updated_at) VALUES (?, ?, '', 'active', ?, ?)",
        (project_id, title, now, now),
    )
    conn.commit()


def _insert_step(
    conn: sqlite3.Connection,
    step_id: str,
    project_id: str,
    name: str = "Implement",
    position: int = 0,
    system_prompt: str | None = "You are an agent",
) -> None:
    """Insert a workflow step row for FK references."""
    now = _now()
    conn.execute(
        "INSERT INTO workflow_steps (id, project_id, name, position, system_prompt, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (step_id, project_id, name, position, system_prompt, now),
    )
    conn.commit()


def _insert_task(
    conn: sqlite3.Connection,
    task_id: str,
    project_id: str,
    step_id: str,
    title: str = "Test Task",
) -> None:
    """Insert a task row for FK references."""
    now = _now()
    conn.execute(
        """INSERT INTO tasks (id, project_id, parent_task_id, title, description, step_id, cancelled, created_at, updated_at)
           VALUES (?, ?, NULL, ?, '', ?, 0, ?, ?)""",
        (task_id, project_id, title, step_id, now, now),
    )
    conn.commit()


def _insert_comment(
    conn: sqlite3.Connection,
    comment_id: str,
    task_id: str,
    author_role: str = "human",
    content: str = "Test comment",
) -> None:
    """Insert a comment row for FK references."""
    now = _now()
    conn.execute(
        "INSERT INTO comments (id, task_id, author_role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (comment_id, task_id, author_role, content, now),
    )
    conn.commit()


# ── TestConnectionManager ─────────────────────────────────


class TestConnectionManager:
    """Unit tests for the ConnectionManager class."""

    def test_starts_with_no_connections(self) -> None:
        mgr = ConnectionManager()
        assert mgr.active_connections == []

    @pytest.mark.asyncio
    async def test_connect_adds_websocket(self) -> None:
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        assert ws in mgr.active_connections
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_websocket(self) -> None:
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        assert ws not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections(self) -> None:
        mgr = ConnectionManager()
        # Should not raise
        await mgr.broadcast({"type": "test", "payload": {}})

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self) -> None:
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        msg = {"type": "task_moved", "payload": {"task_id": "123"}}
        await mgr.broadcast(msg)

        ws1.send_json.assert_awaited_once_with(msg)
        ws2.send_json.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self) -> None:
        mgr = ConnectionManager()
        alive_ws = AsyncMock()
        dead_ws = AsyncMock()
        dead_ws.send_json.side_effect = RuntimeError("connection closed")

        await mgr.connect(alive_ws)
        await mgr.connect(dead_ws)

        await mgr.broadcast({"type": "test", "payload": {}})

        # Dead connection should be removed
        assert dead_ws not in mgr.active_connections
        assert alive_ws in mgr.active_connections

    @pytest.mark.asyncio
    async def test_multiple_connect_disconnect(self) -> None:
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()

        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.connect(ws3)
        assert len(mgr.active_connections) == 3

        mgr.disconnect(ws2)
        assert len(mgr.active_connections) == 2
        assert ws2 not in mgr.active_connections


# ── TestEventHelpers ──────────────────────────────────────


class TestEventHelpers:
    """Tests for get_unconsumed_events, mark_event_consumed, enrich_event_payload."""

    def test_get_unconsumed_events_empty(self, conn: sqlite3.Connection) -> None:
        events = get_unconsumed_events(conn)
        assert events == []

    def test_get_unconsumed_events_returns_unconsumed(
        self, conn: sqlite3.Connection
    ) -> None:
        eid = _insert_event(conn, "test_event", {"key": "val"})
        events = get_unconsumed_events(conn)
        assert len(events) == 1
        assert events[0]["id"] == eid
        assert events[0]["type"] == "test_event"
        assert events[0]["payload"] == {"key": "val"}

    def test_get_unconsumed_events_skips_consumed(
        self, conn: sqlite3.Connection
    ) -> None:
        _insert_event(conn, "consumed_event", {"a": 1}, consumed=1)
        _insert_event(conn, "unconsumed_event", {"b": 2}, consumed=0)
        events = get_unconsumed_events(conn)
        assert len(events) == 1
        assert events[0]["type"] == "unconsumed_event"

    def test_mark_event_consumed(self, conn: sqlite3.Connection) -> None:
        eid = _insert_event(conn, "to_consume", {"x": 1})
        mark_event_consumed(conn, eid)

        events = get_unconsumed_events(conn)
        assert len(events) == 0

        # Verify directly in DB
        row = conn.execute(
            "SELECT consumed FROM events WHERE id = ?", (eid,)
        ).fetchone()
        assert row["consumed"] == 1

    def test_get_unconsumed_events_ordered_by_created_at(
        self, conn: sqlite3.Connection
    ) -> None:
        eid1 = _insert_event(conn, "first", {"order": 1})
        eid2 = _insert_event(conn, "second", {"order": 2})
        events = get_unconsumed_events(conn)
        assert events[0]["id"] == eid1
        assert events[1]["id"] == eid2

    def test_enrich_task_created_event(self, conn: sqlite3.Connection) -> None:
        project_id = "proj-001"
        step_id = "step-001"
        task_id = "task-001"
        _insert_project(conn, project_id)
        _insert_step(conn, step_id, project_id)
        _insert_task(conn, task_id, project_id, step_id, title="Enriched Task")

        event = {"type": "task_created", "payload": {"task_id": task_id}}
        enriched = enrich_event_payload(conn, event)

        assert enriched["type"] == "task_created"
        assert enriched["payload"]["id"] == task_id
        assert enriched["payload"]["title"] == "Enriched Task"
        assert enriched["payload"]["step_name"] == "Implement"

    def test_enrich_task_moved_event(self, conn: sqlite3.Connection) -> None:
        project_id = "proj-002"
        step_id = "step-002"
        task_id = "task-002"
        _insert_project(conn, project_id)
        _insert_step(conn, step_id, project_id)
        _insert_task(conn, task_id, project_id, step_id, title="Moved Task")

        event = {"type": "task_moved", "payload": {"task_id": task_id}}
        enriched = enrich_event_payload(conn, event)

        assert enriched["type"] == "task_moved"
        assert enriched["payload"]["id"] == task_id

    def test_enrich_task_cancelled_event(self, conn: sqlite3.Connection) -> None:
        project_id = "proj-003"
        step_id = "step-003"
        task_id = "task-003"
        _insert_project(conn, project_id)
        _insert_step(conn, step_id, project_id)
        _insert_task(conn, task_id, project_id, step_id)

        event = {"type": "task_cancelled", "payload": {"task_id": task_id}}
        enriched = enrich_event_payload(conn, event)

        assert enriched["type"] == "task_cancelled"
        assert enriched["payload"]["id"] == task_id

    def test_enrich_task_uncancelled_event(self, conn: sqlite3.Connection) -> None:
        project_id = "proj-004"
        step_id = "step-004"
        task_id = "task-004"
        _insert_project(conn, project_id)
        _insert_step(conn, step_id, project_id)
        _insert_task(conn, task_id, project_id, step_id)

        event = {"type": "task_uncancelled", "payload": {"task_id": task_id}}
        enriched = enrich_event_payload(conn, event)

        assert enriched["type"] == "task_uncancelled"
        assert enriched["payload"]["id"] == task_id

    def test_enrich_comment_added_event(self, conn: sqlite3.Connection) -> None:
        project_id = "proj-005"
        step_id = "step-005"
        task_id = "task-005"
        comment_id = "comment-001"
        _insert_project(conn, project_id)
        _insert_step(conn, step_id, project_id)
        _insert_task(conn, task_id, project_id, step_id)
        _insert_comment(conn, comment_id, task_id, content="Hello world")

        event = {
            "type": "comment_added",
            "payload": {"comment_id": comment_id, "task_id": task_id},
        }
        enriched = enrich_event_payload(conn, event)

        assert enriched["type"] == "comment_added"
        assert enriched["payload"]["id"] == comment_id
        assert enriched["payload"]["content"] == "Hello world"

    def test_enrich_project_created_event(self, conn: sqlite3.Connection) -> None:
        project_id = "proj-006"
        _insert_project(conn, project_id, title="My Project")

        event = {"type": "project_created", "payload": {"project_id": project_id}}
        enriched = enrich_event_payload(conn, event)

        assert enriched["type"] == "project_created"
        assert enriched["payload"]["id"] == project_id
        assert enriched["payload"]["title"] == "My Project"

    def test_enrich_unknown_event_type_returns_raw(
        self, conn: sqlite3.Connection
    ) -> None:
        event = {"type": "unknown_type", "payload": {"foo": "bar"}}
        enriched = enrich_event_payload(conn, event)
        assert enriched == {"type": "unknown_type", "payload": {"foo": "bar"}}

    def test_enrich_missing_entity_returns_raw(self, conn: sqlite3.Connection) -> None:
        event = {"type": "task_created", "payload": {"task_id": "nonexistent"}}
        enriched = enrich_event_payload(conn, event)
        # Falls back to raw payload because task not found
        assert enriched == {
            "type": "task_created",
            "payload": {"task_id": "nonexistent"},
        }


# ── TestEventBroadcasting ─────────────────────────────────


class TestEventBroadcasting:
    """Verify that API operations create consumable events in the DB."""

    @pytest.mark.asyncio
    async def test_create_project_emits_events(
        self, client: AsyncClient, conn: sqlite3.Connection
    ) -> None:
        resp = await client.post(
            "/projects", json={"title": "Event Test", "description": "test"}
        )
        assert resp.status_code == 201

        # Check events table for project_created and task_created
        events = get_unconsumed_events(conn)
        event_types = [e["type"] for e in events]
        assert "project_created" in event_types
        assert "task_created" in event_types

    @pytest.mark.asyncio
    async def test_create_task_emits_event(
        self, client: AsyncClient, conn: sqlite3.Connection
    ) -> None:
        proj = await client.post(
            "/projects", json={"title": "Task Events", "description": ""}
        )
        project_id = proj.json()["project"]["id"]

        # Get first step id for task creation
        steps_resp = await client.get(f"/projects/{project_id}/steps")
        step_id = steps_resp.json()[0]["id"]

        # Consume existing events
        for e in get_unconsumed_events(conn):
            mark_event_consumed(conn, e["id"])

        # Create a new task
        await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "New Task", "step_id": step_id},
        )

        events = get_unconsumed_events(conn)
        event_types = [e["type"] for e in events]
        assert "task_created" in event_types

    @pytest.mark.asyncio
    async def test_move_task_emits_event(
        self, client: AsyncClient, conn: sqlite3.Connection
    ) -> None:
        proj = await client.post("/projects", json={"title": "Move Events"})
        task_id = proj.json()["task"]["id"]
        project_id = proj.json()["project"]["id"]

        # Get steps to find target
        steps_resp = await client.get(f"/projects/{project_id}/steps")
        steps = steps_resp.json()
        # Root task is at first step; move to second
        target_step_id = steps[1]["id"]

        # Consume existing events
        for e in get_unconsumed_events(conn):
            mark_event_consumed(conn, e["id"])

        # Move task via patch
        await client.patch(f"/tasks/{task_id}", json={"step_id": target_step_id})

        events = get_unconsumed_events(conn)
        event_types = [e["type"] for e in events]
        assert "task_moved" in event_types

    @pytest.mark.asyncio
    async def test_add_comment_emits_event(
        self, client: AsyncClient, conn: sqlite3.Connection
    ) -> None:
        proj = await client.post("/projects", json={"title": "Comment Events"})
        task_id = proj.json()["task"]["id"]

        # Consume existing events
        for e in get_unconsumed_events(conn):
            mark_event_consumed(conn, e["id"])

        # Add a comment
        await client.post(
            f"/tasks/{task_id}/comments",
            json={"content": "Hello", "author_role": "human"},
        )

        events = get_unconsumed_events(conn)
        event_types = [e["type"] for e in events]
        assert "comment_added" in event_types

    @pytest.mark.asyncio
    async def test_delete_project_emits_event(
        self, client: AsyncClient, conn: sqlite3.Connection
    ) -> None:
        proj = await client.post("/projects", json={"title": "Delete Events"})
        project_id = proj.json()["project"]["id"]

        # Consume existing events
        for e in get_unconsumed_events(conn):
            mark_event_consumed(conn, e["id"])

        # Delete project
        await client.delete(f"/projects/{project_id}")

        events = get_unconsumed_events(conn)
        event_types = [e["type"] for e in events]
        assert "project_updated" in event_types

    @pytest.mark.asyncio
    async def test_events_are_consumable(
        self, client: AsyncClient, conn: sqlite3.Connection
    ) -> None:
        await client.post("/projects", json={"title": "Consumable Events"})

        events = get_unconsumed_events(conn)
        assert len(events) > 0

        # Consume all
        for e in events:
            mark_event_consumed(conn, e["id"])

        # Verify none remain
        remaining = get_unconsumed_events(conn)
        assert len(remaining) == 0
