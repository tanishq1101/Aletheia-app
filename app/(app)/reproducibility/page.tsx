"use client";

import { useEffect, useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import CheckStatusIcon from "@/components/CheckStatusIcon";
import CitationCard from "@/components/CitationCard";
import EmptyState from "@/components/EmptyState";
import PaperSelect from "@/components/PaperSelect";
import RepoMetadataCard from "@/components/RepoMetadataCard";
import { getReproducibilityReport, runReproducibilityReport } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { ReproducibilityReport } from "@/types/api";

function ChecklistRow({
  check,
}: {
  check: ReproducibilityReport["checks"][number];
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex w-full flex-col items-start gap-2 bg-surface px-[18px] py-3">
      <div className="flex w-full items-center gap-3">
        <CheckStatusIcon status={check.status} />
        <p className="min-w-px flex-1 font-ui text-[13px] text-primary">
          {check.dimension}
        </p>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="shrink-0 font-ui text-xs font-medium text-brass hover:text-brass-bright"
        >
          {expanded ? "Hide" : "Why"}
        </button>
      </div>

      {expanded && (
        <div className="flex w-full flex-col items-start gap-2 pl-8">
          <p className="w-full font-reading text-[13px] text-secondary">
            {check.rationale}
          </p>
          {check.citations.map((citation) => (
            <CitationCard key={citation.evidence_id} citation={citation} />
          ))}
          {check.citations.length === 0 && (
            <p className="font-ui text-xs text-muted">
              No evidence in the paper addressed this.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function ReproducibilityPage() {
  const { papers: allPapers, loading: workspaceLoading, error: workspaceError, refresh } =
    useWorkspace();
  const papers = allPapers.filter((paper) => paper.status === "ready");
  // An explicit pick, or null while the user has not made one.
  const [chosenPaperId, setChosenPaperId] = useState<string | null>(null);
  // Resolved during render rather than seeded by an effect: the default
  // is a function of the papers that have loaded, so computing it here
  // avoids the extra render pass an effect-plus-setState would cost.
  const paperId = chosenPaperId ?? papers[0]?.id ?? null;
  const [report, setReport] = useState<ReproducibilityReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Show a stored report immediately; auditing costs six model calls.
  useEffect(() => {
    if (!paperId) return;
    let cancelled = false;

    getReproducibilityReport(paperId)
      .then((stored) => {
        if (!cancelled) setReport(stored);
      })
      .catch(() => {
        if (!cancelled) setReport(null);
      });

    return () => {
      cancelled = true;
    };
  }, [paperId]);

  const run = async () => {
    if (!paperId || running) return;
    setRunning(true);
    setError(null);
    try {
      setReport(await runReproducibilityReport(paperId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not audit the paper.");
    } finally {
      setRunning(false);
    }
  };

  const percent = report ? Math.round(report.score * 100) : null;

  return (
    <div className="flex w-full flex-col items-start gap-6">
      <h1 className="font-display text-[28px] font-semibold text-primary">
        Reproducibility Checker
      </h1>

      <p className="font-ui text-[13px] text-secondary">
        Scores what the paper <em>discloses</em> — code, data, hyperparameters,
        seeds, environment and evaluation protocol — with the evidence behind
        each verdict. Nothing here runs the paper&apos;s code, so this is a
        disclosure score, not a replication result.
      </p>

      {(error || workspaceError) && (
        <ApiErrorNotice
          message={error ?? workspaceError ?? ""}
          onRetry={workspaceError ? () => void refresh() : undefined}
        />
      )}

      <div className="flex w-full flex-wrap items-center gap-4">
        <PaperSelect papers={papers} value={paperId} onChange={setChosenPaperId} />
        <button
          type="button"
          onClick={run}
          disabled={!paperId || running}
          className="shrink-0 rounded-md bg-oxblood px-[18px] py-[10px] font-ui text-[13px] font-semibold text-primary disabled:opacity-50"
        >
          {running ? "Auditing…" : report ? "Re-run audit" : "Run audit"}
        </button>
        {percent !== null && (
          <div className="flex shrink-0 items-center gap-2">
            <p className="font-display text-2xl font-semibold text-primary">
              {percent}%
            </p>
            <p className="font-ui text-xs text-muted">
              disclosure score
              <br />
              {report?.checks.filter((c) => c.status === "disclosed").length} of{" "}
              {report?.checks.length} fully disclosed
            </p>
          </div>
        )}
      </div>

      {workspaceLoading && papers.length === 0 && !workspaceError ? (
        <p className="font-ui text-sm text-muted">Loading papers…</p>
      ) : papers.length === 0 && !workspaceError ? (
        <EmptyState
          title="No processed papers yet"
          description="Upload one first — the reproducibility audit runs against a paper's own text."
          actionLabel="Upload a paper"
          actionHref="/upload"
        />
      ) : (
        !report &&
        !running && (
          <p className="font-ui text-sm text-muted">
            This paper has not been audited yet.
          </p>
        )
      )}

      {report && (
        <>
          <RepoMetadataCard repo={report.repo_metadata} links={report.links} />

          <p className="font-ui text-[15px] font-semibold text-primary">
            Disclosure checklist
          </p>

          <div className="flex w-full shrink-0 flex-col items-start gap-px">
            {report.checks.map((check) => (
              <ChecklistRow key={check.check_index} check={check} />
            ))}
          </div>

          {report.links.length > 0 && (
            <div className="flex w-full flex-col items-start gap-2">
              <p className="font-ui text-[15px] font-semibold text-primary">
                Links found in the paper
              </p>
              {report.links.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="font-mono text-xs text-brass hover:text-brass-bright"
                >
                  {link.kind}: {link.url}
                </a>
              ))}
            </div>
          )}

          <p className="font-ui text-[10px] text-muted">
            Audited with {report.model ?? "an unnamed model"} on{" "}
            {new Date(report.created_at).toLocaleString()}
          </p>
        </>
      )}
    </div>
  );
}
