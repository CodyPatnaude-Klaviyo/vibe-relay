"""Database table definitions for vibe-relay.

Uses raw SQL strings matching the canonical schema from ARCHITECTURE.md.
SQLModel is available for future ORM usage, but the schema is defined
as raw DDL to keep migrations simple and explicit.
"""

TABLES = {
    "projects": """
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            description TEXT,
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """,
    "workflow_steps": """
        CREATE TABLE IF NOT EXISTS workflow_steps (
            id            TEXT PRIMARY KEY,
            project_id    TEXT NOT NULL REFERENCES projects(id),
            name          TEXT NOT NULL,
            position      INTEGER NOT NULL,
            system_prompt TEXT,
            model         TEXT,
            color         TEXT,
            created_at    TEXT NOT NULL,
            UNIQUE(project_id, position),
            UNIQUE(project_id, name)
        )
    """,
    "tasks": """
        CREATE TABLE IF NOT EXISTS tasks (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(id),
            parent_task_id  TEXT REFERENCES tasks(id),
            title           TEXT NOT NULL,
            description     TEXT,
            step_id         TEXT NOT NULL REFERENCES workflow_steps(id),
            cancelled       INTEGER NOT NULL DEFAULT 0,
            worktree_path   TEXT,
            branch          TEXT,
            session_id      TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """,
    "comments": """
        CREATE TABLE IF NOT EXISTS comments (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL REFERENCES tasks(id),
            author_role TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """,
    "agent_runs": """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id           TEXT PRIMARY KEY,
            task_id      TEXT NOT NULL REFERENCES tasks(id),
            step_id      TEXT NOT NULL REFERENCES workflow_steps(id),
            started_at   TEXT NOT NULL,
            completed_at TEXT,
            exit_code    INTEGER,
            error        TEXT
        )
    """,
    "ports": """
        CREATE TABLE IF NOT EXISTS ports (
            port         INTEGER PRIMARY KEY,
            task_id      TEXT NOT NULL REFERENCES tasks(id),
            allocated_at TEXT NOT NULL
        )
    """,
    "events": """
        CREATE TABLE IF NOT EXISTS events (
            id                TEXT PRIMARY KEY,
            type              TEXT NOT NULL,
            payload           TEXT NOT NULL,
            created_at        TEXT NOT NULL,
            consumed          INTEGER NOT NULL DEFAULT 0,
            trigger_consumed  INTEGER NOT NULL DEFAULT 0
        )
    """,
}

# Ordered list for creation — respects foreign key dependencies
TABLE_CREATION_ORDER = [
    "projects",
    "workflow_steps",
    "tasks",
    "comments",
    "agent_runs",
    "ports",
    "events",
]
