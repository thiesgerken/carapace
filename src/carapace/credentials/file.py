from __future__ import annotations

from pathlib import Path

from loguru import logger

from carapace.credentials.protocol import is_exposed
from carapace.models import CredentialBackendConfig, CredentialMetadata


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
            key, sep, value = line.partition("=")
            key = key.strip()
            if not sep:
                logger.warning(f"File backend '{self._name}': ignoring invalid line (no '='): {line!r}")
                continue
            if key:
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
