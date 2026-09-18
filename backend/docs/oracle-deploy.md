# Deploying the Aletheia API to an Oracle Cloud always-free instance

This is the only genuinely free host for this API. Everything below was run
against the real image on `linux/arm64`; where a number appears it was measured,
not estimated.

Why this host rather than the alternatives, in one table:

| host | RAM | free? | why not |
|---|---|---|---|
| **Oracle A1** | 24 GB | yes, permanently | — |
| Cloud Run | 4 GiB | no | needs `--no-cpu-throttling`, so outside the documented free tier (~$6/mo) |
| Cloudflare Containers | — | no | Containers are `N/A` on the free plan; needs Workers Paid at $5/mo |
| Render free / any 512 MB tier | 0.5 GB | yes | the two ONNX models are 451 MB **before a request arrives** |
| Fly.io | — | no | free allowance withdrawn |

`docs/cloudrun-deploy.md` remains accurate and is the better choice if you want
a managed host and are willing to pay ~$6/month. This one is free and you own
the box.

## What you get, and the two ways it bites

Oracle's Always Free tier includes 4 Ampere (aarch64) OCPUs and 24 GB of memory
to divide across A1 instances, 200 GB of block storage, and 10 TB/month of
egress. For this service that is enormous headroom — it peaks at 2.28 GB.

**The capacity problem.** `Out of host capacity` on instance creation is the
normal experience, not a fault. A1 is oversubscribed in popular regions. Retry,
try another availability domain in the same region, or pick a quieter region —
your home region is fixed at signup, so choose it with this in mind.

**The idle-reclamation problem, which matters more.** Oracle may reclaim an
Always Free compute instance that looks idle over a 7-day window, defined as
95th-percentile CPU below 20%, network below 20%, **and — on A1 shapes only —
memory below 20%**. A demo API on a 24 GB box idles around 451 MB, which is 1.9%
of memory and close to 0% CPU. It will trip all three.

Reclamation *stops* the instance rather than destroying it, and you can restart
it if the shape is available in your region — which is exactly when A1 capacity
is scarce, so "restartable" is weaker comfort than it sounds.

The real fix is to upgrade the account to Pay As You Go. Always Free resources
stay free on a PAYG account, and PAYG accounts are not subject to idle
reclamation. Do not try to solve this by keeping the box busy: the memory
criterion is 20% of 24 GB, so a keepalive would have to hold ~4.8 GB of RAM
forever to satisfy it.

## Prerequisites

1. **An Oracle Cloud account.** Signup requires a card for identity
   verification. Always Free resources are not charged against it.
2. **An A1 instance.** `VM.Standard.A1.Flex`, 1–4 OCPU and 6–24 GB. Ubuntu 24.04
   or Oracle Linux 9 both work; `provision.sh` handles either. Add your SSH
   public key at creation — there is no password login.
3. **A hostname that resolves to the instance's public IP.** The browser calls
   this API cross-origin from the Vercel page, and an HTTPS page cannot call a
   plain-HTTP API, so a real certificate is not optional.

   A free [DuckDNS](https://www.duckdns.org) subdomain is the cheapest path that
   works: it is on the Public Suffix List, so Let's Encrypt issues for it
   without sharing a rate limit with strangers. A domain you own works
   identically — `API_DOMAIN` is read from the environment, so neither is
   hardcoded anywhere.

   Avoid `nip.io` / `sslip.io` here. They are not on the Public Suffix List, so
   every user of them shares one Let's Encrypt rate limit, and it is frequently
   exhausted.

## The mistake that costs an afternoon

**An Oracle instance sits behind two independent firewalls.**

`provision.sh` opens the one *on* the instance — iptables, firewalld or ufw,
whichever that image uses. The second is the **VCN security list** in the Oracle
console, and nothing running on the instance can see it, change it, or warn you
about it.

If you skip it: `docker compose ps` shows both containers healthy, the API
answers on localhost, Caddy waits forever for an ACME challenge that never
arrives, and the service is unreachable from the internet with no error anywhere
that explains why.

> Console → Networking → Virtual Cloud Networks → *your VCN* → Subnets → *your
> subnet* → Security Lists → Default Security List → **Add Ingress Rules**
>
> | Source | Protocol | Destination port |
> |---|---|---|
> | `0.0.0.0/0` | TCP | 80 |
> | `0.0.0.0/0` | TCP | 443 |

Port 80 is not just for the HTTP→HTTPS redirect: it is where the Let's Encrypt
HTTP-01 challenge arrives. Closing it means the certificate is never issued.

## Deploying

```bash
# 1. On the instance, once.
scp backend/deploy/oracle/provision.sh ubuntu@<ip>:~
ssh ubuntu@<ip> 'sudo bash provision.sh'      # installs docker, opens the local firewall
```

Then do the two things it prints and cannot do itself: the VCN ingress rules
above, and the DNS A record. Confirm DNS from your laptop before going further —
Caddy asks for a certificate on startup and failed challenges are rate limited:

```bash
dig +short aletheia-api.duckdns.org
```

```bash
# 2. On the instance, once: the real configuration.
ssh ubuntu@<ip>
mkdir -p /opt/aletheia/backend/deploy/oracle && cd /opt/aletheia/backend/deploy/oracle
# (after the first deploy.sh run the example is already here)
cp .env.example .env && $EDITOR .env
```

Fill in `API_DOMAIN`, `DATABASE_URL`, `CLERK_ISSUER`, `CORS_ORIGINS`,
`CLERK_AUTHORIZED_PARTIES_CSV` and `GEMINI_API_KEY`. `deploy.sh` never copies a
local `.env` up, because a dev one points at a dev database and shipping that
silently is the worst kind of deploy bug — so on a first run, sync once, let the
missing-`.env` check stop you, write it, and run again.

```bash
# 3. From your laptop, every time.
./backend/deploy/oracle/deploy.sh ubuntu@<ip>
```

That rsyncs the tree, builds on the instance, waits for the healthcheck, and
then checks `https://$API_DOMAIN/health` **from your laptop** — the only test
that exercises both firewalls, DNS and the certificate at once, which are
precisely the things nothing on the instance can observe.

The image is built on the instance rather than pushed to it. Four Ampere cores
build it faster than a 1.21 GB image uploads from a home connection, and it
means no registry, no login, and no cross-architecture build to get wrong.

## After the first deploy

Point the frontend at it and let it back in:

```bash
# On the instance, in .env: CORS_ORIGINS and CLERK_AUTHORIZED_PARTIES_CSV must be
# the Vercel origin exactly, no trailing slash. Then:
docker compose up -d
```

On Vercel set `NEXT_PUBLIC_API_URL=https://aletheia-api.duckdns.org` and
redeploy.

## Why the stack is shaped this way

**Two containers, and the API publishes no port.** Caddy owns 80/443; the API is
reachable only over the compose network. Verified: with the stack up,
`curl http://localhost:8000/health` from the host fails, so there is no
plaintext path a client can take by accident.

**CORS lives in FastAPI, not in Caddy.** Two layers setting
`Access-Control-Allow-Origin` makes browsers reject the response outright, and
the failure reads like an application bug. Verified through the proxy: an
allowed origin gets exactly one header, and `https://evil.example` gets none.

**No Redis.** With `REDIS_URL` empty the rate limiter keeps its windows in
process, and with exactly one API container those windows *are* the real
cluster-wide counters rather than an approximation. `/health` reports
`rate_limiter: in-memory (per process)` so the choice is visible rather than
assumed.

**One instance, and that is a correctness constraint.**
`recover_stranded_jobs()` fails every job still marked `running` at startup, on
the assumption the process holding it died. A second container booting would
fail the first one's in-flight ingestion and mark a paper broken while someone
was reading it. Scaling out means fixing that first, and then adding Redis.

**`STORAGE_BACKEND=local`, unlike Cloud Run.** R2 exists in this codebase
because Cloud Run hands a woken container a fresh in-memory filesystem; a VM has
a real disk, so the reason evaporates. PDFs live on the `papers` named volume —
named, not a bind mount, so replacing the source tree cannot take the library
with it.

Verified rather than assumed: a real 2.1 MB paper was uploaded through TLS,
reached `ready`, then survived `docker compose down` followed by `up`, after
which `POST /papers/{id}/reprocess` re-read its bytes from the volume and
completed. That is the exact sequence that fails on an ephemeral filesystem.

To move to R2 later, set `STORAGE_BACKEND=r2` plus the four `R2_*` values and
run `npm run storage:to-r2` once. `storage.py` already implements both.

**Upload limits are layered deliberately.** Caddy's `max_size` is 60 MB, above
the API's own 50 MB, so a plausible over-size file gets the API's own message
and only an absurd one hits the blunt proxy error. Measured through the proxy:

| upload | result |
|---|---|
| 52 MB | `400 {"detail":"File is 51.0 MB, over the 50 MB limit."}` |
| 67 MB | `413`, empty body, from Caddy |

Setting Caddy's ceiling *to* 50 MB would replace the first row with the second.

## Memory

`EMBED_BATCH_SIZE=4` and `mem_limit: 6g`. Measured in this image on aarch64,
ingesting one 75-page paper (112 chunks):

| stage | resident |
|---|---|
| both ONNX models loaded, idle | 451 MB |
| + parsed, + 99 figures/tables extracted | 766 MB |
| + all chunks embedded | 1742 MB |
| + one `search_top_k=20` rerank while resident | **2278 MB** |

Live after a real ingest through the proxy: 955 MiB of the 6 GiB limit.

Unlike the 4 GiB Cloud Run service, this host has room to raise the batch width
— 24 GB against a 2.28 GB peak. It is a background job that returns before the
work starts, though, so a faster ingest changes nothing a user perceives. If you
do raise `EMBED_BATCH_SIZE`, raise `mem_limit` in `docker-compose.yml` first:
ONNX Runtime sizes its arena to the widest batch it ever sees and keeps it, so
batch 32 needs more than 4 GB. See `docs/cloudrun-deploy.md` for that table.

Do not raise `mem_limit` above roughly 20 GB. The point of the limit is not to
save memory; it is that a runaway container hits a predictable OOM instead of
letting the kernel choose a victim, and on a single-purpose box the victim it
chooses is often `sshd`.

## Backups

`STORAGE_BACKEND=local` means the PDFs exist on exactly one disk, and `papers`
rows in Neon point into it — so losing the volume leaves a library that lists
every paper and can open none of them. The database itself is Neon's problem,
and Neon has its own backups and point-in-time restore.

```bash
ssh ubuntu@<ip> '/opt/aletheia/backend/deploy/oracle/backup.sh'
```

It resolves the real volume name rather than guessing it, archives through a
throwaway container, **verifies the archive with `tar tzf` before pruning older
ones**, keeps the newest `KEEP` (default 7), and prints the restore command.
Daily at 03:15 UTC:

```bash
ssh ubuntu@<ip> 'crontab -l 2>/dev/null; echo "15 3 * * * /opt/aletheia/backend/deploy/oracle/backup.sh >> /var/log/aletheia-backup.log 2>&1"' | ssh ubuntu@<ip> 'crontab -'
```

An archive on the same instance survives a bad deploy, not a lost instance. Copy
it off — `rsync` to your laptop, or to R2, which is free and already has a bucket.

## Checking it

```bash
curl https://aletheia-api.duckdns.org/health
```

`storage` reports `ok` only after a real round trip, so it distinguishes
"reachable and authorised" from "misconfigured".

The test that actually matters is the background one, because it is the only one
that fails silently: upload a PDF, confirm it reaches `ready` rather than
sticking at `running`, restart the stack, and reopen it.

```bash
ssh ubuntu@<ip> 'cd /opt/aletheia/backend/deploy/oracle && docker compose logs -f --tail 100 api'
ssh ubuntu@<ip> 'cd /opt/aletheia/backend/deploy/oracle && docker compose logs -f caddy'   # certificate trouble
```

## When it breaks

| symptom | cause |
|---|---|
| containers healthy, unreachable from outside | the VCN security list — first thing to check, every time |
| Caddy retries ACME forever | port 80 closed in the VCN, or DNS not pointing here yet |
| `Out of host capacity` | A1 is full in that availability domain; retry or change AD |
| instance stopped on its own | idle reclamation; restart it, then upgrade to PAYG |
| browser shows a CORS error | `CORS_ORIGINS` is not the Vercel origin exactly, or has a trailing slash |
| paper stuck at `running` | look at `docker compose logs api`; a container restart mid-ingest leaves it for `recover_stranded_jobs()` to fail on the next boot |
| rules gone after a reboot | `provision.sh` persists them; if it was interrupted, re-run it — it is idempotent |
