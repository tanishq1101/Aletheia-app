import type { AgreementStatus } from "@/lib/preview-data";

const agreementConfig: Record<AgreementStatus, { label: string; text: string; dot: string }> = {
  supports: { label: "Supports", text: "text-success", dot: "bg-success" },
  contradicts: { label: "Contradicts", text: "text-error", dot: "bg-error" },
  unverified: { label: "Not addressed", text: "text-muted", dot: "bg-muted" },
};

export default function AgreementBadge({
  status,
  label,
}: {
  status: AgreementStatus;
  label?: string;
}) {
  const config = agreementConfig[status];

  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <span className={`size-[7px] shrink-0 rounded-full ${config.dot}`} />
      <p className={`font-ui text-xs font-medium whitespace-nowrap ${config.text}`}>
        {label ?? config.label}
      </p>
    </div>
  );
}
