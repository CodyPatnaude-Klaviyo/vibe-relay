# vibe-relay

A multi-agent coding orchestration system built on Claude Code. Define a project, walk away, and watch a coordinated team of AI agents plan, build, review, and ship it.

---

## What it does

vibe-relay breaks software work into phases and routes tasks between specialized Claude Code agents automatically. You create an initial task — either through the UI or via Claude Code itself — and a planning agent decomposes it into a board of work. Coder agents pick up tasks, implement them in isolated git worktrees, and open PRs. Reviewer agents inspect the work and either approve it or send it back with comments. When all tasks are complete, an orchestrator agent surveys the board, runs a completion check, and either closes the project or creates more tasks.

Every agent communicates through comments on tasks. The full conversation history is preserved when tasks change state, so a coder resuming a reviewed task sees exactly what the reviewer said and why.

---

## Architecture overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  React UI   │────▶│  FastAPI    │────▶│   SQLite    │
│  (kanban)   │◀────│  (REST +    │◀────│   (tasks,   │
│             │ WS  │  websocket) │     │  comments)  │
└─────────────┘     └─────────────┘     └─────────────┘
                                               ▲
                                               │
                    ┌─────────────┐            │
                    │  MCP Server │────────────┘
                    │  (stdio)    │
                    └─────────────┘
                          ▲
                          │
              ┌───────────┴───────────┐
              │                       │
        ┌──────────┐           ┌──────────┐
        │  Claude  │           │  Claude  │
        │  (coder) │           │(reviewer)│
        └──────────┘           └──────────┘
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for full detail.

---

## Agent roles

| Role | Trigger | Responsibility |
|------|---------|----------------|
| **Planner** | New project task created | Decomposes work into subtasks on the board |
| **Coder** | Task moves to `in_progress` | Implements in a git worktree, opens PR, moves to `in_review` |
| **Reviewer** | Task moves to `in_review` | Reviews PR, merges or sends back with comments |
| **Orchestrator** | All sibling tasks reach `done` | Reviews project state, runs completion check, creates more tasks or closes project |

See [AGENTS.md](./AGENTS.md) for system prompts and configuration.

---

## Key features

- **Git worktree isolation** — every task gets its own branch and worktree, agents never step on each other
- **Session resumability** — when a task is sent back from review, Claude resumes the exact previous conversation using `--resume {session_id}` in the preserved worktree
- **MCP-driven board** — agents have full control of the board through a local MCP server; they create tasks, move cards, and leave comments without human intervention
- **Phase-specific system prompts** — each agent role runs with a different system prompt tailored to its job
- **Live UI** — watch the board update in real time via websocket as agents work
- **Human-in-the-loop** — you can move cards, add comments, or intervene at any point through the UI

---

## Getting started

### Prerequisites

- Node.js 18+
- Python 3.11+
- [Claude Code](https://docs.claude.com/en/docs/claude-code/quickstart) installed and authenticated (`npx @anthropic-ai/claude-code`)
- Git

### Install

```bash
git clone https://github.com/your-username/vibe-relay
cd vibe-relay

# Backend
pip install -e ".[dev]"

# Frontend
cd ui && npm install && cd ..
```

### Run

```bash
# Start the API server (includes MCP server and agent runner)
vibe-relay serve

# In another terminal, start the UI
cd ui && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) to see the board.

### Create your first project

**Via UI:** Click "New Project", describe the work, hit submit. The planner agent takes it from there.

**Via Claude Code:**

Add the vibe-relay MCP server to your Claude Code config:

```json
{
  "mcpServers": {
    "vibe-relay": {
      "command": "vibe-relay",
      "args": ["mcp"]
    }
  }
}
```

Then from within a Claude Code session:

```
Create a new vibe-relay project: build a REST API for a todo app with auth
```

---

## Configuration

Create a `vibe-relay.config.json` in your project root:

```json
{
  "repo_path": "/path/to/your/repo",
  "base_branch": "main",
  "worktrees_path": "~/.vibe-relay/worktrees",
  "agents": {
    "planner": {
      "model": "claude-opus-4-5",
      "system_prompt_file": "agents/planner.md"
    },
    "coder": {
      "model": "claude-sonnet-4-5",
      "system_prompt_file": "agents/coder.md"
    },
    "reviewer": {
      "model": "claude-sonnet-4-5",
      "system_prompt_file": "agents/reviewer.md"
    },
    "orchestrator": {
      "model": "claude-opus-4-5",
      "system_prompt_file": "agents/orchestrator.md"
    }
  }
}
```

System prompts can be customized per project. See [AGENTS.md](./AGENTS.md) for the defaults and guidance on writing effective prompts for each role.

---

## Project structure

```
vibe-relay/
├── api/              # FastAPI app — REST endpoints + websocket
├── mcp/              # MCP server — tool definitions for agents
├── db/               # SQLite schema and migrations
├── runner/           # Claude CLI subprocess wrapper, worktree management
├── agents/           # Default system prompts per phase
├── ui/               # React kanban board
└── vibe_relay/       # Python package entry point
```

---

## How resumability works

When a coder picks up a task for the first time, vibe-relay:

1. Creates a git worktree on a new branch (`task-{id}-{timestamp}`)
2. Launches `claude` with `--dangerously-skip-permissions` and captures the `session_id` from the JSON output
3. Stores `session_id` and `worktree_path` on the task record

When the task is sent back from review, vibe-relay:

1. Injects the reviewer's comments as a new prompt
2. Launches `claude --resume {session_id}` in the same worktree
3. Claude picks up mid-conversation with full context and the git state intact

The worktree is preserved until the task is marked `done`. Only then is it cleaned up.

---

## License

MIT