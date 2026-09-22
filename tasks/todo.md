# UI pass — themes, Clerk contrast, and a Tab-completing question composer

## What was asked
1. Go through the whole site and fix UI bugs.
2. Add a dark/light mode toggle.
3. Fix the transparency/visibility glitch on the Clerk sign-in page.
4. When the AI recommends a next question, pressing Tab should print the
   *whole* question. Make it more interactive.

## Bugs found by audit (before any change)

### B1 — `text-base` is a font size, not a colour  *(root cause of several)*
`tailwind.config.ts` maps `colors.base → var(--bg-base)`, so the codebase
writes `text-base` meaning "dark text on a brass chip". Tailwind's core
`text-base` utility (font-size: 1rem) wins. Verified in the browser:
`.text-base` computes `font-size: 16px` and leaves `color` inherited.

Every site is therefore *two* bugs — unreadable colour **and** a font-size jump:
- `app/(app)/library/page.tsx:76` — active filter chip: cream-on-brass, and the
  chip grows from 12px to 16px when selected, shifting the row.
- `app/(app)/search/page.tsx:87` — "Semantic" chip, same.
- `app/(app)/claim-verification/page.tsx:176` — active filter chip, same.
- `components/CitationCard.tsx:15` — evidence pill on brass: 9px → 16px, breaks
  the card's single-line layout.
- `app/(app)/agent/page.tsx:30,~120` — step badges inside a `size-4`/`size-5`
  circle get 16px glyphs that overflow the circle.
- `components/ResearchMarkdown.tsx:64` — `hover:bg-brass hover:text-base`
  reflows the whole paragraph on hover of an inline citation.

### B2 — Clerk's neutral colour is black on a dark card
`app/layout.tsx` sets `colorBackground`/`colorForeground` but never
`colorNeutral`, which defaults to black. Clerk derives social-button text,
borders and dividers from it, so "Continue with Google" computes as
`color(srgb 0 0 0 / 0.62)` on a `#14110f` card — the invisible text in the
report. Same cause makes the card border `rgba(0,0,0,0.11)`, i.e. nothing.

### B3 — the Clerk card does not read as a card
`colorBackground: #14110f` vs the page's `--bg-base: #14110d`. Two units
apart: the form floats with no edge. It should sit on `--bg-surface`.

### B4 — accent buttons label themselves with the body text colour
`bg-oxblood … text-primary` in 12 places, `bg-brass` + chip text likewise.
Correct by accident in dark; in a light theme `--text-primary` is dark and the
label disappears. There is no "text that sits on an accent" token.

### B5 — no theme system at all
`:root` holds one hard-coded dark palette. Nothing reads
`prefers-color-scheme`, `color-scheme` is unset (so form controls and
scrollbars render light-mode chrome on a dark page).

### B6 — misc
- `app/(app)/training/page.tsx:35,37` — chart strokes hardcoded `#b39a64` /
  `#91a1ca` instead of tokens.
- Focus styling is inconsistent; several interactive elements remove the
  outline without replacing it.

## Plan

- [x] Audit the site, reproduce B2/B3 in a browser, confirm B1 by computed style
- [x] **Tokens** — rewrite `app/globals.css` as a themed token set: dark under
      `:root` / `[data-theme=dark]`, light under `[data-theme=light]`, plus
      `--text-on-accent` and `--text-on-brass`. Set `color-scheme` per theme.
- [x] **Tailwind** — expose `on-accent` / `on-brass`
- [x] **Theme runtime** — `lib/theme.tsx` (provider + `useTheme`), no-flash
      inline script in `app/layout.tsx`, persisted to `localStorage`, defaults
      to the OS setting and keeps following it until the user chooses
- [x] **Toggle** — `components/ThemeToggle.tsx`, mounted in the app Topbar, the
      landing masthead and the auth layout (the three shells)
- [x] **Clerk** — move `ClerkProvider` into a client `Providers` component so
      its appearance follows the theme; set `colorNeutral`; point every Clerk
      variable at a real app token; give the card a visible border (B2, B3)
- [x] **Fix B1** everywhere; **fix B4** everywhere
- [x] **Question composer** — `components/QuestionComposer.tsx`: inline ghost
      text, **Tab inserts the whole suggestion**, `→` at end-of-line also
      accepts, `↑`/`↓` cycles, `Esc` dismisses, chips below for pointer users.
      Suggestions from `lib/suggestions.ts`, derived from the last answer's
      evidence, uncited blocks, and sufficiency — and superseded by
      `follow_ups` from the API if the backend ever returns it.
- [x] **Verify** — typecheck, lint, build, and drive both themes in a browser

## Review

### Files
New: `lib/theme.tsx`, `lib/suggestions.ts`, `components/ThemeToggle.tsx`,
`components/Providers.tsx`, `components/QuestionComposer.tsx`.
Rewritten: `app/globals.css`, `app/layout.tsx`, `app/(auth)/layout.tsx`.
Touched: the tailwind config, the app shell, Topbar, Sidebar, the workspace
provider, and the eleven pages/components carrying a mis-typed colour class.

### What changed

**Themes.** `globals.css` now holds two token sets — dark under `:root`, light
under `:root[data-theme="light"]` — and sets `color-scheme` for each, which is
what makes native scrollbars, `<select>` popups and autofill match the page.
Two new tokens, `--text-on-accent` and `--text-on-brass`, name the colour that
sits *on* a filled accent; that is the distinction the old palette did not
have, and the one every miscoloured button was failing to make.

The theme is read through `useSyncExternalStore`, not mirrored into React
state. That was not a style choice: the first version kept it in a provider
whose effect wrote `data-theme`, and because React runs effects child-first,
the Clerk palette below it read the theme it was switching *away* from — the
sign-in card stayed dark on a light page. Reading the store makes the DOM write
happen before anything can observe it, and it gave cross-tab sync for free.
An inline script in `<head>` applies the stored theme before first paint, so
there is no flash; the toggle's two glyphs are both in the DOM and chosen by
CSS, so the icon cannot render the server's guess and then flip.

Default is the OS setting, and it keeps following the OS until the reader picks
a side. Verified: with storage cleared and the OS on light, the app opens light.

**Clerk.** Root cause was `colorNeutral`, never set and therefore black. Clerk
derives the social-button label, the "or" divider and several borders from it
at low alpha, so "Continue with Google" computed to `color(srgb 0 0 0 / 0.62)`
on a near-black card — present in the DOM, invisible on screen. Every Clerk
variable is now read from the app's own custom properties at runtime, so there
is one place a hex is written and the hosted form re-themes with everything
else. The card also moved from `#14110f` (two units off the page background) to
`--bg-surface`, and links moved off `colorPrimary`, which has to be a button
fill and is too dark to read as text.

**Tab-completing next question.** `QuestionComposer` draws the suggestion as
ghost text behind the textarea — never in its value, so it cannot be submitted
by accident — and **Tab inserts the whole question**, not a word or a prefix.
`→` at end of line does the same, `↑`/`↓` cycle, `Esc` dismisses, and chips
below cover pointer users. As you type, the offer moves to the suggestion your
text is actually a prefix of. Tab with nothing to complete still moves focus,
so the field is not a keyboard trap.

Suggestions come from `lib/suggestions.ts` and are anchored in what the backend
returned: passages it retrieved and did not cite, papers it cited more than
one of, the section a citation came from, and — when the evidence was
insufficient — the nearest passage it found. Each carries a visible reason.
They were derived on the client at this point, with a seam for the API to
supply its own. **See "Follow-up 2" below — the API now does, and the client
derivation is the fallback for when it cannot.**

**Bugs fixed beyond the brief.** The app shell collapsed to its content height,
so the sidebar stopped partway down the page — `<body>` is `min-h-full` with an
auto height, and every `h-full` under it resolved against an indefinite
containing block. The shell now sizes by flex. The topbar said "API offline"
for any failure, including a refused request from a perfectly healthy API; it
now distinguishes the two. The focus ring is a real, visible default in `base`,
which controls can still override. The training charts use tokens instead of
two hardcoded hexes.

### Verification
- `tsc --noEmit`, `eslint` and `next build` all clean.
- Both themes driven in a browser on the landing page, sign-in, sign-up, the
  app shell and the Training Lab, including a live toggle in each.
- `Tab`, `↑`/`↓`, `Esc`, prefix matching and tab-out were each exercised
  against the real component and asserted on the textarea's value.
- Root causes were confirmed from computed styles before being fixed, not
  guessed: `.text-base` computing to `font-size: 16px` with an inherited
  colour, and the Google button computing to `color(srgb 0 0 0 / 0.62)`.

### Follow-up 2 — the API writes the next questions itself

The client-side derivation above is now the fallback. `POST /answer` and
`POST /conversations/{id}/messages` return `follow_ups`, written by the model
that just read the evidence.

**As a second completion, not an extra section in the answering prompt.** That
prompt is where the citation guarantee lives — which IDs may be cited, the
`INSUFFICIENT_EVIDENCE` marker on its own first line, the exact columns a
numeric comparison table must use — and all three are parsed afterwards by
`answering.py`. Appending "and also suggest three questions" puts unparsed free
text next to a marker check and three regexes, to buy a garnish. One more round
trip is the cheaper risk.

Two consequences, both deliberate:

- **It cannot fail an answer.** Provider outage, unparseable reply, a shape
  nobody anticipated — every one yields no suggestions and a log line. There is
  a deliberate `except Exception` in `services/follow_ups.py`, and a test that
  runs it, because a guard with no failing test is an assumption.
- **It is opt-in per call site.** `answer_from_context` defaults to off, so the
  research agent does not buy a set of suggestions for each of its four planned
  questions on the way to one brief.

The reply is not trusted because it was asked for politely. `_usable_questions`
drops anything that is not a question, is over 180 characters (dropped, not
truncated — half a question cannot be accepted with Tab), repeats the question
just asked, or duplicates another, then caps the count. Fenced and
prose-wrapped JSON are both accepted, via `services/model_json.py` — extracted
from the research planner, which had the same decoder inline.

`follow_ups` is stored in the message metadata, so reopening a thread offers
the questions it offered when the answer arrived rather than a fresh set, or a
fresh model call.

`FOLLOW_UP_SUGGESTIONS_ENABLED=false` turns the whole thing off without
touching code; answers are identical either way.

**Verified.** 19 new tests in `tests/test_follow_ups.py`; full backend suite
444 passed, 1 skipped. The endpoint test was proved able to fail by removing
`suggest_next=True` from the route and watching it go red. One live call
against the configured model (`gpt-5.6-luna`) returned two questions, both
drawn from the evidence blocks the answer had *not* cited — which is what the
prompt asks for and the reason the call exists.

The suite also caught a real assumption of its own: `ScriptedLLM` recorded only
the most recent call, so `test_the_model_is_given_evidence_ids_not_chunk_ids`
started asserting the grounding contract against the follow-up prompt. The
fixture now records every call and exposes the *first* — the answering one —
which is what those tests always meant.

### End-to-end against the rebuilt container

`docker compose build api` + `docker compose up -d api`. The container serves
the real Neon library (509 vectors) through the real configured model
(`gpt-5.6-luna`).

- **Contract published.** `GET /openapi.json` now carries
  `AnswerResponse.follow_ups: array<string>` — proof the running image is the
  new code, not a cached layer.
- **Full pipeline, real corpus.** A question the corpus does *not* cover
  returned `sufficient_evidence: false` with 2 citations, 0 fabricated, and 4
  uncited evidence blocks — and two follow-ups both drawn from those uncited
  blocks, pivoting to what the library does hold. The insufficient case is
  where a next question matters most, and it is the case that works.
- **Persistence, real database.** The conversation route wrote three follow-ups
  into the message metadata on Neon and read them back byte-identical, with 5
  citations alongside. Both test conversations were deleted afterwards.
- **A `citations persisted: 0` on the first run was the model, not the write
  path** — that answer contained no bracketed IDs. Re-run on a well-covered
  question: 5 written, 5 read back. Chased rather than assumed, because
  reporting a clean bill of health over a real regression is the expensive
  mistake.
- **Auth intact.** An unauthenticated `POST /answer` is still `401 {"detail":
  "This endpoint requires a signed-in session."}`, and the container log has no
  errors since the restart.
- **Frontend closes the loop.** The three questions the API actually returned,
  fed through `followUpQuestions`, all carried the reason "suggested by the
  model" — so `follow_ups` took precedence over the client heuristics — and Tab
  inserted the full 101-character question with the caret at the end.

Not covered: the HTTP route through a signed-in browser session. Clerk signs
tokens with RS256 and I cannot mint one; the route's own layer above the
pipeline is exercised by `tests/test_follow_ups.py` against a real database,
and by the 401 above.

### Not done
- Data-bearing states (a populated library, a real answer with citations) were
  not photographed in light mode: the API requires a signed-in session and I
  cannot sign in. Every one of those surfaces is built from the same tokens as
  the pages that were checked, but that is reasoning, not a screenshot.

---

# Previous task — deployment (settled 2026-09-22)

Kept for the record; see `docs/DEPLOYMENT.md` for the current arrangement.

# Aletheia — deployment: Vercel frontend, backend on the developer's machine

Replaces the paused deployment (`aletheia-rag.vercel.app` → `DEPLOYMENT_PAUSED`,
owned by an account we cannot reach). The frontend lives in a fresh Vercel
project in *Tanishq's projects*. **The backend is not deployed anywhere.**

> **Status (2026-09-22). Settled.** The frontend is live at
> <https://aletheia-rag.vercel.app>. The API runs under `backend/docker-compose.yml`
> on a development machine and the deployed site reaches it through a Cloudflare
> tunnel — see [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md), which is now the
> only deployment document in the tree.
>
> **Every backend-host section below is superseded.** Render, Cloudflare
> Containers, Cloud Run and Oracle A1 were each evaluated, three of them built,
> and all four removed. They are kept because they record why each one lost,
> which is the part worth not repeating. See the closing addendum for what was
> deleted.

## Decisions (confirmed with user)
- Backend host: **Cloudflare Containers**, not Render. Render Standard would
  run the code unchanged for ~$27.50/mo; Cloudflare is ~$7/mo at bursty traffic
  but needs an object-storage backend written first.
- Therefore: **implement a real R2 storage backend** before deploying anything.

## Why the storage work is mandatory, not optional
Cloudflare's own docs: *"All disk is ephemeral. When a Container instance goes
to sleep, the next time it is started, it will have a fresh disk."* Containers
sleep on idle by design. Today `storage_backend` has exactly one
implementation — `local` — so every sleep/wake would leave Neon rows pointing
at PDFs that no longer exist: the library would list papers whose reader,
figures and tables are all broken.

## What makes this tractable
The seam is already clean. Every byte of file I/O in the API goes through
`build_storage(settings)` — `papers.py`, `projects.py`, `assets.py`,
`ingestion.py`. Only two places touch the filesystem directly:
`main.py:40` (startup `mkdir`) and `health.py:32` (writability probe). So the
backend swap is one new class plus two backend-aware call sites.

## Plan

### A. R2 storage backend (the actual engineering)
- [x] A1. `R2Storage` in `app/services/storage.py`, implementing the existing
      `StorageBackend` protocol (`store` / `read` / `exists` / `delete`) against
      R2's **S3-compatible API**, signed with SigV4 over the `httpx` client the
      repo already depends on.
      *Chosen over the Worker `outboundByHost` trick (no credentials, less code)
      because SigV4 is verifiable from this machine before deploying, and keeps
      the backend portable if Cloudflare is ever abandoned. Chosen over `boto3`
      because botocore is ~50 MB and the repo explicitly keeps the image slim —
      same reasoning already written down for reportlab-over-WeasyPrint.*
- [x] A2. Settings in `config.py`: `r2_account_id`, `r2_bucket`,
      `r2_access_key_id`, `r2_secret_access_key`, plus a derived endpoint
      property. Document every one in `backend/.env.example`.
- [x] A3. Wire `build_storage` for `backend == "r2"`. Keep the unknown-backend
      and not-implemented errors naming the mistake, as they do now.
- [x] A4. Make `main.py` startup backend-aware — only `local` should mkdir.
- [x] A5. Make `/health` probe R2 for real (round-trip a tiny object, or
      HeadBucket) instead of reporting `not implemented` and going degraded.
      A storage backend that reports itself healthy without touching storage
      is the exact failure this file was written to avoid.
- [x] A6. Tests: round-trip, overwrite, missing-key read, delete idempotence,
      traversal key refusal (`../`), and `/health` degrading when R2 is
      unreachable. Run against a real scratch bucket, not a mock.

### B. Cold-start cost — bake the models in
- [x] B1. fastembed downloads ~120 MB (embedding) + the cross-encoder on first
      use and caches them **to disk**. On ephemeral disk that re-downloads on
      every wake. Pre-fetch both into the image at build time so a cold start
      loads from the image layer, not the network.

### C. Cloudflare deploy
- [x] C1. `wrangler.jsonc`: Worker entrypoint + `[[containers]]` bound to
      `backend/Dockerfile`, Durable Object migration, `instance_type`.
- [x] C2. Worker: proxy all HTTP to the container; R2 bucket binding.
- [x] C3. Create the `aletheia-papers` R2 bucket.
- [ ] C4. Secrets: `DATABASE_URL` (Neon), `CLERK_ISSUER`, `GEMINI_API_KEY`,
      R2 credentials. Never committed.
- [ ] C5. Deploy; capture the `*.workers.dev` URL.

### D. Vercel frontend
- [ ] D1. User creates empty project `aletheia` (the connector here is a role
      that cannot create projects — verified 403 twice).
- [ ] D2. Env: `NEXT_PUBLIC_API_URL` → Worker URL, Clerk publishable + secret,
      sign-in/up URLs.
- [ ] D3. Deploy to production, confirm build.

### E. Verification — nothing is "done" until these pass
- [ ] E1. `/health` returns `ok` with database + storage both ok.
- [ ] E2. Upload a PDF → ingestion completes → it appears in the library.
- [ ] E3. Search returns chunks; Ask returns a grounded answer with citations.
- [ ] E4. **The one that matters:** force the container to sleep, wake it, and
      confirm the uploaded PDF still opens in the reader. This is the whole
      reason for section A.
- [ ] E5. CORS: browser calls from the Vercel origin succeed; a token minted
      for another origin is refused.
- [ ] E6. Full backend test suite still green.

## Open items needing the user
- **Workers Paid ($5/mo)** must be active — Containers are `N/A` on the free
  plan. R2 is already enabled (2 buckets exist), so a card is likely on file,
  but the Workers subscription is separate.
- **Existing papers' binaries.** Handled: `scripts/backfill_r2.py` copies local
  files into R2 under their existing keys (`npm run storage:to-r2`). Run
  against the real schema it found 16 papers + 20 assets, copied and
  byte-verified the 12 present on this machine, and named the 24 whose bytes
  are gone with the paused deployment. Those must be re-uploaded through the
  app; nothing can recover them.

## Review — what is built and proven (2026-09-16)

### Built
`R2Storage` in `app/services/storage.py` implements the existing four-method
`StorageBackend` protocol against R2's S3 API, signed with SigV4 over the
`httpx` client already in requirements. No new Python dependency. `build_storage`
dispatches on `STORAGE_BACKEND=r2`; `main.py` no longer creates a storage
directory for a backend that has no filesystem; `/health` probes the bucket for
real instead of reporting `not implemented`.

`worker/index.ts` + `wrangler.jsonc` run the container behind a Worker that
only wakes it and forwards the request — routing, auth, CORS and rate limiting
stay in FastAPI, so there is one implementation of each, not two.

### Verified, not assumed
- **SigV4 is correct against AWS's own published vector**, not merely
  self-consistent: the derived signing key matches the hex in AWS's "how to
  derive a signing key" example. A fake S3 in the tests independently
  re-derives the signature from the raw request that arrived, which is what
  would catch a wrong canonical request.
- **A bug the tests found:** the signed `Host` header omitted a non-default
  port. Harmless against R2 on 443, fatal against any endpoint with a port.
  Fixed before it could reach a deploy.
- **Both backends refuse the same keys.** `../`, absolute and backslash keys
  raise on R2 exactly as they already did on local disk, so swapping backends
  cannot widen what a key may address.
- **The image builds**, via `wrangler deploy --dry-run` — Worker bundle,
  bindings and Dockerfile all resolve. 1.21 GB.
- **Cold starts no longer download models.** Both ONNX models are baked into
  the image (271 MB at `/opt/fastembed-cache`) and load with `--network none`
  in 0.5s. Without this, a woken container would re-fetch ~150 MB inside the
  request path on every cold start, on top of the model load itself.
- **Nothing regressed:** 403 passed, 12 skipped, 0 failed.
  One earlier failure (`test_rate_limit_redis`) was a stale local venv missing
  the already-pinned `redis==6.4.0`, not a code change — proven by installing
  it and re-running, not by inspection.

### Not yet done, and why
Everything remaining needs either money or a credential only the account owner
can mint:
- Workers Paid ($5/mo) — Containers are `N/A` on the free plan.
- An R2 API token (Object Read & Write on `aletheia-papers`).
- `wrangler login`, then `wrangler secret put` ×6, then `wrangler deploy`.
- The Vercel project: this session's connector is a role that cannot create
  projects (403, confirmed twice — via git link and via direct file deploy).

E1-E6 are deliberately still unchecked. E4 in particular — upload a PDF, let
the instance sleep, confirm the paper still opens — is the test the whole R2
change exists to pass, and it cannot run until the service is deployed.


## Addendum — backfill script (2026-09-16)

`scripts/backfill_r2.py`, wired as `npm run storage:to-r2`, with
`--status` / `--dry-run` / `--verify` / `--force` / `--source-dir`.

Verified end to end, not just unit-tested:
- Against the **real schema and the real dev database** — 16 papers, 20 assets.
  A wrong column name would only ever show at runtime, so the CLI itself was
  run, not just `transfer()`.
- **12 files copied and read back byte-for-byte**, their digests checked
  against the `papers.sha256` recorded at upload.
- **24 correctly reported unrecoverable**, listed by filename, **exit code 1** —
  a partial recovery cannot be mistaken for a complete one.
- **Idempotent:** the second run copied 0 and skipped 12 without overwriting.
- 9 tests cover the failure modes that matter: skip-if-present, force-overwrite,
  missing-locally, dry-run writes nothing, and the one that matters most —
  bytes contradicting the recorded digest are refused rather than uploaded.

Suite: 412 passed, 13 skipped, 0 failed.


## Addendum — the Cloud Run deployment path (2026-09-17)

Chosen after checking what the 2 GiB image actually rules out. Render's free
tier is 512 MB (the blueprint already measured that as too small), Railway and
Fly.io no longer have free tiers, and Hugging Face Spaces now requires a paid
plan to run a Docker Space at all. Cloud Run is the least-friction host that
fits, and Oracle's always-free ARM VM is the only genuinely free one.

Cloud Run is **not** reliably free for this service, and the doc says so rather
than pretending otherwise: Google enumerates the always-free allowance under
*request-based* billing, and the flag this app requires (below) puts it on
instance-based. The $300 / 90-day trial credit is what makes the first months
free; after that, light use is ~$5/month. A budget alert is part of the runbook.

Added `scripts/deploy_cloudrun.sh` and `docs/cloudrun-deploy.md`.

### The finding that shaped it
An upload returns 201 and finishes extraction in a FastAPI `BackgroundTasks`
(`app/api/papers.py:65`). Cloud Run's **default** request-based billing
throttles CPU to ~0 the moment the response is sent, so that background work
would stall mid-ingest: the paper sits at `running`, and the next cold start
marks it failed via `recover_stranded_jobs()`. `--no-cpu-throttling` is
therefore a correctness requirement on this host, not a performance knob —
the same class of constraint as `STORAGE_BACKEND=r2` on Cloudflare.

Its consequence is that a keepalive ping — the obvious cure for scale-to-zero
cold starts, and what was recommended before this was checked — is wrong here:
staying warm under lifetime billing costs 720 h/month against a free allowance
of ~50. Cold starts (~30–40s, floored by the 25s model load) are accepted
instead, and the reasoning is written down in the doc so it is not re-litigated.

`--max-instances 1` carries over from the Cloudflare notes for the same
`recover_stranded_jobs()` reason.

### Verified this session
- **Image builds clean: 1.21 GB**, both ONNX models baked in.
- **Frontend builds: 16 routes, exit 0** — and again with `.env.local` moved
  away, which proves the Clerk keys are runtime-only. A first deploy will not
  fail for want of them.
- `test_storage_r2` + `test_backfill_r2` + `test_health`: **29 passed,
  1 skipped**.
- `CLERK_ISSUER` is `https://amazed-heron-68.clerk.accounts.dev`, derived from
  the publishable key rather than guessed.
- R2 bucket `aletheia-papers` confirmed present.

### Blocked, and on what
- **Cloud Run needs an open billing account.** `tks2005homes@gmail.com` has one
  billing account, `01A552-CEFF0A-9DDD0F` (INR), and it is **closed**
  (`open: false`). Two projects do have billing enabled —
  `collective-odyssey-lr5vm`, `forward-icon-lfq84` — but the account has no
  permission on either them or their billing accounts; `describe` and
  `services list` both return `AUTH_PERMISSION_DENIED`. They are not usable.
- **An R2 API token** still has to be minted by hand; the Cloudflare connector
  exposes bucket CRUD but not token creation.
- **The Vercel project** could not be created again this session — blocked by
  the permission mode before it could reach the connector's own 403.


## Addendum — Oracle always-free VM, the chosen host (2026-09-17)

Chosen over Cloud Run after the billing arithmetic stopped being free. The
Cloud Run assets stay in the tree as the managed-host alternative; this is the
one to deploy.

Added `deploy/oracle/{docker-compose.yml,Caddyfile,provision.sh,deploy.sh,.env.example}`
and `docs/oracle-deploy.md`.

### Why this host and not the other three
It is the only one whose execution model the application does not have to be
compensated for. A real disk means `STORAGE_BACKEND` stays `local`, so there is
no R2 token to mint and no backfill to run — and `papers.storage_path` keeps
meaning what it says. Always-on CPU means the `BackgroundTasks` that finish
ingestion (`app/api/papers.py:65`) simply run, rather than needing Cloud Run's
`--no-cpu-throttling` and its by-the-hour bill. No sleep means no cold start.
`max_instances 1` is satisfied by there being one container, so the
`recover_stranded_jobs()` constraint needs no flag at all.

The cost is ops: patching, uptime and backups become ours. The backup gap is
written down in the doc rather than left implicit — the `papers` volume is now
the only copy of every uploaded PDF.

### Verified, not assumed
- **arm64 is proven, not hoped for.** The image already builds `linux/arm64` on
  this machine, which is exactly what Ampere A1 runs.
- **That image was run against the real Neon database** with this deployment's
  exact environment: `/health` → `database: ok, storage: ok, vector_store:
  disabled (pgvector only)`, healthy **5s** from cold. Worth recording: the
  ONNX models load lazily on first use, not at boot, so the ~25s figure from
  the Dockerfile notes is a first-request cost, not a startup cost.
- **Auth and CORS enforced, not merely configured.** Unauthenticated
  `GET /projects` → **401**. Preflight from `https://aletheia-rag.vercel.app` →
  **200** with a matching `access-control-allow-origin`. Preflight from a
  forged origin → **400**.
- `docker compose config` and `caddy validate` both pass.
- `git check-ignore` confirms `deploy/oracle/.env` cannot be committed.

### The failure mode the doc leads with
An Oracle instance has two independent firewalls. `provision.sh` opens the one
inside the VM — inserting the iptables accepts *above* Canonical's final REJECT
rule, since appending them does nothing — but the VCN security list lives in
Oracle's console and is unreachable from the instance. Miss it and there is no
error anywhere: Let's Encrypt cannot reach the HTTP-01 challenge, Caddy retries
quietly, requests from outside time out, and `curl localhost` on the box works
perfectly. `deploy.sh` therefore health-checks from the laptop, not from the
VM, because the localhost check passes in exactly the broken case.

### Still blocked, and on what
- **An Oracle account and an A1 instance.** Signup needs a card for identity
  verification. `Out of host capacity` on A1 is the normal experience, not a
  mistake — retry over days or use an autoscaling Instance Pool. The always-free
  AMD `E2.1.Micro` is not a fallback: 1 GB is below one ingest.
- **The Vercel project** — unchanged. Blocked by the permission mode this
  session, and by a connector-role 403 in the previous one.


## Addendum — the frontend is deployed (2026-09-17)

Live: **<https://aletheia-rag.vercel.app>** — Vercel project `aletheia-rag` in
*Tanishq's projects*, deployed from the working tree with the CLI rather than a
git link, because this account has `push` but not `admin` on
`AdityaShukla06/Aletheia` and installing the Vercel GitHub App needs `admin`.

Oracle and Cloudflare assets removed this session: `deploy/oracle/`,
`docs/oracle-deploy.md`, `worker/`, `wrangler.jsonc`, `worker-configuration.d.ts`,
`backend/{package.json,package-lock.json,tsconfig.json}`,
`docs/cloudflare-deploy.md`, plus 223 MB of orphaned wrangler `node_modules`.
**R2 stayed** — `storage.py`, `test_storage_r2.py`, `test_backfill_r2.py` and
`backfill_r2.py` are Cloudflare *storage*, which Cloud Run depends on.

### Four bugs between "builds locally" and "works deployed"
1. **`.vercelignore` excluded `colab/`**, which `app/api/training/[task]/route.ts`
   reads at runtime. Next traces the directory, but tracing only sees uploaded
   files, so every notebook download would have 503'd with a clean build log.
2. **`.vercelignore` excluded `backend/`**, which `lib/experiments.ts` imports six
   model/history JSON files from at build time. This one failed the Vercel build
   outright. `backend/` is now excluded child by child, because gitignore
   semantics cannot re-include a file under an excluded parent.
3. **`framework: null`** on the project — `vercel project add` creates a bare
   project, so Next built perfectly and the platform served the output as a static
   directory: `public/` assets 200, every route a platform `NOT_FOUND`. Fixed by
   committing `vercel.json` with `{"framework": "nextjs"}`.
4. **`middleware.ts` is deprecated in Next 16** and is executed unbundled on
   Vercel — it died on its first `import`. Migrated to `proxy.ts` (`git mv`, so
   history follows); Clerk 7.9.3 accepts either filename on Next 16+.

### Verified against the live URL
- `/` → **200**, renders, `<title>Aletheia — grounded research intelligence</title>`.
- `/sign-in` → **200**, Clerk widget mounts with Google SSO and email, no console
  errors. Carries Clerk's **Development mode** badge, which is expected: a Clerk
  *production* instance needs a custom domain for the CNAME and cannot be issued
  for a `*.vercel.app` subdomain.
- `/library`, `/training`, `/api/training/relevance` → **307** to
  `/sign-in?redirect_url=…`. The allow-list in `proxy.ts` is enforced in
  production, and the return URL is carried.
- Build reproduced against **exactly** the file set Vercel receives (98 files,
  2 MB — git's ignore rules plus `.vercelignore`, applied with git's own matcher).
  That build is what proved bug 2 fixed and the three notebooks still traced.

### Still blocked, and on what
- **Cloud Run needs an open billing account.** `01A552-CEFF0A-9DDD0F` is still
  `open: false`. The two projects that *do* have billing —
  `collective-odyssey-lr5vm`, `forward-icon-lfq84` — are Google-managed sandboxes:
  the roles held on the first are free-tier only (`runSaasUserFreeTier`,
  `firebaseUserFreeTier`, `cloudSqlUserFreeTier`) with no `run.admin`, and the
  second denies `getIamPolicy` outright. Neither can host this service.
- **An R2 API token** still has to be minted by hand.
- `scripts/deploy_cloudrun.sh` is otherwise ready: `bash -n` clean, all three
  LOAD-BEARING flags present, and it already prints the follow-up command with
  the now-real `https://aletheia-rag.vercel.app` origin.


## Addendum — the memory ceiling was wrong, and measured (2026-09-18)

Every host decision in this file rested on "2 GB is the smallest that works",
which was reasoned about rather than measured. It is wrong. Measured inside the
deploy image on `linux/amd64` against one real 75-page paper (112 chunks):

| stage | batch=4 | batch=32 (as shipped) |
|---|---|---|
| both ONNX models loaded, idle | 451 MB | 453 MB |
| + parsed + 99 figures/tables extracted | 766 MB | 765 MB |
| + all chunks embedded | 1786 MB | 4227 MB |
| + one `search_top_k=20` rerank while resident | **2326 MB** | **4787 MB** |

Two mechanisms, neither of which is the user's data — the 6.8 MB PDF accounts
for 6.8 MB:

* **ONNX Runtime sizes its CPU arena to the widest batch it ever sees and keeps
  it.** The cost is a permanent ceiling, not a spike: 1399 MB after the first
  pass, then 1409, then 1409 across three passes.
* **The reranker holds a second arena of its own**, independent of the
  embedder's — the last row is one rerank adding ~540 MB to a finished ingest.

Confirmed by enforcement rather than by reading peaks, with
`docker run --memory N --memory-swap N` against the deploy image:

| | 2 GiB | 4 GiB |
|---|---|---|
| `EMBED_BATCH_SIZE=4` | OOM-killed (137) | **survives** |
| `EMBED_BATCH_SIZE=32` | OOM-killed (137) | OOM-killed (137) |

**Neither fix is sufficient alone.** `deploy_cloudrun.sh` would have been
OOM-killed on its first real ingest at `2Gi`, and lowering the batch without
raising memory would still have been killed.

### Changed
- `embed_batch_size` is a setting (default 4), not the hardcoded
  `EMBED_BATCH_SIZE = 32` in `ingestion.py`. It is a memory ceiling, so it has
  to be reachable per host.
- `deploy_cloudrun.sh`: `MEMORY` `2Gi` -> `4Gi`. `--cpu 1` stays; Cloud Run
  allows up to 4 GiB on one vCPU, so this sits exactly at that ceiling and
  going higher would force `--cpu 2`.
- `render.yaml`: `plan: standard` (2 GB) -> `pro` (4 GB), with the measurement
  replacing the claim it contradicts.
- `docs/cloudrun-deploy.md`: new sizing section; cost corrected to ~$0.09/hr
  (~$6/mo light use) for 1 vCPU + 4 GiB.
- `test_ingestion.py` guards both failure modes — re-hardcoding the width, and
  raising the default without re-measuring. Proven non-vacuous: it fails under
  `EMBED_BATCH_SIZE=32`.

413 passed, 13 skipped, 0 failed.

### Caveat
Measured on one paper. Figure extraction scales with figure count (99 here) and
the embedding arena with batch width, not paper length, so a 300-page paper
should land close to this — but that is reasoning, not a measurement.

### What this changes about hosting
Free 512 MB tiers were never borderline: the two models alone are 451 MB, before
a request. Oracle's always-free ARM VM (24 GB) and HF Spaces (16 GB) both have
comfortable headroom; Cloud Run needs `4Gi`, which is not free.


## Addendum — Oracle always-free A1 as a second host (2026-09-18)

The genuinely free host. Built fresh: the earlier Oracle attempt was never
committed to any branch, so nothing was recoverable from history.

### Why it needed no arm64 work at all
The expected cost was porting the image to aarch64. There was none. Every native
wheel the API pins publishes an aarch64 build and was verified to import in the
built image — `onnxruntime` 1.30.0, `pymupdf` 1.28.2, `numpy` 2.5.2, `psycopg`,
`cryptography`, `tokenizers`, `reportlab`. `docker build --platform linux/arm64`
against the unmodified Dockerfile produces the same 1.21 GB image with both ONNX
models baked (271 MB at `/opt/fastembed-cache`), and it builds natively on an
Apple-silicon laptop.

arm64 memory is slightly *lower* than amd64 — 451 MB idle and 2278 MB peak
against 451/2326 — so the Cloud Run sizing work carries over unchanged.

### Added
`backend/deploy/oracle/{docker-compose.yml,Caddyfile,provision.sh,deploy.sh,backup.sh,.env.example}`
and `backend/docs/oracle-deploy.md`. Plus `backend/.dockerignore`, which did not
exist: the build context was 482 MB, of which 375 MB was the local `.venv` of the
wrong architecture. It matters here because `deploy.sh` builds on the instance,
so the context crosses a network first.

### Decisions
- **`STORAGE_BACKEND=local`, not R2.** R2 exists because Cloud Run hands a woken
  container a fresh in-memory filesystem. A VM has a real disk, so the reason
  evaporates, and local needs no credential minted by hand. R2 stays a one-line
  switch. `backup.sh` covers what this makes fragile.
- **No Redis.** With one API container the in-process rate-limit windows *are*
  the real cluster-wide counters. `/health` reports
  `rate_limiter: in-memory (per process)`, so the choice is visible.
- **One instance**, for `recover_stranded_jobs()` — the same constraint as
  `--max-instances 1` on Cloud Run, for the same reason.
- **`API_DOMAIN` from the environment**, so a DuckDNS subdomain and an owned
  domain both work with no file edit. This removed the need to decide up front.
- **CORS in FastAPI only, never in Caddy.** Two layers setting
  `Access-Control-Allow-Origin` makes browsers reject the response, and it reads
  like an application bug.

### Verified by running it, not by inspection
The whole stack was brought up locally — Caddy uses its internal CA for
`localhost`, so TLS, the proxy and the API were exercised together without
touching Let's Encrypt.

- `/health` through TLS: `status: ok`, database ok, storage ok.
- HTTP → HTTPS is a 308.
- `curl http://localhost:8000/health` from the host **fails**: the API publishes
  no port, so TLS is not something a client can skip by accident.
- CORS: an allowed origin gets exactly **one** `Access-Control-Allow-Origin`;
  `https://evil.example` gets none.
- A real 2.1 MB paper uploaded through the proxy reached `ready` with its title
  extracted, and its bytes landed on the `papers` volume.
- **The test that justifies local storage:** after `docker compose down` then
  `up`, `POST /papers/{id}/reprocess` re-read the PDF from the volume and
  completed. This is the exact sequence that fails on an ephemeral filesystem.
- Upload limits layer as intended: 52 MB → the API's own
  `400 {"detail":"File is 51.0 MB, over the 50 MB limit."}`; 67 MB → Caddy's
  bare `413`.
- `backup.sh` resolved the real volume name, archived, and verified with
  `tar tzf` before pruning.
- Live memory after a real ingest: 955 MiB of the 6 GiB limit.
- Caddyfile passes `caddy validate`; all three shell scripts pass `bash -n`.

### A bug this found in my own work
`env_file: .env` makes `docker compose config` fail whenever `.env` is absent —
which is deliberate on a laptop. So `deploy.sh`'s pre-flight validation would
have failed for every developer, every time. Fixed with
`env_file: [{path: .env, required: false}]`; the explicit remote check in
`deploy.sh` gives a better message than compose's anyway.

### The operational trap worth knowing before committing to this host
Oracle may reclaim an Always Free instance idle over 7 days: 95th-percentile CPU
below 20%, network below 20%, **and, on A1 only, memory below 20%**. This service
idles at 451 MB of 24 GB — 1.9% — so it trips all three. Reclamation stops the
instance rather than destroying it, but restarting needs A1 capacity, which is
exactly what is scarce.

The fix is upgrading to Pay As You Go: Always Free resources stay free and PAYG
accounts are exempt. It cannot be solved with a keepalive — the memory criterion
is 20% of 24 GB, so a ping would need to hold ~4.8 GB forever.

### Also corrected
- `.vercelignore` excludes `backend/deploy/` — `backend/` is excluded child by
  child, so a new subdirectory is uploaded to Vercel until it is named.
- `cloudrun-deploy.md` no longer claims Cloud Run is "the only deployment path",
  and its two remaining `2 GiB` / `$0.08` figures now match the 4 GiB fix.
- `backend/README.md` lists both hosts and the 4 GB floor.

### Not done, and why
Nothing was deployed. Every remaining step needs an Oracle account, an A1
instance and a hostname — none of which exist yet, and two of which need a card
for identity verification. The VCN ingress rules and the DNS A record are console
work that no script can do; `provision.sh` prints both with the instance's public
IP rather than pretending otherwise.

413 passed, 13 skipped, 0 failed.


---

## Addendum — no backend host at all (2026-09-22)

The user's call, and the right one: the frontend is already deployed, so rather
than paying for or administering a fourth candidate host, run the backend in
Docker locally and let the deployed site reach it over a tunnel.

### Why this works here and would not work everywhere

`lib/api.ts:29` reads `NEXT_PUBLIC_API_URL`, and the `NEXT_PUBLIC_` prefix means
the value is inlined into the bundle and fetched **by the visitor's browser**.
Verified that every consumer of `lib/api` is a client component — no server
component, route handler or `proxy.ts` path calls the API. So Vercel's servers
never need a route to the backend; only an open browser tab does. Had the app
proxied API calls server-side, "deployed frontend, local backend" would have
been impossible without exposing the machine to Vercel's infrastructure.

### Tunnel, not `http://localhost:8000`

Pointing the deployed bundle straight at loopback was considered and rejected.
It works on exactly one machine in Chrome or Firefox: `localhost` resolves to
*the visitor's* machine, Safari blocks `http://localhost` from an HTTPS page
outright, and current Chrome gates public→local requests behind a Local Network
Access prompt. A tunnel costs one terminal and works for everyone.

Cloudflare over ngrok, for a specific reason rather than a preference: ngrok's
free tier serves a browser interstitial, and while the `ngrok-skip-browser-warning`
header would clear it for `fetch`, `assetUrl` (`lib/api.ts:334`) is consumed as
an `<img>`/iframe `src` and cannot send headers — every figure in the paper
viewer would render ngrok's warning page. The cost is that a quick tunnel's
hostname changes on restart, and `NEXT_PUBLIC_*` is build-time inlined, so each
session needs a Vercel redeploy. A named tunnel on an owned domain removes that.

### Removed
`render.yaml`, `backend/deploy/oracle/` (6 files), `backend/docs/cloudrun-deploy.md`,
`backend/docs/oracle-deploy.md`, `backend/scripts/deploy_cloudrun.sh`.

The R2 storage backend **stays**: it is off by default (`STORAGE_BACKEND=local`),
tested, and untouched by the local path. Deleting it would have meant editing
`services/storage.py` and `config.py` to remove a working, covered code path —
churn with no benefit, since nothing runs it unless it is switched on.

### Changed so the topology actually works
- `backend/docker-compose.yml` no longer pins `CORS_ORIGINS`. It was hardcoded
  to `http://localhost:3000` under `environment:`, which overrides `env_file` —
  so adding the Vercel origin would have meant editing a tracked file every
  session. Unset, the API's own default is the same string, so local dev is
  unchanged and `.env` becomes the single place to edit.
- `.vercelignore` drops `backend/deploy/` and points at the new doc.
- `backend/README.md` replaces the two-host section with the local-Docker note
  and keeps the 4 GB floor, which is the reason there is no host.
- `docs/DEPLOYMENT.md` rewritten end to end: it described Render, named
  `middleware.ts` (renamed to `proxy.ts` in 939a4c1) and documented a
  `render.yaml` that no longer exists.

### Verified
`npm run typecheck` clean, `docker compose config` valid, backend suite green
(425 passed, 1 skipped — the 13 skips in the previous run were services being
down, not tests being disabled). The compose change was verified in the
container rather than by reading the file: `docker compose run --rm --no-deps
--entrypoint sh api -c 'echo $CORS_ORIGINS'` now prints the `.env` value, which
the removed `environment:` entry would have overridden. No reference to a deleted file remains outside the
historical sections of this file and `lessons.md`.

### Not done, and why
The tunnel was not raised and Vercel was not reconfigured. Both need decisions
only the user can make — whether to expose the machine right now, and which
Clerk instance the deployed site should use — and `docs/DEPLOYMENT.md` insists
authentication is on *before* a tunnel opens, because a tunnelled API with
`ALLOW_UNAUTHENTICATED=true` is an open database.
