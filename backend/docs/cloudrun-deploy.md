# Deploying the Aletheia API to Google Cloud Run

The same container that runs under docker-compose runs here. Routing, auth,
CORS and rate limiting stay in FastAPI, so the service behaves identically in
both; only where the bytes live and who assigns the port differ. Cloud Run sets
`$PORT`, which the `Dockerfile` CMD already honours.

`scripts/deploy_cloudrun.sh PROJECT_ID [REGION]` does everything below in one
run. Read this first anyway — three of its flags are compensating for specific
properties of this application, and changing them silently breaks ingestion.

## Why storage is R2 here and not a disk

Cloud Run gives a container a fresh filesystem on every cold start, so
`STORAGE_BACKEND=local` would leave every `papers` row in Neon pointing at a PDF
that no longer exists. And the filesystem it does give you is an **in-memory
tmpfs**, so uploaded PDFs would be charged against the same 2 GiB the ONNX
models need. Object storage is not an optimisation here; it is the only correct
setting.

R2 rather than Cloud Storage because `storage.py` already implements it,
`test_storage_r2.py` already covers it, and R2 charges nothing for egress. The
bucket `aletheia-papers` already exists.

## One-time prerequisites

1. **An open billing account.** Cloud Run's Always Free tier still requires
   one. A new billing account also carries $300 of 90-day credit, which covers
   this service many times over.
2. **An R2 API token.** Cloudflare dashboard → R2 → *Manage API tokens* →
   *Create API token*, **Object Read & Write** scoped to `aletheia-papers`. It
   shows an Access Key ID, a Secret Access Key, and an endpoint of the form
   `https://<account-id>.r2.cloudflarestorage.com`. The secret is shown once.

## Secrets

Six, held in Secret Manager and mounted by name — the deploy script never sees
a value, so it is safe to commit and safe to re-run.

```bash
PROJECT=your-project-id
printf %s 'postgresql://...?sslmode=require' | gcloud secrets create aletheia-database-url        --data-file=- --project $PROJECT
printf %s 'https://amazed-heron-68.clerk.accounts.dev' | gcloud secrets create aletheia-clerk-issuer --data-file=- --project $PROJECT
printf %s 'AIza...'                          | gcloud secrets create aletheia-gemini-key           --data-file=- --project $PROJECT
printf %s 'https://<account-id>.r2.cloudflarestorage.com' | gcloud secrets create aletheia-r2-endpoint --data-file=- --project $PROJECT
printf %s '<access key id>'                  | gcloud secrets create aletheia-r2-access-key-id     --data-file=- --project $PROJECT
printf %s '<secret access key>'              | gcloud secrets create aletheia-r2-secret-access-key --data-file=- --project $PROJECT
```

`printf %s` rather than `echo`: a trailing newline inside `R2_SECRET_ACCESS_KEY`
produces a SigV4 signature that fails on every request, and the error R2
returns for it says nothing about whitespace.

`OPENAI_API_KEY` is deliberately absent. `OPENAI_ENABLED` is `"false"` and a
disabled provider is never called. To switch vendors, add the secret, add it to
`--set-secrets`, and flip both `*_ENABLED` flags — exactly one may be true.

Grant the runtime service account read access once:

```bash
PROJNUM=$(gcloud projects describe $PROJECT --format 'value(projectNumber)')
for s in database-url clerk-issuer gemini-key r2-endpoint r2-access-key-id r2-secret-access-key; do
  gcloud secrets add-iam-policy-binding aletheia-$s --project $PROJECT \
    --member "serviceAccount:$PROJNUM-compute@developer.gserviceaccount.com" \
    --role roles/secretmanager.secretAccessor
done
```

## Three flags that are load-bearing

* **`--no-cpu-throttling`.** This is the one that matters. An upload returns
  201 immediately and finishes extraction in a FastAPI `BackgroundTasks`
  (`app/api/papers.py:65`). Cloud Run's *default* billing mode throttles CPU to
  roughly zero the instant the response is sent, so that background work would
  stall mid-ingest — the paper would sit at `running` forever, and the next
  cold start would mark it failed. This flag bills for instance lifetime
  instead of request time, and it is the only mode in which this application is
  correct. It is not a performance tuning knob.

* **`--min-instances 0`.** Follows directly from the flag above: with lifetime
  billing, a warm instance is a billed instance. Zero is what keeps this inside
  the free tier.

* **`--max-instances 1`.** `recover_stranded_jobs()` (`main.py:48`) fails every
  job left `running` on startup, assuming the process holding it died. A second
  instance booting would fail the first one's in-flight ingestion.

## Why there is no keepalive ping

The obvious trick for a scale-to-zero host is to ping `/health` every few
minutes so a real user never meets a cold start. It is the wrong trick here.
Keeping the instance alive under `--no-cpu-throttling` turns every one of the
month's 720 hours into a billed hour (~$0.08 each, so ~$55), and dropping the
flag to make pinging cheap is exactly what breaks ingestion. There is no
setting where the ping is both cheap and safe.

So cold starts are accepted instead. What one actually costs: the image is
1.21 GB but Cloud Run streams layers, and both ONNX models are baked into an
image layer by the `FASTEMBED_CACHE_PATH` step in the `Dockerfile` — verified
to load in 0.5s with `--network none` rather than downloading 150 MB in the
request path. The floor is the ~25s model load. Expect roughly 30–40s on the
first request after an idle period, then normal latency until it scales down.

If that becomes unacceptable, the honest fix is a host that does not scale to
zero — not a ping that trades correctness for warmth. On Cloud Run that means
`--min-instances 1`, and the cost section below is what it would bill.

## What this actually costs, honestly

Cloud Run's always-free allowance is 2M requests, 180,000 vCPU-seconds and
360,000 GiB-seconds per month. **Whether it applies to this service is not
something the official docs settle.** Google enumerates that allowance under
*request-based* billing, and "2 million requests per month" is not a quantity
instance-based billing even charges for; secondary sources claim the tier still
applies when CPU is always allocated. This deployment needs
`--no-cpu-throttling`, so it sits on the wrong side of that ambiguity. Do not
plan around it being free.

Plan around the $300 / 90-day trial credit instead, which is unambiguous and
covers this many times over. At 1 vCPU + 2 GiB under instance-based rates the
service costs roughly **$0.08 per hour that an instance is alive** — and with
`--min-instances 0` an instance lives from its cold start until roughly 15
minutes after its last request, not 24 hours a day. Light demo use lands around
$5/month once the credit runs out; continuous traffic is about $55.

Set a budget alert on day one rather than discovering this at the end of a
month:

```bash
gcloud billing budgets create --billing-account "$BILLING_ACCOUNT" \
  --display-name "aletheia" --budget-amount 10USD \
  --threshold-rule percent=0.5 --threshold-rule percent=0.9
```

`us-central1` is the default region for exactly one reason: the free allowance,
where it applies at all, is documented in North American terms, and the 1 GB of
free outbound transfer is specified "from North America". The cost is latency —
roughly 250 ms of extra round trip from India. If this is being demoed to
people there and the bill is already accepted, deploy to `asia-south1` instead:

```bash
./scripts/deploy_cloudrun.sh PROJECT_ID asia-south1
```

Cloud Run is the only deployment path this repo supports. Earlier revisions
also carried Cloudflare Containers and an Oracle always-free ARM VM; both were
dropped, and `tasks/todo.md` keeps the reasoning that ruled each of them out.

## After the frontend exists

`CORS_ORIGINS` and `CLERK_AUTHORIZED_PARTIES_CSV` are not set by the deploy
script, so a half-finished deploy fails closed in the browser rather than
accepting every origin. Once the Vercel URL is known, set both to it exactly —
no trailing slash:

```bash
gcloud run services update aletheia-api --region asia-south1 \
  --update-env-vars CORS_ORIGINS=https://aletheia-rag.vercel.app,CLERK_AUTHORIZED_PARTIES_CSV=https://aletheia-rag.vercel.app
```

Then set `NEXT_PUBLIC_API_URL` on Vercel to the Cloud Run URL and redeploy the
frontend.

## Moving the existing library into R2

Switching `STORAGE_BACKEND` changes where the API *looks* for a paper's bytes,
not where they are. Any paper ingested while storage was `local` still has its
PDF on the old disk, so the rows have to be walked and the objects uploaded
before the reader stops 404ing. `scripts/backfill_r2.py` does that, and refuses
to upload bytes that contradict the digest recorded on the row.

Run it in this order — status, then a dry run, then the real one, then verify:

```bash
npm run storage:to-r2 -- --status
npm run storage:to-r2 -- --dry-run
npm run storage:to-r2
npm run storage:to-r2 -- --verify
```

## Checking it

```bash
curl https://aletheia-api-<hash>-el.a.run.app/health
```

`storage` reports `ok` only after a real round trip to the bucket: a HEAD on a
missing key returns 404 when the credentials are good and 403 when they are
not, which is what separates "reachable and authorised" from "misconfigured".

The test that actually matters here is the background one. Upload a PDF, watch
the paper reach `ready` rather than sticking at `running`, and confirm it
survives a scale-to-zero — wait ~20 minutes, then reopen the paper. A reader
that 404s means storage fell back to a filesystem that no longer exists.

```bash
gcloud run services logs read aletheia-api --region asia-south1 --limit 100
```
