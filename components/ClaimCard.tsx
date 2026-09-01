import ClaimStatusBadge from "@/components/ClaimStatusBadge";
import ConfidenceMeter from "@/components/ConfidenceMeter";
import type { BadgeTone } from "@/components/Badge";
import type { VerifiedClaim } from "@/lib/preview-data";

const statusTone: Record<VerifiedClaim["status"], BadgeTone> = {
  verified: "success",
  disputed: "error",
  unverified: "muted",
};

export default function ClaimCard({ claim }: { claim: VerifiedClaim }) {
  return (
    <div className="flex w-full shrink-0 flex-col items-start gap-[14px] rounded-md border border-hairline-subtle bg-surface px-[22px] py-[18px]">
      <div className="flex w-full items-center gap-4">
        <p className="min-w-px flex-1 font-ui text-sm font-medium text-primary">{claim.text}</p>
        <ClaimStatusBadge status={claim.status} />
      </div>

      <div className="flex w-full items-center gap-4">
        <ConfidenceMeter confidence={claim.confidence} tone={statusTone[claim.status]} />
        <p className="shrink-0 font-ui text-xs whitespace-nowrap text-secondary">
          {claim.sourceCount} linked source{claim.sourceCount === 1 ? "" : "s"}
        </p>
      </div>
    </div>
  );
}
