#!/bin/sh
set -e

export BW_NOINTERACTION=true

PORT="${BW_SERVE_PORT:-8087}"

# Docker without a TTY often fully buffers stdout, so progress lines do not show in
# `docker compose logs` until flush. Log to stderr (usually unbuffered) and enable tty
# in compose for this service.
log() {
  printf '%s\n' "$*" >&2
}

log "[entrypoint] sidecar starting"

if [ -z "$BW_MASTER_PASSWORD" ]; then
  log "[entrypoint] error: BW_MASTER_PASSWORD is required"
  exit 1
fi

# Ephemeral path on the container writable layer (survives restart, not `compose down`/recreate).
STATE_DIR=/root/.cache/carapace-bw-sidecar
LAST_URL_FILE="$STATE_DIR/last_bw_server_url"

trim() {
  printf '%s' "$1" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

DESIRED=$(trim "$BW_SERVER_URL")
if [ -f "$LAST_URL_FILE" ]; then
  APPLIED=$(trim "$(cat "$LAST_URL_FILE")")
else
  APPLIED="__none__"
fi

if [ "$APPLIED" = "$DESIRED" ]; then
  log "[entrypoint] BW_SERVER_URL unchanged — skipping logout and bw config server"
else
  log "[entrypoint] BW_SERVER_URL changed or first apply — bw logout then reconfigure"
  bw logout 2>/dev/null || true
  if [ -n "$DESIRED" ]; then
    log "[entrypoint] running: bw config server \"$DESIRED\""
    bw config server "$DESIRED"
  else
    log "[entrypoint] BW_SERVER_URL empty — bw config server bitwarden.com (US cloud default)"
    bw config server bitwarden.com
  fi
  mkdir -p "$STATE_DIR"
  tmp="$LAST_URL_FILE.tmp.$$"
  printf '%s' "$DESIRED" >"$tmp" && mv "$tmp" "$LAST_URL_FILE"
  log "[entrypoint] recorded desired server URL in container storage"
fi

if [ -n "$BW_CLIENTID" ] && [ -n "$BW_CLIENTSECRET" ]; then
  log "[entrypoint] login method: API key"
  # `bw login --check` only proves an access token exists. After a failed API-key login the CLI can
  # leave a token with no usable account crypto (TypeError: toWrappedAccountCryptographicState on
  # null — often Vaultwarden older than bw 2026.2.x). Require unlock + unlock --check before reuse.
  reuse_ok=false
  if bw login --check >/dev/null 2>&1; then
    log "[entrypoint] access token present — verifying vault unlock"
    if BW_SESSION=$(bw unlock --passwordenv BW_MASTER_PASSWORD --raw); then
      export BW_SESSION
      if bw unlock --check >/dev/null 2>&1; then
        reuse_ok=true
        log "[entrypoint] reusing existing login (unlocked)"
      else
        log "[entrypoint] unlock check failed — discarding partial session"
      fi
    else
      log "[entrypoint] bw unlock failed — discarding partial session"
    fi
  fi
  if [ "$reuse_ok" != "true" ]; then
    unset BW_SESSION 2>/dev/null || true
    bw logout 2>/dev/null || true
    log "[entrypoint] running: bw login --apikey"
    if ! bw login --apikey; then
      log "[entrypoint] login failed — bw logout and retry once (Vaultwarden vs CLI mismatch often causes TypeError here; upgrade server or pin older @bitwarden/cli)"
      bw logout 2>/dev/null || true
      bw login --apikey
    fi
    log "[entrypoint] unlocking vault"
    BW_SESSION=$(bw unlock --passwordenv BW_MASTER_PASSWORD --raw)
    export BW_SESSION
  fi
elif [ -n "$BW_CLIENTID" ] || [ -n "$BW_CLIENTSECRET" ]; then
  log "[entrypoint] error: need both BW_CLIENTID and BW_CLIENTSECRET for API key login (one is set, the other is empty)"
  exit 1
else
  if [ -z "$BW_EMAIL" ]; then
    log "[entrypoint] error: set BW_EMAIL for password login, or set both BW_CLIENTID and BW_CLIENTSECRET for API key login"
    exit 1
  fi
  log "[entrypoint] login method: password for ${BW_EMAIL}"
  reuse_ok=false
  if bw login --check >/dev/null 2>&1; then
    log "[entrypoint] access token present — verifying vault unlock"
    if BW_SESSION=$(bw unlock --passwordenv BW_MASTER_PASSWORD --raw); then
      export BW_SESSION
      if bw unlock --check >/dev/null 2>&1; then
        reuse_ok=true
        log "[entrypoint] reusing existing login (unlocked)"
      else
        log "[entrypoint] unlock check failed — discarding partial session"
      fi
    else
      log "[entrypoint] bw unlock failed — discarding partial session"
    fi
  fi
  if [ "$reuse_ok" != "true" ]; then
    unset BW_SESSION 2>/dev/null || true
    bw logout 2>/dev/null || true
    log "[entrypoint] running: bw login <email> --passwordenv BW_MASTER_PASSWORD --raw"
    if ! BW_SESSION=$(bw login "$BW_EMAIL" --passwordenv BW_MASTER_PASSWORD --raw); then
      log "[entrypoint] login failed — bw logout and retry once"
      bw logout 2>/dev/null || true
      BW_SESSION=$(bw login "$BW_EMAIL" --passwordenv BW_MASTER_PASSWORD --raw)
    fi
    export BW_SESSION
  fi
  export BW_SESSION
  log "[entrypoint] login/unlock finished (session key in BW_SESSION)"
fi

log "[entrypoint] running: bw unlock --check"
bw unlock --check
log "[entrypoint] vault unlocked"

log "[entrypoint] status (non-fatal if this errors):"
bw --pretty status 2>&1 || true

log "[entrypoint] running: bw serve --port $PORT --hostname 127.0.0.1"
exec bw serve --port "$PORT" --hostname 127.0.0.1
