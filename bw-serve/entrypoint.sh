#!/bin/sh
set -e

PORT="${BW_SERVE_PORT:-8087}"

if [ -n "$BW_SERVER_URL" ]; then
  bw config server "$BW_SERVER_URL"
  echo "bw: configured server $BW_SERVER_URL"
fi

if [ -n "$BW_CLIENTID" ] && [ -n "$BW_CLIENTSECRET" ]; then
  bw login --apikey
  echo "bw: API key login successful"
  BW_SESSION=$(bw unlock --passwordenv BW_MASTER_PASSWORD --raw)
  export BW_SESSION
else
  BW_SESSION=$(bw login --passwordenv BW_MASTER_PASSWORD --raw)
  export BW_SESSION
  echo "bw: password login successful"
fi

bw unlock --check
echo "bw: vault unlocked and verified"

echo "bw: starting serve on 127.0.0.1:${PORT}"
exec bw serve --port "$PORT" --hostname 127.0.0.1
