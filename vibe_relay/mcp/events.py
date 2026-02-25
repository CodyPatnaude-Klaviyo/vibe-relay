"""Event emission for the MCP server.

Every write operation inserts an event row so the API server
can broadcast it via websocket and the trigger processor can dispatch agents.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def emit_event(
    conn: sqlite3.Connection,
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """Insert an event row and return its ID.

    The caller manages conn.commit() so the data write and event
    emission are in the same transaction.

    Args:
        conn: Active SQLite connection.
        event_type: One of 'task_created', 'task_moved', 'task_cancelled',
                    'task_uncancelled', 'comment_added', 'subtasks_created',
                    'project_created'.
        payload: JSON-serializable dict with event details.

    Returns:
        The generated event ID (UUID4).
    """
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO events (id, type, payload, created_at) VALUES (?, ?, ?, ?)",
        (event_id, event_type, json.dumps(payload), now),
    )
    return event_id
