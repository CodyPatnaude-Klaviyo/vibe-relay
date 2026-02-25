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
    def test_returns_task_moved_events(self, conn):
        _emit(
            conn,
            "task_moved",
            {"task_id": "t1", "old_step_id": "s1", "new_step_id": "s2"},
        )
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1
        assert events[0]["type"] == "task_moved"

    def test_returns_task_cancelled_events(self, conn):
        _emit(
            conn,
            "task_cancelled",
            {"task_id": "t1"},
        )
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1
        assert events[0]["type"] == "task_cancelled"

    def test_returns_task_created_events(self, conn):
        _emit(conn, "task_created", {"task_id": "t1"})
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1
        assert events[0]["type"] == "task_created"

    def test_ignores_other_event_types(self, conn):
        _emit(conn, "comment_added", {"comment_id": "c1"})
        _emit(conn, "project_created", {"project_id": "p1"})
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 0

    def test_ignores_already_trigger_consumed(self, conn):
        eid = _emit(
            conn,
            "task_moved",
            {"task_id": "t1", "old_step_id": "s1", "new_step_id": "s2"},
        )
        mark_trigger_consumed(conn, eid)
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 0

    def test_ws_consumed_does_not_affect_trigger(self, conn):
        eid = _emit(
            conn,
            "task_moved",
            {"task_id": "t1", "old_step_id": "s1", "new_step_id": "s2"},
        )
        conn.execute("UPDATE events SET consumed = 1 WHERE id = ?", (eid,))
        conn.commit()
        events = get_unconsumed_trigger_events(conn)
        assert len(events) == 1


class TestMarkTriggerConsumed:
    def test_marks_event(self, conn):
        eid = _emit(
            conn,
            "task_moved",
            {"task_id": "t1", "old_step_id": "s1", "new_step_id": "s2"},
        )
        mark_trigger_consumed(conn, eid)
        row = conn.execute(
            "SELECT trigger_consumed FROM events WHERE id = ?", (eid,)
        ).fetchone()
        assert row["trigger_consumed"] == 1

    def test_does_not_affect_ws_consumed(self, conn):
        eid = _emit(
            conn,
            "task_moved",
            {"task_id": "t1", "old_step_id": "s1", "new_step_id": "s2"},
        )
        mark_trigger_consumed(conn, eid)
        row = conn.execute(
            "SELECT consumed FROM events WHERE id = ?", (eid,)
        ).fetchone()
        assert row["consumed"] == 0
