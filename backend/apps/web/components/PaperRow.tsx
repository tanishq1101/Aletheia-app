"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import type { Paper, PaperSection } from "@/types/api";
import { StatusBadge } from "./StatusBadge";

interface Props {
  paper: Paper;
  onRetry: (paperId: string) => Promise<void>;
}

export function PaperRow({ paper, onRetry }: Props) {
  const [sections, setSections] = useState<PaperSection[] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const isReady = paper.status === "ready";
  // Retry is offered for anything not currently running: a failed job, and
  // also a job left pending that no process is going to pick up.
  const canRetry =
    paper.job?.status === "failed" ||
    paper.job?.status === "pending" ||
    paper.status === "failed";

  async function toggleSections() {
    const next = !expanded;
    setExpanded(next);
    if (next && sections === null) {
      try {
        setSections(await api.listSections(paper.id));
      } catch {
        setSections([]);
      }
    }
  }

  async function retry() {
    setRetrying(true);
    try {
      await onRetry(paper.id);
      setSections(null);
    } finally {
      setRetrying(false);
    }
  }

  return (
    <li className="py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">
            {paper.title ?? paper.filename}
          </p>
          <p className="mt-0.5 text-xs text-neutral-500">
            {paper.filename}
            {paper.page_count !== null && ` · ${paper.page_count} pages`}
          </p>
          {isReady && (
            <button
              onClick={toggleSections}
              className="mt-1 text-xs font-medium text-neutral-600 underline dark:text-neutral-400"
            >
              {expanded ? "Hide sections" : "Show sections"}
            </button>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <StatusBadge paper={paper} />
          {canRetry && (
            <button
              onClick={retry}
              disabled={retrying}
              className="rounded-md border border-neutral-300 px-2 py-0.5 text-xs font-medium disabled:opacity-40 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              {retrying ? "Retrying…" : "Retry"}
            </button>
          )}
        </div>
      </div>

      {paper.job?.error && (
        <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
          {paper.job.error}
        </p>
      )}

      {expanded && sections !== null && (
        <ul className="mt-2 border-l border-neutral-200 pl-3 dark:border-neutral-800">
          {sections.length === 0 ? (
            <li className="py-0.5 text-xs text-neutral-500">
              No sections detected.
            </li>
          ) : (
            sections.map((section) => (
              <li
                key={section.id}
                className="py-0.5 text-xs text-neutral-600 dark:text-neutral-400"
                style={{ paddingLeft: `${(section.level - 1) * 12}px` }}
              >
                {section.title}
                <span className="ml-2 opacity-60">p{section.start_page}</span>
              </li>
            ))
          )}
        </ul>
      )}
    </li>
  );
}
