"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import type { SearchResult } from "@/types/api";

interface Props {
  projectId: string | null;
  hasReadyPapers: boolean;
  onError: (message: string) => void;
}

export function SearchPanel({ projectId, hasReadyPapers, onError }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!projectId || !query.trim() || searching) return;

    setSearching(true);
    try {
      setResults(await api.searchProject(projectId, query.trim()));
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
      setResults(null);
    } finally {
      setSearching(false);
    }
  }

  const disabled = !projectId || !hasReadyPapers;

  return (
    <section className="mt-12 border-t border-neutral-200 pt-8 dark:border-neutral-800">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
          Semantic search
        </h2>
        <span className="text-xs text-neutral-500">
          raw candidates · before reranking
        </span>
      </div>

      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={disabled}
          placeholder={
            disabled
              ? "Upload and process a paper first"
              : "Ask something about the papers in this project…"
          }
          className="flex-1 rounded-md border border-neutral-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-neutral-500 disabled:opacity-50 dark:border-neutral-700"
        />
        <button
          type="submit"
          disabled={disabled || !query.trim() || searching}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-neutral-900"
        >
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      {results !== null && (
        <div className="mt-5">
          {results.length === 0 ? (
            <p className="text-sm text-neutral-500">No matching passages.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {results.map((result) => (
                <li
                  key={result.chunk_id}
                  className="rounded-md border border-neutral-200 p-3 dark:border-neutral-800"
                >
                  <div className="flex items-baseline justify-between gap-3 text-xs text-neutral-500">
                    <span className="truncate">
                      {result.paper_title ?? result.filename}
                      {result.section && ` · ${result.section}`}
                      {result.page_number !== null &&
                        ` · page ${result.page_number}`}
                    </span>
                    <span className="shrink-0 font-mono">
                      {result.similarity.toFixed(3)}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm leading-relaxed">
                    {result.content.length > 400
                      ? `${result.content.slice(0, 400)}…`
                      : result.content}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
