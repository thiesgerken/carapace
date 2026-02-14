"""Tests for MockCredentialBroker (no LLM tokens needed)."""

from carapace.credentials import MockCredentialBroker


def test_get_returns_placeholder():
    broker = MockCredentialBroker()
    val = broker.get("api_key")
    assert "api_key" in val
    assert val.startswith("<mock-value-for-")


def test_get_is_cached():
    broker = MockCredentialBroker()
    assert broker.get("secret") is broker.get("secret")


def test_is_approved():
    broker = MockCredentialBroker()
    assert broker.is_approved("key1", ["key1", "key2"]) is True
    assert broker.is_approved("key3", ["key1", "key2"]) is False
