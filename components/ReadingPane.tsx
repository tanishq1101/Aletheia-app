import { Fragment } from "react";
import type { Paper, PaperPage, PaperSection } from "@/types/api";
import { paperTitle } from "@/lib/display";

/** Groups the extracted pages under the sections the parser detected.
 *
 * Section boundaries the backend records are page-level (`start_page`), so a
 * section that begins halfway down a page is shown as starting at that page.
 * The alternative — splitting page text on a guessed offset — would look more
 * precise than the data actually is. */
function groupPages(pages: PaperPage[], sections: PaperSection[]) {
  type Group = { section: PaperSection | null; pages: PaperPage[] };

  if (sections.length === 0) {
    return [{ section: null, pages }] as Group[];
  }

  const groups: Group[] = [];

  const firstStart = sections[0].start_page;
  const preamble = pages.filter((page) => page.page_number < firstStart);
  if (preamble.length > 0) groups.push({ section: null, pages: preamble });

  sections.forEach((section, index) => {
    const next = sections[index + 1];
    const from = section.start_page;
    const to = next ? next.start_page : Number.POSITIVE_INFINITY;
    groups.push({
      section,
      // A page carrying two section starts belongs to the first of them; the
      // second shows as a heading with no page of its own rather than
      // duplicating the text.
      pages: pages.filter((page) => page.page_number >= from && page.page_number < to),
    });
  });

  return groups;
}

export default function ReadingPane({
  paper,
  pages,
  sections,
}: {
  paper: Paper;
  pages: PaperPage[];
  sections: PaperSection[];
}) {
  const groups = groupPages(pages, sections);

  return (
    <div className="flex h-full min-w-px flex-1 flex-col items-center overflow-y-auto px-10 py-12">
      <div className="flex w-full max-w-[820px] flex-col items-start gap-5">
      <p className="shrink-0 font-mono text-[10px] tracking-[0.8px] whitespace-nowrap text-brass">
        {paper.page_count != null ? `${paper.page_count} PAGES` : "PDF"} ·{" "}
        {sections.length} SECTION{sections.length === 1 ? "" : "S"}
      </p>

      <h1 className="w-full shrink-0 font-display text-3xl font-black text-primary">
        {paperTitle(paper)}
      </h1>

      <p className="shrink-0 font-ui text-xs text-secondary">{paper.filename}</p>

      {pages.length === 0 && (
        <p className="font-ui text-sm text-muted">
          No extracted text for this paper yet.
        </p>
      )}

      {groups.map((group, index) => (
        <Fragment key={group.section?.id ?? `preamble-${index}`}>
          {group.section && (
            <p
              id={`section-${group.section.id}`}
              className="w-full shrink-0 scroll-mt-6 pt-2 font-ui text-[13px] font-semibold text-brass"
            >
              {group.section.title}
            </p>
          )}
          {group.pages.map((page) => (
            <article
              key={page.id}
              id={`page-${page.page_number}`}
              className="flex w-full shrink-0 scroll-mt-6 flex-col items-start gap-4 rounded-lg border border-hairline-subtle bg-surface px-10 py-9 shadow-[0_16px_50px_rgba(0,0,0,0.12)]"
            >
              <p className="font-mono text-[10px] tracking-[0.6px] text-muted">
                PAGE {page.page_number}
              </p>
              <p className="w-full font-reading text-[17px] leading-[1.85] whitespace-pre-wrap text-secondary">
                {page.cleaned_text ?? ""}
              </p>
            </article>
          ))}
        </Fragment>
      ))}
      </div>
    </div>
  );
}
