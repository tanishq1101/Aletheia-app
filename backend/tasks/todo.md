# Sprint 6 — Evaluation

Scope: PRD Section 11, Sprint row 6 — *benchmark dataset (~10 papers × 15 questions), measure
retrieval recall, answer correctness, citation accuracy, faithfulness, unanswerable-question
handling, latency.*

**Taken out of order, deliberately.** The PRD's next row is Sprint 5 (Chat UI). Sprint 6 is being
pulled forward at the user's direction, and it is the sprint PRD §12's "known sequencing gap"
asks for: §12 gates Phase 2 on retrieval being "measurable against benchmark data" while
scheduling the benchmark *after* the sprints that criterion gates. Running Sprint 6 now closes
that gap rather than leaving it flagged. Sprint 5 (conversation persistence, streaming, history)
remains unbuilt and is **not** in scope here.

Relevant PRD constraints:
- §12 Retrieval — "retrieval is measurable against benchmark data".
- §12 Citations — "correct page • correct section where available • citation points to real
  evidence • **zero fabricated citation IDs**".
- §12 Answering — "answers are grounded • unsupported facts are not invented • system explicitly
  qualifies unanswerable questions".
- §12 Testing — "RAG evaluation benchmark run and recorded".
- §3.2 — chunk size (400 / 600 / 800 tokens) is to be **benchmarked**. The benchmark must
  therefore survive a chunk-size change without being rewritten.
- §5.2 — chunk → page → paper is the citation resolution path.

Sprint 4 left behind (PROGRESS.md handoff): `/search` returns raw pre-rerank candidates and
`/answer` returns reranked evidence + resolved citations, *deliberately kept as two endpoints so
Sprint 6 can measure retrieval quality and answer quality separately.* This sprint is the
consumer that seam was built for.

## Confirmed before planning (checked, not assumed)
- Dev corpus is **2 generated 3-page PDFs**, not real papers — `tests/fixtures.py` builds them
  with PyMuPDF. Nothing in the repo has ever ingested a real paper. A benchmark against this
  corpus would measure nothing.
- `OPENROUTER_API_KEY` is still empty, so the live LLM path remains unverified from Sprint 4.

## Open questions — RESOLVED before building
1. **Corpus** → **~10 real arXiv PDFs**, downloaded (user-approved), pinned by arXiv ID +
   SHA-256 in a checked-in manifest. PDFs themselves are gitignored — they are ~30MB of
   redistributable-but-bulky binaries, and a manifest + fetch script reproduces them exactly.
2. **Gold labels are page-level, not chunk-level.** *Why:* chunk UUIDs are regenerated on every
   reprocess and their boundaries move with `CHUNK_MAX_TOKENS` — a benchmark keyed to chunk IDs
   would be invalidated by the very 400/600/800 sweep PRD §3.2 requires. Page numbers are a
   stable property of the PDF. Retrieval recall is therefore measured as "did a retrieved chunk
   come from a gold page".
3. **Answer correctness without an LLM judge** → keyword/claim assertions per question
   (`must_contain`, `must_not_contain`). *Why:* an LLM-judge introduces a second unverified
   model into the measurement and costs money per run. Deterministic assertions are weaker per
   question and are compensated for by question count.
4. **LLM-dependent metrics gate on the key.** Retrieval recall, rerank lift, citation
   resolution, and latency need no LLM and always run. Correctness, faithfulness, and
   unanswerable handling need one and skip cleanly with a stated reason when the key is unset.

### ⚠️ The trap this sprint has to avoid: a benchmark that grades itself
The failure mode here is writing questions from memory of what these papers say, labelling gold
pages by recollection, and producing a green report that measures nothing but my own consistency.
**Every question is written from the text this pipeline actually extracted**, and every gold page
label is machine-verified against that extracted text before the benchmark is allowed to run.
A question whose gold page does not contain its own answer keywords **fails the test suite** —
the benchmark validates itself against the corpus rather than being trusted.

## Tasks

### Corpus (datasets/)
- [x] `datasets/corpus/manifest.json` — arXiv ID, title, URL, SHA-256, page count per paper
- [x] `scripts/fetch_corpus.py` — idempotent download, SHA-256 verify, polite rate limit
- [x] Gitignore the PDFs; check in the manifest so the corpus is reproducible byte-for-byte
- [x] Verify SHA-256 pinning actually fails on a corrupted file, rather than being decorative

### Ingestion of the corpus
- [x] `scripts/ingest_corpus.py` — ingest the corpus into a named benchmark project through the
      **existing service layer**, not a parallel copy of the pipeline
- [x] Idempotent: re-running must not duplicate papers (Sprint 3 already guarantees this for
      reprocess — confirm it holds here)
- [x] Record real page counts back into the manifest, so gold page labels can be range-checked

### Benchmark dataset (~10 × 15)
- [x] `datasets/benchmark/questions.json` — schema: id, paper, question, answerable,
      expected_pages, must_contain, must_not_contain, category, notes
- [x] ~15 questions per paper, written **from extracted text**, including per paper:
      unanswerable-from-this-paper cases and multi-page cases
- [x] Schema validation: every field present, types correct, IDs unique, papers resolve
- [x] **Gold-label verification against the extracted corpus** — the self-grading trap above

### Metrics (apps/api/app/services/evaluation.py)
- [x] Retrieval recall@k and MRR against gold pages
- [x] **Rerank lift** — recall/MRR before vs after reranking, so the stage's value is measured
      rather than asserted
- [x] Citation accuracy — every citation resolves to a real chunk → page → paper, and cited
      pages are checked against gold
- [x] Faithfulness — `fabricated_citations_removed` must be 0; uncited claim detection
- [x] Unanswerable handling — `sufficient_evidence: false` on questions the corpus cannot answer
- [x] Latency — per stage (embed / retrieve / rerank / LLM), not one opaque total
- [x] Pure functions, no DB or network, so each metric is unit-testable

### Runner + report
- [x] `scripts/run_benchmark.py` — runs the suite, writes a JSON result + a Markdown report
- [x] Retrieval-only mode when no LLM key is configured, stating why rather than reporting zeros
- [x] Results are timestamped and kept, so a chunk-size or model change is comparable to the
      previous run

### Tests
- [x] Unit tests per metric with hand-built cases, including the edge cases (empty retrieval,
      k larger than the result set, zero gold pages)
- [x] Benchmark file schema test — a malformed question fails the suite
- [x] Gold-label test — a question whose gold page lacks its own keywords fails the suite
- [x] Sprints 1–4 tests still pass, unchanged

### Verify
- [x] Run the full suite, paste real output
- [x] Run the benchmark end to end against the real corpus and record actual numbers
- [x] Read a sample of retrieved evidence by eye — confirm it answers the question, rather than
      trusting the recall number
- [x] Update PROGRESS.md with verified vs. unverified

## Explicitly NOT in this sprint
Chat UI · conversation persistence · streaming · conversation history (all Sprint 5) ·
the 400/600/800 chunk-size sweep itself (this sprint builds the instrument that makes it
measurable; running the sweep is a separate exercise) · LitQA2 reuse (PRD §3.2 — explicitly
excluded as the benchmark) · training-scale corpora (blocked on the Phase 6 scope decision)

---

## Review — what was built and what the numbers actually say

### Delivered
- **Corpus**: 10 arXiv papers, pinned by SHA-256 in `datasets/corpus/manifest.json`,
  reproduced by `scripts/fetch_corpus.py`. 198 pages, 389 chunks, all embedded.
  The pin was verified by corrupting a byte and confirming a non-zero exit, not assumed.
- **Benchmark**: `datasets/benchmark/questions.json` — 150 questions (10 papers x 15),
  121 answerable and 29 unanswerable, every one written from the text this pipeline
  extracted rather than from the rendered PDFs or from memory of the papers.
- **Metrics**: `apps/api/app/services/evaluation.py`, pure functions, 55 unit tests.
- **Runner**: `scripts/run_benchmark.py`, writing a timestamped JSON + Markdown report.
- **Tests**: 194 passing, 2 skipped (up from 133 at end of Sprint 4).

### Measured (retrieval, k=20 candidates -> 6 evidence, 600-token chunks)

| Metric | Before rerank | After rerank | Lift |
|---|---|---|---|
| recall@6 | 0.742 | 0.821 | +0.079 |
| MRR | 0.585 | 0.719 | +0.134 |

hit@6 = 0.876 · **evidence sufficiency = 0.884** · retrieve p50 14ms, rerank p50 1048ms.

**Reranking earns its place a second time, now at scale.** Sprint 4 showed it on one
constructed distractor query; across 121 real questions it lifts MRR by +0.134. Recall
moves much less than MRR, which is the interesting part: the right page is usually
*somewhere* in the 20 candidates already, and what reranking fixes is where it ranks.

### Three things worth carrying forward
1. **The gold-label verifier caught 3 of my own mislabelled questions** before any
   number was reported — I had used the papers' printed page numbers instead of the
   PDF's physical page index. That check is now a test, so the same mistake fails CI.
2. **Six "retrieval misses" were actually incomplete gold labels; only four were.**
   Each candidate was checked against the extracted text and three were rejected as
   keyword false positives (rag-09's "11.8%" is a Jeopardy human-eval row, not the NQ
   figure; gpt3's p12/p22 hits are model *names*). Adjusting labels after seeing
   results deserves scrutiny, so the rule applied was: a gold page is any page that
   *independently supports the answer* — a property of the corpus, not of the output.
3. **Evidence sufficiency (0.884) is the ceiling on answer correctness** and needs no
   LLM. The gap from 1.0 is retrieval's to close; the gap between it and correctness,
   once the key is set, is the model's.

### Known limitation, stated rather than papered over
Keyword correctness can be satisfied by the *wrong paper's* numbers — vgg-04 expects
"256" and "0.9", and ResNet used the same values. The mitigation is the metric *pair*:
an answer taking those from ResNet would cite a ResNet page and score zero citation
precision. Neither metric is sufficient alone, which is why both are reported.

### Not done — blocked on the API key, not on code
- [ ] Answer correctness, citation accuracy, faithfulness, unanswerable handling,
      LLM latency. All implemented and wired; they skip with a stated reason.
      Run `scripts/set-openrouter-key.sh`, then `python scripts/run_benchmark.py`.
- [ ] The 400/600/800 chunk-size sweep PRD 3.2 calls for. This sprint built the
      instrument that makes it measurable; running it is a separate exercise.
