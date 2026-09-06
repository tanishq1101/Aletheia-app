"use client";

import { useState } from "react";
import { assetContentUrl, interpretFigure } from "@/lib/api";
import type { Paper, PaperAsset, PaperPage, PaperSection } from "@/types/api";

type TabKey = "outline" | "pages" | "extraction";

const tabs: { key: TabKey; label: string }[] = [
  { key: "outline", label: "Outline" },
  { key: "pages", label: "Pages" },
  { key: "extraction", label: "Extraction" },
];

type InterpretationState =
  | { status: "loading" }
  | {
      status: "succeeded";
      text: string;
      model: string;
      cached: boolean;
      createdAt: string;
    }
  | { status: "failed"; error: string };

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function ExtractionPanel({
  paper,
  pages,
  sections,
  assets,
}: {
  paper: Paper;
  pages: PaperPage[];
  sections: PaperSection[];
  assets: PaperAsset[];
}) {
  const [activeTab, setActiveTab] = useState<TabKey>("outline");
  const [interpretations, setInterpretations] = useState<
    Record<string, InterpretationState>
  >({});
  const figures = assets.filter((asset) => asset.kind === "figure");
  const tables = assets.filter((asset) => asset.kind === "table");
  const equations = assets.filter((asset) => asset.kind === "equation");

  async function handleInterpretFigure(asset: PaperAsset) {
    setInterpretations((current) => ({
      ...current,
      [asset.id]: { status: "loading" },
    }));
    try {
      const result = await interpretFigure(asset.id);
      setInterpretations((current) => ({
        ...current,
        [asset.id]: {
          status: "succeeded",
          text: result.interpretation,
          model: result.model,
          cached: result.cached,
          createdAt: result.created_at,
        },
      }));
    } catch (error) {
      setInterpretations((current) => ({
        ...current,
        [asset.id]: {
          status: "failed",
          error: error instanceof Error ? error.message : "Interpretation failed.",
        },
      }));
    }
  }

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
              {pages.length} text page{pages.length === 1 ? "" : "s"}, {figures.length}{" "}
              figure{figures.length === 1 ? "" : "s"}, {tables.length} table
              {tables.length === 1 ? "" : "s"}, and {equations.length} equation
              {equations.length === 1 ? "" : "s"} candidate
              {equations.length === 1 ? "" : "s"} extracted locally.
            </p>

            {assets.length === 0 && (
              <div
                className="flex w-full shrink-0 flex-col items-start gap-1 rounded-md border border-dashed border-hairline-subtle p-3.5"
              >
                <p className="font-ui text-xs font-semibold text-muted">No structured assets</p>
                <p className="w-full font-ui text-xs text-muted">
                  This PDF may contain vector-only graphics or an unsupported table layout.
                  Text remains fully searchable.
                </p>
              </div>
            )}

            {assets.map((asset) => {
              const interpretation = interpretations[asset.id];
              return (
                <div
                key={asset.id}
                className="flex w-full shrink-0 flex-col items-start gap-2 rounded-md border border-hairline-subtle bg-surface-raised p-3.5"
              >
                <button
                  type="button"
                  onClick={() => scrollTo(`page-${asset.page_number}`)}
                  className="flex w-full items-center gap-2 text-left"
                >
                  <span className="rounded border border-brass px-1.5 py-0.5 font-mono text-[9px] uppercase text-brass">
                    {asset.kind}
                  </span>
                  <span className="min-w-px flex-1 font-ui text-xs font-semibold text-primary">
                    {asset.caption ?? `${asset.kind} ${asset.asset_index + 1}`}
                  </span>
                  <span className="font-mono text-[9px] text-muted">p{asset.page_number}</span>
                </button>

                {asset.kind === "figure" && asset.has_binary && (
                  <>
                    {/* Binary content is served by resolved asset ID; the browser
                        never receives a storage path. */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={assetContentUrl(asset.id)}
                      alt={asset.caption ?? `Figure on page ${asset.page_number}`}
                      className="max-h-52 w-full rounded border border-hairline-subtle bg-white object-contain"
                    />
                    <button
                      type="button"
                      onClick={() => handleInterpretFigure(asset)}
                      disabled={
                        interpretation?.status === "loading" ||
                        interpretation?.status === "succeeded"
                      }
                      className="rounded border border-brass px-2.5 py-1.5 font-ui text-[10px] font-semibold text-brass transition-colors hover:bg-brass/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {interpretation?.status === "loading"
                        ? "Interpreting one figure…"
                        : interpretation?.status === "succeeded"
                          ? "Interpreted"
                          : "Interpret this figure"}
                    </button>
                    {interpretation?.status === "succeeded" && (
                      <div className="w-full rounded border border-hairline-subtle bg-base p-3">
                        <p className="whitespace-pre-wrap font-ui text-xs leading-relaxed text-secondary">
                          {interpretation.text}
                        </p>
                        <p className="mt-2 font-mono text-[9px] text-muted">
                          AI-generated · {interpretation.model} ·{" "}
                          {interpretation.cached
                            ? "loaded from saved result — no new AI call"
                            : "generated now and saved for reuse"}
                          {" · "}
                          {new Date(interpretation.createdAt).toLocaleString()}
                        </p>
                      </div>
                    )}
                    {interpretation?.status === "failed" && (
                      <p className="w-full rounded border border-red-900/50 bg-red-950/20 p-2.5 font-ui text-[10px] text-red-300">
                        {interpretation.error}
                      </p>
                    )}
                    {!interpretation && (
                      <p className="font-ui text-[10px] text-muted">
                        On demand only: generates once, then reuses the saved result.
                      </p>
                    )}
                  </>
                )}

                {asset.content_text && (
                  <pre className="max-h-52 w-full overflow-auto whitespace-pre-wrap rounded bg-base p-3 font-mono text-[10px] leading-relaxed text-secondary">
                    {asset.content_text}
                  </pre>
                )}

                {asset.kind === "equation" && (
                  <p className="font-ui text-[10px] text-muted">
                    Heuristic candidate from PDF text; not math-OCR verified.
                  </p>
                )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
