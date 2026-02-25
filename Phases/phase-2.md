---
title: "Phase 2: MCP Server"
status: not started
---

# Phase 2: MCP Server

Build the MCP server that gives agents full control of the board. By the end of this phase, a Claude Code session can connect to vibe-relay's MCP server and create projects, manage tasks, add comments, and read board state — entirely through tool calls. No API server, no UI, no agent runner yet.

This phase delivers standalone value: you can connect Claude Code to the MCP server and drive the board manually from a conversation, which is a useful way to test the data model and tool contracts before wiring in automation.

---

## Deliverables

### MCP server (`mcp/server.py`)

A stdio-transport MCP server implemented using the `mcp` Python SDK. Launched via `vibe-relay mcp`.

Reads from and writes to the SQLite database directly. All writes emit an internal event (simple in-process queue or file-based signal) so the API server can broadcast them via websocket in Phase 4.

The server accepts an optional `--task-id` argument to scope context-sensitive tools.

### Tool definitions

Implement all eight board tools:

#### `get_board`
Returns the full board state for a project.

Input:
```json
{ "project_id": "string" }
```

Output:
```json
{
  "project": { "id": "...", "title": "...", "status": "..." },
  "tasks": [
    {
      "id": "...",
      "title": "...",
      "phase": "coder",
      "status": "in_progress",
      "parent_task_id": null,
      "comment_count": 3,
      "branch": "task-abc-1234",
      "worktree_path": "/..."
    }
  ]
}
```

#### `get_task`
Returns a single task with its full comment thread.

Input:
```json
{ "task_id": "string" }
```

Output:
```json
{
  "id": "...",
  "title": "...",
  "description": "...",
  "phase": "coder",
  "status": "in_progress",
  "branch": "...",
  "worktree_path": "...",
  "session_id": "...",
  "comments": [
    { "id": "...", "author_role": "planner", "content": "...", "created_at": "..." }
  ]
}
```

#### `get_my_tasks`
Returns tasks currently assigned to a given phase with status `in_progress`.

Input:
```json
{ "phase": "coder" }
```

Output: array of task objects (same shape as items in `get_board.tasks`).

#### `create_task`
Creates a single new task.

Input:
```json
{
  "title": "string",
  "description": "string",
  "phase": "coder | reviewer | planner | orchestrator",
  "parent_task_id": "string | null",
  "project_id": "string"
}
```

Output: created task object.

Status defaults to `backlog`. Created_at and updated_at set to now.

#### `create_subtasks`
Bulk creates tasks under a parent. Preferred over multiple `create_task` calls to reduce round-trips.

Input:
```json
{
  "parent_task_id": "string",
  "tasks": [
    { "title": "string", "description": "string", "phase": "coder" }
  ]
}
```

Output:
```json
{ "created": [ { ...task }, { ...task } ] }
```

#### `update_task_status`
Moves a task to a new status. Enforces the state machine — invalid transitions return an error.

Valid transitions:
- `backlog → in_progress`
- `in_progress → in_review`
- `in_review → in_progress` (sent back)
- `in_review → done` (via complete_task)

Input:
```json
{ "task_id": "string", "status": "in_progress | in_review | done | cancelled" }
```

Output: updated task object.

#### `add_comment`
Adds a comment to a task's thread.

Input:
```json
{
  "task_id": "string",
  "content": "string",
  "author_role": "planner | coder | reviewer | orchestrator | human"
}
```

Output: created comment object.

#### `complete_task`
Marks a task `done`. Convenience wrapper around `update_task_status` that also checks whether all sibling tasks are now done and emits an orchestrator trigger event if so.

Input:
```json
{ "task_id": "string" }
```

Output:
```json
{
  "task": { ...updated task },
  "siblings_complete": true | false,
  "orchestrator_triggered": true | false
}
```

### State machine enforcement

`update_task_status` and `complete_task` must reject invalid transitions with a descriptive error:

```json
{
  "error": "invalid_transition",
  "message": "Cannot move task from 'backlog' to 'in_review'. Valid next states: ['in_progress', 'cancelled']"
}
```

### Event emission

After any write operation, the MCP server writes a notification to a SQLite `events` table:

```sql
CREATE TABLE events (
  id          TEXT PRIMARY KEY,
  type        TEXT NOT NULL,  -- task_updated | comment_added | task_created
  payload     TEXT NOT NULL,  -- JSON
  created_at  TEXT NOT NULL,
  consumed    INTEGER NOT NULL DEFAULT 0
);
```

The API server (Phase 4) polls this table and broadcasts unconsumed events via websocket. This decouples the MCP server from the HTTP layer.

### CLI update

`vibe-relay mcp` now launches the actual MCP server instead of printing a placeholder:

```bash
vibe-relay mcp --task-id <task_id>
```

`--task-id` is optional. When provided, `get_my_tasks` defaults to the phase of that task.

### MCP config snippet

Document the config snippet agents should include:

```json
{
  "mcpServers": {
    "vibe-relay": {
      "command": "vibe-relay",
      "args": ["mcp", "--task-id", "{task_id}"],
      "env": {
        "VIBE_RELAY_DB": "/path/to/vibe-relay.db"
      }
    }
  }
}
```

---

## Acceptance criteria

- [ ] `vibe-relay mcp` starts without errors and accepts MCP tool calls via stdio
- [ ] `create_task` creates a row in the DB and returns the task object
- [ ] `create_subtasks` creates multiple tasks in a single call and returns all of them
- [ ] `get_board` returns all tasks for a project with correct structure
- [ ] `get_task` returns a task with its full comment thread in chronological order
- [ ] `get_my_tasks("coder")` returns only `in_progress` tasks with `phase=coder`
- [ ] `add_comment` creates a comment row and returns it
- [ ] `update_task_status` enforces the state machine — `backlog → in_review` is rejected
- [ ] `update_task_status` succeeds for all valid transitions
- [ ] `complete_task` sets status to `done` and correctly detects when all siblings are complete
- [ ] Every write operation inserts a row into the `events` table
- [ ] The MCP server can be connected to from a Claude Code session using the config snippet above
- [ ] Manual test: connect Claude Code to the MCP server, ask it to create a project with three tasks, verify rows appear in SQLite

---

## Out of scope

- No HTTP server
- No websocket
- No agent execution
- No UI
- No git operations