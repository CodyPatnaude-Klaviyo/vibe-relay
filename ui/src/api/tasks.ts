import type { AgentRun, BoardData, Comment, Task, TaskDetail } from "../types";
import { apiFetch } from "./client";

export function listProjectTasks(projectId: string): Promise<BoardData> {
  return apiFetch(`/projects/${projectId}/tasks`);
}

export function getTask(taskId: string): Promise<TaskDetail> {
  return apiFetch(`/tasks/${taskId}`);
}

export function updateTask(
  taskId: string,
  updates: { step_id?: string; cancelled?: boolean; title?: string; description?: string }
): Promise<TaskDetail> {
  return apiFetch(`/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function addComment(taskId: string, content: string): Promise<Comment> {
  return apiFetch(`/tasks/${taskId}/comments`, {
    method: "POST",
    body: JSON.stringify({ content, author_role: "human" }),
  });
}

export function getTaskRuns(taskId: string): Promise<AgentRun[]> {
  return apiFetch(`/tasks/${taskId}/runs`);
}

export function createTask(
  projectId: string,
  stepId: string,
  title: string,
  description?: string
): Promise<Task> {
  return apiFetch(`/projects/${projectId}/tasks`, {
    method: "POST",
    body: JSON.stringify({ title, description: description ?? "", step_id: stepId }),
  });
}
