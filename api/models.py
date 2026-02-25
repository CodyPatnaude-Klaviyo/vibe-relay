"""Pydantic request/response models for the vibe-relay API."""

from pydantic import BaseModel


# ── Request models ──────────────────────────────────────


class CreateProjectRequest(BaseModel):
    title: str
    description: str = ""


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    phase: str
    parent_task_id: str | None = None


class UpdateTaskRequest(BaseModel):
    status: str | None = None
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


class TaskResponse(BaseModel):
    id: str
    project_id: str
    parent_task_id: str | None = None
    title: str
    description: str | None = None
    phase: str
    status: str
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
    phase: str
    started_at: str
    completed_at: str | None = None
    exit_code: int | None = None
    error: str | None = None


class WebSocketEvent(BaseModel):
    type: str
    payload: dict
