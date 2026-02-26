import type { Project, ProjectDetail, WorkflowStep } from "../types";
import { apiFetch } from "./client";

export function listProjects(): Promise<Project[]> {
  return apiFetch("/projects");
}

export function getProject(id: string): Promise<ProjectDetail> {
  return apiFetch(`/projects/${id}`);
}

export function createProject(
  title: string,
  description: string,
  repoPath?: string | null,
  baseBranch?: string | null,
): Promise<{ project: Project }> {
  return apiFetch("/projects", {
    method: "POST",
    body: JSON.stringify({
      title,
      description,
      repo_path: repoPath || undefined,
      base_branch: baseBranch || undefined,
    }),
  });
}

export function deleteProject(id: string): Promise<void> {
  return apiFetch(`/projects/${id}`, { method: "DELETE" });
}

export function listProjectSteps(projectId: string): Promise<WorkflowStep[]> {
  return apiFetch(`/projects/${projectId}/steps`);
}

export interface ConfigDefaults {
  repo_path: string | null;
  base_branch: string | null;
}

export function getConfigDefaults(): Promise<ConfigDefaults> {
  return apiFetch("/config/defaults");
}

export interface RepoValidation {
  valid: boolean;
  repo_path?: string;
  default_branch?: string;
  error?: string;
}

export function validateRepo(path: string): Promise<RepoValidation> {
  return apiFetch(`/repos/validate?path=${encodeURIComponent(path)}`);
}

export interface StepPrompt {
  step_id: string;
  step_name: string;
  system_prompt: string;
  system_prompt_file: string | null;
}

export function getStepPrompt(projectId: string, stepId: string): Promise<StepPrompt> {
  return apiFetch(`/projects/${projectId}/steps/${stepId}/prompt`);
}

export function updateStepPrompt(
  projectId: string,
  stepId: string,
  systemPrompt: string,
): Promise<{ step_id: string; step_name: string; system_prompt: string }> {
  return apiFetch(`/projects/${projectId}/steps/${stepId}/prompt`, {
    method: "PUT",
    body: JSON.stringify({ system_prompt: systemPrompt }),
  });
}
