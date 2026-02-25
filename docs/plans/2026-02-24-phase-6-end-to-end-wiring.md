# Phase 6: End-to-End Wiring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the state machine to the agent runner so status transitions automatically trigger the right agent, completing the autonomous loop.

**Architecture:** A trigger processor runs as an asyncio background task alongside the existing WS broadcaster inside the FastAPI lifespan. It polls the `events` table (using a separate `trigger_consumed` column) for task state-change events and dispatches agent runs via `launch_agent()` in background threads (`asyncio.to_thread`). Project creation auto-starts the planner. When a planner completes, its subtasks are kicked off. When all sibling tasks complete, an orchestrator task is auto-created. Worktrees are cleaned up when tasks reach `done`.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL mode), asyncio, existing runner modules

**Spec:** `Phases/phase-6.md`

---

## Task 1: Schema Migration + Trigger Event Helpers

Add a `trigger_consumed` column to the events table so the trigger processor can consume events independently from the WS broadcaster. Add helper functions to query and mark trigger events.

**Files:**
- Modify: `db/schema.py:62-69` — add `trigger_consumed` column to events CREATE TABLE
- Modify: `db/migrations.py:18-22` — add ALTER TABLE migration for existing DBs
- Modify: `api/deps.py` — add `get_unconsumed_trigger_events()` and `mark_trigger_consumed()`
- Create: `tests/test_trigger_helpers.py`

### Step 1: Update events table schema

In `db/schema.py`, add `trigger_consumed` to the events table definition:

```python
"events": """
    CREATE TABLE IF NOT EXISTS events (
        id                TEXT PRIMARY KEY,
        type              TEXT NOT NULL,
        payload           TEXT NOT NULL,
        created_at        TEXT NOT NULL,
        consumed          INTEGER NOT NULL DEFAULT 0,
        trigger_consumed  INTEGER NOT NULL DEFAULT 0
    )
""",
```

### Step 2: Add ALTER TABLE migration

In `db/migrations.py`, after the `CREATE TABLE` loop in `run_migrations()`, add an idempotent ALTER TABLE:

```python
def run_migrations(conn: sqlite3.Connection) -> None:
    """Create all tables in dependency order. Idempotent."""
    for table_name in TABLE_CREATION_ORDER:
        conn.execute(TABLES[table_name])
    conn.commit()

    # Add trigger_consumed column to events if it doesn't exist (Phase 6)
    try:
        conn.execute("ALTER TABLE events ADD COLUMN trigger_consumed INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
```

### Step 3: Add trigger event helpers to deps.py

Add these two functions to `api/deps.py`:

```python
def get_unconsumed_trigger_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Fetch unconsumed trigger events (task state changes and orchestrator triggers)."""
    rows = conn.execute(
        """SELECT id, type, payload, created_at FROM events
           WHERE trigger_consumed = 0
             AND type IN ('task_updated', 'orchestrator_trigger')
           ORDER BY created_at"""
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


def mark_trigger_consumed(conn: sqlite3.Connection, event_id: str) -> None:
    """Mark an event as consumed by the trigger processor."""
    conn.execute("UPDATE events SET trigger_consumed = 1 WHERE id = ?", (event_id,))
    conn.commit()
```

### Step 4: Write tests for trigger helpers

Create `tests/test_trigger_helpers.py`:

```python
"""Tests for trigger event helpers in api/deps.py."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from api.deps import get_unconsumed_trigger_events, mark_trigger_consumed
from db.migrations import init_db


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    connection = init_db(db_path)
    yield connection
    connection.close()


def _emit(conn, event_type, payload):
    eid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO events (id, type, payload, created_at) VALUES (?, ?, ?, ?)",
        (eid, event_type, json.dumps(payload), now),
    )
    conn.commit()
    return eid


class TestGetUnconsumedTriggerEvents:
    def test_returns_task_updated_events(self, conn):
        _emit(conn, "task_updated", {"task_id": "t1", "old_status": "backlog", "new_status": "in_progress"})
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1
        assert events[0]["type"] == "task_updated"

    def test_returns_orchestrator_trigger_events(self, conn):
        _emit(conn, "orchestrator_trigger", {"parent_task_id": "p1", "project_id": "proj1"})
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1
        assert events[0]["type"] == "orchestrator_trigger"

    def test_ignores_other_event_types(self, conn):
        _emit(conn, "comment_added", {"comment_id": "c1"})
        _emit(conn, "task_created", {"task_id": "t1"})
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 0

    def test_ignores_already_trigger_consumed(self, conn):
        eid = _emit(conn, "task_updated", {"task_id": "t1", "old_status": "backlog", "new_status": "in_progress"})
        mark_trigger_consumed(conn, eid)
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 0

    def test_ws_consumed_does_not_affect_trigger(self, conn):
        eid = _emit(conn, "task_updated", {"task_id": "t1", "old_status": "backlog", "new_status": "in_progress"})
        conn.execute("UPDATE events SET consumed = 1 WHERE id = ?", (eid,))
        conn.commit()
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1  # Still visible to trigger processor


class TestMarkTriggerConsumed:
    def test_marks_event(self, conn):
        eid = _emit(conn, "task_updated", {"task_id": "t1", "old_status": "backlog", "new_status": "in_progress"})
        mark_trigger_consumed(conn, eid)
        row = conn.execute("SELECT trigger_consumed FROM events WHERE id = ?", (eid,)).fetchone()
        assert row["trigger_consumed"] == 1

    def test_does_not_affect_ws_consumed(self, conn):
        eid = _emit(conn, "task_updated", {"task_id": "t1", "old_status": "backlog", "new_status": "in_progress"})
        mark_trigger_consumed(conn, eid)
        row = conn.execute("SELECT consumed FROM events WHERE id = ?", (eid,)).fetchone()
        assert row["consumed"] == 0  # WS consumed flag unchanged
```

### Step 5: Run tests

Run: `uv run pytest tests/test_trigger_helpers.py -v`
Expected: All 7 tests PASS

### Step 6: Lint and commit

```bash
ruff check db/schema.py db/migrations.py api/deps.py tests/test_trigger_helpers.py
ruff format db/schema.py db/migrations.py api/deps.py tests/test_trigger_helpers.py
git add db/schema.py db/migrations.py api/deps.py tests/test_trigger_helpers.py
git commit -m "Add trigger_consumed column and trigger event helpers"
```

---

## Task 2: Trigger Processor

Create the core trigger processor that polls for events and dispatches agent runs with concurrency guards.

**Files:**
- Create: `runner/triggers.py`
- Create: `tests/test_triggers.py`

### Step 1: Create runner/triggers.py

```python
"""Trigger processor for vibe-relay.

Polls the events table for task state changes and dispatches agent runs.
Runs as an asyncio background task inside the FastAPI lifespan.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from api.deps import get_unconsumed_trigger_events, mark_trigger_consumed
from db.client import get_connection

logger = logging.getLogger(__name__)


def has_active_run(conn: Any, task_id: str) -> bool:
    """Check if a task has an active (incomplete) agent run."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM agent_runs WHERE task_id = ? AND completed_at IS NULL",
        (task_id,),
    ).fetchone()
    return row["cnt"] > 0


def count_active_runs(conn: Any) -> int:
    """Count total active (incomplete) agent runs."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM agent_runs WHERE completed_at IS NULL"
    ).fetchone()
    return row["cnt"]


def should_dispatch(event: dict[str, Any]) -> bool:
    """Determine if an event should trigger an agent dispatch.

    Returns True for:
    - task_updated with new_status='in_progress' (agent needs to run)
    - orchestrator_trigger (need to create orchestrator task)
    """
    if event["type"] == "task_updated":
        return event["payload"].get("new_status") == "in_progress"
    if event["type"] == "orchestrator_trigger":
        return True
    return False


def get_task_phase(conn: Any, task_id: str) -> str | None:
    """Get the phase of a task."""
    row = conn.execute("SELECT phase FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row["phase"] if row else None


async def _launch_in_thread(task_id: str, config: dict[str, Any]) -> None:
    """Launch an agent in a background thread."""
    from runner.launcher import LaunchError, launch_agent
    from runner.worktree import WorktreeError

    try:
        result = await asyncio.to_thread(launch_agent, task_id, config)
        logger.info(
            "Agent completed for task %s: exit_code=%d session_id=%s",
            task_id,
            result.exit_code,
            result.session_id,
        )
    except (LaunchError, WorktreeError) as e:
        logger.error("Failed to launch agent for task %s: %s", task_id, e)
    except Exception:
        logger.exception("Unexpected error launching agent for task %s", task_id)


async def _cleanup_worktree_in_thread(
    task_id: str, worktree_path: str, repo_path: str
) -> None:
    """Clean up a worktree in a background thread."""
    from runner.worktree import WorktreeError, remove_worktree

    try:
        await asyncio.to_thread(
            remove_worktree, Path(worktree_path), Path(repo_path)
        )
        logger.info("Cleaned up worktree for task %s: %s", task_id, worktree_path)
    except WorktreeError as e:
        logger.warning("Failed to clean up worktree for task %s: %s", task_id, e)


async def process_triggers(db_path: str, config: dict[str, Any]) -> None:
    """Background task that polls events and dispatches agent runs.

    Dispatch rules:
    - backlog -> in_progress: launch agent matching task phase
    - in_review -> in_progress (sent back): resume coder agent
    - orchestrator_trigger: handled by complete_task (task already created)

    Concurrency guards:
    - Skip if task already has an active run
    - Skip if at max_parallel_agents capacity (leave event unconsumed for retry)
    """
    max_agents = config.get("max_parallel_agents", 3)

    while True:
        try:
            conn = get_connection(db_path)
            try:
                events = get_unconsumed_trigger_events(conn)
                for event in events:
                    if not should_dispatch(event):
                        mark_trigger_consumed(conn, event["id"])
                        continue

                    if event["type"] == "task_updated":
                        task_id = event["payload"].get("task_id")
                        if not task_id:
                            mark_trigger_consumed(conn, event["id"])
                            continue

                        new_status = event["payload"].get("new_status")

                        # Handle task moving to in_progress -> launch agent
                        if new_status == "in_progress":
                            if has_active_run(conn, task_id):
                                mark_trigger_consumed(conn, event["id"])
                                continue

                            if count_active_runs(conn) >= max_agents:
                                continue  # At capacity, retry next cycle

                            mark_trigger_consumed(conn, event["id"])
                            asyncio.create_task(_launch_in_thread(task_id, config))

                        # Handle task moving to done -> cleanup worktree
                        elif new_status == "done":
                            task = conn.execute(
                                "SELECT worktree_path FROM tasks WHERE id = ?",
                                (task_id,),
                            ).fetchone()
                            if task and task["worktree_path"]:
                                repo_path = config.get("repo_path", "")
                                asyncio.create_task(
                                    _cleanup_worktree_in_thread(
                                        task_id, task["worktree_path"], repo_path
                                    )
                                )
                            mark_trigger_consumed(conn, event["id"])
                        else:
                            mark_trigger_consumed(conn, event["id"])

                    elif event["type"] == "orchestrator_trigger":
                        # Orchestrator task is created by complete_task directly
                        # Just mark consumed — the task_updated event for the new
                        # orchestrator task will trigger the launch
                        mark_trigger_consumed(conn, event["id"])

            finally:
                conn.close()
        except Exception:
            logger.exception("Error in trigger processor")

        await asyncio.sleep(1)
```

### Step 2: Write tests for trigger processor

Create `tests/test_triggers.py`:

```python
"""Tests for runner/triggers.py — trigger processor."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from db.migrations import init_db
from runner.triggers import (
    count_active_runs,
    has_active_run,
    should_dispatch,
)


@pytest.fixture()
def conn(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    connection = init_db(db_path)
    yield connection
    connection.close()


def _seed_project_and_task(
    conn: sqlite3.Connection,
    phase: str = "coder",
    status: str = "in_progress",
) -> tuple[str, str]:
    pid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, "Test", "active", now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, phase, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tid, pid, "Task", phase, status, now, now),
    )
    conn.commit()
    return pid, tid


def _seed_run(conn: sqlite3.Connection, task_id: str, completed: bool = False) -> str:
    rid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    completed_at = now if completed else None
    conn.execute(
        "INSERT INTO agent_runs (id, task_id, phase, started_at, completed_at) VALUES (?, ?, ?, ?, ?)",
        (rid, task_id, "coder", now, completed_at),
    )
    conn.commit()
    return rid


class TestShouldDispatch:
    def test_task_updated_to_in_progress(self):
        event = {
            "type": "task_updated",
            "payload": {"task_id": "t1", "old_status": "backlog", "new_status": "in_progress"},
        }
        assert should_dispatch(event) is True

    def test_task_updated_to_done(self):
        event = {
            "type": "task_updated",
            "payload": {"task_id": "t1", "old_status": "in_review", "new_status": "done"},
        }
        assert should_dispatch(event) is False

    def test_task_updated_to_in_review(self):
        event = {
            "type": "task_updated",
            "payload": {"task_id": "t1", "old_status": "in_progress", "new_status": "in_review"},
        }
        assert should_dispatch(event) is False

    def test_orchestrator_trigger(self):
        event = {
            "type": "orchestrator_trigger",
            "payload": {"parent_task_id": "p1"},
        }
        assert should_dispatch(event) is True

    def test_comment_added_not_dispatched(self):
        event = {"type": "comment_added", "payload": {"comment_id": "c1"}}
        assert should_dispatch(event) is False


class TestHasActiveRun:
    def test_no_runs(self, conn):
        _, tid = _seed_project_and_task(conn)
        assert has_active_run(conn, tid) is False

    def test_completed_run(self, conn):
        _, tid = _seed_project_and_task(conn)
        _seed_run(conn, tid, completed=True)
        assert has_active_run(conn, tid) is False

    def test_active_run(self, conn):
        _, tid = _seed_project_and_task(conn)
        _seed_run(conn, tid, completed=False)
        assert has_active_run(conn, tid) is True


class TestCountActiveRuns:
    def test_no_runs(self, conn):
        assert count_active_runs(conn) == 0

    def test_counts_only_active(self, conn):
        _, tid1 = _seed_project_and_task(conn)
        _, tid2 = _seed_project_and_task(conn)
        _seed_run(conn, tid1, completed=False)  # active
        _seed_run(conn, tid2, completed=True)    # completed
        assert count_active_runs(conn) == 1

    def test_multiple_active(self, conn):
        _, tid1 = _seed_project_and_task(conn)
        _, tid2 = _seed_project_and_task(conn)
        _seed_run(conn, tid1, completed=False)
        _seed_run(conn, tid2, completed=False)
        assert count_active_runs(conn) == 2
```

### Step 3: Run tests

Run: `uv run pytest tests/test_triggers.py -v`
Expected: All 11 tests PASS

### Step 4: Lint and commit

```bash
ruff check runner/triggers.py tests/test_triggers.py
ruff format runner/triggers.py tests/test_triggers.py
git add runner/triggers.py tests/test_triggers.py
git commit -m "Add trigger processor with dispatch rules and concurrency guard"
```

---

## Task 3: complete_task Enhancements

Modify `complete_task` in MCP tools to auto-create an orchestrator task when all siblings complete, and update tests.

**Files:**
- Modify: `vibe_relay/mcp/tools.py:359-415` — enhance `complete_task`
- Modify: `tests/test_mcp_tools.py` — add tests for orchestrator creation

### Step 1: Update complete_task to create orchestrator task

In `vibe_relay/mcp/tools.py`, replace the `complete_task` function. When `siblings_complete` is True, instead of just emitting an `orchestrator_trigger` event, also create an orchestrator task in `in_progress`:

```python
def complete_task(
    conn: sqlite3.Connection,
    task_id: str,
) -> dict[str, Any]:
    """Mark a task done and check if all siblings are complete.

    When all siblings are complete, creates an orchestrator task
    in `in_progress` status to coordinate the merge/review.
    """
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
                {"task_id": orch_id, "old_status": "backlog", "new_status": "in_progress"},
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
```

Note: The return dict key changes from `orchestrator_triggered` (bool) to `orchestrator_task_id` (str | None). Check if any code references the old key.

### Step 2: Update MCP server if it references the old key

Check `vibe_relay/mcp/server.py` for any references to `orchestrator_triggered` in the `complete_task` tool registration. If found, update to use `orchestrator_task_id`.

### Step 3: Add tests for orchestrator auto-creation

Add to `tests/test_mcp_tools.py`:

```python
class TestCompleteTaskOrchestratorCreation:
    def test_creates_orchestrator_when_siblings_complete(self, conn):
        """When all siblings are done, complete_task creates an orchestrator task."""
        pid, parent_id = _seed(conn, phase="planner")
        # Create two coder subtasks
        t1 = create_task(conn, title="Code A", description="", phase="coder", project_id=pid, parent_task_id=parent_id)
        t2 = create_task(conn, title="Code B", description="", phase="coder", project_id=pid, parent_task_id=parent_id)

        # Move both to in_review then done
        update_task_status(conn, t1["id"], "in_progress")
        update_task_status(conn, t1["id"], "in_review")
        update_task_status(conn, t2["id"], "in_progress")
        update_task_status(conn, t2["id"], "in_review")

        # Complete first — siblings not all done yet
        r1 = complete_task(conn, t1["id"])
        assert r1["siblings_complete"] is False
        assert r1["orchestrator_task_id"] is None

        # Complete second — triggers orchestrator
        r2 = complete_task(conn, t2["id"])
        assert r2["siblings_complete"] is True
        assert r2["orchestrator_task_id"] is not None

        # Verify orchestrator task was created
        orch = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (r2["orchestrator_task_id"],)
        ).fetchone()
        assert orch["phase"] == "orchestrator"
        assert orch["status"] == "in_progress"
        assert orch["parent_task_id"] == parent_id

    def test_no_orchestrator_for_single_task(self, conn):
        """complete_task on a task with no siblings does not create orchestrator."""
        pid, tid = _seed(conn, phase="coder")
        update_task_status(conn, tid, "in_progress")
        update_task_status(conn, tid, "in_review")
        result = complete_task(conn, tid)
        assert result["siblings_complete"] is False
        assert result["orchestrator_task_id"] is None
```

### Step 4: Run all MCP tool tests

Run: `uv run pytest tests/test_mcp_tools.py -v`
Expected: All tests PASS (existing + 2 new)

### Step 5: Commit

```bash
ruff check vibe_relay/mcp/tools.py tests/test_mcp_tools.py
ruff format vibe_relay/mcp/tools.py tests/test_mcp_tools.py
git add vibe_relay/mcp/tools.py tests/test_mcp_tools.py
git commit -m "Create orchestrator task automatically when all siblings complete"
```

---

## Task 4: Auto-Start Planner + Planner Prompt + Serve Wiring

Three smaller changes that complete the wiring:
1. Auto-start the planner when a project is created
2. Update the planner prompt to instruct starting subtasks
3. Wire the trigger processor into the serve command

**Files:**
- Modify: `api/routes.py:65-84` — auto-start planner task
- Modify: `agents/planner.md` — add instruction to start subtasks
- Modify: `api/app.py:15-27` — add trigger processor to lifespan
- Modify: `vibe_relay/cli.py:93-117` — pass full config to create_app
- Modify: `tests/test_api.py` — update create project test expectations

### Step 1: Auto-start planner on project creation

In `api/routes.py`, modify `create_project_endpoint` to transition the root planner task from `backlog` to `in_progress`:

```python
@router.post("/projects", status_code=201)
def create_project_endpoint(
    body: CreateProjectRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Create a new project and a root planner task, auto-started."""
    project = create_project(conn, title=body.title, description=body.description)
    _check_error(project)

    root_task = create_task(
        conn,
        title=f"Plan: {body.title}",
        description=body.description,
        phase="planner",
        project_id=project["id"],
    )
    _check_error(root_task)

    # Auto-start the planner — triggers agent launch via trigger processor
    started = update_task_status(conn, root_task["id"], "in_progress")
    _check_error(started)

    return {"project": project, "task": started}
```

### Step 2: Update create project test expectations

In `tests/test_api.py`, update `TestCreateProject` tests to expect the root task in `in_progress` instead of `backlog`:

Find tests that assert `task["status"] == "backlog"` and change to `task["status"] == "in_progress"`.

### Step 3: Update planner prompt

Replace `agents/planner.md`:

```markdown
# Planner Agent

You are the **Planner** agent in a vibe-relay orchestration system. Your job is to decompose a high-level project description into a structured set of implementation tasks.

## Your responsibilities

1. Read the project description and any existing context carefully.
2. Break the work into discrete, implementable tasks — each one should be completable by a single coder agent in one session.
3. Create subtasks on the board using the `create_subtasks` MCP tool.
4. Assign each task a `phase` of `coder`.
5. Order tasks logically — foundational work first, dependent work later.
6. Write clear titles and descriptions. Each task description should include acceptance criteria so the coder knows when it's done.
7. **After creating subtasks, start each one** by calling `update_task_status(task_id, "in_progress")` on each subtask. This kicks off the coder agents.

## Guidelines

- Prefer smaller, focused tasks over large multi-file changes.
- If a task requires changes across many files, split it into subtasks.
- Include a task for writing tests if the project needs them.
- Do not implement anything yourself — your only output is tasks on the board.
- When you're done planning, call `complete_task` on your planning task.

## Available MCP tools

- `get_board` — see current board state
- `get_task(task_id)` — read a specific task
- `create_subtasks(parent_task_id, tasks[])` — create implementation tasks
- `update_task_status(task_id, status)` — move a task to a new status
- `add_comment(task_id, content, author_role)` — leave notes on tasks
- `complete_task(task_id)` — mark your planning task done
```

### Step 4: Wire trigger processor into create_app

Modify `api/app.py` to accept config and start the trigger processor:

```python
"""FastAPI application for vibe-relay."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import set_db_path
from api.routes import router
from api.ws import broadcast_events


def create_app(db_path: str, config: dict[str, Any] | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Path to the SQLite database.
        config: Full vibe-relay config dict. If provided, enables the
                trigger processor for automatic agent dispatch.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        tasks: list[asyncio.Task[None]] = []
        tasks.append(asyncio.create_task(broadcast_events(db_path)))

        if config is not None:
            from runner.triggers import process_triggers

            tasks.append(asyncio.create_task(process_triggers(db_path, config)))

        yield

        for task in tasks:
            task.cancel()
        for task in tasks:
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

### Step 5: Update CLI serve command to pass config

In `vibe_relay/cli.py`, modify the `serve` command to pass config to `create_app`:

```python
@main.command()
@click.option("--port", default=8000, help="Port to listen on")
@click.option(
    "--reload", "use_reload", is_flag=True, help="Enable auto-reload for development"
)
def serve(port: int, use_reload: bool) -> None:
    """Start the vibe-relay API server with trigger processor."""
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

    app = create_app(db_path=config["db_path"], config=config)
    uvicorn.run(app, host="0.0.0.0", port=port, reload=use_reload)
```

### Step 6: Run all tests

Run: `uv run pytest tests/ -v`
Expected: All tests PASS. The `test_api.py` tests may need adjustment for the root task status change.

### Step 7: Commit

```bash
ruff check api/routes.py api/app.py vibe_relay/cli.py tests/test_api.py
ruff format api/routes.py api/app.py vibe_relay/cli.py tests/test_api.py
git add api/routes.py api/app.py vibe_relay/cli.py agents/planner.md tests/test_api.py
git commit -m "Wire trigger processor into serve, auto-start planner on project creation"
```

---

## Task 5: Integration Tests + Full Loop Smoke Test

Write integration tests that verify the trigger system's dispatch behavior end-to-end (mocked Claude), and a smoke test script for real Claude runs.

**Files:**
- Modify: `tests/test_triggers.py` — add integration tests for dispatch behavior
- Create: `tests/test_full_loop.py` — smoke test (manual, skipped in CI)

### Step 1: Add dispatch integration tests

Add to `tests/test_triggers.py`:

```python
import asyncio
from unittest.mock import patch, MagicMock


class TestTriggerDispatchIntegration:
    """Integration tests that verify dispatch behavior with real DB and mocked launcher."""

    @pytest.mark.asyncio
    @patch("runner.triggers.launch_agent")
    async def test_dispatches_on_in_progress_event(self, mock_launch, tmp_path):
        """Trigger processor dispatches agent when task moves to in_progress."""
        from runner.triggers import process_triggers
        from api.deps import get_unconsumed_trigger_events, mark_trigger_consumed
        from vibe_relay.mcp.events import emit_event

        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)

        # Seed a task
        pid, tid = _seed_project_and_task(conn, phase="coder", status="in_progress")

        # Emit the event that would trigger dispatch
        emit_event(conn, "task_updated", {
            "task_id": tid,
            "old_status": "backlog",
            "new_status": "in_progress",
        })
        conn.commit()

        mock_launch.return_value = MagicMock(exit_code=0, session_id="s1")

        config = {"max_parallel_agents": 3, "db_path": db_path}

        # Run one iteration of the trigger loop
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1

        conn.close()

    @pytest.mark.asyncio
    async def test_respects_max_parallel(self, tmp_path):
        """When at capacity, events are left unconsumed for retry."""
        from api.deps import get_unconsumed_trigger_events
        from vibe_relay.mcp.events import emit_event
        from runner.triggers import count_active_runs

        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)

        pid, tid1 = _seed_project_and_task(conn)
        pid2, tid2 = _seed_project_and_task(conn)

        # Create active runs to reach capacity
        _seed_run(conn, tid1, completed=False)
        _seed_run(conn, tid2, completed=False)

        assert count_active_runs(conn) == 2

        # With max_parallel_agents=2, should be at capacity
        emit_event(conn, "task_updated", {
            "task_id": "new-task",
            "old_status": "backlog",
            "new_status": "in_progress",
        })
        conn.commit()

        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1  # Event still there, not consumed

        conn.close()
```

### Step 2: Create full loop smoke test

Create `tests/test_full_loop.py`:

```python
"""Full loop smoke test for vibe-relay.

This test requires a running vibe-relay server with trigger processor enabled,
and a valid Claude API key. It is NOT part of the regular test suite.

Run manually:
    VIBE_RELAY_URL=http://localhost:8000 uv run pytest tests/test_full_loop.py -v -s

The test:
1. Creates a project via the API
2. Waits for the planner agent to create subtasks
3. Monitors task status changes
4. Manually approves tasks moving to done (to avoid needing real PRs)
5. Verifies the orchestrator fires when all siblings complete
"""

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("VIBE_RELAY_URL", "http://localhost:8000")

pytestmark = pytest.mark.skipif(
    "VIBE_RELAY_SMOKE" not in os.environ,
    reason="Set VIBE_RELAY_SMOKE=1 to run full loop smoke test",
)


def _get(path: str) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> dict:
    resp = requests.post(f"{BASE_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _patch(path: str, body: dict) -> dict:
    resp = requests.patch(f"{BASE_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _wait_for(predicate, description: str, timeout: int = 300, interval: int = 5):
    """Poll until predicate returns truthy, or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        result = predicate()
        if result:
            return result
        print(f"  Waiting for {description}... ({int(time.time() - start)}s)")
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {description} after {timeout}s")


class TestFullLoop:
    def test_autonomous_loop(self):
        """End-to-end: create project -> planner -> coders -> orchestrator."""
        # 1. Create project
        print("\n[1] Creating project...")
        data = _post("/projects", {
            "title": "Smoke Test Project",
            "description": "A simple test project for the full loop smoke test. Create a single Python function that adds two numbers.",
        })
        project_id = data["project"]["id"]
        planner_task_id = data["task"]["id"]
        print(f"  Project: {project_id}")
        print(f"  Planner task: {planner_task_id} (status: {data['task']['status']})")

        # 2. Wait for planner to create subtasks
        print("\n[2] Waiting for planner to create subtasks...")

        def has_subtasks():
            tasks = _get(f"/projects/{project_id}/tasks")
            all_tasks = []
            for status_tasks in tasks.values():
                all_tasks.extend(status_tasks)
            non_planner = [t for t in all_tasks if t["phase"] != "planner"]
            return non_planner if len(non_planner) > 0 else None

        subtasks = _wait_for(has_subtasks, "planner to create subtasks")
        print(f"  Planner created {len(subtasks)} subtasks")

        # 3. Wait for coder tasks to move to in_review
        print("\n[3] Waiting for coder tasks...")

        def coders_in_review():
            tasks = _get(f"/projects/{project_id}/tasks")
            in_review = tasks.get("in_review", [])
            done = tasks.get("done", [])
            coder_done = [t for t in in_review + done if t["phase"] == "coder"]
            return coder_done if len(coder_done) == len(subtasks) else None

        _wait_for(coders_in_review, "all coder tasks to reach in_review/done", timeout=600)
        print("  All coder tasks reached in_review or done")

        # 4. Approve tasks (move in_review -> done)
        print("\n[4] Approving tasks...")
        tasks = _get(f"/projects/{project_id}/tasks")
        for t in tasks.get("in_review", []):
            print(f"  Approving: {t['title']}")
            _patch(f"/tasks/{t['id']}", {"status": "done"})

        # 5. Check for orchestrator
        print("\n[5] Waiting for orchestrator...")

        def has_orchestrator():
            tasks = _get(f"/projects/{project_id}/tasks")
            all_tasks = []
            for status_tasks in tasks.values():
                all_tasks.extend(status_tasks)
            orch = [t for t in all_tasks if t["phase"] == "orchestrator"]
            return orch if len(orch) > 0 else None

        orch_tasks = _wait_for(has_orchestrator, "orchestrator task", timeout=30)
        print(f"  Orchestrator task created: {orch_tasks[0]['id']}")

        print("\n[PASS] Full loop completed successfully!")
```

### Step 3: Run integration tests (not smoke test)

Run: `uv run pytest tests/test_triggers.py tests/test_trigger_helpers.py -v`
Expected: All tests PASS

### Step 4: Run full test suite

Run: `uv run pytest tests/ -v`
Expected: All tests PASS (173 existing + ~20 new)

### Step 5: Lint everything

```bash
ruff check runner/triggers.py api/deps.py api/app.py api/routes.py vibe_relay/cli.py vibe_relay/mcp/tools.py db/schema.py db/migrations.py
ruff format runner/triggers.py api/deps.py api/app.py api/routes.py vibe_relay/cli.py vibe_relay/mcp/tools.py db/schema.py db/migrations.py
```

### Step 6: Commit

```bash
git add tests/test_triggers.py tests/test_trigger_helpers.py tests/test_full_loop.py
git commit -m "Add trigger integration tests and full loop smoke test"
```

### Step 7: Update phase-6.md status

Mark `Phases/phase-6.md` status as `complete` and check off all acceptance criteria.

```bash
git add Phases/phase-6.md
git commit -m "Mark Phase 6 acceptance criteria complete"
```

---

## Verification Checklist

Before declaring Phase 6 complete:

1. `uv run pytest tests/ -v` — all tests pass (existing + new)
2. `ruff check runner/ api/ db/ vibe_relay/` — clean
3. `ruff format --check runner/ api/ db/ vibe_relay/` — clean
4. `cd ui && npm run build` — still builds
5. Manual verification: start server, create project via UI, verify planner task auto-starts (visible in server logs)

## Acceptance Criteria Mapping

| Criteria | Implementation |
|----------|---------------|
| Creating project auto-starts planner | Task 4: `api/routes.py` auto-transitions to `in_progress` |
| Planner creates subtasks visible on board | Existing WS broadcaster + planner agent (no change) |
| Coder subtasks auto-started | Task 4: `agents/planner.md` instructs planner to start them |
| Coder agents launch for in_progress tasks | Task 2: `runner/triggers.py` dispatch rules |
| Reviewer triggers on in_review | Existing: reviewer would be triggered on `in_progress` |
| Resume coder with --resume | Existing: `runner/launcher.py` checks `session_id` |
| Comments in resumed session | Existing: `runner/context.py` includes `<comments>` |
| Orchestrator fires on all done | Task 3: `complete_task` creates orchestrator task |
| Worktree cleanup on done | Task 2: trigger processor handles cleanup |
| max_parallel_agents respected | Task 2: `count_active_runs` guard |
| No double-launches | Task 2: `has_active_run` guard |
| Full loop smoke test | Task 5: `tests/test_full_loop.py` |
| UI updates live | Existing WS broadcaster (no change) |
