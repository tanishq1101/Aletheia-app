# AI Research Intelligence Platform — Product Requirements Document

**Prepared for internal team use — not the review PPT**

| | |
|---|---|
| Document version | v1.0 (Draft) |
| Date | August 23, 2026 |
| Status | Draft — Phase 1, Sprint 1 (planning) |
| Audience | Project team (internal) — not the review presentation |
| Owner | *[ fill in — team lead ]* |
| Team members | *[ fill in ]* |
| Course / reviewer | *[ fill in ]* |

A multimodal research-paper understanding system — built phase by phase, starting from a reliable text-RAG foundation.

---

## 1. Executive Summary

We are building an AI Research Intelligence Platform: a system that reads scientific papers the way a careful researcher would, across text, figures, tables, equations, citations, and eventually code, and answers questions with evidence that can be traced back to an exact page and section. This is explicitly not a "Chat with PDF" demo. The differentiators are deep multimodal understanding, claim-level evidence verification (not just citation dumping), and an eventual paper-to-code reproducibility check.

The project is being built in six phases, each frozen and evaluated before the next begins. We are currently at the very start: Phase 1, Sprint 1, which is pure scaffolding — repo structure, frontend/backend setup, database connection, a health check, and a basic PDF upload flow. No retrieval, no chunking, no LLM calls yet.

This document exists so the whole team is working from the same architecture, the same phase boundaries, and the same acceptance criteria — rather than everyone independently guessing what "done" means.

## 2. Problem Statement

Researchers increasingly rely on LLMs to make sense of scientific literature, but existing tools mostly treat a paper as a flat block of text. They ignore figures, tables, and equations as reasoning objects; they cite loosely (a page number, sometimes not even that); and they rarely check whether a generated claim is actually supported by the source before presenting it as fact. As the volume of published research grows, this gap between "text search over PDFs" and "actual research understanding" becomes more costly — findings get misread, comparisons get oversimplified, and unverifiable claims get treated as verified ones.

The platform's job is to close that gap: understand a paper the way it was meant to be read (prose + figures + tables + equations together), and never present a claim without being able to point at the exact evidence behind it.

## 3. Related Work: PaperQA2

The closest existing system to what we're building is PaperQA2, from FutureHouse (Skarlinski et al., 2024), which itself builds on the original PaperQA (Lála et al., 2023). This is the paper to reference for the "existing system" and "literature review" parts of any review, and the gaps it leaves are exactly what our phase roadmap is designed to close.

### 3.1 What PaperQA2 does

PaperQA2 is a retrieval-augmented language agent built specifically for answering questions over full-text scientific literature. It searches across papers, judges which passages are actually relevant, and generates answers grounded in what it retrieves, combining full-text search, semantic embedding search, and an LLM-based re-ranking/summarization step they call Retrieval-augmented Contextual Summarization (RCS). On their LitQA2 benchmark, it matched or beat PhD-level human researchers on precision and accuracy for literature question-answering, and it was also used to surface contradictions across a sample of biology papers, with the majority confirmed correct by human experts on review.

### 3.2 Where it falls short

| Gap in PaperQA2 | Evidence | Our planned response |
|---|---|---|
| Text-only evidence. | Its retrieval and citation units are papers and passages. Figures, tables, and equations are not treated as first-class, independently citable evidence. | Phase 2: figure/table/equation extraction, linked to captions and surrounding text, as retrievable and citable units in their own right. |
| Loose claim-to-passage tracking. | FutureHouse's own engineering write-up names entity conflation and parsing errors as the two leading failure modes in their error analysis. | Phase 1 design: the LLM never invents citation numbers. The backend issues explicit evidence IDs per chunk, and the model can only cite an ID it was actually given. |
| Chunking treated as an implementation detail. | Their own ablations show precision and recall shift meaningfully with chunk size and parsing choice, but this isn't framed as a first-class variable to optimize per use case. | Sprint 3 / Phase 1 evaluation: chunk size (400 / 600 / 800 tokens) is explicitly benchmarked against retrieval recall, not assumed. |
| No reproducibility angle. | Not addressed anywhere in the paper or repo — it answers questions about a paper's claims, not about whether those claims can be reproduced from the paper's own methodology. | Phase 6: a reproducibility score based on whether dataset, hyperparameters, seeds, and code are actually disclosed. |

This gives us an honest, defensible framing: PaperQA2 proves RAG-over-literature works for text question-answering at a high level. Our contribution is extending that toward multimodal evidence and stricter, auditable citation verification — not reinventing what already works.

### 3.3 References

| Title | Link |
|---|---|
| Language Agents Achieve Superhuman Synthesis of Scientific Knowledge (PaperQA2) — Skarlinski et al., 2024 | arxiv.org/abs/2409.13740 |
| PaperQA: Retrieval-Augmented Generative Agent for Scientific Research — Lála et al., 2023 | arxiv.org/abs/2312.07559 |
| PaperQA2 open-source implementation (Future-House/paper-qa) | github.com/Future-House/paper-qa |

## 4. Product Vision & Differentiators

Positioning: an AI Research Intelligence Platform that understands scientific literature across text, figures, tables, equations, code, and citations — enabling grounded analysis, cross-paper reasoning, verification, and reproducibility checking. Not "an AI chatbot for PDFs."

The three things this project should ultimately stand out for:

- Deep multimodal understanding — text, figures, graphs, tables, and equations reasoned over together, not independently.
- Claim-level evidence verification — the system doesn't just cite a source, it checks whether the claim is actually supported by that source and how strongly.
- Paper → code → experiment reproducibility — connecting a paper's claims to its implementation, and eventually re-running the experiment to check the claimed result.

## 5. System Architecture — Phase 1

### 5.1 High-level pipeline

1. User uploads a PDF via the Next.js frontend
2. FastAPI backend validates and stores the file, creates a paper record + processing job
3. PDF text extraction (page-level), normalization, basic section detection
4. Section-aware, paragraph-aware, token-bounded chunking with small overlap
5. Embedding generation (behind a swappable EmbeddingProvider interface)
6. Storage in PostgreSQL + pgvector (Supabase)
7. Query time: semantic retrieval (~top 20) → reranking → top ~5–8 evidence chunks
8. Context builder assembles evidence with explicit IDs → LLM (behind a swappable LLMProvider interface)
9. Grounded answer returned with citations resolved from evidence IDs, never invented by the model

### 5.2 Why both pages and chunks are stored

Retrieval operates on chunks, but citations need to be human-readable. Each chunk links to a page, which links to the paper, so the UI can show "Source: Section 3.2, Page 7" instead of an internal chunk ID. Chunk → Page → Paper is the resolution path for every citation the system produces.

### 5.3 Citation design (important)

The LLM is never allowed to generate its own citation numbers like [1], [2], [3] and have those mapped after the fact. Instead, the backend supplies evidence blocks with explicit IDs (e.g. `<EVIDENCE id="E1" page="7" section="Results">`), and the model can only cite an ID that was actually handed to it. The backend resolves E1 to a real citation object. This is the single biggest defense against citation hallucination, and it's a stricter version of a known weak point in comparable systems (see Section 3.2).

### 5.4 Grounding rules for answering

- Answer only using supplied evidence — never fill gaps from general model knowledge.
- Every factual claim must be traceable to a specific evidence ID.
- If evidence is insufficient, say so explicitly (e.g. "the paper does not contain enough information to determine that") instead of guessing.
- No fabricated citations, ever.

## 6. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Next.js, TypeScript, Tailwind CSS | Project dashboard, paper list, chat UI |
| Backend | Python, FastAPI, Pydantic | REST API, validation, processing orchestration |
| PDF processing | PyMuPDF | Text extraction now; reused for multimodal extraction in Phase 2 |
| Database | PostgreSQL + pgvector (via Supabase) | One system for relational + vector data — no separate vector DB |
| Storage | Supabase Storage | Original PDF files |
| AI — LLM | Provider-agnostic via LLMProvider interface | No hard-coded provider; must be swappable |
| AI — Embeddings | Provider-agnostic via EmbeddingProvider interface | Same rationale |
| AI — Reranking | Provider-agnostic via RerankerProvider interface | Same rationale |
| PDF parsing abstraction | DocumentParser interface | Keeps PyMuPDF swappable later |

Rationale for Postgres + pgvector over a separate vector database: the app needs strong relational modeling (users, projects, papers, pages, chunks, conversations, citations, jobs) as much as it needs vector search, and one system serving both avoids unnecessary infrastructure at this stage.

## 7. Database Schema — Phase 1 Entities

| Entity | Key fields | Purpose |
|---|---|---|
| users | id | Account owner |
| projects | id, user_id, name, description, created_at | Groups papers into a working project |
| papers | id, project_id, title, filename, storage_path, sha256, page_count, authors, abstract, status, created_at, processed_at | One uploaded paper and its processing state |
| paper_pages | id, paper_id, page_number, raw_text, cleaned_text, character_count, token_count | Page-level extracted text |
| paper_chunks | id, paper_id, page_id, section, chunk_index, content, token_count, embedding, start_offset, end_offset, metadata | Retrieval unit; embedding lives here |
| conversations | id, project_id, paper_id (nullable), created_at | A chat thread, optionally scoped to one paper |
| messages | id, conversation_id, role, content, created_at | Chat turns |
| citations | id, message_id, paper_id, page_id, chunk_id, citation_label, support_metadata | Resolved evidence behind a claim in a message |
| processing_jobs | id, paper_id, status, stage, progress, error, created_at, updated_at | Tracks ingestion pipeline state per paper |

Schema is intentionally minimal for Phase 1 — no premature normalization or speculative fields for future-phase features.

## 8. Repository Structure

```
research-intelligence/
  apps/
    web/   # Next.js — app/, components/, hooks/, lib/, types/
    api/   # FastAPI — app/api, app/core, app/db, app/models, app/schemas, app/services, main.py, tests/
  packages/shared/   # Shared types/utilities
  evaluation/        # datasets/, questions/, reports/ (Sprint 6)
  docs/               # architecture/, decisions/
  scripts/
  docker/
  .env.example
  docker-compose.yml
  README.md
```

This is a guideline, not a mandate to create every folder up front — keep it clean and only add structure when something needs to live there.

## 9. Engineering Principles — Team Working Agreement

- No phase bleeding. Each phase is self-contained; do not implement future-phase features early, even if it seems easy in the moment.
- Swappable AI providers. LLM, embedding, reranker, and parser integrations sit behind interfaces so providers can be swapped without rewriting application logic.
- Verify before claiming done. A feature is not "complete" because the UI looks right — it needs an actual passing test or a confirmed manual check.
- Avoid over-engineering. Build for the current phase's needs, not hypothetical future scale.
- Never silently swallow errors. Processing failures must be logged, visible, and retryable.
- Never fake evaluation metrics. If retrieval or answer quality hasn't been measured, say so.
- Secrets stay in environment variables. Never commit API keys or credentials.
- Explain before implementing a non-trivial change: what's changing, why, and the tradeoffs — then implement, test, and report what was actually verified versus what remains unverified.

## 10. Phase Roadmap

| Phase | Focus | Key capabilities |
|---|---|---|
| Phase 1 | Reliable text-RAG foundation | Ingestion, chunking, embeddings, retrieval, reranking, grounded answers, citations, evaluation |
| Phase 2 | Multimodal intelligence | Figure extraction, figure/caption linking, graph understanding, table extraction, equation extraction, multimodal retrieval & Q&A |
| Phase 3 | Advanced retrieval & verification | Hybrid search, query decomposition, claim-level verification, confidence scoring, hallucination detection |
| Phase 4 | Research intelligence | Cross-paper comparison, contradiction detection, research-gap detection, literature review generation, knowledge graph, citation graph |
| Phase 5 | Agentic research system | Research planner, search/reader/vision/math/data agents, critic, verifier, report generator, human approval gates |
| Phase 6 | Advanced / standout capabilities | GitHub integration, paper/code mapping, reproducibility scoring, experiment reproduction, AI peer review, production deployment |

Order of priority, restated: reliable ingestion → reliable retrieval → reliable evidence → reliable citations → multimodal understanding → cross-paper intelligence → agents → autonomous research.

## 11. Phase 1 — Sprint Plan

| Sprint | Goal | Key deliverables | Status |
|---|---|---|---|
| 1 | Foundation | Repo structure, Next.js + FastAPI setup, env management, Supabase connection, initial migrations, /health endpoint, PDF upload + storage, paper record, processing status, basic tests | Planned |
| 2 | PDF processing | Validation, SHA-256 hashing, duplicate detection, metadata extraction, page extraction, text normalization, basic section detection | Not started |
| 3 | Chunking + embeddings | Section/paragraph-aware chunker, token counting, overlap, EmbeddingProvider abstraction, pgvector storage, retrieval endpoint | Not started |
| 4 | RAG | Query embedding, semantic retrieval, reranking, context builder, LLMProvider abstraction, grounded answers, evidence IDs, citation resolution | Not started |
| 5 | Chat UI | Conversation UI, streaming, loading states, source cards, page/section citations, error handling, conversation history | Not started |
| 6 | Evaluation | Benchmark dataset (~10 papers × 15 questions), measure retrieval recall, answer correctness, citation accuracy, faithfulness, unanswerable-question handling, latency | Not started |

### 11.1 Sprint 1 end state (what "done" looks like)

User opens the app → creates/selects a project → uploads a PDF → backend receives it → PDF is stored → a paper record exists → a processing job exists → the UI shows status. No RAG logic yet.

### 11.2 Open questions blocking Sprint 1 execution

- Does a repository already exist with partial work, or are we starting from a clean scaffold? (Do not overwrite existing working code blindly.)
- Is a Supabase project already provisioned (URL + keys available), or should Sprint 1 start against a local Postgres + pgvector via docker-compose and wire in Supabase afterward?

## 12. Phase 1 Acceptance Criteria

Phase 2 does not start until every item below is true and verified — not assumed.

| Category | Criteria |
|---|---|
| Upload | Valid PDFs upload successfully • invalid files are rejected • duplicates are detected • processing status is visible |
| Extraction | Page boundaries preserved • text ordering reasonably preserved • metadata stored • basic section info retained |
| Retrieval | Relevant chunks retrieved • page/section metadata preserved • reranking works • retrieval is measurable against benchmark data |
| Answering | Answers are grounded • unsupported facts are not invented • system explicitly qualifies unanswerable questions |
| Citations | Correct page • correct section where available • citation points to real evidence • zero fabricated citation IDs |
| Reliability | Errors are logged • failed jobs are diagnosable/retryable • long/malformed PDFs handled gracefully • API errors handled cleanly |
| Testing | Unit tests • integration tests • ingestion tests • retrieval tests • RAG evaluation benchmark run and recorded |

> **Known sequencing gap (flagged during review, not yet resolved):** this section requires retrieval to be "measurable against benchmark data" before Phase 2 starts, but the benchmark itself is a Sprint 6 deliverable (Section 11), scheduled after the sprints this criterion is meant to gate. Either pull a rough benchmark forward to Sprint 3–4, or treat this specific criterion as unenforceable until Sprint 6 completes. Resolve before relying on this table as a hard gate.

## 13. Proposed Timeline — Phase 1

No fixed project deadline has been confirmed at the time of writing, so the windows below are proposed working estimates, sized to each sprint's scope, starting from this week. Replace the dates once the team knows the actual semester/submission deadline — the sprint order and dependencies should not change even if the calendar does.

| Sprint | Suggested window | Duration | Depends on |
|---|---|---|---|
| 1 — Foundation | Aug 25 – Aug 31, 2026 | ~1 week | Repo / Supabase decisions above |
| 2 — PDF processing | Sep 1 – Sep 9, 2026 | ~1.5 weeks | Sprint 1 upload flow |
| 3 — Chunking + embeddings | Sep 10 – Sep 21, 2026 | ~1.5–2 weeks | Sprint 2 clean page text |
| 4 — RAG | Sep 22 – Oct 5, 2026 | ~2 weeks | Sprint 3 embeddings + retrieval endpoint |
| 5 — Chat UI | Oct 6 – Oct 12, 2026 | ~1 week | Sprint 4 answer + citation API |
| 6 — Evaluation | Oct 13 – Oct 21, 2026 | ~1.5 weeks | End-to-end pipeline from Sprints 1–5 |

Phase 1 total: roughly 8–9 weeks of focused work at this scope. Phases 2–6 are intentionally left unscheduled until Phase 1's acceptance criteria are met — scheduling them now would itself be a form of phase bleeding.

## 14. Team & Ownership

To be filled in by the team — left blank intentionally rather than guessed.

| Name | Role | Owns |
|---|---|---|
| *[ fill in ]* | *[ fill in ]* | *[ e.g. frontend / Next.js ]* |
| *[ fill in ]* | *[ fill in ]* | *[ e.g. backend / FastAPI ]* |
| *[ fill in ]* | *[ fill in ]* | *[ e.g. DB / Supabase / schema ]* |
| *[ fill in ]* | *[ fill in ]* | *[ e.g. evaluation / benchmark ]* |

## 15. Working Agreement (with Claude / with each other)

- Explain a non-trivial change before making it: what, why, tradeoffs.
- Verify before declaring anything done — run it, test it, then say so.
- Always flag what hasn't been confirmed to work yet.
- Resolve ambiguity with a clarifying question up front rather than assuming and building the wrong thing.
- Keep communication brief and direct — concise status over long explanations.
