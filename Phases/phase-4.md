---
title: "Phase 4: API + Websocket"
status: complete
---

# Phase 4: API + Websocket

Build the HTTP server that the UI talks to. By the end of this phase, all board operations are accessible via REST, the state machine is enforced at the API layer, and live board updates are pushed to connected clients via websocket. No UI yet — verify with curl and a websocket client.

This phase delivers standalone value: the API is the stable contract between the UI and the system. Getting it right here means the UI in Phase 5 is straightforward to build.

---

## Deliverables

### FastAPI application (`api/app.py`)

A FastAPI app with CORS enabled (all origins, for local development).

```python
app = FastAPI(title="vibe-relay")
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```

### REST endpoints

#### Projects

```
POST   /projects                    Create a new project
GET    /projects                    List all projects
GET    /projects/{project_id}       Get project with task summary
DELETE /projects/{project_id}       Cancel/archive project
```

**POST /projects**

Request:
```json
{ "title": "string", "description": "string" }
```

Response: created project object. Also creates a root planning task with `phase=planner`, `status=backlog`.

**GET /projects/{project_id}**

Response:
```json
{
  "id": "...",
  "title": "...",
  "description": "...",
  "status": "active",
  "tasks": {
    "backlog": 2,
    "in_progress": 1,
    "in_review": 1,
    "done": 3
  },
  "created_at": "...",
  "updated_at": "..."
}
```

#### Tasks

```
POST   /projects/{project_id}/tasks         Create a task
GET    /projects/{project_id}/tasks         List all tasks for a project
GET    /tasks/{task_id}                     Get task with comments
PATCH  /tasks/{task_id}                     Update task (status, title, description)
POST   /tasks/{task_id}/comments            Add a comment
GET    /tasks/{task_id}/runs                Get agent run history for a task
```

**GET /projects/{project_id}/tasks**

Returns tasks grouped by status:
```json
{
  "backlog":     [ { ...task } ],
  "in_progress": [ { ...task } ],
  "in_review":   [ { ...task } ],
  "done":        [ { ...task } ]
}
```

**GET /tasks/{task_id}**

Returns task with full comment thread:
```json
{
  "id": "...",
  "title": "...",
  "description": "...",
  "phase": "coder",
  "status": "in_review",
  "branch": "task-abc-1234",
  "worktree_path": "/...",
  "session_id": "...",
  "parent_task_id": null,
  "comments": [
    { "id": "...", "author_role": "coder", "content": "...", "created_at": "..." }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

**PATCH /tasks/{task_id}**

Updatable fields: `status`, `title`, `description`. Status changes go through the state machine — invalid transitions return 422.

Request:
```json
{ "status": "in_review" }
```

**POST /tasks/{task_id}/comments**

Request:
```json
{ "content": "string", "author_role": "human" }
```

#### Agent runs

```
GET /tasks/{task_id}/runs
```

Response:
```json
[
  {
    "id": "...",
    "phase": "coder",
    "started_at": "...",
    "completed_at": "...",
    "exit_code": 0,
    "error": null
  }
]
```

### State machine enforcement

The PATCH /tasks/{task_id} endpoint enforces valid transitions. Invalid transitions return:

```json
HTTP 422
{
  "detail": "Invalid transition: cannot move task from 'backlog' to 'in_review'. Valid next states: ['in_progress', 'cancelled']"
}
```

Transition logic lives in `db/state_machine.py` and is shared between the API and the MCP server.

### Websocket (`api/ws.py`)

Single websocket endpoint:

```
GET /ws
```

All connected clients receive all board events. No per-project filtering in this phase.

Event format:
```json
{
  "type": "task_updated | task_created | comment_added",
  "payload": { ...full updated object }
}
```

#### Event source

The websocket broadcaster polls the `events` table for unconsumed rows every 500ms, broadcasts them to all connected clients, and marks them consumed. This is the same `events` table the MCP server writes to in Phase 2.

```python
async def broadcast_events():
    while True:
        events = db.get_unconsumed_events()
        for event in events:
            await manager.broadcast(event.payload)
            db.mark_consumed(event.id)
        await asyncio.sleep(0.5)
```

A `ConnectionManager` class tracks active websocket connections.

### CLI update

`vibe-relay serve` now starts the actual FastAPI server:

```bash
vibe-relay serve --port 8000 --reload
```

Defaults: port 8000, no reload. `--reload` enables uvicorn's auto-reload for development.

---

## Acceptance criteria

- [x] `vibe-relay serve` starts uvicorn and accepts requests on port 8000
- [x] `POST /projects` creates a project and a root planner task, returns both
- [x] `GET /projects/{id}` returns project with task count by status
- [x] `GET /projects/{id}/tasks` returns tasks grouped by status column
- [x] `GET /tasks/{id}` returns task with full comment thread
- [x] `PATCH /tasks/{id}` with valid status transition updates the task
- [x] `PATCH /tasks/{id}` with invalid transition returns 422 with descriptive message
- [x] `POST /tasks/{id}/comments` adds a comment and returns it
- [x] `GET /tasks/{id}/runs` returns agent run history
- [x] `GET /ws` accepts websocket connection
- [x] When a task is updated (via API or MCP), connected websocket clients receive the event within 1 second
- [x] Websocket events include the full updated object, not just an ID
- [x] Manual test: open two browser tabs with a websocket client, update a task via curl, verify both tabs receive the event
- [x] Manual test: update a task via the MCP server directly, verify the websocket client receives the event (confirms the events table bridging works)

---

## Out of scope

- No UI
- No agent triggering
- No authentication
- No per-project websocket filtering