"""Tests for runner/launcher.py — top-level agent coordinator.

Mocks runner.claude.run_agent to avoid real Claude calls.
Uses real DB and real git repo for worktree and recording tests.
"""

import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from db.migrations import init_db
from runner.claude import AgentRunResult
from runner.launcher import LaunchError, launch_agent


@pytest.fixture()
def git_repo(tmp_path):
    """Create a real git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    # Create agents dir with a prompt file
    agents_dir = repo / "agents"
    agents_dir.mkdir()
    (agents_dir / "coder.md").write_text("You are a coder agent.")
    (agents_dir / "planner.md").write_text("You are a planner agent.")
    (agents_dir / "reviewer.md").write_text("You are a reviewer agent.")
    (agents_dir / "orchestrator.md").write_text("You are an orchestrator agent.")

    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    return repo


@pytest.fixture()
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn, str(db_path)
    conn.close()


@pytest.fixture()
def config(git_repo, tmp_path):
    return {
        "repo_path": str(git_repo),
        "base_branch": "main",
        "worktrees_path": str(tmp_path / "worktrees"),
        "db_path": str(tmp_path / "test.db"),
        "agents": {
            "coder": {
                "model": "claude-sonnet-4-5",
                "system_prompt_file": "agents/coder.md",
            },
            "planner": {
                "model": "claude-opus-4-5",
                "system_prompt_file": "agents/planner.md",
            },
            "reviewer": {
                "model": "claude-sonnet-4-5",
                "system_prompt_file": "agents/reviewer.md",
            },
            "orchestrator": {
                "model": "claude-opus-4-5",
                "system_prompt_file": "agents/orchestrator.md",
            },
        },
    }


def _seed(conn: sqlite3.Connection, status: str = "in_progress") -> tuple[str, str]:
    """Insert project + task, return (project_id, task_id)."""
    pid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO projects (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, "Test", "active", now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, description, phase, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tid, pid, "Code task", "Implement feature X", "coder", status, now, now),
    )
    conn.commit()
    return pid, tid


def _mock_run_result(session_id: str = "mock-session") -> AgentRunResult:
    return AgentRunResult(session_id=session_id, exit_code=0)


class TestWorktreeCreation:
    @patch("runner.launcher.run_agent")
    def test_creates_worktree_on_first_run(self, mock_run, db_conn, config):
        conn, db_path = db_conn
        config["db_path"] = db_path
        _, tid = _seed(conn)

        mock_run.return_value = _mock_run_result()

        result = launch_agent(tid, config)

        # Task should have worktree_path and branch set
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        assert task["worktree_path"] is not None
        assert task["branch"] is not None
        assert Path(task["worktree_path"]).is_dir()
        assert result.exit_code == 0

    @patch("runner.launcher.run_agent")
    def test_reuses_worktree_on_second_run(self, mock_run, db_conn, config):
        conn, db_path = db_conn
        config["db_path"] = db_path
        _, tid = _seed(conn)

        mock_run.return_value = _mock_run_result()

        launch_agent(tid, config)
        task1 = dict(
            conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        )
        wt_path_1 = task1["worktree_path"]
        branch_1 = task1["branch"]

        launch_agent(tid, config)
        task2 = dict(
            conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        )

        assert task2["worktree_path"] == wt_path_1
        assert task2["branch"] == branch_1


class TestSessionIdPersistence:
    @patch("runner.launcher.run_agent")
    def test_session_id_persisted_via_callback(self, mock_run, db_conn, config):
        conn, db_path = db_conn
        config["db_path"] = db_path
        _, tid = _seed(conn)

        def side_effect(**kwargs):
            # Simulate the callback being invoked
            cb = kwargs.get("on_session_id")
            if cb:
                cb("persisted-sid")
            return AgentRunResult(session_id="persisted-sid", exit_code=0)

        mock_run.side_effect = side_effect

        launch_agent(tid, config)

        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        assert task["session_id"] == "persisted-sid"


class TestRunRecording:
    @patch("runner.launcher.run_agent")
    def test_run_recorded(self, mock_run, db_conn, config):
        conn, db_path = db_conn
        config["db_path"] = db_path
        _, tid = _seed(conn)

        mock_run.return_value = _mock_run_result()

        launch_agent(tid, config)

        runs = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id = ?", (tid,)
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["phase"] == "coder"
        assert runs[0]["exit_code"] == 0
        assert runs[0]["completed_at"] is not None

    @patch("runner.launcher.run_agent", side_effect=Exception("boom"))
    def test_failed_run_recorded(self, mock_run, db_conn, config):
        conn, db_path = db_conn
        config["db_path"] = db_path
        _, tid = _seed(conn)

        with pytest.raises(Exception, match="boom"):
            launch_agent(tid, config)

        runs = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id = ?", (tid,)
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["exit_code"] == -1
        assert runs[0]["error"] == "boom"


class TestValidation:
    @patch("runner.launcher.run_agent")
    def test_task_not_found_raises(self, mock_run, db_conn, config):
        _, db_path = db_conn
        config["db_path"] = db_path

        with pytest.raises(LaunchError, match="Task not found"):
            launch_agent("nonexistent-id", config)

    @patch("runner.launcher.run_agent")
    def test_wrong_status_raises(self, mock_run, db_conn, config):
        conn, db_path = db_conn
        config["db_path"] = db_path
        _, tid = _seed(conn, status="backlog")

        with pytest.raises(LaunchError, match="backlog.*expected 'in_progress'"):
            launch_agent(tid, config)
