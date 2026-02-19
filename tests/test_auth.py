"""Auth module tests (no LLM tokens needed)."""

from __future__ import annotations

from pathlib import Path

from carapace.auth import TOKEN_FILE, ensure_token


def test_ensure_token_creates_file(tmp_path: Path):
    token = ensure_token(tmp_path)
    assert len(token) > 20
    assert (tmp_path / TOKEN_FILE).exists()


def test_ensure_token_is_idempotent(tmp_path: Path):
    t1 = ensure_token(tmp_path)
    t2 = ensure_token(tmp_path)
    assert t1 == t2


def test_ensure_token_reads_existing(tmp_path: Path):
    token_path = tmp_path / TOKEN_FILE
    token_path.write_text("my-custom-token\n")
    assert ensure_token(tmp_path) == "my-custom-token"
