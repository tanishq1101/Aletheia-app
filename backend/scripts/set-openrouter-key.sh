#!/usr/bin/env bash
#
# Secret box for OPENROUTER_API_KEY.
#
# Reads the key from the terminal with echo OFF and writes it straight into
# .env. The key is never printed, never passed as an argument (argv is visible
# to `ps`), and never enters shell history. Only a masked fingerprint is shown
# so you can confirm the right value landed.
#
#   ./scripts/set-openrouter-key.sh           prompt, save, then verify
#   ./scripts/set-openrouter-key.sh --check   verify what is already in .env
#   ./scripts/set-openrouter-key.sh --clear   remove the stored key
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
VAR="OPENROUTER_API_KEY"

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
green(){ printf '\033[32m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

# --- helpers ----------------------------------------------------------------

current_key() {
  [ -f "$ENV_FILE" ] || return 0
  # Cut on the first '=' only; keys can legitimately contain '='.
  grep -m1 "^${VAR}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true
}

fingerprint() {
  # Enough to identify the key, not enough to use it.
  local key="$1"
  printf '%s… (%d chars)' "${key:0:11}" "${#key}"
}

write_key() {
  local key="$1"
  [ -f "$ENV_FILE" ] || { red "No .env at $ENV_FILE — copy .env.example first."; exit 1; }

  # Write via a private temp file, then move into place, so a failure halfway
  # through cannot leave .env truncated or world-readable.
  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/env.XXXXXX")"
  chmod 600 "$tmp"

  if grep -q "^${VAR}=" "$ENV_FILE"; then
    # Not sed: the key can contain '/' and '&', which sed would interpret.
    # Not `awk -v` either -- that processes backslash escapes in the value, so
    # a key containing "\e" would be written as "e" and fail authentication
    # with no visible cause. ENVIRON passes the bytes through untouched.
    RI_KEY_VALUE="$key" awk -v var="$VAR" \
      'BEGIN{FS=OFS="="} $1==var && !done {print var "=" ENVIRON["RI_KEY_VALUE"]; done=1; next} {print}' \
      "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    printf '%s=%s\n' "$VAR" "$key" >> "$tmp"
  fi

  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

verify_key() {
  local key="$1"
  command -v curl >/dev/null || { dim "curl not found — skipping verification."; return 0; }

  printf 'Verifying against OpenRouter… '
  local response http_code body
  # Key travels in a header, never in the URL (URLs get logged).
  response="$(curl -sS -w '\n%{http_code}' \
    -H "Authorization: Bearer ${key}" \
    https://openrouter.ai/api/v1/key 2>&1 || true)"
  http_code="$(printf '%s' "$response" | tail -n1)"
  body="$(printf '%s' "$response" | sed '$d')"

  case "$http_code" in
    200)
      green "OK"
      # Surface limit/usage if jq is around; it is not required.
      if command -v jq >/dev/null; then
        printf '  label:     %s\n' "$(printf '%s' "$body" | jq -r '.data.label // "—"')"
        printf '  usage:     $%s\n' "$(printf '%s' "$body" | jq -r '.data.usage // 0')"
        printf '  limit:     %s\n' "$(printf '%s' "$body" | jq -r 'if .data.limit == null then "none (pay as you go)" else "$" + (.data.limit|tostring) end')"
      fi
      return 0
      ;;
    401) red "REJECTED — OpenRouter says that key is not valid."; return 1 ;;
    *)   red "FAILED (HTTP ${http_code})"
         printf '%s\n' "$body" | head -3
         return 1 ;;
  esac
}

model_name() {
  grep -m1 '^OPENROUTER_MODEL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true
}

# --- modes ------------------------------------------------------------------

case "${1:-}" in
  --clear)
    write_key ""
    green "Cleared ${VAR}. Answering will now return 503 until a key is set."
    exit 0
    ;;
  --check)
    key="$(current_key)"
    if [ -z "$key" ]; then
      red "${VAR} is empty in .env."
      exit 1
    fi
    printf 'Stored key: %s\n' "$(fingerprint "$key")"
    verify_key "$key"
    exit $?
    ;;
  -h|--help)
    sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

# --- prompt -----------------------------------------------------------------

# Read from the terminal directly, so this still works when stdin is a pipe.
if [ ! -r /dev/tty ]; then
  red "No terminal available to read a secret from."
  dim  "Run this in an interactive terminal — the whole point is that the key"
  dim  "is typed, not passed as an argument or piped in."
  exit 1
fi

existing="$(current_key)"
if [ -n "$existing" ]; then
  printf 'A key is already stored: %s\n' "$(fingerprint "$existing")"
  printf 'Replace it? [y/N] '
  read -r reply < /dev/tty
  case "$reply" in [yY]*) ;; *) dim "Left unchanged."; exit 0 ;; esac
fi

cat <<'EOF'

  ┌─────────────────────────────────────────────────────────────┐
  │  OpenRouter API key                                         │
  │                                                             │
  │  Get one at https://openrouter.ai/keys                      │
  │  Input is hidden. Nothing is echoed, logged, or committed.   │
  └─────────────────────────────────────────────────────────────┘

EOF

printf '  Paste key: '
IFS= read -rs key < /dev/tty
printf '\n\n'

# Strip whitespace a paste can drag along.
key="$(printf '%s' "$key" | tr -d '[:space:]')"

if [ -z "$key" ]; then
  red "Nothing entered — .env unchanged."
  exit 1
fi

if [ "${key:0:6}" != "sk-or-" ]; then
  printf 'That does not look like an OpenRouter key (they start "sk-or-").\n'
  printf 'Save it anyway? [y/N] '
  read -r reply < /dev/tty
  case "$reply" in [yY]*) ;; *) red "Not saved."; exit 1 ;; esac
fi

write_key "$key"
green "Saved to .env — $(fingerprint "$key")"
dim   ".env is chmod 600 and git-ignored."
echo

if verify_key "$key"; then
  echo
  green "Ready. Model: $(model_name)"
  dim   "Restart the API to pick up the new key, then run the live tests:"
  dim   "  cd apps/api && ../../.venv/bin/python -m pytest tests/test_llm_openrouter.py -v"
else
  echo
  red "The key was saved but did not verify. Fix it with:"
  dim "  ./scripts/set-openrouter-key.sh"
  exit 1
fi
