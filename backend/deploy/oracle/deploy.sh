#!/usr/bin/env bash
#
# Deploy the current working tree to a provisioned Oracle instance.
# Run from your laptop, from anywhere in the repo:
#
#     ./backend/deploy/oracle/deploy.sh ubuntu@203.0.113.10
#
# The image is built ON the instance rather than pushed to it. An A1 shape has
# 4 Ampere cores and 24 GB, so it builds this faster than a 1.21 GB image
# uploads over a domestic connection -- and it means no registry, no login, and
# no cross-architecture build to get wrong.
#
# Safe to re-run: this is the normal way to ship a change.

set -euo pipefail

TARGET="${1:?usage: deploy.sh user@host   (e.g. ubuntu@203.0.113.10)}"
REMOTE_DIR=/opt/aletheia
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/../.." && pwd)"

log() { printf '\n==> %s\n' "$*"; }

command -v rsync >/dev/null || { echo "rsync is required on this machine" >&2; exit 1; }

# --- refuse to ship a broken tree -------------------------------------------
# Cheap, and it is the difference between finding a syntax error here and
# finding it as a container that restart-loops behind a healthcheck.
log "checking the compose file parses"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
	(cd "$HERE" && API_DOMAIN=validate.invalid docker compose config -q)
fi

log "syncing source to ${TARGET}:${REMOTE_DIR}"
# --delete so a file deleted locally is deleted there too; without it the
# instance accumulates modules that no longer exist and imports still resolve.
#
# .env is excluded and NEVER overwritten: the instance's copy holds the real
# secrets, and the local one holds dev values pointing at a dev database.
rsync -az --delete \
	--exclude '.venv/' \
	--exclude '__pycache__/' \
	--exclude '.pytest_cache/' \
	--exclude 'storage/' \
	--exclude 'datasets/' \
	--exclude '.env' \
	--exclude '.env.*' \
	"$BACKEND/" "${TARGET}:${REMOTE_DIR}/backend/"

# --- the instance must already hold its own .env -----------------------------
if ! ssh "$TARGET" "test -f ${REMOTE_DIR}/backend/deploy/oracle/.env"; then
	cat >&2 <<EOF

No .env on the instance yet. Create it there once, from the example:

    ssh ${TARGET}
    cd ${REMOTE_DIR}/backend/deploy/oracle
    cp .env.example .env
    \$EDITOR .env        # DATABASE_URL, API_DOMAIN, CLERK_ISSUER, CORS_ORIGINS, GEMINI_API_KEY

It is deliberately not copied from your laptop: your local .env points at a dev
database and would be shipped to production silently.
EOF
	exit 1
fi

log "building and starting on the instance"
# --build every time: the source just changed, and a deploy that reuses a stale
# image is the kind of thing you debug for an hour.
ssh "$TARGET" "cd ${REMOTE_DIR}/backend/deploy/oracle && docker compose up -d --build --remove-orphans"

log "waiting for the API to become healthy"
# The compose healthcheck already gates Caddy on this; polling here is so a
# failed deploy exits non-zero at the point of failure instead of looking fine.
for attempt in $(seq 1 60); do
	state="$(ssh "$TARGET" "cd ${REMOTE_DIR}/backend/deploy/oracle && docker compose ps api --format '{{.Health}}'" 2>/dev/null || true)"
	case "$state" in
		healthy)
			log "api is healthy"
			break
			;;
		unhealthy)
			echo "api went unhealthy. Last 60 lines:" >&2
			ssh "$TARGET" "cd ${REMOTE_DIR}/backend/deploy/oracle && docker compose logs --tail 60 api" >&2
			exit 1
			;;
	esac
	if [ "$attempt" -eq 60 ]; then
		echo "api did not become healthy within 5 minutes. Last 60 lines:" >&2
		ssh "$TARGET" "cd ${REMOTE_DIR}/backend/deploy/oracle && docker compose logs --tail 60 api" >&2
		exit 1
	fi
	sleep 5
done

DOMAIN="$(ssh "$TARGET" "grep -E '^API_DOMAIN=' ${REMOTE_DIR}/backend/deploy/oracle/.env | cut -d= -f2-" | tr -d '\r')"

log "checking TLS from the outside"
# From here, not from the instance: this is the only check that exercises both
# firewalls, DNS, and the certificate at once -- the three things that fail
# silently and that nothing on the instance can observe.
if curl -fsS --max-time 20 "https://${DOMAIN}/health" >/dev/null 2>&1; then
	echo
	curl -fsS "https://${DOMAIN}/health"
	echo
	log "deployed: https://${DOMAIN}"
else
	cat >&2 <<EOF

The containers are healthy but https://${DOMAIN}/health is not reachable from
here. In order of likelihood:

  1. The VCN security list still does not allow 80 and 443. This is the usual
     answer and nothing on the instance can tell you so.
  2. DNS for ${DOMAIN} does not point at the instance yet:  dig +short ${DOMAIN}
  3. Caddy has not finished the ACME challenge. Watch it:
       ssh ${TARGET} 'cd ${REMOTE_DIR}/backend/deploy/oracle && docker compose logs -f caddy'
EOF
	exit 1
fi
