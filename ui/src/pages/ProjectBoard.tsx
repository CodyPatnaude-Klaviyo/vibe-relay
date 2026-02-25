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

  const { data: boardData, isLoading: tasksLoading } = useBoard(id!);

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          padding: "14px 24px",
          background: "var(--glass-bg)",
          backdropFilter: "blur(12px)",
          borderBottom: "1px solid var(--glass-border)",
          boxShadow: "0 2px 12px rgba(0,0,0,0.2)",
          height: "60px",
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => navigate("/")}
          style={{
            background: "none",
            border: "1px solid transparent",
            color: "var(--text-muted)",
            fontSize: "14px",
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
          &larr; Projects
        </button>
        <h1 style={{ fontSize: "17px", fontWeight: 600, flex: 1, letterSpacing: "-0.2px" }}>
          {project?.title ?? "Loading..."}
        </h1>
        <div
          title={wsConnected ? "WebSocket connected" : "WebSocket disconnected"}
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            background: wsConnected ? "var(--ws-connected)" : "var(--ws-disconnected)",
            boxShadow: wsConnected ? "0 0 8px var(--ws-connected)" : "none",
            flexShrink: 0,
            transition: "background 0.3s ease, box-shadow 0.3s ease",
          }}
        />
      </div>

      {/* Board area */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {tasksLoading || !boardData ? (
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
          <Board data={boardData} projectId={id!} />
        )}
      </div>

      {/* Task detail sidebar */}
      {selectedTaskId && <TaskDetail taskId={selectedTaskId} />}
    </div>
  );
}
