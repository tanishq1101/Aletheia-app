"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError, deletePaper } from "@/lib/api";
import { paperTitle } from "@/lib/display";
import { useWorkspace } from "@/lib/workspace";

/** A compact, project-scoped source inventory shared by Ask and Research. */
export default function ProjectSources() {
  const { papers, refresh } = useWorkspace();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const remove = async (id: string, filename: string) => {
    if (!window.confirm(`Delete ${filename}? Its extracted text and search index will also be removed.`)) return;
    setDeletingId(id);
    setError(null);
    try {
      await deletePaper(id);
      await refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not delete the source.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <section className="w-full rounded-lg border border-hairline-subtle bg-surface p-4">
      <div className="mb-3 flex items-center gap-3">
        <div className="min-w-px flex-1">
          <h2 className="font-ui text-sm font-semibold text-primary">Project sources</h2>
          <p className="mt-0.5 font-ui text-xs text-muted">These are the files this project can search and cite.</p>
        </div>
        <Link href="/upload" className="shrink-0 font-ui text-xs font-semibold text-brass hover:text-brass-bright">Add source</Link>
      </div>
      {papers.length === 0 ? (
        <p className="font-ui text-xs text-muted">No sources added yet.</p>
      ) : (
        <ul className="divide-y divide-hairline-subtle">
          {papers.map((paper) => (
            <li key={paper.id} className="flex items-center gap-3 py-2">
              <Link href={`/paper/${paper.id}`} className="min-w-px flex-1 truncate font-ui text-xs text-secondary hover:text-brass" title={paperTitle(paper)}>
                {paper.filename}
              </Link>
              <span className="shrink-0 font-mono text-[9px] uppercase text-muted">{paper.status}</span>
              <button type="button" onClick={() => void remove(paper.id, paper.filename)} disabled={deletingId === paper.id} className="shrink-0 font-ui text-[11px] text-error hover:text-primary disabled:text-muted">
                {deletingId === paper.id ? "Deleting…" : "Delete"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="mt-3 font-ui text-xs text-error">{error}</p>}
    </section>
  );
}
