import type { Project, ProjectDetail } from "../types";
import { apiFetch } from "./client";

export function listProjects(): Promise<Project[]> {
  return apiFetch("/projects");
}

export function getProject(id: string): Promise<ProjectDetail> {
  return apiFetch(`/projects/${id}`);
}

export function createProject(title: string, description: string): Promise<{ project: Project }> {
  return apiFetch("/projects", {
    method: "POST",
    body: JSON.stringify({ title, description }),
  });
}

export function deleteProject(id: string): Promise<void> {
  return apiFetch(`/projects/${id}`, { method: "DELETE" });
}
