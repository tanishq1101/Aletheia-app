/** One consistent rendering for "the API said no" or "the API isn't there".
 *
 * Kept distinct from an empty state: no papers and no backend look identical
 * on an empty grid, and only one of them is the user's problem to fix. */
export default function ApiErrorNotice({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex w-full shrink-0 items-center gap-4 rounded-md border border-oxblood bg-surface px-[18px] py-4">
      <span className="size-[6px] shrink-0 rounded-full bg-error" />
      <p className="min-w-px flex-1 font-ui text-[13px] text-secondary">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 font-ui text-xs font-semibold whitespace-nowrap text-oxblood-bright hover:text-error"
        >
          Retry
        </button>
      )}
    </div>
  );
}
