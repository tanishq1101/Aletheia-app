# Aletheia — Neon + Prisma + ChromaDB integration

## Decisions (confirmed with user)
- Prisma = schema + migration source of truth only. FastAPI stays on psycopg.
- ChromaDB = self-hosted Docker server alongside the app.
- Chroma primary, Neon pgvector mirrored as automatic fallback.
- Existing data migrated, not re-ingested.

## Plan
- [x] 1. `chroma` service in docker-compose (1.5.9, port 8001), healthy
- [x] 2. `chromadb-client==1.5.9` installed and pinned (thin HTTP client)
- [x] 3. CHROMA_* settings in config.py + .env.example
- [x] 4. `services/vector_store.py` — Chroma behind one interface
- [x] 5. Retrieval reads Chroma, falls back to pgvector; ingestion dual-writes
       after commit; reprocess clears stale vectors first
- [x] 6. `prisma/schema.prisma` — 18 models, matches live schema exactly
- [x] 7. `scripts/migrate_to_neon.py` — transactional row copy, FK order
- [x] 8. `scripts/backfill_chroma.py` — 459 vectors synced
- [x] 9. `scripts/verify_schema.py` + `npm run db:verify` guard
- [x] 10. `tests/test_vector_store.py` — 10 tests, Chroma + fallback
- [x] 11. Re-verification: 278 pass, build clean, typecheck clean

## Review

### What was built
`vector_store.py` is a small module with one job: hand back (chunk_id,
similarity) pairs from Chroma, or raise. Retrieval catches that and runs the
pgvector query instead. Content, section and page are always read from
Postgres afterwards, so Chroma holds vectors and filter metadata only and the
two stores cannot drift into disagreeing about what a chunk says.

The dual write happens *after* the ingestion transaction commits, not inside
it. A Chroma outage then costs a paper its place in the primary index and
nothing else — the vectors are already durable in `paper_chunks.embedding`,
retrieval still finds them, and `backfill_chroma.py` re-syncs.

### Verified, not assumed
- Fallback: stopped the container mid-session. Same chunk ids, same order,
  same similarity scores as Chroma, to 4 dp. `/health` reported
  `vector_store: degraded` while `status` stayed `ok`.
- Degradation without the client library installed: import blocked at runtime,
  retrieval still answered.
- Baseline fidelity: applied `0_init/migration.sql` to a scratch database and
  diffed against the source — 132 columns, 45 indexes, 65 constraints, all
  matching.
- Cut-over: full 1086-row copy to a scratch target. Vector and JSONB columns
  compared by md5 over the whole table — byte identical. ANN query works on
  the target.
- The guard: dropped an index and a CHECK on a scratch database and confirmed
  `verify_schema.py` exits 1 and names both.

### The trap worth knowing about
`prisma migrate diff` produced a baseline that was missing all 18 CHECK
constraints, had rewritten the HNSW index as a btree, and had dropped the
WHERE clause off the partial sha256 index. None of that fails loudly: a
dropped HNSW index leaves vector search *working*, just sequentially scanning.
`scripts/dump_raw_objects.py` regenerates the correct DDL from the catalog and
`npm run db:verify` asserts it is still there. This is why the README says to
read generated migration SQL before applying it.

### Still open
- **OpenRouter is out of credits (HTTP 402).** Every LLM feature — answering,
  agent research, claim verification, figure interpretation, cross-paper
  synthesis — returns 503 until it is topped up. Unrelated to this work; the
  2 failing tests are exactly these live calls.
- **Neon not yet cut over** — waiting on the connection string. Everything is
  built and rehearsed against a scratch database; the cut-over is 4 commands.
- `schema_migrations` carries 5 stale rows from an old renumbering. Harmless
  (the schema is correct) and cleared by starting Neon from the Prisma
  baseline instead of the legacy SQL migrations.
- Enter-to-submit on /search could not be reproduced under browser automation.
  Trusted keydown reaches the input, bubbles un-prevented to window, no submit
  fires — but CDP's synthetic Enter does not run Chromium's default form
  action, and the form is otherwise textbook (onSubmit, enabled submit button,
  input inside the form; requestSubmit works). Needs a 5-second manual check.

---

## Final pre-ship audit (7 Sept 2026)

Full sweep: build, typecheck, lint, 294 backend tests, live browser walk of every
page, and a security pass over the API. Six real defects found and fixed.

### Fixed

- [x] **Duplicate default project — papers appeared to vanish.** `listProjects`
      then "create if empty" is two round trips with a gap; a dev double-mount
      fell into it and created two "My Library" projects 171 ms apart. The UI
      then selected the newer, empty one, so the uploaded paper was invisible.
      Now `POST /projects/default` decides it server-side under a per-user
      advisory lock. Verified with 5 concurrent calls returning one id.
- [x] **Every AI feature was down on a 402.** `max_tokens` is a reservation, not
      a spend, so a 2048 ceiling was refused outright while the balance could
      cover the actual answer. The provider now retries once at the affordable
      ceiling, and refuses below 256 tokens rather than serving a stub.
      This turned the 2 long-standing failing tests green.
- [x] **467 of 508 Chroma vectors were orphaned (92%).** Left behind by the Neon
      cut-over. Retrieval skipped them, so no wrong citations — but they
      occupied candidate slots and silently shrank result sets. Rebuilt from
      Postgres: now 41/41 in sync.
- [x] **Paper deletion never removed vectors.** `vector_store.delete_paper` was
      written and documented for exactly this and never called. Wired in, so
      the orphan problem above cannot recur.
- [x] **`DELETE /projects/{id}` did not exist.** The settings screen has always
      shown a delete-with-confirmation flow; the button returned 405. Route
      added, cascading to papers, vectors and stored bytes.
- [x] **Uploads were fully buffered before the size check.** A 2 GB body cost
      2 GB of memory before being rejected. Now read in 1 MB blocks, stopping
      one block past the limit.

### Hardening

- [x] Security headers on every response (`nosniff`, `DENY`, `no-referrer`,
      CSP). Matters because `/assets/{id}/content` replays a media type
      recorded at ingestion.
- [x] 402 now names the cause ("account is out of credits") instead of leaking
      `Prompt tokens limit exceeded: 3332 > 2642`, which reads like an app bug.
- [x] Two pre-existing `react-hooks/set-state-in-effect` lint errors fixed by
      deriving the default paper during render instead of seeding it in an
      effect. Lint is now clean at zero warnings.

### Verified, not assumed

- 294 backend tests pass. `tsc --noEmit`, `eslint` and `next build` all clean.
- Search end-to-end against the rebuilt index: 0.797 top similarity, relevant.
- Fresh-user path (cleared localStorage) now lands on the library holding the
  paper, and persists that choice.
- CORS refuses a forged origin; all SQL is parameterized; storage resolves and
  re-checks against the root, so no traversal.

### Still open

- **OpenRouter account is out of credits.** Not a code problem: the retry lands
  on a *prompt*-token ceiling of ~2642 against a 3300-token evidence prompt.
  One live test fails only when run back-to-back with the other; it passes
  alone. Everything else — search, reranking, extraction — is local.
- **No authentication.** Anyone who can reach the API reads and writes
  everything. The sign-in page says so honestly. This is the one thing that
  must land before any deployment reachable from a network.
- **No rate limiting.** An open, unauthenticated LLM-backed endpoint is a
  billing risk as soon as it is exposed.
- The duplicate empty "My Library" still exists. It is no longer selected;
  removing it is now possible from Settings.

---

## Sprint: third training session, Clerk auth, free LLM, rate limiting (7 Sept 2026)

### 1. Third model missing from the Training Lab
Root cause found, three separate gaps — not one bug:
- [ ] `app/(app)/training/page.tsx` hardcodes a two-element `experiments` array
      (relevance, stance). The neural relevance reranker is simply absent.
- [ ] `app/api/training/[task]/route.ts` maps only two notebooks, so even the
      download route could not serve the third.
- [ ] `colab/validate_research_notebooks.py` hardcodes the same two filenames,
      so `Aletheia_Neural_Reranker_Colab.ipynb` has 9 code cells and **zero**
      outputs — it has never been executed, hence no "training session".
- [ ] `backend/models/neural_relevance_model.json` records only
      `initial_train_loss` / `final_train_loss`. `TrainingHistory.losses` is
      computed and thrown away, so there is no learning curve to draw.
- [ ] The `Sprint 6 Benchmark Corpus` project no longer exists in Neon (lost in
      the cut-over), so the trainer cannot rebuild candidates.

Fix, in order:
- [ ] Re-ingest the 10-paper corpus (`scripts/ingest_corpus.py`) — local
      embeddings, no API key.
- [ ] Persist `history.json` from `train_neural_reranker.py` in the same shape
      the other two models use, and re-run training.
- [ ] Make the Training Lab data-driven so a trained model can never again be
      silently missing from the page.
- [ ] Execute the reranker notebook offline against the local corpus and record
      it in `validation-results.json` alongside the other two.

### 2. Clerk authentication
- [ ] Google OAuth + email/password + username.
- [ ] Middleware protecting the `(app)` routes.
- [ ] Backend verifies the Clerk session JWT; `DEV_USER_ID` is replaced by the
      real subject, so projects scope per user for the first time.
- [ ] `users` table gains a Clerk subject column; users provisioned on first
      request.

### 3. Free LLM provider (OpenRouter is out of credits)
- [ ] Google Gemini free tier via its OpenAI-compatible endpoint — free, high
      daily limits, and it does vision, which figure interpretation needs.
- [ ] Keep the provider interface; select with `LLM_PROVIDER`.

### 4. Rate limiting and security
- [ ] Per-user / per-IP rate limits, strictest on the LLM-backed routes.
- [ ] Audit and fix whatever else the pass turns up.

---

## Review — third training session, Clerk auth, free LLM, rate limiting

### 1. The third model was missing in four separate places

Not one bug. The neural relevance reranker was trained, evaluated and
completely invisible, and each layer had its own reason:

- [x] `app/(app)/training/page.tsx` held a two-element literal. The reranker
      was never added to it.
- [x] `app/api/training/[task]/route.ts` held a *second* two-element literal,
      so the download would have 404'd even once the page offered it.
- [x] `colab/validate_research_notebooks.py` held a *third*, so the notebook
      had nine code cells and zero outputs — never executed, whatever the
      prose said.
- [x] `TrainingHistory.losses` was computed every run and thrown away.
      `neural_relevance_model.json` kept only the first and last loss, so
      there was no curve to draw even if the page had wanted one.
- [x] The `Sprint 6 Benchmark Corpus` project no longer existed in Neon (lost
      in the cut-over), so the trainer could not rebuild its candidates.

Fixed by making the list exist once. `lib/experiments.ts` is now the single
registry the page and the download route both read, and the notebook validator
derives its list from the directory and **fails** if a notebook in `colab/` is
not in it. A fourth model is one entry; a half-added one cannot ship looking
complete.

The card is not a copy of the other two. A ranking model has no meaningful
accuracy and no confusion matrix, so it shows MRR and Recall@6 against the
cosine baseline it has to beat. Forcing it into the classifier layout would
have meant inventing numbers.

### 2. Two real bugs found only by running things

- [x] **The reranker notebook crashed on cell 4.** `make_chunks` iterated
      `lines`, which was never assigned. Anyone who opened it in Colab and
      chose Run all hit `NameError`. Found because the notebook was executed
      for the first time, which is the entire argument for executing it.
- [x] **`build_neural_reranker_notebook.py` would have silently reverted it.**
      The generator has drifted well behind the checked-in notebook — it still
      emits the pypdf→PyMuPDF switch, drops the download retry loop, and has
      12 double-brace sites that print `{key}` instead of the value. Running it
      overwrote all of that without a word. It now compares the code cells and
      refuses unless `--force`, naming what to reconcile.

### 3. Retraining reproduced the original run exactly

Re-ingested the corpus (10/10 papers, 198 pages, 389 chunks embedded) and
retrained. Same 1,920/500 split, same 169/41 positives, same MRR 0.717, same
Recall@6 0.799, same losses to 4 dp as the run from 1 September. A re-ingest
that produces byte-identical retrieval candidates is a stronger reproducibility
result than the notebook was ever going to give.

`history.json` now records 21 sampled epochs with **both** train and validation
loss. The validation line is new for all future runs: it costs one forward pass
per sample and it is the only thing on the chart that can show overfitting.

### 4. Authentication (Clerk)

- [x] Google, email and username sign-in. Clerk hosts the form, so no
      credential ever passes through this codebase.
- [x] `middleware.ts` protects every route by allow-list. A page added next
      month is protected by default; with a deny-list it would be public by
      accident and nobody would notice.
- [x] The API verifies the session JWT locally against Clerk's JWKS — one
      fetch per key rotation, not per request, and the secret key is not
      involved. Users are provisioned on first request rather than by webhook,
      because a webhook that has not arrived yet is a signed-in user staring at
      an error.
- [x] Migration `0011_clerk_users.sql`. The local UUID stays the primary key —
      every foreign key already points at it — with `clerk_user_id` unique
      alongside, so one person cannot fork into two half-libraries.
- [x] **The API refuses to start** with no issuer and no explicit
      `ALLOW_UNAUTHENTICATED=true`. A deployment that forgets to configure
      Clerk gets a startup error instead of an open database.
- [x] Without keys, everything behaves exactly as before and the sign-in page
      says so. A repository checked out fresh still builds and runs.

### 5. A live IDOR, found while wiring auth in

Only `GET /projects` filtered by user. `GET /projects/{id}`,
`DELETE /projects/{id}` and every paper, claim, conversation and asset route
took an id from the URL and trusted it. With one seeded user that was
invisible; the moment accounts existed, **any signed-in user could have read or
deleted another's entire library by guessing a UUID.**

`app/core/ownership.py` is attached at the router, not the handler — FastAPI
resolves dependencies after route matching, so one function sees whichever
resource id the matched route declares and a new endpoint inherits the check
the day it is written. Per-handler would have been thirty edits and one that
got forgotten, which is precisely the failure that produced the bug above.

404, not 403, for someone else's id: a 403 confirms the id exists.

### 6. Rate limiting

Three sliding windows, per signed-in user and falling back to IP: 120
requests/minute general, **12/minute** for the LLM-backed routes because those
cost money and take seconds, and 60 uploads/hour because those consume disk.
`/health` is never limited — a liveness probe that fails during an incident is
worse than useless.

Stated plainly in the module: the counter is in memory, so it is per process
and N workers permit roughly N times the rate. For one process it is exact; for
a scaled deployment it is a floor and the counter belongs in Redis.

### 7. Free LLM provider

OpenRouter is out of credits — the account affords 210 output tokens against a
256 minimum, which is why two live tests fail. The provider is now any
OpenAI-compatible endpoint, selected by `LLM_PROVIDER`: `openrouter`, `gemini`,
`groq`, `ollama` or `custom`. **Google Gemini** is the recommended free option
and is the one to switch to — free tier, no card, and it does vision, which
figure interpretation needs. Groq is free and faster but text-only, so figures
would fail loudly rather than be guessed at.

429 is now distinguished from 402 in the error text, because "your free tier
quota reset in 37 seconds" and "your wallet is empty" are different problems
and only one of them is fixed with a credit card.

### Verified, not assumed

- 319 backend tests pass. The 2 failures are the live OpenRouter calls,
  failing on 402 for lack of credits — the same two that were already failing.
- 22 new security tests, including `alg: none`, a token signed by the wrong
  key, a wrong issuer, an expired token and a token minted for another origin.
- **Negative control run:** the ownership dependency was removed and all four
  cross-user tests failed, including the delete. The guard is load-bearing and
  the tests are not passing vacuously.
- Rate limiting against the live API: exactly 120 requests allowed, then 429
  with `Retry-After: 30`, while `/health` kept answering 200 throughout.
- All three notebooks execute end to end. `validation-results.json` lists
  three, not two.
- `tsc --noEmit`, `eslint` and `next build` all clean. Training Lab renders
  three cards with three learning curves; all three notebook downloads return
  200 and an unknown one returns 404.

### Still open

- **Clerk is built but unverified against a live tenant.** No keys were
  supplied, so the sign-in flow, the Google redirect and a real signed token
  end-to-end have not been exercised in a browser. The verification path is in
  `test_auth.py` and everything below the token is tested; what is untested is
  Clerk itself.
- **The reranker notebook does not reproduce the shipped numbers,** and now
  says so in its own final cell. It retrieves with TF-IDF so it can run
  anywhere; the shipped pipeline retrieves with a semantic embedding model.
  Different candidates, different baseline, and the notebook's MLP comes out
  slightly *below* its baseline. Both numbers are real; they are not the same
  experiment.
- **`build_neural_reranker_notebook.py` is still behind the notebook.** It no
  longer overwrites silently, but reconciling the two is unfinished work.
- The rate limiter is per process. Correct for one worker, a floor for many.

---

## Sprint: carried-over debt, landing page, production audit (12 Sept 2026)

Four items left open by the previous sprint, then a pass over whether this is
actually deployable.

### 1. The notebook generator was behind its own notebook

`build_neural_reranker_notebook.py` refused to overwrite, which stopped the
damage but left the two disagreeing. The notebook was ahead in four ways: it
used pypdf where the generator still emitted PyMuPDF, it carried the arXiv
download retry loop, it had the `make_chunks` fix for the `NameError` that hit
anyone who chose Run all, and it had two markdown sections the generator did
not. The generator also emitted 12 `{{...}}` sites in cells that are not
f-strings, so those reached the reader as literal braces.

- [x] Every cell body is now a module-level **raw, non-f-string** constant at
      column zero, taken verbatim from the notebook. The one cell needing a
      substitution names a placeholder and replaces it. The whole class of
      escaping bug is gone rather than fixed site by site — which matters,
      because the previous attempt at fixing it by blanket-replacing braces
      broke the cells that really were f-strings.
- [x] Regenerating now **preserves** the execution outputs and the validator's
      record when the code is unchanged, and drops them when `--force` changes
      the code, because an output that no longer matches its cell is worse than
      no output.
- [x] The comparison decodes the embedded benchmark instead of comparing its
      base64. gzip output differs between zlib builds, so the old check
      reported drift on a byte no reader of the notebook can see.
- [x] `--check` added, wired into `validate_research_notebooks.py` and into the
      test suite (`test_notebook_generator.py`), so drift fails on its own
      rather than when someone remembers to look.
- [x] Negative control: injected a comment into the notebook and confirmed
      `--check`, the bare generator, and pytest all go red.

### 2. The rate limiter now has somewhere shared to count

- [x] `REDIS_URL` selects a sorted-set sliding window in Redis; blank keeps the
      in-process deque. The trim, count and append happen inside one Lua
      script, so the check and the write cannot interleave across workers.
- [x] Redis is treated as a limiter, not a dependency: if it is unreachable the
      request is counted against the in-process window and the API keeps
      serving. Refusing instead would hand anyone who can disrupt Redis a way
      to take the service down.
- [x] `/health` reports which backend is counting and whether it has degraded.
- [x] A `redis` service in docker-compose with no persistence — a lost window
      costs one caller one extra minute of allowance.
- [x] **Found while writing it:** the caller's identity was `hash(token)`, and
      `hash()` is salted per process. Every worker would have bucketed the same
      user differently and each granted a full budget, so the shared counter
      would have been shared in name only. Now blake2b.
- [x] Verified against the real stack, not just unit tests: exactly 120 of 130
      requests allowed with `Retry-After` correct, `/health` answering 200
      throughout, then Redis stopped mid-flight — the API kept answering,
      `/health` said `redis (degraded: falling back to in-process)`, and it
      recovered on its own when Redis came back.
- [x] Negative control: two in-process limiters each granted a full budget
      where two Redis limiters shared one, so the test distinguishes them.

### 3. The duplicate "My Library"

- [x] `backend/scripts/remove_duplicate_default_projects.py`, dry-run by
      default. It only takes a project that is not its user's oldest, holds no
      papers, has no description and is named exactly the default — two
      projects a user deliberately gave the same name is a legitimate thing to
      want. The emptiness check is repeated inside the deleting transaction,
      so a paper uploaded mid-run saves its project.
- [x] Eight tests covering each refusal, including the mid-run upload.
- [x] Exercised against a reconstructed copy of the original race (two projects
      171 ms apart) plus a described one, a renamed one and an occupied one:
      it took exactly the one row and left the other four.
- [ ] **Still to run against the live Neon database.** This local database no
      longer holds the duplicate; the row is in Neon, and the connection string
      is not in this checkout. `npm run projects:dedupe` reports before it
      deletes.

### 4. A landing page

- [x] `/` was a redirect into `/library`, so a signed-out visitor was bounced
      to a sign-in form having never been told what this is. It is now a real
      page: the problem, the four guarantees, the six-step path a question
      takes, the eight workspace entry points, and the three trained models.
- [x] Added to the middleware allow-list as `"/"` exactly, not `"/(.*)"`.
- [x] The stance classifier is shown at 54% and labelled as below its own
      baseline. A page about not fabricating citations is a bad place to start
      quietly dropping the result that did not work.
- [x] Verified rendered at 1440px and 390px through a real browser.

### 5. Production audit

- [x] **Critical: unauthenticated RCE in Next.js** (GHSA-p293-qw3h-jr36, plus
      an AVIF path in the image optimiser). 16.3.2 was inside the affected
      range and this is a Windows host, which is exactly what the first
      advisory targets. Upgraded to 16.3.5 — a patch bump — along with sharp
      and js-yaml. Build, typecheck, lint and 342 tests clean afterwards.
- [x] **`npm run db:verify` was passing vacuously on Windows.** The npm scripts
      named `backend/.venv/bin/python`, which does not exist here; cmd.exe
      printed "'backend' is not recognized" and npm still exited 0. The schema
      guard — the one asserting the HNSW index and 18 CHECK constraints Prisma
      cannot express are still present — had been reporting success without
      running. `scripts/run-python.mjs` resolves the interpreter per platform
      and propagates the real exit code. It now runs: 3 raw indexes, 18 CHECKs.
- [x] **A malformed token answered 500, not 401.** Found by pointing the API at
      a real JWKS server instead of the suite's stub: finding the signing key
      parses the token header, so `Authorization: Bearer nonsense` raised
      `DecodeError` — a *sibling* of the JWKS errors, not a subclass — and
      escaped both handlers. An unauthenticated caller could write a traceback
      into the log on demand. The suite could not have caught it: its stub
      returned a key for any string, which is more forgiving than PyJWKClient.
      The stub now parses the header like the real one does, and five
      parametrised cases fail without the fix.
- [x] Auth verified end to end over HTTP against a live JWKS: 15 checks
      covering anonymous, garbage, expired, wrong issuer, wrong key, `alg:none`
      and unknown `kid`, plus first-request provisioning, the same subject
      returning to the same library, and four cross-user isolation checks.
- [x] Whole stack from a cold `docker compose up`: API, Postgres, Chroma and
      Redis all healthy, `/health` green on every dependency.
- [x] No secrets committed — only `.env.example` files are tracked, and a scan
      for key-shaped strings across the tree is clean.

### Still open

- **Clerk has still never run against a live tenant.** Everything below the
  token is now verified against a real JWKS over real HTTP, so what remains
  untested is Clerk's hosted sign-in UI and the Google redirect — their
  product, not this code. It needs keys from a Clerk dashboard; nothing else
  is blocking it.
- **The dedupe script has not been run against Neon** (see 3).
- **4 high-severity advisories remain, all in the `prisma` CLI**
  (`deepmerge-ts`, and `mysql2` via `@prisma/config`). There is no fixed 7.x —
  npm's proposed "fix" is a downgrade to 6.19.3, which would break the schema
  baseline. It is a devDependency: it never runs in production, nothing imports
  `@prisma/client` at runtime, and `mysql2` is a MySQL driver a Postgres
  project never loads. Worth revisiting when Prisma ships a patched 7.x.
- **~1 MB of scratch artifacts are committed** under `tmp/pdfs/` and
  `output/pdf/` — intermediate page renders from building SUMMARY.pdf. Not a
  blocker, but `tmp/` is not a directory that belongs in a repository.
- The reranker notebook still does not reproduce the shipped numbers, and still
  says so in its own final cell. TF-IDF retrieval against a semantic pipeline
  is a different experiment, not a worse run of the same one.
