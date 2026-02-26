import type { Task } from "../types";
import { StepBadge } from "./StepBadge";
import { useBoardStore } from "../store/boardStore";

function StatusBadge({ label, color }: { label: string; color: string }) {
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  return (
    <span
      style={{
        fontSize: "10px",
        fontWeight: 600,
        padding: "2px 7px",
        borderRadius: "var(--badge-radius)",
        background: `rgba(${r}, ${g}, ${b}, 0.12)`,
        color: color,
        border: `1px solid rgba(${r}, ${g}, ${b}, 0.25)`,
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        textTransform: "uppercase",
        letterSpacing: "0.3px",
      }}
    >
      {label}
    </span>
  );
}

function RunningDot() {
  return (
    <span
      style={{
        width: "6px",
        height: "6px",
        borderRadius: "50%",
        background: "var(--agent-active)",
        display: "inline-block",
        boxShadow: "0 0 6px var(--agent-active)",
      }}
    />
  );
}

interface CardState {
  borderLeft: string | undefined;
  className: string;
  opacity: number;
  filter: string | undefined;
}

function getCardState(task: Task, isBlocked: boolean): CardState {
  if (task.cancelled) {
    return {
      borderLeft: undefined,
      className: "task-card",
      opacity: 0.35,
      filter: "grayscale(0.8)",
    };
  }
  if (isBlocked) {
    return {
      borderLeft: undefined,
      className: "task-card",
      opacity: 0.5,
      filter: undefined,
    };
  }
  if (task.has_active_run) {
    return {
      borderLeft: "3px solid var(--agent-active)",
      className: "task-card task-card--agent-active",
      opacity: 1,
      filter: undefined,
    };
  }
  if (task.type === "milestone" && !task.plan_approved) {
    return {
      borderLeft: "3px solid var(--needs-attention)",
      className: "task-card task-card--needs-attention",
      opacity: 1,
      filter: undefined,
    };
  }
  if (task.type === "milestone" && task.plan_approved) {
    return {
      borderLeft: "3px solid #22c55e",
      className: "task-card",
      opacity: 1,
      filter: undefined,
    };
  }
  return {
    borderLeft: undefined,
    className: "task-card",
    opacity: 1,
    filter: undefined,
  };
}

export function TaskCard({ task, isBlocked }: { task: Task; isBlocked?: boolean }) {
  const selectTask = useBoardStore((s) => s.selectTask);
  const state = getCardState(task, isBlocked ?? false);

  return (
    <div
      className={state.className}
      onClick={() => selectTask(task.id)}
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--glass-border)",
        borderLeft: state.borderLeft,
        borderRadius: "var(--card-radius)",
        padding: "12px",
        cursor: "pointer",
        marginBottom: "8px",
        opacity: state.opacity,
        filter: state.filter,
        boxShadow: "0 2px 8px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.03)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--bg-hover)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "var(--bg-surface)";
      }}
    >
      <div style={{ marginBottom: "8px", fontWeight: 500, fontSize: "13px", lineHeight: 1.4 }}>
        {task.title}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
        <StepBadge name={task.step_name} position={task.step_position} />

        {task.has_active_run && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
            <RunningDot />
            <StatusBadge label="Running" color="#3b82f6" />
          </span>
        )}

        {!task.has_active_run && task.type === "milestone" && !task.plan_approved && !task.cancelled && (
          <StatusBadge label="Needs Approval" color="#f59e0b" />
        )}

        {task.type === "milestone" && task.plan_approved && (
          <StatusBadge label="Approved" color="#22c55e" />
        )}

        {isBlocked && !task.cancelled && (
          <StatusBadge label="Blocked" color="#6b7280" />
        )}

        {task.type === "research" && task.step_name.toLowerCase() !== "research" && (
          <StatusBadge label="Research" color="#3b82f6" />
        )}

        {task.type === "research" && task.output && (
          <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>has output</span>
        )}

        {task.branch && (
          <span
            style={{
              fontSize: "10px",
              color: "var(--text-dim)",
              maxWidth: "120px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              fontFamily: "monospace",
            }}
          >
            {task.branch}
          </span>
        )}
      </div>
    </div>
  );
}
