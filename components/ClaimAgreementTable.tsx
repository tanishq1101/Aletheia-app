import AgreementBadge from "@/components/AgreementBadge";
import { paperTitle } from "@/lib/display";
import type { Claim, CrossPaperCell, Paper } from "@/types/api";

export default function ClaimAgreementTable({
  papers,
  claims,
  cells,
  onSelectCell,
}: {
  papers: Paper[];
  claims: Claim[];
  cells: CrossPaperCell[];
  onSelectCell: (cell: CrossPaperCell) => void;
}) {
  const byKey = new Map(
    cells.map((cell) => [`${cell.claim_id}:${cell.paper_id}`, cell])
  );

  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-px overflow-x-auto">
      <div className="flex w-full min-w-[720px] shrink-0 items-start bg-surface-raised px-4 py-3">
        <div className="min-w-px flex-[2] shrink-0">
          <p className="font-mono text-[10px] tracking-[0.4px] text-muted">Claim</p>
        </div>
        {papers.map((paper) => (
          <div key={paper.id} className="min-w-px flex-1 shrink-0 pr-3">
            <p className="font-mono text-[10px] tracking-[0.4px] text-muted">
              {paperTitle(paper)}
            </p>
          </div>
        ))}
      </div>

      {claims.map((claim) => (
        <div
          key={claim.id}
          className="flex w-full min-w-[720px] shrink-0 items-start bg-surface p-4"
        >
          <div className="min-w-px flex-[2] shrink-0 pr-4">
            <p className="font-ui text-[13px] text-primary">{claim.text}</p>
          </div>
          {papers.map((paper) => {
            const cell = byKey.get(`${claim.id}:${paper.id}`);
            return (
              <div key={paper.id} className="min-w-px flex-1 shrink-0">
                <AgreementBadge
                  verdict={cell?.verification.verdict ?? "unchecked"}
                  confidence={cell?.verification.confidence}
                  onClick={cell ? () => onSelectCell(cell) : undefined}
                />
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
