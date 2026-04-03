from __future__ import annotations

from pathlib import Path
from typing import assert_never

from loguru import logger

from carapace.credentials.bitwarden import BitwardenBackend
from carapace.credentials.file import FileVaultBackend
from carapace.credentials.protocol import VaultBackend
from carapace.models import (
    BitwardenCredentialBackendConfig,
    CredentialMetadata,
    CredentialsConfig,
    FileCredentialBackendConfig,
)


class CredentialRegistry:
    """Routes ``<backend-name>/<identifier>`` vault paths to the correct backend."""

    def __init__(self) -> None:
        self._backends: dict[str, VaultBackend] = {}

    def register(self, name: str, backend: VaultBackend) -> None:
        self._backends[name] = backend

    def _resolve(self, vault_path: str) -> tuple[VaultBackend, str]:
        """Split *vault_path* into backend + identifier and return both.

        Raises ``KeyError`` if the backend prefix is unknown.
        """
        prefix, _, identifier = vault_path.partition("/")
        if not identifier:
            raise KeyError(f"Invalid vault_path (missing backend prefix): {vault_path!r}")
        backend = self._backends.get(prefix)
        if backend is None:
            raise KeyError(f"Unknown credential backend: {prefix!r}")
        return backend, identifier

    async def fetch(self, vault_path: str) -> str:
        backend, identifier = self._resolve(vault_path)
        return await backend.fetch(identifier)

    async def fetch_metadata(self, vault_path: str) -> CredentialMetadata:
        backend, identifier = self._resolve(vault_path)
        return await backend.fetch_metadata(identifier)

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        results: list[CredentialMetadata] = []
        for backend in self._backends.values():
            results.extend(await backend.list(query))
        return results

    async def close(self) -> None:
        """Close all managed credential backends."""
        for backend in self._backends.values():
            await backend.close()

    @property
    def backend_names(self) -> list[str]:
        return list(self._backends)


async def build_credential_registry(config: CredentialsConfig, data_dir: Path) -> CredentialRegistry:
    """Create a :class:`CredentialRegistry` from the ``credentials`` config block."""
    registry = CredentialRegistry()
    for name, cfg in config.backends.items():
        match cfg:
            case FileCredentialBackendConfig():
                path = Path(cfg.path) if cfg.path else data_dir / "secrets.env"
                registry.register(name, FileVaultBackend(name=name, path=path, cfg=cfg))
            case BitwardenCredentialBackendConfig():
                registry.register(name, BitwardenBackend(name=name, base_url=cfg.url, cfg=cfg))
                logger.info(f"Bitwarden backend '{name}' configured at {cfg.url}")
            case _:
                assert_never(cfg)
    return registry
