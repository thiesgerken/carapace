"""Auth module tests (no LLM tokens needed)."""

from __future__ import annotations

import pytest

from carapace.auth import get_token


def test_get_token_from_env(monkeypatch):
    monkeypatch.setenv("CARAPACE_TOKEN", "test-token-123")
    assert get_token() == "test-token-123"


def test_get_token_strips_whitespace(monkeypatch):
    monkeypatch.setenv("CARAPACE_TOKEN", "  my-token  ")
    assert get_token() == "my-token"


def test_get_token_raises_when_missing(monkeypatch):
    monkeypatch.delenv("CARAPACE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CARAPACE_TOKEN"):
        get_token()


def test_get_token_raises_when_empty(monkeypatch):
    monkeypatch.setenv("CARAPACE_TOKEN", "")
    with pytest.raises(RuntimeError, match="CARAPACE_TOKEN"):
        get_token()
