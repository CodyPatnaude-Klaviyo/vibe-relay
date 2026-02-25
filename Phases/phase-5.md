---
title: "Phase 5: UI"
status: complete
---

# Phase 5: UI

Build the kanban board. By the end of this phase, you can open a browser, see all tasks organized by status column, watch cards move in real time as agents work, click into a task to read the comment thread, and manually move cards or add comments as a human. The board is the control room for the whole system.

This phase is self-contained — it only needs the API from Phase 4 running. No knowledge of agents, MCP, or git.

---

## Deliverables

### Scaffolding

Vite + React + TypeScript project in `ui/`. 

```bash
npm create vite@latest ui -- --template react-ts
```

Dependencies:
```json
{
  "@tanstack/react-query": "^5.0.0",
  "react-router-dom": "^6.0.0",
  "zustand": "^4.0.0"
}
```

No component library — plain CSS with CSS variables for theming. Keeping it minimal so an agent can understand and modify the styles without fighting a framework.

API base URL configured via `VITE_API_URL` environment variable, defaulting to `http://localhost:8000`.

### Pages

Two pages:

- `/` — project list
- `/projects/:id` — kanban board for a project

### Project list (`/`)

Simple list of all projects. Each row shows project title, status badge, and task counts (x in progress, x in review, x done). "New Project" button opens a modal to create one.

### Kanban board (`/projects/:id`)

Four columns: **Backlog**, **In Progress**, **In Review**, **Done**.

Each card shows:
- Task title
- Phase badge (planner / coder / reviewer / orchestrator) — color coded
- Comment count
- Branch name (if set), truncated

Clicking a card opens a task detail panel (sidebar or modal — sidebar preferred).

#### Task detail panel

Shows:
- Title and description
- Status badge
- Phase badge
- Branch name (linked to GitHub if a remote URL is configured)
- Worktree path
- Comment thread in chronological order, each comment showing author role and timestamp
- "Add comment" textarea + submit button (posts as `author_role: "human"`)
- Agent run history — list of runs with start time, duration, exit code
- Status change buttons — the valid next states for this task, as buttons

#### Status change buttons

Derived from the state machine. If task is `in_progress`, show "Send to Review" button. If `in_review`, show "Approve" (→ done) and "Request Changes" (→ in_progress) buttons. If `backlog`, show "Start" button.

Human-triggered status changes POST to `PATCH /tasks/{id}` and optimistically update the UI.

### Websocket integration

On mount, the board opens a websocket connection to `ws://localhost:8000/ws`. On each event:

- `task_created` — adds card to correct column
- `task_updated` — moves card if status changed, updates card content
- `comment_added` — updates comment count on card, appends to thread if detail panel is open

No full page reload. Cards animate between columns on status change (CSS transition on column membership).

### Live indicator

Small dot in the top right — green if websocket is connected, grey if disconnected. Auto-reconnect with exponential backoff on disconnect.

### Phase badges — color scheme

| Phase | Color |
|-------|-------|
| planner | Purple |
| coder | Blue |
| reviewer | Orange |
| orchestrator | Green |

### Empty states

- No projects: "No projects yet. Create one to get started."
- Empty column: subtle placeholder text ("Nothing here yet")
- Task with no comments: "No comments yet."

---

## File structure

```
ui/
├── src/
│   ├── api/
│   │   ├── client.ts        # fetch wrapper with base URL
│   │   ├── projects.ts      # project API calls
│   │   └── tasks.ts         # task API calls
│   ├── components/
│   │   ├── Board.tsx        # four-column kanban layout
│   │   ├── TaskCard.tsx     # card shown in column
│   │   ├── TaskDetail.tsx   # sidebar panel
│   │   ├── CommentThread.tsx
│   │   ├── PhaseBadge.tsx
│   │   ├── StatusBadge.tsx
│   │   └── NewProjectModal.tsx
│   ├── hooks/
│   │   ├── useBoard.ts      # fetches and subscribes to project tasks
│   │   └── useWebSocket.ts  # websocket connection + reconnect logic
│   ├── store/
│   │   └── boardStore.ts    # zustand store for board state
│   ├── pages/
│   │   ├── ProjectList.tsx
│   │   └── ProjectBoard.tsx
│   ├── App.tsx
│   └── main.tsx
├── index.html
├── vite.config.ts
└── package.json
```

---

## Acceptance criteria

- [x] `npm run dev` starts the dev server, board loads at `http://localhost:5173`
- [x] Project list shows all projects from the API
- [x] "New Project" modal creates a project and navigates to the board
- [x] Board shows four columns with correct tasks in each
- [x] Task card shows title, phase badge, comment count, branch name
- [x] Clicking a card opens the detail panel
- [x] Detail panel shows full comment thread in order
- [x] "Add comment" submits and the new comment appears immediately
- [x] Status change buttons show only valid next states
- [x] Clicking a status change button moves the card to the correct column
- [x] Websocket events move cards in real time without page reload
- [x] Websocket live indicator shows green when connected, grey when not
- [x] Disconnected websocket auto-reconnects
- [x] Manual test: in one browser tab, move a task via curl — verify the card moves in the other tab within 1 second
- [x] `npm run build` produces a working static build in `ui/dist/`

---

## Out of scope

- No drag-and-drop between columns (status change buttons only)
- No authentication
- No dark mode
- No mobile layout