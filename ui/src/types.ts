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

export interface WorkflowStep {
  id: string;
  name: string;
  position: number;
  has_agent: boolean;
  model: string | null;
  color: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  parent_task_id: string | null;
  title: string;
  description: string | null;
  step_id: string;
  step_name: string;
  step_position: number;
  cancelled: boolean;
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
  step_id: string;
  started_at: string;
  completed_at: string | null;
  exit_code: number | null;
  error: string | null;
}

export interface WebSocketEvent {
  type: "task_created" | "task_moved" | "task_cancelled" | "task_uncancelled" | "comment_added" | "project_created" | "project_updated";
  payload: Record<string, unknown>;
}

export interface BoardData {
  steps: WorkflowStep[];
  tasks: Record<string, Task[]>;
  cancelled: Task[];
}

export type TasksByStep = Record<string, Task[]>;
