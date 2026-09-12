import { paperTitle } from "@/lib/display";
import type { Paper } from "@/types/api";

/** Papers that finished processing — the only ones with anything to analyse. */
export default function PaperSelect({
  papers,
  value,
  onChange,
  label = "Paper",
}: {
  papers: Paper[];
  value: string | null;
  onChange: (paperId: string) => void;
  label?: string;
}) {
  return (
    <div className="flex shrink-0 items-center gap-3">
      <p className="font-mono text-[10px] tracking-[0.6px] whitespace-nowrap text-muted">
        {label.toUpperCase()}
      </p>
      <select
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
        className="min-w-[320px] max-w-[520px] rounded-md border border-hairline bg-surface px-3 py-2 font-ui text-[13px] text-primary focus:border-brass focus:outline-none"
      >
        {papers.length === 0 && <option value="">No processed papers</option>}
        {papers.map((paper) => (
          <option key={paper.id} value={paper.id}>
            {paperTitle(paper)}
          </option>
        ))}
      </select>
    </div>
  );
}
