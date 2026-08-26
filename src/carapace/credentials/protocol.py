from __future__ import annotations

from typing import Protocol

from ..models.credentials import (
    BitwardenCredentialBackendConfig,
    CredentialMetadata,
    CredentialValueKind,
    FileCredentialBackendConfig,
)


class CredentialBackendError(RuntimeError):
    """Credential backend failure with a message safe to show to users."""


class UnsupportedCredentialValueKindError(ValueError):
    """The selected backend cannot return the requested credential representation."""


class VaultBackend(Protocol):
    """Abstract interface for credential storage backends.

    Implementations fetch secrets from a password manager (file, Bitwarden, …)
    and return metadata for listing/searching.
    """

    async def fetch(self, identifier: str, kind: CredentialValueKind = "password") -> str:
        """Return the selected representation of *identifier*.

        Raises ``KeyError`` if the identifier does not exist.
        """
        ...

    async def write(self, identifier: str, value: str) -> None:
        """Overwrite the secret value for an existing *identifier*.

        Used for token rotation (e.g. persisting a refreshed OAuth access token).
        Raises ``KeyError`` if the identifier does not exist and
        ``CredentialBackendError`` if the backend cannot store the value.
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

    async def close(self) -> None:
        """Release backend resources."""
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


def require_exposed(
    identifier: str,
    cfg: FileCredentialBackendConfig | BitwardenCredentialBackendConfig,
    backend_name: str,
) -> None:
    """Raise ``KeyError`` if *identifier* is hidden by exposure rules."""
    if not is_exposed(identifier, cfg):
        raise KeyError(f"Credential '{identifier}' not found in backend '{backend_name}'")
