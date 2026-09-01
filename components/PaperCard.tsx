import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { paperTitle, shortDate } from "@/lib/display";
import type { Paper } from "@/types/api";

export default function PaperCard({ paper }: { paper: Paper }) {
  // Only a ready paper has extracted text to read, so a failed or still
  // processing one links to the reader's status view rather than pretending.
  const facts = [
    paper.page_count != null
      ? `${paper.page_count} page${paper.page_count === 1 ? "" : "s"}`
      : null,
    paper.filename,
  ].filter(Boolean) as string[];

  return (
    <Link
      href={`/paper/${paper.id}`}
      className="flex w-[410px] shrink-0 flex-col items-start gap-[14px] rounded-md border border-hairline-subtle bg-surface p-5 transition-colors hover:border-hairline"
    >
      <div className="flex w-full items-start gap-2">
        <StatusBadge status={paper.status} />
        <p className="font-ui text-[11px] whitespace-nowrap text-muted">
          {shortDate(paper.created_at)}
        </p>
      </div>

      <p className="w-full font-display text-[17px] font-semibold text-primary">
        {paperTitle(paper)}
      </p>

      {paper.status === "failed" && paper.job?.error ? (
        <p className="w-full font-ui text-xs text-error">{paper.job.error}</p>
      ) : (
        <p className="w-full font-ui text-xs text-secondary">
          {paper.job?.stage && paper.status === "processing"
            ? `Stage: ${paper.job.stage}`
            : "\u00a0"}
        </p>
      )}

      <div className="flex shrink-0 flex-wrap items-start gap-1.5">
        {facts.map((fact) => (
          <div
            key={fact}
            className="shrink-0 rounded-[3px] bg-surface-raised px-2 py-[3px]"
          >
            <p className="max-w-[280px] truncate font-mono text-[9px] text-secondary">
              {fact}
            </p>
          </div>
        ))}
      </div>
    </Link>
  );
}
