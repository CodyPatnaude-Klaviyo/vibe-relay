import type { Task } from "../types";
import { StepBadge } from "./StepBadge";
import { useBoardStore } from "../store/boardStore";

export function TaskCard({ task }: { task: Task }) {
  const selectTask = useBoardStore((s) => s.selectTask);

  return (
    <div
      className="task-card"
      onClick={() => selectTask(task.id)}
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--card-radius)",
        padding: "12px",
        cursor: "pointer",
        marginBottom: "8px",
        opacity: task.cancelled ? 0.5 : 1,
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
