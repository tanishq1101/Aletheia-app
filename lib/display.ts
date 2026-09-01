/** Presentation helpers shared by the pages that render API records.
 *
 * The backend leaves a field null when it genuinely does not know it (a title
 * before extraction has run, a page count on a failed paper). These helpers
 * pick a truthful fallback in one place so no page invents its own. */

import type { Paper, PaperStatus } from "@/types/api";

/** A paper's display title. Extraction fills `title` in; until then the
 *  filename is the only name the paper actually has. */
export function paperTitle(paper: Paper): string {
  const title = paper.title?.trim();
  if (title) return title;
  return paper.filename.replace(/\.pdf$/i, "");
}

/** "Aug 21" — matches the density of the library card. */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function fullDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export const statusLabel: Record<PaperStatus, string> = {
  uploaded: "Queued",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

/** The stages `process_paper` walks a job through, in order. Used to render
 *  progress as steps rather than a bare percentage. */
export const INGESTION_STAGES = [
  { key: "downloading", label: "Reading file" },
  { key: "parsing", label: "Parsing document" },
  { key: "chunking", label: "Chunking text" },
  { key: "embedding", label: "Embedding chunks" },
  { key: "persisting", label: "Indexing for search" },
] as const;

/** Which of `INGESTION_STAGES` a job is on. `queued` sits before the first
 *  stage; `complete` sits after the last. -1 means not started. */
export function stageIndex(stage: string | null | undefined): number {
  if (!stage) return -1;
  if (stage === "complete") return INGESTION_STAGES.length;
  return INGESTION_STAGES.findIndex((s) => s.key === stage);
}

/** Similarity is a 0..1 cosine score; the UI shows it as a percentage. */
export function matchPercent(similarity: number): number {
  return Math.round(Math.max(0, Math.min(1, similarity)) * 100);
}

/** "Section 3.2, page 7" for a search hit. The answer endpoint pre-renders
 *  this server-side; the search endpoint returns the parts. */
export function chunkLocation(
  section: string | null,
  pageNumber: number | null,
): string {
  const parts: string[] = [];
  if (section) parts.push(section);
  if (pageNumber != null) parts.push(`page ${pageNumber}`);
  return parts.join(", ");
}
