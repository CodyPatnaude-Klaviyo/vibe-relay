const STEP_PALETTE = [
  "#a855f7", // purple
  "#3b82f6", // blue
  "#f97316", // orange
  "#22c55e", // green
  "#ef4444", // red
  "#06b6d4", // cyan
  "#eab308", // yellow
  "#ec4899", // pink
];

export function StepBadge({ name, color, position }: { name: string; color?: string | null; position?: number }) {
  const bg = color ?? STEP_PALETTE[(position ?? 0) % STEP_PALETTE.length];
  return (
    <span
      style={{
        background: bg,
        color: "#fff",
        padding: "2px 8px",
        borderRadius: "var(--badge-radius)",
        fontSize: "11px",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
      }}
    >
      {name}
    </span>
  );
}
