from __future__ import annotations

import secrets
from pathlib import Path

TOKEN_FILE = "server.token"


def ensure_token(data_dir: Path) -> str:
    """Return the bearer token, generating one on first call."""
    token_path = data_dir / TOKEN_FILE
    if token_path.exists():
        return token_path.read_text().strip()
    token = secrets.token_urlsafe(32)
    token_path.write_text(token + "\n")
    return token
