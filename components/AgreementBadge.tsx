import type { Verdict } from "@/types/api";

const agreementConfig: Record<
  Verdict | "unchecked",
  { label: string; text: string; dot: string }
> = {
  supported: { label: "Supports", text: "text-success", dot: "bg-success" },
  contradicted: { label: "Contradicts", text: "text-error", dot: "bg-error" },
  insufficient: { label: "Doesn't address", text: "text-warning", dot: "bg-warning" },
  unchecked: { label: "Not checked", text: "text-muted", dot: "bg-muted" },
};

export default function AgreementBadge({
  verdict,
  confidence,
  onClick,
}: {
  verdict: Verdict | "unchecked";
  confidence?: number | null;
  onClick?: () => void;
}) {
  const config = agreementConfig[verdict];
  const percent =
    confidence === null || confidence === undefined
      ? null
      : Math.round(confidence * 100);

  const content = (
    <span className="flex shrink-0 items-center gap-1.5">
      <span className={`size-[7px] shrink-0 rounded-full ${config.dot}`} />
      <span
        className={`font-ui text-xs font-medium whitespace-nowrap ${config.text}`}
      >
        {config.label}
        {percent !== null && (
          <span className="ml-1 font-mono text-[10px] text-muted">{percent}%</span>
        )}
      </span>
    </span>
  );

  if (!onClick) return content;

  return (
    <button type="button" onClick={onClick} className="text-left hover:opacity-80">
      {content}
    </button>
  );
}
