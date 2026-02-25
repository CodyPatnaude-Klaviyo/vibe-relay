import { STEP_PALETTE, withAlpha } from "../utils/colors";

export function StepBadge({ name, color, position }: { name: string; color?: string | null; position?: number }) {
  const stepColor = color ?? STEP_PALETTE[(position ?? 0) % STEP_PALETTE.length];
  return (
    <span
      style={{
        background: withAlpha(stepColor, 0.12),
        color: stepColor,
        border: `1px solid ${withAlpha(stepColor, 0.25)}`,
        backdropFilter: "blur(4px)",
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
