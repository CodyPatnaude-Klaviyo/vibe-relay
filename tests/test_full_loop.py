"""Full loop smoke test for vibe-relay.

This test requires a running vibe-relay server with trigger processor enabled,
and a valid Claude API key. It is NOT part of the regular test suite.

Run manually:
    VIBE_RELAY_SMOKE=1 VIBE_RELAY_URL=http://localhost:8000 uv run pytest tests/test_full_loop.py -v -s

The test:
1. Creates a project via the API
2. Waits for the planner agent to create subtasks
3. Monitors task status changes
4. Manually approves tasks moving to done (to avoid needing real PRs)
5. Verifies the orchestrator fires when all siblings complete
"""

import os
import time

import httpx
import pytest

BASE_URL = os.environ.get("VIBE_RELAY_URL", "http://localhost:8000")

pytestmark = pytest.mark.skipif(
    "VIBE_RELAY_SMOKE" not in os.environ,
    reason="Set VIBE_RELAY_SMOKE=1 to run full loop smoke test",
)


def _get(path: str) -> dict:
    resp = httpx.get(f"{BASE_URL}{path}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> dict:
    resp = httpx.post(f"{BASE_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _patch(path: str, body: dict) -> dict:
    resp = httpx.patch(f"{BASE_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _wait_for(predicate, description: str, timeout: int = 300, interval: int = 5):
    """Poll until predicate returns truthy, or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        result = predicate()
        if result:
            return result
        print(f"  Waiting for {description}... ({int(time.time() - start)}s)")
        time.sleep(interval)
    msg = f"Timed out waiting for {description} after {timeout}s"
    raise TimeoutError(msg)


class TestFullLoop:
    def test_autonomous_loop(self):
        """End-to-end: create project -> planner -> coders -> orchestrator."""
        # 1. Create project
        print("\n[1] Creating project...")
        data = _post(
            "/projects",
            {
                "title": "Smoke Test Project",
                "description": (
                    "A simple test project. Create a single Python function "
                    "that adds two numbers and a test for it."
                ),
            },
        )
        project_id = data["project"]["id"]
        planner_task_id = data["task"]["id"]
        print(f"  Project: {project_id}")
        print(f"  Planner task: {planner_task_id} (status: {data['task']['status']})")

        # 2. Wait for planner to create subtasks
        print("\n[2] Waiting for planner to create subtasks...")

        def has_subtasks():
            tasks = _get(f"/projects/{project_id}/tasks")
            all_tasks = []
            for status_tasks in tasks.values():
                all_tasks.extend(status_tasks)
            non_planner = [t for t in all_tasks if t["phase"] != "planner"]
            return non_planner if len(non_planner) > 0 else None

        subtasks = _wait_for(has_subtasks, "planner to create subtasks")
        print(f"  Planner created {len(subtasks)} subtasks")
        for t in subtasks:
            print(f"    - {t['title']} ({t['phase']}, {t['status']})")

        # 3. Wait for coder tasks to reach in_review or done
        print("\n[3] Waiting for coder tasks to complete...")
        coder_tasks = [t for t in subtasks if t["phase"] == "coder"]

        def coders_in_review_or_done():
            tasks = _get(f"/projects/{project_id}/tasks")
            in_review = tasks.get("in_review", [])
            done = tasks.get("done", [])
            completed_coders = [t for t in in_review + done if t["phase"] == "coder"]
            return (
                completed_coders if len(completed_coders) >= len(coder_tasks) else None
            )

        _wait_for(
            coders_in_review_or_done,
            "all coder tasks to reach in_review/done",
            timeout=600,
        )
        print("  All coder tasks reached in_review or done")

        # 4. Approve all in_review tasks (move to done)
        print("\n[4] Approving in_review tasks...")
        tasks = _get(f"/projects/{project_id}/tasks")
        for t in tasks.get("in_review", []):
            print(f"  Approving: {t['title']}")
            _patch(f"/tasks/{t['id']}", {"status": "done"})

        # 5. Check for orchestrator task
        print("\n[5] Waiting for orchestrator task...")

        def has_orchestrator():
            tasks = _get(f"/projects/{project_id}/tasks")
            all_tasks = []
            for status_tasks in tasks.values():
                all_tasks.extend(status_tasks)
            orch = [t for t in all_tasks if t["phase"] == "orchestrator"]
            return orch if len(orch) > 0 else None

        orch_tasks = _wait_for(
            has_orchestrator, "orchestrator task creation", timeout=30
        )
        print(
            f"  Orchestrator task created: {orch_tasks[0]['id']} "
            f"(status: {orch_tasks[0]['status']})"
        )

        print("\n[PASS] Full loop smoke test completed successfully!")
