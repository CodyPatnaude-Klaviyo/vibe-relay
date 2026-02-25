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
          fontSize: "13px",
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.5px",
          color: "var(--text-muted)",
          marginBottom: "12px",
        }}
      >
        Comments
      </h4>

      {comments.length === 0 ? (
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: "13px",
            fontStyle: "italic",
            padding: "12px 0",
          }}
        >
          No comments yet.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "16px" }}>
          {comments.map((comment) => (
            <div
              key={comment.id}
              style={{
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--card-radius)",
                padding: "10px 12px",
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
                <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>
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
          }}
        >
          {isSubmitting ? "Posting..." : "Post Comment"}
        </button>
      </form>
    </div>
  );
}
