"""Claude CLI subprocess wrapper for vibe-relay.

Launches `claude` as a subprocess with stream-json output format,
captures session_id from the init message, and returns the result.
"""

import json
import logging
import os
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global registry of active Claude subprocesses for cleanup on shutdown
_active_processes: set[subprocess.Popen[str]] = set()
_process_lock = threading.Lock()


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
    proc: subprocess.Popen[str] | None = None

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

        # Strip all CLAUDE* env vars to avoid nested session detection
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}

        captured_session_id = session_id or ""
        error: str | None = None

        logger.info(
            "Launching Claude for task %s: cmd=%s cwd=%s",
            task_id,
            " ".join(cmd[:6]) + " ...",
            str(worktree_path),
        )

        proc = subprocess.Popen(
            cmd,
            cwd=str(worktree_path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            start_new_session=True,
        )

        logger.info("Claude subprocess started: PID %d", proc.pid)

        with _process_lock:
            _active_processes.add(proc)

        # Read stdout line-by-line as NDJSON
        assert proc.stdout is not None  # guaranteed by PIPE
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Non-JSON stdout: %s", line[:200])
                continue

            msg_type = msg.get("type", "")
            msg_subtype = msg.get("subtype", "")
            logger.debug("Claude msg: type=%s subtype=%s", msg_type, msg_subtype)

            # Capture session_id from init message
            if (
                msg_type == "system"
                and msg_subtype == "init"
                and "session_id" in msg
                and not captured_session_id
            ):
                captured_session_id = msg["session_id"]
                logger.info("Captured session_id: %s", captured_session_id)
                if on_session_id:
                    on_session_id(captured_session_id)

        proc.wait()
        exit_code = proc.returncode
        logger.info("Claude subprocess PID %d exited: code=%d", proc.pid, exit_code)

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
        if proc is not None:
            with _process_lock:
                _active_processes.discard(proc)
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
        "--strict-mcp-config",
        "--setting-sources",
        "project",
    ]

    if session_id:
        cmd.extend(["--resume", session_id])

    cmd.extend(["-p", prompt])

    return cmd


def _build_mcp_config(task_id: str, db_path: str) -> dict[str, Any]:
    """Build the MCP config dict for the agent subprocess."""
    import shutil
    import sys

    # Use the vibe-relay from the same venv as the running server,
    # since the CLI may not be on the system PATH.
    venv_bin = Path(sys.executable).parent / "vibe-relay"
    command = str(venv_bin) if venv_bin.exists() else (shutil.which("vibe-relay") or "vibe-relay")

    return {
        "mcpServers": {
            "vibe-relay": {
                "command": command,
                "args": ["mcp", "--task-id", task_id],
                "env": {"VIBE_RELAY_DB": db_path},
            }
        }
    }



def terminate_all() -> int:
    """Terminate all active Claude subprocesses.

    Called during server shutdown to clean up spawned agents.

    Returns:
        Number of processes terminated.
    """
    with _process_lock:
        procs = list(_active_processes)

    count = 0
    for proc in procs:
        try:
            proc.terminate()
            count += 1
            logger.info("Terminated Claude subprocess PID %d", proc.pid)
        except OSError:
            pass

    # Give them a moment, then force-kill stragglers
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                logger.warning("Force-killed Claude subprocess PID %d", proc.pid)
            except OSError:
                pass

    with _process_lock:
        _active_processes.clear()

    return count
