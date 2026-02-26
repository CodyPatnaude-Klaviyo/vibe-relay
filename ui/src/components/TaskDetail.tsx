import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addComment, approvePlan, getTask, getTaskRuns, updateTask } from "../api/tasks";
import { listProjectSteps } from "../api/projects";
import { useBoardStore } from "../store/boardStore";
import type { WorkflowStep } from "../types";
import { AgentLogViewer } from "./AgentLogViewer";
import { CommentThread } from "./CommentThread";
import { StepBadge } from "./StepBadge";
import { STEP_PALETTE, withAlpha } from "../utils/colors";

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
    if (s.position === currentPosition + 1) return true;
    if (s.position < currentPosition) return true;
    return false;
  });
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h4
      style={{
        fontSize: "11px",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
        color: "var(--text-muted)",
        marginBottom: "10px",
        paddingLeft: "10px",
        borderLeft: "2px solid var(--agent-active)",
      }}
    >
      {children}
    </h4>
  );
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

  const approveMutation = useMutation({
    mutationFn: () => approvePlan(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["board"] });
    },
  });

  if (taskLoading || !task) {
    return (
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          width: "440px",
          height: "100vh",
          background: "var(--bg-elevated)",
          backdropFilter: "blur(20px)",
          borderLeft: "1px solid var(--glass-border)",
          boxShadow: "-8px 0 32px rgba(0,0,0,0.4)",
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
  const isMutating = moveMutation.isPending || cancelMutation.isPending || approveMutation.isPending;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: "440px",
        height: "100vh",
        background: "var(--bg-elevated)",
        backdropFilter: "blur(20px)",
        borderLeft: "1px solid var(--glass-border)",
        boxShadow: "-8px 0 32px rgba(0,0,0,0.4)",
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
            border: "1px solid transparent",
            color: "var(--text-muted)",
            fontSize: "18px",
            cursor: "pointer",
            padding: "4px 8px",
            borderRadius: "var(--badge-radius)",
            transition: "all 0.15s ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "var(--text)";
            e.currentTarget.style.borderColor = "var(--border)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "var(--text-muted)";
            e.currentTarget.style.borderColor = "transparent";
          }}
        >
          ✕
        </button>

        {/* Title */}
        <h2 style={{ fontSize: "17px", fontWeight: 600, marginBottom: "12px", paddingRight: "32px", lineHeight: 1.4 }}>
          {task.title}
        </h2>

        {/* Badge row */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
          <StepBadge name={task.step_name} position={task.step_position} />
          {task.type !== "task" && (
            <span
              style={{
                fontSize: "11px",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "var(--badge-radius)",
                background:
                  task.type === "milestone"
                    ? "rgba(168,85,247,0.12)"
                    : "rgba(59,130,246,0.12)",
                color: task.type === "milestone" ? "#a855f7" : "#3b82f6",
                border: `1px solid ${task.type === "milestone" ? "rgba(168,85,247,0.25)" : "rgba(59,130,246,0.25)"}`,
              }}
            >
              {task.type === "milestone" ? "Milestone" : "Research"}
            </span>
          )}
          {task.type === "milestone" && task.plan_approved && (
            <span
              style={{
                fontSize: "11px",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "var(--badge-radius)",
                background: "rgba(34,197,94,0.12)",
                color: "var(--status-done)",
                border: "1px solid rgba(34,197,94,0.25)",
              }}
            >
              Approved
            </span>
          )}
          {task.cancelled && (
            <span
              style={{
                background: "rgba(239,68,68,0.12)",
                color: "var(--status-cancelled)",
                border: "1px solid rgba(239,68,68,0.25)",
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

        {/* Approve Plan button */}
        {task.type === "milestone" && !task.plan_approved && !task.cancelled && (
          <div style={{ marginBottom: "16px" }}>
            <button
              onClick={() => approveMutation.mutate()}
              disabled={isMutating}
              style={{
                padding: "8px 20px",
                background: isMutating ? "var(--border)" : "#22c55e",
                color: "#fff",
                border: "none",
                borderRadius: "var(--badge-radius)",
                fontSize: "13px",
                fontWeight: 600,
                cursor: isMutating ? "not-allowed" : "pointer",
                boxShadow: isMutating ? "none" : "0 0 12px rgba(34,197,94,0.3)",
                transition: "box-shadow 0.2s ease",
              }}
              onMouseEnter={(e) => {
                if (!isMutating) e.currentTarget.style.boxShadow = "0 0 20px rgba(34,197,94,0.5)";
              }}
              onMouseLeave={(e) => {
                if (!isMutating) e.currentTarget.style.boxShadow = "0 0 12px rgba(34,197,94,0.3)";
              }}
            >
              {approveMutation.isPending ? "Approving..." : "Approve Plan"}
            </button>
            {approveMutation.isError && (
              <div style={{ color: "var(--status-cancelled)", fontSize: "12px", marginTop: "4px" }}>
                Failed to approve. Milestone needs at least one child task.
              </div>
            )}
          </div>
        )}

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

        {/* Output field (research tasks) */}
        {task.output && (
          <div style={{ marginBottom: "16px" }}>
            <SectionHeader>Output</SectionHeader>
            <div
              style={{
                background: "var(--bg)",
                border: "1px solid var(--glass-border)",
                borderRadius: "var(--card-radius)",
                padding: "12px",
                fontSize: "13px",
                lineHeight: 1.6,
                whiteSpace: "pre-wrap",
                maxHeight: "200px",
                overflowY: "auto",
              }}
            >
              {task.output}
            </div>
          </div>
        )}

        {/* Dependencies */}
        {task.dependencies && (task.dependencies.predecessors.length > 0 || task.dependencies.successors.length > 0) && (
          <div style={{ marginBottom: "16px" }}>
            <SectionHeader>Dependencies</SectionHeader>
            {task.dependencies.predecessors.length > 0 && (
              <div style={{ marginBottom: "8px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-dim)", marginBottom: "4px" }}>
                  Blocked by:
                </div>
                {task.dependencies.predecessors.map((dep) => (
                  <div
                    key={dep.dependency_id}
                    onClick={() => dep.predecessor_id && selectTask(dep.predecessor_id)}
                    style={{
                      fontSize: "12px",
                      padding: "6px 8px",
                      background: "var(--bg)",
                      border: "1px solid var(--glass-border)",
                      borderRadius: "var(--badge-radius)",
                      marginBottom: "4px",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      transition: "box-shadow 0.15s ease, border-color 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.boxShadow = "0 0 8px rgba(59,130,246,0.15)";
                      e.currentTarget.style.borderColor = "rgba(59,130,246,0.2)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.boxShadow = "none";
                      e.currentTarget.style.borderColor = "var(--glass-border)";
                    }}
                  >
                    <StepBadge name={dep.step_name} position={dep.step_position} />
                    <span>{dep.title}</span>
                  </div>
                ))}
              </div>
            )}
            {task.dependencies.successors.length > 0 && (
              <div>
                <div style={{ fontSize: "11px", color: "var(--text-dim)", marginBottom: "4px" }}>
                  Blocks:
                </div>
                {task.dependencies.successors.map((dep) => (
                  <div
                    key={dep.dependency_id}
                    onClick={() => dep.successor_id && selectTask(dep.successor_id)}
                    style={{
                      fontSize: "12px",
                      padding: "6px 8px",
                      background: "var(--bg)",
                      border: "1px solid var(--glass-border)",
                      borderRadius: "var(--badge-radius)",
                      marginBottom: "4px",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      transition: "box-shadow 0.15s ease, border-color 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.boxShadow = "0 0 8px rgba(59,130,246,0.15)";
                      e.currentTarget.style.borderColor = "rgba(59,130,246,0.2)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.boxShadow = "none";
                      e.currentTarget.style.borderColor = "var(--glass-border)";
                    }}
                  >
                    <StepBadge name={dep.step_name} position={dep.step_position} />
                    <span>{dep.title}</span>
                  </div>
                ))}
              </div>
            )}
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
                  border: "1px solid var(--glass-border)",
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
                  border: "1px solid var(--glass-border)",
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
            <SectionHeader>Move to</SectionHeader>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {validTargets.map((target) => {
                const targetColor = target.color ?? STEP_PALETTE[target.position % STEP_PALETTE.length];
                return (
                  <button
                    key={target.id}
                    onClick={() => moveMutation.mutate(target.id)}
                    disabled={isMutating}
                    style={{
                      padding: "6px 14px",
                      background: isMutating ? "var(--border)" : "var(--glass-bg)",
                      color: "var(--text)",
                      border: "1px solid var(--glass-border)",
                      borderRadius: "var(--badge-radius)",
                      fontSize: "13px",
                      fontWeight: 500,
                      cursor: isMutating ? "not-allowed" : "pointer",
                      backdropFilter: "blur(4px)",
                      transition: "box-shadow 0.2s ease, border-color 0.2s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (!isMutating) {
                        e.currentTarget.style.boxShadow = `0 0 12px ${withAlpha(targetColor, 0.3)}`;
                        e.currentTarget.style.borderColor = withAlpha(targetColor, 0.4);
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isMutating) {
                        e.currentTarget.style.boxShadow = "none";
                        e.currentTarget.style.borderColor = "var(--glass-border)";
                      }
                    }}
                  >
                    {target.position > task.step_position ? `→ ${target.name}` : `← ${target.name}`}
                  </button>
                );
              })}
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
              background: isMutating ? "var(--border)" : "var(--glass-bg)",
              color: task.cancelled ? "var(--text)" : "var(--status-cancelled)",
              border: `1px solid ${task.cancelled ? "var(--glass-border)" : "rgba(239,68,68,0.25)"}`,
              borderRadius: "var(--badge-radius)",
              fontSize: "13px",
              fontWeight: 500,
              cursor: isMutating ? "not-allowed" : "pointer",
              backdropFilter: "blur(4px)",
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
            <SectionHeader>Agent Runs</SectionHeader>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {runs.map((run) => {
                const isRunning = !run.completed_at;
                const isSuccess = run.exit_code === 0;
                const isFailed = run.exit_code !== null && run.exit_code !== 0;
                const accentColor = isRunning ? "var(--agent-active)" : isSuccess ? "var(--status-done)" : isFailed ? "var(--status-cancelled)" : "var(--border)";
                return (
                  <div
                    key={run.id}
                    style={{
                      background: "var(--bg)",
                      border: "1px solid var(--glass-border)",
                      borderLeft: `3px solid ${accentColor}`,
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
                );
              })}
            </div>
          </div>
        )}

        {/* Agent Transcript Viewer */}
        {task.session_id && (
          <AgentLogViewer
            taskId={taskId}
            isRunning={runs?.some((r) => !r.completed_at) ?? false}
          />
        )}
      </div>
    </div>
  );
}
