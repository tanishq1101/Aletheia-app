"use client";

import ResearchMarkdown from "@/components/ResearchMarkdown";
import EvidenceOverview from "@/components/EvidenceOverview";
import { useId, useState } from "react";
import Link from "next/link";
import { matchPercent } from "@/lib/display";
import type { AnswerResponse } from "@/types/api";

export default function AnswerView({ result }: { result: AnswerResponse }) {
  const citationPrefix = useId();
  const focusCitation = (id: string) => {
    setFocused(id);
    document.getElementById(`${citationPrefix}-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
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
              {result.truncated ? "Partial response — output limit reached" : "Insufficient evidence"}
            </p>
          </div>
        )}

        {result.truncated && <p className="text-sm text-secondary">The provider stopped before finishing. Ask a narrower question, or increase the response budget in the API configuration when credits allow.</p>}
        <ResearchMarkdown
          text={result.answer}
          known={known}
          onFocus={focusCitation}
        />

        <p className="font-mono text-[10px] text-muted">
          {result.model} · {result.candidates_considered} candidates →{" "}
          {result.evidence.length} evidence blocks
          {result.evidence_dropped_for_budget > 0 &&
            ` · ${result.evidence_dropped_for_budget} dropped for context budget`}
        </p>
      </div>

      {(result.charts ?? []).map((chart, index) => <figure key={index} className="w-full rounded border border-hairline bg-surface p-5"><figcaption className="font-semibold">{chart.title} ({chart.unit})</figcaption><p className="mb-4 text-xs text-secondary">Conditions: {chart.conditions}</p>{chart.points.map(point => <div key={point.label} className="mb-4"><div className="mb-1 flex flex-wrap items-center gap-2 text-sm"><strong>{point.label}</strong><span>{point.value} {chart.unit}</span>{point.evidence_ids.map(id => <button type="button" key={id} onClick={() => focusCitation(id)} className="rounded border border-brass px-1 text-xs text-brass">{id}</button>)}</div><div role="img" aria-label={`${point.label}: ${point.value} ${chart.unit}`} className="h-4 rounded bg-brass" style={{width: `${100 * point.value / Math.max(1, ...chart.points.map(p => p.value))}%`}} /></div>)}<p className="text-xs italic text-muted">{chart.note}</p></figure>)}
      <EvidenceOverview result={result} />
      {(result.model_diagnostics ?? []).length > 0 && <details className="w-full rounded border border-hairline p-4 text-sm"><summary className="cursor-pointer font-semibold">Experimental model analysis</summary><p className="my-3 italic text-secondary">These scores are uncalibrated diagnostics, not verification. The stance model performed poorly in held-out testing and does not determine this answer.</p>{result.model_diagnostics!.map((model) => <div key={model.task} className="mt-4 overflow-x-auto"><p className="font-semibold capitalize">{model.task} · {model.status}</p><p className="my-2 text-xs text-muted">{model.note}</p>{model.scores.length > 0 && <table className="w-full text-left text-xs"><thead><tr><th className="p-2">Evidence</th>{model.labels.map(label => <th className="p-2" key={label}>{label.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{model.scores.map(row => <tr key={row.evidence_id}><td className="p-2">{row.evidence_id}</td>{row.values.map((value, i) => <td className="p-2 font-mono" key={i}>{value.toFixed(3)}</td>)}</tr>)}</tbody></table>}</div>)}</details>}
      {result.citations.length > 0 && (
        <div className="flex w-full shrink-0 flex-col items-start gap-3">
          <p className="font-ui text-[15px] font-semibold text-primary">
            Citations
          </p>
          {result.citations.map((citation) => (
            <div
              key={citation.evidence_id}
              id={`${citationPrefix}-${citation.evidence_id}`}
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
                  href={citation.source_url ?? `/paper/${citation.paper_id}`}
                  target={citation.source_url ? "_blank" : undefined}
                  rel={citation.source_url ? "noopener noreferrer" : undefined}
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
                    {item.location}{item.source_url ? " · public abstract" : ` · ${matchPercent(item.similarity)}% · rerank ${item.rerank_score.toFixed(2)}`}
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
