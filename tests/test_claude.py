"""Tests for runner/claude.py — Claude CLI subprocess wrapper.

Uses mocked subprocess.Popen to avoid real Claude CLI calls.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from runner.claude import ClaudeRunError, _build_mcp_config, run_agent


def _make_stream_lines(*messages: dict) -> list[str]:
    """Build NDJSON lines from message dicts."""
    return [json.dumps(m) + "\n" for m in messages]


def _mock_popen(stdout_lines: list[str], returncode: int = 0, stderr: str = ""):
    """Create a mock Popen that yields stdout_lines and returns the given exit code."""
    mock_proc = MagicMock()
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = stderr
    mock_proc.returncode = returncode
    mock_proc.wait.return_value = returncode
    return mock_proc


class TestBuildCommand:
    @patch("runner.claude.subprocess.Popen")
    def test_first_run_flags(self, mock_popen_cls, tmp_path):
        mock_popen_cls.return_value = _mock_popen(
            _make_stream_lines(
                {"type": "system", "subtype": "init", "session_id": "sess-1"}
            )
        )

        run_agent(
            prompt="test prompt",
            worktree_path=tmp_path,
            model="claude-sonnet-4-5",
            session_id=None,
            task_id="task-1",
            db_path="/tmp/db.sqlite",
        )

        cmd = mock_popen_cls.call_args[0][0]
        assert "claude" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--verbose" in cmd
        assert "--model" in cmd
        assert "claude-sonnet-4-5" in cmd
        assert "--resume" not in cmd
        assert "-p" in cmd

    @patch("runner.claude.subprocess.Popen")
    def test_resume_flag(self, mock_popen_cls, tmp_path):
        mock_popen_cls.return_value = _mock_popen(
            _make_stream_lines(
                {"type": "system", "subtype": "init", "session_id": "sess-1"}
            )
        )

        run_agent(
            prompt="test",
            worktree_path=tmp_path,
            model="claude-sonnet-4-5",
            session_id="existing-session",
            task_id="task-1",
            db_path="/tmp/db.sqlite",
        )

        cmd = mock_popen_cls.call_args[0][0]
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "existing-session"


class TestSessionIdCapture:
    @patch("runner.claude.subprocess.Popen")
    def test_captures_session_id(self, mock_popen_cls, tmp_path):
        mock_popen_cls.return_value = _mock_popen(
            _make_stream_lines(
                {"type": "system", "subtype": "init", "session_id": "captured-sid"},
                {"type": "assistant", "message": "Hello"},
            )
        )

        result = run_agent(
            prompt="test",
            worktree_path=tmp_path,
            model="claude-sonnet-4-5",
            session_id=None,
            task_id="task-1",
            db_path="/tmp/db.sqlite",
        )

        assert result.session_id == "captured-sid"
        assert result.exit_code == 0
        assert result.error is None

    @patch("runner.claude.subprocess.Popen")
    def test_callback_invoked(self, mock_popen_cls, tmp_path):
        mock_popen_cls.return_value = _mock_popen(
            _make_stream_lines(
                {"type": "system", "subtype": "init", "session_id": "cb-sid"},
            )
        )

        captured = []
        run_agent(
            prompt="test",
            worktree_path=tmp_path,
            model="claude-sonnet-4-5",
            session_id=None,
            task_id="task-1",
            db_path="/tmp/db.sqlite",
            on_session_id=lambda sid: captured.append(sid),
        )

        assert captured == ["cb-sid"]


class TestEnvironment:
    @patch("runner.claude.subprocess.Popen")
    def test_claudecode_unset(self, mock_popen_cls, tmp_path):
        mock_popen_cls.return_value = _mock_popen([])

        with patch.dict("os.environ", {"CLAUDECODE": "1", "PATH": "/usr/bin"}):
            run_agent(
                prompt="test",
                worktree_path=tmp_path,
                model="claude-sonnet-4-5",
                session_id=None,
                task_id="task-1",
                db_path="/tmp/db.sqlite",
            )

        env = mock_popen_cls.call_args[1]["env"]
        assert "CLAUDECODE" not in env


class TestMcpConfig:
    @patch("runner.claude.subprocess.Popen")
    def test_mcp_config_file_written(self, mock_popen_cls, tmp_path):
        """Verify --mcp-config is passed and points to a valid file path."""
        mock_popen_cls.return_value = _mock_popen([])

        run_agent(
            prompt="test",
            worktree_path=tmp_path,
            model="claude-sonnet-4-5",
            session_id=None,
            task_id="task-1",
            db_path="/tmp/db.sqlite",
        )

        cmd = mock_popen_cls.call_args[0][0]
        assert "--mcp-config" in cmd
        idx = cmd.index("--mcp-config")
        config_path = cmd[idx + 1]
        # Temp file is cleaned up after run, so just check it was a path string
        assert config_path.endswith(".json")

    def test_build_mcp_config_structure(self):
        config = _build_mcp_config("task-abc", "/tmp/db.sqlite")
        assert "mcpServers" in config
        assert "vibe-relay" in config["mcpServers"]
        server = config["mcpServers"]["vibe-relay"]
        assert server["command"] == "vibe-relay"
        assert "--task-id" in server["args"]
        assert "task-abc" in server["args"]
        assert server["env"]["VIBE_RELAY_DB"] == "/tmp/db.sqlite"


class TestErrorHandling:
    @patch("runner.claude.subprocess.Popen")
    def test_nonzero_exit_code(self, mock_popen_cls, tmp_path):
        mock_popen_cls.return_value = _mock_popen(
            _make_stream_lines(
                {"type": "system", "subtype": "init", "session_id": "s1"},
            ),
            returncode=1,
            stderr="Something failed",
        )

        result = run_agent(
            prompt="test",
            worktree_path=tmp_path,
            model="claude-sonnet-4-5",
            session_id=None,
            task_id="task-1",
            db_path="/tmp/db.sqlite",
        )

        assert result.exit_code == 1
        assert result.error == "Something failed"

    @patch("runner.claude.subprocess.Popen", side_effect=FileNotFoundError("no claude"))
    def test_missing_claude_raises(self, mock_popen_cls, tmp_path):
        with pytest.raises(ClaudeRunError, match="Claude CLI not found"):
            run_agent(
                prompt="test",
                worktree_path=tmp_path,
                model="claude-sonnet-4-5",
                session_id=None,
                task_id="task-1",
                db_path="/tmp/db.sqlite",
            )
