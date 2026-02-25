import type { TasksByStatus } from "../types";
import { TaskCard } from "./TaskCard";

const COLUMNS: { key: string; label: string }[] = [
  { key: "backlog", label: "Backlog" },
  { key: "in_progress", label: "In Progress" },
  { key: "in_review", label: "In Review" },
  { key: "done", label: "Done" },
];

export function Board({ tasks }: { tasks: TasksByStatus }) {
  return (
    <div
      style={{
        display: "flex",
        gap: "16px",
        padding: "16px",
        overflowX: "auto",
        height: "calc(100vh - 80px)",
      }}
    >
      {COLUMNS.map((col) => (
        <div
          key={col.key}
          style={{
            minWidth: "var(--column-width)",
            width: "var(--column-width)",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              padding: "8px 12px",
              fontWeight: 600,
              fontSize: "13px",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              color: "var(--text-muted)",
              marginBottom: "8px",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <span>{col.label}</span>
            <span>{(tasks[col.key] ?? []).length}</span>
          </div>
          <div style={{ flex: 1, overflowY: "auto" }}>
            {(tasks[col.key] ?? []).length === 0 ? (
              <div
                style={{
                  color: "var(--text-muted)",
                  fontSize: "13px",
                  padding: "16px",
                  textAlign: "center",
                  fontStyle: "italic",
                }}
              >
                Nothing here yet
              </div>
            ) : (
              (tasks[col.key] ?? []).map((task) => (
                <TaskCard key={task.id} task={task} />
              ))
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
