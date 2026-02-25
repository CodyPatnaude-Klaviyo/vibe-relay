"""Seed a test project and task for manual testing of `vibe-relay run-agent`.

Usage:
    uv run python scripts/seed_test_task.py
"""

from pathlib import Path

from db.migrations import init_db
from vibe_relay.mcp.tools import create_project, create_task, update_task_status

DB_PATH = Path("~/.vibe-relay/vibe-relay.db").expanduser()


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(DB_PATH)

    project = create_project(conn, "Test Project", "A project for manual testing")
    print(f"Created project: {project['id']}")

    task = create_task(
        conn,
        title="Add a hello-world endpoint",
        description="Create a simple /hello endpoint that returns {'message': 'Hello, world!'}",
        phase="coder",
        project_id=project["id"],
    )
    print(f"Created task:    {task['id']}  (status: {task['status']})")

    # Move to in_progress so run-agent accepts it
    updated = update_task_status(conn, task["id"], "in_progress")
    print(f"Updated status:  {updated['status']}")

    conn.close()

    print()
    print("Run the agent with:")
    print(f"  uv run vibe-relay run-agent --task-id {task['id']}")


if __name__ == "__main__":
    main()
