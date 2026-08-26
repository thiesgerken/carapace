from __future__ import annotations

import json

import httpx
from loguru import logger

from ..models.credentials import BitwardenCredentialBackendConfig, CredentialMetadata, CredentialValueKind
from .protocol import CredentialBackendError, is_exposed, require_exposed


class BitwardenBackend:
    """Talks to an external ``bw serve`` instance (companion container / Pod).

    Expects ``bw serve`` to already be running at *base_url* — carapace does not
    manage the process lifecycle.  In Docker Compose the ``bw serve`` container
    shares the network namespace via ``network_mode: service:carapace``; in
    Kubernetes the Helm chart runs it as a companion Pod behind an nginx proxy.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        cfg: BitwardenCredentialBackendConfig,
    ) -> None:
        self._name = name
        self._cfg = cfg
        self._base_url = base_url.rstrip("/")
        auth = None
        if cfg.basic_auth is not None:
            if cfg.basic_auth.password is None:
                raise ValueError(f"Bitwarden backend {name!r} basic_auth.password is required")
            auth = httpx.BasicAuth(cfg.basic_auth.username, cfg.basic_auth.password)
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0, auth=auth)

    async def _get(
        self,
        path: str,
        *,
        operation: str,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            if params is not None:
                return await self._client.get(path, params=params)
            return await self._client.get(path)
        except httpx.RequestError as exc:
            message = (
                f"Bitwarden credential backend {self._name!r} is unreachable at {self._base_url} "
                f"while trying to {operation}. Check that the `bw serve` sidecar or proxy is running, "
                "unlocked, and reachable from the Carapace server."
            )
            logger.exception(f"{message} Request target: {self._base_url}{path}")
            raise CredentialBackendError(message) from exc

    async def _put(self, path: str, *, json_body: dict, operation: str) -> httpx.Response:
        try:
            return await self._client.put(path, json=json_body)
        except httpx.RequestError as exc:
            message = (
                f"Bitwarden credential backend {self._name!r} is unreachable at {self._base_url} "
                f"while trying to {operation}. Check that the `bw serve` sidecar or proxy is running, "
                "unlocked, and reachable from the Carapace server."
            )
            logger.exception(f"{message} Request target: {self._base_url}{path}")
            raise CredentialBackendError(message) from exc

    def _vault_path(self, uuid: str) -> str:
        return f"{self._name}/{uuid}"

    async def fetch(self, identifier: str, kind: CredentialValueKind = "password") -> str:
        """Fetch a password, login name, or provider-specific JSON by item UUID."""
        require_exposed(identifier, self._cfg, self._name)
        object_type = {"password": "password", "login": "username", "json": "item"}[kind]
        resp = await self._get(f"/object/{object_type}/{identifier}", operation=f"fetch {kind}")
        if resp.status_code == 404:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return json.dumps(data, separators=(",", ":")) if kind == "json" else data.get("data", "")

    async def write(self, identifier: str, value: str) -> None:
        """Store *value* in the item's login password field (read-modify-write via bw serve)."""
        require_exposed(identifier, self._cfg, self._name)
        resp = await self._get(f"/object/item/{identifier}", operation="fetch item for update")
        if resp.status_code == 404:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp.raise_for_status()
        item = resp.json().get("data", {})
        login = item.get("login")
        if not isinstance(login, dict):
            raise CredentialBackendError(
                f"Bitwarden item {identifier!r} in backend '{self._name}' has no login field to store the secret in"
            )
        login["password"] = value
        put_resp = await self._put(f"/object/item/{identifier}", json_body=item, operation="update item")
        put_resp.raise_for_status()

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        """Fetch item metadata by UUID."""
        require_exposed(identifier, self._cfg, self._name)
        resp = await self._get(f"/object/item/{identifier}", operation="fetch item metadata")
        if resp.status_code == 404:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp.raise_for_status()
        item = resp.json().get("data", {})
        return CredentialMetadata(
            vault_path=self._vault_path(identifier),
            name=item.get("name", identifier),
        )

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        """List items, optionally filtered by search query."""
        params: dict[str, str] | None = {"search": query} if query else None
        resp = await self._get("/list/object/items", operation="list items", params=params)
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("data", [])
        results: list[CredentialMetadata] = []
        for item in items:
            item_id = item.get("id", "")
            if not is_exposed(item_id, self._cfg):
                continue
            results.append(
                CredentialMetadata(
                    vault_path=self._vault_path(item_id),
                    name=item.get("name", item_id),
                )
            )
        return results

    async def close(self) -> None:
        await self._client.aclose()
