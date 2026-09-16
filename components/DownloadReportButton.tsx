"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

/** One "Download PDF" control, shared by every surface that produces a report.
 *
 *  A download is slow enough to need a pending state and can fail for reasons
 *  the user can act on, so the failure is shown next to the button that caused
 *  it rather than replacing the report the user is reading. */
export default function DownloadReportButton({
  download,
  label = "Download PDF",
  title,
}: {
  download: () => Promise<void>;
  label?: string;
  title?: string;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A download that finishes after the user has navigated away must not set
  // state on an unmounted component.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = async () => {
    setPending(true);
    setError(null);
    try {
      await download();
    } catch (err) {
      if (!mounted.current) return;
      setError(
        err instanceof ApiError
          ? err.message
          : "The report could not be downloaded.",
      );
    } finally {
      if (mounted.current) setPending(false);
    }
  };

  return (
    <div className="flex shrink-0 flex-col items-end gap-1">
      <button
        type="button"
        onClick={run}
        disabled={pending}
        title={title}
        className="flex min-h-9 shrink-0 items-center gap-2 rounded-md border border-brass px-3 font-ui text-[12px] font-semibold text-brass transition-colors hover:bg-surface-raised hover:text-brass-bright disabled:cursor-not-allowed disabled:border-hairline disabled:text-muted"
      >
        <span aria-hidden="true" className="font-mono text-[11px]">
          {pending ? "…" : "↓"}
        </span>
        {pending ? "Preparing…" : label}
      </button>
      {error && (
        <p role="alert" className="max-w-xs text-right font-ui text-[11px] text-error">
          {error}
        </p>
      )}
    </div>
  );
}
