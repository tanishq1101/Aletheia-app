"use client";

import { Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import SearchResultCard from "@/components/SearchResultCard";
import { ApiError, searchProject } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { SearchResult } from "@/types/api";

const TOP_K_OPTIONS = [10, 20, 50];

function SearchPageBody() {
  const { projectId, papers, project } = useWorkspace();
  const params = useSearchParams();
  const initialQuery = params.get("q") ?? "";

  const [query, setQuery] = useState(initialQuery);
  const [topK, setTopK] = useState(20);
  const [paperIds, setPaperIds] = useState<string[]>([]);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastRun = useRef<string | null>(null);

  const run = useCallback(
    async (text: string, k: number) => {
      const trimmed = text.trim();
      if (!trimmed || !projectId) return;
      setSearching(true);
      setError(null);
      try {
        setResults(await searchProject(projectId, trimmed, k, paperIds));
      } catch (err) {
        setResults(null);
        setError(err instanceof ApiError ? err.message : "Search failed.");
      } finally {
        setSearching(false);
      }
    },
    [paperIds, projectId],
  );

  // Run a query handed over from the topbar, once, when a project is ready.
  useEffect(() => {
    if (!initialQuery || !projectId || lastRun.current === initialQuery) return;
    lastRun.current = initialQuery;
    setQuery(initialQuery);
    void run(initialQuery, topK);
  }, [initialQuery, projectId, run, topK]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(query, topK);
  };

  const indexed = papers.filter((p) => p.status === "ready").length;

  return (
    <div className="flex w-full flex-col items-start gap-8">
      <h1 className="font-display text-3xl font-semibold text-primary">
        Semantic search
      </h1>

      <form
        onSubmit={submit}
        className="flex w-full shrink-0 items-center gap-2.5 rounded-lg border border-brass bg-surface px-5 py-4"
      >
        <input
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="papers that challenge the scaling hypothesis for reasoning"
          className="min-w-px flex-1 bg-transparent font-ui text-[15px] text-primary placeholder:text-muted focus:outline-none"
        />
        <button
          type="submit"
          disabled={!projectId || searching || !query.trim()}
          className="shrink-0 font-mono text-[11px] whitespace-nowrap text-brass disabled:text-muted"
        >
          {searching ? "Searching…" : "↵ Search"}
        </button>
      </form>

      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <div className="shrink-0 rounded-full bg-brass px-[14px] py-[7px]">
          <p className="font-ui text-xs font-medium whitespace-nowrap text-base">
            Semantic
          </p>
        </div>
        {TOP_K_OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => {
              setTopK(option);
              if (results) void run(query, option);
            }}
            className={`shrink-0 rounded-full px-[14px] py-[7px] transition-colors ${
              option === topK
                ? "border border-brass"
                : "border border-hairline hover:border-brass"
            }`}
          >
            <p
              className={`font-ui text-xs font-medium whitespace-nowrap ${
                option === topK ? "text-brass" : "text-secondary"
              }`}
            >
              Top {option}
            </p>
          </button>
        ))}
      </div>

      {papers.length > 0 && (
        <fieldset className="flex w-full flex-col gap-2 rounded-md border border-hairline-subtle bg-surface p-4">
          <legend className="px-1 font-ui text-xs font-semibold text-secondary">Search sources</legend>
          <p className="font-ui text-xs text-muted">Leave all unchecked to search every indexed source. Select files to focus the semantic results.</p>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {papers.map((paper) => (
              <label key={paper.id} className="flex max-w-full items-center gap-2 font-ui text-xs text-secondary">
                <input
                  type="checkbox"
                  checked={paperIds.includes(paper.id)}
                  onChange={() => setPaperIds((current) => current.includes(paper.id) ? current.filter((id) => id !== paper.id) : [...current, paper.id])}
                  className="accent-[var(--color-brass)]"
                />
                <span className="max-w-56 truncate">{paper.filename}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {error && <ApiErrorNotice message={error} onRetry={() => void run(query, topK)} />}

      {results === null ? (
        <p className="shrink-0 font-ui text-xs text-muted">
          {indexed === 0
            ? `No indexed papers in ${project?.name ?? "this project"} yet — upload one first.`
          : `Searching across ${paperIds.length || indexed} selected indexed source${(paperIds.length || indexed) === 1 ? "" : "s"}. Results are passages ranked by semantic similarity.`}
        </p>
      ) : (
        <p className="shrink-0 font-ui text-xs text-muted">
          {results.length} passage{results.length === 1 ? "" : "s"}, ranked by
          semantic relevance · source-aware scope
        </p>
      )}

      <div className="flex w-full shrink-0 flex-col items-start gap-4">
        {results?.map((result) => (
          <SearchResultCard key={result.chunk_id} result={result} />
        ))}
        {results?.length === 0 && (
          <p className="font-ui text-sm text-muted">
            Nothing matched. The index only covers papers that finished
            processing.
          </p>
        )}
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<p className="font-ui text-sm text-muted">Loading…</p>}>
      <SearchPageBody />
    </Suspense>
  );
}
