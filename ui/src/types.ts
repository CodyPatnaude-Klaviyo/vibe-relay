export type TaskType = "task" | "research" | "milestone";

export interface Project {
  id: string;
  title: string;
  description: string | null;
  repo_path: string | null;
  base_branch: string | null;
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
  type: TaskType;
  plan_approved: boolean;
  has_active_run: boolean;
  output: string | null;
  branch: string | null;
  worktree_path: string | null;
  session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DependencyInfo {
  predecessors: DependencyEntry[];
  successors: DependencyEntry[];
}

export interface DependencyEntry {
  dependency_id: string;
  predecessor_id?: string;
  successor_id?: string;
  title: string;
  step_name: string;
  step_position: number;
}

export interface TaskDetail extends Task {
  comments: Comment[];
  dependencies?: DependencyInfo;
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

export interface Dependency {
  id: string;
  predecessor_id: string;
  successor_id: string;
}

export interface WebSocketEvent {
  type:
    | "task_created"
    | "task_moved"
    | "task_cancelled"
    | "task_uncancelled"
    | "task_updated"
    | "comment_added"
    | "project_created"
    | "project_updated"
    | "plan_approved"
    | "task_ready"
    | "milestone_completed"
    | "subtasks_created"
    | "dependency_created"
    | "dependency_removed";
  payload: Record<string, unknown>;
}

export interface BoardData {
  steps: WorkflowStep[];
  tasks: Record<string, Task[]>;
  cancelled: Task[];
  dependencies?: Dependency[];
}

export type TasksByStep = Record<string, Task[]>;
