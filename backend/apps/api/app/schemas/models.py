from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class Project(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    created_at: datetime


class ProcessingJob(BaseModel):
    id: UUID
    paper_id: UUID
    status: str
    stage: str | None
    progress: float
    error: str | None
    attempts: int = 0
    created_at: datetime
    updated_at: datetime


class PaperPage(BaseModel):
    id: UUID
    paper_id: UUID
    page_number: int
    cleaned_text: str | None
    character_count: int | None


class PaperSection(BaseModel):
    id: UUID
    paper_id: UUID
    title: str
    level: int
    section_index: int
    start_page: int
    start_offset: int | None


class PaperAsset(BaseModel):
    id: UUID
    paper_id: UUID
    page_id: UUID
    page_number: int
    kind: str
    asset_index: int
    caption: str | None
    content_text: str | None
    has_binary: bool
    bbox: list[float]
    metadata: dict[str, Any]
    created_at: datetime


class FigureInterpretationResponse(BaseModel):
    asset_id: UUID
    paper_id: UUID
    page_number: int
    caption: str | None
    interpretation: str
    model: str
    ai_generated: bool = True
    cached: bool
    created_at: datetime


class Paper(BaseModel):
    id: UUID
    project_id: UUID
    title: str | None
    filename: str
    storage_path: str
    sha256: str | None
    page_count: int | None
    status: str
    created_at: datetime
    processed_at: datetime | None


class PaperWithJob(Paper):
    job: ProcessingJob | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    # Optional source scope. It narrows the semantic index without weakening
    # the project boundary enforced by retrieval.
    paper_ids: list[UUID] | None = Field(default=None, max_length=100)


class SearchResult(BaseModel):
    chunk_id: UUID
    paper_id: UUID
    paper_title: str | None
    filename: str
    content: str
    section: str | None
    chunk_index: int
    token_count: int | None
    page_number: int | None
    similarity: float


class AnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    # Candidates retrieved before reranking (PRD 5.1 step 7).
    top_k: int | None = Field(default=None, ge=1, le=100)
    # Evidence blocks that survive reranking. PRD 5.1 says 5-8; the ceiling is
    # a little higher so the effect of more evidence stays measurable.
    rerank_top_k: int | None = Field(default=None, ge=1, le=20)


class CitationOut(BaseModel):
    """A citation the backend resolved — never a label the model invented."""

    evidence_id: str
    chunk_id: UUID
    paper_id: UUID
    paper_title: str | None
    page_number: int | None
    section: str | None
    # Pre-rendered "Section 3.2, page 7", degrading to "page 7" when a chunk
    # sits before the first heading.
    location: str
    snippet: str
    source_url: str | None = None


class EvidenceOut(BaseModel):
    """An evidence block handed to the model, cited or not.

    Returned so retrieval can be inspected independently of the answer — an
    answer that ignored good evidence and one built on bad evidence look
    identical from the answer text alone.
    """

    evidence_id: str
    chunk_id: UUID
    paper_id: UUID
    paper_title: str | None
    page_number: int | None
    section: str | None
    location: str
    content: str
    similarity: float
    # Cross-encoder logit. Unbounded, and NOT comparable to `similarity`.
    rerank_score: float
    source_url: str | None = None


class AnswerResponse(BaseModel):
    answer: str
    # False when the model reported the evidence was insufficient. That is a
    # correct outcome, not an error (PRD 5.4) — the UI renders it as an answer.
    sufficient_evidence: bool
    citations: list[CitationOut]
    evidence: list[EvidenceOut]
    # Must be 0 (PRD Section 12: zero fabricated citation IDs). Exposed rather
    # than only logged, so the criterion is checkable from the outside.
    fabricated_citations_removed: int
    candidates_considered: int
    evidence_dropped_for_budget: int
    model: str
    model_diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    # A conversation may be scoped to one paper, or to the whole project.
    paper_id: UUID | None = None


class Conversation(BaseModel):
    id: UUID
    project_id: UUID
    paper_id: UUID | None
    created_at: datetime
    message_count: int = 0
    # First question asked, used as a list label. Not stored separately.
    preview: str | None = None


class MessageCreate(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    rerank_top_k: int | None = Field(default=None, ge=1, le=20)


class Message(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    created_at: datetime
    citations: list[CitationOut] = []
    # Assistant turns carry what made the answer auditable: sufficiency, model,
    # and how much evidence was considered. User turns carry nothing.
    metadata: dict | None = None


class MessageExchange(BaseModel):
    """One question and the answer it produced."""

    user_message: Message
    assistant_message: Message


class ExtractClaimsRequest(BaseModel):
    limit: int = Field(default=8, ge=1, le=20)


class ClaimCreate(BaseModel):
    text: str = Field(min_length=10, max_length=400)
    paper_id: UUID | None = None


class Claim(BaseModel):
    id: UUID
    project_id: UUID
    paper_id: UUID | None
    text: str
    source: str
    claim_index: int
    created_at: datetime


class ClaimVerification(BaseModel):
    id: UUID
    claim_id: UUID
    # Which paper's evidence produced this verdict; None means the project's.
    paper_id: UUID | None
    verdict: str
    # Model-reported, 0-1, NOT calibrated. Every surface showing it says so.
    confidence: float | None
    rationale: str
    citations: list[CitationOut]
    evidence_count: int
    model: str | None
    created_at: datetime


class ClaimWithVerification(Claim):
    verification: ClaimVerification | None = None


class CrossPaperRequest(BaseModel):
    claim_ids: list[UUID] = Field(min_length=1, max_length=5)
    paper_ids: list[UUID] = Field(min_length=1, max_length=5)
    # Re-check cells that already have a verdict instead of reusing them.
    refresh: bool = False


class CrossPaperCell(BaseModel):
    claim_id: UUID
    paper_id: UUID
    verification: ClaimVerification


class CrossPaperMatrix(BaseModel):
    claim_ids: list[UUID]
    paper_ids: list[UUID]
    cells: list[CrossPaperCell]
    # How many cells cost a model call on this request.
    cells_computed: int


class ReproducibilityRequest(BaseModel):
    # Off for offline runs; a missing GitHub lookup never blocks the audit.
    check_github: bool = True


class ReproducibilityCheck(BaseModel):
    dimension: str
    status: str
    rationale: str
    citations: list[CitationOut]
    check_index: int


class ReproducibilityReport(BaseModel):
    id: UUID
    paper_id: UUID
    # Weighted disclosure across the checks below. This measures what the paper
    # discloses — nothing here runs the paper's code.
    score: float
    repo_metadata: dict | None
    links: list[dict]
    model: str | None
    created_at: datetime
    checks: list[ReproducibilityCheck] = []


class SettingsUpdate(BaseModel):
    """Only the tunables. Keys, URLs and backends stay in the environment."""

    search_top_k: int | None = Field(default=None, ge=1, le=100)
    rerank_top_k: int | None = Field(default=None, ge=1, le=20)
    context_max_tokens: int | None = Field(default=None, ge=500, le=32000)
    llm_model: str | None = Field(default=None, max_length=200)


class SettingsResponse(BaseModel):
    search_top_k: int
    rerank_top_k: int
    context_max_tokens: int
    llm_model: str
    llm_provider: str
    # Whether a key is present — never the key.
    llm_key_configured: bool
    embedding_model: str
    rerank_model: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    storage_backend: str
    max_upload_bytes: int
    github_token_configured: bool
    dev_user_id: UUID
    # Which values are overridden in the database rather than the environment.
    overridden: list[str]


class AgentResearchRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    max_steps: int = Field(default=3, ge=1, le=4)
    synthesize: bool = False
    discover_sources: bool = False


class AgentStepResponse(BaseModel):
    question: str
    status: str
    answer: AnswerResponse | None = None
    error: str | None = None


class AgentResearchResponse(BaseModel):
    goal: str
    planned_questions: list[str]
    planner_fallback_used: bool
    steps: list[AgentStepResponse]
    model: str
    synthesis: AnswerResponse | None = None
    synthesis_error: str | None = None
    discoveries: list[dict[str, Any]] = Field(default_factory=list)
    discovery_errors: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    database: str
    storage: str
    # Chroma is reported but never gates `status`: it is the primary vector
    # index, not a hard dependency, and retrieval still answers from pgvector
    # without it. A degraded vector store has to be visible without making the
    # whole service look down.
    vector_store: str = "unknown"
    # Which store the request budgets are counted in, and whether it is
    # currently degraded. Like vector_store this never gates `status`: a
    # limiter that has fallen back to a per-process window is still
    # limiting, and the service is still serving.
    rate_limiter: str = "unknown"
