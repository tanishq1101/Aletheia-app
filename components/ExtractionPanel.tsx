"use client";

import { useState } from "react";
import type { Paper, PaperPage, PaperSection } from "@/types/api";

type TabKey = "outline" | "pages" | "extraction";

const tabs: { key: TabKey; label: string }[] = [
  { key: "outline", label: "Outline" },
  { key: "pages", label: "Pages" },
  { key: "extraction", label: "Extraction" },
];

/** Figures, tables, equations and citations are Phase 2 of the backend PRD.
 *  The tab stays so the shape of the reader is right, and says what is missing
 *  rather than showing placeholder cards that look like extracted objects. */
const NOT_EXTRACTED = [
  { label: "Figures", note: "Requires layout-aware parsing (backend Phase 2)." },
  { label: "Tables", note: "Requires table structure recognition (Phase 2)." },
  { label: "Equations", note: "Requires math OCR (Phase 2)." },
  { label: "Citations", note: "Requires reference parsing (Phase 2)." },
];

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function ExtractionPanel({
  paper,
  pages,
  sections,
}: {
  paper: Paper;
  pages: PaperPage[];
  sections: PaperSection[];
}) {
  const [activeTab, setActiveTab] = useState<TabKey>("outline");

  return (
    <div className="flex h-full w-[400px] shrink-0 flex-col items-start border-l border-hairline-subtle bg-surface">
      <div className="flex w-full shrink-0 items-start gap-[22px] border-b border-hairline-subtle px-6">
        {tabs.map((tab) => {
          const active = tab.key === activeTab;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className="flex shrink-0 flex-col items-start gap-2 pt-4 pb-3.5"
            >
              <span
                className={`font-ui text-[13px] whitespace-nowrap ${
                  active ? "font-semibold text-primary" : "font-normal text-muted"
                }`}
              >
                {tab.label}
              </span>
              <span
                className={`h-[2px] w-[60px] shrink-0 ${active ? "bg-brass" : "bg-surface"}`}
              />
            </button>
          );
        })}
      </div>

      <div className="flex w-full flex-1 min-h-px flex-col items-start gap-3 overflow-y-auto p-6">
        {activeTab === "outline" && (
          <>
            {sections.length === 0 && (
              <p className="font-ui text-xs text-muted">
                No sections detected. The parser looks for numbered and titled
                headings; a paper without them still indexes fine.
              </p>
            )}
            {sections.map((section) => (
              <button
                key={section.id}
                type="button"
                onClick={() => scrollTo(`section-${section.id}`)}
                className="flex w-full shrink-0 items-baseline gap-2 rounded px-2 py-1.5 text-left transition-colors hover:bg-surface-raised"
                // Nesting mirrors the heading level the parser assigned.
                style={{ paddingLeft: `${8 + (section.level - 1) * 12}px` }}
              >
                <span className="min-w-px flex-1 font-ui text-xs text-primary">
                  {section.title}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-muted">
                  p{section.start_page}
                </span>
              </button>
            ))}
          </>
        )}

        {activeTab === "pages" && (
          <>
            {pages.length === 0 && (
              <p className="font-ui text-xs text-muted">
                No extracted pages{paper.status === "failed" ? " — processing failed." : "."}
              </p>
            )}
            {pages.map((page) => (
              <button
                key={page.id}
                type="button"
                onClick={() => scrollTo(`page-${page.page_number}`)}
                className="flex w-full shrink-0 items-center gap-3 rounded px-2 py-1.5 text-left transition-colors hover:bg-surface-raised"
              >
                <span className="w-8 shrink-0 font-mono text-[10px] text-brass">
                  p{page.page_number}
                </span>
                <span className="min-w-px flex-1 truncate font-ui text-xs text-secondary">
                  {page.cleaned_text?.slice(0, 60) ?? "empty"}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-muted">
                  {page.character_count ?? 0}c
                </span>
              </button>
            ))}
          </>
        )}

        {activeTab === "extraction" && (
          <div className="flex w-full flex-col items-start gap-3">
            <p className="w-full font-ui text-xs text-secondary">
              This paper is extracted as text: {pages.length} page
              {pages.length === 1 ? "" : "s"} and {sections.length} section
              {sections.length === 1 ? "" : "s"}, chunked and embedded for
              search. Structured objects are not extracted yet.
            </p>
            {NOT_EXTRACTED.map((item) => (
              <div
                key={item.label}
                className="flex w-full shrink-0 flex-col items-start gap-1 rounded-md border border-dashed border-hairline-subtle p-3.5"
              >
                <p className="font-ui text-xs font-semibold text-muted">
                  {item.label}
                </p>
                <p className="w-full font-ui text-xs text-muted">{item.note}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
