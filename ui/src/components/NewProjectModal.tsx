import { useState } from "react";

interface NewProjectModalProps {
  onSubmit: (title: string, description: string) => void;
  onClose: () => void;
  isSubmitting: boolean;
}

export function NewProjectModal({ onSubmit, onClose, isSubmitting }: NewProjectModalProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;
    onSubmit(trimmedTitle, description.trim());
  }

  function handleBackdropClick(e: React.MouseEvent) {
    if (e.target === e.currentTarget) {
      onClose();
    }
  }

  return (
    <div
      onClick={handleBackdropClick}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 20,
      }}
    >
      <div
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--card-radius)",
          padding: "24px",
          width: "480px",
          maxWidth: "90vw",
        }}
      >
        <h2 style={{ fontSize: "18px", fontWeight: 600, marginBottom: "20px" }}>
          New Project
        </h2>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: "16px" }}>
            <label
              htmlFor="project-title"
              style={{
                display: "block",
                fontSize: "13px",
                fontWeight: 600,
                color: "var(--text-muted)",
                marginBottom: "6px",
              }}
            >
              Title
            </label>
            <input
              id="project-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Project title"
              autoFocus
              style={{
                width: "100%",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--badge-radius)",
                color: "var(--text)",
                padding: "10px 12px",
                fontSize: "14px",
                fontFamily: "inherit",
              }}
            />
          </div>

          <div style={{ marginBottom: "20px" }}>
            <label
              htmlFor="project-description"
              style={{
                display: "block",
                fontSize: "13px",
                fontWeight: 600,
                color: "var(--text-muted)",
                marginBottom: "6px",
              }}
            >
              Description
            </label>
            <textarea
              id="project-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this project should build..."
              rows={4}
              style={{
                width: "100%",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--badge-radius)",
                color: "var(--text)",
                padding: "10px 12px",
                fontSize: "14px",
                fontFamily: "inherit",
                resize: "vertical",
              }}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              style={{
                padding: "8px 16px",
                background: "var(--bg)",
                color: "var(--text)",
                border: "1px solid var(--border)",
                borderRadius: "var(--badge-radius)",
                fontSize: "13px",
                fontWeight: 500,
                cursor: isSubmitting ? "not-allowed" : "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !title.trim()}
              style={{
                padding: "8px 16px",
                background: isSubmitting || !title.trim() ? "var(--border)" : "var(--phase-coder)",
                color: "#fff",
                border: "none",
                borderRadius: "var(--badge-radius)",
                fontSize: "13px",
                fontWeight: 600,
                cursor: isSubmitting || !title.trim() ? "not-allowed" : "pointer",
              }}
            >
              {isSubmitting ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
