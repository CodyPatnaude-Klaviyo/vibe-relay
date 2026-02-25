---
title: "Phase 1: Foundation"
status: complete
---

# Phase 1: Foundation

Establish the project skeleton, database schema, and configuration system. Nothing executes agents yet, but by the end of this phase the data model is correct and stable, the repo structure matches the architecture, and the project can be installed and imported without errors.

This phase has no runtime behavior to demo — its value is that every subsequent phase builds on a solid, agreed-upon foundation rather than retrofitting structure later.

---

## Deliverables

### Repo structure

```
vibe-relay/
├── api/
│   └── __init__.py
├── mcp/
│   └── __init__.py
├── db/
│   ├── __init__.py
│   ├── schema.py        # Table definitions (SQLModel or raw sqlite3)
│   ├── migrations.py    # Schema creation / upgrade logic
│   └── client.py        # DB connection helper, WAL mode setup
├── runner/
│   └── __init__.py
├── agents/
│   ├── planner.md
│   ├── coder.md
│   ├── reviewer.md
│   └── orchestrator.md
├── ui/
│   └── (scaffolded via Vite in a later phase)
├── vibe_relay/
│   ├── __init__.py
│   ├── config.py        # Config loading + validation
│   └── cli.py           # Entry point (vibe-relay serve / mcp / init)
├── tests/
│   └── test_db.py
├── vibe-relay.config.json.example
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md
└── AGENTROLES.md
```

### Database schema

Implement the full schema as defined in ARCHITECTURE.md. All tables created on first run via `db/migrations.py`. WAL mode enabled on every connection.

Tables:
- `projects` — id, title, description, status, created_at, updated_at
- `tasks` — id, project_id, parent_task_id, title, description, phase, status, worktree_path, branch, session_id, created_at, updated_at
- `comments` — id, task_id, author_role, content, created_at
- `agent_runs` — id, task_id, phase, started_at, completed_at, exit_code, error
- `ports` — port, task_id, allocated_at (for port management in Phase 7)

All primary keys are UUIDs (TEXT). All timestamps are ISO 8601 strings in UTC.

### Config system

`vibe_relay/config.py` loads and validates `vibe-relay.config.json` from the current directory or a path passed via `--config`. Raises a clear error if required fields are missing.

Required config fields:
```json
{
  "repo_path": "/absolute/path/to/repo",
  "base_branch": "main",
  "worktrees_path": "~/.vibe-relay/worktrees",
  "db_path": "~/.vibe-relay/vibe-relay.db",
  "agents": {
    "planner":      { "model": "claude-opus-4-5",   "system_prompt_file": "agents/planner.md" },
    "coder":        { "model": "claude-sonnet-4-5", "system_prompt_file": "agents/coder.md" },
    "reviewer":     { "model": "claude-sonnet-4-5", "system_prompt_file": "agents/reviewer.md" },
    "orchestrator": { "model": "claude-opus-4-5",   "system_prompt_file": "agents/orchestrator.md" }
  }
}
```

Optional fields with defaults:
```json
{
  "max_parallel_agents": 3,
  "port_range": [4000, 4099]
}
```

### CLI entry point

`vibe-relay init` — creates a starter `vibe-relay.config.json` in the current directory and copies default agent prompts into `agents/`.

`vibe-relay serve` — placeholder that prints "server not yet implemented" and exits cleanly.

`vibe-relay mcp` — placeholder that prints "MCP server not yet implemented" and exits cleanly.

### Default agent prompts

Copy the four system prompts from AGENTROLES.md into `agents/planner.md`, `agents/coder.md`, `agents/reviewer.md`, `agents/orchestrator.md`. These are the defaults that `vibe-relay init` copies into new projects.

### pyproject.toml

```toml
[project]
name = "vibe-relay"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110.0",
  "uvicorn[standard]>=0.27.0",
  "sqlmodel>=0.0.16",
  "pydantic>=2.0",
  "mcp>=1.0.0",
  "click>=8.0",
  "websockets>=12.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=7.0",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
]

[project.scripts]
vibe-relay = "vibe_relay.cli:main"
```

---

## Acceptance criteria

- [x] `pip install -e .` completes without errors
- [x] `vibe-relay init` creates a valid `vibe-relay.config.json` and `agents/` directory
- [x] `vibe-relay serve` exits cleanly with a placeholder message
- [x] `vibe-relay mcp` exits cleanly with a placeholder message
- [x] Running `db/migrations.py` against an empty SQLite file creates all tables with correct columns
- [x] Re-running migrations is idempotent (no errors if tables already exist)
- [x] WAL mode is confirmed enabled after DB initialization
- [x] Config loader raises a descriptive error for missing `repo_path`
- [x] Config loader expands `~` in path fields
- [x] `tests/test_db.py` passes: creates DB, inserts a project and task, reads them back, verifies foreign key constraint on task→project

---

## Out of scope

- No HTTP server
- No MCP server
- No agent execution
- No UI
- No git operations