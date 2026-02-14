"""Tests for security engine helpers (no LLM tokens needed)."""

from carapace.security.engine import _trigger_is_always


def test_trigger_is_always():
    assert _trigger_is_always("always") is True
    assert _trigger_is_always("  Always  ") is True
    assert _trigger_is_always("ALWAYS") is True


def test_trigger_is_not_always():
    assert _trigger_is_always("when agent reads external data") is False
    assert _trigger_is_always("") is False
