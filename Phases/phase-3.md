---
title: "Phase 3: Agent Runner"
status: not started
---

# Phase 3: Agent Runner

Build the system that executes Claude Code agents. By the end of this phase, vibe-relay can launch a Claude Code subprocess for a task, capture the session ID, manage the git worktree, and resume a session when a task is picked back up. No automatic triggers yet — agents are launched manually via CLI command. 

This phase delivers standalone value: you can run a single agent against a task and watch it work, which lets you validate prompts and the context format before wiring in the full automation loop.

---

## Deliverables

### Worktree manager (`runner/worktree.py`)

Handles all git worktree operations.

```python
create_worktree(repo_path, base_branch, task_id) -> WorktreeInfo
  # Creates a new branch: task-{task_id}-{unix_timestamp}
  # Creates worktree at: {worktrees_path}/{project_id}/{task_id}/
  # Returns: WorktreeInfo(path, branch)

remove_worktree(worktree_path, repo_path) -> None
  # Runs git worktree remove --force
  # Deletes the branch from remote
  # Cleans up the directory

prune_worktrees(repo_path) -> None
  # Runs git worktree prune to clean up orphaned registrations

worktree_exists(worktree_path) -> bool
```

Worktree path convention:
```
{config.worktrees_path}/{project_id}/{task_id}/
```

Branch name convention:
```
task-{task_id[:8]}-{unix_timestamp}
```

### Context builder (`runner/context.py`)

Builds the structured prompt injected into each agent run.

```python
build_prompt(task: Task, comments: list[Comment], system_prompt: str) -> str
```

Output format:
```
<system_prompt>
{system_prompt file contents}
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

If there are no comments, the `<comments>` block is omitted.

### Claude runner (`runner/claude.py`)

Wraps the `claude` CLI subprocess.

```python
run_agent(
  prompt: str,
  worktree_path: Path,
  model: str,
  session_id: str | None,        # if set, passes --resume {session_id}
  task_id: str,
  mcp_config: dict,
) -> AgentRunResult

@dataclass
class AgentRunResult:
  session_id: str
  exit_code: int
  error: str | None
```

CLI invocation (first run):
```bash
claude \
  --dangerously-skip-permissions \
  --output-format json \
  --model {model} \
  -p "{prompt}"
```

CLI invocation (resume):
```bash
claude \
  --dangerously-skip-permissions \
  --output-format json \
  --model {model} \
  --resume {session_id} \
  -p "{prompt}"
```

The MCP config is written to a temp file and passed via `--mcp-config {path}` so the agent has board access during its run.

Session ID extraction: parse the JSON output stream and capture `session_id` from the first result object. Store it on the task immediately after the first response arrives (not after completion) so it's available if the process is interrupted.

### Agent run recorder (`runner/recorder.py`)

Writes to the `agent_runs` table.

```python
start_run(task_id, phase) -> str          # returns run_id
complete_run(run_id, exit_code) -> None
fail_run(run_id, error) -> None
```

### Agent launcher (`runner/launcher.py`)

The top-level coordinator for a single agent execution. Composes worktree manager, context builder, Claude runner, and recorder.

```python
launch_agent(task_id: str, config: Config) -> AgentRunResult
```

Process:
1. Load task and comments from DB
2. If task has no worktree: create one, update task with `worktree_path` and `branch`
3. Load system prompt from config
4. Build prompt via context builder
5. Record run start
6. Execute claude subprocess
7. Store `session_id` on task (update DB)
8. Record run completion
9. Return result

Idempotent worktree creation: if `task.worktree_path` is already set and the directory exists, skip creation.

### CLI command

```bash
vibe-relay run-agent --task-id <task_id>
```

Loads config, launches the agent for the given task, streams output to stdout. Exits with the agent's exit code.

Useful for manual testing and debugging individual agent runs without the full automation loop.

---

## Acceptance criteria

- [ ] `create_worktree` creates a new git branch and worktree at the correct path
- [ ] `create_worktree` is idempotent — called twice for same task, second call is a no-op
- [ ] `remove_worktree` removes the worktree directory and git registration
- [ ] `build_prompt` produces correctly structured output with all three sections
- [ ] `build_prompt` omits `<comments>` block when there are no comments
- [ ] `run_agent` launches `claude` subprocess and captures exit code
- [ ] `run_agent` captures `session_id` from JSON output and returns it
- [ ] `run_agent` passes `--resume {session_id}` when session_id is provided
- [ ] `run_agent` writes MCP config to temp file and passes it to claude
- [ ] `launch_agent` creates a worktree on first run and stores path/branch on task
- [ ] `launch_agent` reuses existing worktree on subsequent runs
- [ ] `launch_agent` stores `session_id` on the task record after first response
- [ ] `agent_runs` table is updated with start time, completion time, and exit code
- [ ] `vibe-relay run-agent --task-id <id>` executes end-to-end against a real task
- [ ] Manual test: create a task via MCP, run `vibe-relay run-agent`, verify the agent can call `get_task` and `add_comment` via MCP during its run

---

## Out of scope

- No automatic triggering on status transitions (that's Phase 6)
- No HTTP server
- No websocket
- No UI
- No concurrency management (single agent at a time in this phase)