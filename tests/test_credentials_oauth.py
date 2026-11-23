"""OAuth state blobs: Carapace refreshes them and hands out only the access token."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from carapace.credentials.oauth import (
    NotOAuthStateError,
    OAuthStateRefusedError,
    access_token,
    is_oauth_state,
    refuse_oauth_state,
)
from carapace.credentials.protocol import CredentialBackendError

_BASE_BLOB = {"token_url": "https://issuer.example.com/token", "client_id": "cid", "refresh_token": "rt"}


class _FakeVault:
    def __init__(self, value: dict | str):
        self.value = value if isinstance(value, str) else json.dumps(value)
        self.written: str | None = None

    async def fetch(self, vault_path: str, kind: str = "password") -> str:
        return self.value

    async def write(self, vault_path: str, value: str) -> None:
        self.written = value


def _token_endpoint(*, status: int = 200, payload: dict | None = None):
    resp = MagicMock(status_code=status, text=json.dumps(payload or {}))
    resp.json = MagicMock(return_value=payload or {})
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return patch("carapace.credentials.oauth.httpx.AsyncClient", MagicMock(return_value=cm)), client


def test_a_blob_is_a_json_object_with_token_url_and_refresh_token() -> None:
    assert is_oauth_state(json.dumps(_BASE_BLOB))
    assert not is_oauth_state('{"token_url": "https://issuer.example.com/token"}')
    assert not is_oauth_state("s3cret")


async def test_a_blob_is_refused_and_other_values_pass() -> None:
    with pytest.raises(OAuthStateRefusedError, match="--access-token"):
        await refuse_oauth_state(_FakeVault(_BASE_BLOB), "demo/oauth")
    await refuse_oauth_state(_FakeVault("s3cret"), "demo/api-key")


async def test_a_missing_access_token_is_refreshed_and_written_back() -> None:
    vault = _FakeVault(_BASE_BLOB)
    endpoint, client = _token_endpoint(payload={"access_token": "AT", "expires_in": 3600, "refresh_token": "rt2"})

    with endpoint:
        token = await access_token(vault, "demo/oauth", refresh=False)

    assert token == "AT"
    client.post.assert_awaited_once()
    written = json.loads(vault.written or "")
    assert (written["access_token"], written["refresh_token"]) == ("AT", "rt2")
    assert written["expires_at"] > time.time()


async def test_a_fresh_token_is_returned_without_refresh_unless_forced() -> None:
    vault = _FakeVault({**_BASE_BLOB, "access_token": "cached", "expires_at": time.time() + 9999})
    endpoint, client = _token_endpoint(payload={"access_token": "new"})

    with endpoint:
        assert await access_token(vault, "demo/oauth", refresh=False) == "cached"
        client.post.assert_not_awaited()
        assert await access_token(vault, "demo/oauth", refresh=True) == "new"


async def test_an_expiring_token_is_refreshed() -> None:
    vault = _FakeVault({**_BASE_BLOB, "access_token": "old", "expires_at": time.time() + 10})
    endpoint, _ = _token_endpoint(payload={"access_token": "fresh", "expires_in": 3600})

    with endpoint:
        assert await access_token(vault, "demo/oauth", refresh=False) == "fresh"


async def test_a_failed_refresh_raises() -> None:
    endpoint, _ = _token_endpoint(status=400, payload={"error": "invalid_grant"})

    with endpoint, pytest.raises(CredentialBackendError, match="refresh"):
        await access_token(_FakeVault(_BASE_BLOB), "demo/oauth", refresh=False)


async def test_an_entry_without_oauth_state_has_no_access_token() -> None:
    with pytest.raises(NotOAuthStateError):
        await access_token(_FakeVault("s3cret"), "demo/api-key", refresh=False)
