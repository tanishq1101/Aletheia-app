import Link from "next/link";
import type { Citation } from "@/types/api";

/**
 * A citation the backend resolved from an evidence ID it issued — never a label
 * the model invented. The snippet is the exact text the answer was built on.
 */
export default function CitationCard({ citation }: { citation: Citation }) {
  return (
    <Link
      href={`/paper/${citation.paper_id}`}
      className="flex w-full shrink-0 flex-col items-start gap-1.5 rounded-md border border-hairline-subtle bg-surface-raised px-4 py-3 transition-colors hover:border-hairline"
    >
      <div className="flex w-full items-center gap-2">
        <span className="shrink-0 rounded-[3px] bg-brass px-1.5 py-[2px] font-mono text-[9px] font-semibold text-base">
          {citation.evidence_id}
        </span>
        <p className="min-w-px flex-1 truncate font-ui text-xs font-semibold text-primary">
          {citation.paper_title ?? "Untitled paper"}
        </p>
        <p className="shrink-0 font-ui text-[10px] whitespace-nowrap text-muted">
          {citation.location}
        </p>
      </div>
      <p className="w-full font-reading text-xs text-secondary">
        {citation.snippet}
      </p>
    </Link>
  );
}
