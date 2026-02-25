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
    mutationFn: ({
      title,
      description,
      repoPath,
      baseBranch,
    }: {
      title: string;
      description: string;
      repoPath?: string | null;
      baseBranch?: string | null;
    }) => createProject(title, description, repoPath, baseBranch),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      setShowModal(false);
      navigate(`/projects/${data.project.id}`);
    },
  });

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "40px 24px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "36px",
        }}
      >
        <h1 style={{ fontSize: "28px", fontWeight: 700, letterSpacing: "-0.5px" }}>Projects</h1>
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
            boxShadow: "0 0 12px rgba(59,130,246,0.25)",
            transition: "box-shadow 0.2s ease, transform 0.15s ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow = "0 0 20px rgba(59,130,246,0.4)";
            e.currentTarget.style.transform = "translateY(-1px)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = "0 0 12px rgba(59,130,246,0.25)";
            e.currentTarget.style.transform = "translateY(0)";
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
            color: "var(--text-dim)",
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
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          {projects.map((project) => (
            <div
              key={project.id}
              onClick={() => navigate(`/projects/${project.id}`)}
              style={{
                background: "var(--bg-surface)",
                border: "1px solid var(--glass-border)",
                borderRadius: "var(--card-radius)",
                padding: "16px 20px",
                cursor: "pointer",
                boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
                transition: "transform 0.15s ease, box-shadow 0.2s ease, border-color 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = "translateY(-2px)";
                e.currentTarget.style.boxShadow = "0 6px 20px rgba(0,0,0,0.25)";
                e.currentTarget.style.borderColor = "rgba(59,130,246,0.15)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = "translateY(0)";
                e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.15)";
                e.currentTarget.style.borderColor = "var(--glass-border)";
              }}
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
                    background: project.status === "active" ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)",
                    color: project.status === "active" ? "var(--status-done)" : "var(--status-cancelled)",
                    border: `1px solid ${project.status === "active" ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`,
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
          onSubmit={(title, description, repoPath, baseBranch) =>
            createMutation.mutate({ title, description, repoPath, baseBranch })
          }
          onClose={() => setShowModal(false)}
          isSubmitting={createMutation.isPending}
        />
      )}
    </div>
  );
}
