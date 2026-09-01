"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import type { AnswerResponse, Citation } from "@/types/api";

interface Props {
  projectId: string | null;
  hasReadyPapers: boolean;
  onError: (message: string) => void;
}

/** Split answer text so `[E1]` and `[E1, E3]` render as clickable markers.
 *  The backend has already stripped any ID it did not issue, so every marker
 *  reaching here resolves to a real citation (PRD 5.3). */
function renderAnswer(
  answer: string,
  citations: Citation[],
  onJump: (evidenceId: string) => void,
) {
  const known = new Map(citations.map((c) => [c.evidence_id, c]));
  const parts = answer.split(/(\[[^\[\]]*?E\d+[^\[\]]*?\])/g);

  return parts.map((part, index) => {
    const match = part.match(/^\[(.*)\]$/);
    if (!match) return <span key={index}>{part}</span>;

    const ids = match[1].split(",").map((id) => id.trim());
    return (
      <span key={index}>
        {ids.map((id) => {
          const citation = known.get(id);
          // Only reachable if an ID was cited but resolved to nothing, which
          // the backend already prevents. Render it inert rather than as a
          // clickable source that goes nowhere.
          if (!citation) return <span key={id}>{id}</span>;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onJump(id)}
              title={`${citation.paper_title ?? "Paper"} — ${citation.location}`}
              className="mx-0.5 rounded bg-neutral-200 px-1.5 py-0.5 align-baseline font-mono text-[11px] text-neutral-700 hover:bg-neutral-300 dark:bg-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-700"
            >
              {id}
            </button>
          );
        })}
      </span>
    );
  });
}

export function AnswerPanel({ projectId, hasReadyPapers, onError }: Props) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnswerResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [highlighted, setHighlighted] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!projectId || !question.trim() || asking) return;

    setAsking(true);
    setHighlighted(null);
    try {
      setResult(await api.answerQuestion(projectId, question.trim()));
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
      setResult(null);
    } finally {
      setAsking(false);
    }
  }

  function jump(evidenceId: string) {
    setHighlighted(evidenceId);
    document
      .getElementById(`evidence-${evidenceId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const disabled = !projectId || !hasReadyPapers;

  return (
    <section className="mt-12 border-t border-neutral-200 pt-8 dark:border-neutral-800">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
          Grounded answer
        </h2>
        <span className="text-xs text-neutral-500">
          retrieve → rerank → cite
        </span>
      </div>

      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={disabled}
          placeholder={
            disabled
              ? "Upload and process a paper first"
              : "Ask a question about the papers in this project…"
          }
          className="flex-1 rounded-md border border-neutral-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-neutral-500 disabled:opacity-50 dark:border-neutral-700"
        />
        <button
          type="submit"
          disabled={disabled || !question.trim() || asking}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-neutral-900"
        >
          {asking ? "Thinking…" : "Ask"}
        </button>
      </form>

      {asking && (
        <p className="mt-4 text-sm text-neutral-500">
          Retrieving, reranking, and asking the model…
        </p>
      )}

      {result && !asking && (
        <div className="mt-5">
          {/* An unsupported answer is a legitimate outcome, not a failure. */}
          {!result.sufficient_evidence && (
            <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
              The papers in this project do not contain enough evidence to
              answer that.
            </p>
          )}

          {/* Should always be zero. If it is not, say so loudly rather than
              quietly rendering a cleaned-up answer (PRD Section 12). */}
          {result.fabricated_citations_removed > 0 && (
            <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
              {result.fabricated_citations_removed} citation
              {result.fabricated_citations_removed === 1 ? "" : "s"} referenced
              evidence that was never supplied, and{" "}
              {result.fabricated_citations_removed === 1 ? "was" : "were"}{" "}
              removed from this answer.
            </p>
          )}

          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {renderAnswer(result.answer, result.citations, jump)}
          </p>

          {result.citations.length > 0 && (
            <>
              <h3 className="mt-6 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                Sources
              </h3>
              <ul className="mt-2 flex flex-col gap-3">
                {result.citations.map((citation) => (
                  <li
                    key={citation.evidence_id}
                    id={`evidence-${citation.evidence_id}`}
                    className={`rounded-md border p-3 transition-colors ${
                      highlighted === citation.evidence_id
                        ? "border-neutral-500 bg-neutral-50 dark:bg-neutral-900"
                        : "border-neutral-200 dark:border-neutral-800"
                    }`}
                  >
                    <div className="flex items-baseline gap-2 text-xs text-neutral-500">
                      <span className="rounded bg-neutral-200 px-1.5 py-0.5 font-mono text-[11px] text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
                        {citation.evidence_id}
                      </span>
                      <span className="truncate">
                        {citation.paper_title ?? "Untitled paper"} ·{" "}
                        {citation.location}
                      </span>
                    </div>
                    <p className="mt-1.5 text-sm leading-relaxed text-neutral-700 dark:text-neutral-300">
                      {citation.snippet}
                    </p>
                  </li>
                ))}
              </ul>
            </>
          )}

          <p className="mt-5 text-xs text-neutral-500">
            {result.candidates_considered} candidate
            {result.candidates_considered === 1 ? "" : "s"} retrieved ·{" "}
            {result.evidence.length} reranked into evidence ·{" "}
            {result.citations.length} cited · {result.model}
            {result.evidence_dropped_for_budget > 0 &&
              ` · ${result.evidence_dropped_for_budget} dropped for context budget`}
          </p>
        </div>
      )}
    </section>
  );
}
