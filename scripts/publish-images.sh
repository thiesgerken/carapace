#!/usr/bin/env bash
set -euo pipefail
: "${REGISTRY_OWNER:?Set the GHCR owner}"
: "${1:?Supply at least one image tag}"

for path in dist/*.tar.gz; do
  image=$(basename "$path" .tar.gz)
  archive="docker-archive:$path"
  test "$(skopeo inspect "$archive" | jq -r .Architecture)" = amd64
  for tag in "$@"; do
    # CI verifies archive provenance; image signing is outside this publication contract.
    skopeo --insecure-policy copy --format oci "$archive" "docker://ghcr.io/${REGISTRY_OWNER}/${image}:${tag}"
  done
done
