from __future__ import annotations

from typing import Protocol

from carapace.models import CredentialMetadata


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
