# Deploying Aletheia

Two pieces: the Next.js front end on Vercel, and the FastAPI backend somewhere
that can run a container with a disk. They are separate deployments and each
has to be told where the other is.

The current Vercel deployment serves the front end correctly and cannot do
anything else, because neither of those two things has been configured. This
document is the fix.

---

## The order matters

**Configure Clerk on Vercel before the backend is reachable.** Not after.

Without `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `middleware.ts` is a no-op by
design — the app is meant to still run for someone who checks the repository
out with no keys. On a deployment that means every page is public. Today that
is harmless, because the API it would talk to does not exist. The moment a real
backend answers, the same configuration is an open database.

So:

1. Clerk keys on Vercel, and `CLERK_ISSUER` + `ALLOW_UNAUTHENTICATED=false` on
   the API, **first**.
2. Deploy the API.
3. Point Vercel at it with `NEXT_PUBLIC_API_URL` and redeploy.

The API refuses to start with no issuer unless `ALLOW_UNAUTHENTICATED=true`, so
step 2 fails loudly if step 1 was skipped. That guard is the reason this order
is safe to follow rather than merely advisable.

---

## 1. Clerk: a production instance

The keys currently in use are `pk_test_` / `sk_test_`. Those belong to a
development instance: Clerk prints a console warning that it has "strict usage
limits and should not be used when deploying", the sign-in card shows a
"Development mode" badge, and sessions behave differently from production.

In the Clerk dashboard, create a **production** instance for the domain, enable
the same providers (Google, email, username), and take three values:

| Value | Where to find it |
| --- | --- |
| `pk_live_…` | API keys |
| `sk_live_…` | API keys |
| Frontend API URL, e.g. `https://clerk.your-domain.com` | API keys → Show JWT public key |

That third value is the issuer. Everything else derives from it: the JWKS is
`<issuer>/.well-known/jwks.json`, which the API fetches for itself.

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

The code already tolerates their absence, so this is cosmetic until something
displays a user's identity — but it is thirty seconds now versus a confusing
blank later.

---

## 2. The API on Render

`render.yaml` in the repository root is a Blueprint. Point Render at the repo
(**Blueprints → New Blueprint Instance**) and fill in the four values it marks
`sync: false`.

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | The Neon connection string, including `?sslmode=require` |
| `CLERK_ISSUER` | The Frontend API URL from above |
| `GEMINI_API_KEY` | Google AI Studio key (or use `OPENAI_API_KEY` and set `LLM_PROVIDER=openai`) |
| `OPENAI_API_KEY` | Optional. With both keys set, OpenAI is primary and Gemini is the automatic fallback |

Everything else — CORS, rate limits, storage paths, `ALLOW_UNAUTHENTICATED=false` —
is already in the blueprint.

### Three things the blueprint decides for you

**A persistent disk, and therefore a single instance.** `storage_backend` has
exactly one implementation, `local`. `/health` reports any other value as
"not implemented" and marks the service degraded, so uploaded PDFs must live on
a mounted disk. A disk pins the service to one instance: scaling out requires
implementing the Supabase storage backend first, not raising a number.

**Chroma off, pgvector only.** Retrieval reads Chroma and falls back to
pgvector, and that fallback returns the same chunk ids in the same order with
the same similarity scores to four decimal places — it was tested by stopping
the container mid-session. Running Chroma in production means a second service
and a second disk holding a copy of vectors Neon already stores. The blueprint
has a commented-out service for when there is a measured reason to add it.

**Standard, not Starter.** The image loads two local ONNX models (the embedding
model and the cross-encoder reranker) plus PyMuPDF. Starter's 512 MB will be
killed on the first ingest.

### Not Vercel

The backend cannot go on Vercel. It holds long-lived model objects in memory,
writes to a disk, and runs ingestion jobs in-process — none of which survive a
serverless function. Render, Fly.io, Railway and Cloud Run all work; the
`Dockerfile` binds `$PORT` with a fallback to 8000, so it is portable across
all of them and still runs under `docker compose` unchanged.

---

## 3. Vercel environment variables

**Settings → Environment Variables.** Set all four for Production (and Preview,
if preview deployments should reach the same API).

| Variable | Value | Why |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://aletheia-api.onrender.com` | Where the browser sends API calls. **No trailing slash.** Unset, it falls back to `http://localhost:8000` — which is what the current deployment does, so every visitor's browser tries to call their own machine. It must be `https`: a page served over HTTPS cannot call an `http://` endpoint. |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_…` | Absent, `middleware.ts` is a no-op and every route is public. |
| `CLERK_SECRET_KEY` | `sk_live_…` | Server-side Clerk calls. |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | `/sign-in` | Already the default; set it so a Clerk dashboard change cannot silently redirect users off-site. |
| `NEXT_PUBLIC_CLERK_SIGN_UP_URL` | `/sign-up` | As above. |

`NEXT_PUBLIC_*` variables are inlined into the bundle **at build time**, so
setting them is not enough — Vercel must rebuild. Redeploy after saving, and do
not use "Redeploy with existing Build Cache".

---

## 4. Verify, rather than assume

Run these against the real deployment. Each one has a failure this project has
actually shipped at least once.

```bash
API=https://aletheia-api.onrender.com
APP=https://aletheia-rag.vercel.app

# The API is up and every dependency is healthy.
curl -s $API/health
#   status ok, database ok, storage ok, rate_limiter redis

# Auth is ON. This must be 401, not 200 and not 500.
curl -s -o /dev/null -w '%{http_code}\n' $API/projects            # 401
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer nonsense' $API/projects  # 401

# CORS admits the app and refuses anyone else.
curl -s -I -H "Origin: $APP" $API/health | grep -i access-control-allow-origin
curl -s -I -H 'Origin: https://evil.example' $API/health | grep -i access-control-allow-origin  # absent

# The front end is not calling localhost any more.
curl -s $APP/library | grep -c 'localhost:8000'                   # 0

# Protected pages redirect a signed-out visitor instead of serving them.
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' $APP/library   # 307 -> /sign-in?redirect_url=...
```

Then sign in through the browser and confirm the library loads without the
"API offline" badge. That badge is the visible symptom of the two faults this
document exists to fix.

---

## Cost, honestly

Render Standard is around $25/month and the Redis/Key Value instance adds a few
more. Neon and Clerk both have free tiers that comfortably cover this. The
single largest saving available is dropping Redis: the rate limiter degrades to
per-process counters, which are *exact* for a single instance, and this
deployment is a single instance by virtue of the disk. Remove the `REDIS_URL`
entry and the `aletheia-redis` service and nothing else changes — `/health`
will report `in-memory (per process)` instead of `redis`.
