import { useState } from "react";
import type { Comment } from "../types";
import { StepBadge } from "./StepBadge";

interface CommentThreadProps {
  comments: Comment[];
  onAddComment: (content: string) => void;
  isSubmitting: boolean;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function CommentThread({ comments, onAddComment, isSubmitting }: CommentThreadProps) {
  const [content, setContent] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = content.trim();
    if (!trimmed) return;
    onAddComment(trimmed);
    setContent("");
  }

  return (
    <div style={{ marginTop: "24px" }}>
      <h4
        style={{
          fontSize: "11px",
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.5px",
          color: "var(--text-muted)",
          marginBottom: "12px",
          paddingLeft: "10px",
          borderLeft: "2px solid var(--phase-reviewer)",
        }}
      >
        Comments
      </h4>

      {comments.length === 0 ? (
        <div
          style={{
            color: "var(--text-dim)",
            fontSize: "12px",
            fontStyle: "italic",
            padding: "12px 0",
          }}
        >
          No comments yet.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginBottom: "16px" }}>
          {comments.map((comment) => (
            <div
              key={comment.id}
              style={{
                background: "var(--glass-bg)",
                border: "1px solid var(--glass-border)",
                borderRadius: "var(--card-radius)",
                padding: "10px 12px",
                backdropFilter: "blur(4px)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  marginBottom: "6px",
                }}
              >
                <StepBadge name={comment.author_role} />
                <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>
                  {formatTimestamp(comment.created_at)}
                </span>
              </div>
              <div style={{ fontSize: "13px", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                {comment.content}
              </div>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} style={{ marginTop: "12px" }}>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Add a comment..."
          rows={3}
          style={{
            width: "100%",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: "var(--card-radius)",
            color: "var(--text)",
            padding: "10px 12px",
            fontSize: "13px",
            fontFamily: "inherit",
            resize: "vertical",
            outline: "none",
            transition: "border-color 0.2s ease, box-shadow 0.2s ease",
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = "var(--agent-active)";
            e.currentTarget.style.boxShadow = "0 0 8px rgba(59,130,246,0.15)";
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = "var(--border)";
            e.currentTarget.style.boxShadow = "none";
          }}
        />
        <button
          type="submit"
          disabled={isSubmitting || !content.trim()}
          style={{
            marginTop: "8px",
            padding: "6px 16px",
            background: isSubmitting || !content.trim() ? "var(--border)" : "var(--phase-coder)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--badge-radius)",
            fontSize: "13px",
            fontWeight: 600,
            cursor: isSubmitting || !content.trim() ? "not-allowed" : "pointer",
            transition: "box-shadow 0.2s ease",
          }}
          onMouseEnter={(e) => {
            if (!isSubmitting && content.trim()) {
              e.currentTarget.style.boxShadow = "0 0 12px rgba(59,130,246,0.3)";
            }
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = "none";
          }}
        >
          {isSubmitting ? "Posting..." : "Post Comment"}
        </button>
      </form>
    </div>
  );
}
