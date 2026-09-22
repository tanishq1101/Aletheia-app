# Running Aletheia: Vercel front end, local backend

The front end is deployed. The backend is not, and is not going to be — it runs
in Docker on a development machine and the deployed site reaches it through a
tunnel.

That sounds like a compromise and mostly is, but it rests on a real property of
this codebase rather than on hope:

```ts
// lib/api.ts:29
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
```

`NEXT_PUBLIC_` means that URL is inlined into the JavaScript bundle and every
call to it is made **by the visitor's browser**. Every consumer of `lib/api` is
a client component; no server component, route handler or `proxy.ts` path ever
fetches the API. So Vercel's servers never need to reach the backend — only
whichever browser has the page open does. Vercel is serving static assets and
nothing more.

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

## Why the backend is not deployed

Not for lack of trying — Render, Cloudflare Containers, Google Cloud Run and an
Oracle always-free A1 VM were each built out and then removed. The arithmetic is
in `tasks/todo.md`. The short version: this service holds two ONNX models in
memory, writes to a disk, and runs ingestion in-process, so it needs ~4 GB and
persistent storage. Every free tier is 512 MB and ephemeral, which cannot run it
at all, and the cheapest host that genuinely fits was ~$6–27/month for something
with no users yet.

The backend is portable when that changes: the `Dockerfile` binds `$PORT` with a
fallback to 8000 and runs unmodified on Render, Fly.io, Railway or Cloud Run.
Vercel is the one host it cannot use — long-lived model objects, disk writes and
in-process jobs do not survive a serverless function.
