import type { BadgeTone } from "@/components/Badge";
import type { CheckStatus } from "@/lib/preview-data";

const statusConfig: Record<CheckStatus, { glyph: string; tone: BadgeTone }> = {
  pass: { glyph: "✓", tone: "success" },
  warning: { glyph: "!", tone: "warning" },
  pending: { glyph: "…", tone: "muted" },
};

const toneClasses: Record<BadgeTone, { border: string; text: string }> = {
  success: { border: "border-success", text: "text-success" },
  warning: { border: "border-warning", text: "text-warning" },
  error: { border: "border-error", text: "text-error" },
  muted: { border: "border-muted", text: "text-muted" },
};

export default function CheckStatusIcon({ status }: { status: CheckStatus }) {
  const { glyph, tone } = statusConfig[status];
  const classes = toneClasses[tone];

  return (
    <div
      className={`flex size-5 shrink-0 items-center justify-center rounded-full border ${classes.border}`}
    >
      <p className={`font-ui text-[11px] font-semibold ${classes.text}`}>{glyph}</p>
    </div>
  );
}
