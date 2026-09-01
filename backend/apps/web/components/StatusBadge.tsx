import type { Paper } from "@/types/api";

const STYLES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  succeeded:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  none: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
};

export function StatusBadge({ paper }: { paper: Paper }) {
  const job = paper.job;
  const status = job?.status ?? "none";
  const label = job
    ? job.stage
      ? `${job.status} · ${job.stage}`
      : job.status
    : "no job";

  const inFlight = status === "pending" || status === "running";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        STYLES[status] ?? STYLES.none
      }`}
    >
      {inFlight && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {label}
      {inFlight && job && job.progress > 0 && (
        <span className="opacity-70">{Math.round(job.progress * 100)}%</span>
      )}
    </span>
  );
}
