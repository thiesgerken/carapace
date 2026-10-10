"""Render the sources of a week or month digest into the text the digest model reads."""

from __future__ import annotations

# Bump whenever the rendered digest material changes for the same sources. Like the extraction
# input version, a bump marks digests outdated; it must never make them stale (the coverage hash
# depends only on which source records a digest consumed, not on how they were rendered).
DIGEST_INPUT_FORMAT_VERSION = 1
