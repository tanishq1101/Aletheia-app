"use client";

import { useEffect, useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import ClaimCard from "@/components/ClaimCard";
import EmptyState from "@/components/EmptyState";
import PaperSelect from "@/components/PaperSelect";
import { extractClaims, listPaperClaims, verifyClaim } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { Claim, Verdict } from "@/types/api";

type Filter = "all" | Verdict | "unchecked";

const chips: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "supported", label: "Supported" },
  { key: "contradicted", label: "Contradicted" },
  { key: "insufficient", label: "Insufficient" },
  { key: "unchecked", label: "Not checked" },
];

function statusOf(claim: Claim): Filter {
  return claim.verification?.verdict ?? "unchecked";
}

export default function ClaimVerificationPage() {
  const { papers: allPapers, loading: workspaceLoading, error: workspaceError, refresh } =
    useWorkspace();
  const papers = allPapers.filter((paper) => paper.status === "ready");
  // An explicit pick, or null while the user has not made one.
  const [chosenPaperId, setChosenPaperId] = useState<string | null>(null);
  // Resolved during render rather than seeded by an effect: the default
  // is a function of the papers that have loaded, so computing it here
  // avoids the extra render pass an effect-plus-setState would cost.
  const paperId = chosenPaperId ?? papers[0]?.id ?? null;
  const [claims, setClaims] = useState<Claim[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [verifyingIds, setVerifyingIds] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    if (!paperId) return;
    let cancelled = false;

    listPaperClaims(paperId)
      .then((loaded) => {
        if (!cancelled) setClaims(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Could not load claims.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [paperId]);

  const runExtraction = async () => {
    if (!paperId || extracting) return;
    setExtracting(true);
    setError(null);
    try {
      setClaims(await extractClaims(paperId));
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not extract claims."
      );
    } finally {
      setExtracting(false);
    }
  };

  const check = async (claim: Claim) => {
    setVerifyingIds((current) => [...current, claim.id]);
    setError(null);
    try {
      const verification = await verifyClaim(claim.id);
      setClaims((current) =>
        current.map((item) =>
          item.id === claim.id ? { ...item, verification } : item
        )
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not check the claim."
      );
    } finally {
      setVerifyingIds((current) => current.filter((id) => id !== claim.id));
    }
  };

  const checkAll = async () => {
    // Sequential on purpose: each check is a model call, and firing a dozen at
    // once turns one slow page into a rate-limit error.
    for (const claim of claims) {
      await check(claim);
    }
  };

  const counts = Object.fromEntries(
    chips.map((chip) => [
      chip.key,
      chip.key === "all"
        ? claims.length
        : claims.filter((claim) => statusOf(claim) === chip.key).length,
    ])
  ) as Record<Filter, number>;

  const visible =
    filter === "all" ? claims : claims.filter((claim) => statusOf(claim) === filter);

  return (
    <div className="flex w-full flex-col items-start gap-6">
      <h1 className="font-display text-[28px] font-semibold text-primary">
        Claim Verification
      </h1>

      <p className="font-ui text-[13px] text-secondary">
        Claims are extracted from the paper&apos;s own text, then checked against
        evidence retrieved from this project. Every verdict shows the evidence it
        rests on; confidence is what the model reported, not a calibrated
        measurement.
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
          onClick={runExtraction}
          disabled={!paperId || extracting}
          className="shrink-0 rounded-md bg-oxblood px-[18px] py-[10px] font-ui text-[13px] font-semibold text-primary disabled:opacity-50"
        >
          {extracting
            ? "Extracting…"
            : claims.length > 0
              ? "Re-extract claims"
              : "Extract claims"}
        </button>
        {claims.length > 0 && (
          <button
            type="button"
            onClick={checkAll}
            disabled={verifyingIds.length > 0}
            className="shrink-0 rounded-md border border-hairline px-[14px] py-[9px] font-ui text-xs font-medium text-secondary hover:text-primary disabled:text-muted"
          >
            {verifyingIds.length > 0
              ? `Checking ${verifyingIds.length}…`
              : `Check all ${claims.length}`}
          </button>
        )}
      </div>

      {claims.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-start gap-2">
          {chips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={() => setFilter(chip.key)}
              className={`shrink-0 rounded-full px-[14px] py-[7px] ${
                filter === chip.key ? "bg-brass" : "border border-hairline"
              }`}
            >
              <p
                className={`font-ui text-xs font-medium whitespace-nowrap ${
                  filter === chip.key ? "text-base" : "text-secondary"
                }`}
              >
                {chip.label} · {counts[chip.key]}
              </p>
            </button>
          ))}
        </div>
      )}

      {workspaceLoading && papers.length === 0 && !workspaceError ? (
        <p className="font-ui text-sm text-muted">Loading papers…</p>
      ) : papers.length === 0 && !workspaceError ? (
        <EmptyState
          title="No processed papers yet"
          description="Upload one first — claim verification runs against a paper's own text."
          actionLabel="Upload a paper"
          actionHref="/upload"
        />
      ) : (
        <>
          {papers.length > 0 && claims.length === 0 && !extracting && (
            <p className="font-ui text-sm text-muted">
              No claims extracted from this paper yet.
            </p>
          )}

          <div className="flex w-full shrink-0 flex-col items-start gap-3.5">
            {visible.map((claim) => (
              <ClaimCard
                key={claim.id}
                claim={claim}
                onVerify={check}
                verifying={verifyingIds.includes(claim.id)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
