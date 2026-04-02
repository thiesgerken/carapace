from __future__ import annotations

from pathlib import Path
from typing import Protocol

from loguru import logger

from carapace.models import CredentialBackendConfig, CredentialMetadata, CredentialsConfig


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


# ---------------------------------------------------------------------------
# Exposure filter
# ---------------------------------------------------------------------------


def is_exposed(identifier: str, cfg: CredentialBackendConfig) -> bool:
    """Check whether *identifier* passes the backend's exposure rules.

    Returns ``True`` when the credential should be visible; ``False`` otherwise.
    """
    if cfg.expose:
        return identifier in cfg.expose
    if cfg.hide:
        return identifier not in cfg.hide
    return True


# ---------------------------------------------------------------------------
# File backend
# ---------------------------------------------------------------------------


class FileVaultBackend:
    """Reads credentials from a ``.env``-format file (``key=value`` per line).

    The file is read once on construction and cached in memory.
    Lines starting with ``#`` and blank lines are ignored.
    """

    def __init__(self, *, name: str, path: Path, cfg: CredentialBackendConfig) -> None:
        self._name = name
        self._cfg = cfg
        self._secrets: dict[str, str] = {}
        self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning(f"Credential file {path} does not exist — backend '{self._name}' has no secrets")
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and value is not None:
                self._secrets[key] = value
        logger.info(f"File credential backend '{self._name}': loaded {len(self._secrets)} key(s) from {path}")

    def _vault_path(self, key: str) -> str:
        return f"{self._name}/{key}"

    async def fetch(self, identifier: str) -> str:
        if identifier not in self._secrets:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        if not is_exposed(identifier, self._cfg):
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        return self._secrets[identifier]

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        if identifier not in self._secrets:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        if not is_exposed(identifier, self._cfg):
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        return CredentialMetadata(vault_path=self._vault_path(identifier), name=identifier)

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        results: list[CredentialMetadata] = []
        for key in sorted(self._secrets):
            if not is_exposed(key, self._cfg):
                continue
            if query and query.lower() not in key.lower():
                continue
            results.append(CredentialMetadata(vault_path=self._vault_path(key), name=key))
        return results


# ---------------------------------------------------------------------------
# Registry — dispatches vault_path prefixes to backend instances
# ---------------------------------------------------------------------------


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

    @property
    def backend_names(self) -> list[str]:
        return list(self._backends)


def build_credential_registry(config: CredentialsConfig, data_dir: Path) -> CredentialRegistry:
    """Create a :class:`CredentialRegistry` from the ``credentials`` config block."""
    registry = CredentialRegistry()
    for name, cfg in config.backends.items():
        if cfg.type == "file":
            path = Path(cfg.path) if cfg.path else data_dir / "secrets.env"
            backend = FileVaultBackend(name=name, path=path, cfg=cfg)
            registry.register(name, backend)
        elif cfg.type == "vaultwarden":
            logger.info(f"Vaultwarden backend '{name}' configured but not yet implemented — skipping")
        else:
            logger.warning(f"Unknown credential backend type '{cfg.type}' for '{name}' — skipping")
    return registry
