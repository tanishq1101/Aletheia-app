# Sprint 4 — RAG

Scope: PRD Section 11, Sprint row 4 — *query embedding, semantic retrieval, reranking, context
builder, LLMProvider abstraction, grounded answers, evidence IDs, citation resolution.*
Nothing from Sprint 5+ (no chat UI, no streaming, no conversation history).

Relevant PRD constraints:
- §5.1 step 7 — semantic retrieval (~top 20) → **rerank** → top 5–8 evidence chunks.
- §5.3 — the LLM **never invents citation labels.** The backend issues explicit evidence IDs
  (`<EVIDENCE id="E1" page="7" section="Results">`) and the model may only cite an ID it was
  handed. The backend resolves E1 back to a real citation object.
- §5.4 — answer from supplied evidence only; every claim traceable to an evidence ID; say
  explicitly when evidence is insufficient rather than guessing; no fabricated citations, ever.
- §5.2 — chunk → page → paper stays the resolution path for every citation.

Sprint 3 left behind (PROGRESS.md handoff): `POST /projects/{id}/search` already returns chunk
id, content, section, page number, paper id/title and similarity — Sprint 4 **reranks that
candidate set, it does not re-query.** A chunk can legitimately have `section = NULL`, so
citations must degrade to "page N" rather than rendering "null".

## Confirmed available (checked before planning)
- `fastembed` 0.8.0 ships cross-encoder rerankers, so **reranking is local** — same no-key,
  no-spend, real-model-in-CI property as Sprint 3's embeddings.
- OpenRouter's public `/api/v1/models` endpoint is reachable and the chosen model is listed.

## Open questions — RESOLVED before building
1. **LLM provider** → **OpenRouter** (OpenAI-compatible), key supplied by the user.
   Default model `anthropic/claude-haiku-4.5` (200K context, $1/$5 per M tokens ≈ **$0.009 per
   answer** at ~7K in / ~400 out). Chosen for instruction-following, which is what grounding and
   refusal actually depend on. Configurable via `OPENROUTER_MODEL`; cheaper alternatives checked
   and recorded in PROGRESS.md.
2. **Persistence** → **stateless answers.** `POST /projects/{id}/answer` returns the answer with
   fully resolved citations in the response body. Nothing is written to `conversations`,
   `messages`, or `citations`. *Why:* PRD §7 makes `citations.message_id` a NOT NULL foreign key,
   so persisting a citation requires a message row — and conversations are a Sprint 5 deliverable.
   Writing them now would be phase bleeding. Citation *resolution* is still fully delivered.
   *Consequence:* no migration this sprint.

### ⚠️ Reranker model choice — the Sprint 3 truncation trap, again
`Xenova/ms-marco-MiniLM-L-6-v2` is the obvious default and **truncates at 512 tokens.** PRD §3.2
benchmarks 600- and 800-token chunks, so it would silently score two of the three arms on
partial text — the same failure Sprint 3 caught in the embedding model.
**Using `jinaai/jina-reranker-v1-turbo-en` (8K context, 150MB)**, and proving the long-context
claim with a test rather than trusting the model card.

## Still open from earlier, not mine to close
- PRD §7 does not list `paper_sections` (flagged in Sprint 2). Still unresolved.
- PRD §12's "retrieval measurable against benchmark data" still gates Phase 2 on a Sprint 6
  deliverable. Sprint 4 produces answers that *can* be measured; it does not resolve the gap.

## Tasks

### Retrieval (shared seam)
- [x] Extract the search SQL out of the endpoint into a retrieval service so `/search` and
      `/answer` share one candidate-generation path instead of two copies drifting apart

### Reranking
- [x] `RerankerProvider` implementation behind the existing interface (local cross-encoder)
- [x] Prove it does **not** truncate at 512 tokens — a test, not the model card
- [x] Configurable candidate count and final evidence count (PRD's 5–8), not hardcoded
- [x] Rerank scores kept distinct from cosine similarity in the response — they are unbounded
      logits and are not the same quantity

### Context builder + evidence IDs
- [x] Assign `E1..En` **backend-side** in rank order; the model never sees a chunk id
- [x] Render evidence blocks carrying paper, page and section (PRD §5.3)
- [x] `section = NULL` degrades to "page N", never the string "null"
- [x] Token-budget the context and report what was dropped — never silently truncate

### LLMProvider
- [x] `OpenRouterProvider` behind the existing interface; model/base URL/timeout all config
- [x] Missing or invalid key fails with a readable error, not a 500
- [x] Provider injected as a FastAPI dependency so tests can override it without monkeypatching

### Grounded answering
- [x] Prompt encoding the PRD §5.4 grounding rules
- [x] **Validate every cited ID against the set actually supplied.** A fabricated ID is stripped
      and *reported in the response*, never silently passed through
- [x] Insufficient evidence is an explicit, first-class outcome — not an empty answer
- [x] Zero retrieved chunks short-circuits before spending an LLM call
- [x] Resolve each valid ID to a citation: paper, page, section, snippet (chunk → page → paper)

### API + frontend
- [x] `POST /projects/{id}/answer`
- [x] Answer panel: answer text, inline evidence markers, source cards with section + page

### Verification
- [x] Reranking genuinely reorders (relevant above irrelevant), not just "returns k rows"
- [x] Fabricated-citation test: a scripted LLM cites an ID it was never given
- [x] Unanswerable-question test
- [~] Live OpenRouter test — written and skipping cleanly; **not yet run against the
      real API** (no key configured at time of writing).
      `scripts/set-openrouter-key.sh` sets the key without it passing through chat or history.
- [ ] Browser check end to end against the real dev papers — blocked on the API key
