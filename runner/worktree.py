"""Git worktree operations for vibe-relay agent runner.

Creates isolated worktrees so each agent operates on its own branch
without interfering with the main repo or other agents.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""


@dataclass(frozen=True)
class WorktreeInfo:
    """Information about a created worktree."""

    path: Path
    branch: str


def create_worktree(
    repo_path: Path,
    base_branch: str,
    worktrees_path: Path,
    project_id: str,
    task_id: str,
) -> WorktreeInfo:
    """Create a git worktree for a task.

    Branch name: task-{task_id[:8]}-{unix_timestamp}
    Path: {worktrees_path}/{project_id}/{task_id}/

    Idempotent: if the worktree directory already exists with a .git file,
    returns the existing worktree info without creating a new one.

    Args:
        repo_path: Path to the main git repository.
        base_branch: Branch to base the worktree on (e.g. "main").
        worktrees_path: Root directory for all worktrees.
        project_id: Project UUID.
        task_id: Task UUID.

    Returns:
        WorktreeInfo with the worktree path and branch name.

    Raises:
        WorktreeError: If the git command fails.
    """
    wt_path = worktrees_path / project_id / task_id

    # Idempotent: if worktree already exists, return existing info
    if worktree_exists(wt_path):
        branch = _read_branch(wt_path, repo_path)
        return WorktreeInfo(path=wt_path, branch=branch)

    branch = f"task-{task_id[:8]}-{int(time.time())}"
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(wt_path), base_branch],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise WorktreeError(
            f"Failed to create worktree at {wt_path}: {e.stderr.strip()}"
        ) from e

    return WorktreeInfo(path=wt_path, branch=branch)


def remove_worktree(worktree_path: Path, repo_path: Path) -> None:
    """Remove a worktree and delete its branch.

    Args:
        worktree_path: Path to the worktree directory.
        repo_path: Path to the main git repository.

    Raises:
        WorktreeError: If the git command fails.
    """
    # Read the branch before removing
    branch = _read_branch(worktree_path, repo_path)

    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise WorktreeError(
            f"Failed to remove worktree at {worktree_path}: {e.stderr.strip()}"
        ) from e

    # Delete the branch
    if branch:
        try:
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            pass  # Branch may already be deleted


def prune_worktrees(repo_path: Path) -> None:
    """Prune stale worktree registrations.

    Args:
        repo_path: Path to the main git repository.

    Raises:
        WorktreeError: If the git command fails.
    """
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise WorktreeError(f"Failed to prune worktrees: {e.stderr.strip()}") from e


def worktree_exists(worktree_path: Path) -> bool:
    """Check if a worktree exists at the given path.

    A valid worktree has a directory with a .git file (not directory).
    """
    git_file = worktree_path / ".git"
    return worktree_path.is_dir() and git_file.exists() and git_file.is_file()


def _read_branch(worktree_path: Path, repo_path: Path) -> str:
    """Read the current branch of a worktree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""
