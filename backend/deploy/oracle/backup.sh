#!/usr/bin/env bash
#
# Back up the paper library. Run ON the instance:
#
#     ./backup.sh                  # write a new archive, prune old ones
#     ./backup.sh /mnt/elsewhere   # write somewhere other than the default
#
# WHAT THIS COVERS, AND WHAT IT DOES NOT.
#
# STORAGE_BACKEND=local means uploaded PDFs and extracted figures live only on
# this instance's `papers` volume. Nothing else has a copy, and `papers` rows in
# Neon point at keys inside it -- so losing the volume leaves a library that
# lists every paper and can open none of them. That is what this protects.
#
# It does NOT back up the database: that is Neon, which has its own backups and
# point-in-time restore. Restoring this archive against a much newer database is
# therefore fine (some rows point at bytes that are missing), but restoring a
# much newer archive against an older database is not (bytes with no rows).
#
# For a cron entry, see docs/oracle-deploy.md.

set -euo pipefail

DEST="${1:-/opt/aletheia/backups}"
KEEP="${KEEP:-7}"
STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="${DEST}/papers-${STAMP}.tar.gz"

mkdir -p "$DEST"

# Resolve the real volume name rather than assuming it. Compose prefixes it with
# the project name, and guessing "aletheia_papers" breaks the moment someone
# runs the stack from a differently named directory.
VOLUME="$(cd "$STACK_DIR" && docker compose config --format json \
	| python3 -c 'import json,sys; print(json.load(sys.stdin)["volumes"]["papers"].get("name","aletheia_papers"))' 2>/dev/null || echo aletheia_papers)"

if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
	echo "volume '$VOLUME' does not exist -- is the stack up?" >&2
	exit 1
fi

echo "==> archiving volume '$VOLUME' -> $ARCHIVE"
# A throwaway container with the volume mounted read-only. Reading the volume
# through Docker rather than poking at /var/lib/docker directly is what makes
# this work regardless of the storage driver.
docker run --rm \
	-v "${VOLUME}:/data:ro" \
	-v "${DEST}:/backup" \
	alpine:3 \
	tar czf "/backup/$(basename "$ARCHIVE")" -C /data .

# Verify the archive is readable before trusting it and pruning older ones. An
# unverified backup is a guess, and `tar tzf` is cheap.
echo "==> verifying"
if ! docker run --rm -v "${DEST}:/backup:ro" alpine:3 \
	tar tzf "/backup/$(basename "$ARCHIVE")" >/dev/null; then
	echo "archive did not verify; keeping every older backup" >&2
	exit 1
fi

SIZE="$(du -h "$ARCHIVE" | cut -f1)"
echo "==> ok: $ARCHIVE ($SIZE)"

echo "==> pruning to the newest $KEEP"
ls -1t "${DEST}"/papers-*.tar.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
	echo "    removing $(basename "$old")"
	rm -f "$old"
done

cat <<EOF

To restore into a fresh volume:

    docker compose down
    docker volume rm ${VOLUME}
    docker volume create ${VOLUME}
    docker run --rm -v ${VOLUME}:/data -v ${DEST}:/backup:ro alpine:3 \\
      tar xzf /backup/$(basename "$ARCHIVE") -C /data
    docker compose up -d
EOF
