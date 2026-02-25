# Agent Roles

vibe-relay uses four specialized agent roles. Each role has a system prompt that defines its behavior. The default prompts live in `agents/` and are copied into new projects by `vibe-relay init`.

## Roles

| Role | Model | Trigger | File |
|------|-------|---------|------|
| **Planner** | claude-opus-4-5 | New project created | `agents/planner.md` |
| **Coder** | claude-sonnet-4-5 | Task moves to `in_progress` | `agents/coder.md` |
| **Reviewer** | claude-sonnet-4-5 | Task moves to `in_review` | `agents/reviewer.md` |
| **Orchestrator** | claude-opus-4-5 | All sibling tasks reach `done` | `agents/orchestrator.md` |

## Customizing prompts

Each project gets its own copy of the agent prompts in its `agents/` directory. You can modify these per-project to tailor agent behavior. The config file (`vibe-relay.config.json`) maps each role to its prompt file and model.

## Communication

Agents communicate through **comments on tasks**. The comment thread is included in every agent's context, providing a persistent memory handoff between roles. When a coder resumes after review, the reviewer's feedback appears in the `<comments>` block.

## Context format

Every agent receives its task context in this format:

```
<system_prompt>
[role-specific system prompt from agents/{role}.md]
</system_prompt>

<issue>
Title: {task.title}
Description: {task.description}
Phase: {task.phase}
Branch: {task.branch}
Worktree: {task.worktree_path}
</issue>

<comments>
[{author_role}] {created_at}: {content}
...
</comments>
```
