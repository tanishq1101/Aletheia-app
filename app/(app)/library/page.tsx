"use client";

import Link from "next/link";
import { useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import EmptyState from "@/components/EmptyState";
import PaperCard from "@/components/PaperCard";
import { statusLabel } from "@/lib/display";
import { useWorkspace } from "@/lib/workspace";
import type { PaperStatus } from "@/types/api";

const FILTERS: { key: PaperStatus | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "ready", label: statusLabel.ready },
  { key: "processing", label: statusLabel.processing },
  { key: "failed", label: statusLabel.failed },
];

export default function LibraryPage() {
  const { papers, loading, error, refresh, project } = useWorkspace();
  const [filter, setFilter] = useState<PaperStatus | "all">("all");

  const countFor = (key: PaperStatus | "all") =>
    key === "all"
      ? papers.length
      : key === "processing"
        // "Queued" is a processing paper the worker hasn't reached yet;
        // splitting them into two chips would be noise.
        ? papers.filter((p) => p.status === "processing" || p.status === "uploaded")
            .length
        : papers.filter((p) => p.status === key).length;

  const visible =
    filter === "all"
      ? papers
      : filter === "processing"
        ? papers.filter((p) => p.status === "processing" || p.status === "uploaded")
        : papers.filter((p) => p.status === filter);

  return (
    <div className="flex w-full flex-col items-start gap-6">
      <div className="flex w-full items-center gap-4">
        <h1 className="flex-1 font-display text-3xl font-semibold text-primary">
          Library
        </h1>
        <Link
          href="/upload"
          className="shrink-0 rounded-md bg-oxblood px-[18px] py-[10px] font-ui text-[13px] font-semibold text-primary"
        >
          + Upload paper
        </Link>
      </div>

      {project && (
        <p className="font-ui text-[13px] text-secondary">
          {project.name} · {papers.length} paper{papers.length === 1 ? "" : "s"}
        </p>
      )}

      {error && <ApiErrorNotice message={error} onRetry={() => void refresh()} />}

      <div className="flex shrink-0 items-start gap-2">
        {FILTERS.map((chip) => {
          const active = chip.key === filter;
          return (
            <button
              key={chip.key}
              type="button"
              onClick={() => setFilter(chip.key)}
              className={`shrink-0 rounded-full px-[14px] py-[7px] transition-colors ${
                active ? "bg-brass" : "border border-hairline hover:border-brass"
              }`}
            >
              <p
                className={`font-ui text-xs font-medium whitespace-nowrap ${
                  active ? "text-base" : "text-secondary"
                }`}
              >
                {chip.label} · {countFor(chip.key)}
              </p>
            </button>
          );
        })}
      </div>

      {loading && papers.length === 0 && !error ? (
        <p className="font-ui text-sm text-muted">Loading papers…</p>
      ) : papers.length === 0 && !error ? (
        <EmptyState
          title="No papers yet"
          description="Upload a PDF and the API will extract its text, chunk it, embed it, and index it for search."
          actionLabel="Upload a paper"
          actionHref="/upload"
        />
      ) : (
        <div className="flex w-full flex-wrap items-start gap-x-5 gap-y-5">
          {visible.map((paper) => (
            <PaperCard key={paper.id} paper={paper} />
          ))}
          {visible.length === 0 && (
            <p className="font-ui text-sm text-muted">
              No papers with that status.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
