# Deploying Aletheia

**Default: everything on Vercel.** The Next.js app and the FastAPI backend ship
in one Vercel project. The browser calls `https://<site>/api/py/...`; a rewrite
in `next.config.ts` sends that to the Python function `api/index.py`, which runs
the unchanged app from `backend/apps/api`. There is no tunnel to keep alive, no
second origin and no CORS, and Clerk's session cookie reaches the API, so figure
images authenticate too.

The backend was written for one long-lived process with about 2 GB of RAM. A
serverless function is neither of those things, so `api/index.py` changes the
defaults for exactly the parts that assumed one:

| Assumption | Long-lived container (docker compose) | Vercel function |
|---|---|---|
| Embeddings | fastembed / ONNX in process, ~1.4 GB | `EMBEDDING_PROVIDER` = the enabled LLM vendor's `/embeddings` (OpenAI `text-embedding-3-small` or Gemini `gemini-embedding-001`, both at 512 dims) |
| Reranking | local cross-encoder | `RERANKER_PROVIDER=none`, which keeps retrieval order |
| Ingestion | background task after the 201 | `INGESTION_MODE=inline`, finished before the response, because a frozen instance would strand it |
| File storage | local disk volume | `STORAGE_BACKEND=postgres` (table `stored_objects`), or `r2` when R2 keys are set |
| Uploads > 4.5 MB | one multipart POST | sent in 4 MB parts and joined server-side, since Vercel rejects larger request bodies |
| Startup recovery | fails every `running` job | only jobs idle > 15 min (`STRANDED_JOB_AFTER_SECONDS`) |
| Migrations | `scripts/migrate.py` in the container CMD | applied on each instance's first request, under an advisory lock |
| Vector index | Chroma + pgvector | pgvector only (`CHROMA_ENABLED=false`) |

Every one of those is an ordinary environment variable, and setting it
explicitly on Vercel overrides the default.

**What that costs.** Two honest trade-offs. Retrieval loses the cross-encoder
pass, so the evidence ranking is the bi-encoder's alone. And each indexed chunk
and each question is one embedding call to the vendor, which costs a fraction
of a cent per paper with `text-embedding-3-small` and is free within Gemini's
free tier.

## Setting it up (one time, about 5 minutes)

All of this is in the Vercel dashboard for the `aletheia-rag` project.

1. **Database.** Storage → *Create Database* → **Neon** (free tier) → connect it
   to this project for Production and Preview. That injects `DATABASE_URL`.
   pgvector is available on Neon; the first request creates every table. Any
   other Postgres with pgvector works too: set `DATABASE_URL` yourself, using
   the pooled endpoint if there is one. Supabase's injected `POSTGRES_URL` is
   also picked up.
2. **AI key.** Settings → Environment Variables:
   * `OPENAI_ENABLED=true` and `OPENAI_API_KEY=sk-…`, **or**
   * `OPENAI_ENABLED=false`, `GEMINI_ENABLED=true`, `GEMINI_API_KEY=…`

   The same key embeds documents and answers questions.
3. **Auth.** Nothing to add. The backend derives `CLERK_ISSUER` from the
   `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` the frontend already has (the key encodes
   the instance's domain). Set `CLERK_ISSUER` explicitly only to override it.
4. **Point the frontend at it.** On Vercel, `NEXT_PUBLIC_API_URL` is ignored,
   so a leftover value cannot bypass the bundled backend. The one thing that
   still can is the `apiBaseUrl` item in the `aletheia-runtime` Edge Config,
   which holds the old tunnel URL: delete it. With it gone, `/api/config`
   answers `{"apiBaseUrl":"/api/py","source":"bundled"}`.
5. **Redeploy** production so the function picks up the new variables.

### Verify

```bash
APP=https://aletheia-rag.vercel.app
curl -s $APP/api/config               # "source":"bundled"
curl -s $APP/api/py/health            # status ok, database ok, storage ok (postgres)
curl -s -o /dev/null -w '%{http_code}\n' $APP/api/py/projects   # 401: auth is on
```

Then sign in, upload a PDF, and ask a question. If a route answers
`503 Backend is not ready: …`, the message names what is missing: no database,
no `CLERK_ISSUER`, or a migration that failed.

### Limits worth knowing

* **Function duration is 300 s** (`vercel.json`). Ingesting a long paper and a
  multi-step research-agent run both have to fit inside it. A 12-page, 6 MB
  PDF ingests in a few seconds; a several-hundred-page scan may not.
* **Postgres storage counts against the database quota.** Neon's free tier is
  0.5 GB, which is a few dozen typical papers with their figures. Past that, set
  the `R2_*` variables (`backend/.env.example`) and storage switches to R2
  automatically; `backend/scripts/backfill_r2.py` copies existing files across.
* **Papers indexed by the local model are not searchable here, and vice versa.**
  Every chunk records the model that embedded it, and retrieval only compares
  vectors from the same model. A library moved from the Docker setup needs its
  papers reprocessed (the *Retry* action) after the move.

---

# Alternative: Vercel front end, self-hosted backend over a tunnel

The arrangement this project used before the backend could run on Vercel, and
still the way to run the full local-model stack (fastembed embeddings and the
cross-encoder) behind the deployed site. To use it, set the `apiBaseUrl` item in
Edge Config to the tunnel URL as described below; it takes precedence over the
bundled backend.

Every API call is made **by the visitor's browser** (every consumer of
`lib/api` is a client component), so Vercel's servers never need to reach a
self-hosted backend; only the browser that has the page open does.

The whole arrangement is therefore: **Vercel serves the app → the visitor's
browser calls a tunnel URL → the tunnel reaches port 8000 on the machine
running `docker compose`.**

---

## Why a tunnel rather than `http://localhost:8000`

Setting `NEXT_PUBLIC_API_URL=http://localhost:8000` on Vercel looks like it
should work, and on one machine in one browser it does. It is not worth it:

* `localhost` means *the visitor's own machine*. Anyone who opens the link on
  any other computer gets "Cannot reach the API" on every page.
* Safari blocks an HTTPS page from fetching `http://localhost` outright. Chrome
  and Firefox allow it (loopback counts as a trustworthy origin, so it is not
  mixed content), but recent Chrome gates public→local requests behind a Local
  Network Access permission prompt.

A tunnel costs one terminal window and removes all of that: any browser, any
device, anyone you send the link to.

---

## The order matters

**Turn authentication on before the tunnel goes up.** Not after.

With no `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `proxy.ts` is a no-op by design —
the app is meant to still run for someone who checks the repository out with no
keys — and on a deployment that means every page is public. Harmless while the
API is unreachable. The moment a tunnel makes the API answer from the public
internet, the same configuration is an open database with your Postgres behind
it.

So: Clerk keys on Vercel and `CLERK_ISSUER` + `ALLOW_UNAUTHENTICATED=false` in
`backend/.env` **first**, tunnel second. The API refuses to start with no issuer
unless `ALLOW_UNAUTHENTICATED=true`, which is what makes this order enforceable
rather than merely advisable.

---

## 1. Clerk

The front end and the backend must point at the **same Clerk instance**: the
browser gets a session token from the publishable key, and the API verifies it
against the issuer's JWKS. Mismatch them and every request is a 401 that looks
like a bug.

| Where | Variable | Value |
| --- | --- | --- |
| Vercel | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_…` |
| Vercel | `CLERK_SECRET_KEY` | `sk_…` |
| `backend/.env` | `CLERK_ISSUER` | The Frontend API URL, e.g. `https://clerk.your-domain.com` |
| `backend/.env` | `ALLOW_UNAUTHENTICATED` | `false` |

`CLERK_JWKS_URL` is derived from the issuer, so leave it blank.

A `pk_test_`/`sk_test_` development instance works for a demo — the sign-in card
shows a "Development mode" badge and has usage limits. A production instance is
only needed if this becomes something people actually use.

### The one Clerk setting that is not optional

The default session token carries no `email` or `username` claim, so
`_resolve_user` provisions rows with both columns null. Add a JWT template
(**Sessions → Customize session token**) containing:

```json
{
  "email": "{{user.primary_email_address}}",
  "username": "{{user.username}}"
}
```

The code tolerates their absence, so this is cosmetic until something displays a
user's identity — thirty seconds now versus a confusing blank later.

---

## 2. Start the backend

```bash
cd backend
docker compose up -d
curl -s localhost:8000/health
```

Four containers: the API, Postgres (pgvector), Chroma and Redis. Give the API a
moment on first start — it loads two local ONNX models, 451 MB resident before
a request arrives.

`docker compose` needs ~4 GB available to Docker Desktop. Ingesting one paper
peaks at ~2.3 GB; below that, the first upload gets OOM-killed.

---

## 3. Put a tunnel in front of it

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

It prints a URL like `https://random-words-here.trycloudflare.com`. That is a
public HTTPS endpoint for port 8000 on this machine, free, no account.

**Cloudflare rather than ngrok, for one specific reason.** ngrok's free tier
serves a browser interstitial page before the real response, bypassed by sending
an `ngrok-skip-browser-warning` header. API calls could send it, but
`assetUrl` (`lib/api.ts:334`) is consumed as a plain `<img>`/iframe `src` and
cannot carry headers — so every figure in the paper viewer would render as
ngrok's warning page. Cloudflare has no interstitial. The trade is that a quick
tunnel's URL changes on every restart; ngrok free includes one static domain.

If you own a domain on Cloudflare, a *named* tunnel gives a permanent hostname
and step 4 stops repeating itself. Otherwise budget one redeploy per session.

---

## 4. Introduce the two halves

**Backend** — `backend/.env`, then restart so the API rereads it:

```bash
CORS_ORIGINS=http://localhost:3000,https://aletheia-rag.vercel.app
```

That is the *front end's* origin, not the tunnel's: CORS is about who is allowed
to call, not who is being called. Exact scheme, host and port, no trailing
slash — the browser matches the `Origin` header literally. `docker-compose.yml`
deliberately does not override this value, so `.env` is the only place to edit.

```bash
docker compose up -d --force-recreate api
```

**Vercel** — one command, no redeploy:

```bash
vercel global-config update aletheia-runtime \
  --patch '[{"operation":"update","key":"apiBaseUrl","value":"https://….trycloudflare.com"}]'
```

**No trailing slash** — every call site concatenates a path onto it.

The front end asks `GET /api/config` for this value on each page load, and that
route reads it out of Edge Config per request. Edge Config is the only part of
a Vercel project that can be changed in place: environment variables are bound
to a deployment, so editing one — `NEXT_PUBLIC_API_URL` or any other — still
needs a redeploy before a running lambda sees it. A quick tunnel changes
hostname every time it reconnects, so that used to mean a full no-cache
production rebuild per reconnection. Now it is the line above and a reload.

`NEXT_PUBLIC_API_URL` still exists and is still the fallback, which is what
makes local development unchanged: there is no Edge Config on a laptop, so
`.env.local` remains the single place that says where the API is. `/api/config`
reports which one it used:

```bash
curl -s https://aletheia-rag.vercel.app/api/config
#   {"apiBaseUrl":"https://….trycloudflare.com","source":"edge-config"}
#   source "build" means Edge Config was unreachable or unset and the
#   inlined value is in play — the one state where a redeploy still matters.
```

The store is `aletheia-runtime` (`vercel global-config items aletheia-runtime`
to read it). Its read token lives in the `EDGE_CONFIG` environment variable;
rotating that token *is* an env var change, so it needs a redeploy.

---

## 5. Verify, rather than assume

Each of these has a failure this project has shipped at least once.

```bash
TUNNEL=https://random-words-here.trycloudflare.com
APP=https://aletheia-rag.vercel.app

# The tunnel reaches the API and every dependency is healthy.
curl -s $TUNNEL/health
#   status ok, database ok, storage ok, rate_limiter redis

# Auth is ON. Both must be 401 — not 200, not 500.
curl -s -o /dev/null -w '%{http_code}\n' $TUNNEL/projects
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer nonsense' $TUNNEL/projects

# CORS admits the app and refuses anyone else.
curl -s -I -H "Origin: $APP" $TUNNEL/health | grep -i access-control-allow-origin
curl -s -I -H 'Origin: https://evil.example' $TUNNEL/health | grep -i access-control-allow-origin  # absent

# The deployed bundle is not still pointing at localhost.
curl -s $APP/library | grep -c 'localhost:8000'   # 0

# Protected pages redirect a signed-out visitor instead of serving them.
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' $APP/library   # 307 -> /sign-in?...
```

Then sign in through the browser and confirm the library loads with no "API
offline" badge in the topbar. That badge is the visible symptom of every fault
above.

---

## Afterwards

```bash
# Ctrl-C the cloudflared window, then:
cd backend && docker compose down
```

The deployed site goes back to showing "API offline", which is the honest state:
the backend is a laptop, and the laptop is closed. Data survives in Docker
volumes (`db_data`, `chroma_data`, `source_data`) until you pass `-v`.

**While the tunnel is up, the API is on the public internet.** Clerk is the only
thing standing in front of it. Bring it up for a demo, take it down after.

---

---

## Why the backend can now run on Vercel

Render, Cloudflare Containers, Google Cloud Run and an Oracle always-free A1 VM
were each built out and then removed (the arithmetic is in `tasks/todo.md`).
They failed for the same reason: the service held two ONNX models in memory,
wrote to a disk, and ran ingestion in-process, so it needed ~2–4 GB and
persistent storage, and every free tier is 512 MB and ephemeral.

Those three properties are exactly what the serverless mode replaces: the models
by hosted embeddings and `RERANKER_PROVIDER=none`, the disk by Postgres (or R2)
storage, and the in-process job by inline ingestion. The `Dockerfile` remains
the way to run the original local-model configuration, unchanged, on Render,
Fly.io, Railway or Cloud Run.
