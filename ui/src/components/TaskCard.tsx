import type { Task } from "../types";
import { StepBadge } from "./StepBadge";
import { useBoardStore } from "../store/boardStore";

function TypeIndicator({ type, planApproved }: { type: string; planApproved: boolean }) {
  if (type === "milestone") {
    return (
      <span
        style={{
          fontSize: "11px",
          fontWeight: 600,
          padding: "1px 6px",
          borderRadius: "var(--badge-radius)",
          background: planApproved ? "rgba(34,197,94,0.15)" : "rgba(168,85,247,0.15)",
          color: planApproved ? "var(--status-done)" : "#a855f7",
          border: `1px solid ${planApproved ? "rgba(34,197,94,0.3)" : "rgba(168,85,247,0.3)"}`,
        }}
      >
        {planApproved ? "Approved" : "Milestone"}
      </span>
    );
  }
  if (type === "research") {
    return (
      <span
        style={{
          fontSize: "11px",
          fontWeight: 600,
          padding: "1px 6px",
          borderRadius: "var(--badge-radius)",
          background: "rgba(59,130,246,0.15)",
          color: "#3b82f6",
          border: "1px solid rgba(59,130,246,0.3)",
        }}
      >
        Research
      </span>
    );
  }
  return null;
}

export function TaskCard({ task, isBlocked }: { task: Task; isBlocked?: boolean }) {
  const selectTask = useBoardStore((s) => s.selectTask);

  const isMilestone = task.type === "milestone";
  const borderColor = isMilestone
    ? task.plan_approved
      ? "rgba(34,197,94,0.4)"
      : "rgba(168,85,247,0.4)"
    : "var(--border)";

  return (
    <div
      className="task-card"
      onClick={() => selectTask(task.id)}
      style={{
        background: "var(--bg-surface)",
        border: `1px solid ${borderColor}`,
        borderLeft: isMilestone ? `3px solid ${borderColor}` : undefined,
        borderRadius: "var(--card-radius)",
        padding: "12px",
        cursor: "pointer",
        marginBottom: "8px",
        opacity: task.cancelled ? 0.5 : isBlocked ? 0.6 : 1,
        textDecoration: task.cancelled ? "line-through" : "none",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "var(--bg-surface)")}
    >
      <div style={{ marginBottom: "8px", fontWeight: 500, fontSize: "14px" }}>
        {task.title}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
        <StepBadge name={task.step_name} position={task.step_position} />
        <TypeIndicator type={task.type} planApproved={task.plan_approved} />
        {isBlocked && (
          <span
            style={{
              fontSize: "11px",
              color: "var(--text-muted)",
              fontStyle: "italic",
            }}
          >
            blocked
          </span>
        )}
        {task.type === "research" && task.output && (
          <span
            style={{
              fontSize: "11px",
              color: "var(--text-muted)",
              maxWidth: "100px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            has output
          </span>
        )}
        {task.branch && (
          <span
            style={{
              fontSize: "11px",
              color: "var(--text-muted)",
              maxWidth: "140px",
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
