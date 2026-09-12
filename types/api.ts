/** Wire types for the FastAPI backend in `backend/`.
 *
 * These mirror `backend/apps/api/app/schemas/models.py`. UUIDs and datetimes
 * arrive as strings over JSON, so they are typed as such here rather than
 * pretending to be richer types the fetch layer never constructs. */

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
  /** downloading | parsing | chunking | embedding | persisting | complete */
  stage: string | null;
  progress: number;
  error: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
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

export interface PaperPage {
  id: string;
  paper_id: string;
  page_number: number;
  cleaned_text: string | null;
  character_count: number | null;
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

export type PaperAssetKind = "figure" | "table" | "equation";

export interface PaperAsset {
  id: string;
  paper_id: string;
  page_id: string;
  page_number: number;
  kind: PaperAssetKind;
  asset_index: number;
  caption: string | null;
  content_text: string | null;
  has_binary: boolean;
  bbox: number[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface FigureInterpretationResponse {
  asset_id: string;
  paper_id: string;
  page_number: number;
  caption: string | null;
  interpretation: string;
  model: string;
  ai_generated: boolean;
  cached: boolean;
  created_at: string;
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
  /** Cosine similarity, 0..1. */
  similarity: number;
}

/** A citation the backend resolved from an evidence ID it issued itself.
 *  The model never invents these labels (backend PRD 5.3). */
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
  source_url?: string | null;
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
  source_url?: string | null;
}

export interface ModelDiagnostic {
  task: string;
  status: string;
  labels: string[];
  note: string;
  validation_macro_f1?: number;
  scores: { evidence_id: string; values: number[] }[];
}

export interface AnswerResponse {
  answer: string;
  /** False when the model reported the evidence was insufficient. That is a
   *  correct outcome, not an error (backend PRD 5.4). */
  sufficient_evidence: boolean;
  citations: Citation[];
  evidence: Evidence[];
  /** Must be 0 (backend PRD Section 12). Surfaced in the UI if it ever is not. */
  fabricated_citations_removed: number;
  candidates_considered: number;
  evidence_dropped_for_budget: number;
  model_diagnostics?: ModelDiagnostic[];
  truncated?: boolean;
  charts?: { title: string; unit: string; conditions: string; note: string; points: { label: string; value: number; evidence_ids: string[] }[] }[];
  model: string;
}

export interface AgentStepResponse {
  question: string;
  status: "succeeded" | "failed";
  answer: AnswerResponse | null;
  error: string | null;
}

export interface AgentResearchResponse {
  goal: string;
  planned_questions: string[];
  planner_fallback_used: boolean;
  steps: AgentStepResponse[];
  synthesis?: AnswerResponse | null;
  synthesis_error?: string | null;
  discoveries?: { provider: string; title: string; url: string; year: string; evidence_scope: string }[];
  discovery_errors?: string[];
  model: string;
}

export interface HealthResponse {
  status: string;
  database: string;
  storage: string;
}

// --- Conversations (Ask persistence) ----------------------------------------

export interface Conversation {
  id: string;
  project_id: string;
  paper_id: string | null;
  created_at: string;
  message_count: number;
  /** First question asked, used as a list label. Not stored separately. */
  preview: string | null;
}

export interface MessageMetadata {
  sufficient_evidence: boolean;
  model: string;
  candidates_considered: number;
  fabricated_citations_removed: number;
  evidence_dropped_for_budget: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  citations: Citation[];
  metadata: MessageMetadata | null;
}

export interface MessageExchange {
  user_message: Message;
  assistant_message: Message;
}

// --- Claims and cross-paper verification ------------------------------------

export type Verdict = "supported" | "contradicted" | "insufficient";

export interface ClaimVerification {
  id: string;
  claim_id: string;
  paper_id: string | null;
  verdict: Verdict;
  /** Model-reported, 0-1. Not calibrated — always labelled as such in the UI. */
  confidence: number | null;
  rationale: string;
  citations: Citation[];
  evidence_count: number;
  model: string | null;
  created_at: string;
}

export interface Claim {
  id: string;
  project_id: string;
  paper_id: string | null;
  text: string;
  source: "extracted" | "manual";
  claim_index: number;
  created_at: string;
  verification: ClaimVerification | null;
}

export interface CrossPaperCell {
  claim_id: string;
  paper_id: string;
  verification: ClaimVerification;
}

export interface CrossPaperMatrix {
  claim_ids: string[];
  paper_ids: string[];
  cells: CrossPaperCell[];
  /** How many cells cost a model call on the last request. */
  cells_computed: number;
}

// --- Reproducibility ---------------------------------------------------------

export type DisclosureStatus = "disclosed" | "partial" | "missing";

export interface ReproducibilityCheck {
  dimension: string;
  status: DisclosureStatus;
  rationale: string;
  citations: Citation[];
  check_index: number;
}

export interface RepoMetadata {
  repository: string;
  status: "ok" | "not_found" | "rate_limited" | "unavailable";
  url?: string;
  description?: string | null;
  stars?: number;
  forks?: number;
  license?: string | null;
  language?: string | null;
  last_pushed_at?: string | null;
  archived?: boolean;
  open_issues?: number;
  detail?: string;
}

export interface PaperLink {
  kind: "github" | "gitlab" | "doi";
  url: string;
  owner?: string;
  repo?: string;
  doi?: string;
}

export interface ReproducibilityReport {
  id: string;
  paper_id: string;
  /** Weighted disclosure, 0-1. Measures disclosure, not replication. */
  score: number;
  repo_metadata: RepoMetadata | null;
  links: PaperLink[];
  model: string | null;
  created_at: string;
  checks: ReproducibilityCheck[];
}

// --- Settings -----------------------------------------------------------------

export interface AppSettings {
  search_top_k: number;
  rerank_top_k: number;
  context_max_tokens: number;
  llm_model: string;
  llm_provider: string;
  /** Whether a key is present — the key itself is never sent. */
  llm_key_configured: boolean;
  embedding_model: string;
  rerank_model: string;
  chunk_max_tokens: number;
  chunk_overlap_tokens: number;
  storage_backend: string;
  max_upload_bytes: number;
  github_token_configured: boolean;
  dev_user_id: string;
  overridden: string[];
}
