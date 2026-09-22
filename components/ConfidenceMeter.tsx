import type { BadgeTone } from "@/components/Badge";

const fillColor: Record<BadgeTone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  error: "bg-error",
  muted: "bg-muted",
};

/**
 * The model's own stated confidence, 0-1. It is not a calibrated probability,
 * so the label says whose number it is rather than presenting it as measured.
 */
export default function ConfidenceMeter({
  confidence,
  tone,
}: {
  confidence: number | null;
  tone: BadgeTone;
}) {
  const percent = confidence === null ? null : Math.round(confidence * 100);

  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 sm:flex-nowrap">
      <div className="relative h-1.5 min-w-[120px] flex-1 overflow-hidden rounded-sm bg-surface-raised sm:w-[220px] sm:flex-none">
        {percent !== null && percent > 0 && (
          <div
            className={`absolute inset-y-0 left-0 rounded-sm ${fillColor[tone]}`}
            style={{ width: `${percent}%` }}
          />
        )}
      </div>
      <p className="shrink-0 font-mono text-[11px] whitespace-nowrap text-muted">
        {percent === null
          ? "no confidence reported"
          : `${percent}% model-reported`}
      </p>
    </div>
  );
}
