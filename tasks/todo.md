# Aletheia — Multimodal Agentic Research Sprint

## Current objective

Deliver one verified vertical slice beyond the text-RAG foundation:

1. extract readable text plus first-class figures, tables, and equation candidates from PDFs;
2. expose those assets through the API and paper reader;
3. add a bounded, inspectable research-agent workflow over the local paper corpus;
4. add a reproducible local neural relevance-model training pipeline and evaluation report;
5. document exactly which features are local and which require an external AI key.

This sprint deliberately crosses the old PRD phase boundaries at the user's direction. It does
not claim that all of Phases 2–6 are complete.

## Architecture and scope decisions

- **PDF extraction:** keep PyMuPDF as the only PDF dependency. Raster figures are extracted from
  embedded images, captions are linked by page geometry, tables use PyMuPDF's table detector,
  and equation candidates use conservative text/layout heuristics. Math OCR and chart semantics
  remain later work and must not be presented as solved.
- **Storage:** add `paper_assets`, linked to paper and page. Binary figures use the existing
  storage backend; table/equation text is stored in Postgres. Reprocessing replaces assets in
  the same transaction as pages/chunks so stale data cannot survive.
- **Reader:** add structured extraction cards, previews, captions, page links, and readable page
  typography. The original cleaned text remains the canonical searchable text.
- **Agent:** implement a bounded planner → retrieve/rerank → answer → verify workflow. Every step
  is returned in an audit trace, citations are still validated server-side, and the agent cannot
  browse or mutate external systems. `max_steps` is capped to control cost and loops.
- **Keys:** embeddings, reranking, PDF parsing, asset extraction, and training are local and need
  no key. Planning/answer generation uses only `OPENROUTER_API_KEY` through `LLMProvider`.
- **Training:** train a small multi-layer neural relevance classifier from benchmark
  question/candidate pairs using NumPy and deterministic backprop. Split by question ID, publish
  validation metrics, and do not replace the production cross-encoder unless the trained model
  demonstrably improves the held-out ranking metric. This is genuine local supervised training,
  but not an end-to-end transformer fine-tune; that requires a GPU-scale training decision.

## Ordered checklist

### 1. Plan and schema

- [x] Reconcile current PRD, sprint status, and requested expanded scope.
- [x] Add migration for structured PDF assets and indexes.
- [x] Add wire schemas for assets and agent traces.

### 2. Multimodal PDF extraction

- [x] Implement figure extraction with size/noise filters and caption linking.
- [x] Implement table extraction to structured rows plus Markdown text.
- [x] Implement conservative equation-candidate extraction.
- [x] Store binaries safely through the existing storage abstraction.
- [x] Replace assets idempotently during reprocessing.
- [x] Add asset list/content API endpoints.
- [x] Add generated-PDF fixtures and extraction tests.

### 3. Reader and data clarity

- [x] Load assets with pages and sections in the paper reader.
- [x] Replace the placeholder Extraction tab with real figure/table/equation cards.
- [x] Add clear counts, captions, page locations, and figure previews.
- [x] Improve text measure, line height, page separation, and navigation readability.

### 4. Bounded research agent

- [x] Add planner output parsing with a deterministic fallback question plan.
- [x] Execute a capped set of grounded subquestions through the existing RAG pipeline.
- [x] Return an explicit trace of planned, running, succeeded, and failed steps.
- [x] Preserve evidence-ID validation on every agent answer.
- [x] Add endpoint, frontend page, navigation, and mocked-provider tests.

### 5. Local model training

- [x] Implement deterministic feature extraction for benchmark candidate pairs.
- [x] Implement a NumPy multi-layer neural binary classifier and serialization.
- [x] Add a training CLI that uses the real benchmark project in Postgres.
- [x] Split by question, report held-out loss/accuracy/MRR, and compare with cosine baseline.
- [x] Save model metadata and a Markdown training report.
- [x] Add unit tests for determinism, loss reduction, and save/load parity.

### 6. Configuration and documentation

- [x] Add provider/key capability matrix to `.env.example`, README, and Settings.
- [x] Document local models, training dataset, artifact format, and GPU-scale next step.
- [x] Update project progress without overstating unverified hosted-model behavior.

### 7. Verification

- [x] Apply migrations to the Docker Postgres instance.
- [x] Run the complete backend suite.
- [x] Run frontend ESLint, TypeScript, and production build.
- [x] Reprocess one real corpus paper and inspect extracted assets.
- [x] Run the neural training CLI and record held-out metrics.
- [x] Start the local stack and verify health, reader extraction, and agent error/key behavior.

## Acceptance criteria

- Reprocessing a PDF produces queryable structured assets without duplicating old rows.
- Figure content cannot escape the configured storage root and is served only by resolved asset ID.
- The reader clearly distinguishes extracted, unavailable, and heuristic data.
- Agent runs are bounded, auditable, grounded, and reject fabricated evidence IDs.
- Training is reproducible from checked-in code/dataset metadata and reports held-out metrics.
- No secret is committed; the only hosted AI secret requested is `OPENROUTER_API_KEY`.
- All existing behavior and tests remain green.

## Review

- Docker Postgres is healthy on host port `5433`; migration `0005_paper_assets.sql` is applied.
- Complete backend result after configuring OpenRouter: **214 passed**. The live provider tests
  now run successfully rather than being skipped.
- Frontend result: ESLint, TypeScript, and the Next.js webpack production build pass. The build
  includes the new `/agent` route and dynamic paper reader.
- Real-PDF result (`Attention Is All You Need`, 15 pages): **3 figures, 2 readable tables, and
  12 explicitly labelled heuristic equation candidates**. A second pass replaced rather than
  duplicated assets. A quality gate rejected 33–56-column attention-layout grids that the PDF
  library initially misclassified as tables.
- Browser/API result: extracted figures render from the protected asset-content endpoint, captions
  and page numbers are visible, and text uses a narrower measure and larger line height. A live
  Claude Haiku 4.5 agent run produced two planned, grounded steps without fallback; every returned
  citation resolved to server-supplied evidence.
- Neural training result: deterministic `5 → 16 → 8 → 1` NumPy MLP, 1,920 training examples and
  500 held-out examples. MRR improved **0.544 → 0.717 (+0.173)** and Recall@6 improved
  **0.646 → 0.799 (+0.153)**. The artifact is eligible for a later blended-reranker experiment;
  it was not silently promoted over the current production cross-encoder.
- Only hosted AI secret required: `OPENROUTER_API_KEY`. PDF parsing, asset extraction, embeddings,
  reranking, and neural training all run locally without an API key.
- Remaining limitations are explicit: equation extraction is text/layout heuristic rather than
  math OCR; figure vision is one-at-a-time and cached without regeneration/history; the agent is deliberately
  bounded to four corpus-only steps; a transformer fine-tune still needs a larger labelled dataset
  and an approved GPU/compute budget.

## Focused Multimodal Slice — On-demand Figure Interpretation

### Objective

Interpret exactly one extracted figure per explicit user action. Do not batch, precompute, or
auto-run vision requests. Keep page context and output bounded so free-tier usage remains
predictable. Tables and equations stay out of scope for this slice.

### Checklist

- [x] Extend the provider boundary with one image-plus-text completion method.
- [x] Add a single-figure interpretation service with image/type/size validation.
- [x] Add `POST /assets/{asset_id}/interpret` and a small response schema.
- [x] Add an on-demand Interpret button and result/error state to figure cards only.
- [x] Add provider-payload, endpoint, validation, and no-auto-run tests.
- [x] Run backend tests and frontend lint/typecheck/build.
- [x] Make at most one live interpretation call against the existing Transformer figure.

### Focused-slice acceptance criteria

- No vision request occurs while loading the reader or extraction tab.
- One button/API invocation interprets one resolved figure and cannot target tables/equations.
- Image bytes stay inside the backend; the frontend sends only an asset ID.
- The provider request is capped and the interpretation clearly says it is AI-generated.
- Existing text extraction, grounded agent, and training behavior remain green.

### Focused-slice review

- Implemented a figure-only `POST /assets/{id}/interpret` endpoint and reader button. Loading the
  reader performs zero vision calls; a successful result disables repeat calls for that card in
  the current UI session.
- The browser sends only the asset UUID. The backend resolves private image bytes, accepts PNG,
  JPEG, WebP, or GIF up to 5 MB, includes at most 2,500 page-context characters, and caps vision
  output at 500 tokens.
- Offline verification (key deliberately disabled): **217 passed, 2 live tests skipped**. Frontend
  ESLint, TypeScript, and the production webpack build pass.
- Exactly one live request was made for Transformer Figure 1: HTTP 200, 2,072 prompt tokens and
  383 completion tokens. It identified the encoder/decoder structure, attention blocks, residual
  paths, feed-forward layers, and output head, while reporting uncertainty about unlabeled details.
- No batch interpretation, table interpretation, equation OCR, or result persistence was added in
  this initial slice; the following cache slice adds persistence without expanding provider usage.

## Focused Multimodal Slice — Interpretation Cache

### Objective

Persist one successful interpretation per figure/model/prompt version and return it on later
requests without another provider call. Do not add regeneration, history, batch processing,
table interpretation, or equation OCR in this slice.

### Checklist

- [x] Add an asset-interpretation migration with cascade cleanup and a unique cache key.
- [x] Return cached interpretations before reading image bytes or resolving the LLM dependency.
- [x] Persist only successful provider results and handle concurrent first requests safely.
- [x] Add `cached` and `created_at` to the API/frontend response contract.
- [x] Update the figure card to distinguish newly generated and saved interpretations.
- [x] Test first-call generation, second-call cache hits, failures, and cascade cleanup.
- [x] Apply the migration and run backend/frontend verification with live calls disabled.

### Cache acceptance criteria

- The second request for the same asset/model/prompt version makes zero provider calls.
- Provider failures never create a cache row.
- Reprocessing/deleting an asset removes its cached interpretation through the foreign key.
- The UI tells the user whether the displayed result was generated now or loaded from cache.
- Verification consumes no OpenRouter quota.

### Cache review

- Added `0006_asset_interpretations.sql`. The cache key is
  `(asset_id, model, prompt_version)`, and `ON DELETE CASCADE` removes stale results when an
  asset is replaced during reprocessing.
- A cache hit is resolved before storage reads and before `get_llm_provider()`. Concurrent first
  requests serialize on a transaction-scoped advisory lock, recheck the cache, and make one
  provider call. Only a successful result is inserted.
- The API now returns `cached` and `created_at`. Figure cards label results as either generated
  and saved now or loaded from a saved result with no new AI call.
- Focused cache result: **7 passed**, covering no-auto-run, first generation/second cache hit,
  concurrent first requests, provider rollback, reprocess cascade, non-figure rejection, and the
  existing image-size guard.
- Complete backend result with `OPENROUTER_API_KEY` deliberately blank: **220 passed, 2 live
  provider tests skipped**. Frontend ESLint, TypeScript, and the Next.js production build pass.
- Migration `0006` is applied to Docker Postgres; the container reports healthy and the local
  backend health endpoint reports database/storage `ok`. Verification made zero OpenRouter calls.
