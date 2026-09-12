"use client";

import { useEffect, useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import CitationCard from "@/components/CitationCard";
import ClaimAgreementTable from "@/components/ClaimAgreementTable";
import {
  buildCrossPaperMatrix,
  getStoredCrossPaperMatrix,
  listProjectClaims,
} from "@/lib/api";
import { paperTitle } from "@/lib/display";
import { useWorkspace } from "@/lib/workspace";
import type { Claim, CrossPaperCell } from "@/types/api";

const MAX_CLAIMS = 5;
const MAX_PAPERS = 5;

function toggle(list: string[], id: string, max: number): string[] {
  if (list.includes(id)) return list.filter((item) => item !== id);
  if (list.length >= max) return list;
  return [...list, id];
}

export default function CrossPaperPage() {
  const {
    projectId,
    papers: allPapers,
    loading: workspaceLoading,
    error: workspaceError,
    refresh,
  } = useWorkspace();
  const papers = allPapers.filter((paper) => paper.status === "ready");
  const [claims, setClaims] = useState<Claim[]>([]);
  const [selectedPapers, setSelectedPapers] = useState<string[]>([]);
  const [selectedClaims, setSelectedClaims] = useState<string[]>([]);
  const [cells, setCells] = useState<CrossPaperCell[]>([]);
  const [inspecting, setInspecting] = useState<CrossPaperCell | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seeded, setSeeded] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    listProjectClaims(projectId)
      .then((loadedClaims) => {
        if (cancelled) return;
        setClaims(loadedClaims);
        if (!seeded) {
          setSelectedPapers(papers.slice(0, 3).map((paper) => paper.id));
          setSelectedClaims(loadedClaims.slice(0, 3).map((claim) => claim.id));
          setSeeded(true);
        }
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Could not load claims.");
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, papers.length]);

  // Show what has already been checked before spending anything.
  useEffect(() => {
    if (!projectId || selectedClaims.length === 0 || selectedPapers.length === 0) {
      return;
    }
    let cancelled = false;

    getStoredCrossPaperMatrix(projectId, selectedClaims, selectedPapers)
      .then((matrix) => {
        if (!cancelled) setCells(matrix.cells);
      })
      .catch(() => {
        // Cached-state lookup; a failure here is not worth blocking the page.
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, selectedClaims, selectedPapers]);

  const run = async (refresh: boolean) => {
    if (!projectId || running) return;
    setRunning(true);
    setError(null);
    try {
      const matrix = await buildCrossPaperMatrix(
        projectId,
        selectedClaims,
        selectedPapers,
        refresh
      );
      setCells(matrix.cells);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not build the matrix."
      );
    } finally {
      setRunning(false);
    }
  };

  const visibleClaims = claims.filter((claim) => selectedClaims.includes(claim.id));
  const visiblePapers = papers.filter((paper) => selectedPapers.includes(paper.id));
  const checkedCount = cells.filter(
    (cell) =>
      selectedClaims.includes(cell.claim_id) && selectedPapers.includes(cell.paper_id)
  ).length;
  const total = selectedClaims.length * selectedPapers.length;

  return (
    <div className="flex w-full flex-col items-start gap-6">
      <h1 className="font-display text-[28px] font-semibold text-primary">
        Cross-Paper Workspace
      </h1>

      <p className="font-ui text-[13px] text-secondary">
        Each cell checks one claim against one paper&apos;s own evidence, so a
        paper can only agree with a claim it actually discusses. Every cell is a
        separate model call — results are cached and reused.
      </p>

      {(error || workspaceError) && (
        <ApiErrorNotice
          message={error ?? workspaceError ?? ""}
          onRetry={workspaceError ? () => void refresh() : undefined}
        />
      )}

      {!workspaceLoading && (papers.length === 0 || claims.length === 0) && (
        <p className="font-ui text-sm text-muted">
          {papers.length === 0
            ? "No processed papers in this project yet."
            : "No claims yet — extract some on the Claim Verification page first."}
        </p>
      )}

      {papers.length > 0 && (
        <div className="flex w-full flex-col items-start gap-2">
          <p className="font-ui text-[11px] font-semibold tracking-wide text-muted">
            PAPERS ({selectedPapers.length}/{MAX_PAPERS})
          </p>
          <div className="flex w-full flex-wrap items-start gap-2.5">
            {papers.map((paper) => {
              const active = selectedPapers.includes(paper.id);
              return (
                <button
                  key={paper.id}
                  type="button"
                  onClick={() =>
                    setSelectedPapers((current) =>
                      toggle(current, paper.id, MAX_PAPERS)
                    )
                  }
                  className={`flex shrink-0 items-center gap-2 rounded-full border px-[14px] py-2 ${
                    active ? "border-brass bg-surface" : "border-hairline bg-surface"
                  }`}
                >
                  <span
                    className={`size-1.5 shrink-0 rounded-full ${active ? "bg-brass" : "bg-muted"}`}
                  />
                  <p
                    className={`max-w-[280px] truncate font-ui text-xs font-medium ${
                      active ? "text-primary" : "text-muted"
                    }`}
                  >
                    {paperTitle(paper)}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {claims.length > 0 && (
        <div className="flex w-full flex-col items-start gap-2">
          <p className="font-ui text-[11px] font-semibold tracking-wide text-muted">
            CLAIMS ({selectedClaims.length}/{MAX_CLAIMS})
          </p>
          <div className="flex w-full flex-col items-start gap-px">
            {claims.map((claim) => {
              const active = selectedClaims.includes(claim.id);
              return (
                <button
                  key={claim.id}
                  type="button"
                  onClick={() =>
                    setSelectedClaims((current) =>
                      toggle(current, claim.id, MAX_CLAIMS)
                    )
                  }
                  className="flex w-full items-start gap-3 bg-surface px-4 py-2.5 text-left hover:bg-surface-raised"
                >
                  <span
                    className={`mt-1 size-3 shrink-0 rounded-[3px] border ${
                      active ? "border-brass bg-brass" : "border-hairline"
                    }`}
                  />
                  <p
                    className={`min-w-px flex-1 font-ui text-[13px] ${
                      active ? "text-primary" : "text-muted"
                    }`}
                  >
                    {claim.text}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {total > 0 && (
        <div className="flex w-full flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={() => run(false)}
            disabled={running}
            className="shrink-0 rounded-md bg-oxblood px-[18px] py-[10px] font-ui text-[13px] font-semibold text-primary disabled:opacity-50"
          >
            {running
              ? "Checking…"
              : `Run ${total - checkedCount || total} check${
                  (total - checkedCount || total) === 1 ? "" : "s"
                }`}
          </button>
          {checkedCount > 0 && (
            <button
              type="button"
              onClick={() => run(true)}
              disabled={running}
              className="shrink-0 rounded-md border border-hairline px-[14px] py-[9px] font-ui text-xs font-medium text-secondary hover:text-primary disabled:text-muted"
            >
              Re-check all {total}
            </button>
          )}
          <p className="font-ui text-xs text-muted">
            {checkedCount} of {total} cells checked
          </p>
        </div>
      )}

      {visibleClaims.length > 0 && visiblePapers.length > 0 && (
        <>
          <p className="font-ui text-[15px] font-semibold text-primary">
            Claim agreement matrix
          </p>
          <ClaimAgreementTable
            papers={visiblePapers}
            claims={visibleClaims}
            cells={cells}
            onSelectCell={setInspecting}
          />
        </>
      )}

      {inspecting && (
        <div className="flex w-full flex-col items-start gap-3 rounded-md border border-hairline bg-surface px-5 py-4">
          <div className="flex w-full items-center gap-3">
            <p className="min-w-px flex-1 font-ui text-[13px] font-semibold text-primary">
              Why this verdict
            </p>
            <button
              type="button"
              onClick={() => setInspecting(null)}
              className="shrink-0 font-ui text-xs text-muted hover:text-secondary"
            >
              Close
            </button>
          </div>
          <p className="w-full font-reading text-[13px] text-secondary">
            {inspecting.verification.rationale}
          </p>
          {inspecting.verification.citations.map((citation) => (
            <CitationCard key={citation.evidence_id} citation={citation} />
          ))}
          {inspecting.verification.citations.length === 0 && (
            <p className="font-ui text-xs text-muted">
              No evidence from this paper was cited.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
