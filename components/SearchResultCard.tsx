import Link from "next/link";
import { chunkLocation, matchPercent } from "@/lib/display";
import type { SearchResult } from "@/types/api";

/** One retrieved chunk. Search returns passages, not papers — the card shows
 *  the passage and where in which paper it came from. */
export default function SearchResultCard({ result }: { result: SearchResult }) {
  const title = result.paper_title ?? result.filename.replace(/\.pdf$/i, "");
  const location = chunkLocation(result.section, result.page_number);

  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-2.5 rounded-md border border-hairline-subtle bg-surface px-6 py-5">
      <div className="flex w-full items-center gap-3">
        <Link
          href={`/paper/${result.paper_id}`}
          className="flex-1 min-w-px font-display text-lg font-semibold text-primary hover:text-brass-bright"
        >
          {title}
        </Link>
        <div className="shrink-0 rounded-full border border-brass px-2.5 py-1">
          <p className="font-mono text-[10px] whitespace-nowrap text-brass">
            {matchPercent(result.similarity)}% match
          </p>
        </div>
      </div>

      {location && (
        <p className="font-ui text-xs text-secondary">{location}</p>
      )}

      <p className="w-full font-reading text-sm whitespace-pre-wrap text-secondary">
        {result.content}
      </p>
    </div>
  );
}
