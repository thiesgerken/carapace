"""OAuth state blobs: Carapace refreshes them and hands out only the access token."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from carapace.agent.tools import _cache_skill_credentials
from carapace.credentials.oauth import NotOAuthStateError, OAuthStateRefusedError, access_token, fetch_for_sandbox
from carapace.credentials.protocol import CredentialBackendError
from carapace.models.credentials import CredentialMetadata
from carapace.models.skills import SkillCredentialDecl

_BASE_BLOB = {"token_url": "https://issuer.example.com/token", "client_id": "cid", "refresh_token": "rt"}


class _FakeVault:
    def __init__(self, value: dict | str):
        self.value = value if isinstance(value, str) else json.dumps(value)
        self.written: str | None = None

    async def fetch(self, vault_path: str, kind: str = "password") -> str:
        return self.value if kind == "password" else f"{kind} of {vault_path}"

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


@pytest.mark.parametrize(
    "value",
    [
        _BASE_BLOB,
        # A near miss is refused too: a Google authorized_user file names its endpoint token_uri.
        {"token_uri": "https://oauth2.example.com/token", "client_id": "cid", "refresh_token": "rt"},
        {"refresh_token": "rt"},
    ],
)
@pytest.mark.parametrize("kind", ["password", "json", "login"])
async def test_anything_with_a_refresh_token_is_refused_in_every_kind(value: dict, kind: str) -> None:
    with pytest.raises(OAuthStateRefusedError, match="--access-token"):
        await fetch_for_sandbox(_FakeVault(value), "demo/oauth", kind)  # type: ignore[arg-type]


async def test_other_values_go_to_the_sandbox_in_the_kind_asked_for() -> None:
    vault = _FakeVault('{"user": "a", "password": "b"}')

    assert await fetch_for_sandbox(vault, "demo/login") == '{"user": "a", "password": "b"}'
    assert await fetch_for_sandbox(vault, "demo/login", "json") == "json of demo/login"


async def test_use_skill_never_caches_an_oauth_entry() -> None:
    ctx = MagicMock()
    ctx.deps.credential_registry = _FakeVault(_BASE_BLOB)
    ctx.deps.credential_registry.fetch_metadata = AsyncMock(
        return_value=CredentialMetadata(vault_path="demo/oauth", name="OAuth", description="")
    )
    ctx.deps.append_session_events = None
    decl = SkillCredentialDecl(vault_path="demo/oauth", description="OAuth", env_var="TOKEN")

    message, _ = await _cache_skill_credentials(ctx, [decl], "tracker")

    assert "refresh token" in message
    ctx.deps.sandbox.cache_credential.assert_not_called()


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


async def test_a_failed_refresh_raises_without_the_providers_answer() -> None:
    endpoint, _ = _token_endpoint(status=400, payload={"error": "invalid_grant", "client_id": "cid-echoed"})

    with endpoint, pytest.raises(CredentialBackendError, match="re-provision") as raised:
        await access_token(_FakeVault(_BASE_BLOB), "demo/oauth", refresh=False)
    assert "cid-echoed" not in str(raised.value)


async def test_a_refresh_answer_without_an_access_token_raises() -> None:
    endpoint, _ = _token_endpoint(payload={"token_type": "bearer"})

    with endpoint, pytest.raises(CredentialBackendError, match="without an access_token"):
        await access_token(_FakeVault(_BASE_BLOB), "demo/oauth", refresh=False)


async def test_an_entry_without_oauth_state_has_no_access_token() -> None:
    with pytest.raises(NotOAuthStateError):
        await access_token(_FakeVault("s3cret"), "demo/api-key", refresh=False)


async def test_a_near_miss_is_refused_but_cannot_be_refreshed_either() -> None:
    vault = _FakeVault({"token_uri": "https://oauth2.example.com/token", "client_id": "cid", "refresh_token": "rt"})

    with pytest.raises(NotOAuthStateError):
        await access_token(vault, "demo/google", refresh=False)
