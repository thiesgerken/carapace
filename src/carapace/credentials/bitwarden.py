from __future__ import annotations

import httpx

from carapace.credentials.protocol import is_exposed, require_exposed
from carapace.models import BitwardenCredentialBackendConfig, CredentialMetadata


class BitwardenBackend:
    """Talks to an external ``bw serve`` instance (sidecar / companion container).

    Expects ``bw serve`` to already be running at *base_url* — Carapace does not
    manage the process lifecycle.  In Docker Compose the ``bw serve`` container
    shares the network namespace via ``network_mode: service:carapace``; in
    Kubernetes it runs as a sidecar in the same Pod.
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
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    def _vault_path(self, uuid: str) -> str:
        return f"{self._name}/{uuid}"

    async def fetch(self, identifier: str) -> str:
        """Fetch the password for a Bitwarden item by UUID."""
        require_exposed(identifier, self._cfg, self._name)
        resp = await self._client.get(f"/object/password/{identifier}")
        if resp.status_code == 404:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("data", "")

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        """Fetch item metadata by UUID."""
        require_exposed(identifier, self._cfg, self._name)
        resp = await self._client.get(f"/object/item/{identifier}")
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
        params: dict[str, str] = {}
        if query:
            params["search"] = query
        resp = await self._client.get("/list/object/items", params=params)
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
