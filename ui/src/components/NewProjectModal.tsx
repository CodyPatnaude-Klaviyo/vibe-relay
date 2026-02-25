import { useEffect, useRef, useState } from "react";
import { getConfigDefaults, validateRepo } from "../api/projects";

interface NewProjectModalProps {
  onSubmit: (title: string, description: string, repoPath?: string | null, baseBranch?: string | null) => void;
  onClose: () => void;
  isSubmitting: boolean;
}

export function NewProjectModal({ onSubmit, onClose, isSubmitting }: NewProjectModalProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [baseBranch, setBaseBranch] = useState("");
  const [repoValid, setRepoValid] = useState<boolean | null>(null);
  const [repoValidating, setRepoValidating] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load config defaults on mount
  useEffect(() => {
    getConfigDefaults()
      .then((defaults) => {
        if (defaults.repo_path) setRepoPath(defaults.repo_path);
        if (defaults.base_branch) setBaseBranch(defaults.base_branch);
      })
      .catch(() => {
        // Config defaults unavailable — leave fields empty
      });
  }, []);

  // Debounced repo validation
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(() => {
      if (!repoPath.trim()) {
        setRepoValid(null);
        setRepoError(null);
        setRepoValidating(false);
        return;
      }

      setRepoValidating(true);
      validateRepo(repoPath.trim())
        .then((result) => {
          setRepoValid(result.valid);
          setRepoError(result.valid ? null : (result.error ?? "Invalid path"));
          if (result.valid && result.default_branch) {
            setBaseBranch(result.default_branch);
          }
        })
        .catch(() => {
          setRepoValid(false);
          setRepoError("Validation request failed");
        })
        .finally(() => setRepoValidating(false));
    }, 500);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [repoPath]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;
    onSubmit(
      trimmedTitle,
      description.trim(),
      repoPath.trim() || null,
      baseBranch.trim() || null,
    );
  }

  function handleBackdropClick(e: React.MouseEvent) {
    if (e.target === e.currentTarget) {
      onClose();
    }
  }

  const isSubmitDisabled = isSubmitting || !title.trim() || repoValid === false;

  const labelStyle: React.CSSProperties = {
    display: "block",
    fontSize: "12px",
    fontWeight: 600,
    color: "var(--text-muted)",
    marginBottom: "6px",
    textTransform: "uppercase",
    letterSpacing: "0.3px",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    background: "var(--bg)",
    border: "1px solid var(--border)",
    borderRadius: "var(--badge-radius)",
    color: "var(--text)",
    padding: "10px 12px",
    fontSize: "14px",
    fontFamily: "inherit",
    outline: "none",
    transition: "border-color 0.2s ease, box-shadow 0.2s ease",
  };

  function handleFocus(e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) {
    e.currentTarget.style.borderColor = "var(--agent-active)";
    e.currentTarget.style.boxShadow = "0 0 8px rgba(59,130,246,0.15)";
  }

  function handleBlur(e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) {
    e.currentTarget.style.borderColor = "var(--border)";
    e.currentTarget.style.boxShadow = "none";
  }

  return (
    <div
      onClick={handleBackdropClick}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.75)",
        backdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 20,
      }}
    >
      <div
        style={{
          background: "var(--bg-elevated)",
          border: "1px solid var(--glass-border)",
          borderRadius: "16px",
          padding: "28px",
          width: "480px",
          maxWidth: "90vw",
          boxShadow: "0 0 40px rgba(59,130,246,0.08), 0 16px 48px rgba(0,0,0,0.5)",
        }}
      >
        <h2 style={{ fontSize: "18px", fontWeight: 600, marginBottom: "20px" }}>
          New Project
        </h2>

        <form onSubmit={handleSubmit}>
          {/* Title */}
          <div style={{ marginBottom: "16px" }}>
            <label htmlFor="project-title" style={labelStyle}>
              Title
            </label>
            <input
              id="project-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Project title"
              autoFocus
              style={inputStyle}
              onFocus={handleFocus}
              onBlur={handleBlur}
            />
          </div>

          {/* Repository */}
          <div style={{ marginBottom: "16px" }}>
            <label htmlFor="project-repo" style={labelStyle}>
              Repository
            </label>
            <div style={{ position: "relative" }}>
              <input
                id="project-repo"
                type="text"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder="/path/to/git/repo"
                style={{
                  ...inputStyle,
                  paddingRight: "36px",
                  borderColor:
                    repoValid === true
                      ? "rgba(34,197,94,0.5)"
                      : repoValid === false
                        ? "rgba(239,68,68,0.5)"
                        : "var(--border)",
                }}
                onFocus={handleFocus}
                onBlur={handleBlur}
              />
              {/* Validation indicator */}
              {repoPath.trim() && (
                <span
                  style={{
                    position: "absolute",
                    right: "10px",
                    top: "50%",
                    transform: "translateY(-50%)",
                    fontSize: "16px",
                    lineHeight: 1,
                  }}
                >
                  {repoValidating
                    ? "\u2026"
                    : repoValid === true
                      ? "\u2713"
                      : repoValid === false
                        ? "\u2717"
                        : ""}
                </span>
              )}
            </div>
            {repoError && (
              <div
                style={{
                  fontSize: "11px",
                  color: "var(--status-cancelled)",
                  marginTop: "4px",
                }}
              >
                {repoError}
              </div>
            )}
          </div>

          {/* Base Branch */}
          <div style={{ marginBottom: "16px" }}>
            <label htmlFor="project-branch" style={labelStyle}>
              Base Branch
            </label>
            <input
              id="project-branch"
              type="text"
              value={baseBranch}
              onChange={(e) => setBaseBranch(e.target.value)}
              placeholder="main"
              style={inputStyle}
              onFocus={handleFocus}
              onBlur={handleBlur}
            />
          </div>

          {/* Description */}
          <div style={{ marginBottom: "20px" }}>
            <label htmlFor="project-description" style={labelStyle}>
              Description
            </label>
            <textarea
              id="project-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this project should build..."
              rows={4}
              style={{
                ...inputStyle,
                resize: "vertical" as const,
              }}
              onFocus={handleFocus}
              onBlur={handleBlur}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              style={{
                padding: "8px 16px",
                background: "var(--glass-bg)",
                color: "var(--text)",
                border: "1px solid var(--glass-border)",
                borderRadius: "var(--badge-radius)",
                fontSize: "13px",
                fontWeight: 500,
                cursor: isSubmitting ? "not-allowed" : "pointer",
                backdropFilter: "blur(4px)",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitDisabled}
              style={{
                padding: "8px 16px",
                background: isSubmitDisabled ? "var(--border)" : "var(--phase-coder)",
                color: "#fff",
                border: "none",
                borderRadius: "var(--badge-radius)",
                fontSize: "13px",
                fontWeight: 600,
                cursor: isSubmitDisabled ? "not-allowed" : "pointer",
                boxShadow: isSubmitDisabled ? "none" : "0 0 12px rgba(59,130,246,0.25)",
                transition: "box-shadow 0.2s ease",
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
