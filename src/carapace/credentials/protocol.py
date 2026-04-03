from __future__ import annotations

from typing import Protocol

from carapace.models import BitwardenCredentialBackendConfig, CredentialMetadata, FileCredentialBackendConfig


class VaultBackend(Protocol):
    """Abstract interface for credential storage backends.

    Implementations fetch secrets from a password manager (file, Bitwarden, …)
    and return metadata for listing/searching.
    """

    async def fetch(self, identifier: str) -> str:
        """Return the raw secret value for *identifier*.

        Raises ``KeyError`` if the identifier does not exist.
        """
        ...

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        """Return metadata (vault_path, name, description) for *identifier*.

        Raises ``KeyError`` if the identifier does not exist.
        """
        ...

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        """Return metadata for all credentials matching *query*.

        An empty *query* returns everything the backend exposes.
        """
        ...


def is_exposed(identifier: str, cfg: FileCredentialBackendConfig | BitwardenCredentialBackendConfig) -> bool:
    """Check whether *identifier* passes the backend's exposure rules.

    Returns ``True`` when the credential should be visible; ``False`` otherwise.
    """
    if cfg.expose:
        return identifier in cfg.expose
    if cfg.hide:
        return identifier not in cfg.hide
    return True
