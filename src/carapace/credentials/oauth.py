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
from loguru import logger

from ..models.credentials import CredentialRegistryProtocol, CredentialValueKind
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


def _json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_oauth_state(value: str) -> bool:
    """What `access_token` can refresh: strict, so it fails on anything it would get wrong."""
    parsed = _json_object(value)
    return parsed is not None and "token_url" in parsed and "refresh_token" in parsed


def _holds_refresh_token(value: str) -> bool:
    """What never goes to a sandbox: fail closed, also for near misses such as a Google `token_uri` file."""
    parsed = _json_object(value)
    return parsed is not None and "refresh_token" in parsed


async def fetch_for_sandbox(
    registry: CredentialRegistryProtocol, vault_path: str, kind: CredentialValueKind = "password"
) -> str:
    """A credential value bound for a sandbox. The only way one is fetched, so no path forgets the check.

    Raises ``OAuthStateRefusedError`` for an entry that holds a refresh token. Every representation of the
    entry carries it (a provider's JSON includes the password field), so the check reads the password value
    whatever kind the caller asked for.
    """
    password = await registry.fetch(vault_path)
    if _holds_refresh_token(password):
        raise OAuthStateRefusedError(vault_path)
    return password if kind == "password" else await registry.fetch(vault_path, kind)


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
    if not _is_oauth_state(value):
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
    # The provider's body stays in the server log: token endpoints echo request details in their errors,
    # and this message reaches the sandbox.
    if resp.status_code >= 400:
        logger.warning(f"OAuth refresh for {vault_path!r} failed ({resp.status_code}): {resp.text[:200]}")
        raise CredentialBackendError(
            f"OAuth refresh for {vault_path!r} failed ({resp.status_code}); "
            "the refresh token may be expired, re-provision the vault entry"
        )
    try:
        token = resp.json()
    except ValueError:
        token = None
    if not isinstance(token, dict) or not token.get("access_token"):
        logger.warning(f"OAuth refresh for {vault_path!r} answered without an access_token: {resp.text[:200]}")
        raise CredentialBackendError(f"OAuth refresh for {vault_path!r} answered without an access_token")
    refreshed = blob | {"access_token": token["access_token"]}
    if "expires_in" in token:
        refreshed["expires_at"] = int(time.time()) + int(token["expires_in"])
    if token.get("refresh_token"):
        refreshed["refresh_token"] = token["refresh_token"]
    return refreshed
