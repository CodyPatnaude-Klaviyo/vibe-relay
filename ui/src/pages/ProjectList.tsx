import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createProject, listProjects } from "../api/projects";
import { NewProjectModal } from "../components/NewProjectModal";

export function ProjectList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);

  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const createMutation = useMutation({
    mutationFn: ({ title, description }: { title: string; description: string }) =>
      createProject(title, description),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      setShowModal(false);
      navigate(`/projects/${data.project.id}`);
    },
  });

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "32px 24px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "32px",
        }}
      >
        <h1 style={{ fontSize: "24px", fontWeight: 700 }}>Projects</h1>
        <button
          onClick={() => setShowModal(true)}
          style={{
            padding: "8px 20px",
            background: "#3b82f6",
            color: "#fff",
            border: "none",
            borderRadius: "var(--badge-radius)",
            fontSize: "14px",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          New Project
        </button>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div style={{ color: "var(--text-muted)", textAlign: "center", padding: "48px 0" }}>
          Loading projects...
        </div>
      )}

      {/* Empty state */}
      {!isLoading && projects && projects.length === 0 && (
        <div
          style={{
            color: "var(--text-muted)",
            textAlign: "center",
            padding: "48px 0",
            fontSize: "15px",
            fontStyle: "italic",
          }}
        >
          No projects yet. Create one to get started.
        </div>
      )}

      {/* Project list */}
      {projects && projects.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {projects.map((project) => (
            <div
              key={project.id}
              onClick={() => navigate(`/projects/${project.id}`)}
              style={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border)",
                borderRadius: "var(--card-radius)",
                padding: "16px 20px",
                cursor: "pointer",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "var(--bg-surface)")}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  marginBottom: project.description ? "8px" : "0",
                }}
              >
                <span style={{ fontSize: "16px", fontWeight: 600 }}>{project.title}</span>
                <span
                  style={{
                    background: project.status === "active" ? "var(--status-done)22" : "var(--status-cancelled)22",
                    color: project.status === "active" ? "var(--status-done)" : "var(--status-cancelled)",
                    border: `1px solid ${project.status === "active" ? "var(--status-done)44" : "var(--status-cancelled)44"}`,
                    padding: "2px 8px",
                    borderRadius: "var(--badge-radius)",
                    fontSize: "11px",
                    fontWeight: 600,
                  }}
                >
                  {project.status}
                </span>
              </div>
              {project.description && (
                <div
                  style={{
                    fontSize: "13px",
                    color: "var(--text-muted)",
                    lineHeight: 1.5,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {project.description}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* New Project Modal */}
      {showModal && (
        <NewProjectModal
          onSubmit={(title, description) => createMutation.mutate({ title, description })}
          onClose={() => setShowModal(false)}
          isSubmitting={createMutation.isPending}
        />
      )}
    </div>
  );
}
