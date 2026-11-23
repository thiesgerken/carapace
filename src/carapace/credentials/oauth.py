"""OAuth state blobs in the vault: Carapace refreshes them, a sandbox only ever gets the access token.

A blob is a JSON object with ``token_url``, ``client_id``, optional ``client_secret``, ``refresh_token``,
and optional ``access_token`` / ``expires_at`` (epoch seconds) / ``scope``. The one-time authorization that
produces the first refresh token happens out of band; see docs/skill-flakes.md, "OAuth".
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any

import httpx

from ..models.credentials import CredentialRegistryProtocol
from .protocol import CredentialBackendError

# Refresh this long before the access token expires, so a token is never handed out about to lapse.
_REFRESH_MARGIN_SECONDS = 60

# One refresh at a time per blob: providers that rotate refresh tokens invalidate the old one on use.
# ponytail: one lock per vault path for the process lifetime, bounded by the number of OAuth entries.
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class OAuthStateRefusedError(Exception):
    """The value is an OAuth state blob, whose refresh token must not leave the server."""

    def __init__(self, vault_path: str) -> None:
        super().__init__(
            f"{vault_path} holds OAuth state with a refresh token, which never enters the sandbox. "
            f"Use `ccred get {vault_path} --access-token` for a short-lived access token."
        )


class NotOAuthStateError(ValueError):
    """An access token was asked for an entry that holds no OAuth state."""

    def __init__(self, vault_path: str) -> None:
        super().__init__(f"{vault_path} holds no OAuth state (a JSON object with token_url and refresh_token)")


def is_oauth_state(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and "token_url" in parsed and "refresh_token" in parsed


async def refuse_oauth_state(registry: CredentialRegistryProtocol, vault_path: str) -> None:
    """Raise ``OAuthStateRefusedError`` if *vault_path* holds an OAuth state blob.

    Every representation of the entry carries the blob (a provider's JSON includes the password field),
    so the check looks at the password value whatever kind the caller asked for.
    """
    if is_oauth_state(await registry.fetch(vault_path)):
        raise OAuthStateRefusedError(vault_path)


async def access_token(registry: CredentialRegistryProtocol, vault_path: str, *, refresh: bool) -> str:
    """The blob's access token, refreshed when it is missing, about to expire, or *refresh* forces it."""
    async with _locks[vault_path]:
        blob = _parse(vault_path, await registry.fetch(vault_path))
        if refresh or _expiring(blob):
            blob = await _refreshed(vault_path, blob)
            await registry.write(vault_path, json.dumps(blob, separators=(",", ":")))
        if not blob.get("access_token"):
            raise CredentialBackendError(f"OAuth state at {vault_path!r} has no access_token after refresh")
        return blob["access_token"]


def _parse(vault_path: str, value: str) -> dict[str, Any]:
    if not is_oauth_state(value):
        raise NotOAuthStateError(vault_path)
    return json.loads(value)


def _expiring(blob: dict[str, Any]) -> bool:
    if not blob.get("access_token"):
        return True
    expires_at = blob.get("expires_at")
    return expires_at is None or time.time() >= float(expires_at) - _REFRESH_MARGIN_SECONDS


async def _refreshed(vault_path: str, blob: dict[str, Any]) -> dict[str, Any]:
    for required in ("token_url", "client_id", "refresh_token"):
        if not blob.get(required):
            raise CredentialBackendError(f"OAuth state at {vault_path!r} is missing '{required}'")
    data = {"grant_type": "refresh_token", "refresh_token": blob["refresh_token"], "client_id": blob["client_id"]}
    for optional in ("client_secret", "scope"):
        if blob.get(optional):
            data[optional] = blob[optional]
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(blob["token_url"], data=data)
    if resp.status_code >= 400:
        raise CredentialBackendError(
            f"OAuth refresh for {vault_path!r} failed ({resp.status_code}); "
            "the refresh token may be expired, re-provision the vault entry. "
            f"Response: {resp.text[:200]}"
        )
    token = resp.json()
    refreshed = blob | {"access_token": token["access_token"]}
    if "expires_in" in token:
        refreshed["expires_at"] = int(time.time()) + int(token["expires_in"])
    if token.get("refresh_token"):
        refreshed["refresh_token"] = token["refresh_token"]
    return refreshed
