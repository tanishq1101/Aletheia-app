# Sprint 1 — Foundation Scaffolding

Scope: PRD Section 11, Sprint row 1. Nothing from Sprint 2+.
End state (PRD 11.1): open app → create/select project → upload PDF → backend stores it → paper record exists → processing job exists → UI shows status.

## Decisions already locked (see PROGRESS.md)
- Clean start, no existing code to preserve.
- Local Postgres + pgvector via docker-compose; Supabase wired in later.
- Repo root = existing project folder (not a nested `research-intelligence/`).
- Plain SQL migrations + runner script; raw SQL, no ORM.
- Storage interface + local filesystem backend only; no Supabase backend yet.

## Tasks

### Repo + config
- [x] Directory skeleton — created `apps/web`, `apps/api`, `scripts`. **Not** created: `packages/shared` (nothing is shared yet), `docker/` (root `docker-compose.yml` is enough), `evaluation/` (Sprint 6). Per PRD §8, structure is added when something needs to live there.
- [x] `.gitignore` — must exclude `.env`, storage dir, `node_modules`, `__pycache__`, `.venv`
- [x] `.env.example` with every var named, no real values
- [x] `docker-compose.yml` — one `pgvector/pgvector:pg17` service (matches the pg17 on the Supabase account)
- [x] `README.md` — how to run it, in order
- [x] `git init` (no commit without asking)

### Database
- [x] `0001_init.sql` — `users`, `projects`, `papers`, `processing_jobs` with real FKs, plus table shells for `paper_pages`, `paper_chunks`, `citations`, `conversations`, `messages`; `vector` extension enabled; `paper_chunks.embedding` column declared but nothing writes to it
- [x] Seed one fixed-UUID dev user (Sprint 1 has no auth; `projects.user_id` still needs a real owner)
- [x] `scripts/migrate.py` — applies numbered SQL files, tracks what ran, idempotent

### Backend (FastAPI)
- [x] `main.py` + settings loaded from env via Pydantic, fail loudly on missing required vars
- [x] DB connection helper (pool, no ORM)
- [x] `GET /health` — reports DB reachability, not just `{"ok": true}`
- [x] `POST /projects`, `GET /projects` — needed for "create/select a project"
- [x] `POST /projects/{id}/papers` — validate PDF, store bytes, insert `papers` row + `processing_jobs` row (status `pending`), return status
- [x] `GET /projects/{id}/papers` — status for the UI
- [x] Storage: `StorageBackend` protocol + `LocalStorage` implementation
- [x] Structured logging; errors surfaced, never swallowed. **Corrected from the original plan:** no code path sets a job to `failed` in Sprint 1, because nothing processes jobs yet — a job that never runs cannot fail. Upload failures are logged and returned as HTTP errors instead. The `status`/`error` columns are shaped for Sprint 2's pipeline to use.
- [x] AI provider interface stubs (`LLMProvider`, `EmbeddingProvider`, `RerankerProvider`, `DocumentParser`). **Written as `typing.Protocol` rather than base classes raising `NotImplementedError`** — structural typing means Sprint 2+ implementations need no import of or inheritance from this module, which is a cleaner swap seam and keeps zero runtime behavior in Sprint 1.

### Frontend (Next.js)
- [x] Scaffold: TypeScript + Tailwind, App Router
- [x] API client in `lib/`
- [x] Project create/select
- [x] PDF upload with client-side type check
- [x] Paper list showing per-paper processing status
- [x] Visible error states — no silent failures

### Tests
- [x] `/health` test
- [x] Upload happy path — asserts paper row AND job row both created, file actually landed in storage
- [x] Upload rejects non-PDF (wrong extension, wrong content type, and a `.pdf` that isn't one)
- [x] Upload to a nonexistent project returns 404, creates nothing
- [x] Run the suite and paste real output before marking anything done

### Verify
- [x] `docker compose up` → migrate → API boots → tests green
- [x] Manual end-to-end: real PDF through the browser UI, status visible
- [x] Confirm no secret values committed anywhere
- [x] Update PROGRESS.md with what was verified vs. what wasn't

## Explicitly NOT in this sprint
PyMuPDF text extraction · page/section parsing · chunking · embeddings · pgvector queries · retrieval · reranking · LLM calls · duplicate detection · auth · Supabase storage backend · anything under `evaluation/`

## Open question for the user — RESOLVED
`papers.sha256` vs. Sprint 2's "SHA-256 hashing, duplicate detection". **Decided: compute and store the hash, implement no duplicate detection.** The column is populated on upload; `idx_papers_sha256` exists but is deliberately not a uniqueness constraint, leaving Sprint 2 free to choose the dedup policy.

## Review

### What was actually verified (each run, not assumed)
| Check | Result |
|---|---|
| Postgres 17 + pgvector container | healthy; `vector` + `pgcrypto` enabled |
| Migrations | both applied; re-run is a no-op |
| Backend test suite | 15/15 passing |
| `/health` healthy | 200 `{status: ok, database: ok, storage: ok}` |
| `/health` degraded | 503 with real reason, tested by stopping the DB container |
| Pool recovery after DB restart | immediate (was ~20s of failures before the fix) |
| Browser end-to-end §11.1 | project → upload real 3-page PDF → paper + job rows → status badge |
| Stored file integrity | sha256 byte-identical to source |
| Invalid upload | 400 on magic bytes, message shown in UI, zero rows and zero files left behind |
| Project switching | no paper leakage between projects |
| Frontend build / TypeScript / ESLint | all clean |

### Two defects found by verifying rather than reviewing
1. **Connection pool did not recover from a database restart.** psycopg's pool kept handing out dead connections, so every request failed for ~20 seconds after any DB blip. Fixed with a connection check on checkout; re-verified by restarting the container mid-flight.
2. **Render-then-fetch cascade on the papers list.** ESLint's `set-state-in-effect` flagged it. Restructured to fetch from the selection events instead of an effect watching the selection, and the rendered list is now derived from the selected project, which also removed a potential stale-paper flash when switching projects.

### Explicitly NOT verified
- **Supabase** — no Supabase code path has ever executed. The Storage backend for it is not written, and `SUPABASE_*` env vars are unused. This is the decided Sprint 1 scope, not an oversight.
- **Auth** — does not exist; all projects belong to one seeded dev user.
- **Job processing** — jobs are created `pending` and nothing consumes them. Correct for Sprint 1.
- **Scale/malformed PDFs** — only the size limit and the PDF header are checked. Structural robustness against malformed or very long PDFs is Sprint 2, when the file is actually parsed.
