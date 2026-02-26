import type { AgentRun, BoardData, Comment, DependencyInfo, Task, TaskDetail } from "../types";
import { apiFetch } from "./client";

export function listProjectTasks(projectId: string): Promise<BoardData> {
  return apiFetch(`/projects/${projectId}/tasks`);
}

export function getTask(taskId: string): Promise<TaskDetail> {
  return apiFetch(`/tasks/${taskId}`);
}

export function updateTask(
  taskId: string,
  updates: { step_id?: string; cancelled?: boolean; title?: string; description?: string; output?: string }
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

export function approvePlan(taskId: string): Promise<TaskDetail> {
  return apiFetch(`/tasks/${taskId}/approve`, {
    method: "POST",
  });
}

export function getTaskDependencies(taskId: string): Promise<DependencyInfo> {
  return apiFetch(`/tasks/${taskId}/dependencies`);
}

export function addDependency(predecessorId: string, successorId: string): Promise<void> {
  return apiFetch(`/tasks/${predecessorId}/dependencies`, {
    method: "POST",
    body: JSON.stringify({ predecessor_id: predecessorId, successor_id: successorId }),
  });
}

export function removeDependency(dependencyId: string): Promise<void> {
  return apiFetch(`/dependencies/${dependencyId}`, {
    method: "DELETE",
  });
}

export interface LogLine {
  index: number;
  type: "assistant" | "tool_use" | "tool_result" | "system";
  content?: string;
  tool?: string;
}

export interface LogsResponse {
  lines: LogLine[];
  offset: number;
  status: "running" | "completed" | "no_session" | "no_worktree" | "transcript_not_found" | "read_error";
}

export function getAgentLogs(taskId: string, offset: number = 0): Promise<LogsResponse> {
  return apiFetch(`/tasks/${taskId}/logs?offset=${offset}`);
}
