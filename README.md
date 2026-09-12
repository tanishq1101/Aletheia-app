# Aletheia

Aletheia (working name "The Archive") is a research intelligence workspace for
reading, organizing, and cross-checking academic papers: a library of uploaded
papers, a distraction-free reader, semantic search over their contents, and
grounded answers that cite the passage they came from.

The repository holds two halves:

```
/            Next.js 16 frontend — the UI, wired to the API below
backend/     FastAPI service — ingestion, chunking, embeddings, retrieval,
             reranking, grounded answering (see backend/README.md)
```

## What is actually wired

| Feature | State |
|---|---|
| Projects | Live — `/projects`, switcher in the topbar, selection persisted locally |
| Upload + ingestion | Live — PDFs, text, Office documents, slide decks, data files, and attachments; extractable text is indexed |
| Library | Live — real papers and statuses, filter chips, polling while anything ingests |
| Reader | Live — extracted page text and detected section outline |
| Semantic search | Live — `POST /projects/{id}/search`, raw candidates before reranking |
| Ask | Live — `POST /projects/{id}/answer`: retrieve → rerank → evidence → LLM → resolved citations |
| Figures / tables / equations | Live — raster figures + captions, structured tables, heuristic equation candidates, plus cached one-at-a-time AI figure interpretation; vector-chart extraction and math OCR remain future work |
| Research Agent | Live API/UI — bounded planner → grounded subquestions → verified evidence trace; OpenAI primary with Gemini backup |
| Cross-Paper, Claim Verification, Reproducibility | Live — backed by `/projects/{id}/cross-paper`, `/claims` and `/reproducibility`. The fixture module and its preview banner are gone |
| Sign-in | Live with Clerk — Google, email and username. Without keys the app runs open, as before, and the sign-in page says so; the API then refuses to start unless `ALLOW_UNAUTHENTICATED=true` states that openness is intended |
| Rate limiting | Live — sliding windows per signed-in user (IP when anonymous): 120 req/min, 12/min on LLM routes, 60 uploads/hour. Counters live in Redis when `REDIS_URL` is set, so the numbers are cluster-wide; without it they are per process. Losing Redis degrades the limiter to the in-process window and is reported by `/health`, rather than taking the API down |
| Landing page | Live — a public `/` explaining what the system does and what it refuses to do. It is the only route outside the middleware's sign-in allow-list |

Answering, research-agent generation, and explicitly requested figure interpretation use a hosted
model. Embedding and reranking run locally through fastembed — no key, no spend. Without a key
those three generation paths return 503 with an explanation; extraction, reading, search, and
local training still work.

The hosted model is any OpenAI-compatible endpoint, chosen with `LLM_PROVIDER`: `openai`,
`openrouter`, `gemini`, `groq`, `ollama` or `custom`. **OpenAI is the default primary**;
when `GEMINI_API_KEY` is also configured, Gemini automatically retries a failed OpenAI request
with the same grounded evidence. This preserves availability without relaxing citation checks:

```
LLM_PROVIDER=openai
OPENAI_API_KEY=<your OpenAI API key>
LLM_MODEL=gpt-5.6-luna
GEMINI_API_KEY=<optional backup key>
GEMINI_MODEL=gemini-2.5-flash
```

Groq is also free and faster, but text-only, so figure interpretation would fail rather than
guess. See `backend/.env.example` for every option.

## AI keys and local models

| Capability | Provider | Key required |
|---|---|---|
| PDF text, figures, tables, equation candidates | PyMuPDF, local | No |
| Embeddings | fastembed / Jina ONNX, local | No |
| Cross-encoder reranking | fastembed / Jina ONNX, local | No |
| Neural relevance-model training | NumPy, local | No |
| Grounded answers | OpenAI; Gemini fallback when configured | `OPENAI_API_KEY` |
| Research-agent planning and step answers | OpenAI; Gemini fallback when configured | `OPENAI_API_KEY` |
| On-demand single-figure interpretation | OpenAI; Gemini fallback when configured, cached by figure/model/prompt | `OPENAI_API_KEY` only on cache miss |
| Supabase | Not wired | No key is currently used |

The active hosted-AI secret is `OPENAI_API_KEY`; `GEMINI_API_KEY` is an optional fallback. Set
them only in `backend/.env`; do not put them in frontend variables or commit them.

## Stack

- Next.js 16 (App Router) with TypeScript
- Tailwind CSS v4, theme tokens as CSS variables in `app/globals.css`, mapped in
  `tailwind.config.ts`
- Fraunces, Source Serif 4, Inter, JetBrains Mono via `next/font/google`
- Backend: FastAPI, Postgres 17 + pgvector, PyMuPDF, fastembed (ONNX)

## Running it

Both halves have to be up. The backend needs Docker and Python 3.12 or newer
(its pinned dependencies resolve on 3.14).

**1. Backend** — full instructions in [backend/README.md](backend/README.md):

```bash
cd backend
cp .env.example .env
docker compose up -d
python -m venv .venv && ./.venv/bin/pip install -r apps/api/requirements.txt
./.venv/bin/python scripts/migrate.py
cd apps/api && ../../.venv/bin/python -m uvicorn main:app --reload --port 8000
```

**2. Frontend** — from the repository root:

```bash
cp .env.local.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. It redirects to `/library`, resolves a project
(creating "My Library" on first run), and from there you can upload a PDF.

`NEXT_PUBLIC_API_URL` in `.env.local` must match `CORS_ORIGINS` in
`backend/.env` — default `http://localhost:8000` and `http://localhost:3000`
respectively.

If the backend is down, the topbar shows **API offline** and each page renders
the reason rather than an empty state that reads like "you have no papers".

## Layout

```
app/
  (app)/          authenticated shell: sidebar + topbar, one folder per page
    library/      real papers for the selected project
    search/       semantic search over the project's chunks
    ask/          grounded answers with resolved citations
    agent/        bounded research planner with an inspectable grounded trace
    upload/       real upload + live ingestion stages
    paper/[id]/   readable text plus structured PDF assets
    cross-paper/, claim-verification/, reproducibility/   preview only
    settings/     live /health, workspace facts, provider notes
  (auth)/
    sign-in/      not wired
components/       shared UI pieces
lib/
  api.ts          the only place that talks to the backend
  workspace.tsx   project selection + the single paper-polling loop
  display.ts      shared formatting (titles, dates, stages, scores)
  preview-data.ts fixtures, used only by the three preview pages
types/api.ts      wire types mirroring backend/apps/api/app/schemas/models.py
```

The two route groups exist because they need different chrome: `(app)` renders
the sidebar and topbar around every page, `(auth)` just centers its content.

## Notes

- `lib/api.ts` distinguishes "the API is unreachable" from "the API refused
  this" — an offline backend and a rejected upload are different problems and
  say so differently.
- Ingestion runs in-process on the API, so job progress is polled, not pushed.
  The workspace context owns one timer for that and stops it when nothing is in
  flight.
- Citation IDs in an answer are minted and validated server-side; anything the
  model invented is stripped before the response is serialized. The UI shows
  `fabricated_citations_removed` if it is ever non-zero rather than hiding it.

## Multi-source training and research reports

The project now includes **two additional trained neural classifiers** and a **neural relevance reranker**, three public training datasets plus the in-house benchmark, and three standalone Colab notebooks. The research agent searches Europe PMC and Crossref and combines library passages with clearly labeled public abstracts into a cited report. Answers support bold/italic Markdown, comparison tables, source coverage graphs, conservative citation-backed numeric charts, and experimental model diagnostics.

See [training results, notebooks, setup and limitations](backend/docs/research-models.md). Relevance reached **89.87% held-out accuracy** versus a **84.96% lexical baseline**. Scientific stance remains experimental (**54% accuracy**, below the majority baseline); neither model is a replacement for the hosted language model or a verified claim checker.

Open **Training Lab** in the sidebar to inspect the measured results and download all three notebooks — the two classifiers plus the neural relevance reranker (5 → 16 → 8 → 1, MRR 0.717 vs a 0.544 cosine baseline on 500 held-out candidates, offline experiment only). [Validation record](backend/docs/validation-summary.json).
