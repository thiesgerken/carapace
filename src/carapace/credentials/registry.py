from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import assert_never

from loguru import logger

from ..models.credentials import (
    BitwardenCredentialBackendConfig,
    CredentialMetadata,
    CredentialRegistryProtocol,
    CredentialsConfig,
    CredentialValueKind,
    FileCredentialBackendConfig,
)
from .bitwarden import BitwardenBackend
from .file import FileVaultBackend
from .protocol import UnsupportedCredentialValueKindError, VaultBackend

FILE_CREDENTIAL_BACKEND_ENV = "CARAPACE_ALLOW_FILE_CREDENTIAL_BACKEND"
_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_FALSE_ENV_VALUES = {"", "0", "false", "no", "off"}


def file_credential_backend_allowed_from_env() -> bool:
    raw = os.environ.get(FILE_CREDENTIAL_BACKEND_ENV, "")
    normalized = raw.strip().lower()
    if normalized in _TRUE_ENV_VALUES:
        return True
    if normalized in _FALSE_ENV_VALUES:
        return False
    raise ValueError(f"{FILE_CREDENTIAL_BACKEND_ENV} must be a boolean value (true/false, yes/no, on/off, or 1/0)")


class UnknownBackendError(KeyError):
    """Vault path names a backend that is not registered (unknown or disabled).

    Distinct from a plain ``KeyError`` (backend exists but has no such identifier),
    so callers can tell "backend not configured" apart from "secret missing".
    """


class CredentialRegistry:
    """Routes ``<backend-name>/<identifier>`` vault paths to the correct backend."""

    def __init__(self) -> None:
        self._backends: dict[str, VaultBackend] = {}

    def register(self, name: str, backend: VaultBackend) -> None:
        self._backends[name] = backend

    def _resolve(self, vault_path: str) -> tuple[VaultBackend, str]:
        """Split *vault_path* into backend + identifier and return both.

        Raises ``UnknownBackendError`` if the backend prefix is unknown or disabled.
        """
        prefix, _, identifier = vault_path.partition("/")
        if not identifier:
            raise UnknownBackendError(f"Invalid vault_path (missing backend prefix): {vault_path!r}")
        backend = self._backends.get(prefix)
        if backend is None:
            raise UnknownBackendError(f"Unknown credential backend: {prefix!r}")
        return backend, identifier

    def require_supported(self, vault_path: str, kind: CredentialValueKind) -> None:
        backend, _ = self._resolve(vault_path)
        if kind not in backend.supported_kinds:
            name = vault_path.partition("/")[0]
            raise UnsupportedCredentialValueKindError(
                f"Credential backend '{name}' does not support {kind!r} retrieval"
            )

    async def fetch(self, vault_path: str, kind: CredentialValueKind = "password") -> str:
        backend, identifier = self._resolve(vault_path)
        return await backend.fetch(identifier) if kind == "password" else await backend.fetch(identifier, kind)

    async def write(self, vault_path: str, value: str) -> None:
        backend, identifier = self._resolve(vault_path)
        await backend.write(identifier, value)

    async def fetch_metadata(self, vault_path: str) -> CredentialMetadata:
        backend, identifier = self._resolve(vault_path)
        return await backend.fetch_metadata(identifier)

    @property
    def backend_names(self) -> list[str]:
        return list(self._backends)

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        results: list[CredentialMetadata] = []
        for backend in self._backends.values():
            results.extend(await backend.list(query))
        return results

    async def close(self) -> None:
        """Close all managed credential backends."""
        for backend in self._backends.values():
            await backend.close()


class SessionCredentialRegistry:
    """Credential registry view bound to one session owner."""

    def __init__(
        self,
        *,
        session_id: str,
        resolve_registry: Callable[[str], Awaitable[CredentialRegistryProtocol]],
    ) -> None:
        self._session_id = session_id
        self._resolve_registry = resolve_registry

    async def _registry(self) -> CredentialRegistryProtocol:
        return await self._resolve_registry(self._session_id)

    async def fetch(self, vault_path: str, kind: CredentialValueKind = "password") -> str:
        registry = await self._registry()
        return await registry.fetch(vault_path) if kind == "password" else await registry.fetch(vault_path, kind)

    async def write(self, vault_path: str, value: str) -> None:
        await (await self._registry()).write(vault_path, value)

    async def fetch_metadata(self, vault_path: str) -> CredentialMetadata:
        return await (await self._registry()).fetch_metadata(vault_path)

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        return await (await self._registry()).list(query)


async def build_credential_registry(
    config: CredentialsConfig,
    data_dir: Path,
    *,
    file_backend_allowed: bool | None = None,
) -> CredentialRegistry:
    """Create a :class:`CredentialRegistry` from the ``credentials`` config block."""
    is_file_backend_allowed = (
        file_credential_backend_allowed_from_env() if file_backend_allowed is None else file_backend_allowed
    )
    registry = CredentialRegistry()
    for name, cfg in config.backends.items():
        match cfg:
            case FileCredentialBackendConfig():
                if not is_file_backend_allowed:
                    logger.warning(
                        f"File credential backend '{name}' is disabled; set {FILE_CREDENTIAL_BACKEND_ENV}=true "
                        "only when credential backend configs are managed by trusted users"
                    )
                    continue
                if cfg.path:
                    raw = Path(cfg.path)
                    path = raw if raw.is_absolute() else data_dir / raw
                else:
                    path = data_dir / "secrets.env"
                registry.register(name, FileVaultBackend(name=name, path=path, cfg=cfg))
            case BitwardenCredentialBackendConfig():
                registry.register(name, BitwardenBackend(name=name, base_url=cfg.url, cfg=cfg))
                logger.info(f"Bitwarden backend '{name}' configured at {cfg.url}")
            case _:
                assert_never(cfg)
    return registry
