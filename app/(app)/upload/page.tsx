"use client";

import Link from "next/link";
import { useState } from "react";
import ApiErrorNotice from "@/components/ApiErrorNotice";
import Dropzone from "@/components/Dropzone";
import ProcessingStepper from "@/components/ProcessingStepper";
import { ApiError, reprocessPaper, uploadPaper } from "@/lib/api";
import { paperTitle, shortDate, statusLabel } from "@/lib/display";
import { isInFlight, useWorkspace } from "@/lib/workspace";
import type { Paper, PaperStatus } from "@/types/api";

const statusColor: Record<PaperStatus, string> = {
  uploaded: "text-muted",
  processing: "text-warning",
  ready: "text-success",
  failed: "text-error",
};

export default function UploadPage() {
  const { projectId, papers, error, refresh } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [duplicateOf, setDuplicateOf] = useState<string | null>(null);
  // The paper this page just added, so the stepper follows it specifically
  // rather than whichever paper happens to be processing.
  const [trackedId, setTrackedId] = useState<string | null>(null);

  const handleFile = async (file: File) => {
    if (!projectId) return;
    setBusy(true);
    setUploadError(null);
    setDuplicateOf(null);
    try {
      const paper = await uploadPaper(projectId, file);
      setTrackedId(paper.id);
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setUploadError(err.message);
        // A 409 carries the id of the paper this PDF duplicates — link to it
        // instead of leaving the user to hunt for it.
        const detail = err.detail as { existing_paper_id?: string } | null;
        if (err.status === 409 && detail?.existing_paper_id) {
          setDuplicateOf(detail.existing_paper_id);
        }
      } else {
        setUploadError("Upload failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  const retry = async (paper: Paper) => {
    try {
      await reprocessPaper(paper.id);
      setTrackedId(paper.id);
      await refresh();
    } catch (err) {
      setUploadError(
        err instanceof ApiError ? err.message : "Could not retry processing.",
      );
    }
  };

  // Track the explicit upload if there is one, otherwise whatever is running.
  const tracked =
    papers.find((p) => p.id === trackedId) ?? papers.find(isInFlight) ?? null;

  const recent = papers.slice(0, 6);

  return (
    <div className="flex w-full flex-col items-start gap-8">
      <h1 className="font-display text-3xl font-semibold text-primary">
        Upload a paper
      </h1>

      {error && <ApiErrorNotice message={error} onRetry={() => void refresh()} />}

      <Dropzone
        onFile={(file) => void handleFile(file)}
        disabled={!projectId || busy}
        busy={busy}
      />

      {uploadError && (
        <div className="flex w-full shrink-0 items-center gap-4 rounded-md border border-oxblood bg-surface px-[18px] py-4">
          <p className="min-w-px flex-1 font-ui text-[13px] text-secondary">
            {uploadError}
          </p>
          {duplicateOf && (
            <Link
              href={`/paper/${duplicateOf}`}
              className="shrink-0 font-ui text-xs font-semibold whitespace-nowrap text-brass"
            >
              Open the existing paper ›
            </Link>
          )}
        </div>
      )}

      {tracked && <ProcessingStepper paper={tracked} />}

      <p className="font-ui text-base font-semibold text-primary">Recently added</p>

      {recent.length === 0 ? (
        <p className="font-ui text-sm text-muted">Nothing uploaded yet.</p>
      ) : (
        <div className="flex w-full shrink-0 flex-col items-start gap-px bg-base">
          {recent.map((paper) => (
            <div
              key={paper.id}
              className="flex w-full items-center gap-3 bg-surface px-4 py-[14px]"
            >
              <Link
                href={`/paper/${paper.id}`}
                className="flex-1 min-w-px truncate font-mono text-xs text-primary hover:text-brass-bright"
                title={paperTitle(paper)}
              >
                {paper.filename}
              </Link>
              <p className="shrink-0 font-ui text-[11px] whitespace-nowrap text-muted">
                {paper.page_count != null ? `${paper.page_count} pp` : "—"}
              </p>
              <p className="shrink-0 font-ui text-[11px] whitespace-nowrap text-muted">
                {shortDate(paper.created_at)}
              </p>
              <p
                className={`shrink-0 font-ui text-[11px] font-medium whitespace-nowrap ${statusColor[paper.status]}`}
              >
                {statusLabel[paper.status]}
              </p>
              {paper.status === "failed" && (
                <button
                  type="button"
                  onClick={() => void retry(paper)}
                  className="shrink-0 font-ui text-[11px] font-semibold whitespace-nowrap text-brass hover:text-brass-bright"
                >
                  Retry
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
