import Badge, { type BadgeTone } from "@/components/Badge";
import type { Verdict } from "@/types/api";

export const verdictTone: Record<Verdict | "unchecked", BadgeTone> = {
  supported: "success",
  contradicted: "error",
  insufficient: "warning",
  unchecked: "muted",
};

const verdictLabel: Record<Verdict | "unchecked", string> = {
  supported: "Supported",
  contradicted: "Contradicted",
  insufficient: "Insufficient evidence",
  unchecked: "Not checked",
};

export default function ClaimStatusBadge({
  verdict,
}: {
  verdict: Verdict | "unchecked";
}) {
  return <Badge tone={verdictTone[verdict]} label={verdictLabel[verdict]} />;
}
