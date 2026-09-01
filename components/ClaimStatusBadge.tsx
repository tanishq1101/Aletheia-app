import Badge, { type BadgeTone } from "@/components/Badge";
import type { ClaimVerificationStatus } from "@/lib/preview-data";

const statusConfig: Record<ClaimVerificationStatus, { label: string; tone: BadgeTone }> = {
  verified: { label: "Verified", tone: "success" },
  disputed: { label: "Disputed", tone: "error" },
  unverified: { label: "Unverified", tone: "muted" },
};

export default function ClaimStatusBadge({ status }: { status: ClaimVerificationStatus }) {
  const config = statusConfig[status];
  return <Badge tone={config.tone} label={config.label} />;
}
