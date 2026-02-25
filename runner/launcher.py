"""Top-level agent launcher for vibe-relay.

Coordinates worktree creation, prompt building, run recording,
and Claude CLI execution for a single task.
"""

from pathlib import Path
from typing import Any

from db.client import get_connection
from runner.claude import AgentRunResult, ClaudeRunError, run_agent
from runner.context import build_prompt
from runner.recorder import complete_run, fail_run, start_run
from runner.worktree import create_worktree


class LaunchError(Exception):
    """Raised when agent launch fails due to invalid state or missing data."""


def launch_agent(task_id: str, config: dict[str, Any]) -> AgentRunResult:
    """Launch a Claude agent for a task.

    Process:
        1. Load task and comments from DB
        2. Create worktree if needed, update task with path/branch
        3. Load system prompt from workflow_steps table
        4. Build prompt
        5. Record run start
        6. Execute Claude subprocess
        7. Store session_id on task
        8. Record run completion/failure
        9. Return result

    Args:
        task_id: UUID of the task to run an agent for.
        config: Validated vibe-relay config dict.

    Returns:
        AgentRunResult with session_id, exit_code, and optional error.

    Raises:
        LaunchError: If the task is not found, cancelled, or step has no agent.
        WorktreeError: If worktree creation fails.
        ClaudeRunError: If the Claude CLI cannot be started.
    """
    db_path = config["db_path"]
    conn = get_connection(db_path)

    try:
        # 1. Load task with step info
        task = conn.execute(
            """SELECT t.*, ws.name as step_name, ws.system_prompt, ws.model as step_model
               FROM tasks t
               JOIN workflow_steps ws ON t.step_id = ws.id
               WHERE t.id = ?""",
            (task_id,),
        ).fetchone()
        if task is None:
            raise LaunchError(f"Task not found: {task_id}")

        task_dict = dict(task)

        if task_dict["cancelled"]:
            raise LaunchError(f"Task {task_id} is cancelled")

        # Load comments
        comments = conn.execute(
            "SELECT * FROM comments WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        comment_dicts = [dict(c) for c in comments]

        # 2. Create worktree if needed
        if not task_dict.get("worktree_path"):
            repo_path = Path(config["repo_path"])
            worktrees_path = Path(config["worktrees_path"])
            base_branch = config["base_branch"]
            project_id = task_dict["project_id"]

            wt_info = create_worktree(
                repo_path=repo_path,
                base_branch=base_branch,
                worktrees_path=worktrees_path,
                project_id=project_id,
                task_id=task_id,
            )

            conn.execute(
                "UPDATE tasks SET worktree_path = ?, branch = ? WHERE id = ?",
                (str(wt_info.path), wt_info.branch, task_id),
            )
            conn.commit()
            task_dict["worktree_path"] = str(wt_info.path)
            task_dict["branch"] = wt_info.branch

        # 3. Load system prompt from step
        system_prompt = task_dict.get("system_prompt")
        if not system_prompt:
            raise LaunchError(
                f"Step '{task_dict.get('step_name', '?')}' has no system_prompt (no agent configured)"
            )

        # Determine model: step model > config default_model
        model = task_dict.get("step_model") or config.get(
            "default_model", "claude-sonnet-4-5"
        )

        # Add step_name to task_dict for the prompt builder
        task_dict["step_name"] = task_dict.get("step_name", "")

        # 4. Build prompt
        full_prompt = build_prompt(task_dict, comment_dicts, system_prompt)

        # 5. Record run start
        step_id = task_dict["step_id"]
        run_id = start_run(conn, task_id, step_id)

        # 6-7. Execute Claude subprocess
        existing_session_id = task_dict.get("session_id")

        def on_session_id(sid: str) -> None:
            """Persist session_id to task immediately when captured."""
            conn.execute(
                "UPDATE tasks SET session_id = ? WHERE id = ?",
                (sid, task_id),
            )
            conn.commit()

        try:
            result = run_agent(
                prompt=full_prompt,
                worktree_path=Path(task_dict["worktree_path"]),
                model=model,
                session_id=existing_session_id,
                task_id=task_id,
                db_path=db_path,
                on_session_id=on_session_id,
            )
        except (ClaudeRunError, Exception) as e:
            # 8. Record failure
            fail_run(conn, run_id, str(e))
            raise

        # 8. Record completion
        complete_run(conn, run_id, result.exit_code)

        return result

    finally:
        conn.close()
