"""Tests for runner/context.py — prompt builder."""

from runner.context import build_prompt


class TestBuildPrompt:
    def test_all_sections_present(self):
        task = {
            "title": "Fix the bug",
            "description": "There is a bug in auth",
            "step_name": "Implement",
            "branch": "task-abc-123",
            "worktree_path": "/tmp/wt/abc",
        }
        comments = [
            {
                "author_role": "Plan",
                "created_at": "2025-01-01T00:00:00Z",
                "content": "Please fix this",
            }
        ]
        system_prompt = "You are a coder agent."

        result = build_prompt(task, comments, system_prompt)

        assert "<system_prompt>" in result
        assert "You are a coder agent." in result
        assert "</system_prompt>" in result
        assert "<issue>" in result
        assert "Title: Fix the bug" in result
        assert "</issue>" in result
        assert "<comments>" in result
        assert "[Plan] 2025-01-01T00:00:00Z: Please fix this" in result
        assert "</comments>" in result

    def test_no_comments_omits_block(self):
        task = {
            "title": "Task",
            "description": "Desc",
            "step_name": "Implement",
            "branch": "b",
            "worktree_path": "/tmp/wt",
        }
        result = build_prompt(task, [], "prompt")

        assert "<system_prompt>" in result
        assert "<issue>" in result
        assert "<comments>" not in result

    def test_issue_fields_populated(self):
        task = {
            "title": "My Title",
            "description": "My Desc",
            "step_name": "Review",
            "branch": "task-xyz-999",
            "worktree_path": "/home/user/wt",
        }
        result = build_prompt(task, [], "sys")

        assert "Title: My Title" in result
        assert "Description: My Desc" in result
        assert "Step: Review" in result
        assert "Branch: task-xyz-999" in result
        assert "Worktree: /home/user/wt" in result

    def test_multiple_comments(self):
        task = {
            "title": "T",
            "description": "D",
            "step_name": "Implement",
            "branch": "b",
            "worktree_path": "/wt",
        }
        comments = [
            {
                "author_role": "Plan",
                "created_at": "2025-01-01T00:00:00Z",
                "content": "First comment",
            },
            {
                "author_role": "Review",
                "created_at": "2025-01-02T00:00:00Z",
                "content": "Second comment",
            },
        ]
        result = build_prompt(task, comments, "sys")

        assert "[Plan] 2025-01-01T00:00:00Z: First comment" in result
        assert "[Review] 2025-01-02T00:00:00Z: Second comment" in result

    def test_missing_task_fields_default_empty(self):
        """Missing optional task fields default to empty strings."""
        task = {"title": "T"}
        result = build_prompt(task, [], "sys")

        assert "Description: " in result
        assert "Step: " in result
        assert "Branch: " in result
        assert "Worktree: " in result
