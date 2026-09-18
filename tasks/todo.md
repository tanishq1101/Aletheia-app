# Aletheia — redeploy: Vercel frontend + Cloud Run backend

Replaces the paused deployment (`aletheia-rag.vercel.app` → `DEPLOYMENT_PAUSED`,
owned by an account we cannot reach). Frontend moves to a fresh Vercel project
in *Tanishq's projects*; the API moves off Render to Google Cloud Run.

> **Status (2026-09-17).** The frontend is **live** at
> <https://aletheia-rag.vercel.app>. Cloud Run is the one remaining host and is
> blocked only on billing — see the closing addendum.
>
> The Cloudflare Containers and Oracle ARM sections below are **superseded**:
> both hosts were evaluated, built and then removed from the tree. They are kept
> because they record why each one lost, which is the part worth not repeating.

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
