import { INGESTION_STAGES, paperTitle, stageIndex } from "@/lib/display";
import type { Paper } from "@/types/api";

const barColor = {
  complete: "bg-success",
  active: "bg-brass",
  pending: "bg-hairline-subtle",
  failed: "bg-error",
} as const;

const labelColor = {
  complete: "text-secondary font-normal",
  active: "text-secondary font-medium",
  pending: "text-muted font-normal",
  failed: "text-error font-medium",
} as const;

/** Renders a paper's live ingestion job. Stages come from the backend's
 *  `process_paper`, so this shows where the work actually is rather than a
 *  timed animation. */
export default function ProcessingStepper({ paper }: { paper: Paper }) {
  const current = stageIndex(paper.job?.stage);
  const failed = paper.status === "failed";
  const done = paper.status === "ready";

  const shownStep = done
    ? INGESTION_STAGES.length
    : Math.max(0, Math.min(current, INGESTION_STAGES.length));

  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-[18px] rounded-md border border-hairline-subtle bg-surface px-6 py-5">
      <div className="flex w-full items-center gap-3">
        <p className="flex-1 min-w-px truncate font-ui text-sm font-semibold text-primary">
          {paperTitle(paper)}
        </p>
        <p
          className={`shrink-0 font-mono text-[11px] whitespace-nowrap ${
            failed ? "text-error" : done ? "text-success" : "text-brass"
          }`}
        >
          {failed
            ? "Failed"
            : done
              ? "Complete"
              : `Step ${Math.max(1, shownStep)} of ${INGESTION_STAGES.length}`}
        </p>
      </div>

      <div className="flex w-full items-start gap-1">
        {INGESTION_STAGES.map((stage, index) => {
          const state = failed
            ? index === current
              ? "failed"
              : index < current
                ? "complete"
                : "pending"
            : done || index < current
              ? "complete"
              : index === current
                ? "active"
                : "pending";

          return (
            <div
              key={stage.key}
              className="flex flex-1 min-w-px flex-col items-start gap-2"
            >
              <div className={`h-1 w-full shrink-0 rounded-sm ${barColor[state]}`} />
              <p className={`w-full font-ui text-[11px] ${labelColor[state]}`}>
                {stage.label}
              </p>
            </div>
          );
        })}
      </div>

      {failed && paper.job?.error && (
        <p className="w-full font-ui text-xs text-error">{paper.job.error}</p>
      )}
    </div>
  );
}
