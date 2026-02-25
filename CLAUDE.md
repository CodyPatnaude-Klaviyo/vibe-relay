# CLAUDE.md

You are working in the **vibe-relay** repository — a multi-agent coding orchestration system built on Claude Code.

Before doing anything, read `ARCHITECTURE.md` to understand the system design and `README.md` for the project overview. The `phases/` directory contains detailed specs for each milestone — always check the relevant phase doc before implementing a feature.

---

## How this repo is organized

```
vibe-relay/
├── api/              # FastAPI app — REST endpoints + websocket
├── mcp/              # MCP server — tool definitions for agents
├── db/               # SQLite schema, migrations, state machine
├── runner/           # Claude CLI subprocess wrapper, worktree management
├── agents/           # System prompts for each agent role
├── ui/               # React + TypeScript kanban board
├── vibe_relay/       # Python package entry point, config, CLI
├── tests/            # Unit and integration tests
├── phases/           # Phase specs (read these before implementing)
├── ARCHITECTURE.md   # Full system design — read this first
├── README.md         # Project overview
└── CLAUDE.md         # This file
```

---

## Working on a phase

Each file in `phases/` corresponds to a milestone. Check the front-matter `status` field before starting:

- `not started` — nothing exists yet, build from scratch
- `in progress` — partially complete, read carefully before adding code
- `complete` — do not modify unless fixing a bug

When you finish a phase, update the front-matter `status` to `complete`.

The phases build on each other in order. Do not implement functionality belonging to a later phase unless the current phase explicitly requires it.

---

## Python conventions

- Python 3.11+
- Use `sqlmodel` for DB models and queries
- Pydantic v2 for all data validation
- `asyncio` throughout — no synchronous blocking calls in async contexts
- Type-annotate everything. No bare `Any` unless unavoidable and commented
- Use `pathlib.Path` for all file paths, never string concatenation
- All timestamps: ISO 8601 strings in UTC (`datetime.now(timezone.utc).isoformat()`)
- All primary keys: UUID4 as TEXT (`str(uuid.uuid4())`)
- DO NOT globally install python deps. Use uv instead

---

## TypeScript / React conventions (ui/)

- TypeScript strict mode
- Functional components only, hooks for all state
- No component libraries — plain CSS with CSS variables
- `@tanstack/react-query` for server state
- `zustand` for client state
- `VITE_API_URL` env var for API base URL, default `http://localhost:8000`

---

## Required checks before pushing

### Python
Run these against any file you modify. Fix all errors before committing.

```bash
# From repo root
ruff check {changed_files}
ruff format {changed_files}
mypy {changed_files}
pytest tests/
```

### TypeScript
```bash
cd ui
npm run typecheck
npm run lint
npm run build   # must succeed before pushing
```

Do not push if any of these fail.

---

## Git workflow

- Never push directly to `main`
- Branch naming: `phase-{N}-{short-description}` (e.g., `phase-2-mcp-tools`)
- Commit messages: present tense, imperative ("Add get_board MCP tool", not "Added...")
- One logical change per commit — don't bundle unrelated changes
- Open a PR when the phase acceptance criteria are met

---

## Database rules

- The schema lives in `db/schema.py`. Do not modify the schema without updating `db/migrations.py`
- Migrations must be idempotent — running them twice must not error
- WAL mode must be enabled on every new DB connection (`PRAGMA journal_mode=WAL`)
- Foreign keys must be enabled on every new DB connection (`PRAGMA foreign_keys=ON`)
- The `events` table is the communication channel between the MCP server and the API websocket broadcaster. Every write operation in the MCP server must insert an event row.
- State machine transitions are enforced in `db/state_machine.py` — import from there, do not duplicate the logic

---

## MCP server rules

- All board mutations go through MCP tools
- MCP tools are the source of truth for business logic — the API is a thin wrapper
- Tool inputs and outputs must be fully type-annotated
- Every tool must handle the case where the referenced task or project does not exist (return a clear error, not an exception)

---

## Agent runner rules

- Always capture `session_id` from the first Claude output and persist it to the task immediately — do not wait for the run to complete
- Always use `--resume {session_id}` when relaunching a task that has a session_id set
- Never clean up a worktree unless the task is `done`, `cancelled`, or `failed`
- The `<comments>` block in the agent prompt is the memory handoff between roles — always include it

---

## What not to do

- Do not add new dependencies without a clear reason — check if something in the existing stack covers the need
- Do not implement features from a later phase to "get ahead" — phases exist to keep scope manageable
- Do not hardcode paths — everything comes from config
- Do not swallow exceptions silently — log them and propagate or surface them to the user
- Do not write to the DB from the API and the MCP server using different logic — the state machine lives in `db/state_machine.py` and is used by both

---

## Running the system locally

```bash
# Install
pip install -e ".[dev]"

# Initialize a new project
vibe-relay init

# Start the server (API + websocket + trigger processor)
vibe-relay serve

# Start the UI (separate terminal)
cd ui && npm run dev

# Run a single agent manually (useful for testing)
vibe-relay run-agent --task-id <task_id>

# Connect Claude Code to the MCP server
# Add to your Claude Code MCP config:
# {
#   "mcpServers": {
#     "vibe-relay": {
#       "command": "vibe-relay",
#       "args": ["mcp", "--task-id", "<task_id>"],
#       "env": { "VIBE_RELAY_DB": "/path/to/vibe-relay.db" }
#     }
#   }
# }
```

---

## Acceptance criteria

Every phase doc in `phases/` has an acceptance criteria checklist. A phase is not complete until every item is checked off. When marking a phase complete:

1. Check off all items in the phase doc
2. Update the front-matter `status` to `complete`
3. Commit the phase doc update as part of the PR