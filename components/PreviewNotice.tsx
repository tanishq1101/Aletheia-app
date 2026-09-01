/** Marks a page whose content is still fixtures.
 *
 * The backend covers ingestion, retrieval and grounded answering; claim
 * extraction, cross-paper comparison and reproducibility checking are a later
 * phase of its PRD. Those pages still render, but they say so rather than
 * passing fixtures off as results. */
export default function PreviewNotice({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex w-full shrink-0 items-start gap-3 rounded-md border border-dashed border-brass bg-surface px-[18px] py-3.5">
      <span className="mt-[5px] size-[6px] shrink-0 rounded-full bg-brass" />
      <p className="min-w-px flex-1 font-ui text-xs text-secondary">
        <span className="font-semibold text-brass">Preview · not live data. </span>
        {children}
      </p>
    </div>
  );
}
