"""Tests for the vibe-relay REST API endpoints.

Covers project CRUD, task CRUD (step-based), comments, workflow steps,
and agent run listing. Uses httpx.AsyncClient with ASGITransport for
async FastAPI testing.
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


async def _get_steps(client: AsyncClient, project_id: str) -> list[dict]:
    """Helper to get project steps."""
    resp = await client.get(f"/projects/{project_id}/steps")
    assert resp.status_code == 200
    return resp.json()


async def _create_task(
    client: AsyncClient,
    project_id: str,
    title: str = "Test Task",
    step_id: str | None = None,
    description: str = "",
    parent_task_id: str | None = None,
) -> dict:
    """Helper to create a task and return the response body."""
    if step_id is None:
        steps = await _get_steps(client, project_id)
        step_id = steps[0]["id"]

    body: dict = {"title": title, "step_id": step_id, "description": description}
    if parent_task_id is not None:
        body["parent_task_id"] = parent_task_id
    resp = await client.post(f"/projects/{project_id}/tasks", json=body)
    assert resp.status_code == 201
    return resp.json()


# ── TestCreateProject ─────────────────────────────────────


class TestCreateProject:
    """POST /projects creates a project with workflow steps and root task."""

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
    async def test_root_task_at_first_step(self, client: AsyncClient) -> None:
        data = await _create_project(client, title="My Project")
        task = data["task"]
        assert task["title"].startswith("Plan:")
        # Should have step_id, step_name, cancelled
        assert "step_id" in task
        assert "step_name" in task
        assert task["cancelled"] is False

    @pytest.mark.asyncio
    async def test_root_task_belongs_to_project(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project = data["project"]
        task = data["task"]
        assert task["project_id"] == project["id"]

    @pytest.mark.asyncio
    async def test_creates_workflow_steps(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]
        steps = await _get_steps(client, project_id)
        # Default 10-step SDLC workflow
        assert len(steps) == 10
        assert steps[0]["name"] == "Scope"
        assert steps[9]["name"] == "Done"

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
    """GET /projects/{id} returns project with task counts by step."""

    @pytest.mark.asyncio
    async def test_get_project_with_task_counts(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.get(f"/projects/{project_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == project_id
        assert "tasks" in body
        # Should have step names as keys + cancelled
        assert "cancelled" in body["tasks"]

    @pytest.mark.asyncio
    async def test_get_project_404(self, client: AsyncClient) -> None:
        resp = await client.get("/projects/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_task_counts_include_step_names(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.get(f"/projects/{project_id}")
        body = resp.json()
        tasks = body["tasks"]
        # Should have step names from 10-step workflow
        assert "Scope" in tasks
        assert "Plan Review" in tasks
        assert "Research" in tasks
        assert "Spec" in tasks
        assert "Plan" in tasks
        assert "Implement" in tasks
        assert "Test" in tasks
        assert "Security" in tasks
        assert "Review" in tasks
        assert "Done" in tasks
        assert "cancelled" in tasks


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


# ── TestListProjectSteps ──────────────────────────────────


class TestListProjectSteps:
    """GET /projects/{id}/steps returns ordered workflow steps."""

    @pytest.mark.asyncio
    async def test_returns_steps(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        steps = await _get_steps(client, project_id)
        assert len(steps) == 10
        assert steps[0]["position"] == 0
        assert steps[9]["position"] == 9

    @pytest.mark.asyncio
    async def test_nonexistent_project_404(self, client: AsyncClient) -> None:
        resp = await client.get("/projects/nonexistent-id/steps")
        assert resp.status_code == 404


# ── TestCreateTask ────────────────────────────────────────


class TestCreateTask:
    """POST /projects/{id}/tasks creates a task at a workflow step."""

    @pytest.mark.asyncio
    async def test_create_task_returns_201(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]
        steps = await _get_steps(client, project_id)

        resp = await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "Write code", "step_id": steps[1]["id"]},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_created_task_has_expected_fields(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]
        steps = await _get_steps(client, project_id)

        task = await _create_task(
            client, project_id, title="Write code", step_id=steps[2]["id"]
        )
        assert task["title"] == "Write code"
        assert task["step_id"] == steps[2]["id"]
        assert task["step_name"] == "Plan"
        assert task["cancelled"] is False
        assert task["project_id"] == project_id
        assert task["parent_task_id"] is None
        assert task["type"] == "task"
        assert task["plan_approved"] is False

    @pytest.mark.asyncio
    async def test_create_task_with_parent(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]
        root_task_id = data["task"]["id"]
        steps = await _get_steps(client, project_id)

        child = await _create_task(
            client,
            project_id,
            title="Child",
            step_id=steps[1]["id"],
            parent_task_id=root_task_id,
        )
        assert child["parent_task_id"] == root_task_id

    @pytest.mark.asyncio
    async def test_create_task_nonexistent_step_404(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.post(
            f"/projects/{project_id}/tasks",
            json={"title": "Bad", "step_id": "nonexistent-step"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_task_nonexistent_project_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/projects/nonexistent-id/tasks",
            json={"title": "Orphan", "step_id": "some-step"},
        )
        assert resp.status_code == 404


# ── TestListTasks ─────────────────────────────────────────


class TestListTasks:
    """GET /projects/{id}/tasks returns tasks grouped by step."""

    @pytest.mark.asyncio
    async def test_list_tasks_grouped_by_step(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]

        resp = await client.get(f"/projects/{project_id}/tasks")
        assert resp.status_code == 200
        body = resp.json()

        assert "steps" in body
        assert "tasks" in body
        assert "cancelled" in body

    @pytest.mark.asyncio
    async def test_root_task_in_correct_step(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        project_id = data["project"]["id"]
        root_task_id = data["task"]["id"]
        root_step_id = data["task"]["step_id"]

        resp = await client.get(f"/projects/{project_id}/tasks")
        body = resp.json()

        task_ids = [t["id"] for t in body["tasks"].get(root_step_id, [])]
        assert root_task_id in task_ids

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
        steps = await _get_steps(client, project_id)

        await _create_task(client, project_id, title="Task A", step_id=steps[1]["id"])
        await _create_task(client, project_id, title="Task B", step_id=steps[2]["id"])

        resp = await client.get(f"/projects/{project_id}/tasks")
        body = resp.json()
        # Count total tasks across all steps
        total = sum(len(tasks) for tasks in body["tasks"].values())
        assert total == 3  # root + 2 new


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
            "step_id",
            "step_name",
            "step_position",
            "cancelled",
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
    """PATCH /tasks/{id} updates step, cancelled, title, or description."""

    @pytest.mark.asyncio
    async def test_move_task_to_next_step(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]
        project_id = data["project"]["id"]
        steps = await _get_steps(client, project_id)

        # Root task at first step, move to second
        resp = await client.patch(f"/tasks/{task_id}", json={"step_id": steps[1]["id"]})
        assert resp.status_code == 200
        assert resp.json()["step_id"] == steps[1]["id"]

    @pytest.mark.asyncio
    async def test_skip_step_422(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]
        project_id = data["project"]["id"]
        steps = await _get_steps(client, project_id)

        # Try to skip from first to third step
        resp = await client.patch(f"/tasks/{task_id}", json={"step_id": steps[2]["id"]})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cancel_task(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.patch(f"/tasks/{task_id}", json={"cancelled": True})
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True

    @pytest.mark.asyncio
    async def test_uncancel_task(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        await client.patch(f"/tasks/{task_id}", json={"cancelled": True})
        resp = await client.patch(f"/tasks/{task_id}", json={"cancelled": False})
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is False

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
    async def test_move_and_update_title(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]
        project_id = data["project"]["id"]
        steps = await _get_steps(client, project_id)

        resp = await client.patch(
            f"/tasks/{task_id}",
            json={"step_id": steps[1]["id"], "title": "Active Task"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["step_id"] == steps[1]["id"]
        assert body["title"] == "Active Task"

    @pytest.mark.asyncio
    async def test_update_nonexistent_task_404(self, client: AsyncClient) -> None:
        resp = await client.patch("/tasks/nonexistent-id", json={"title": "Nope"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, client: AsyncClient) -> None:
        """Test a full lifecycle: step 0 -> 1 -> 2 -> 3."""
        data = await _create_project(client)
        task_id = data["task"]["id"]
        project_id = data["project"]["id"]
        steps = await _get_steps(client, project_id)

        for step in steps[1:]:
            resp = await client.patch(f"/tasks/{task_id}", json={"step_id": step["id"]})
            assert resp.status_code == 200
            assert resp.json()["step_id"] == step["id"]


# ── TestAddComment ────────────────────────────────────────


class TestAddComment:
    """POST /tasks/{id}/comments adds a comment."""

    @pytest.mark.asyncio
    async def test_add_comment_returns_201(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.post(
            f"/tasks/{task_id}/comments",
            json={"content": "Looks good", "author_role": "Review"},
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
    async def test_empty_author_role_422(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        resp = await client.post(
            f"/tasks/{task_id}/comments",
            json={"content": "Bad role", "author_role": ""},
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
    async def test_any_author_role_accepted(self, client: AsyncClient) -> None:
        data = await _create_project(client)
        task_id = data["task"]["id"]

        for role in ["Plan", "Implement", "Review", "human", "custom_step"]:
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
