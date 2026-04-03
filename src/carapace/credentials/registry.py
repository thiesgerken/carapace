from __future__ import annotations

from pathlib import Path

from loguru import logger

from carapace.credentials.file import FileVaultBackend
from carapace.credentials.protocol import VaultBackend
from carapace.credentials.vaultwarden import BwServeManager, VaultwardenBackend
from carapace.models import CredentialMetadata, CredentialsConfig


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


async def build_credential_registry(config: CredentialsConfig, data_dir: Path) -> CredentialRegistry:
    """Create a :class:`CredentialRegistry` from the ``credentials`` config block."""
    registry = CredentialRegistry()
    for name, cfg in config.backends.items():
        if cfg.type == "file":
            path = Path(cfg.path) if cfg.path else data_dir / "secrets.env"
            backend = FileVaultBackend(name=name, path=path, cfg=cfg)
            registry.register(name, backend)
        elif cfg.type == "vaultwarden":
            bw_serve = BwServeManager(
                server_url=cfg.url,
                port=cfg.bw_serve_port,
            )
            try:
                await bw_serve.start()
            except Exception as exc:
                logger.error(f"Failed to start bw serve for backend '{name}': {exc}")
                continue
            backend = VaultwardenBackend(name=name, bw_serve=bw_serve, cfg=cfg)
            registry.register(name, backend)
        else:
            logger.warning(f"Unknown credential backend type '{cfg.type}' for '{name}' — skipping")
    return registry


async def shutdown_credential_registry(registry: CredentialRegistry) -> None:
    """Shut down all managed backends (stop bw serve processes, close clients)."""
    for name in registry.backend_names:
        backend = registry._backends.get(name)
        if isinstance(backend, VaultwardenBackend):
            await backend.close()
            await backend._bw_serve.stop()
