import type { TaskStatus } from "../types";

const STATUS_COLORS: Record<TaskStatus, string> = {
  backlog: "var(--status-backlog)",
  in_progress: "var(--status-in-progress)",
  in_review: "var(--status-in-review)",
  done: "var(--status-done)",
  cancelled: "var(--status-cancelled)",
};

const STATUS_LABELS: Record<TaskStatus, string> = {
  backlog: "Backlog",
  in_progress: "In Progress",
  in_review: "In Review",
  done: "Done",
  cancelled: "Cancelled",
};

export function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status as TaskStatus] ?? "var(--text-muted)";
  const label = STATUS_LABELS[status as TaskStatus] ?? status;
  return (
    <span
      style={{
        background: `${color}22`,
        color,
        border: `1px solid ${color}44`,
        padding: "2px 8px",
        borderRadius: "var(--badge-radius)",
        fontSize: "11px",
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  );
}
