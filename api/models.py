"""Pydantic request/response models for the vibe-relay API."""

from pydantic import BaseModel


# ── Request models ──────────────────────────────────────


class WorkflowStepInput(BaseModel):
    name: str
    system_prompt: str | None = None
    system_prompt_file: str | None = None
    model: str | None = None
    color: str | None = None


class CreateProjectRequest(BaseModel):
    title: str
    description: str = ""
    workflow_steps: list[WorkflowStepInput] | None = None


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    step_id: str
    parent_task_id: str | None = None


class UpdateTaskRequest(BaseModel):
    step_id: str | None = None
    cancelled: bool | None = None
    title: str | None = None
    description: str | None = None


class CreateCommentRequest(BaseModel):
    content: str
    author_role: str


# ── Response models ─────────────────────────────────────


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str
    created_at: str
    updated_at: str


class ProjectDetailResponse(ProjectResponse):
    tasks: dict[str, int]


class WorkflowStepResponse(BaseModel):
    id: str
    name: str
    position: int
    has_agent: bool
    model: str | None = None
    color: str | None = None


class TaskResponse(BaseModel):
    id: str
    project_id: str
    parent_task_id: str | None = None
    title: str
    description: str | None = None
    step_id: str
    step_name: str
    step_position: int
    cancelled: bool
    branch: str | None = None
    worktree_path: str | None = None
    session_id: str | None = None
    created_at: str
    updated_at: str


class TaskDetailResponse(TaskResponse):
    comments: list[dict]


class CommentResponse(BaseModel):
    id: str
    task_id: str
    author_role: str
    content: str
    created_at: str


class AgentRunResponse(BaseModel):
    id: str
    step_id: str
    started_at: str
    completed_at: str | None = None
    exit_code: int | None = None
    error: str | None = None


class WebSocketEvent(BaseModel):
    type: str
    payload: dict
