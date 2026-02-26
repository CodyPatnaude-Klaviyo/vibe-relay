import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { getStepPrompt, updateStepPrompt } from "../api/projects";

interface Props {
  projectId: string;
  stepId: string;
  stepName: string;
  onClose: () => void;
}

export function PromptEditor({ projectId, stepId, stepName, onClose }: Props) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["stepPrompt", projectId, stepId],
    queryFn: () => getStepPrompt(projectId, stepId),
  });

  useEffect(() => {
    if (data?.system_prompt != null) {
      setDraft(data.system_prompt);
    }
  }, [data?.system_prompt]);

  const saveMutation = useMutation({
    mutationFn: () => updateStepPrompt(projectId, stepId, draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stepPrompt", projectId, stepId] });
      onClose();
    },
  });

  const isDirty = draft !== (data?.system_prompt ?? "");

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          background: "var(--glass-bg)",
          border: "1px solid var(--glass-border)",
          borderRadius: "var(--card-radius)",
          width: "720px",
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
          backdropFilter: "blur(12px)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--glass-border)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: "15px", color: "var(--text)" }}>
              Edit Prompt: {stepName}
            </h3>
            {data?.system_prompt_file && (
              <div style={{ fontSize: "11px", color: "var(--text-dim)", marginTop: "4px" }}>
                Source file: {data.system_prompt_file}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              fontSize: "18px",
              cursor: "pointer",
              padding: "4px 8px",
            }}
          >
            ×
          </button>
        </div>

        {/* Editor */}
        <div style={{ padding: "16px 20px", flex: 1, overflow: "auto" }}>
          {isLoading ? (
            <div style={{ color: "var(--text-dim)", fontSize: "13px" }}>Loading...</div>
          ) : (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              style={{
                width: "100%",
                minHeight: "400px",
                background: "#0d1117",
                color: "var(--text)",
                border: "1px solid var(--glass-border)",
                borderRadius: "var(--badge-radius)",
                padding: "12px",
                fontFamily: "monospace",
                fontSize: "12px",
                lineHeight: 1.6,
                resize: "vertical",
                outline: "none",
              }}
            />
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "12px 20px",
            borderTop: "1px solid var(--glass-border)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>
            {draft.length.toLocaleString()} characters
          </span>
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              onClick={onClose}
              style={{
                padding: "6px 14px",
                background: "var(--glass-bg)",
                color: "var(--text-muted)",
                border: "1px solid var(--glass-border)",
                borderRadius: "var(--badge-radius)",
                fontSize: "12px",
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!isDirty || saveMutation.isPending}
              style={{
                padding: "6px 14px",
                background: isDirty ? "var(--agent-active)" : "var(--border)",
                color: isDirty ? "#fff" : "var(--text-dim)",
                border: "none",
                borderRadius: "var(--badge-radius)",
                fontSize: "12px",
                fontWeight: 600,
                cursor: isDirty ? "pointer" : "not-allowed",
              }}
            >
              {saveMutation.isPending ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
