import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addComment, getTask, getTaskRuns, updateTask } from "../api/tasks";
import { listProjectSteps } from "../api/projects";
import { useBoardStore } from "../store/boardStore";
import type { WorkflowStep } from "../types";
import { CommentThread } from "./CommentThread";
import { StepBadge } from "./StepBadge";

function formatDuration(started: string, completed: string | null): string {
  if (!completed) return "running...";
  const ms = new Date(completed).getTime() - new Date(started).getTime();
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getValidTargetSteps(steps: WorkflowStep[], currentPosition: number): WorkflowStep[] {
  return steps.filter((s) => {
    // Next step (forward by 1)
    if (s.position === currentPosition + 1) return true;
    // Any previous step (backward)
    if (s.position < currentPosition) return true;
    return false;
  });
}

export function TaskDetail({ taskId }: { taskId: string }) {
  const selectTask = useBoardStore((s) => s.selectTask);
  const eventVersion = useBoardStore((s) => s.eventVersion);
  const queryClient = useQueryClient();

  const { data: task, isLoading: taskLoading } = useQuery({
    queryKey: ["task", taskId, eventVersion],
    queryFn: () => getTask(taskId),
  });

  const { data: runs } = useQuery({
    queryKey: ["runs", taskId, eventVersion],
    queryFn: () => getTaskRuns(taskId),
  });

  const { data: steps } = useQuery({
    queryKey: ["steps", task?.project_id, eventVersion],
    queryFn: () => listProjectSteps(task!.project_id),
    enabled: !!task?.project_id,
  });

  const moveMutation = useMutation({
    mutationFn: (targetStepId: string) => updateTask(taskId, { step_id: targetStepId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["board"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (cancelled: boolean) => updateTask(taskId, { cancelled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["board"] });
    },
  });

  const commentMutation = useMutation({
    mutationFn: (content: string) => addComment(taskId, content),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    },
  });

  if (taskLoading || !task) {
    return (
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          width: "420px",
          height: "100vh",
          background: "var(--bg-surface)",
          borderLeft: "1px solid var(--border)",
          padding: "24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-muted)",
          zIndex: 10,
        }}
      >
        Loading...
      </div>
    );
  }

  const validTargets = steps ? getValidTargetSteps(steps, task.step_position) : [];
  const isMutating = moveMutation.isPending || cancelMutation.isPending;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: "420px",
        height: "100vh",
        background: "var(--bg-surface)",
        borderLeft: "1px solid var(--border)",
        overflowY: "auto",
        zIndex: 10,
      }}
    >
      <div style={{ padding: "24px" }}>
        {/* Close button */}
        <button
          onClick={() => selectTask(null)}
          style={{
            position: "absolute",
            top: "16px",
            right: "16px",
            background: "none",
            border: "none",
            color: "var(--text-muted)",
            fontSize: "20px",
            cursor: "pointer",
            padding: "4px 8px",
            borderRadius: "var(--badge-radius)",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
        >
          ✕
        </button>

        {/* Title */}
        <h2 style={{ fontSize: "18px", fontWeight: 600, marginBottom: "12px", paddingRight: "32px" }}>
          {task.title}
        </h2>

        {/* Badge */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
          <StepBadge name={task.step_name} position={task.step_position} />
          {task.cancelled && (
            <span
              style={{
                background: "var(--status-cancelled)22",
                color: "var(--status-cancelled)",
                border: "1px solid var(--status-cancelled)44",
                padding: "2px 8px",
                borderRadius: "var(--badge-radius)",
                fontSize: "11px",
                fontWeight: 600,
              }}
            >
              Cancelled
            </span>
          )}
        </div>

        {/* Description */}
        {task.description && (
          <div
            style={{
              fontSize: "13px",
              lineHeight: 1.6,
              color: "var(--text)",
              marginBottom: "16px",
              whiteSpace: "pre-wrap",
            }}
          >
            {task.description}
          </div>
        )}

        {/* Metadata */}
        <div style={{ marginBottom: "16px" }}>
          {task.branch && (
            <div style={{ fontSize: "12px", marginBottom: "6px" }}>
              <span style={{ color: "var(--text-muted)" }}>Branch: </span>
              <code
                style={{
                  fontFamily: "monospace",
                  background: "var(--bg)",
                  padding: "2px 6px",
                  borderRadius: "var(--badge-radius)",
                  fontSize: "11px",
                }}
              >
                {task.branch}
              </code>
            </div>
          )}
          {task.worktree_path && (
            <div style={{ fontSize: "12px", marginBottom: "6px" }}>
              <span style={{ color: "var(--text-muted)" }}>Worktree: </span>
              <code
                style={{
                  fontFamily: "monospace",
                  background: "var(--bg)",
                  padding: "2px 6px",
                  borderRadius: "var(--badge-radius)",
                  fontSize: "11px",
                  wordBreak: "break-all",
                }}
              >
                {task.worktree_path}
              </code>
            </div>
          )}
        </div>

        {/* Step movement buttons */}
        {!task.cancelled && validTargets.length > 0 && (
          <div style={{ marginBottom: "20px" }}>
            <h4
              style={{
                fontSize: "13px",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                color: "var(--text-muted)",
                marginBottom: "8px",
              }}
            >
              Move to
            </h4>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {validTargets.map((target) => (
                <button
                  key={target.id}
                  onClick={() => moveMutation.mutate(target.id)}
                  disabled={isMutating}
                  style={{
                    padding: "6px 14px",
                    background: isMutating ? "var(--border)" : "var(--bg)",
                    color: "var(--text)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--badge-radius)",
                    fontSize: "13px",
                    fontWeight: 500,
                    cursor: isMutating ? "not-allowed" : "pointer",
                  }}
                  onMouseEnter={(e) => {
                    if (!isMutating) e.currentTarget.style.background = "var(--bg-hover)";
                  }}
                  onMouseLeave={(e) => {
                    if (!isMutating) e.currentTarget.style.background = "var(--bg)";
                  }}
                >
                  {target.position > task.step_position ? `→ ${target.name}` : `← ${target.name}`}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Cancel / Uncancel button */}
        <div style={{ marginBottom: "20px" }}>
          <button
            onClick={() => cancelMutation.mutate(!task.cancelled)}
            disabled={isMutating}
            style={{
              padding: "6px 14px",
              background: isMutating ? "var(--border)" : "var(--bg)",
              color: task.cancelled ? "var(--text)" : "var(--status-cancelled)",
              border: `1px solid ${task.cancelled ? "var(--border)" : "var(--status-cancelled)44"}`,
              borderRadius: "var(--badge-radius)",
              fontSize: "13px",
              fontWeight: 500,
              cursor: isMutating ? "not-allowed" : "pointer",
            }}
          >
            {task.cancelled ? "Uncancel" : "Cancel"}
          </button>
        </div>

        {/* Comments */}
        <CommentThread
          comments={task.comments}
          onAddComment={(content) => commentMutation.mutate(content)}
          isSubmitting={commentMutation.isPending}
        />

        {/* Agent Runs */}
        {runs && runs.length > 0 && (
          <div style={{ marginTop: "24px" }}>
            <h4
              style={{
                fontSize: "13px",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                color: "var(--text-muted)",
                marginBottom: "12px",
              }}
            >
              Agent Runs
            </h4>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {runs.map((run) => (
                <div
                  key={run.id}
                  style={{
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--card-radius)",
                    padding: "10px 12px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      marginBottom: "4px",
                    }}
                  >
                    <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
                      {formatTimestamp(run.started_at)}
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "12px",
                      fontSize: "12px",
                    }}
                  >
                    <span style={{ color: "var(--text-muted)" }}>
                      Duration: {formatDuration(run.started_at, run.completed_at)}
                    </span>
                    {run.exit_code !== null && (
                      <span
                        style={{
                          color: run.exit_code === 0 ? "var(--status-done)" : "var(--status-cancelled)",
                        }}
                      >
                        Exit: {run.exit_code}
                      </span>
                    )}
                  </div>
                  {run.error && (
                    <div
                      style={{
                        marginTop: "6px",
                        fontSize: "12px",
                        color: "var(--status-cancelled)",
                        fontFamily: "monospace",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-all",
                      }}
                    >
                      {run.error}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
