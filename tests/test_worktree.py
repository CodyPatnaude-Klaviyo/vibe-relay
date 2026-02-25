"""Tests for runner/worktree.py — git worktree operations."""

import subprocess

import pytest

from runner.worktree import (
    WorktreeError,
    WorktreeInfo,
    create_worktree,
    prune_worktrees,
    remove_worktree,
    worktree_exists,
)


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
    # Initial commit so branches work
    readme = repo / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    return repo


class TestCreateWorktree:
    def test_creates_directory_and_branch(self, git_repo, tmp_path):
        wt_root = tmp_path / "worktrees"
        result = create_worktree(
            repo_path=git_repo,
            base_branch="main",
            worktrees_path=wt_root,
            project_id="proj-123",
            task_id="task-abcdef12-rest",
        )
        assert isinstance(result, WorktreeInfo)
        assert result.path == wt_root / "proj-123" / "task-abcdef12-rest"
        assert result.path.is_dir()
        assert result.branch.startswith("task-task-abc")

    def test_branch_name_format(self, git_repo, tmp_path):
        wt_root = tmp_path / "worktrees"
        result = create_worktree(
            repo_path=git_repo,
            base_branch="main",
            worktrees_path=wt_root,
            project_id="p1",
            task_id="abcdef12-3456-7890-abcd-ef1234567890",
        )
        # Branch should start with task-{first 8 chars of task_id}-
        assert result.branch.startswith("task-abcdef12-")

    def test_idempotent_second_call(self, git_repo, tmp_path):
        wt_root = tmp_path / "worktrees"
        kwargs = dict(
            repo_path=git_repo,
            base_branch="main",
            worktrees_path=wt_root,
            project_id="p1",
            task_id="task-1234",
        )
        first = create_worktree(**kwargs)
        second = create_worktree(**kwargs)
        assert first.path == second.path
        assert first.branch == second.branch

    def test_invalid_base_branch_raises(self, git_repo, tmp_path):
        wt_root = tmp_path / "worktrees"
        with pytest.raises(WorktreeError, match="Failed to create worktree"):
            create_worktree(
                repo_path=git_repo,
                base_branch="nonexistent-branch",
                worktrees_path=wt_root,
                project_id="p1",
                task_id="task-bad",
            )


class TestRemoveWorktree:
    def test_removes_worktree_and_branch(self, git_repo, tmp_path):
        wt_root = tmp_path / "worktrees"
        result = create_worktree(
            repo_path=git_repo,
            base_branch="main",
            worktrees_path=wt_root,
            project_id="p1",
            task_id="task-rm",
        )
        assert result.path.is_dir()

        remove_worktree(result.path, git_repo)
        assert not result.path.exists()

        # Branch should be deleted
        branches = subprocess.run(
            ["git", "branch", "--list", result.branch],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
        )
        assert result.branch not in branches.stdout


class TestWorktreeExists:
    def test_exists_true(self, git_repo, tmp_path):
        wt_root = tmp_path / "worktrees"
        result = create_worktree(
            repo_path=git_repo,
            base_branch="main",
            worktrees_path=wt_root,
            project_id="p1",
            task_id="task-exists",
        )
        assert worktree_exists(result.path) is True

    def test_exists_false_no_dir(self, tmp_path):
        assert worktree_exists(tmp_path / "nonexistent") is False

    def test_exists_false_plain_dir(self, tmp_path):
        """A plain directory without .git file is not a worktree."""
        plain = tmp_path / "plain"
        plain.mkdir()
        assert worktree_exists(plain) is False


class TestPruneWorktrees:
    def test_prune_succeeds(self, git_repo):
        # Should not raise on a clean repo
        prune_worktrees(git_repo)
