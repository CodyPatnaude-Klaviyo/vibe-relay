"""Tests for the vibe-relay REST API endpoints.

Covers project CRUD, task CRUD, comments, and agent run listing.
Uses httpx.AsyncClient with ASGITransport for async FastAPI testing.
"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from db.migrations import init_db


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.close()
    return path


@pytest_asyncio.fixture()
async def client(db_path: str) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=db_path)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


async def _create_project(
    client: AsyncClient,
    title: str = "Test Project",
    description: str = "A test project",
) -> dict:
    """Helper to create a project and return the full response body."""
    resp = await client.post(
        "/projects", json={"title": title, "description": description}
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_task(
    client: AsyncClient,
    project_id: str,
    title: str = "Test Task",
    phase: str = "coder",
    description: str = "",
    parent_task_id: str | None = None,
) -> dict:
    """Helper to create a task and return the response body."""
    body: dict = {"title": title, "phase": phase, "description": description}
    if parent_task_id is not None:
        body["parent_task_id"] = parent_task_id
    resp = await client.post(f"/projects/{project_id}/tasks", json=body)
    assert resp.status_code == 201
    return resp.json()


# ── TestCreateProject ─────────────────────────────────────


class TestCreateProject:
    """POST /projects creates a project and root planner task."""

    @pytest.mark.asyncio
    async def test_create_project_returns_201(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/projects",
            json={"title": "My Project", "description": "desc"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_create_project_returns_project_and_task(
        self, client: AsyncClient
    ) -> None:
        data = await _create_project(client, title="My Project", description="desc")
        assert "project" in data
        assert "task" in data

    @pytest.mark.asyncio
    async def test_project_has_expected_fields(self, client: AsyncClient) -> None:
        data = await _create_project(client, title="My Project", description="desc")
        project = data["project"]
        assert project["title"] == "My Project"
        assert project["description"] == "desc"
        assert project["status"] == "active"
        assert "id" in project
        assert "created_at" in project
        assert "updated_at" in project

    @pytest.mark.asyncio
    async def test_root_task_is_planner_phase(self, client: AsyncClient) -> None:
        data = await _create_project(client, title="My Project")
        task = data["task"]
        assert task["phase"] == "planner"
        assert task["status"] == "backlog"
        assert task["title"].startswith("Plan:")

    @pytest.mark.asyncio
    async def test_root_task_belongs_to_project(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project = data["project"]
        task = data["task"]
        assert task["project_id"] == project["id"]

    @pytest.mark.asyncio
    async def test_create_project_default_description(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post("/projects", json={"title": "Minimal"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"]["description"] == ""


# ── TestListProjects ──────────────────────────────────────


class TestListProjects:
    """GET /projects lists all projects."""

    @pytest.mark.asyncio
    async def test_empty_list(self, client: AsyncClient) -> None:
        resp = await client.get("/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_lists_created_projects(self, client: AsyncClient) -> None:
        await _create_project(client, title="Alpha")
        await _create_project(client, title="Beta")

        resp = await client.get("/projects")
        assert resp.status_code == 200
        projects = resp.json()
        assert len(projects) == 2
        titles = {p["title"] for p in projects}
        assert titles == {"Alpha", "Beta"}

    @pytest.mark.asyncio
    async def test_list_projects_ordered_desc_by_created_at(
        self, client: AsyncClient
    ) -> None:
        await _create_project(client, title="First")
        await _create_project(client, title="Second")

        resp = await client.get("/projects")
        projects = resp.json()
        # Most recent first
        assert projects[0]["title"] == "Second"
        assert projects[1]["title"] == "First"


# ── TestGetProject ────────────────────────────────────────


class TestGetProject:
    """GET /projects/{id} returns project with task counts."""

    @pytest.mark.asyncio
    async def test_get_project_with_task_counts(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.get(f"/projects/{project_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == project_id
        assert "tasks" in body
        # Root planner task is in backlog
        assert body["tasks"]["backlog"] == 1

    @pytest.mark.asyncio
    async def test_get_project_404(self, client: AsyncClient) -> None:
        resp = await client.get("/projects/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_task_counts_all_statuses_present(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.get(f"/projects/{project_id}")
        body = resp.json()
        tasks = body["tasks"]
        expected_statuses = {"backlog", "in_progress", "in_review", "done", "cancelled"}
        assert set(tasks.keys()) == expected_statuses


# ── TestDeleteProject ─────────────────────────────────────


class TestDeleteProject:
    """DELETE /projects/{id} cancels a project."""

    @pytest.mark.asyncio
    async def test_delete_project_cancels(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.delete(f"/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_deleted_project_shows_cancelled(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        await client.delete(f"/projects/{project_id}")

        resp = await client.get(f"/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/projects/nonexistent-id")
        assert resp.status_code == 404


# ── TestCreateTask ────────────────────────────────────────


class TestCreateTask:
    """POST /projects/{id}/tasks creates a task."""

    @pytest.mark.asyncio
    async def test_create_task_returns_201(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "Write code", "phase": "coder"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_created_task_has_expected_fields(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        task = await _create_task(client, project_id, title="Write code", phase="coder")
        assert task["title"] == "Write code"
        assert task["phase"] == "coder"
        assert task["status"] == "backlog"
        assert task["project_id"] == project_id
        assert task["parent_task_id"] is None

    @pytest.mark.asyncio
    async def test_create_task_with_parent(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]
        root_task_id = data["task"]["id"]

        child = await _create_task(
            client,
            project_id,
            title="Child",
            phase="coder",
            parent_task_id=root_task_id,
        )
        assert child["parent_task_id"] == root_task_id

    @pytest.mark.asyncio
    async def test_create_task_invalid_phase_422(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "Bad", "phase": "invalid_phase"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_task_nonexistent_project_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/projects/nonexistent-id/tasks",
            json={"title": "Orphan", "phase": "coder"},
        )
        assert resp.status_code == 404


# ── TestListTasks ─────────────────────────────────────────


class TestListTasks:
    """GET /projects/{id}/tasks returns tasks grouped by status."""

    @pytest.mark.asyncio
    async def test_list_tasks_grouped_by_status(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.get(f"/projects/{project_id}/tasks")
        assert resp.status_code == 200
        body = resp.json()

        expected_statuses = {"backlog", "in_progress", "in_review", "done", "cancelled"}
        assert set(body.keys()) == expected_statuses

    @pytest.mark.asyncio
    async def test_root_task_in_backlog(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]
        root_task_id = data["task"]["id"]

        resp = await client.get(f"/projects/{project_id}/tasks")
        body = resp.json()

        backlog_ids = [t["id"] for t in body["backlog"]]
        assert root_task_id in backlog_ids

    @pytest.mark.asyncio
    async def test_list_tasks_nonexistent_project_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/projects/nonexistent-id/tasks")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_tasks_multiple_tasks(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        await _create_task(client, project_id, title="Task A", phase="coder")
        await _create_task(client, project_id, title="Task B", phase="reviewer")

        resp = await client.get(f"/projects/{project_id}/tasks")
        body = resp.json()
        # Root planner task + 2 new tasks = 3 in backlog
        assert len(body["backlog"]) == 3


# ── TestGetTask ───────────────────────────────────────────


class TestGetTask:
    """GET /tasks/{id} returns task with comments."""

    @pytest.mark.asyncio
    async def test_get_task_with_comments(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == task_id
        assert "comments" in body
        assert isinstance(body["comments"], list)

    @pytest.mark.asyncio
    async def test_get_task_404(self, client: AsyncClient) -> None:
        resp = await client.get("/tasks/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_task_includes_comment_thread(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        # Add a comment
        await client.post(
            f"/tasks/{task_id}/comments",
            json={"content": "Hello", "author_role": "human"},
        )

        resp = await client.get(f"/tasks/{task_id}")
        body = resp.json()
        assert len(body["comments"]) == 1
        assert body["comments"][0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_get_task_has_expected_fields(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.get(f"/tasks/{task_id}")
        body = resp.json()
        expected_keys = {
            "id",
            "project_id",
            "parent_task_id",
            "title",
            "description",
            "phase",
            "status",
            "branch",
            "worktree_path",
            "session_id",
            "created_at",
            "updated_at",
            "comments",
        }
        assert expected_keys.issubset(set(body.keys()))


# ── TestUpdateTask ────────────────────────────────────────


class TestUpdateTask:
    """PATCH /tasks/{id} updates status, title, or description."""

    @pytest.mark.asyncio
    async def test_valid_status_transition(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        # backlog -> in_progress is valid
        resp = await client.patch(f"/tasks/{task_id}", json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_invalid_status_transition_422(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        # backlog -> done is invalid
        resp = await client.patch(f"/tasks/{task_id}", json={"status": "done"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_title(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.patch(f"/tasks/{task_id}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    @pytest.mark.asyncio
    async def test_update_description(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.patch(
            f"/tasks/{task_id}", json={"description": "Updated desc"}
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated desc"

    @pytest.mark.asyncio
    async def test_update_status_and_title(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.patch(
            f"/tasks/{task_id}",
            json={"status": "in_progress", "title": "Active Task"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_progress"
        assert body["title"] == "Active Task"

    @pytest.mark.asyncio
    async def test_update_nonexistent_task_404(self, client: AsyncClient) -> None:
        resp = await client.patch("/tasks/nonexistent-id", json={"title": "Nope"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_chain_valid_transitions(self, client: AsyncClient) -> None:
        """Test a full lifecycle: backlog -> in_progress -> in_review -> done."""
        data = await _create_project(client)
        task_id = data["task"]["id"]

        for status in ["in_progress", "in_review", "done"]:
            resp = await client.patch(f"/tasks/{task_id}", json={"status": status})
            assert resp.status_code == 200
            assert resp.json()["status"] == status


# ── TestAddComment ────────────────────────────────────────


class TestAddComment:
    """POST /tasks/{id}/comments adds a comment."""

    @pytest.mark.asyncio
    async def test_add_comment_returns_201(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.post(
            f"/tasks/{task_id}/comments",
            json={"content": "Looks good", "author_role": "reviewer"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_comment_has_expected_fields(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.post(
            f"/tasks/{task_id}/comments",
            json={"content": "Test comment", "author_role": "human"},
        )
        body = resp.json()
        assert body["task_id"] == task_id
        assert body["content"] == "Test comment"
        assert body["author_role"] == "human"
        assert "id" in body
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_invalid_author_role_422(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.post(
            f"/tasks/{task_id}/comments",
            json={"content": "Bad role", "author_role": "alien"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_comment_on_nonexistent_task_404(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/tasks/nonexistent-id/comments",
            json={"content": "No task", "author_role": "human"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_all_valid_author_roles(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        for role in ["planner", "coder", "reviewer", "orchestrator", "human"]:
            resp = await client.post(
                f"/tasks/{task_id}/comments",
                json={"content": f"Comment by {role}", "author_role": role},
            )
            assert resp.status_code == 201, f"Failed for role: {role}"


# ── TestGetTaskRuns ───────────────────────────────────────


class TestGetTaskRuns:
    """GET /tasks/{id}/runs returns agent run history."""

    @pytest.mark.asyncio
    async def test_empty_runs(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.get(f"/tasks/{task_id}/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_runs_nonexistent_task_404(self, client: AsyncClient) -> None:
        resp = await client.get("/tasks/nonexistent-id/runs")
        assert resp.status_code == 404
