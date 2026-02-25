import type { Phase } from "../types";

const PHASE_COLORS: Record<Phase, string> = {
  planner: "var(--phase-planner)",
  coder: "var(--phase-coder)",
  reviewer: "var(--phase-reviewer)",
  orchestrator: "var(--phase-orchestrator)",
};

export function PhaseBadge({ phase }: { phase: string }) {
  const color = PHASE_COLORS[phase as Phase] ?? "var(--text-muted)";
  return (
    <span
      style={{
        background: color,
        color: "#fff",
        padding: "2px 8px",
        borderRadius: "var(--badge-radius)",
        fontSize: "11px",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
      }}
    >
      {phase}
    </span>
  );
}
