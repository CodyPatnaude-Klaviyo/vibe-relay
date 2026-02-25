"""Git repository validation utilities for vibe-relay."""

import subprocess
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    """Check if a path is inside a git working tree."""
    if not path.exists() or not path.is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, OSError):
        return False


def detect_default_branch(path: Path) -> str:
    """Detect the default branch for a git repository.

    Tries in order:
    1. git symbolic-ref refs/remotes/origin/HEAD (remote default)
    2. Check if 'main' or 'master' exists in local branches
    3. Fallback to 'main'
    """
    # Try remote HEAD
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Output is like "refs/remotes/origin/main"
            ref = result.stdout.strip()
            return ref.split("/")[-1]
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Check local branches for main/master
    try:
        result = subprocess.run(
            ["git", "branch", "--list"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branches = [b.strip().lstrip("* ") for b in result.stdout.splitlines()]
            if "main" in branches:
                return "main"
            if "master" in branches:
                return "master"
    except (subprocess.TimeoutExpired, OSError):
        pass

    return "main"
