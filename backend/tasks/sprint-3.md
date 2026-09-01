# Sprint 3 — Chunking + Embeddings

Scope: PRD Section 11, Sprint row 3 — *section/paragraph-aware chunker, token counting,
overlap, EmbeddingProvider abstraction, pgvector storage, retrieval endpoint.*
Nothing from Sprint 4+ (no reranking, no context builder, no LLM calls, no grounded answers).

Relevant PRD constraints:
- §3.2 — chunk size (400 / 600 / 800 tokens) is to be **benchmarked**, not assumed. Sprint 3
  must therefore make chunk size a configurable variable, not a hardcoded number.
- §5.1 step 7 — query time is semantic retrieval (~top 20) → rerank → top 5–8. **Reranking is
  Sprint 4**, so this sprint's retrieval endpoint returns semantic hits only.
- §5.2 — chunk → page → paper must stay resolvable, so a citation can say "Section 3.2, Page 7".

Sprint 2 left behind (PROGRESS.md handoff): `paper_pages.cleaned_text` with paragraph breaks
intact, `paper_sections.start_offset` (nullable) for mapping chunks to sections,
`paper_pages.token_count` NULL pending a tokenizer choice, and `paper_chunks.embedding` as an
unconstrained `vector` with no index.

## Confirmed available (checked before planning)
- `fastembed` and `tiktoken` both resolve on this Python 3.14 venv.

## Open questions — RESOLVED before building
1. **Embedding provider** → local via `fastembed`. No API key, no spend, no network at
   inference, and real embeddings run in the test suite.
2. **Test isolation** → fixed this sprint. The suite now owns `research_intelligence_test`.

Rationale for both, plus the model change forced by PRD §3.2, is in PROGRESS.md.

## Still open from earlier, not mine to close
- PRD §7 does not list `paper_sections` (flagged in Sprint 2). Unchanged on the Cowork side.
- PRD §12's "retrieval measurable against benchmark data" still gates Phase 2 on a Sprint 6
  deliverable. Sprint 3 produces retrieval that *can* be measured; it does not resolve the gap.

## Tasks

### Tokenizer + chunker
- [x] Tokenizer behind a small seam (choice follows the embedding decision)
- [x] Backfill `paper_pages.token_count`, which Sprint 2 deliberately left NULL
- [x] Section/paragraph-aware chunker: respect paragraph breaks, never split mid-sentence where avoidable, attach each chunk to its section
- [x] Token-bounded with configurable size + overlap (default documented, 400/600/800 all settable)
- [x] Preserve `start_offset`/`end_offset` into the page so chunk → page → paper resolves

### Embeddings
- [x] `EmbeddingProvider` implementation behind the existing interface
- [x] Batch embedding, so a long paper is not one call per chunk
- [x] Deterministic fake for tests. **Narrower than planned, deliberately:** a fake `TokenCounter` (`WordCounter`) makes chunker behaviour testable without loading a 120MB model, but there is **no fake EmbeddingProvider** — the embedding and retrieval tests run the real model. A stub would have made the semantic assertions meaningless, and since the model is local there is no cost or network reason to avoid it.
- [x] Fail loudly and land on the job's `error` if embedding fails — no silent half-embedded paper

### Schema + storage
- [x] Migration: fix `paper_chunks.embedding` dimensionality to the chosen model
- [x] ANN index appropriate to the dimensionality and expected volume
- [x] Record which model/dimension produced a chunk, so a model change is detectable rather than silently mixing vector spaces

### Pipeline
- [x] Extend ingestion with chunking + embedding stages, reporting `stage`/`progress`
- [x] Reprocess must remain idempotent (no duplicate or orphaned chunks)

### Retrieval
- [x] `POST /projects/{id}/search` (or equivalent) — embed query, semantic top-k
- [x] Results carry page, section, and paper so citations resolve later
- [x] Explicitly NOT reranked — that is Sprint 4

### Tests
- [x] Chunker: boundaries, overlap, size bounds, section attribution, offset correctness
- [x] Token counting
- [x] Embedding provider contract, incl. batching and failure
- [x] Retrieval returns the semantically right chunk for a known corpus
- [x] Reprocess does not duplicate chunks
- [x] Sprint 1 + 2 tests still pass — **53 unchanged, 1 deliberately inverted.** `test_token_count_is_left_null_for_sprint_3` asserted `paper_pages.token_count` stays NULL, which was correct while no tokenizer existed. Sprint 3 populates it, so the test now asserts the counts are present and plausible (non-zero, fewer tokens than characters) rather than being deleted.

### Verify
- [x] Run the suite, paste real output
- [x] Drive it in a browser: upload → chunks + embeddings → search returns sensible hits
- [x] Read retrieved chunks by eye and confirm they actually answer the query — not just "it returned rows"
- [x] Update PROGRESS.md with verified vs. unverified

## Explicitly NOT in this sprint
Reranking · context builder · evidence IDs · LLM calls · grounded answers · citations ·
chat UI · figures/tables/equations (Phase 2) · auth · Supabase · the Sprint 6 benchmark

## Review

### Verified (each actually run)
| Check | Result |
|---|---|
| Test suite | **91/91 passing** (54 at end of Sprint 2) |
| Clean-venv reproducibility | 91/91 in a venv built only from `requirements.txt` |
| Test isolation | suite owns `research_intelligence_test`; dev data confirmed untouched after a full run |
| Migrations | `0004` applied; `--status` clean; re-run is a no-op |
| Chunking | token budget honoured, paragraphs respected, sections attributed, offsets valid, chunks never span pages |
| PRD §3.2 sizes | 400 / 600 / 800 all usable, parametrized test |
| Embeddings | 512-dim, L2-normalized, deterministic; related text scores above unrelated |
| Token counting | uses the model's own tokenizer; reflects subword splits |
| Retrieval (synthetic) | three-topic corpus returns the correct page for three distinct queries |
| Retrieval (real papers) | ResNet content 0.83–0.89 vs. unrelated filler 0.65–0.69 |
| Storage integrity | every chunk has a vector, a model name, and a resolvable page |
| Browser end to end | ranked results with section, page, and similarity |
| Frontend build / TypeScript / ESLint | all clean |

### The decision that mattered most
The proposed embedding model (`bge-small-en-v1.5`) **truncates at 512 tokens**, but PRD §3.2
commits to benchmarking **400 / 600 / 800**-token chunks. Two of the three arms would have been
silently truncated — producing benchmark numbers that looked fine and meant nothing. Caught by
reading the model's actual limits before writing code, not after. Switched to
`jina-embeddings-v2-small-en` (512-dim, 8192-token context). Also checked and rejected
`all-MiniLM-L6-v2`, which truncates at only 256.

### Worth recording for next time
An early `SELECT count(*) FROM paper_chunks` returned zero and briefly looked like embeddings
were not running at all. They were — the test fixture cascade-deletes its project at teardown.
**Counting rows after a suite run proves nothing;** the assertion has to happen inside the test.

### Known limitations (not defects)
- **Retrieval quality is unmeasured.** It is verified as *sensible* on a handful of documents,
  not measured against a benchmark. PRD §12 requires that before Phase 2, and the benchmark is
  a Sprint 6 deliverable — the sequencing gap is still open.
- **Chunk defaults are unvalidated.** 600/80 is a mid-range starting point, not a finding. §3.2's
  benchmark is what should set it.
- **Vectors are model-specific.** Changing the model invalidates every stored vector; mixing
  models degrades ranking silently rather than erroring. `embedding_model` per chunk makes this
  detectable, but nothing currently enforces it.
- **First call after an API restart pays ~25s** of model load.
- Content before the first heading has `section = NULL`. Sprint 4 citations must degrade to
  "page N" rather than rendering "null".
