import { useEffect, useRef, useState } from "react";
import { getAgentLogs, type LogLine } from "../api/tasks";

const TYPE_COLORS: Record<string, string> = {
  assistant: "var(--text)",
  tool_use: "#22c55e",
  tool_result: "#3b82f6",
  system: "var(--text-dim)",
};

function LogEntry({ line }: { line: LogLine }) {
  const color = TYPE_COLORS[line.type] ?? "var(--text-muted)";
  const label =
    line.type === "tool_use" && line.tool
      ? `tool: ${line.tool}`
      : line.type;

  return (
    <div style={{ marginBottom: "6px", fontSize: "12px", lineHeight: 1.5 }}>
      <span
        style={{
          color,
          fontWeight: 600,
          fontSize: "10px",
          textTransform: "uppercase",
          letterSpacing: "0.3px",
          marginRight: "8px",
        }}
      >
        [{label}]
      </span>
      <span
        style={{
          color: line.type === "system" ? "var(--text-dim)" : "var(--text-muted)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {line.content ?? ""}
      </span>
    </div>
  );
}

interface Props {
  taskId: string;
  isRunning: boolean;
}

/** Wrapper that remounts the viewer when taskId changes, resetting all state. */
export function AgentLogViewer({ taskId, isRunning }: Props) {
  return <AgentLogViewerInner key={taskId} taskId={taskId} isRunning={isRunning} />;
}

function AgentLogViewerInner({ taskId, isRunning }: Props) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<string>("");
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  useEffect(() => {
    if (!expanded) return;

    let cancelled = false;

    async function poll() {
      if (cancelled) return;
      try {
        const resp = await getAgentLogs(taskId, offset);
        if (cancelled) return;
        if (resp.lines.length > 0) {
          setLines((prev) => [...prev, ...resp.lines]);
          setOffset(resp.offset);
        }
        setStatus(resp.status);
      } catch {
        // silently ignore fetch errors during polling
      }
    }

    void poll();

    // Only poll if the agent is still running
    if (isRunning || status === "running") {
      const interval = setInterval(() => void poll(), 3000);
      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }

    return () => {
      cancelled = true;
    };
  }, [taskId, offset, expanded, isRunning, status]);

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    if (autoScrollRef.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [lines.length]);

  function handleScroll() {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    autoScrollRef.current = atBottom;
  }

  const hasLogs = status !== "no_session" && status !== "no_worktree";

  if (!hasLogs && !expanded) return null;

  return (
    <div style={{ marginTop: "24px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "10px",
        }}
      >
        <h4
          style={{
            fontSize: "11px",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
            color: "var(--text-muted)",
            paddingLeft: "10px",
            borderLeft: "2px solid var(--agent-active)",
            margin: 0,
          }}
        >
          Agent Transcript
        </h4>
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            background: "none",
            border: "1px solid var(--glass-border)",
            color: "var(--text-muted)",
            fontSize: "11px",
            padding: "2px 8px",
            borderRadius: "var(--badge-radius)",
            cursor: "pointer",
          }}
        >
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>
      {expanded && (
        <div
          ref={containerRef}
          onScroll={handleScroll}
          style={{
            background: "#0d1117",
            border: "1px solid var(--glass-border)",
            borderRadius: "var(--card-radius)",
            padding: "12px",
            maxHeight: "400px",
            overflowY: "auto",
            fontFamily: "monospace",
          }}
        >
          {lines.length === 0 && (
            <div style={{ color: "var(--text-dim)", fontSize: "12px" }}>
              {status === "transcript_not_found"
                ? "Transcript file not found yet..."
                : "Waiting for agent output..."}
            </div>
          )}
          {lines.map((line) => (
            <LogEntry key={line.index} line={line} />
          ))}
          {(isRunning || status === "running") && lines.length > 0 && (
            <div
              style={{
                color: "var(--agent-active)",
                fontSize: "11px",
                marginTop: "4px",
                animation: "pulse 1.5s ease-in-out infinite",
              }}
            >
              Agent is running...
            </div>
          )}
        </div>
      )}
    </div>
  );
}
