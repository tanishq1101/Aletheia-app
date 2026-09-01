# Project Progress Log — AI Research Intelligence Platform

Shared status file for coordinating implementation, planning, documentation, and research on this project. Anyone who touches this project should read this file first and update it before signing off.

## Current phase / sprint
Phase 1, **Sprint 6 (Evaluation) — code complete; every metric that does not need an LLM is measured and recorded** as of 2026-08-25. **Sprint 5 (Chat UI) is still not started** — Sprint 6 was pulled forward ahead of it at the user's direction.

**Verified working** (each actually run):
- **194/194 tests passing**, 2 skipped (the live OpenRouter tests, which skip cleanly with no key). 133 at end of Sprint 4.
- **A real corpus exists for the first time**: 10 arXiv papers (198 pages, 389 chunks, all embedded), pinned by SHA-256 in `datasets/corpus/manifest.json` and reproducible byte-for-byte via `scripts/fetch_corpus.py`. The pin was proven by corrupting a byte and confirming a non-zero exit — not assumed.
- **150-question benchmark** (`datasets/benchmark/questions.json`), 10 papers x 15, 121 answerable and 29 unanswerable.
- **The benchmark validates itself against the corpus.** Every `must_contain` term is machine-checked to appear in the text *this pipeline extracted* from that question's own gold pages, using the pipeline's own parser. A question written from recollection fails the suite.
- **Reranking earns its place at scale, not just on a constructed example.** Measured below.
- Retrieval, rerank lift, evidence sufficiency and latency all measured over 121 answerable questions.
- Answer correctness, citation accuracy, faithfulness and unanswerable handling are **implemented, wired and untested against a live model** — they skip with a stated reason because no key is configured.

### Measured: retrieval, over 121 answerable questions
Config: 20 candidates -> 6 evidence blocks, 600-token chunks, `jinaai/jina-reranker-v1-turbo-en`.

| Metric | Before rerank | After rerank | Lift |
|---|---|---|---|
| recall@6 | 0.742 | 0.821 | **+0.079** |
| MRR | 0.585 | 0.719 | **+0.134** |

hit@6 = 0.876 · **evidence sufficiency = 0.884** · retrieve p50 14ms · rerank p50 1048ms · end-to-end p50 1065ms.

**Read the shape, not just the numbers.** Recall moves far less than MRR, which says the right page is usually already somewhere in the 20 candidates — what reranking fixes is *where it ranks*, which is exactly what it is for. Sprint 4 demonstrated this on one hand-built distractor query; this is the same effect across 121 real questions.

**Evidence sufficiency (0.884) is the ceiling on answer correctness**, and it needs no LLM to compute. It is the fraction of questions whose assembled evidence blocks actually contain every required answer term. The gap from 1.0 belongs to retrieval; the gap between it and correctness, once a key is set, belongs to the model. Reporting a bare correctness number without it would fuse two different failures into one.

### ⚠️ The trap this sprint existed to avoid — and it very nearly landed
A benchmark written from memory of these papers would produce a green report measuring nothing but its author's self-consistency. Two things stopped that:

1. **The gold-label verifier caught 3 mislabelled questions before any number was reported.** The cause was mundane and would have been invisible: I used each paper's *printed* page numbers (from its own table of contents) instead of the PDF's physical page index. That check is now `test_gold_pages_actually_contain_the_expected_answers`, so the same mistake fails CI rather than silently depressing recall forever.
2. **Of 19 apparent retrieval misses, 6 looked like incomplete gold labels — but only 4 were.** Each was checked against the extracted text and three were rejected as keyword false positives: rag-09's "11.8%" on page 8 is a *Jeopardy human-evaluation row*, not the Natural Questions figure; gpt3's page 12/22 hits on "175" are the model's *name*, not a statement of its parameter count. Adjusting labels after seeing results deserves scrutiny, so the rule applied was explicit: **a gold page is any page that independently supports the answer — a property of the corpus, not of the system's output.**

### ⚠️ Bug found by real PDFs that the generated fixtures could never surface
**4 of the 10 papers failed to ingest**: `PostgreSQL text fields cannot contain NUL (0x00) bytes`. The NULs are not corruption — they are *unmapped maths glyphs*. LaTeX's `\big(` and `\big)` fail their font's ToUnicode CMap and PyMuPDF emits them as raw C0 control bytes, so `exp\x00d(z)⊤q(x)\x01` is really `exp(d(z)ᵀq(x))`. `normalize_page_text` already stripped these, but `raw_text` is persisted **unnormalized on purpose** (section detection needs the line structure normalization collapses), so it had no guard.

Fixed in `sanitize_for_storage`, applied at the extraction boundary in `parsing.py` so no consumer of `ParsedPage` ever sees a byte the database cannot store. **The substitution is length-preserving by design** — NUL becomes a space, never nothing — because `paper_sections.start_offset` and the chunk offsets are positions into that string, and a shortening substitution would slide every offset after the NUL out of alignment. That would have shown up as citations pointing at the wrong section, not as an error. Six regression tests, including the offset-preservation property.

### Known limitation, stated rather than papered over
Keyword correctness can be satisfied by the **wrong paper's** numbers: vgg-04 expects "256" and "0.9", and ResNet happens to use the same values. The mitigation is the metric *pair* — an answer taking those from ResNet would cite a ResNet page and score zero citation precision. Neither metric is sufficient alone, which is why both are reported rather than averaged into one score.

### Sprint 6 decisions (resolved before building)
- **Corpus** → 10 real arXiv PDFs, user-approved download, SHA-256 pinned, PDFs gitignored. *Why:* ~13MB of binaries that are not ours to redistribute; a manifest plus a fetch script reproduces them exactly.
- **Gold labels are page-level, never chunk-level.** *Why:* chunk ids are regenerated on every reprocess and their boundaries move with `CHUNK_MAX_TOKENS`. A chunk-keyed benchmark would be invalidated by the very 400/600/800 sweep PRD §3.2 requires. Pages are a stable property of the PDF.
- **No LLM judge.** *Why:* it would put a second unverified model inside the measurement and charge per run. Deterministic `must_contain` / `must_not_contain` assertions are weaker per question; the compensation is 150 of them.
- **LLM-dependent metrics gate on the key and say so.** *Why:* a 0% correctness score and an unrun correctness score are completely different facts, and reporting zeros would misrepresent the second as the first.

## Previous sprint
Phase 1, **Sprint 4 (RAG)** — completed 2026-08-24. The live LLM path was unverified then and is still unverified now; see the current sprint above.

**Verified working** (each actually run):
- **133/133 tests passing**, 2 skipped (the live OpenRouter tests, which skip cleanly with no key configured). 91 at end of Sprint 3.
- Reranking is **local** (fastembed cross-encoder, `jinaai/jina-reranker-v1-turbo-en`) — same no-key, no-spend, real-model-in-CI property as Sprint 3's embeddings.
- **Reranking demonstrably corrects semantic search rather than reshuffling it** — see the measured numbers below. This is the evidence that the stage earns its place.
- Evidence IDs are minted backend-side in rank order; the chunk UUID never appears in the prompt (asserted, not assumed).
- **Fabricated citations cannot reach the response.** A scripted model citing `[E99]` when handed five blocks has the ID stripped, the claim left visibly uncited, and the count reported in the response body so PRD §12's "zero fabricated citation IDs" is checkable from the outside.
- Insufficient evidence is a first-class outcome carrying `sufficient_evidence: false`, not an empty answer.
- A project with no chunks short-circuits before spending an LLM call.
- `section = NULL` degrades to "page 4" — never the string "null"/"None", in the prompt or the UI.
- Context is token-budgeted; evidence dropped for budget is counted and returned.
- LLM failures surface the provider's own message (402/"Insufficient credits", connect timeouts, malformed and empty completions all covered) as a 503, never swallowed.
- Frontend production build, TypeScript, and ESLint all clean.

**Not yet confirmed:** the **live OpenRouter path has never been executed** — no key was configured at time of writing, so the two live tests skip and no real model has answered a real question. Nothing about answer quality, latency, or cost is measured. Also still absent: Supabase unwired, no auth, no conversation persistence (deliberate — see below), and retrieval quality still unmeasured against a benchmark (PRD §12 / Sprint 6).

Sprint 3 archived at `tasks/sprint-3.md`; Sprint 4 record at `tasks/todo.md`.

### Sprint 4 decisions (resolved 2026-08-24, both were blocking)
- **LLM: OpenRouter**, OpenAI-compatible, key supplied by the user. Default model **`anthropic/claude-haiku-4.5`** (200K context, $1/$5 per M ≈ **$0.009 per answer** at ~7K in / ~400 out). *Why that model:* grounding and honest refusal are instruction-following problems, and that is what the extra cost buys. Alternatives checked live on OpenRouter's model list and recorded in `.env.example`: `google/gemini-3.1-flash-lite` ($0.25/$1.50) and `openai/gpt-5-mini` ($0.25/$2.00). *How to apply:* `OPENROUTER_MODEL` is config — switching provider means writing another class with a `complete` method, nothing else.
- **Answers are stateless.** `POST /projects/{id}/answer` returns the answer with fully resolved citations in the response body; **nothing is written to `conversations`, `messages`, or `citations`.** *Why:* PRD §7 makes `citations.message_id` a NOT NULL foreign key, so persisting a citation requires a message row — and conversations are a Sprint 5 deliverable. Writing them now would be phase bleeding. Citation *resolution* is fully delivered; only its persistence waits. *Consequence:* no migration this sprint.

### ⚠️ The Sprint 3 truncation trap, found again in a new place
Sprint 3 rejected an embedding model for truncating at 512 tokens while PRD §3.2 benchmarks 600- and 800-token chunks. The same trap is present in reranking, and **picking an 8K model does not by itself avoid it**: `fastembed` pins *every* cross-encoder tokenizer to `max_length=512` at load, whatever the model supports.

Measured, before the cap was lifted: a passage with the answer buried at token ~700 and the same passage without it scored **identically — delta exactly 0.000**. The model never saw the difference. Lifting the cap separates them. `FastEmbedReranker._ensure_model` now raises the limit explicitly and fails loudly if it cannot reach the tokenizer, and a test asserts the separation so a future `fastembed` upgrade that re-pins the cap breaks the suite instead of quietly degrading every ranking.

*Both the obvious default (`Xenova/ms-marco-MiniLM-L-6-v2`) and the chosen model showed delta 0.000 under the default cap — the model card alone would have been misleading either way.*

### Measured: reranking corrects semantic search, it does not just reshuffle it
Query: *"What batch size did the authors use to train the network?"* against three passages, one of which actually contains the number.

| Passage | cosine | rank | rerank | rank |
|---|---|---|---|---|
| contains "mini-batch size of 256" | 0.8253 | **3** | −0.907 | **1** |
| general prose about training | 0.8323 | 1 | −1.057 | 2 |
| about batch normalization | 0.8297 | 2 | −1.865 | 3 |

Cosine puts the passage that actually answers the question **third**, and spreads all three across **0.007** of similarity — not a margin any decision can rest on. The cross-encoder reads query and passage together and puts the right one first. Locked in as `test_reranking_beats_cosine_on_a_distractor`.

## Previous sprint
Phase 1, **Sprint 3 (chunking + embeddings) — code complete and verified end to end** as of 2026-08-24. Sprint 4 (RAG) not started.

**Verified working** (each actually run):
- **91/91 tests passing** (54 at end of Sprint 2), and passing in a clean venv built only from `requirements.txt`.
- **Test isolation fixed:** the suite creates and migrates its own `research_intelligence_test` database via the same migration runner as the app. Confirmed dev data is untouched after a full run.
- Chunking: token-bounded, paragraph-aware, sentence-granular overlap, section attribution, offsets into the page. Chunks never span pages, so a citation always resolves to one page (PRD 5.2).
- All three PRD §3.2 benchmark sizes (400 / 600 / 800) are usable and covered by a parametrized test — the reason the model was switched.
- Embeddings: real model, 512-dim, L2-normalized, deterministic for identical input; related text scores above unrelated.
- Token counting uses the model's own tokenizer and reflects subword splits, so chunk budgets mean what they say.
- **Retrieval verified semantically, not just structurally:** a three-topic corpus returns the correct page for each of three distinct queries, and on real papers ResNet content ranks 0.83–0.89 while an unrelated filler document ranks 0.65–0.69.
- Search scoped to its project; reprocess does not duplicate chunks; every stored chunk has a vector, a model name, and a resolvable page.
- Verified in a browser end to end, including the ranked result list with section and page attribution.

**Not yet confirmed / deliberately absent:** no reranking, context builder, evidence IDs, LLM calls, or grounded answers — all Sprint 4. Supabase still unwired. No auth. Retrieval quality has **not** been measured against a benchmark; PRD §12 still requires that, and the benchmark is a Sprint 6 deliverable (unresolved sequencing gap, below).

Sprint 2 archived at `tasks/sprint-2.md`; Sprint 3 record at `tasks/todo.md`.

### Sprint 3 decisions (resolved 2026-08-24, both were blocking)
- **Embeddings: local via `fastembed`** (ONNX, offline, no API key, no spend, real embeddings runnable in CI). Hosted providers stay a config swap behind `EmbeddingProvider`.
- **Test isolation: fixed this sprint.** Tests move to their own database instead of sharing the app's and mutating real rows.

### ⚠️ Model choice changed from what was proposed — PRD §3.2 forced it
Proposed `BAAI/bge-small-en-v1.5` (384-dim). **Rejected after checking the actual model limits: it truncates at 512 input tokens.** PRD §3.2 commits to benchmarking chunk sizes of **400 / 600 / 800 tokens** — with a 512-token model, the 600 and 800 arms would be silently truncated and produce meaningless benchmark numbers that still look successful. That is exactly the "never silently swallow" failure the PRD warns against.

**Using `jinaai/jina-embeddings-v2-small-en` instead: 512-dim, 8192-token context, 120MB.** It covers all three benchmark arms with headroom. Verified working on this Python 3.14 venv: loads in ~25s, embeds in ~0.01s, returns L2-normalized vectors (so cosine is the right pgvector index).

*Consequence:* `paper_chunks.embedding` is fixed at **512 dimensions**. Changing the model later means re-embedding every chunk, so the chunk rows record which model produced them.

*Also checked and rejected:* `all-MiniLM-L6-v2` truncates at only **256** tokens — worse for this purpose than either.

**Token counting uses the embedding model's own tokenizer**, not `tiktoken`. `tiktoken` is OpenAI's BPE and would miscount for this model, and chunk sizes must be measured in the tokens the model actually sees.

## Previous sprint
Phase 1, **Sprint 2 (PDF processing) — code complete and verified end to end** as of 2026-08-24. Sprint 1 archived at `tasks/sprint-1.md`; Sprint 2 record at `tasks/todo.md`. Sprint 3 (chunking + embeddings) is not started.

**Verified working** (each actually run, not assumed):
- **54/54 backend tests passing** (15 at end of Sprint 1).
- Extraction end to end in a browser: upload → background extraction → `ready`, with page count, title, and authors populated from the PDF.
- Page boundaries and reading order preserved; verified by reading extracted text against the source, not just by assertion.
- De-hyphenation correct in both directions: `break-\nthroughs` → `breakthroughs`, while `state-\nof-the-art` keeps its real hyphen.
- Section detection with correct nesting (`3.1` renders as level 2 under `3 Methods`) and correct page attribution; running headers are not counted as repeat sections.
- Duplicate re-upload rejected with 409 naming the existing file; the same PDF in a different project is still accepted. Backed by `UNIQUE(project_id, sha256)`, asserted at the database level in a test.
- Failure path: corrupt PDF → job `failed` at stage `parsing`, real error shown in the UI, Retry offered, no partial pages or sections written.
- Retry works: a failed paper reprocesses to `ready`, and repeated reprocessing does not duplicate pages or sections.
- Stranded jobs recovered on startup, including papers uploaded before extraction existed.

**Not yet confirmed / deliberately absent:** Supabase still entirely unwired. No auth. No chunking, token counting, or embeddings (`paper_pages.token_count` is deliberately NULL — Sprint 3). Extraction is in-process, so it does not survive a server restart mid-run; that is the accepted tradeoff, mitigated by startup recovery rather than eliminated.

### Sprint 2 decisions (resolved 2026-08-24, both were blocking)
- **Duplicate policy: per-project, reject with 409.** Same sha256 already in the *same* project is a duplicate and is rejected, returning the existing paper's id so the UI can point at it. The same PDF in a *different* project stays a separate paper record. *Why:* global dedup would couple projects together — deleting a paper in one project would affect another, which complicates every later sprint. *How to apply:* enforced by a `UNIQUE(project_id, sha256)` constraint so the database guarantees it rather than app code alone.
- **Job execution: FastAPI BackgroundTasks, in-process.** Upload returns immediately; extraction runs after the response. *Why:* no new libraries or infrastructure beyond PRD Section 6, while keeping status visible and jobs retryable. *Known tradeoff, handled explicitly:* jobs die if the process is killed mid-run, so startup recovery marks stranded `running` jobs as failed and retryable. Revisit a real worker only if ingestion volume justifies it.

### ⚠️ Gap found in the PRD — needs an explicit decision, not a silent patch
PRD **Section 12 requires "basic section info retained"**, but the **Section 7 schema has nowhere to put it**. The only `section` field is on `paper_chunks`, which is a Sprint 3 entity — so satisfying a Sprint 2 acceptance criterion would require writing to a Sprint 3 table, which is phase bleeding.

Proceeding with a new **`paper_sections` table** (sections span multiple pages, so hanging them off a single `paper_pages` row would be wrong). Flagging rather than quietly amending Section 7: **Section 7 should be updated to include `paper_sections` as a Phase 1 entity.**

**Verified working** (not assumed — each was actually run):
- docker-compose Postgres 17 + pgvector, healthy; `vector` + `pgcrypto` extensions enabled.
- Both migrations applied; re-running is a no-op (idempotency confirmed).
- 15/15 backend tests passing.
- `/health` returns 200 when healthy and 503 with a real reason when the DB is down (tested by stopping the container).
- Full PRD §11.1 flow driven through a real browser: create project → upload a genuine 3-page 18KB PDF → `papers` row + `processing_jobs` row created → status badge rendered. Stored file confirmed **byte-identical** to the source (sha256 match).
- Rejection path: a non-PDF named `.pdf` is refused on magic bytes, the backend's own message is shown in the UI, and **no row and no file are left behind**.
- Project switching does not leak papers between projects.
- Frontend production build, TypeScript, and ESLint all clean.

**Not yet confirmed / deliberately absent:** Supabase (DB + Storage) is entirely unwired — no Supabase code path has ever been executed. Auth does not exist; every project belongs to one seeded dev user. Nothing consumes `processing_jobs`, so jobs sit in `pending` forever by design until Sprint 2.

## Coordination rule (read before touching this project)
This file is the shared source of truth for the project. Read it before making changes, and update it before you stop working, not just at the end of a session. Log blockers and decisions as they happen, not retroactively.

## Open decisions (blocking Sprint 1 execution — see PRD Section 11.2)
- [x] **Does a repo already exist with partial work, or starting clean?** — RESOLVED 2026-08-23: **clean start.** Project folder contained only `PRD.md`, `PROGRESS.md`, and `docs/dataset-references.md`. No `apps/`, no source code, and not a git repository. Nothing to preserve or overwrite.
- [x] **Supabase provisioned, or local Postgres + pgvector first?** — RESOLVED 2026-08-23: **local Postgres + pgvector via docker-compose first; Supabase wired in afterward.** Checked the connected Supabase account — two projects exist (`expire-x`, `tanishq1101's Project`, both ap-south-1) but neither belongs to this platform, so nothing was provisioned for it. User chose local-first. *Why:* Sprint 1 reaches a green test suite with no network dependency, no live credentials, and no billing decision; Supabase becomes a config swap later. *How to apply:* all DB/storage access sits behind a seam so the swap does not touch application logic. Migrations are written as plain SQL files so the Supabase CLI can consume them unchanged when we migrate.

### Decisions made during Sprint 1 execution
- **Repo root = the existing project folder**, not a nested `research-intelligence/` directory as drawn in PRD Section 8. *Why:* `PROGRESS.md` is specified as living at the project root and is the shared source of truth; nesting the code under a subfolder would orphan it from the repo it describes. `docs/` already sits at this level. Section 8's tree is explicitly a guideline, not a mandate.
- **Storage: interface + local filesystem backend only in Sprint 1.** The Supabase Storage backend is deliberately NOT written yet. *Why:* we cannot verify it against a project that does not exist, and writing an untested implementation would violate the "never claim done without verification" principle. The interface is the seam; the Supabase backend lands when a project is provisioned.
- **Migrations: plain numbered SQL files + a small runner script**, no ORM/Alembic. *Why:* PRD Section 6 lists no migration library, four tables do not justify one, and plain SQL matches the format the Supabase CLI already consumes — making the eventual move a file move rather than a rewrite.
- **DB access: raw SQL via a Postgres driver, no ORM.** *Why:* Section 6 specifies FastAPI + Pydantic only; Sprint 1 has a handful of queries and an ORM would be over-engineering at this scope.

## Handoff notes for Sprint 5 (Chat UI)
Sprint 6 ran ahead of this one, so Sprint 5 now inherits a measured baseline it can regress against — re-run `python scripts/run_benchmark.py` after any retrieval or prompt change and compare to `datasets/benchmark/results/`.

- **`POST /projects/{id}/answer` returns everything the chat UI needs**: answer text, `sufficient_evidence`, resolved `citations` (paper, page, section, pre-rendered `location`, snippet), the full `evidence` set whether cited or not, and `fabricated_citations_removed`. `AnswerPanel.tsx` already renders all of it and is the obvious starting point.
- **Persistence is the first thing Sprint 5 has to add.** Answers are stateless today by deliberate decision. `conversations`, `messages`, and `citations` are still empty shells from migration `0001` — and `citations.message_id` is NOT NULL, so a message row must be written before a citation row.
- **Do not move citation validation into the frontend.** `strip_fabricated_citations` runs server-side before an answer is ever serialized, so an invented ID cannot reach a client at all.
- The answer endpoint is **synchronous and takes as long as the model does**. Streaming means either an SSE variant of this endpoint or a streaming `complete` on `LLMProvider` — the latter changes the interface, so decide before building. **If the interface changes, `scripts/run_benchmark.py` calls `answer_question` directly and will need the same treatment.**
- **`sufficient_evidence: false` is a successful answer, not an error.** 29 of the 150 benchmark questions exist specifically to exercise it; rendering it as a failure state would defeat PRD §5.4 and tank the faithfulness metric.
- Retrieval stays exposed separately at `POST /projects/{id}/search` — the benchmark depends on that seam to measure retrieval and answer quality independently. Do not collapse the two endpoints.
- **The first request after an API restart is slow** — the embedding model (~25s cold) and the reranker both load lazily on first use. A full 150-question benchmark run takes about 3 minutes, dominated by reranking at ~1s per question.

## Superseded: handoff notes for Sprint 4 (RAG)
- **`POST /projects/{id}/search` already returns everything the context builder needs**: chunk id, content, section, page number, paper id/title, and similarity. Sprint 4 should rerank that candidate set down to 5–8, not re-query.
- **Do not let the LLM invent citation labels** (PRD §5.3). The evidence IDs handed to the model must be generated backend-side from the chunk ids this endpoint already returns, and resolved back through chunk → page → paper. That path is intact and tested.
- **A chunk can legitimately have `section = NULL`** — content before the first detected heading (a paper's title block, for instance). Citations must degrade to "page N" rather than rendering "null".
- **Vectors are model-specific.** Every chunk records `embedding_model`. If the model ever changes, existing vectors are invalid and must be re-embedded — comparing across models silently produces garbage rankings rather than an error. Check the column before assuming a project's vectors are comparable.
- Chunk size and overlap are `CHUNK_MAX_TOKENS` / `CHUNK_OVERLAP_TOKENS` in settings, and all three PRD §3.2 sizes are supported. Changing either requires reprocessing papers to take effect.
- Ingestion is still in-process (`BackgroundTasks`) and now does real model work. It is fast locally with a cached model, but Sprint 4's LLM calls are a good moment to revisit the worker decision.
- The embedding model loads lazily and takes ~25s on the very first call in a fresh process (cached thereafter). The first request after an API restart pays that cost.

## Known unresolved issues in the PRD
- Section 12 requires retrieval to be "measurable against benchmark data" before Phase 2 starts, but the benchmark (Sprint 6) is scheduled after the sprints that criterion gates. Needs a decision: pull a rough benchmark earlier, or treat the criterion as unenforceable until Sprint 6.
- Phase 6 ("reproducibility scoring, AI peer review") has not been confirmed as trained-model-based vs. heuristic/prompted. This determines whether any model training work is in scope at all, and if so, which dataset tier (S2ORC / PMC) applies. Currently unresolved — do not start pulling large training corpora until this is answered.

## Datasets — status
- **Ingestion corpus: DONE.** 10 arXiv papers in `datasets/corpus/`, pinned by SHA-256 in `manifest.json`, PDFs gitignored, reproduced by `scripts/fetch_corpus.py`. 198 pages, 389 chunks. Ingested into the project "Sprint 6 Benchmark Corpus" by `scripts/ingest_corpus.py`, which drives the real upload endpoint rather than a parallel copy of the pipeline.
- **Sprint 6 benchmark: DONE.** `datasets/benchmark/questions.json` — 150 hand-built questions (10 papers x 15), written from extracted text and machine-verified against it. Results land in `datasets/benchmark/results/` as timestamped JSON + Markdown.
- LitQA2 / PaperQA2 data: reference-only for Section 3 related work — still explicitly NOT reused as the benchmark, per PRD §3.2.
- Training-scale corpus (S2ORC / PMC): still on hold pending the Phase 6 scope decision above.

## Log
- **2026-08-25** — **Sprint 6 (Evaluation) complete: 194 passing, 2 skipped.** Taken out of order ahead of Sprint 5 at the user's direction; it closes PRD §12's known sequencing gap, which gated Phase 2 on a benchmark scheduled after the sprints it gates. Pulled a real 10-paper arXiv corpus (the first real PDFs this repo has ever ingested), built a 150-question benchmark, and measured retrieval end to end. **Reranking lifts MRR from 0.585 to 0.719 across 121 questions** — recall barely moves, so what it fixes is ranking, not coverage. Three findings worth carrying: (1) **real PDFs broke ingestion on day one** — 4 of 10 papers failed on NUL bytes that turned out to be unmapped LaTeX maths glyphs, a class of bug the generated fixture corpus structurally could not produce; the fix is length-preserving so section and chunk offsets stay aligned. (2) **The gold-label verifier caught three of my own mislabelled questions** before any number was reported — printed page numbers are not PDF page indices. (3) **Six apparent retrieval misses looked like bad labels; only four were** — the other three were keyword false positives, including an "11.8%" that belongs to a Jeopardy human-eval table rather than the Natural Questions result. Answer-side metrics are implemented and wired but **still unrun against a live model**, because `OPENROUTER_API_KEY` remains unset — they skip with a stated reason rather than reporting zeros.
- **2026-08-24** — **Sprint 4 backend + frontend complete: 133 passing, 2 skipped.** Reranking, context building, evidence IDs, citation resolution, and the OpenRouter provider all landed; `POST /projects/{id}/answer` is live and the frontend renders answers with clickable evidence markers and source cards. **The live LLM path is NOT yet verified** — no key was configured, so the two live tests skip and no real model has answered a real question. Everything else was run. Two findings worth carrying forward: (1) **fastembed silently caps every cross-encoder at 512 tokens** regardless of the model's real context, and the measured proof was two documents scoring identically to the last decimal — the reranker literally could not see past the shared prefix; the cap is now lifted explicitly and a test guards it. (2) **Reranking earns its place**: on a distractor query, cosine ranked the passage containing the answer *third* out of three, inside a 0.007 similarity spread, and the cross-encoder put it first. Also refactored Sprint 3's search SQL out of the endpoint into `services/retrieval.py`, since answering must rerank the same candidate set rather than re-query — two copies of that query would have drifted.
- **2026-08-24** — **Sprint 4 opened.** Reread PROGRESS.md and the PRD first. Both blocking decisions resolved before any code (OpenRouter for the LLM; stateless answers to avoid pulling Sprint 5's conversation model forward). Checked `fastembed`'s cross-encoder support and OpenRouter's live model list before planning around either, rather than assuming. Sprint 3 plan archived to `tasks/sprint-3.md`.
- **2026-08-24** — **Sprint 3 complete, 91/91 tests passing**, verified in a clean venv built only from `requirements.txt`. Frontend gained a semantic search panel showing ranked passages with section, page, and similarity. Verified in a browser against the two real dev papers: ResNet content ranks 0.83–0.89 for a residual-connections query while an unrelated filler document ranks 0.65–0.69, so the ordering is genuinely semantic rather than incidental. **A caution worth recording:** an early check of `paper_chunks` showed zero rows and briefly looked like embeddings were not running — it was the test fixture's cascade delete at teardown. Counting rows *after* a suite run proves nothing; assert inside the test.
- **2026-08-24** — **Sprint 3 backend complete: 91/91 tests passing** (54 at end of Sprint 2). Test isolation fixed first — the suite now creates and migrates its own `research_intelligence_test` database using the same migration runner as the app, so it can no longer mutate dev data (verified: dev rows untouched after a full run). Migration `0004` pins `paper_chunks.embedding` to `vector(512)`, adds an HNSW cosine index, and records `embedding_model`/`embedded_at` per chunk so a model swap is detectable rather than silently mixing vector spaces. Chunker is section/paragraph-aware, token-bounded, with sentence-granular overlap; chunks never span pages so a citation always resolves to one page (PRD 5.2). Ingestion gained `chunking` and `embedding` stages, batched at 32. `POST /projects/{id}/search` does semantic top-k. **Retrieval verified semantically, not just structurally** — a three-topic corpus returns the correct page for each of three distinct queries. Frontend not updated yet at time of writing.
- **2026-08-24** — **Sprint 3 opened.** Reread PROGRESS.md first (the PRD §7 `paper_sections` gap flagged in Sprint 2 remained open). Verified `fastembed` and `tiktoken` resolve on Python 3.14 before planning around them. Both blocking decisions resolved. **Caught a model/PRD conflict before writing any code:** the proposed embedding model truncates at 512 tokens while PRD §3.2 commits to benchmarking 600- and 800-token chunks — switched models rather than ship a benchmark that silently truncates two of its three arms. Details above.
- **2026-08-24** — **Sprint 2 complete, 54/54 tests passing.** Frontend updated: live status polling (only while a job is actually in flight), page counts, expandable section outline with nesting, per-paper error display, and a Retry button. **Two further bugs found by verifying rather than reviewing:** (1) papers uploaded before extraction existed sat at `pending` forever with no recovery path and caused the UI to poll indefinitely — startup recovery now also strands `pending` jobs, and Retry is offered for them; (2) **normalization destroyed every paragraph break** — PDFs pad "blank" lines with spaces, and single newlines were collapsed to spaces *before* that padding was trimmed, so `\n\n` never formed. This would have left Sprint 3's paragraph-aware chunker with no boundaries to chunk on. Fixed by trimming whitespace around line breaks first; confirmed on a real PDF (page 1 went from 0 to 2 paragraph breaks) and covered by a regression test.
- **2026-08-24** — **Sprint 2 backend complete: 52/52 tests passing** (was 15 at end of Sprint 1). Migration `0003` adds `paper_sections`, `UNIQUE(project_id, sha256)`, and job retry columns. `PyMuPDFParser` implements the widened `DocumentParser`; extraction runs as a background task and writes pages, sections, and metadata. Added `GET /papers/{id}/pages`, `GET /papers/{id}/sections`, `POST /papers/{id}/reprocess`, plus startup recovery for jobs stranded by a restart. **Three bugs found by tests, all real:** (1) section detection ran on normalized text, but normalization collapses the newlines that make a heading identifiable — detection now reads raw text and resolves offsets into cleaned text; (2) abstract extraction had the same root cause and is now derived from detected section boundaries; (3) de-hyphenation turned `state-\nof-the-art` into `stateof-the-art` because the greedy quantifier backtracked to a partial word. Frontend not updated yet at time of writing.
- **2026-08-24** — **Sprint 2 opened.** Reread PROGRESS.md first. Confirmed PyMuPDF 1.28.2 installs and imports on this Python 3.14 venv before planning around it. Restored the stack after an overnight restart — Docker volume persisted, migrations still applied, Sprint 1 data intact. Both blocking Sprint 2 decisions resolved (see above). Sprint 1 plan archived to `tasks/sprint-1.md`; `tasks/todo.md` is now the Sprint 2 plan. **Flagged a PRD schema gap** (Section 12 needs section storage that Section 7 does not define) — see above; Section 7 needs an update.
- **2026-08-23** — PRD reviewed and cleaned up into `PRD.md`. Sequencing gap in Section 12 flagged. Dataset sourcing links researched and compiled. Folder seeded for project coordination.
- **2026-08-23** — **Sprint 1 complete.** Frontend built (Next.js 16 / React 19 / Tailwind v4) and the whole §11.1 flow verified in a browser against the running backend. Two fixes found by verification rather than by review: (1) the psycopg pool handed out connections killed by a DB restart, failing every request for ~20s — now checks connections on checkout and recovers immediately; (2) ESLint's `set-state-in-effect` caught a render-then-fetch cascade on the papers list — restructured to fetch from the selection events instead, and the visible list is now derived so switching projects cannot flash the previous project's papers. Repo initialized with git; `.env`, `storage/`, `node_modules/`, `.venv/` confirmed excluded. **Committed** on `main` as `17b5a0e` (initial commit, 60 files) after a content-level secret scan, not just a filename check — the only credential in the tree is the throwaway local docker-compose Postgres password that pairs with `.env.example`. No remote is configured and nothing has been pushed.
- **2026-08-23** — **Backend + database complete and verified.** docker-compose Postgres 17 + pgvector healthy on host port 5433. Both migrations applied and confirmed idempotent on re-run; all 10 tables present, `vector` and `pgcrypto` extensions enabled. FastAPI serves `/health` (reports real DB + storage reachability, 503 when degraded), projects create/list/get, PDF upload, and paper status. **15/15 backend tests passing.** Frontend not started yet at time of writing.
- **2026-08-23** — **Sprint 1 implementation started.** Read PRD, PROGRESS, and dataset-references in full before writing code. Both Section 11.2 blocking questions resolved (clean start; local Postgres + pgvector first). Four execution-level decisions recorded above. Sprint 1 plan written to `tasks/todo.md`. Scaffolding started — see that file for live per-deliverable status. The two non-blocking PRD issues (Section 12 benchmark sequencing gap, Phase 6 training-vs-heuristic scope) remain OPEN and untouched; neither gates Sprint 1.

---
*Update this file whenever you complete work, hit a blocker, or make a decision.*
