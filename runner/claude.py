"""Claude CLI subprocess wrapper for vibe-relay.

Launches `claude` as a subprocess with stream-json output format,
captures session_id from the init message, and returns the result.
"""

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ClaudeRunError(Exception):
    """Raised when the Claude CLI subprocess fails unexpectedly."""


@dataclass
class AgentRunResult:
    """Result of a Claude agent run."""

    session_id: str
    exit_code: int
    error: str | None = None


def run_agent(
    prompt: str,
    worktree_path: Path,
    model: str,
    session_id: str | None,
    task_id: str,
    db_path: str,
    on_session_id: Callable[[str], None] | None = None,
) -> AgentRunResult:
    """Launch a Claude CLI subprocess and capture the result.

    First run: launches with --output-format stream-json to capture session_id
    from the init message before the run completes.

    Resume: adds --resume {session_id} to continue an existing session.

    Args:
        prompt: The full agent prompt to pass to Claude.
        worktree_path: Working directory for the subprocess.
        model: Claude model identifier (e.g. "claude-sonnet-4-5").
        session_id: If set, resumes this session instead of starting new.
        task_id: Task UUID, passed to MCP server for scoping.
        db_path: Path to the vibe-relay SQLite database.
        on_session_id: Callback invoked with session_id as soon as it's captured.

    Returns:
        AgentRunResult with session_id, exit_code, and optional error.

    Raises:
        ClaudeRunError: If the subprocess cannot be started.
    """
    mcp_config = _build_mcp_config(task_id, db_path)
    tmp_file = None

    try:
        # Write MCP config to temp file
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="vibe-relay-mcp-",
            delete=False,
        )
        json.dump(mcp_config, tmp_file)
        tmp_file.close()

        cmd = _build_command(
            model=model,
            session_id=session_id,
            mcp_config_path=tmp_file.name,
            prompt=prompt,
        )

        # Unset CLAUDECODE to avoid nested session blocking
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        captured_session_id = session_id or ""
        error: str | None = None

        proc = subprocess.Popen(
            cmd,
            cwd=str(worktree_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )

        # Read stdout line-by-line as NDJSON
        assert proc.stdout is not None  # guaranteed by PIPE
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Capture session_id from init message
            if (
                msg.get("type") == "system"
                and msg.get("subtype") == "init"
                and "session_id" in msg
                and not captured_session_id
            ):
                captured_session_id = msg["session_id"]
                if on_session_id:
                    on_session_id(captured_session_id)

        proc.wait()
        exit_code = proc.returncode

        # Capture stderr for error reporting on non-zero exit
        assert proc.stderr is not None
        stderr_output = proc.stderr.read()
        if exit_code != 0 and stderr_output:
            error = stderr_output.strip()

        return AgentRunResult(
            session_id=captured_session_id,
            exit_code=exit_code,
            error=error,
        )

    except FileNotFoundError as e:
        raise ClaudeRunError(
            "Claude CLI not found. Ensure 'claude' is installed and on PATH."
        ) from e
    finally:
        if tmp_file is not None:
            try:
                Path(tmp_file.name).unlink(missing_ok=True)
            except OSError:
                pass


def _build_command(
    model: str,
    session_id: str | None,
    mcp_config_path: str,
    prompt: str,
) -> list[str]:
    """Build the claude CLI command."""
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--mcp-config",
        mcp_config_path,
    ]

    if session_id:
        cmd.extend(["--resume", session_id])

    cmd.extend(["-p", prompt])

    return cmd


def _build_mcp_config(task_id: str, db_path: str) -> dict[str, Any]:
    """Build the MCP config dict for the agent subprocess."""
    return {
        "mcpServers": {
            "vibe-relay": {
                "command": "vibe-relay",
                "args": ["mcp", "--task-id", task_id],
                "env": {"VIBE_RELAY_DB": db_path},
            }
        }
    }
