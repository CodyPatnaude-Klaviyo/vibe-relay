#!/usr/bin/env python3
"""Monitor a vibe-relay project and auto-approve milestones.

Simulates a human clicking "Approve" on each milestone plan
so the full pipeline can run end-to-end without manual intervention.

Usage:
    python scripts/auto_approve_monitor.py [--db-path PATH] [--interval SECS]
"""

import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("~/.vibe-relay/vibe-relay.db").expanduser()
POLL_INTERVAL = 3  # seconds


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def dump_board(conn: sqlite3.Connection, project_id: str) -> None:
    """Print current board state."""
    steps = conn.execute(
        "SELECT id, name, position FROM workflow_steps WHERE project_id = ? ORDER BY position",
        (project_id,),
    ).fetchall()

    for step in steps:
        tasks = conn.execute(
            """SELECT t.id, t.title, t.type, t.plan_approved, t.cancelled,
                      t.session_id IS NOT NULL as has_session,
                      EXISTS(SELECT 1 FROM agent_runs ar WHERE ar.task_id = t.id AND ar.completed_at IS NULL) as running
               FROM tasks t
               WHERE t.project_id = ? AND t.step_id = ? AND t.cancelled = 0
               ORDER BY t.created_at""",
            (project_id, step["id"]),
        ).fetchall()
        if tasks:
            log(f"  [{step['name']}] ({len(tasks)} tasks)")
            for t in tasks:
                status = []
                if t["type"] == "milestone":
                    status.append("MILESTONE")
                    status.append("approved" if t["plan_approved"] else "NEEDS_APPROVAL")
                if t["running"]:
                    status.append("RUNNING")
                elif t["has_session"]:
                    status.append("completed")
                flags = " ".join(status)
                log(f"    - {t['title']} [{flags}]")


def auto_approve_milestones(conn: sqlite3.Connection, project_id: str) -> int:
    """Find milestones that need approval and have children. Approve them."""
    import json
    import uuid

    milestones = conn.execute(
        """SELECT t.id, t.title, t.project_id
           FROM tasks t
           WHERE t.project_id = ? AND t.type = 'milestone' AND t.plan_approved = 0 AND t.cancelled = 0""",
        (project_id,),
    ).fetchall()

    approved = 0
    for m in milestones:
        # Only approve if milestone has children
        children = conn.execute(
            "SELECT id FROM tasks WHERE parent_task_id = ? AND cancelled = 0",
            (m["id"],),
        ).fetchall()
        if not children:
            continue

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE tasks SET plan_approved = 1, updated_at = ? WHERE id = ?",
            (now, m["id"]),
        )

        # Emit plan_approved event
        event_id = str(uuid.uuid4())
        payload = json.dumps({"task_id": m["id"], "project_id": m["project_id"]})
        conn.execute(
            "INSERT INTO events (id, type, payload, created_at) VALUES (?, 'plan_approved', ?, ?)",
            (event_id, payload, now),
        )

        # Emit task_ready for each unblocked child
        for child in children:
            # Check if child is blocked by dependencies
            blocked = conn.execute(
                """SELECT COUNT(*) as cnt FROM task_dependencies td
                   JOIN tasks t ON td.predecessor_id = t.id
                   JOIN workflow_steps ws ON t.step_id = ws.id
                   WHERE td.successor_id = ?
                   AND ws.position < (SELECT MAX(position) FROM workflow_steps WHERE project_id = ?)""",
                (child["id"], project_id),
            ).fetchone()
            if blocked["cnt"] == 0:
                child_event_id = str(uuid.uuid4())
                child_payload = json.dumps({"task_id": child["id"], "project_id": m["project_id"]})
                conn.execute(
                    "INSERT INTO events (id, type, payload, created_at) VALUES (?, 'task_ready', ?, ?)",
                    (child_event_id, child_payload, now),
                )

        conn.commit()
        log(f"  AUTO-APPROVED: {m['title']} ({len(children)} children)")
        approved += 1

    return approved


def check_completion(conn: sqlite3.Connection, project_id: str) -> bool:
    """Check if all non-cancelled tasks are at the terminal step."""
    terminal = conn.execute(
        "SELECT id, position FROM workflow_steps WHERE project_id = ? ORDER BY position DESC LIMIT 1",
        (project_id,),
    ).fetchone()

    remaining = conn.execute(
        """SELECT COUNT(*) as cnt FROM tasks t
           JOIN workflow_steps ws ON t.step_id = ws.id
           WHERE t.project_id = ? AND t.cancelled = 0 AND ws.position < ?""",
        (project_id, terminal["position"]),
    ).fetchone()

    active_runs = conn.execute(
        """SELECT COUNT(*) as cnt FROM agent_runs ar
           JOIN tasks t ON ar.task_id = t.id
           WHERE t.project_id = ? AND ar.completed_at IS NULL""",
        (project_id,),
    ).fetchone()

    return remaining["cnt"] == 0 and active_runs["cnt"] == 0


def main() -> None:
    global DB_PATH  # noqa: PLW0603
    db_path = sys.argv[1] if len(sys.argv) > 1 else str(DB_PATH)
    DB_PATH = Path(db_path)

    log("Waiting for a project to appear...")

    project_id = None
    while project_id is None:
        try:
            conn = get_conn()
            row = conn.execute("SELECT id, title FROM projects ORDER BY created_at DESC LIMIT 1").fetchone()
            if row:
                project_id = row["id"]
                log(f"Found project: {row['title']} ({project_id})")
            conn.close()
        except Exception:
            pass
        if project_id is None:
            time.sleep(POLL_INTERVAL)

    log("Monitoring board state. Will auto-approve milestones...")
    log("")

    cycle = 0
    while True:
        try:
            conn = get_conn()

            # Auto-approve any milestones that have children
            approved = auto_approve_milestones(conn, project_id)

            # Print board state periodically
            if cycle % 5 == 0 or approved > 0:
                log("--- Board State ---")
                dump_board(conn, project_id)
                log("")

            # Check if done
            if check_completion(conn, project_id) and cycle > 5:
                log("=== ALL TASKS COMPLETE ===")
                dump_board(conn, project_id)
                conn.close()
                break

            conn.close()
        except Exception as e:
            log(f"Error: {e}")

        cycle += 1
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
