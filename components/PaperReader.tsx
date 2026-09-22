"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import ExtractionPanel from "@/components/ExtractionPanel";
import ProcessingStepper from "@/components/ProcessingStepper";
import ReadingPane from "@/components/ReadingPane";
import {
  ApiError,
  getPaper,
  listAssets,
  listPages,
  listSections,
  reprocessPaper,
} from "@/lib/api";
import { paperTitle } from "@/lib/display";
import type { Paper, PaperAsset, PaperPage, PaperSection } from "@/types/api";

const POLL_INTERVAL_MS = 2500;

export default function PaperReader({ paperId }: { paperId: string }) {
  const [paper, setPaper] = useState<Paper | null>(null);
  const [pages, setPages] = useState<PaperPage[]>([]);
  const [sections, setSections] = useState<PaperSection[]>([]);
  const [assets, setAssets] = useState<PaperAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Promise chain rather than async/await so the setStates sit in callbacks
  // instead of running synchronously inside the effect below.
  const load = useCallback(() => {
    return getPaper(paperId)
      .then((next): Promise<[Paper, PaperPage[], PaperSection[], PaperAsset[]]> => {
        // Text only exists once extraction has succeeded; asking earlier just
        // returns empty lists, so skip the two round trips.
        if (next.status !== "ready") {
          return Promise.resolve([next, [], [], []]);
        }
        return Promise.all([
          Promise.resolve(next),
          listPages(paperId),
          listSections(paperId),
          listAssets(paperId),
        ]);
      })
      .then(([next, nextPages, nextSections, nextAssets]) => {
        setPaper(next);
        setPages(nextPages);
        setSections(nextSections);
        setAssets(nextAssets);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError ? err.message : "Could not load the paper.",
        );
        setLoading(false);
      });
  }, [paperId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Follow a paper that is still ingesting so the reader fills in when it lands.
  const inFlight = paper?.status === "uploaded" || paper?.status === "processing";
  useEffect(() => {
    if (!inFlight) return;
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [inFlight, load]);

  const header = (
    <div className="flex w-full shrink-0 items-center gap-3 border-b border-hairline-subtle px-4 py-4 sm:px-6 md:px-10 md:py-[18px]">
      <Link
        href="/library"
        className="shrink-0 font-ui text-xs whitespace-nowrap text-muted hover:text-secondary"
      >
        Library
      </Link>
      <span className="shrink-0 font-ui text-xs text-muted">/</span>
      <p className="flex-1 min-w-px truncate font-ui text-xs font-medium text-primary">
        {paper ? paperTitle(paper) : loading ? "Loading…" : "Paper"}
      </p>
    </div>
  );

  return (
    <div className="-mx-4 -my-6 flex h-full w-[calc(100%+2rem)] flex-1 flex-col items-start sm:-mx-6 sm:w-[calc(100%+3rem)] md:-mx-10 md:-my-8 md:w-[calc(100%+5rem)]">
      {header}

      {error ? (
        <div className="w-full px-4 py-6 sm:px-6 md:px-10 md:py-8">
          <ApiErrorNotice message={error} onRetry={() => void load()} />
        </div>
      ) : loading || !paper ? (
        <p className="px-4 py-6 font-ui text-sm text-muted sm:px-6 md:px-10 md:py-8">Loading paper…</p>
      ) : paper.status === "ready" ? (
        <div className="flex w-full flex-1 min-h-px flex-col items-start lg:flex-row">
          <ReadingPane paper={paper} pages={pages} sections={sections} />
          <ExtractionPanel
            paper={paper}
            pages={pages}
            sections={sections}
            assets={assets}
          />
        </div>
      ) : (
        // Not ready: show the job instead of an empty reader, so the state is
        // legible and a failure is retryable from here.
        <div className="flex w-full flex-col items-start gap-6 px-4 py-6 sm:px-6 md:px-10 md:py-8">
          <h1 className="font-display text-2xl font-semibold text-primary">
            {paperTitle(paper)}
          </h1>
          <ProcessingStepper paper={paper} />
          {paper.status === "failed" && (
            <button
              type="button"
              onClick={async () => {
                try {
                  await reprocessPaper(paper.id);
                  await load();
                } catch (err) {
                  setError(
                    err instanceof ApiError ? err.message : "Could not retry.",
                  );
                }
              }}
              className="shrink-0 rounded-md bg-oxblood px-[18px] py-[10px] font-ui text-[13px] font-semibold text-on-accent"
            >
              Retry processing
            </button>
          )}
        </div>
      )}
    </div>
  );
}
