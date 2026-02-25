export interface Project {
  id: string;
  title: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  tasks: Record<string, number>;
}

export interface Task {
  id: string;
  project_id: string;
  parent_task_id: string | null;
  title: string;
  description: string | null;
  phase: string;
  status: string;
  branch: string | null;
  worktree_path: string | null;
  session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskDetail extends Task {
  comments: Comment[];
}

export interface Comment {
  id: string;
  task_id: string;
  author_role: string;
  content: string;
  created_at: string;
}

export interface AgentRun {
  id: string;
  phase: string;
  started_at: string;
  completed_at: string | null;
  exit_code: number | null;
  error: string | null;
}

export interface WebSocketEvent {
  type: "task_created" | "task_updated" | "comment_added" | "project_created" | "project_updated";
  payload: Record<string, unknown>;
}

export type TasksByStatus = Record<string, Task[]>;
export type TaskStatus = "backlog" | "in_progress" | "in_review" | "done" | "cancelled";
export type Phase = "planner" | "coder" | "reviewer" | "orchestrator";

export const TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  backlog: ["in_progress", "cancelled"],
  in_progress: ["in_review", "cancelled"],
  in_review: ["in_progress", "done", "cancelled"],
  done: [],
  cancelled: [],
};
