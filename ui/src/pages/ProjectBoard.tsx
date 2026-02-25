import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { getProject } from "../api/projects";
import { Board } from "../components/Board";
import { TaskDetail } from "../components/TaskDetail";
import { useBoard } from "../hooks/useBoard";
import { useWebSocket } from "../hooks/useWebSocket";
import { useBoardStore } from "../store/boardStore";

export function ProjectBoard() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const selectedTaskId = useBoardStore((s) => s.selectedTaskId);
  const wsConnected = useBoardStore((s) => s.wsConnected);

  useWebSocket();

  const { data: project } = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: !!id,
  });

  const { data: tasks, isLoading: tasksLoading } = useBoard(id!);

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          padding: "16px 24px",
          borderBottom: "1px solid var(--border)",
          height: "60px",
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => navigate("/")}
          style={{
            background: "none",
            border: "none",
            color: "var(--text-muted)",
            fontSize: "14px",
            cursor: "pointer",
            padding: "4px 8px",
            borderRadius: "var(--badge-radius)",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
        >
          &larr; Projects
        </button>
        <h1 style={{ fontSize: "18px", fontWeight: 600, flex: 1 }}>
          {project?.title ?? "Loading..."}
        </h1>
        <div
          title={wsConnected ? "WebSocket connected" : "WebSocket disconnected"}
          style={{
            width: "10px",
            height: "10px",
            borderRadius: "50%",
            background: wsConnected ? "var(--ws-connected)" : "var(--ws-disconnected)",
            flexShrink: 0,
          }}
        />
      </div>

      {/* Board area */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {tasksLoading || !tasks ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              color: "var(--text-muted)",
            }}
          >
            Loading tasks...
          </div>
        ) : (
          <Board tasks={tasks} />
        )}
      </div>

      {/* Task detail sidebar */}
      {selectedTaskId && <TaskDetail taskId={selectedTaskId} />}
    </div>
  );
}
