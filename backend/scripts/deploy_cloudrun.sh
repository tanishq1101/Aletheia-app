#!/usr/bin/env bash
#
# Deploy the Aletheia API to Google Cloud Run.
#
#   ./scripts/deploy_cloudrun.sh PROJECT_ID [REGION]
#
# Idempotent: re-running deploys a new revision over the same service. Nothing
# here is secret — every credential is read from Secret Manager by name, and
# the names are created once by `--set-secrets` below.
#
# Read docs/cloudrun-deploy.md before changing any of the flags marked
# LOAD-BEARING; each one is compensating for something specific in this app.

set -euo pipefail

PROJECT="${1:?usage: deploy_cloudrun.sh PROJECT_ID [REGION]}"
REGION="${2:-us-central1}"
SERVICE="aletheia-api"
REPO="aletheia"

# Measured, not reasoned about. Loading both ONNX models costs 708 MB before a
# request arrives; ingesting one 75-page paper then peaks at ~1.8 GB with
# EMBED_BATCH_SIZE=4 (figure extraction and the embedding arena are the two
# spikes). 2Gi -- the value this script used to pass -- left no headroom above
# that, and with the old hardcoded batch of 32 the peak was 3.7 GB and the
# first real ingest would have been OOM-killed. 4Gi is the smallest size with
# room for the measured peak plus a concurrent query.
MEMORY="4Gi"
CPU="1"

echo "==> project=$PROJECT region=$REGION service=$SERVICE"

gcloud config set project "$PROJECT" >/dev/null

echo "==> enabling APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT"

echo "==> ensuring Artifact Registry repo"
gcloud artifacts repositories describe "$REPO" \
  --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 || \
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location "$REGION" --project "$PROJECT" \
  --description "Aletheia API images"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:$(date +%Y%m%d-%H%M%S)"

# Built by Cloud Build, not locally: the image must be linux/amd64 and building
# that on an Apple Silicon machine means QEMU emulation for a pip install that
# compiles nothing but downloads ~150 MB of ONNX weights. Cloud Build does it
# natively in a couple of minutes.
echo "==> building $IMAGE"
gcloud builds submit . --tag "$IMAGE" --project "$PROJECT" --region "$REGION"

echo "==> deploying"
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --memory "$MEMORY" \
  --cpu "$CPU" \
  `# LOAD-BEARING: recover_stranded_jobs() (main.py:48) fails every job left` \
  `# 'running' on startup, assuming the process holding it died. A second` \
  `# instance booting would fail the first one's in-flight ingestion.` \
  --max-instances 1 \
  `# LOAD-BEARING: uploads return 201 and finish extraction in a FastAPI` \
  `# BackgroundTasks (papers.py:65). Cloud Run's default request-based` \
  `# billing throttles CPU to ~0 the moment the response is sent, which` \
  `# would stall that work mid-ingest. This bills for instance lifetime` \
  `# instead, which is the only mode where this app is correct.` \
  --no-cpu-throttling \
  `# LOAD-BEARING: with --no-cpu-throttling an idle instance is billed, so it` \
  `# must be allowed to scale to zero. This is what keeps the bill inside the` \
  `# free tier, and it is why there is no keepalive ping -- see the doc.` \
  --min-instances 0 \
  `# The research agent's combined report is the long pole; llm_timeout is` \
  `# 180s per call and it makes several.` \
  --timeout 900 \
  --set-env-vars "STORAGE_BACKEND=r2,R2_BUCKET=aletheia-papers,R2_REGION=auto,ALLOW_UNAUTHENTICATED=false,OPENAI_ENABLED=false,GEMINI_ENABLED=true,CHROMA_ENABLED=false,RATE_LIMIT_ENABLED=true,LOG_LEVEL=INFO" \
  --set-secrets "DATABASE_URL=aletheia-database-url:latest,CLERK_ISSUER=aletheia-clerk-issuer:latest,GEMINI_API_KEY=aletheia-gemini-key:latest,R2_ENDPOINT_URL=aletheia-r2-endpoint:latest,R2_ACCESS_KEY_ID=aletheia-r2-access-key-id:latest,R2_SECRET_ACCESS_KEY=aletheia-r2-secret-access-key:latest"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
echo
echo "==> deployed: $URL"
echo "==> health:"
curl -fsS "$URL/health" || echo "  health check failed -- see: gcloud run services logs read $SERVICE --region $REGION"
echo
echo "Next: set CORS_ORIGINS and CLERK_AUTHORIZED_PARTIES_CSV to the Vercel origin:"
echo "  gcloud run services update $SERVICE --region $REGION \\"
echo "    --update-env-vars CORS_ORIGINS=https://aletheia-rag.vercel.app,CLERK_AUTHORIZED_PARTIES_CSV=https://aletheia-rag.vercel.app"
