"""Prompt builder for vibe-relay agent runner.

Builds the structured prompt injected into each agent run,
following the format defined in ARCHITECTURE.md.
"""


def build_prompt(
    task: dict[str, str | None],
    comments: list[dict[str, str]],
    system_prompt: str,
) -> str:
    """Build the full agent prompt from task data, comments, and system prompt.

    Output format:
        <system_prompt>...</system_prompt>
        <issue>Title: ... Description: ... Step: ... Branch: ... Worktree: ...</issue>
        <comments>[role] timestamp: content ...</comments>

    The <comments> block is omitted if there are no comments.

    Args:
        task: Task dict with keys: title, description, step_name, branch, worktree_path.
        comments: List of comment dicts with keys: author_role, created_at, content.
        system_prompt: Contents of the role-specific system prompt.

    Returns:
        The formatted prompt string.
    """
    parts: list[str] = []

    parts.append(f"<system_prompt>\n{system_prompt}\n</system_prompt>")

    issue_lines = [
        f"Task ID: {task.get('id', '')}",
        f"Project ID: {task.get('project_id', '')}",
        f"Parent Task ID: {task.get('parent_task_id', '')}",
        f"Title: {task.get('title', '')}",
        f"Description: {task.get('description', '')}",
        f"Step: {task.get('step_name', '')}",
        f"Branch: {task.get('branch', '')}",
        f"Worktree: {task.get('worktree_path', '')}",
    ]
    parts.append(f"<issue>\n{chr(10).join(issue_lines)}\n</issue>")

    if comments:
        comment_lines = [
            f"[{c['author_role']}] {c['created_at']}: {c['content']}" for c in comments
        ]
        parts.append(f"<comments>\n{chr(10).join(comment_lines)}\n</comments>")

    return "\n\n".join(parts)
