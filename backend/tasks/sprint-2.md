# Sprint 2 — PDF Processing

Scope: PRD Section 11, Sprint row 2 — *validation, SHA-256 hashing, duplicate detection,
metadata extraction, page extraction, text normalization, basic section detection.*
Nothing from Sprint 3+ (no chunking, no token counting, no embeddings, no retrieval).

Gates this sprint must satisfy (PRD Section 12):
- Extraction: page boundaries preserved · text ordering reasonably preserved · metadata stored · basic section info retained
- Upload: duplicates are detected · processing status is visible
- Reliability: errors logged · failed jobs diagnosable **and retryable** · long/malformed PDFs handled gracefully

Sprint 1 left behind (see PROGRESS.md handoff notes): `processing_jobs` rows that nothing
consumes, a populated `papers.sha256` with no dedup logic, and a `DocumentParser` interface
with no implementation. Sprint 2 closes all three.

## Confirmed available
- PyMuPDF 1.28.2 installs and imports cleanly on this Python 3.14 venv (checked before planning).

## Open questions — RESOLVED before building
1. **Duplicate policy** → per-project, reject with 409 returning the existing paper's id. Backed by `UNIQUE(project_id, sha256)`.
2. **Job execution model** → FastAPI `BackgroundTasks`, in-process, with startup recovery for stranded jobs.

Full rationale for both in PROGRESS.md.

## Flagged: a gap in the PRD, not a decision I should make silently
PRD Section 12 requires "basic section info retained", but the Section 7 schema has nowhere
to put it — the only `section` field lives on `paper_chunks`, which is Sprint 3. Options are a
new `paper_sections` table, or JSONB on `paper_pages`. **Proposing a `paper_sections` table**
(sections span pages, so hanging them off a single page is wrong) and logging this as a PRD
schema gap in PROGRESS.md. Raise with the Cowork side rather than quietly amending Section 7.

## Tasks

### Schema
- [x] `0003_sections_and_jobs.sql` — add `paper_sections`; add whatever `processing_jobs` needs for retry (attempt count, timestamps)
- [x] Decide and apply the `papers.sha256` constraint per the dedup answer above
- [x] Leave `paper_pages.token_count` NULL — token counting is a Sprint 3 deliverable

### Parser (behind the existing interface)
- [x] `PyMuPDFParser` implementing `DocumentParser` from `app/services/providers.py`
- [x] Page-by-page text extraction, preserving page boundaries and reading order
- [x] Metadata extraction: title, authors, abstract, page count → existing `papers` columns
- [x] Text normalization: de-hyphenate line breaks, collapse whitespace, strip control chars, keep paragraph structure
- [x] Basic section detection. **Corrected from the plan: no font-size signal was used.** Numbered/roman headings plus a canonical IMRaD name list proved sufficient on real output, and a font-size heuristic would have added a second tuning surface for no measured gain. Revisit only if a real paper defeats the text heuristic.
- [x] Never trust the PDF: a corrupt/encrypted/zero-page file must fail cleanly, not crash the worker

### Pipeline
- [x] Ingestion service that walks a job through its stages, writing `stage`/`progress` as it goes
- [x] Wire it to upload per the execution-model answer
- [x] Failure path: job → `failed` with a readable `error`, paper → `failed`, nothing half-written
- [x] `POST /papers/{id}/reprocess` — retry a failed job (explicit Section 12 requirement)
- [x] Recover jobs stuck in `running` from a killed process. **Widened during verification:** also recovers `pending` jobs, because a paper uploaded before extraction existed sat pending forever with no recovery path and made the UI poll indefinitely.

### API + UI
- [x] `GET /papers/{id}/pages` — extracted page text
- [x] `GET /papers/{id}/sections` — detected sections
- [x] Duplicate response shape per the answer above
- [x] UI: live status while processing, page/section counts when ready, error + retry button when failed

### Tests
- [x] Parser unit tests on real generated PDFs: page count, boundaries, ordering, normalization
- [x] Section detection on a paper with real IMRaD headings
- [x] Duplicate upload behaves per the decision
- [x] Malformed/corrupt/encrypted PDF → job `failed` with a useful error, no crash, no partial rows
- [x] Reprocess endpoint recovers a failed job
- [x] Full pipeline integration test: upload → processed → pages and sections queryable
- [x] Sprint 1's tests still pass — **13 unchanged, 2 deliberately updated.** They asserted a job stays `pending`/`queued`, which was correct when nothing consumed jobs. Sprint 2 makes extraction run, so those assertions were changed to the new expected outcome, not deleted, and a new test covers the fact that the *upload response itself* is still returned while the job is queued.

### Verify
- [x] Run the suite, paste real output
- [x] Drive the whole flow in a browser with a real multi-page paper
- [x] Confirm extracted text ordering by eye against the source PDF — not just "it ran"
- [x] Update PROGRESS.md with verified vs. unverified

## Explicitly NOT in this sprint
Chunking · token counting · overlap · embeddings · pgvector queries · retrieval · reranking ·
LLM calls · figures/tables/equations (Phase 2) · auth · Supabase

## Review

### Verified (each actually run)
| Check | Result |
|---|---|
| Backend test suite | **54/54 passing** (15 at end of Sprint 1) |
| Migrations | `0003` applied; `--status` clean; re-run is a no-op |
| Extraction end to end in browser | upload → background extraction → `ready`, 3 pages, title + authors from PDF |
| Page boundaries & ordering | read extracted text against the source by eye, not just asserted |
| De-hyphenation | `break-\nthroughs`→`breakthroughs`; `state-\nof-the-art` keeps its real hyphen |
| Paragraph breaks | confirmed on a real PDF after the fix below (0 → 2 breaks on page 1) |
| Section detection | correct nesting (`3.1` = level 2), correct pages, running headers not duplicated |
| Duplicate upload | 409 naming the existing file; same PDF in another project still accepted |
| DB-level dedup | `UniqueViolation` asserted directly against the constraint |
| Corrupt PDF | job `failed` at stage `parsing`, real error in UI, Retry offered, no partial rows |
| Retry | failed paper reprocesses to `ready`; repeated reprocessing does not duplicate pages |
| Frontend build / TypeScript / ESLint | all clean |

### Five bugs found by verifying rather than reviewing
1. **Section detection ran on normalized text.** Normalization deliberately collapses the single newlines that make a heading a heading, so zero sections were ever detected. Detection now reads raw text and resolves offsets into cleaned text.
2. **Abstract extraction had the same root cause** — it searched normalized text for a following heading that no longer existed as a line. Now derived from the already-detected section boundaries.
3. **De-hyphenation corrupted real compounds.** `state-\nof-the-art` became `stateof-the-art`: the greedy quantifier backtracked to a partial word and defeated the guard. Fixed by anchoring to a word boundary.
4. **Papers uploaded before extraction existed were unrecoverable** — stuck `pending` forever, with the UI polling indefinitely and no Retry offered. Startup recovery now covers `pending`, and Retry is available for it.
5. **Normalization destroyed every paragraph break.** PDFs pad visually-blank lines with spaces; single newlines were collapsed *before* that padding was trimmed, so `\n\n` never formed. This would have left Sprint 3's paragraph-aware chunker with nothing to chunk on. Fixed by trimming whitespace around line breaks first, plus a regression test.

### Known limitations (not defects, but do not assume otherwise)
- **Section detection is text-heuristic only.** A paper whose headings are neither numbered nor canonically named will yield no sections. `paper_sections.start_offset` is NULL when a heading cannot be relocated after normalization — consumers must handle that.
- **Extraction does not survive a restart mid-run.** Accepted tradeoff of the in-process model; mitigated by startup recovery, not eliminated.
- **Tests share the app's database**, and `recover_stranded_jobs()` is global, so running the suite mutates non-test rows. It did so during this sprint. Fix before the suite grows.
- **Abstract extraction depends on an "Abstract" heading** being detected. Papers that mark it differently return NULL rather than a wrong value.
