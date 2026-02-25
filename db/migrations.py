"""Schema creation and migration logic for vibe-relay.

Migrations are idempotent — running them multiple times has no effect
because all CREATE TABLE statements use IF NOT EXISTS.

Can be run directly:
    python -m db.migrations [db_path]
"""

import sqlite3
import sys
from pathlib import Path

from db.client import get_connection
from db.schema import TABLE_CREATION_ORDER, TABLES


def run_migrations(conn: sqlite3.Connection) -> None:
    """Create all tables in dependency order. Idempotent."""
    for table_name in TABLE_CREATION_ORDER:
        conn.execute(TABLES[table_name])
    conn.commit()

    # Add trigger_consumed column to events if it doesn't exist (Phase 6)
    try:
        conn.execute(
            "ALTER TABLE events ADD COLUMN trigger_consumed INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection, run migrations, and return the ready connection."""
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn


def main() -> None:
    """CLI entry point for running migrations directly."""
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "vibe-relay.db"

    print(f"Running migrations on {db_path}...")
    conn = init_db(db_path)

    # Verify WAL mode
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"Journal mode: {journal_mode}")

    # Verify tables
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print(f"Tables created: {[t[0] for t in tables]}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
