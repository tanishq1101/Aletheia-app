import Badge, { type BadgeTone } from "@/components/Badge";
import { statusLabel } from "@/lib/display";
import type { PaperStatus } from "@/types/api";

const statusTone: Record<PaperStatus, BadgeTone> = {
  // `uploaded` means stored but not yet picked up by the worker.
  uploaded: "muted",
  processing: "warning",
  ready: "success",
  failed: "error",
};

export default function StatusBadge({ status }: { status: PaperStatus }) {
  return <Badge tone={statusTone[status]} label={statusLabel[status]} />;
}
