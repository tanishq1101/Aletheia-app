import PreviewNotice from "@/components/PreviewNotice";
import ClaimAgreementTable from "@/components/ClaimAgreementTable";
import { crossPaperWorkspace } from "@/lib/preview-data";

export default function CrossPaperPage() {
  return (
    <div className="flex w-full flex-col items-start gap-6">
      <h1 className="font-display text-[28px] font-semibold text-primary">
        Cross-Paper Workspace
      </h1>

      <PreviewNotice>
        Cross-paper claim comparison is not implemented in the API yet — the
        matrix below is a fixture. What is live today: upload, semantic search
        and grounded answers over your own papers.
      </PreviewNotice>

      <p className="font-ui text-[13px] text-secondary">{crossPaperWorkspace.summary}</p>

      <div className="flex w-full shrink-0 flex-wrap items-start gap-2.5">
        {crossPaperWorkspace.papers.map((paper) => (
          <div
            key={paper.id}
            className="flex shrink-0 items-center gap-2 rounded-full border border-hairline bg-surface px-[14px] py-2"
          >
            <span className="size-1.5 shrink-0 rounded-full bg-brass" />
            <p className="font-ui text-xs font-medium whitespace-nowrap text-primary">
              {paper.title}
            </p>
          </div>
        ))}
        <div className="flex shrink-0 items-start rounded-full border border-dashed border-hairline px-[14px] py-2">
          <p className="font-ui text-xs font-medium whitespace-nowrap text-muted">+ Add paper</p>
        </div>
      </div>

      <p className="font-ui text-[15px] font-semibold text-primary">Claim agreement matrix</p>

      <ClaimAgreementTable papers={crossPaperWorkspace.papers} rows={crossPaperWorkspace.claims} />
    </div>
  );
}
