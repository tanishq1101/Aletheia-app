# AI Research Intelligence Platform

Multimodal research-paper understanding, built phase by phase from a text-RAG foundation.
See [PRD.md](PRD.md) for scope and [PROGRESS.md](PROGRESS.md) for live project state.

> **Current state: Phase 1, Sprint 4 (RAG).**
> Upload, extraction, chunking, local embeddings, semantic retrieval, local
> reranking, and grounded answers with backend-resolved citations.
> Answers are stateless — conversation history and streaming are Sprint 5.
> Retrieval and answer quality have **not** been measured against a benchmark
> (Sprint 6), and the live OpenRouter path is unverified until a key is set.

## Prerequisites

Docker, Python 3.12+, Node 20+.

## Running it

Sprint 1 runs against local Postgres + pgvector. Supabase is not wired up yet — that decision
and its rationale are recorded in [PROGRESS.md](PROGRESS.md).

**1. Configure**

```bash
cp .env.example .env
```

The defaults work with the bundled docker-compose. Everything except **answering** runs
with no secrets: embeddings and reranking are local. Grounded answers need an
[OpenRouter](https://openrouter.ai/keys) key — without one, the answer endpoint returns a
503 saying so rather than degrading to an ungrounded answer.

Set the key with the helper rather than editing `.env` by hand:

```bash
./scripts/set-openrouter-key.sh
```

It prompts with echo off, writes the key straight into `.env`, sets the file to `chmod 600`,
and verifies the key against OpenRouter before it finishes. The key is never echoed, never
passed as an argument (`argv` is visible to `ps`), and never enters shell history — only a
masked fingerprint is shown. `--check` re-verifies the stored key and reports usage and
limit; `--clear` removes it.

**2. Start the database**

```bash
docker compose up -d
```

**3. Install backend dependencies and migrate**

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r apps/api/requirements.txt
```

```bash
./.venv/bin/python scripts/migrate.py
```

`scripts/migrate.py --status` shows what has and hasn't been applied. Re-running is safe.

**4. Start the API**

```bash
cd apps/api && ../../.venv/bin/python -m uvicorn main:app --reload --port 8000
```

Interactive API docs at http://localhost:8000/docs.

**5. Start the frontend**

```bash
npm install --prefix apps/web && npm run dev --prefix apps/web
```

Open http://localhost:3000, create a project, and upload a PDF.

## Tests

```bash
cd apps/api && ../../.venv/bin/python -m pytest
```

The suite creates and migrates its own `research_intelligence_test` database on the same
Postgres instance, so running it does not touch your development data. The container must
be up. Real embeddings run in the tests — there is no stub.

## Evaluation benchmark

The corpus is ten open-access arXiv papers, pinned by SHA-256 and **not** checked in. Fetch
and ingest it once:

```bash
.venv/bin/python scripts/fetch_corpus.py
.venv/bin/python scripts/ingest_corpus.py
```

Then run the benchmark — 150 hand-built questions (10 papers x 15, 121 answerable and 29
deliberately unanswerable):

```bash
.venv/bin/python scripts/run_benchmark.py
```

Results land in `datasets/benchmark/results/` as a timestamped JSON plus a Markdown report,
so a chunk-size or model change is comparable against the previous run.

**Retrieval metrics need no LLM and always run.** Answer correctness, citation accuracy and
faithfulness do, and skip with a stated reason when `OPENROUTER_API_KEY` is unset rather than
reporting zeros — an unrun metric and a failed one are different facts. Set the key with
`scripts/set-openrouter-key.sh` (it keeps the value out of shell history) and re-run.

A few things worth knowing before trusting a number from it:

- **Gold labels are page-level, not chunk-level.** Chunk ids are regenerated on every
  reprocess and their boundaries move with `CHUNK_MAX_TOKENS`, so a chunk-keyed benchmark
  would be invalidated by the very 400/600/800 sweep the PRD asks for.
- **The benchmark validates itself against the corpus.** Every expected answer term is
  checked to actually appear in the text the pipeline extracted from that question's own gold
  pages. A question written from recollection of the paper fails the test suite. This already
  caught three mislabelled questions.
- **Evidence sufficiency is the ceiling on correctness.** It reports how often the assembled
  evidence blocks actually contain the answer, and needs no LLM. The gap from 1.0 is
  retrieval's; the gap between it and correctness is the model's.
- `scripts/dump_corpus_text.py <paper>` prints a paper exactly as the pipeline extracted it —
  use it when writing or auditing a question, never the rendered PDF.

## Layout

```
apps/api/          FastAPI backend
  app/api/         Route handlers (health, projects, papers, search, answer)
  app/core/        Config and logging
  app/db/          Connection pool
  app/schemas/     Pydantic models
  app/services/    Ingestion, chunking, embedding, retrieval, reranking, context, LLM
  migrations/      Numbered SQL, applied by scripts/migrate.py
  tests/
apps/web/          Next.js frontend
docs/              Architecture notes and dataset references
scripts/           Operational scripts
storage/           Uploaded PDFs (git-ignored, created at runtime)
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Reports real database and storage reachability; 503 when degraded |
| `POST /projects` · `GET /projects` · `GET /projects/{id}` | Create and select projects |
| `POST /projects/{id}/papers` | Validate a PDF, store it, and queue extraction. 409 if that PDF is already in the project |
| `GET /projects/{id}/papers` · `GET /papers/{id}` | Papers with their latest job status |
| `GET /papers/{id}/pages` | Extracted page text, in page order |
| `GET /papers/{id}/sections` | Detected sections, in document order |
| `POST /papers/{id}/reprocess` | Retry extraction for a failed or stranded paper |
| `POST /projects/{id}/search` | Semantic search over the project's chunks — the **raw candidate set, before reranking**. Kept separate so retrieval quality stays measurable independently of answer quality |
| `POST /projects/{id}/answer` | Grounded answer: retrieve → rerank → build evidence → LLM → resolved citations |

### How ingestion runs

Upload returns immediately and processing runs in-process as a FastAPI background task,
walking the job through `downloading → parsing → chunking → embedding → persisting →
complete`. Because it is in-process, it does not survive a server restart mid-run — on
startup, any job left `running` or `pending` is marked failed with an explanation and can
be retried from the UI.

### Embeddings

Embeddings run locally through `fastembed` (ONNX) — no API key, no spend, no network at
inference time. The model (`jinaai/jina-embeddings-v2-small-en`, 512-dim) downloads once
(~120MB) on first use and is cached; the first call after a restart takes ~25s to load.

The model was chosen for its 8192-token context: PRD §3.2 commits to benchmarking 400/600/800
token chunks, and the more obvious small models truncate at 512 (or 256), which would silently
invalidate most of that benchmark. Reasoning is recorded in [PROGRESS.md](PROGRESS.md).

Chunk size and overlap are configurable (`CHUNK_MAX_TOKENS`, `CHUNK_OVERLAP_TOKENS`). The
defaults of 600/80 are a starting point, **not** a benchmarked result. Changing them requires
reprocessing existing papers.

> **Vectors are model-specific.** Every chunk records the model that produced it. Changing
> models invalidates stored vectors — comparing across models degrades ranking silently
> rather than raising an error, so re-embed rather than mixing.

### Answering

The pipeline is PRD §5.1 steps 7–9:

```
question -> embed -> semantic top-20 -> rerank to top-6 -> evidence blocks -> LLM -> citations
```

**Reranking is local**, like embeddings — a `fastembed` cross-encoder
(`jinaai/jina-reranker-v1-turbo-en`), no key and no spend. It is not decorative: on a
distractor query, cosine similarity ranked the passage that actually contained the answer
*third of three* within a 0.007 spread, and the cross-encoder put it first. The numbers are
in [PROGRESS.md](PROGRESS.md) and asserted in `tests/test_reranking.py`.

> **fastembed caps every cross-encoder at 512 tokens at load**, whatever context the model
> really supports — so a chunk longer than that is scored on its opening only, silently and
> with a plausible-looking score. The cap is lifted explicitly at load and a test guards it.
> If you change `RERANK_MODEL`, confirm the new model actually tolerates `RERANK_MAX_TOKENS`.

**The LLM never invents citations** (PRD §5.3). The backend mints evidence IDs `E1..En` in
rank order and hands the model `<EVIDENCE id="E1" page="7" section="Results">` blocks; the
chunk's UUID never enters the prompt. Every ID the model cites is then checked against the
set actually supplied — anything else is stripped server-side before serialization and
counted in `fabricated_citations_removed`, which should always be `0`. That field is
returned rather than only logged, so PRD §12's "zero fabricated citation IDs" is verifiable
from outside the system.

`sufficient_evidence: false` means the model reported the evidence could not answer the
question. **That is a successful answer, not an error** (PRD §5.4) — the UI renders it as
one.

The LLM sits behind `LLMProvider`; only `app/services/llm.py` knows OpenRouter exists.
`OPENROUTER_MODEL` defaults to `anthropic/claude-haiku-4.5` (~$0.009 per answer); cheaper
alternatives are listed in `.env.example`. Swapping providers means writing another class
with a `complete` method.

## Notes for the next sprint

Sprint 6 (evaluation) landed ahead of Sprint 5 (chat UI), so there is now a measured
baseline to regress against — re-run the benchmark after any retrieval or prompt change.

- **Answers are not persisted.** `conversations`, `messages`, and `citations` are still
  empty shells from migration `0001`, and `citations.message_id` is NOT NULL — a message row
  has to exist before a citation row does. This is deliberate: conversations are a Sprint 5
  deliverable, and writing them in Sprint 4 would have been phase bleeding.
- **Streaming changes the provider interface.** `LLMProvider.complete` returns a whole
  string. Streaming means either an SSE variant of the endpoint or a streaming method on the
  interface — decide before building.
- **Do not move citation validation into the frontend.** It runs before an answer is
  serialized, so an invented ID cannot reach a client at all. Filtering at render time would
  be a strictly weaker guarantee.
- The answer endpoint is synchronous and takes as long as the model does. The first request
  after a restart also pays the lazy load of *both* local models.
- **`scripts/run_benchmark.py` calls `answer_question` directly.** If streaming changes that
  interface, the runner needs the same treatment or the benchmark stops working.
- `app/services/providers.py` holds the provider interfaces. All four are now implemented:
  `DocumentParser` (`parsing.py`), `EmbeddingProvider` (`embedding.py`),
  `RerankerProvider` (`reranking.py`), and `LLMProvider` (`llm.py`).
