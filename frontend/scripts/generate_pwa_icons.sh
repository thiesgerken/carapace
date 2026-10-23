#!/usr/bin/env bash

set -euo pipefail

if ! command -v magick >/dev/null 2>&1; then
  echo "magick is required to generate frontend/public PWA icons" >&2
  exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
frontend_root=$(cd "$script_dir/.." && pwd)
icon_svg="$frontend_root/public/icon.svg"

# Rasterize above the largest output size before downsampling.
magick -background none -density 288 "$icon_svg" -resize 192x192 "$frontend_root/public/pwa-192x192.png"
magick -background none -density 288 "$icon_svg" -resize 512x512 "$frontend_root/public/pwa-512x512.png"
magick -background none -density 288 "$icon_svg" -resize 180x180 "$frontend_root/public/apple-touch-icon.png"

echo "Generated PWA icons from $icon_svg"
