#!/usr/bin/env bash

set -euo pipefail

if ! command -v magick >/dev/null 2>&1; then
  echo "magick is required to generate frontend/public/favicon.ico" >&2
  exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
frontend_root=$(cd "$script_dir/.." && pwd)
icon_svg="$frontend_root/public/icon.svg"
favicon_ico="$frontend_root/public/favicon.ico"

# Supersampling keeps the small shell seams crisp on the final pixel grid.
magick -background none -density 144 "$icon_svg" \
  \( -clone 0 -resize 48x48 \) \
  \( -clone 0 -resize 32x32 \) \
  \( -clone 0 -resize 16x16 \) \
  -delete 0 \
  "$favicon_ico"

echo "Generated $favicon_ico from $icon_svg"
