export type PaperStatus = "uploaded" | "processing" | "ready" | "failed";
export type JobStatus = "pending" | "running" | "succeeded" | "failed";

export interface Project {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface ProcessingJob {
  id: string;
  paper_id: string;
  status: JobStatus;
  stage: string | null;
  progress: number;
  error: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
}

export interface SearchResult {
  chunk_id: string;
  paper_id: string;
  paper_title: string | null;
  filename: string;
  content: string;
  section: string | null;
  chunk_index: number;
  token_count: number | null;
  page_number: number | null;
  similarity: number;
}

export interface PaperSection {
  id: string;
  paper_id: string;
  title: string;
  level: number;
  section_index: number;
  start_page: number;
  start_offset: number | null;
}

export interface Paper {
  id: string;
  project_id: string;
  title: string | null;
  filename: string;
  storage_path: string;
  sha256: string | null;
  page_count: number | null;
  status: PaperStatus;
  created_at: string;
  processed_at: string | null;
  job: ProcessingJob | null;
}

/** A citation the backend resolved from an evidence ID it issued itself.
 *  The model never invents these labels (PRD 5.3). */
export interface Citation {
  evidence_id: string;
  chunk_id: string;
  paper_id: string;
  paper_title: string | null;
  page_number: number | null;
  section: string | null;
  /** Pre-rendered "Section 3.2, page 7", degrading to "page 7". */
  location: string;
  snippet: string;
}

/** An evidence block handed to the model, whether or not it was cited. */
export interface Evidence {
  evidence_id: string;
  chunk_id: string;
  paper_id: string;
  paper_title: string | null;
  page_number: number | null;
  section: string | null;
  location: string;
  content: string;
  similarity: number;
  /** Cross-encoder logit. Unbounded, and NOT comparable to `similarity`. */
  rerank_score: number;
}

export interface AnswerResponse {
  answer: string;
  /** False when the model reported the evidence was insufficient. That is a
   *  correct outcome, not an error (PRD 5.4). */
  sufficient_evidence: boolean;
  citations: Citation[];
  evidence: Evidence[];
  /** Must be 0 (PRD Section 12). Shown in the UI if it ever is not. */
  fabricated_citations_removed: number;
  candidates_considered: number;
  evidence_dropped_for_budget: number;
  model: string;
}
