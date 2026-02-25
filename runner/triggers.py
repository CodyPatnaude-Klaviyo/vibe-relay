"""Trigger processor for vibe-relay.

Polls the events table for task state changes and dispatches agent runs.
Runs as an asyncio background task inside the FastAPI lifespan.
"""

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any

from api.deps import get_unconsumed_trigger_events, mark_trigger_consumed
from db.client import get_connection

logger = logging.getLogger(__name__)


def has_active_run(conn: sqlite3.Connection, task_id: str) -> bool:
    """Check if a task has an active (incomplete) agent run."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM agent_runs WHERE task_id = ? AND completed_at IS NULL",
        (task_id,),
    ).fetchone()
    return row["cnt"] > 0


def count_active_runs(conn: sqlite3.Connection) -> int:
    """Count total active (incomplete) agent runs."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM agent_runs WHERE completed_at IS NULL"
    ).fetchone()
    return row["cnt"]


def _step_has_agent(conn: sqlite3.Connection, step_id: str) -> bool:
    """Check if a workflow step has a system_prompt (agent configured)."""
    row = conn.execute(
        "SELECT system_prompt IS NOT NULL as has_agent FROM workflow_steps WHERE id = ?",
        (step_id,),
    ).fetchone()
    return bool(row and row["has_agent"])


def _is_terminal_step(conn: sqlite3.Connection, step_id: str) -> bool:
    """Check if a step is the last step with no system_prompt (terminal)."""
    step = conn.execute(
        "SELECT project_id, position, system_prompt FROM workflow_steps WHERE id = ?",
        (step_id,),
    ).fetchone()
    if step is None:
        return False

    if step["system_prompt"] is not None:
        return False

    # Check if it's the last step
    max_pos = conn.execute(
        "SELECT MAX(position) as max_pos FROM workflow_steps WHERE project_id = ?",
        (step["project_id"],),
    ).fetchone()

    return step["position"] == max_pos["max_pos"]


def should_dispatch(
    event: dict[str, Any], conn: sqlite3.Connection | None = None
) -> bool:
    """Determine if an event should trigger an agent dispatch.

    Returns True for:
    - task_moved events where the new step has a system_prompt
    - task_created events where the task's step has a system_prompt
    """
    if conn is None:
        return False
    if event["type"] == "task_moved":
        new_step_id = event["payload"].get("new_step_id")
        if new_step_id:
            return _step_has_agent(conn, new_step_id)
    if event["type"] == "task_created":
        task_id = event["payload"].get("task_id")
        if task_id:
            row = conn.execute(
                "SELECT step_id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row:
                return _step_has_agent(conn, row["step_id"])
    return False


def should_cleanup(
    event: dict[str, Any], conn: sqlite3.Connection | None = None
) -> bool:
    """Determine if an event should trigger worktree cleanup.

    Returns True for:
    - task_moved events where the new step is terminal (last position, no agent)
    - task_cancelled events
    """
    if event["type"] == "task_cancelled":
        return True
    if event["type"] == "task_moved" and conn is not None:
        new_step_id = event["payload"].get("new_step_id")
        if new_step_id:
            return _is_terminal_step(conn, new_step_id)
    return False


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
        await asyncio.to_thread(remove_worktree, Path(worktree_path), Path(repo_path))
        logger.info("Cleaned up worktree for task %s: %s", task_id, worktree_path)
    except WorktreeError as e:
        logger.warning("Failed to clean up worktree for task %s: %s", task_id, e)


async def process_triggers(db_path: str, config: dict[str, Any]) -> None:
    """Background task that polls events and dispatches agent runs.

    Dispatch rules:
    - task_moved to step with system_prompt: launch agent
    - task_moved to terminal step: clean up worktree
    - task_cancelled: clean up worktree

    Concurrency guards:
    - Skip if task already has an active run (no double-launch)
    - Leave event unconsumed if at max_parallel_agents capacity (retry next cycle)
    """
    max_agents = config.get("max_parallel_agents", 3)

    while True:
        try:
            conn = get_connection(db_path)
            try:
                events = get_unconsumed_trigger_events(conn)
                for event in events:
                    task_id = event["payload"].get("task_id")

                    if event["type"] in ("task_moved", "task_created"):
                        if not task_id:
                            mark_trigger_consumed(conn, event["id"])
                            continue

                        if should_dispatch(event, conn):
                            # Check concurrency guards
                            if has_active_run(conn, task_id):
                                mark_trigger_consumed(conn, event["id"])
                                continue

                            if count_active_runs(conn) >= max_agents:
                                continue  # At capacity, retry next cycle

                            mark_trigger_consumed(conn, event["id"])
                            asyncio.create_task(_launch_in_thread(task_id, config))

                        elif should_cleanup(event, conn):
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

                    elif event["type"] == "task_cancelled":
                        if task_id:
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

            finally:
                conn.close()
        except Exception:
            logger.exception("Error in trigger processor")

        await asyncio.sleep(1)
