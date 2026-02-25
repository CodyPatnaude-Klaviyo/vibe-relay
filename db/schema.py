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
    "tasks": """
        CREATE TABLE IF NOT EXISTS tasks (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(id),
            parent_task_id  TEXT REFERENCES tasks(id),
            title           TEXT NOT NULL,
            description     TEXT,
            phase           TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'backlog',
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
            phase        TEXT NOT NULL,
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
}

# Ordered list for creation — respects foreign key dependencies
TABLE_CREATION_ORDER = ["projects", "tasks", "comments", "agent_runs", "ports"]
