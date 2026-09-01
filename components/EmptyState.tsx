import Link from "next/link";

export default function EmptyState({
  title,
  description,
  actionLabel,
  actionHref,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  actionHref?: string;
}) {
  return (
    <div className="flex w-full shrink-0 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-hairline py-16">
      <p className="font-display text-lg font-semibold text-primary">{title}</p>
      <p className="max-w-[420px] text-center font-ui text-[13px] text-muted">
        {description}
      </p>
      {actionLabel && actionHref && (
        <Link
          href={actionHref}
          className="mt-1 rounded-md bg-oxblood px-[18px] py-[10px] font-ui text-[13px] font-semibold text-primary"
        >
          {actionLabel}
        </Link>
      )}
    </div>
  );
}
