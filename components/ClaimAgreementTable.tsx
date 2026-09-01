import AgreementBadge from "@/components/AgreementBadge";
import type { ClaimAgreementRow, CrossPaperEntry } from "@/lib/preview-data";

export default function ClaimAgreementTable({
  papers,
  rows,
}: {
  papers: CrossPaperEntry[];
  rows: ClaimAgreementRow[];
}) {
  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-px overflow-x-auto">
      <div className="flex w-full min-w-[720px] shrink-0 items-start bg-surface-raised px-4 py-3">
        <div className="min-w-px flex-[2] shrink-0">
          <p className="font-mono text-[10px] tracking-[0.4px] text-muted">Claim</p>
        </div>
        {papers.map((paper) => (
          <div key={paper.id} className="min-w-px flex-1 shrink-0">
            <p className="font-mono text-[10px] tracking-[0.4px] whitespace-nowrap text-muted">
              {paper.label}
            </p>
          </div>
        ))}
      </div>

      {rows.map((row) => (
        <div
          key={row.id}
          className="flex w-full min-w-[720px] shrink-0 items-start bg-surface p-4"
        >
          <div className="min-w-px flex-[2] shrink-0 pr-4">
            <p className="font-ui text-[13px] text-primary">{row.claim}</p>
          </div>
          {papers.map((paper) => (
            <div key={paper.id} className="min-w-px flex-1 shrink-0">
              <AgreementBadge status={row.agreements[paper.id] ?? "unverified"} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
