"use client";

import { useState } from "react";
import CitationCard from "@/components/CitationCard";
import ClaimStatusBadge, { verdictTone } from "@/components/ClaimStatusBadge";
import ConfidenceMeter from "@/components/ConfidenceMeter";
import type { Claim } from "@/types/api";

export default function ClaimCard({
  claim,
  onVerify,
  verifying,
}: {
  claim: Claim;
  onVerify: (claim: Claim) => void;
  verifying: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const verification = claim.verification;
  const tone = verdictTone[verification?.verdict ?? "unchecked"];

  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-[14px] rounded-md border border-hairline-subtle bg-surface px-[22px] py-[18px]">
      <div className="flex w-full items-center gap-4">
        <p className="min-w-px flex-1 font-ui text-sm font-medium text-primary">
          {claim.text}
        </p>
        <ClaimStatusBadge verdict={verification?.verdict ?? "unchecked"} />
      </div>

      <div className="flex w-full items-center gap-4">
        <ConfidenceMeter confidence={verification?.confidence ?? null} tone={tone} />
        <p className="shrink-0 font-ui text-xs whitespace-nowrap text-secondary">
          {verification
            ? `${verification.citations.length} cited of ${verification.evidence_count} evidence`
            : "Not checked yet"}
        </p>
        <button
          type="button"
          onClick={() => onVerify(claim)}
          disabled={verifying}
          className="shrink-0 rounded-md border border-hairline px-3 py-1.5 font-ui text-xs font-medium text-secondary hover:text-primary disabled:text-muted"
        >
          {verifying ? "Checking…" : verification ? "Re-check" : "Check"}
        </button>
      </div>

      {verification && (
        <div className="flex w-full flex-col items-start gap-2">
          <p className="w-full font-reading text-[13px] text-secondary">
            {verification.rationale}
          </p>

          {verification.citations.length > 0 && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="font-ui text-xs font-semibold text-brass hover:text-brass-bright"
            >
              {expanded ? "Hide evidence" : "Show evidence"}
            </button>
          )}

          {expanded && (
            <div className="flex w-full flex-col items-start gap-2">
              {verification.citations.map((citation) => (
                <CitationCard key={citation.evidence_id} citation={citation} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
