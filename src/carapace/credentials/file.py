from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from loguru import logger

from carapace.credentials.protocol import is_exposed, require_exposed
from carapace.models import CredentialMetadata, FileCredentialBackendConfig


@dataclass(slots=True)
class _Secret:
    name: str
    value: str


class FileVaultBackend:
    """Reads credentials from a ``.env`` or YAML file.

    **``.env`` format** (``key=value`` per line, ``#`` comments)::

        gmail=myapppassword
        github-token=ghp_xxx

    **YAML format** (list of entries with ``id``, ``name``, ``value``)::

        - id: gmail
          name: Gmail App Password
          value: myapppassword
        - id: github-token
          name: GitHub API Token
          value: ghp_xxx

    The file is read once on construction and cached in memory.
    Format is auto-detected from the file extension (``.yaml``/``.yml`` → YAML,
    everything else → ``.env``).
    """

    def __init__(self, *, name: str, path: Path, cfg: FileCredentialBackendConfig) -> None:
        self._name = name
        self._cfg = cfg
        self._secrets: dict[str, _Secret] = {}
        self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning(f"Credential file {path} does not exist — backend '{self._name}' has no secrets")
            return
        if path.suffix in (".yaml", ".yml"):
            self._load_yaml(path)
        else:
            self._load_env(path)
        logger.info(f"File credential backend '{self._name}': loaded {len(self._secrets)} key(s) from {path}")

    def _load_env(self, path: Path) -> None:
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
                self._secrets[key] = _Secret(name=key, value=value)

    def _load_yaml(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, list):
            logger.warning(f"File backend '{self._name}': YAML file must contain a list of entries")
            return
        for entry in data:
            if not isinstance(entry, dict):
                logger.warning(f"File backend '{self._name}': skipping non-dict YAML entry: {entry!r}")
                continue
            entry_id = str(entry.get("id", "")).strip()
            if not entry_id:
                logger.warning(f"File backend '{self._name}': skipping YAML entry without 'id'")
                continue
            value = str(entry.get("value", ""))
            name = str(entry.get("name", entry_id))
            self._secrets[entry_id] = _Secret(name=name, value=value)

    def _vault_path(self, key: str) -> str:
        return f"{self._name}/{key}"

    def _require(self, identifier: str) -> None:
        if identifier not in self._secrets:
            raise KeyError(f"Credential '{identifier}' not found in backend '{self._name}'")
        require_exposed(identifier, self._cfg, self._name)

    async def fetch(self, identifier: str) -> str:
        self._require(identifier)
        return self._secrets[identifier].value

    async def fetch_metadata(self, identifier: str) -> CredentialMetadata:
        self._require(identifier)
        secret = self._secrets[identifier]
        return CredentialMetadata(vault_path=self._vault_path(identifier), name=secret.name)

    async def list(self, query: str = "") -> list[CredentialMetadata]:
        results: list[CredentialMetadata] = []
        for key in sorted(self._secrets):
            if not is_exposed(key, self._cfg):
                continue
            secret = self._secrets[key]
            if query:
                q = query.lower()
                if q not in key.lower() and q not in secret.name.lower():
                    continue
            results.append(CredentialMetadata(vault_path=self._vault_path(key), name=secret.name))
        return results

    async def close(self) -> None:
        return
