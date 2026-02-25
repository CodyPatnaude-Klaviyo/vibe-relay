# Architecture

vibe-relay is a local-first multi-agent orchestration system. Everything runs on your machine — no cloud dependencies, no managed services. The core data store is SQLite. The agent interface is the Claude Code CLI. The integration layer is an MCP server.

---

## System components

### FastAPI server (`api/`)

The central hub. Handles:

- REST endpoints for the UI and external tooling
- Websocket connections for live board updates
- Task state machine enforcement — validates status transitions
- Triggering agent runs when task state changes

The server also owns the SQLite connection and is the single writer to the database (the MCP server reads directly but routes all writes through the API).

### MCP server (`mcp/`)

A stdio-transport MCP server that exposes the board as a set of tools for Claude Code agents. Agents running inside Claude Code sessions connect to this server and use it to read and write the board without needing HTTP knowledge.

The MCP server connects to the same SQLite database as the API. It is read-write. Writes from the MCP server trigger websocket broadcasts via a lightweight internal event bus so the UI stays live.

All board mutations available to agents:

| Tool | Description |
|------|-------------|
| `get_board` | Returns full board state — all tasks, statuses, comments |
| `get_task(task_id)` | Returns a single task with full comment thread |
| `get_my_tasks(phase)` | Returns tasks in `in_progress` assigned to a given phase |
| `create_task(title, description, phase, parent_task_id?)` | Creates a new task, optionally as a subtask |
| `create_subtasks(parent_task_id, tasks[])` | Bulk creates subtasks for a parent |
| `update_task_status(task_id, status)` | Moves a task through the state machine |
| `add_comment(task_id, content, author_role)` | Adds a comment to a task's thread |
| `complete_task(task_id)` | Marks a task done and triggers orchestrator check |

### Agent runner (`runner/`)

Manages the lifecycle of Claude Code subprocesses. Responsibilities:

- Watching for state transitions that require an agent run (via SQLite triggers or polling)
- Creating and managing git worktrees
- Launching `claude` with the appropriate system prompt, MCP config, and flags
- Capturing `session_id` from the first run and persisting it on the task
- Resuming sessions with `--resume {session_id}` on subsequent runs
- Port allocation (if agents need dev servers)

The runner does not directly call the Claude API — it shells out to the `claude` CLI. This means agent runs inherit the user's Claude Code authentication and rate limits.

### SQLite database (`db/`)

Single file, WAL mode enabled for concurrent reads from the MCP server and API.

#### Schema

```sql
CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'active', -- active | complete
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE tasks (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(id),
  parent_task_id  TEXT REFERENCES tasks(id),
  title           TEXT NOT NULL,
  description     TEXT,
  phase           TEXT NOT NULL,             -- planner | coder | reviewer | orchestrator
  status          TEXT NOT NULL DEFAULT 'backlog', -- backlog | in_progress | in_review | done | cancelled
  worktree_path   TEXT,                      -- set when agent first picks up
  branch          TEXT,                      -- set when worktree created
  session_id      TEXT,                      -- claude session_id for --resume
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE TABLE comments (
  id          TEXT PRIMARY KEY,
  task_id     TEXT NOT NULL REFERENCES tasks(id),
  author_role TEXT NOT NULL,                 -- planner | coder | reviewer | orchestrator | human
  content     TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE agent_runs (
  id          TEXT PRIMARY KEY,
  task_id     TEXT NOT NULL REFERENCES tasks(id),
  phase       TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  completed_at TEXT,
  exit_code   INTEGER,
  error       TEXT
);
```

#### State machine

Valid task status transitions:

```
backlog ──▶ in_progress ──▶ in_review ──▶ done
                ▲                │
                └────────────────┘
                   (sent back by reviewer)
```

The API enforces this — invalid transitions are rejected with 422.

### React UI (`ui/`)

A single-page kanban board. Uses websocket for live updates — no polling.

Columns map to task statuses. Cards show title, phase badge, and comment count. Clicking a card opens a detail panel with the full description and comment thread.

Human actions available from the UI:

- Create a new project (triggers planner)
- Move a card manually (for intervention)
- Add a comment to any task
- Cancel a task
- View agent run history per task

---

## Data flow

### New project created

```
Human creates project via UI
  → POST /projects
  → Project row created, root planning task created with status=in_progress
  → Runner detects new in_progress task with phase=planner
  → Runner creates worktree, launches claude with planner system prompt + MCP config
  → Planner agent calls create_subtasks() via MCP
  → Tasks appear on board in real time via websocket
  → Planner agent calls complete_task() on root task
  → Runner cleans up planner worktree
```

### Coder picks up a task

```
Task status=in_progress, phase=coder
  → Runner creates worktree on new branch
  → Runner launches claude --dangerously-skip-permissions with coder system prompt
  → Agent payload:
      <system_prompt>[coder.md contents]</system_prompt>
      <issue>[task title + description]</issue>
      <comments>[full comment thread]</comments>
  → Claude implements, commits, pushes, opens PR
  → Agent calls update_task_status(task_id, "in_review") via MCP
  → Runner captures session_id, stores on task
  → Reviewer agent triggered
```

### Reviewer sends task back

```
Reviewer calls add_comment(task_id, "needs tests for edge case X") via MCP
Reviewer calls update_task_status(task_id, "in_progress") via MCP
  → Runner detects transition back to in_progress
  → Runner launches claude --resume {session_id} in existing worktree
  → Agent receives reviewer comment in prompt context
  → Coder addresses feedback, pushes, moves back to in_review
```

### Orchestrator fires

```
All sibling tasks reach status=done
  → API detects completion condition
  → Orchestrator task created and set to in_progress
  → Runner launches orchestrator agent with full board state
  → Orchestrator reviews merged code, runs checks
  → Either: calls create_subtasks() for more work
  → Or: marks project complete
```

---

## Agent context format

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
[{author_role}] {created_at}: {content}
...
</comments>
```

The comment thread is the memory handoff between roles. When a coder resumes after review, the reviewer's feedback is in `<comments>` and Claude's own prior work is in the resumed session context.

---

## Worktree lifecycle

```
Task created (backlog)
  → No worktree

Task moves to in_progress (first time)
  → worktree created at ~/.vibe-relay/worktrees/{project_id}/{task_id}/
  → branch created: task-{task_id}-{timestamp}
  → session_id captured and stored

Task moves to in_review
  → Worktree preserved
  → Session preserved

Task moves back to in_progress
  → Worktree unchanged (git state intact)
  → claude --resume {session_id} launched in same path

Task moves to done
  → PR merged (by reviewer agent via gh CLI)
  → Worktree removed
  → Branch deleted from remote
```

---

## Concurrency model

Multiple coder agents can run in parallel — each operates in its own worktree on its own branch. There is no shared mutable state between agent processes except the SQLite database, which handles concurrent access via WAL mode.

The runner uses a simple task queue: it polls for `in_progress` tasks with no active run and spawns agents up to a configurable concurrency limit (`max_parallel_agents`, default 3).

Reviewer agents are intentionally serialized — only one reviewer runs at a time — to avoid conflicting merge decisions on interdependent tasks.

---

## Port management

If a coder agent spins up a dev server to test its work, vibe-relay allocates it a port from a reserved range (default: 4000–4099) using a SQLite-backed port table with `SELECT FOR UPDATE` semantics. The port is released when the agent run completes.

---

## MCP transport

The MCP server uses stdio transport, which means each agent process gets its own MCP server instance as a subprocess. The MCP config injected into each Claude Code session:

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

Passing `--task-id` scopes certain tools (like `get_my_tasks`) to the current task's context automatically.

---

## Configuration reference

`vibe-relay.config.json`:

```json
{
  "repo_path": "/path/to/repo",
  "base_branch": "main",
  "worktrees_path": "~/.vibe-relay/worktrees",
  "db_path": "~/.vibe-relay/vibe-relay.db",
  "max_parallel_agents": 3,
  "port_range": [4000, 4099],
  "agents": {
    "planner":      { "model": "claude-opus-4-5",   "system_prompt_file": "agents/planner.md" },
    "coder":        { "model": "claude-sonnet-4-5", "system_prompt_file": "agents/coder.md" },
    "reviewer":     { "model": "claude-sonnet-4-5", "system_prompt_file": "agents/reviewer.md" },
    "orchestrator": { "model": "claude-opus-4-5",   "system_prompt_file": "agents/orchestrator.md" }
  }
}
```