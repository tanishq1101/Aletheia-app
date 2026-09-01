# Claude Code Prompt — Sprint 1: Foundation Scaffolding

Copy everything below into Claude Code as your starting prompt.

---

I'm building an AI Research Intelligence Platform per an internal PRD (v1.0 draft). This prompt covers **Sprint 1 only** — foundation scaffolding. Do not implement anything from Sprint 2 onward (no PDF text extraction logic, no chunking, no embeddings, no retrieval, no LLM calls). If you're tempted to add any of that "since it's easy," stop and ask me first — phase bleeding is explicitly against our engineering principles.

## Coordination requirement (read this first, not optional)
This project is being worked on in parallel by you (Claude Code, doing the actual implementation) and a separate Claude Cowork session (handling planning, docs, and research). Both of us read and write to the same project folder. `PROGRESS.md` at the project root is the single shared source of truth for project state — it is NOT documentation you write once and forget.

Before you do anything else:
1. Read `PROGRESS.md` and `PRD.md` in the project root, and `docs/dataset-references.md`, in full.
2. Confirm back to me that you've read them and summarize the current open decisions listed in `PROGRESS.md` before writing any code.

As you work:
3. Update `PROGRESS.md` whenever you complete a deliverable, hit a blocker, make a decision (especially the two Section 11.2 open questions below), or discover something the PRD got wrong. Don't wait until the end of the session — update it as things happen, the same way you'd narrate status to a teammate.
4. If you resolve an open question from `PROGRESS.md`, check it off and record what was decided and why, not just that it's done.
5. Do not let `PROGRESS.md` go stale while you work silently for a long stretch — if you're mid-task on something substantial, log that you started it before you finish it, in case the session ends unexpectedly.

## Sprint 1 goal (from the PRD, Section 11.1)
"User opens the app → creates/selects a project → uploads a PDF → backend receives it → PDF is stored → a paper record exists → a processing job exists → the UI shows status. No RAG logic yet."

## Tech stack (PRD Section 6 — do not substitute or add libraries beyond this)
- Frontend: Next.js, TypeScript, Tailwind CSS
- Backend: Python, FastAPI, Pydantic
- Database: PostgreSQL + pgvector via Supabase (one system for relational + vector data, no separate vector DB)
- Storage: Supabase Storage for original PDF files
- AI integrations (LLM/Embedding/Reranker) are NOT wired up in Sprint 1 — just leave interface stubs if you scaffold them at all

## Repository structure (PRD Section 8 — guideline, not a mandate to create every folder up front)
```
research-intelligence/
  apps/
    web/   # Next.js — app/, components/, hooks/, lib/, types/
    api/   # FastAPI — app/api, app/core, app/db, app/models, app/schemas, app/services, main.py, tests/
  packages/shared/   # Shared types/utilities
  evaluation/        # datasets/, questions/, reports/ — Sprint 6, do not populate now
  docs/               # architecture/, decisions/
  scripts/
  docker/
  .env.example
  docker-compose.yml
  README.md
```

## Database schema — Sprint 1 relevant entities only (PRD Section 7)
Create migrations for these tables now. Other Phase 1 entities (paper_chunks with embedding, citations) can have their table shells created per the full schema, but do NOT build any logic that populates chunks/embeddings yet.
- `users` — id
- `projects` — id, user_id, name, description, created_at
- `papers` — id, project_id, title, filename, storage_path, sha256, page_count, authors, abstract, status, created_at, processed_at
- `processing_jobs` — id, paper_id, status, stage, progress, error, created_at, updated_at

## Sprint 1 deliverables (PRD Section 11, Sprint row 1)
1. Repo structure as above
2. Next.js frontend scaffold + FastAPI backend scaffold
3. Environment variable management (.env.example, no secrets committed — PRD Section 9)
4. Supabase connection wired up (see open question below — confirm before assuming a project exists)
5. Initial database migrations for the tables listed above
6. `/health` endpoint on the FastAPI backend
7. PDF upload endpoint: accepts a file, validates it's a PDF, stores it in Supabase Storage, creates a `papers` record and a `processing_jobs` record, returns status
8. Basic tests covering upload + health check

## Engineering principles to follow throughout (PRD Section 9)
- No phase bleeding — Sprint 1 scope only, nothing from Sprint 2+
- AI provider interfaces (LLMProvider, EmbeddingProvider, RerankerProvider, DocumentParser) must be swappable — but do not implement any AI logic yet, this is scaffolding only
- Don't mark anything "done" without an actual passing test or confirmed manual check
- Avoid over-engineering — build for Sprint 1's needs only
- Never silently swallow errors — processing failures must be logged, visible, retryable
- Secrets stay in environment variables, never committed

## Open questions to resolve before/while executing (PRD Section 11.2 — ask me, don't assume)
1. Does a repository already exist with partial work, or are we starting from a clean scaffold? Do not overwrite existing working code blindly — check first.
2. Is a Supabase project already provisioned (URL + keys available), or should Sprint 1 start against a local Postgres + pgvector via docker-compose and wire in Supabase afterward?

## Working agreement (PRD Section 15)
- Explain any non-trivial change before making it: what's changing, why, tradeoffs
- Verify before declaring anything done — run it, test it, then say so
- Always flag what hasn't been confirmed to work yet
- If something is ambiguous, ask me rather than assuming and building the wrong thing
- Keep status updates brief and direct

---

**Note on datasets:** Sprint 1 has no dataset requirement — the PDF upload endpoint just needs to accept and store *a* valid PDF, any PDF, to prove the flow works. Real ingestion-corpus and Sprint 6 benchmark sourcing (arXiv bulk data, LitQA2 reference, etc.) comes later and is intentionally left out of this prompt.
