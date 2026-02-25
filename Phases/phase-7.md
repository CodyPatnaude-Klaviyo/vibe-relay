---
title: "Phase 7: Polish & Hardening"
status: not started
---

# Phase 7: Polish & Hardening

Make the system robust enough to run real projects without manual babysitting. The full loop works after Phase 6, but agents fail, worktrees accumulate, ports conflict, and error messages are cryptic. This phase fixes that. By the end, vibe-relay is something you'd actually trust to run overnight.

---

## Deliverables

### Failed agent run handling

When an agent run exits with a non-zero exit code or raises an exception:

1. Record the error in `agent_runs.error`
2. Add a system comment to the task: `[system] Agent run failed: {error message}`
3. Move the task to a new status: `failed`
4. Emit a websocket event so the UI reflects the failure immediately

Add `failed` to the valid task statuses. Add it as a column in the UI (or show failed tasks with a red badge in their current column — either works).

#### Retry button

In the task detail panel, failed tasks show a "Retry" button. Clicking it:
1. Moves the task back to `in_progress`
2. The trigger system picks it up and launches a new agent run
3. If `session_id` is set, uses `--resume` — agent continues from where it left off

#### Max retries

Config option `max_retries` (default: 2). If a task has failed more than `max_retries` times, the retry button is replaced with a "Needs human attention" notice. The task stays `failed` and does not auto-retry.

### Stuck agent detection

An agent that never terminates is worse than one that fails cleanly. Add a watchdog:

- Config option `agent_timeout_minutes` (default: 60)
- Background task checks for agent runs with `started_at < now - timeout` and no `completed_at`
- On timeout: kill the subprocess, record the timeout as a failure, follow the failed run handling above

### Stale worktree cleanup

Background task runs every 6 hours. Finds worktrees with no active agent run and no task in `in_progress` or `in_review` (i.e., task is `done`, `cancelled`, or `failed`) and removes them.

Also: on startup, scan for worktrees with no corresponding task and remove them. These are leftovers from interrupted processes.

```python
async def cleanup_stale_worktrees():
    while True:
        await asyncio.sleep(6 * 3600)
        stale = find_stale_worktrees()
        for path in stale:
            remove_worktree(path)
```

### Port management

Implement the port allocation table for agents that spin up dev servers.

```sql
CREATE TABLE ports (
  port       INTEGER PRIMARY KEY,
  task_id    TEXT REFERENCES tasks(id),
  allocated_at TEXT NOT NULL
);
```

```python
allocate_port(task_id) -> int     # SELECT + INSERT with SQLite exclusive transaction
release_port(port) -> None        # DELETE
get_allocated_ports() -> list[int]
```

Port range comes from config (`port_range: [4000, 4099]`). If no ports are available, raise `NoPortsAvailable` — the agent run is deferred until a port frees up.

Ports are released when the agent run completes (success, failure, or timeout).

### Config validation on startup

`vibe-relay serve` validates the full config before starting any services:

- `repo_path` exists and is a git repository
- `worktrees_path` exists or can be created
- `db_path` parent directory exists or can be created
- All `system_prompt_file` paths exist and are readable
- `claude` binary is on PATH and responds to `--version`
- `gh` binary is on PATH (warn but don't fail if missing)
- `max_parallel_agents` is between 1 and 10
- `port_range` has at least 10 ports

Startup fails fast with a clear error message if any required check fails.

### Improved error messages

Audit all user-facing errors and make them actionable:

- Invalid state transition: include current status, attempted status, and valid options
- Missing config field: include field name and example value
- Worktree creation failure: include the git error output
- Agent launch failure: include whether `claude` was found, what command was attempted
- DB connection failure: include the db path and whether the file exists

### Graceful shutdown

On SIGTERM or SIGINT:
1. Stop accepting new trigger events
2. Wait for active agent runs to complete (up to `shutdown_timeout_seconds`, default 30)
3. Kill any runs still active after timeout
4. Close DB connection
5. Exit

Active run count is shown during the wait: "Waiting for 2 agent run(s) to complete (28s remaining)..."

### UI improvements

- Failed tasks show a red error badge
- Retry button on failed tasks in the detail panel
- Agent run history shows duration and exit code with color coding (green=0, red=non-zero)
- "Cancel" button on in-progress and in-review tasks (moves to `cancelled`, kills active run)
- Cancelled tasks shown in a collapsed "Cancelled" section at the bottom of the board
- Toast notifications for key events: "Planner finished — 4 tasks created", "Agent run failed on task X"

### Health endpoint

```
GET /health
```

Response:
```json
{
  "status": "ok",
  "db": "ok",
  "active_runs": 2,
  "worktrees": 3,
  "uptime_seconds": 3600
}
```

---

## Acceptance criteria

- [ ] Agent run failure sets task to `failed` and adds a system comment
- [ ] Websocket broadcasts failure immediately — UI shows red badge without refresh
- [ ] Retry button in UI re-launches the agent for a failed task
- [ ] `--resume` is used on retry if `session_id` is set
- [ ] Tasks that exceed `max_retries` show "Needs human attention" instead of retry button
- [ ] Agent runs that exceed `agent_timeout_minutes` are killed and recorded as failed
- [ ] Stale worktrees are cleaned up on the 6-hour cycle
- [ ] Orphaned worktrees (no task in DB) are removed on startup
- [ ] `allocate_port` returns a port from the configured range
- [ ] `allocate_port` never returns a port already in use
- [ ] Port is released after agent run completes
- [ ] `vibe-relay serve` fails fast with a clear message if `claude` is not on PATH
- [ ] `vibe-relay serve` fails fast with a clear message if `repo_path` is not a git repo
- [ ] `GET /health` returns correct active run count
- [ ] SIGTERM causes graceful shutdown — active runs are waited on, not killed immediately
- [ ] End-to-end: run a full project including a deliberate agent failure, verify retry works and project completes

---

## Out of scope

- No authentication
- No multi-user support
- No remote/cloud deployment support
- No plugin system