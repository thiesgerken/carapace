from __future__ import annotations

import os


def get_token() -> str:
    """Return the bearer token from the CARAPACE_TOKEN environment variable."""
    token = os.environ.get("CARAPACE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("CARAPACE_TOKEN environment variable is required but not set")
    return token
