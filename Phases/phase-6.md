---
title: "Phase 6: End-to-End Wiring"
status: not started
---

# Phase 6: End-to-End Wiring

Connect the state machine to the agent runner. By the end of this phase, the full loop works: create a project, walk away, and watch agents plan, build, review, and complete work autonomously. Status transitions automatically trigger the right agent. The board updates live in the UI. This is the phase where vibe-relay becomes a real system.

---

## Deliverables

### Trigger system (`runner/triggers.py`)

A background task that watches for state transitions requiring agent runs and launches them.

The trigger system runs as an asyncio task inside `vibe-relay serve`. It polls the `events` table for unconsumed task state change events and dispatches agent runs based on transition type.

```python
async def process_triggers():
    while True:
        events = db.get_unconsumed_trigger_events()
        for event in events:
            await dispatch(event)
            db.mark_trigger_consumed(event.id)
        await asyncio.sleep(1)
```

#### Dispatch rules

| Transition | Agent triggered |
|-----------|----------------|
| `backlog → in_progress` with `phase=planner` | Planner agent |
| `backlog → in_progress` with `phase=coder` | Coder agent |
| `backlog → in_progress` with `phase=reviewer` | Reviewer agent |
| `in_review → in_progress` (sent back) | Coder agent (resume) |
| `in_review → done` on last sibling | Orchestrator agent |
| `backlog → in_progress` with `phase=orchestrator` | Orchestrator agent |

The trigger system does **not** auto-start tasks in `backlog`. Only explicit transitions to `in_progress` launch agents. This preserves human control — a human (or the planner agent) must explicitly move a task to `in_progress` to kick it off.

#### Concurrency guard

Before launching an agent, check if the task already has an active run (started_at set, completed_at null). If so, skip. This prevents double-launching on duplicate events.

Also enforce the global `max_parallel_agents` limit from config. If at capacity, leave the event unconsumed and retry on the next poll cycle.

### Project creation auto-start

When `POST /projects` creates the root planner task, immediately set it to `in_progress` (not `backlog`). This auto-starts the planning agent without requiring a manual nudge.

Update `api/app.py` accordingly.

### Planner agent completion → task auto-start

After the planner agent creates subtasks (via `create_subtasks` MCP tool) and calls `complete_task`, the system automatically moves all created subtasks from `backlog` to `in_progress` with `phase=coder`.

This logic lives in the `complete_task` MCP tool handler: when a planner task completes, find all its children in `backlog` with `phase=coder` and transition them.

Alternatively, the planner agent can call `update_task_status` on each subtask explicitly — the system prompt should instruct it to do this. Either approach works; explicit agent control is preferred for transparency.

Update `agents/planner.md` to include the instruction to start subtasks.

### Reviewer merge → worktree cleanup

When a reviewer calls `complete_task`, the system:
1. Marks the task `done`
2. Schedules worktree cleanup: removes the worktree directory and git registration
3. Does **not** delete the branch until the PR is confirmed merged (check via `gh pr status`)

Add a `cleanup_worktree_after_complete` hook to the `complete_task` MCP handler.

### Orchestrator trigger condition

The `complete_task` MCP handler already detects when all siblings are complete (`siblings_complete: true`). When this fires:

1. Find the parent task
2. Create a new task: `phase=orchestrator`, `status=in_progress`, `parent_task_id=parent.id`
3. The trigger system picks this up and launches the orchestrator agent

### Full loop integration test

A script (`tests/test_full_loop.py`) that:
1. Creates a project via the API
2. Waits for the planner agent to create subtasks (polls board)
3. Waits for coder agents to move tasks to `in_review`
4. Manually approves tasks (moves to `done`) to avoid needing a real PR
5. Waits for the orchestrator to fire
6. Asserts the project reaches a terminal state

This test runs against a real Claude session and is not part of the unit test suite — it's a smoke test for the full system.

### Updated `vibe-relay serve`

The serve command now starts three concurrent tasks:
1. Uvicorn (FastAPI HTTP server)
2. Websocket event broadcaster (Phase 4)
3. Trigger processor (this phase)

```python
async def serve():
    config = load_config()
    await asyncio.gather(
        run_uvicorn(config),
        broadcast_events(config),
        process_triggers(config),
    )
```

---

## Acceptance criteria

- [ ] Creating a project via the UI auto-starts the planner agent
- [ ] Planner agent creates subtasks visible on the board in real time
- [ ] Planner-created subtasks with `phase=coder` are automatically moved to `in_progress`
- [ ] Coder agents launch for each `in_progress` coder task
- [ ] Coder agents move tasks to `in_review` when done — reviewer agent triggers
- [ ] Reviewer sending a task back to `in_progress` resumes the coder with `--resume {session_id}`
- [ ] Resumed coder session has access to reviewer comments via the `<comments>` block
- [ ] When all coder tasks are done, orchestrator agent fires
- [ ] Worktrees are cleaned up after tasks complete
- [ ] `max_parallel_agents` limit is respected — excess tasks wait until a slot opens
- [ ] No double-launches — triggering the same task twice results in one agent run
- [ ] Full loop smoke test: project created, tasks planned, coded, reviewed, orchestrated — reaches terminal state without manual intervention
- [ ] The UI shows the board updating throughout the full run with no manual refresh

---

## Out of scope

- No retry logic for failed agent runs (Phase 7)
- No timeout handling for stuck agents (Phase 7)
- No notification system