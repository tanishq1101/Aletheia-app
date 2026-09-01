import PreviewNotice from "@/components/PreviewNotice";
import ClaimCard from "@/components/ClaimCard";
import { claimVerification } from "@/lib/preview-data";

export default function ClaimVerificationPage() {
  const { paperTitle, claims } = claimVerification;

  const verifiedCount = claims.filter((c) => c.status === "verified").length;
  const disputedCount = claims.filter((c) => c.status === "disputed").length;
  const unverifiedCount = claims.filter((c) => c.status === "unverified").length;

  const chips: { label: string; count: number; active: boolean }[] = [
    { label: "All", count: claims.length, active: true },
    { label: "Verified", count: verifiedCount, active: false },
    { label: "Disputed", count: disputedCount, active: false },
    { label: "Unverified", count: unverifiedCount, active: false },
  ];

  return (
    <div className="flex w-full flex-col items-start gap-6">
      <h1 className="font-display text-[28px] font-semibold text-primary">Claim Verification</h1>

      <PreviewNotice>
        Claim extraction and verification are a later phase of the backend PRD.
        These claims, confidences and source counts are fixtures, not results.
      </PreviewNotice>

      <p className="font-ui text-[13px] text-secondary">
        {paperTitle} · {claims.length} claims extracted
      </p>

      <div className="flex shrink-0 items-start gap-2">
        {chips.map((chip) => (
          <div
            key={chip.label}
            className={`shrink-0 rounded-full px-[14px] py-[7px] ${
              chip.active ? "bg-brass" : "border border-hairline"
            }`}
          >
            <p
              className={`font-ui text-xs font-medium whitespace-nowrap ${
                chip.active ? "text-base" : "text-secondary"
              }`}
            >
              {chip.label} · {chip.count}
            </p>
          </div>
        ))}
      </div>

      <div className="flex w-full shrink-0 flex-col items-start gap-3.5">
        {claims.map((claim) => (
          <ClaimCard key={claim.id} claim={claim} />
        ))}
      </div>
    </div>
  );
}
