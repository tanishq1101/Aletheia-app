"use client";

import { useState } from "react";
import Link from "next/link";
import { matchPercent } from "@/lib/display";
import type { AnswerResponse } from "@/types/api";

// Mirrors the backend's own citation pattern: an ID inside brackets, so a
// stray "E1" in the paper's prose is not turned into a link. Built per call --
// a shared /g regex carries `lastIndex` between renders.
const citationPattern = () => /\[([^[\]]*?E\d+[^[\]]*?)\]/g;

/** Renders the answer with its [E1, E3] markers turned into pills that jump to
 *  the resolved citation. The backend has already stripped any ID it did not
 *  issue, so every marker left here resolves. */
function AnswerText({
  text,
  known,
  onFocus,
}: {
  text: string;
  known: Set<string>;
  onFocus: (id: string) => void;
}) {
  const nodes: React.ReactNode[] = [];
  const pattern = citationPattern();
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    const ids = match[1].match(/E\d+/g) ?? [];
    nodes.push(
      <span key={`${match.index}-cite`} className="whitespace-nowrap">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onFocus(id)}
            disabled={!known.has(id)}
            className="mx-[2px] rounded-[3px] border border-brass px-1 py-px align-baseline font-mono text-[10px] text-brass transition-colors hover:bg-brass hover:text-base disabled:border-hairline disabled:text-muted"
          >
            {id}
          </button>
        ))}
      </span>,
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));

  return (
    <p className="w-full font-reading text-base whitespace-pre-wrap text-primary">
      {nodes}
    </p>
  );
}

export default function AnswerView({ result }: { result: AnswerResponse }) {
  const [showEvidence, setShowEvidence] = useState(false);
  const [focused, setFocused] = useState<string | null>(null);

  const known = new Set(result.citations.map((c) => c.evidence_id));
  const uncited = result.evidence.filter((e) => !known.has(e.evidence_id));

  return (
    <div className="flex w-full flex-col items-start gap-5">
      {/* Must be 0. When it is not, that is the most important thing here. */}
      {result.fabricated_citations_removed > 0 && (
        <div className="flex w-full shrink-0 items-start gap-3 rounded-md border border-oxblood bg-surface px-[18px] py-3.5">
          <span className="mt-[5px] size-[6px] shrink-0 rounded-full bg-error" />
          <p className="min-w-px flex-1 font-ui text-xs text-secondary">
            <span className="font-semibold text-error">
              {result.fabricated_citations_removed} fabricated citation
              {result.fabricated_citations_removed === 1 ? "" : "s"} removed.{" "}
            </span>
            The model cited an evidence ID it was never given. The IDs were
            stripped before this answer was returned, but the text around them
            is worth reading sceptically.
          </p>
        </div>
      )}

      <div
        className={`flex w-full shrink-0 flex-col items-start gap-4 rounded-lg border bg-surface px-7 py-6 ${
          result.sufficient_evidence ? "border-hairline-subtle" : "border-brass"
        }`}
      >
        {!result.sufficient_evidence && (
          <div className="flex shrink-0 items-center gap-2 rounded-full border border-brass px-2.5 py-1">
            <span className="size-[5px] shrink-0 rounded-full bg-brass" />
            <p className="font-mono text-[10px] whitespace-nowrap text-brass">
              Insufficient evidence
            </p>
          </div>
        )}

        <AnswerText
          text={result.answer}
          known={known}
          onFocus={(id) => setFocused((current) => (current === id ? null : id))}
        />

        <p className="font-mono text-[10px] text-muted">
          {result.model} · {result.candidates_considered} candidates →{" "}
          {result.evidence.length} evidence blocks
          {result.evidence_dropped_for_budget > 0 &&
            ` · ${result.evidence_dropped_for_budget} dropped for context budget`}
        </p>
      </div>

      {result.citations.length > 0 && (
        <div className="flex w-full shrink-0 flex-col items-start gap-3">
          <p className="font-ui text-[15px] font-semibold text-primary">
            Citations
          </p>
          {result.citations.map((citation) => (
            <div
              key={citation.evidence_id}
              className={`flex w-full shrink-0 flex-col items-start gap-2 rounded-md border bg-surface px-5 py-4 transition-colors ${
                focused === citation.evidence_id
                  ? "border-brass"
                  : "border-hairline-subtle"
              }`}
            >
              <div className="flex w-full items-center gap-3">
                <span className="shrink-0 rounded-[3px] border border-brass px-1.5 py-px font-mono text-[10px] text-brass">
                  {citation.evidence_id}
                </span>
                <Link
                  href={`/paper/${citation.paper_id}`}
                  className="min-w-px flex-1 truncate font-ui text-[13px] font-medium text-primary hover:text-brass-bright"
                >
                  {citation.paper_title ?? "Untitled paper"}
                </Link>
                <p className="shrink-0 font-mono text-[10px] whitespace-nowrap text-muted">
                  {citation.location}
                </p>
              </div>
              <p className="w-full font-reading text-sm text-secondary">
                {citation.snippet}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Retrieval stays inspectable on its own: an answer that ignored good
          evidence and one built on bad evidence read alike otherwise. */}
      {result.evidence.length > 0 && (
        <div className="flex w-full shrink-0 flex-col items-start gap-3">
          <button
            type="button"
            onClick={() => setShowEvidence((open) => !open)}
            className="font-ui text-xs font-medium text-brass hover:text-brass-bright"
          >
            {showEvidence ? "Hide" : "Show"} all {result.evidence.length} evidence
            blocks{uncited.length > 0 && ` · ${uncited.length} not cited`}
          </button>

          {showEvidence &&
            result.evidence.map((item) => (
              <div
                key={item.evidence_id}
                className="flex w-full shrink-0 flex-col items-start gap-2 rounded-md border border-hairline-subtle bg-surface-raised px-5 py-4"
              >
                <div className="flex w-full items-center gap-3">
                  <span
                    className={`shrink-0 rounded-[3px] border px-1.5 py-px font-mono text-[10px] ${
                      known.has(item.evidence_id)
                        ? "border-brass text-brass"
                        : "border-hairline text-muted"
                    }`}
                  >
                    {item.evidence_id}
                  </span>
                  <p className="min-w-px flex-1 truncate font-ui text-[13px] text-primary">
                    {item.paper_title ?? "Untitled paper"}
                  </p>
                  <p className="shrink-0 font-mono text-[10px] whitespace-nowrap text-muted">
                    {item.location} · {matchPercent(item.similarity)}% · rerank{" "}
                    {item.rerank_score.toFixed(2)}
                  </p>
                </div>
                <p className="w-full font-reading text-sm whitespace-pre-wrap text-secondary">
                  {item.content}
                </p>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
